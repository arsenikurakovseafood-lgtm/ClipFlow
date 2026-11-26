"""Prepare distinct short clips from authorized footage and optional caption tracks."""
import re
import subprocess
from bisect import bisect_left
from dataclasses import asdict
from uuid import UUID, uuid5

from clipflow.render import Cue, LOCAL_PROTOCOLS, probe

MAX_BATCH = 10
MAX_TRANSCRIPT = 128 * 1024
BATCH_OUTPUT_BYTES = 5 * 1024 * 1024
PALETTES = {
    'white': '00FFFFFF',
    'pink': '008728FF',
    'red': '004522F0',
    'blue': '00FFE66B',
}
TIME = r'(?:(\d{1,2}):)?(\d{2}):(\d{2})[,.](\d{3})'
TIMING = re.compile(r'^' + TIME + r'\s+-->\s+' + TIME + r'(?:\s+.*)?$')
STOP_WORDS = {'and', 'for', 'the', 'with', 'from', 'video', 'clips', 'these', 'that',
              'this', 'make', 'clip', 'create', 'чтобы', 'мне', 'для', 'сделай', 'видео', 'клипы'}


class BatchError(ValueError):
    pass


def parse_captions(text):
    def seconds(parts):
        hours, minutes, seconds, millis = (int(value or 0) for value in parts)
        if not (minutes < 60 and seconds < 60):
            raise BatchError('Invalid timestamp in subtitles.')
        return 3600 * hours + 60 * minutes + seconds + millis / 1000

    lines = text.strip().lstrip('\ufeff').splitlines()
    cues = []
    index = 0
    while index < len(lines):
        match = TIMING.fullmatch(lines[index].strip())
        index += 1
        if not match:
            continue
        start, end = seconds(match.groups()[:4]), seconds(match.groups()[4:])
        text_lines = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index])
            index += 1
        caption = re.sub(r'<[^>]*>', '', ' '.join(text_lines)).strip()[:160]
        if caption and 0 <= start < end <= 1800:
            cues.append(Cue(start, end, caption))
        if len(cues) > 1000:
            raise BatchError('The subtitle file has too many cues.')
    if not cues:
        raise BatchError('No usable SRT or WebVTT subtitle cues were found.')
    return sorted(cues, key=lambda cue: (cue.start, cue.end))


def terms(text):
    return set(re.findall(r'[^\W\d_]{3,}', text.casefold())) - STOP_WORDS


def speech_windows(cues, source_duration, goal, count, limit):
    goal_terms = terms(goal)
    options = []
    for index, first in enumerate(cues):
        start = first.start
        if index and first.start - cues[index - 1].end < 1 and not ended(cues[index - 1].text):
            continue
        matches = set()
        previous_end = start
        for cue in cues[index:index + 40]:
            if cue.end > source_duration or cue.end - start > limit or cue.start - previous_end > 1.8:
                break
            matches.update(goal_terms & terms(cue.text))
            previous_end = max(previous_end, cue.end)
            if cue.end - start >= 3 and ended(cue.text):
                options.append((start, cue.end, len(matches), int(abs(cue.end - start - min(limit, 7)) * 10)))
    options.sort()
    starts = [option[0] for option in options]
    after = [bisect_left(starts, option[1]) for option in options]
    best = [[0] * (len(options) + 1) for _ in range(count + 1)]

    def take(remaining, index):
        _, _, matches, penalty = options[index]
        return 1_000_000 + matches * 1000 - penalty + best[remaining - 1][after[index]]

    for remaining in range(1, count + 1):
        for index in reversed(range(len(options))):
            best[remaining][index] = max(best[remaining][index + 1], take(remaining, index))
    selected = []
    index = 0
    while count and index < len(options):
        if take(count, index) >= best[count][index + 1]:
            selected.append(options[index][:2])
            index = after[index]
            count -= 1
        else:
            index += 1
    return selected


def ended(text):
    return text.rstrip('”’"»\')]').endswith(('.', '!', '?', '…'))


def scene_windows(source, duration, count, limit):
    result = subprocess.run([
        'ffmpeg', '-nostdin', '-hide_banner', '-v', 'info', '-filter_threads', '1',
        *LOCAL_PROTOCOLS, '-threads', '1', '-i', str(source), '-an', '-sn', '-dn',
        '-vf', "fps=4,scale=256:-2,select='gt(scene,0.22)',showinfo", '-f', 'null', '-',
    ], capture_output=True, text=True, timeout=90, check=True, stdin=subprocess.DEVNULL)
    count = min(count, int(duration / 3))
    span = duration / count
    # Keep each excerpt in a separate slot, moving its start to a scene cut when possible.
    length = min(limit, 9, max(3, span - min(1, span / 8)))
    scenes = [float(value) for value in re.findall(r'pts_time:([0-9.]+)', result.stderr)]
    selected = []
    for index in range(count):
        left, right = index * span, (index + 1) * span
        start = next((scene for scene in scenes if left <= scene <= right - length), left)
        selected.append((start, min(duration, start + length)))
    return selected


def stage_batch(root, queue, job, data, transcriber=None):
    folder = root / job['id']
    source = folder / 'source'
    info = probe(source)
    duration = float(info['format']['duration'])
    if not (3 <= duration <= data['source_seconds']) or not any(
            stream['codec_type'] == 'video' and not stream.get('disposition', {}).get('attached_pic')
            and 0 < stream['width'] <= 1920 and 0 < stream['height'] <= 1920
            for stream in info['streams']):
        raise BatchError('Batch source must be 3 seconds to 2 minutes, with dimensions up to 1920 px.')
    captions = folder / 'captions'
    cues = parse_captions(captions.read_text(encoding='utf-8-sig')) if captions.exists() else []
    if data['mode'] == 'speech':
        if not cues:
            if not transcriber:
                raise BatchError('Attach an SRT or VTT file for spoken highlights.')
            cues = transcriber.captions(queue, job, source, 0, duration)
        windows = speech_windows(cues, duration, data['goal'], data['count'], data['clip_seconds'])
    else:
        track = probe(folder / 'music')
        track_seconds = float(track['format']['duration'])
        if not 3 <= track_seconds <= 1800 or not any(stream['codec_type'] == 'audio' for stream in track['streams']):
            raise BatchError('Upload a playable track of at least three seconds.')
        windows = scene_windows(source, duration, data['count'], data['clip_seconds'])
    if not windows:
        raise BatchError('No complete highlights fit the requested duration. Check the source and subtitles.')

    children = []
    for number, (start, end) in enumerate(windows, 1):
        child_id = uuid5(UUID(job['id']), str(number)).hex
        # Children read the single staged source until their own render is complete.
        first_cue = next((cue.text for cue in cues if start <= cue.start < end), '')
        title = f'{number}. {first_cue[:75] or data["goal"][:75]}'
        clip = {'batch_parent': job['id'], 'start': start, 'end': end,
                'caption_style': data['caption_style'],
                'release_day': 1 + ((number - 1) * data['days'] // len(windows)),
                'release_days': data['days'],
                'cues': [asdict(cue) for cue in cues if cue.end > start and cue.start < end]}
        if data['mode'] == 'music':
            clip['music_start'] = (number - 1) * 6 % max(1, track_seconds - (end - start))
        children.append((child_id, title, clip))

    queue.expand_batch(job, children, BATCH_OUTPUT_BYTES,
                       f'{len(children)} of {data["count"]} clips queued for the render worker.')
