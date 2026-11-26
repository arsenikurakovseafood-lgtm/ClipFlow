"""VidFetch's range-only conversion API. The worker holds the API key."""
import json
import os
import re
import time
from subprocess import SubprocessError
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from clipflow.auth import NoRedirect
from clipflow.render import probe
from clipflow.youtube import SOURCE_LIMIT

API = 'https://api.vidfetch.dev/v1/downloads'
CONVERSION_FAILED = 'The video converter could not return the selected segment. Try a pre-cut MP4 or an R2 file link.'
DISABLED = 'YouTube segment conversion is off. Connect an approved VidFetch account or use a pre-cut source.'
IDENTIFIER = re.compile(r'dl_[a-zA-Z0-9_-]{8,80}')
MAX_RANGE = 120


class ConversionError(ValueError):
    pass


def monthly_limit():
    if os.environ.get('CLIPFLOW_VIDFETCH_ENABLED') != 'true':
        return 0
    value = os.environ.get('CLIPFLOW_VIDFETCH_MONTHLY_JOBS', '')
    return int(value) if value.isascii() and value.isdecimal() and len(value) <= 4 else 0


def segment_range(start, end):
    def seconds(value):
        if not re.fullmatch(r'[0-9]{1,5}(?::[0-5][0-9]){0,2}', value):
            raise ValueError('Use seconds, MM:SS or HH:MM:SS for both timecodes.')
        total = 0
        for part in value.split(':'):
            total = total * 60 + int(part)
        return total

    start, end = seconds(start), seconds(end)
    if not 3 <= end - start <= MAX_RANGE or end > 12 * 3600:
        raise ValueError('Choose a segment of 3–120 seconds within the first 12 hours.')
    return {'start': start, 'end': end}


class VidFetch:
    def __init__(self, key, delivery_origin, limit, opener=None):
        self.key = key
        self.delivery_origin = delivery_origin
        self.limit = limit
        self.opener = opener or build_opener(NoRedirect)

    @classmethod
    def configured(cls):
        limit = monthly_limit()
        key = os.environ.get('CLIPFLOW_VIDFETCH_API_KEY', '')
        origin = os.environ.get('CLIPFLOW_VIDFETCH_DELIVERY_ORIGIN', '')
        if not (limit and key and re.fullmatch(r'https://(?:[a-z0-9-]+\.)+[a-z][a-z0-9-]+', origin)):
            return None
        return cls(key, origin, limit)

    def api(self, method, remote_id='', data=None):
        headers = {'Authorization': 'Bearer ' + self.key, 'Accept': 'application/json'}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        payload = json.dumps(data).encode() if data is not None else None
        request = Request(API + ('/' + remote_id if remote_id else ''), headers=headers, data=payload, method=method)
        with self.opener.open(request, timeout=8) as response:
            return None if method == 'DELETE' else json.loads(response.read(64 * 1024))

    def download(self, url, output, size):
        parts = urlsplit(url)
        if (len(url) > 4096 or parts.fragment or any(c.isspace() for c in url)
                or f'{parts.scheme}://{parts.netloc}' != self.delivery_origin):
            raise ConversionError(CONVERSION_FAILED)
        deadline = time.monotonic() + 25
        with self.opener.open(Request(url, headers={'Accept': 'video/mp4'}), timeout=8) as response:
            if (response.status != 200 or response.headers.get('Content-Encoding', 'identity') != 'identity'
                    or response.headers.get('Content-Type', '').partition(';')[0].lower()
                    not in ('video/mp4', 'application/octet-stream')):
                raise ConversionError(CONVERSION_FAILED)
            remaining = int(response.headers.get('Content-Length', '0'))
            if not 0 < remaining <= SOURCE_LIMIT or remaining != size:
                raise ConversionError(CONVERSION_FAILED)
            with output.open('xb') as target:
                while remaining:
                    if time.monotonic() > deadline:
                        raise ConversionError(CONVERSION_FAILED)
                    block = response.read1(min(remaining, 65536))
                    if not block:
                        raise ConversionError(CONVERSION_FAILED)
                    target.write(block)
                    remaining -= len(block)

    def stage(self, queue, job, url, window, destination):
        remote_id = None
        try:
            remote_id, submit = queue.reserve_conversion(job, self.limit)
            if submit:
                response = self.api('POST', data={'url': url, 'format': '360p', 'trim': window, 'destination': 'url'})
                returned_id = response['id']
                if not isinstance(returned_id, str) or not IDENTIFIER.fullmatch(returned_id):
                    raise ConversionError(CONVERSION_FAILED)
                remote_id = returned_id
                if not queue.bind_conversion(job, remote_id):
                    raise ConversionError(CONVERSION_FAILED)
            if not remote_id:
                raise ConversionError(CONVERSION_FAILED)
            deadline = time.monotonic() + 100
            while time.monotonic() < deadline and queue.conversion_active(job):
                status = self.api('GET', remote_id)
                if status['id'] != remote_id:
                    raise ConversionError(CONVERSION_FAILED)
                if status['status'] == 'completed':
                    if status.get('trim') != window or not 0 < status['size_bytes'] <= SOURCE_LIMIT:
                        raise ConversionError(CONVERSION_FAILED)
                    with TemporaryDirectory(prefix='converter-', dir=destination.parent) as scratch:
                        output = Path(scratch) / 'segment.mp4'
                        self.download(status['download_url'], output, status['size_bytes'])
                        info = probe(output)
                        expected = window['end'] - window['start']
                        if ('mp4' not in info['format']['format_name'].split(',')
                                or not abs(float(info['format']['duration']) - expected) <= 0.5
                                or not any(stream['codec_type'] == 'video' and
                                           not stream.get('disposition', {}).get('attached_pic')
                                           for stream in info['streams'])
                                or not queue.conversion_active(job)):
                            raise ConversionError(CONVERSION_FAILED)
                        output.replace(destination)
                    return
                if status['status'] not in ('queued', 'processing'):
                    break
                time.sleep(3)
            raise ConversionError(CONVERSION_FAILED)
        except (OSError, KeyError, AttributeError, TypeError, ValueError, SubprocessError) as error:
            raise ConversionError(CONVERSION_FAILED) from error
        finally:
            if remote_id:
                self.release(queue, job['id'], remote_id)

    def release(self, queue, job_id, remote_id):
        try:
            self.api('DELETE', remote_id)
        except HTTPError as error:
            if error.code != 404:
                return
        except OSError:
            return
        queue.mark_conversion_deleted(job_id, remote_id)
