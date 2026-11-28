"""Read public statistics using the official YouTube Data API."""
import json
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from clipflow.auth import NoRedirect
from clipflow.youtube import youtube_url


def youtube_video_id(url):
    canonical = youtube_url(url)
    return canonical.rsplit('=', 1)[-1] if canonical else None


def youtube_statistics(video_id, api_key, opener=None):
    query = urlencode({'part': 'statistics', 'id': video_id, 'fields': 'items(id,statistics)'})
    request = Request('https://www.googleapis.com/youtube/v3/videos?' + query,
                      headers={'X-Goog-Api-Key': api_key, 'Accept': 'application/json'})
    try:
        with (opener or build_opener(NoRedirect)).open(request, timeout=8) as response:
            payload = json.loads(response.read(64 * 1024))
        item = next(item for item in payload['items'] if item['id'] == video_id)
        stats = item['statistics']
        result = {name: int(stats[name + 'Count']) if name + 'Count' in stats else None
                  for name in ('view', 'like', 'comment')}
        if result['view'] is None or any(value is not None and not 0 <= value <= 10**14 for value in result.values()):
            raise ValueError()
    except (OSError, KeyError, ValueError, TypeError, StopIteration) as error:
        raise ValueError('YouTube statistics are unavailable. Check the public post and Data API configuration.') from error
    return {name + 's': value for name, value in result.items()}
