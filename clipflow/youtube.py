"""Canonical YouTube URLs used by accounts and range conversion."""
import re
from urllib.parse import parse_qs, urlsplit

VIDEO_ID = re.compile(r'[a-zA-Z0-9_-]{11}')
SOURCE_LIMIT = 8 * 1024 * 1024
ACCESS_REFUSED = 'YouTube refused access from this cloud server. Upload the original video.'


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
