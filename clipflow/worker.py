"""Independent cloud demonstration worker."""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from clipflow.batch import BATCH_OUTPUT_BYTES, PALETTES, BatchError, stage_batch
from clipflow.planner import Plans, planner_budget
from clipflow.queue import Queue
from clipflow.r2 import PrivateMedia
from clipflow.render import Cue, probe, render
from clipflow.transcription import Transcriber, TranscriptionUnavailable


def render_job(queue, job, data, source, output, transcriber):
    if os.environ.get('CLIPFLOW_INTERNAL_RENDER_PREVIEW') == 'true':
        info = probe(source)
        if float(info['format']['duration']) > 120 or any(
                stream.get('width', 0) > 1920 or stream.get('height', 0) > 1920
                for stream in info['streams']):
            raise ValueError('Preview source exceeds the two-minute or 1920-pixel limit')
    start_time, end_time = data['start'], data['end']
    cues = [Cue(**cue) for cue in data['cues']]
    if data.get('automatic_captions'):
        if transcriber is None:
            raise TranscriptionUnavailable('Automatic captions are paused.')
        cues = transcriber.captions(queue, job, source, start_time, end_time)
    if data.get('batch_parent'):
        music = source.parent / 'music' if 'music_start' in data else None
        return render(source, output, start_time, end_time, cues,
                      caption_color=PALETTES[data['caption_style']], music=music,
                      music_start=data.get('music_start', 0), output_limit=BATCH_OUTPUT_BYTES)
    if os.environ.get('CLIPFLOW_INTERNAL_RENDER_PREVIEW') == 'true':
        return render(source, output, start_time, end_time, cues, output_limit=BATCH_OUTPUT_BYTES)
    return render(source, output, start_time, end_time, cues)


def work(root, queue, job, transcriber=None, media=None, owner_id=None):
    data = json.loads(job['spec'])
    directory = root / job['id']
    output = directory / (job['lease_token'] + '.mp4')
    start = time.monotonic()
    remote = data.get('storage') == 'r2'
    try:
        if data.get('batch'):
            stage_batch(root, queue, job, data, transcriber)
            return
        if remote:
            if not media:
                raise TranscriptionUnavailable('Private cloud storage is unavailable.')
            with TemporaryDirectory(prefix='media-', dir=root) as scratch:
                source = Path(scratch) / 'source'
                media.stage_source(owner_id, job['id'], etag=data['etag'], size=data['size'],
                                   destination=source)
                result = render_job(queue, job, data, source, Path(scratch) / 'output.mp4', transcriber)
                media.save_output(owner_id, job['id'], job['lease_token'], Path(scratch) / 'output.mp4')
        else:
            source_directory = root / data.get('batch_parent', job['id'])
            directory.mkdir(mode=0o700, exist_ok=True)
            result = render_job(queue, job, data, source_directory / 'source', output, transcriber)
    except (BatchError, TranscriptionUnavailable) as error:
        queue.finish(job, error=str(error))
    except (ValueError, OSError, KeyError, StopIteration):
        queue.finish(job, error='Source or clip could not be processed. Check the video and clip range.')
    except Exception:
        queue.finish(job, error='The renderer or private storage could not process this source.')
    else:
        if not queue.finish(job, elapsed=time.monotonic() - start, output_bytes=result['output_bytes']):
            if remote:
                try:
                    media.drop_output(owner_id, job['id'], job['lease_token'])
                except Exception:
                    # R2 lifecycle expiration also bounds orphaned attempts.
                    pass
            else:
                output.unlink(missing_ok=True)


def sweep(root, queue, media, owner_id, *, now, source_seconds, output_seconds):
    for job in queue.expiring(now - source_seconds, now - output_seconds):
        spec = json.loads(job['spec'])
        try:
            if spec.get('storage') == 'r2':
                if not media:
                    continue
                media.drop_source(owner_id, job['id'])
                if job['state'] == 'expired' and job['lease_token']:
                    media.drop_output(owner_id, job['id'], job['lease_token'])
            else:
                directory = root / job['id']
                if job['state'] == 'expired':
                    if directory.exists():
                        shutil.rmtree(directory)
                else:
                    (directory / 'source').unlink(missing_ok=True)
                    (directory / 'music').unlink(missing_ok=True)
                    (directory / 'captions').unlink(missing_ok=True)
            queue.reclaimed(job, spec.get('size', 0))
        except Exception:
            print(f"Media cleanup will retry for job {job['id']}", file=sys.stderr)
    for directory in root.glob('media-*'):
        try:
            if directory.is_dir() and directory.stat().st_mtime < now - 86400:
                shutil.rmtree(directory)
        except FileNotFoundError:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    root = parser.parse_args().root.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    queue = Queue(root / 'jobs.sqlite3')
    transcriber = Transcriber.configured()
    plans = Plans(queue)
    plan_key = os.environ.get('OPENAI_API_KEY', '')
    media = PrivateMedia.configured()
    owner_id = os.environ.get('CLIPFLOW_OWNER_ID')
    if media and not owner_id:
        parser.error('Private cloud storage requires a configured owner ID')
    source_seconds = max(1, int(os.environ.get('CLIPFLOW_SOURCE_RETENTION_HOURS', '24'))) * 3600
    output_seconds = max(1, int(os.environ.get('CLIPFLOW_OUTPUT_RETENTION_HOURS', '168'))) * 3600
    next_sweep = 0
    while True:
        now = time.time()
        if now >= next_sweep:
            sweep(root, queue, media, owner_id, now=now, source_seconds=source_seconds,
                  output_seconds=output_seconds)
            next_sweep = now + 300
        job = queue.claim()
        if job:
            work(root, queue, job, transcriber, media, owner_id)
        elif not plans.process_one(plan_key, planner_budget()):
            time.sleep(0.5)


if __name__ == '__main__':
    main()
