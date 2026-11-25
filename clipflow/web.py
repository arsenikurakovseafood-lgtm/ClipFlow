"""Owner demonstration API. Run behind the authenticated Codex Cloud preview."""
import argparse
import json
import math
import re
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from clipflow.queue import Limit, Queue
from clipflow.render import MAX_OUTPUT_BYTES

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
        self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'none'")
        super().end_headers()

    def reply(self, status, body, mime='application/json'):
        if mime == 'application/json':
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                 '/app.css': ('app.css', 'text/css')}
        if url.path in files:
            name, mime = files[url.path]
            return self.reply(200, (WEB / name).read_bytes(), mime + '; charset=utf-8')
        jobs = self.server.queue.all()
        if url.path == '/api/jobs':
            return self.reply(200, [{k: v for k, v in job.items() if k != 'lease_token'} for job in jobs])
        match = re.fullmatch(r'/media/([0-9a-f]{32})', url.path)
        if match:
            job = next((j for j in jobs if j['id'] == match[1] and j['state'] == 'ready'), None)
            if job:
                path = self.server.root / job['id'] / (job['lease_token'] + '.mp4')
                if path.is_file():
                    return self.stream(path, parse_qs(url.query).get('download') == ['1'])
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

    def do_POST(self):
        if self.path != '/api/jobs':
            return self.reply(404, {'error': 'Item unavailable'})
        # Cross-site forms cannot produce the required custom headers.
        if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin'):
            return self.reply(403, {'error': 'Cross-origin upload refused'})
        if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() not in (
                'video/mp4', 'video/webm', 'video/quicktime'):
            return self.reply(415, {'error': 'Upload an MP4, MOV or WebM video'})
        key = self.headers.get('Idempotency-Key', '')
        if not re.fullmatch(r'[0-9a-f-]{36}', key):
            return self.reply(400, {'error': 'Missing valid request key'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
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
        spec = json.dumps({'start': start, 'end': end, 'cues': cues})
        try:
            # Reserve source plus room for two lease attempts and stale output.
            storage = size + 2 * MAX_OUTPUT_BYTES
            job_id, created = self.server.queue.reserve(key, name, spec, storage, cost=DEMO_RESERVATION,
                                                        budget=DEMO_MONTHLY_BUDGET, quota=QUOTA)
        except Limit as error:
            return self.reply(429, {'error': str(error)})
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', default=3000, type=int)
    parser.add_argument('--authenticated-gateway', action='store_true')
    args = parser.parse_args()
    if args.bind != '127.0.0.1' and not args.authenticated_gateway:
        parser.error('Non-loopback access requires an authenticated gateway')
    args.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.bind, args.port), OwnerAPI)
    server.root = args.root.resolve()
    server.queue = Queue(server.root / 'jobs.sqlite3')
    server.serve_forever()


if __name__ == '__main__':
    main()
