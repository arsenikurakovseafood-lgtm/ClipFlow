"""Render bounded clips from staged, authorized local media."""
import json
import math
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

MAX_SOURCE_BYTES = 250 * 1024 * 1024
MAX_SOURCE_SECONDS = 1800
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
LOCAL_PROTOCOLS = ('-protocol_whitelist', 'file', '-format_whitelist', 'mov,matroska,webm,mp3,wav,flac,ogg')


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def run(*args, timeout=30, cwd=None):
    return subprocess.run(
        args, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        timeout=timeout, cwd=cwd,
    ).stdout


def probe(path):
    return json.loads(run(
        'ffprobe', '-v', 'error', *LOCAL_PROTOCOLS, '-show_streams',
        '-show_format', '-of', 'json', str(path),
    ))


def timestamp(seconds):
    hours, remainder = divmod(round(seconds * 1000), 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}'


def subtitles(cues, start, end):
    blocks = []
    previous_end = start
    for cue in cues:
        if not (math.isfinite(cue.start) and math.isfinite(cue.end)):
            raise ValueError('Caption timestamps must be finite')
        if cue.end <= start or cue.start >= end:
            continue
        left, right = max(previous_end, cue.start), min(end, cue.end)
        # Neutralize subtitle markup. A single line also prevents injected cue boundaries.
        caption = ' '.join(cue.text.split())[:160].replace('<', '‹').replace('>', '›')
        caption = caption.translate(str.maketrans({'{': '｛', '}': '｝', chr(92): '＼'}))
        if round((right - start) * 1000) <= round((left - start) * 1000) or not caption:
            continue
        blocks.append(f'{len(blocks) + 1}\n{timestamp(left - start)} --> {timestamp(right - start)}\n{caption}\n')
        previous_end = right
    return '\n'.join(blocks)


def render(source: Path, output: Path, start: float, end: float, cues: list[Cue]):
    """Write a verified MP4 atomically. Cues use absolute source timestamps."""
    source, output = source.resolve(), output.resolve()
    metadata = source.stat()
    if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_SOURCE_BYTES:
        raise ValueError('Source must be a regular staged file within the size limit')
    if source == output or len(cues) > 1000:
        raise ValueError('Invalid output or caption count')
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end and 1 <= end - start <= 60):
        raise ValueError('Select a clip between 1 and 60 seconds')
    info = probe(source)
    duration = float(info['format']['duration'])
    if not 0 < duration <= MAX_SOURCE_SECONDS or end > duration:
        raise ValueError('Clip exceeds source duration or source duration limit')
    video = next((stream for stream in info['streams'] if stream['codec_type'] == 'video'
                  and not stream.get('disposition', {}).get('attached_pic')), None)
    if video is None or not (0 < video['width'] <= 3840 and 0 < video['height'] <= 3840):
        raise ValueError('A playable source video within the dimension limit is required')
    caption_body = subtitles(sorted(cues, key=lambda cue: cue.start), start, end)
    with TemporaryDirectory(prefix='.clipflow-', dir=output.parent) as work:
        staged = Path(work) / 'clip.mp4'
        filters = ('scale=720:1280:force_original_aspect_ratio=increase:force_divisible_by=2,'
                   'crop=720:1280,setsar=1,fps=30')
        if caption_body:
            (Path(work) / 'clip.srt').write_text(caption_body, encoding='utf-8')
            filters += ",subtitles=clip.srt:force_style='FontName=DejaVu Sans,FontSize=17,Outline=2,MarginV=32'"
        run(
            'ffmpeg', '-nostdin', '-v', 'error', '-filter_threads', '2',
            *LOCAL_PROTOCOLS, '-threads', '2', '-ss', str(start), '-i', str(source),
            '-t', str(end - start), '-map', f"0:{video['index']}", '-map', '0:a:0?',
            '-map_metadata', '-1', '-map_chapters', '-1', '-vf', filters,
            '-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ac', '2',
            '-maxrate', '3M', '-bufsize', '6M', '-fs', str(MAX_OUTPUT_BYTES),
            '-movflags', '+faststart', str(staged), timeout=240, cwd=work,
        )
        result = probe(staged)
        stream = next(s for s in result['streams'] if s['codec_type'] == 'video')
        actual_duration = float(result['format']['duration'])
        if ((stream['width'], stream['height'], stream['codec_name']) != (720, 1280, 'h264')
                or staged.stat().st_size > MAX_OUTPUT_BYTES
                or abs(actual_duration - (end - start)) > 0.2):
            raise ValueError('Rendered file failed quality checks')
        os.replace(staged, output)
    return {'duration_seconds': actual_duration, 'width': 720, 'height': 1280,
            'output_bytes': output.stat().st_size}
