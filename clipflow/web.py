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

from clipflow.auth import LoginUnavailable, OwnerAuth, PreviewAuth, session_header
from clipflow.batch import BATCH_OUTPUT_BYTES, MAX_BATCH, MAX_TRANSCRIPT, PALETTES, direct_source_url
from clipflow.campaigns import Campaigns, Conflict
from clipflow.planner import Plans, planner_budget
from clipflow.queue import Limit, Queue
from clipflow.r2 import MEDIA_TYPES, PrivateMedia
from clipflow.render import MAX_OUTPUT_BYTES
from clipflow.transcription import enabled as transcription_enabled

MAX_UPLOAD = 25 * 1024 * 1024
QUOTA = 250 * 1024 * 1024
DEMO_RESERVATION = 1000
DEMO_MONTHLY_BUDGET = 30000
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
            email, password = payload.get('email', ''), payload['password']
            if not (isinstance(email, str) and len(email) <= 254
                    and (email or isinstance(auth, PreviewAuth)) and
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
                                    'batch_editing': self.server.media is None,
                                    'ai_planner': planner_budget() > 0,
                                    'upload_limit_mib': 8 if isinstance(self.server.auth, PreviewAuth) else 25,
                                    'clip_limit_seconds': 10 if isinstance(self.server.auth, PreviewAuth) else 60})
        files = {'/signin': ('signin.html', 'text/html'), '/signin.js': ('signin.js', 'text/javascript'),
                 '/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                 '/app.css': ('app.css', 'text/css'),
                 '/campaigns.js': ('campaigns.js', 'text/javascript'), '/batch.js': ('batch.js', 'text/javascript'),
                 '/workspace.js': ('workspace.js', 'text/javascript')}
        if url.path in files:
            name, mime = files[url.path]
            content = (WEB / name).read_bytes()
            if name == 'signin.html' and isinstance(self.server.auth, PreviewAuth):
                content = content.replace(b'<body>', b'<body class="password-only">').replace(
                    b'maxlength="254" required', b'maxlength="254"')
            return self.reply(200, content, mime + '; charset=utf-8')
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
            match = re.fullmatch(r'/api/campaigns/([0-9a-f]{32})/(approve|pause|resume|stop|schedule|schedule-batch)', self.path)
            post = re.fullmatch(r'/api/manual-posts/([0-9a-f]{32})/handoff', self.path)
            if post:
                self.server.campaigns.complete(post[1])
            elif not match:
                return self.reply(404, {'error': 'Item unavailable'})
            elif match[2] == 'schedule':
                self.server.campaigns.schedule(match[1], data)
            elif match[2] == 'schedule-batch':
                self.server.campaigns.schedule_batch(match[1], data)
            else:
                self.server.campaigns.transition(match[1], match[2])
            return self.reply(200, {'ok': True})
        except Limit as error:
            return self.reply(429, {'error': str(error)})
        except Conflict as error:
            return self.reply(409, {'error': str(error)})
        except (ValueError, OverflowError, TimeoutError) as error:
            return self.reply(400, {'error': str(error)})

    def do_POST(self):
        if self.path in ('/api/session', '/api/session/logout'):
            return self.session_request()
        if not self.authenticate(self.path):
            return
        if self.path == '/api/plans' or self.path.startswith(('/api/campaigns', '/api/manual-posts')):
            return self.campaign_request()
        if self.path == '/api/batches':
            return self.batch_request()
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
            preview = isinstance(self.server.auth, PreviewAuth)
            upload_limit = 8 * 1024 * 1024 if preview else MAX_UPLOAD
            clip_limit = 10 if preview else 60
            if not (0 < size <= upload_limit and math.isfinite(start) and math.isfinite(end)
                    and 0 <= start < end <= 1800 and 1 <= end - start <= clip_limit
                    and isinstance(cues, list) and len(cues) <= 30):
                raise ValueError()
            for cue in cues:
                if not (isinstance(cue, dict) and set(cue) == {'start', 'end', 'text'} and 0 <= cue['start'] < cue['end'] <= 1800
                        and isinstance(cue['text'], str) and 0 < len(cue['text']) <= 160):
                    raise ValueError()
        except (TypeError, ValueError, KeyError):
            return self.reply(400, {'error': 'Check the upload size, clip range and caption limits shown in Studio'})
        automatic = self.headers.get('X-Clip-Auto-Captions') == '1'
        if automatic and (not self.server.transcription_enabled or cues):
            return self.reply(409, {'error': 'Automatic captions require an enabled provider and no manual caption'})
        data = {'start': start, 'end': end, 'cues': cues, 'size': size, 'automatic_captions': automatic}
        if direct:
            data.update(storage='r2', mime=mime)
        spec = json.dumps(data)
        try:
            # Reserve source plus room for two lease attempts and stale output.
            storage = size + 2 * (BATCH_OUTPUT_BYTES if preview else MAX_OUTPUT_BYTES)
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

    def batch_request(self):
        if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin'):
            return self.reply(403, {'error': 'Cross-origin upload refused'})
        if self.server.media:
            return self.reply(409, {'error': 'Batch editing is currently available in Owner Preview storage'})
        if self.headers.get_content_type() != 'application/octet-stream' or self.headers.get('Transfer-Encoding'):
            return self.reply(415, {'error': 'Upload a source from the Batch Studio form'})
        try:
            video, music, captions, total = (int(self.headers[field]) for field in
                ('X-Source-Bytes', 'X-Music-Bytes', 'X-Subtitle-Bytes', 'Content-Length'))
            mode, style, key = (self.headers[field] for field in
                                ('X-Batch-Mode', 'X-Caption-Style', 'Idempotency-Key'))
            count, days = int(self.headers['X-Clip-Count']), int(self.headers['X-Release-Days'])
            goal = unquote(self.headers['X-Content-Goal']).strip()
            reference = unquote(self.headers.get('X-Batch-Reference', '')).strip()
            if reference:
                address = urlsplit(reference)
                if not (len(reference) <= 400 and address.scheme == 'https'
                        and address.netloc in ('www.youtube.com', 'youtube.com', 'youtu.be', 'open.spotify.com')):
                    raise ValueError()
            source_url = unquote(self.headers.get('X-Batch-Source-URL', '')).strip()
            if source_url:
                direct_source_url(source_url)
            name = unquote(self.headers.get('X-Clip-Name', 'Batch source'))[:120]
            if not (((0 < video <= 8 * 1024 * 1024 and not source_url) or (video == 0 and source_url))
                    and 0 <= music <= 8 * 1024 * 1024
                    and 0 <= captions <= MAX_TRANSCRIPT and total == video + music + captions
                    and re.fullmatch(r'[0-9a-f-]{36}', key)
                    and 1 <= count <= MAX_BATCH and 1 <= days <= 30 and 1 <= len(goal) <= 500
                    and style in PALETTES and mode in ('visual', 'speech', 'music')):
                raise ValueError()
        except (TypeError, ValueError):
            return self.reply(400, {'error': 'Check the source, goal, clip count and release window. Direct links must point to a Cloudflare R2 file.'})
        if mode == 'speech' and (music or not (captions or self.server.transcription_enabled)):
            return self.reply(400, {'error': 'Spoken highlights require timed SRT or VTT subtitles in this preview'})
        if mode != 'music' and music:
            return self.reply(400, {'error': 'Select Music promos to add a separate track'})
        if mode == 'music' and not music:
            return self.reply(400, {'error': 'Attach the authorized track audio file for music promos'})
        spec = json.dumps({'batch': True, 'mode': mode, 'caption_style': style, 'goal': goal,
                           'count': count, 'days': days, 'source_seconds': 120,
                           'clip_seconds': 10, 'size': 0, 'reference': reference, 'source_url': source_url})
        try:
            job_id, created = self.server.queue.reserve(key, 'Batch: ' + name, spec,
                total + (8 * 1024 * 1024 if source_url else 0) + 2 * count * BATCH_OUTPUT_BYTES,
                cost=count * DEMO_RESERVATION, budget=DEMO_MONTHLY_BUDGET, quota=QUOTA)
        except Limit as error:
            return self.reply(429, {'error': str(error)})
        # A batch reserves the full total until its exports expire. Source expiry does not
        # reduce the reservation because children share one source until rendering ends.
        if created:
            folder = self.server.root / job_id
            try:
                folder.mkdir(mode=0o700)
                for filename, remaining in (('source', video), ('music', music), ('captions', captions)):
                    if not remaining:
                        continue
                    with (folder / filename).open('xb') as target:
                        while remaining:
                            block = self.rfile.read(min(remaining, 65536))
                            if not block:
                                raise OSError('Incomplete upload')
                            target.write(block)
                            remaining -= len(block)
                self.server.queue.uploaded(job_id)
            except OSError:
                shutil.rmtree(folder, ignore_errors=True)
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
    parser.add_argument('--render-preview', action='store_true')
    args = parser.parse_args()
    if args.bind != '127.0.0.1' and not (args.authenticated_gateway or args.application_auth or args.render_preview):
        parser.error('Non-loopback access requires an authenticated gateway')
    args.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.bind, args.port), OwnerAPI)
    server.auth = (PreviewAuth(os.environ.get('CLIPFLOW_PREVIEW_PASSWORD', ''))
                   if args.render_preview else OwnerAuth.configured())
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
