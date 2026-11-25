"""Owner demonstration API. Run behind the authenticated Codex Cloud preview."""
import argparse
import json
import math
import os
import re
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from clipflow.auth import LoginUnavailable, OwnerAuth, session_header
from clipflow.campaigns import Campaigns, Conflict
from clipflow.planner import Plans, planner_budget
from clipflow.queue import Limit, Queue
from clipflow.r2 import MEDIA_TYPES, PrivateMedia
from clipflow.render import MAX_OUTPUT_BYTES
from clipflow.transcription import enabled as transcription_enabled

MAX_UPLOAD = 25 * 1024 * 1024
QUOTA = 250 * 1024 * 1024
DEMO_RESERVATION = 1000
DEMO_MONTHLY_BUDGET = 10000
WEB = Path(__file__).with_name('ui')


class OwnerAPI(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        policy = "default-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'none'"
        if self.server.media:
            policy += f"; connect-src 'self' {self.server.media.origin}; media-src 'self' {self.server.media.origin}"
        self.send_header('Content-Security-Policy', policy)
        super().end_headers()

    def reply(self, status, body, mime='application/json', headers=()):
        if mime == 'application/json':
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def authenticate(self, path):
        auth = self.server.auth
        if not auth or auth.authenticated(self.headers.get('Cookie', '')):
            return True
        if path == '/':
            self.reply(303, b'', 'text/plain', headers=[('Location', '/signin')])
        else:
            self.reply(401, {'error': 'Sign in to access Owner Studio'})
        return False

    def session_request(self):
        auth = self.server.auth
        if auth is None:
            return self.reply(404, {'error': 'Sign-in unavailable'})
        if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin'):
            return self.reply(403, {'error': 'Cross-origin request refused'})
        if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
            return self.reply(415, {'error': 'JSON required'})
        if self.path == '/api/session/logout':
            return self.reply(200, {'ok': True}, headers=[('Set-Cookie', session_header('', 0))])
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 4096:
                raise ValueError()
            payload = json.loads(self.rfile.read(size))
            email, password = payload['email'], payload['password']
            if not (isinstance(email, str) and 0 < len(email) <= 254 and
                    isinstance(password, str) and 0 < len(password) <= 256):
                raise ValueError()
        except (TypeError, KeyError, ValueError, TimeoutError):
            return self.reply(400, {'error': 'Enter your email and password'})
        if not auth.allow_attempt():
            return self.reply(429, {'error': 'Too many attempts. Try again in a minute'})
        try:
            result = auth.login(email, password)
        except LoginUnavailable:
            return self.reply(503, {'error': 'Sign-in is temporarily unavailable'})
        if result is None:
            return self.reply(401, {'error': 'Check your sign-in details'})
        return self.reply(200, {'ok': True}, headers=[('Set-Cookie', session_header(*result))])

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == '/healthz':
            return self.reply(200, {'ok': True})
        if url.path not in ('/signin', '/signin.js', '/app.css') and not self.authenticate(url.path):
            return
        if url.path == '/api/session':
            return self.reply(200, {'sign_out': self.server.auth is not None,
                                    'automatic_captions': self.server.transcription_enabled,
                                    'direct_upload': self.server.media is not None,
                                    'ai_planner': planner_budget() > 0})
        files = {'/signin': ('signin.html', 'text/html'), '/signin.js': ('signin.js', 'text/javascript'),
                 '/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                 '/app.css': ('app.css', 'text/css'),
                 '/campaigns.js': ('campaigns.js', 'text/javascript')}
        if url.path in files:
            name, mime = files[url.path]
            return self.reply(200, (WEB / name).read_bytes(), mime + '; charset=utf-8')
        if url.path == '/api/plans':
            return self.reply(200, self.server.plans.list())
        if url.path == '/api/campaigns':
            return self.reply(200, self.server.campaigns.snapshot())
        if url.path == '/api/jobs':
            jobs = self.server.queue.all()
            return self.reply(200, [{k: v for k, v in job.items() if k != 'lease_token'} for job in jobs])
        match = re.fullmatch(r'/media/([0-9a-f]{32})', url.path)
        if match:
            job = self.server.queue.get(match[1])
            if job and job['state'] == 'ready':
                download = parse_qs(url.query).get('download') == ['1']
                spec = json.loads(job['spec'])
                if spec.get('storage') == 'r2':
                    if not self.server.media:
                        return self.reply(503, {'error': 'Private storage unavailable'})
                    try:
                        location = self.server.media.sign_preview(
                            self.server.owner_id, job['id'], download=download, revision=job['lease_token'])
                    except Exception:
                        return self.reply(503, {'error': 'Could not open the private clip'})
                    return self.reply(307, b'', 'text/plain', headers=[('Location', location)])
                path = self.server.root / job['id'] / (job['lease_token'] + '.mp4')
                if path.is_file():
                    return self.stream(path, download)
        self.reply(404, {'error': 'Item unavailable'})

    def stream(self, path, download):
        size = path.stat().st_size
        start, end = 0, size - 1
        requested = self.headers.get('Range')
        if requested:
            match = re.fullmatch(r'bytes=(\d{0,20})-(\d{0,20})', requested)
            if match and match[1]:
                start = int(match[1])
                if match[2]:
                    end = min(end, int(match[2]))
            elif match and match[2]:
                start = max(0, size - int(match[2]))
            else:
                start = size
            if start > end:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.end_headers()
                return
        self.send_response(206 if requested else 200)
        self.send_header('Content-Type', 'video/mp4')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        if requested:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="clipflow.mp4"')
        self.end_headers()
        with path.open('rb') as media:
            media.seek(start)
            remaining = end - start + 1
            while remaining:
                block = media.read(min(remaining, 65536))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def campaign_request(self):
        if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin'):
            return self.reply(403, {'error': 'Cross-origin request refused'})
        if self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding'):
            return self.reply(415, {'error': 'JSON required'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8192:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('Expected an object')
            if self.path == '/api/plans':
                return self.reply(202, {'id': self.server.plans.request(data.get('goal'), planner_budget())})
            if self.path == '/api/campaigns':
                return self.reply(201, {'id': self.server.campaigns.create(data)})
            match = re.fullmatch(r'/api/campaigns/([0-9a-f]{32})/(approve|pause|resume|stop|schedule)', self.path)
            post = re.fullmatch(r'/api/manual-posts/([0-9a-f]{32})/handoff', self.path)
            if post:
                self.server.campaigns.complete(post[1])
            elif not match:
                return self.reply(404, {'error': 'Item unavailable'})
            elif match[2] == 'schedule':
                self.server.campaigns.schedule(match[1], data)
            else:
                self.server.campaigns.transition(match[1], match[2])
            return self.reply(200, {'ok': True})
        except Limit as error:
            return self.reply(429, {'error': str(error)})
        except Conflict as error:
            return self.reply(409, {'error': str(error)})
        except (ValueError, TimeoutError) as error:
            return self.reply(400, {'error': str(error)})

    def do_POST(self):
        if self.path in ('/api/session', '/api/session/logout'):
            return self.session_request()
        if not self.authenticate(self.path):
            return
        if self.path == '/api/plans' or self.path.startswith(('/api/campaigns', '/api/manual-posts')):
            return self.campaign_request()
        complete = re.fullmatch(r'/api/uploads/([0-9a-f]{32})/complete', self.path)
        if complete:
            return self.complete_upload(complete[1])
        direct = self.path == '/api/uploads'
        if not direct and self.path != '/api/jobs':
            return self.reply(404, {'error': 'Item unavailable'})
        # Cross-site forms cannot produce the required custom headers.
        if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin'):
            return self.reply(403, {'error': 'Cross-origin upload refused'})
        if direct != bool(self.server.media):
            return self.reply(409, {'error': 'Reload the studio to use the configured upload method'})
        mime = self.headers.get('X-Upload-Mime') if direct else self.headers.get_content_type()
        if self.headers.get('Transfer-Encoding') or mime not in MEDIA_TYPES:
            return self.reply(415, {'error': 'Upload an MP4, MOV or WebM video'})
        key = self.headers.get('Idempotency-Key', '')
        if not re.fullmatch(r'[0-9a-f-]{36}', key):
            return self.reply(400, {'error': 'Missing valid request key'})
        try:
            size = int(self.headers.get('X-Upload-Size' if direct else 'Content-Length', '0'))
            name = unquote(self.headers.get('X-Clip-Name', 'Source video'))[:120]
            start, end = (float(self.headers[f'X-Clip-{n}']) for n in ('Start', 'End'))
            cues = json.loads(unquote(self.headers.get('X-Clip-Cues', '[]')))
            if not (0 < size <= MAX_UPLOAD and math.isfinite(start) and math.isfinite(end)
                    and 0 <= start < end <= 1800 and 1 <= end - start <= 60
                    and isinstance(cues, list) and len(cues) <= 30):
                raise ValueError()
            for cue in cues:
                if not (isinstance(cue, dict) and set(cue) == {'start', 'end', 'text'} and 0 <= cue['start'] < cue['end'] <= 1800
                        and isinstance(cue['text'], str) and 0 < len(cue['text']) <= 160):
                    raise ValueError()
        except (TypeError, ValueError, KeyError):
            return self.reply(400, {'error': 'Check the 25 MiB upload limit, 1–60 second clip and timestamped captions'})
        automatic = self.headers.get('X-Clip-Auto-Captions') == '1'
        if automatic and (not self.server.transcription_enabled or cues):
            return self.reply(409, {'error': 'Automatic captions require an enabled provider and no manual caption'})
        data = {'start': start, 'end': end, 'cues': cues, 'size': size, 'automatic_captions': automatic}
        if direct:
            data.update(storage='r2', mime=mime)
        spec = json.dumps(data)
        try:
            # Reserve source plus room for two lease attempts and stale output.
            storage = size + 2 * MAX_OUTPUT_BYTES
            job_id, created = self.server.queue.reserve(key, name, spec, storage, cost=DEMO_RESERVATION,
                                                        budget=DEMO_MONTHLY_BUDGET, quota=QUOTA)
        except Limit as error:
            return self.reply(429, {'error': str(error)})
        if direct:
            job = self.server.queue.get(job_id)
            if not job:
                return self.reply(409, {'error': 'Upload reservation expired'})
            if job['state'] != 'uploading':
                return self.reply(202, {'id': job_id})
            if job['spec'] != spec:
                return self.reply(409, {'error': 'This upload key was already used for different input'})
            try:
                signed = self.server.media.sign_upload(self.server.owner_id, job_id, mime=mime, size=size)
            except Exception:
                return self.reply(503, {'error': 'Could not sign private upload'})
            return self.reply(201, {'id': job_id, **signed})
        if created:
            directory = self.server.root / job_id
            try:
                directory.mkdir(mode=0o700)
                with (directory / 'source').open('xb') as source:
                    remaining = size
                    while remaining:
                        block = self.rfile.read(min(remaining, 65536))
                        if not block:
                            raise OSError('Incomplete upload')
                        source.write(block)
                        remaining -= len(block)
                self.server.queue.uploaded(job_id)
            except OSError:
                shutil.rmtree(directory, ignore_errors=True)
                self.server.queue.abandon(job_id)
                return self.reply(400, {'error': 'Upload was interrupted'})
        self.reply(202, {'id': job_id})

    def complete_upload(self, job_id):
        if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin'):
            return self.reply(403, {'error': 'Cross-origin request refused'})
        if not self.server.media:
            return self.reply(503, {'error': 'Private storage unavailable'})
        job = self.server.queue.get(job_id)
        if not job:
            return self.reply(404, {'error': 'Upload unavailable'})
        data = json.loads(job['spec'])
        if data.get('storage') != 'r2':
            return self.reply(409, {'error': 'This job was created for local storage'})
        if job['state'] == 'uploading':
            try:
                data['etag'] = self.server.media.verify_upload(
                    self.server.owner_id, job_id, mime=data['mime'], size=data['size'])
            except Exception:
                return self.reply(409, {'error': 'The private upload is missing or does not match the reservation'})
            self.server.queue.uploaded(job_id, json.dumps(data))
        return self.reply(202, {'id': job_id})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', default=3000, type=int)
    parser.add_argument('--authenticated-gateway', action='store_true')
    parser.add_argument('--application-auth', action='store_true')
    args = parser.parse_args()
    if args.bind != '127.0.0.1' and not (args.authenticated_gateway or args.application_auth):
        parser.error('Non-loopback access requires an authenticated gateway')
    args.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.bind, args.port), OwnerAPI)
    server.auth = OwnerAuth.configured()
    if args.application_auth and not server.auth:
        parser.error('Application authentication requires all Supabase owner settings')
    server.transcription_enabled = transcription_enabled()
    server.media = PrivateMedia.configured()
    server.owner_id = server.auth.owner if server.auth else None
    if server.media and not server.auth:
        parser.error('Private cloud storage requires a configured owner identity')
    server.root = args.root.resolve()
    server.queue = Queue(server.root / 'jobs.sqlite3')
    if server.auth:
        server.queue.bind_owner(server.owner_id)
    server.campaigns = Campaigns(server.queue)
    server.plans = Plans(server.queue)
    server.serve_forever()


if __name__ == '__main__':
    main()
