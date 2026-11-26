"""Original ClipFlow walkthrough rendered in the worker for owner testing."""
from pathlib import Path
from tempfile import TemporaryDirectory

from clipflow.render import Cue, run, subtitles

SCENES = (
    ('PLAN THE CAMPAIGN', 'Start with a goal your audience cares about.', 'FA247D'),
    ('MAKE THE CUT', 'Turn an approved source into short vertical edits.', 'E23950'),
    ('REVIEW AND SCHEDULE', 'Watch each clip before adding it to the schedule.', '506AFF'),
    ('MEASURE THE RESULT', 'Compare real clicks and conversions before changing your hook.', '5FD5FF'),
)
SCENE_SECONDS = 6
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def stage_sample(folder, mode):
    source = folder / 'source'
    if not source.is_file():
        with TemporaryDirectory(prefix='.sample-', dir=folder) as directory:
            parts = []
            for index, (title, speech, color) in enumerate(SCENES):
                part = f'part-{index}.mp4'
                parts.append(part)
                filters = (f'drawbox=x=35:y=159:w=290:h=4:color=0x{color}:t=fill,'
                           f'drawtext=fontfile={FONT}:text=CLIPFLOW:fontsize=14:fontcolor=0x{color}:x=35:y=126,'
                           f'drawtext=fontfile={FONT}:text={title}:fontsize=20:fontcolor=white:x=35:y=220')
                run('ffmpeg', '-nostdin', '-v', 'error', '-filter_threads', '1', '-f', 'lavfi',
                    '-i', 'color=c=0x0B0D19:s=360x640:r=30', '-f', 'lavfi',
                    '-i', f"flite=voice=slt:text='{speech}'", '-t', str(SCENE_SECONDS), '-vf', filters,
                    '-af', 'apad', '-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast',
                    '-c:a', 'aac', '-ar', '44100', part, cwd=directory)
            staging = Path(directory)
            (staging / 'parts.txt').write_text(''.join(f'file {part}\n' for part in parts))
            run('ffmpeg', '-nostdin', '-v', 'error', '-f', 'concat', '-safe', '1', '-i', 'parts.txt',
                '-c', 'copy', '-movflags', '+faststart', 'sample.mp4', cwd=directory)
            (staging / 'sample.mp4').replace(source)
    if mode != 'music' and not (folder / 'captions').is_file():
        cues = [Cue(index * SCENE_SECONDS, (index + 1) * SCENE_SECONDS, speech)
                for index, (_, speech, _) in enumerate(SCENES)]
        (folder / 'captions').write_text(subtitles(cues, 0, len(SCENES) * SCENE_SECONDS), encoding='utf-8')
    if mode == 'music' and not (folder / 'music').is_file():
        with TemporaryDirectory(prefix='.track-', dir=folder) as directory:
            track = Path(directory) / 'sample.wav'
            run('ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                'aevalsrc=0.22*sin(2*PI*110*t)+0.12*sin(2*PI*165*t)+0.08*sin(2*PI*220*t):s=22050',
                '-af', 'tremolo=f=4:d=0.7', '-t', str(len(SCENES) * SCENE_SECONDS), str(track))
            track.replace(folder / 'music')
