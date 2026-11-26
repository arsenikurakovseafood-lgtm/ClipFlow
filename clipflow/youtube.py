"""Bounded one-video importer for the private cloud studio."""
import os
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

VIDEO_ID = re.compile(r'[a-zA-Z0-9_-]{11}')
SOURCE_LIMIT = 8 * 1024 * 1024


class ImportFailed(ValueError):
    pass


def youtube_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'https':
        return None
    if parsed.netloc == 'youtu.be':
        video_id = parsed.path.removeprefix('/')
    elif parsed.netloc in ('www.youtube.com', 'youtube.com', 'm.youtube.com'):
        if parsed.path == '/watch':
            video_id = parse_qs(parsed.query).get('v', [''])[0]
        elif parsed.path.startswith('/shorts/'):
            video_id = parsed.path.removeprefix('/shorts/')
        else:
            return None
    else:
        return None
    if VIDEO_ID.fullmatch(video_id):
        return 'https://www.youtube.com/watch?v=' + video_id
    return None


def fetch_youtube(url, destination):
    canonical = youtube_url(url)
    if canonical is None:
        raise ImportFailed('Use a valid public YouTube video or Shorts link.')
    with TemporaryDirectory(prefix='youtube-', dir=destination.parent) as scratch:
        output = Path(scratch) / 'video.mp4'
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('OPENAI_', 'CLIPFLOW_'))}
        args = [
            'prlimit', f'--fsize={SOURCE_LIMIT}:{SOURCE_LIMIT}', '--', sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-plugin-dirs',
            '--js-runtimes', 'node', '--no-playlist', '--no-progress', '--no-cache-dir',
            '--no-simulate', '--no-mtime', '--socket-timeout', '8', '--retries', '0',
            '--fragment-retries', '0', '--extractor-retries', '0',
            '--match-filter', 'duration >= 3 & duration <= 120 & !is_live',
            '--max-filesize', str(SOURCE_LIMIT), '--print', 'after_move:filepath',
            '--format', ('b[ext=mp4][height<=360][filesize<8M]/'
             'b[ext=mp4][height<=360][filesize_approx<8M]/b[protocol=https][ext=mp4][height<=360]'),
            '--output', str(output), '--', canonical,
        ]
        try:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                    timeout=65, env=env, cwd=scratch)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ImportFailed('YouTube import timed out or is temporarily unavailable.') from error
        if result.returncode or not output.is_file():
            details = result.stderr.casefold()
            if 'confirm you' in details or 'sign in' in details or 'http error 403' in details or '403 forbidden' in details:
                raise ImportFailed('YouTube refused access from this cloud server. Upload the original video.')
            if 'filter' in result.stdout.casefold() or 'does not pass' in details or 'does not pass' in result.stdout.casefold():
                raise ImportFailed('Choose a recorded YouTube video between 3 seconds and 2 minutes.')
            if 'requested format' in details or 'filesize' in details:
                raise ImportFailed('YouTube did not offer a compatible MP4 under 8 MiB. Upload the original.')
            raise ImportFailed('Could not import this YouTube video. Try a public link or upload the original.')
        if not 0 < output.stat().st_size <= SOURCE_LIMIT:
            raise ImportFailed('YouTube source exceeds the 8 MiB preview limit.')
        output.replace(destination)
