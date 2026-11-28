"""Convert a bounded YouTube interval on the ClipFlow cloud worker."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from clipflow.converter import CONVERSION_FAILED, MAX_RANGE, ConversionError
from clipflow.render import probe
from clipflow.youtube import ACCESS_REFUSED, SOURCE_LIMIT, youtube_url

TIMEOUT = 145


def enabled():
    return os.environ.get('CLIPFLOW_BUILTIN_YOUTUBE') == 'true'


class BuiltinConverter:
    def stage(self, queue, job, url, window, destination):
        canonical = youtube_url(url)
        start, end = window['start'], window['end']
        if (not canonical or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= 43200 or not 3 <= end - start <= MAX_RANGE):
            raise ConversionError(CONVERSION_FAILED)

        with TemporaryDirectory(prefix='youtube-', dir=destination.parent) as scratch:
            output = Path(scratch) / 'segment.mp4'
            arguments = [
                'prlimit', f'--fsize={SOURCE_LIMIT}:{SOURCE_LIMIT}', '--',
                sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-plugin-dirs',
                '--no-cache-dir', '--no-remote-components', '--no-playlist', '--no-progress',
                '--socket-timeout', '12', '--retries', '0', '--fragment-retries', '0',
                '--extractor-retries', '0', '--match-filter', '!is_live',
                '--js-runtimes', 'node', '--download-sections', f'*{start}-{end}',
                '--force-keyframes-at-cuts', '--format-sort', 'res:360',
                '--format', 'b[ext=mp4][width<=640][height<=640]/bv[ext=mp4][width<=640][height<=640]+ba[ext=m4a]',
                '--merge-output-format', 'mp4', '--output', str(output), '--', canonical,
            ]
            if not queue.conversion_active(job):
                raise ConversionError(CONVERSION_FAILED)
            try:
                log_path = Path(scratch) / 'converter.log'
                with log_path.open('wb') as log:
                    exit_code = self.run(arguments, scratch, log, queue, job)
                if exit_code:
                    with log_path.open('rb') as log:
                        log.seek(max(0, log_path.stat().st_size - 4096))
                        details = log.read().lower()
                    if any(marker in details for marker in (b'403', b'confirm you', b'sign in', b'access denied')):
                        raise ConversionError(ACCESS_REFUSED)
                    raise ConversionError(CONVERSION_FAILED)
                if not 0 < output.stat().st_size <= SOURCE_LIMIT:
                    raise ConversionError(CONVERSION_FAILED)
                info = probe(output)
                if ('mp4' not in info['format']['format_name'].split(',')
                        or not abs(float(info['format']['duration']) - (end - start)) <= 0.5
                        or not any(stream['codec_type'] == 'video' and
                                   not stream.get('disposition', {}).get('attached_pic')
                                   for stream in info['streams'])
                        or not queue.conversion_active(job)):
                    raise ConversionError(CONVERSION_FAILED)
                output.replace(destination)
            except ConversionError:
                raise
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                raise ConversionError(CONVERSION_FAILED) from error

    @staticmethod
    def run(arguments, scratch, log, queue, job):
        # Pass network configuration without passing any application credentials.
        allowed = {'PATH', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
                   'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',
                   'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE'}
        env = {name: value for name, value in os.environ.items() if name in allowed}
        env.update(TMPDIR=scratch, PYTHONDONTWRITEBYTECODE='1')
        deadline = time.monotonic() + TIMEOUT
        with subprocess.Popen(arguments, cwd=scratch, env=env, stdin=subprocess.DEVNULL,
                              stdout=log, stderr=log, start_new_session=True) as process:
            try:
                while True:
                    try:
                        return process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        if time.monotonic() >= deadline or not queue.conversion_active(job):
                            raise ConversionError(CONVERSION_FAILED)
            finally:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
