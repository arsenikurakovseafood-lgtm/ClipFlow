"""Durable, explicitly approved YouTube uploads and public status checks."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from clipflow.auth import NoRedirect
from clipflow.queue import audit, workloads_paused
from clipflow.youtube import VIDEO_ID

SERVICE = 'https://www.googleapis.com'
TOKEN = 'https://oauth2.googleapis.com/token'
SECRET_NAMES = ('CLIENT_ID', 'CLIENT_SECRET', 'REFRESH_TOKEN', 'CHANNEL_ID')


def publishing_enabled():
    return os.environ.get('CLIPFLOW_YOUTUBE_PUBLISHING') == 'true'


class YouTubePublisher:
    def __init__(self, client_id, secret, refresh_token, channel, opener=None):
        self.channel = channel
        self.credentials = urlencode(dict(client_id=client_id, client_secret=secret,
                                          refresh_token=refresh_token, grant_type='refresh_token')).encode()
        self.opener = opener or build_opener(NoRedirect)

    @classmethod
    def configured(cls):
        values = [os.environ.get('CLIPFLOW_YOUTUBE_' + name, '') for name in SECRET_NAMES]
        if publishing_enabled() and all(values) and re.fullmatch(r'UC[a-zA-Z0-9_-]{22}', values[3]):
            return cls(*values)
        return None

    def json(self, url, *, token=None, data=None, headers=None, method=None):
        headers = dict(headers or {})
        if token:
            headers['Authorization'] = 'Bearer ' + token
        with self.opener.open(Request(url, data=data, headers=headers, method=method), timeout=30) as response:
            return json.loads(response.read(128 * 1024))

    def token(self):
        return self.json(TOKEN, data=self.credentials)['access_token']

    def check_channel(self, token):
        channels = self.json(SERVICE + '/youtube/v3/channels?part=id&mine=true', token=token)['items']
        if {channel['id'] for channel in channels} != {self.channel}:
            raise ValueError('The connected account does not match the configured channel.')

    def upload(self, path, title, still_approved):
        token = self.token()
        self.check_channel(token)
        size = path.stat().st_size
        data = json.dumps({'snippet': {'title': title[:100]}, 'status': {'privacyStatus': 'public'}}).encode()
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                   'X-Upload-Content-Type': 'video/mp4', 'X-Upload-Content-Length': str(size)}
        if not still_approved():
            raise ValueError('Publication was paused or stopped.')
        request = Request(SERVICE + '/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status&notifySubscribers=false',
                          data=data, headers=headers)
        with self.opener.open(request, timeout=15) as response:
            location = response.headers['Location']
        url = urlsplit(location)
        if (url.scheme != 'https' or url.netloc not in ('www.googleapis.com', 'youtube.googleapis.com')
                or url.path != '/upload/youtube/v3/videos' or not url.query or url.fragment):
            raise ValueError('YouTube returned an unexpected upload endpoint.')
        if not still_approved():
            raise ValueError('Publication was paused or stopped.')
        with path.open('rb') as video:
            result = self.json(location, token=token, data=video, method='PUT',
                               headers={'Content-Type': 'video/mp4', 'Content-Length': str(size)})
        identifier = result.get('id', '')
        if not isinstance(identifier, str) or not VIDEO_ID.fullmatch(identifier):
            raise ValueError('YouTube did not return a video identifier.')
        return identifier

    def inspect(self, identifier):
        query = urlencode({'id': identifier, 'part': 'snippet,status,statistics'})
        videos = self.json(SERVICE + '/youtube/v3/videos?' + query, token=self.token())['items']
        video = next((item for item in videos if item['id'] == identifier), None)
        if not video or video['snippet']['channelId'] != self.channel:
            return None
        return video


def publication_allowed(db, post_id):
    return not workloads_paused(db) and bool(db.execute("""SELECT 1 FROM manual_posts p
        JOIN campaigns c ON c.id=p.campaign_id JOIN jobs j ON j.id=p.job_id
        WHERE p.id=? AND p.state='uploading' AND c.state='active'
          AND j.review='approved' AND j.state='ready'""", (post_id,)).fetchone())


def process_publication(queue, publisher, root, media=None, owner_id=None, connected=None):
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    with queue.transaction() as db:
        db.execute("""UPDATE manual_posts SET state='publication_failed',
            publication_error='Upload outcome unknown. Check YouTube Studio before trying again.'
            WHERE delivery='youtube' AND state='uploading' AND attempted_at<?""",
            ((now - timedelta(minutes=3)).isoformat(),))
        if workloads_paused(db):
            return False
        candidate = db.execute("""SELECT p.*,j.name,j.spec,j.lease_token,j.output_bytes
            FROM manual_posts p JOIN campaigns c ON c.id=p.campaign_id JOIN jobs j ON j.id=p.job_id
            WHERE p.delivery='youtube' AND c.channel='youtube' AND (
              (p.state='scheduled' AND p.scheduled_at<=? AND c.state='active' AND j.state='ready' AND j.review='approved')
              OR (p.state='uploaded' AND p.checked_at<=?))
            ORDER BY p.scheduled_at LIMIT 1""", (stamp, (now - timedelta(seconds=30)).isoformat())).fetchone()
        if not candidate:
            return False
        if candidate['state'] == 'scheduled':
            db.execute("UPDATE manual_posts SET state='uploading',attempted_at=? WHERE id=?", (stamp, candidate['id']))
        else:
            db.execute('UPDATE manual_posts SET checked_at=? WHERE id=?', (stamp, candidate['id']))
    identifier = candidate['id']

    def still_approved():
        if connected and not connected():
            return False
        with queue.transaction() as db:
            return publication_allowed(db, identifier)

    try:
        if candidate['state'] == 'scheduled':
            if json.loads(candidate['spec']).get('storage') == 'r2':
                if not media or not owner_id:
                    raise ValueError('Private output storage is unavailable.')
                with TemporaryDirectory(prefix='media-publish-', dir=root) as directory:
                    path = Path(directory) / 'output.mp4'
                    try:
                        media.stage_output(owner_id, candidate['job_id'], candidate['lease_token'],
                                           size=candidate['output_bytes'], destination=path)
                    except Exception as error:
                        raise ValueError('Private output storage is unavailable.') from error
                    video_id = publisher.upload(path, candidate['name'], still_approved)
            else:
                path = root / candidate['job_id'] / (candidate['lease_token'] + '.mp4')
                video_id = publisher.upload(path, candidate['name'], still_approved)
            with queue.transaction() as db:
                db.execute("""UPDATE manual_posts SET state='uploaded',provider_id=?,checked_at=?
                    WHERE id=? AND state='uploading' AND attempted_at=?""",
                           (video_id, stamp, identifier, stamp))
            return True

        video = publisher.inspect(candidate['provider_id'])
        status = video['status'] if video else {}
        if status.get('privacyStatus') == 'public' and status.get('uploadStatus') == 'processed':
            with queue.transaction() as db:
                db.execute("""UPDATE manual_posts SET state='published',post_url=?,reported_at=?
                    WHERE id=? AND state='uploaded'""",
                    ('https://www.youtube.com/shorts/' + candidate['provider_id'], stamp, identifier))
                audit(db, 'youtube_publication_confirmed', identifier)
        elif status.get('uploadStatus') in ('failed', 'rejected', 'deleted') or (
                datetime.fromisoformat(candidate['attempted_at']) <= now - timedelta(minutes=30)):
            fail_publication(queue, identifier, 'YouTube did not confirm a public video. Check processing and project approval in YouTube Studio.')
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        if candidate['state'] == 'scheduled':
            fail_publication(queue, identifier, 'Upload not confirmed. Check YouTube Studio and the connected channel before trying again.')
        elif datetime.fromisoformat(candidate['attempted_at']) <= now - timedelta(minutes=30):
            fail_publication(queue, identifier, 'YouTube could not confirm the video status. Check YouTube Studio.')
    return True


def fail_publication(queue, identifier, error):
    with queue.transaction() as db:
        db.execute("""UPDATE manual_posts SET state='publication_failed',publication_error=?
            WHERE id=? AND state IN ('uploading','uploaded')""",
                   (error, identifier))
