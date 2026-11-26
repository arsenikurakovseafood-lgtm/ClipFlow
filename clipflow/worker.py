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
from clipflow.insights import Insights
from clipflow.planner import Plans, planner_budget
from clipflow.queue import Queue, source_retention_seconds
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
    music = source.parent / 'music' if 'music_start' in data else None
    if data.get('automatic_captions'):
        if transcriber is None:
            raise TranscriptionUnavailable('Automatic captions are paused.')
        if music is None:
            cues = transcriber.captions(queue, job, source, start_time, end_time)
        else:
            offset = data['music_start']
            end = min(offset + end_time - start_time, float(probe(music)['format']['duration']))
            timed = transcriber.captions(queue, job, music, offset, end)
            cues = [Cue(cue.start - offset + start_time, cue.end - offset + start_time, cue.text)
                    for cue in timed]
    if data.get('batch_parent'):
        overlays = [Cue(**cue) for cue in data.get('overlays', [])]
        return render(source, output, start_time, end_time, cues,
                      caption_color=PALETTES[data['caption_style']], music=music,
                      music_start=data.get('music_start', 0), output_limit=BATCH_OUTPUT_BYTES,
                      overlays=overlays)
    if os.environ.get('CLIPFLOW_INTERNAL_RENDER_PREVIEW') == 'true':
        return render(source, output, start_time, end_time, cues, output_limit=BATCH_OUTPUT_BYTES)
    return render(source, output, start_time, end_time, cues)


def stage_private_batch(directory, job_id, data, media, owner_id):
    directory.mkdir(mode=0o700, exist_ok=True)
    complete = directory / 'bundle-staged'
    if not data['size'] or complete.exists():
        return
    with TemporaryDirectory(prefix='.r2-bundle-', dir=directory) as scratch:
        scratch = Path(scratch)
        bundle = scratch / 'bundle'
        media.stage_source(owner_id, job_id, etag=data['etag'], size=data['size'], destination=bundle)
        with bundle.open('rb') as source:
            for name in ('source', 'music', 'captions'):
                size = data['parts'][name]
                if not size:
                    continue
                item = scratch / name
                with item.open('xb') as output:
                    remaining = size
                    while remaining:
                        chunk = source.read(min(remaining, 65536))
                        if not chunk:
                            raise OSError('Incomplete batch bundle')
                        output.write(chunk)
                        remaining -= len(chunk)
                item.replace(directory / name)
        complete.touch(mode=0o600)


def work(root, queue, job, transcriber=None, media=None, owner_id=None):
    data = json.loads(job['spec'])
    directory = root / job['id']
    output = directory / (job['lease_token'] + '.mp4')
    start = time.monotonic()
    remote = data.get('storage') == 'r2'
    try:
        if remote and media is None:
            raise TranscriptionUnavailable('Private cloud storage is unavailable.')
        if data.get('batch'):
            if remote:
                stage_private_batch(directory, job['id'], data, media, owner_id)
            stage_batch(root, queue, job, data, transcriber)
            return
        if remote and not data.get('batch_parent'):
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
            if remote:
                try:
                    media.save_output(owner_id, job['id'], job['lease_token'], output)
                finally:
                    output.unlink(missing_ok=True)
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
                if spec.get('size'):
                    media.drop_source(owner_id, job['id'])
                if job['state'] == 'expired' and job['lease_token'] and not spec.get('batch'):
                    media.drop_output(owner_id, job['id'], job['lease_token'])
            if spec.get('storage') != 'r2' or spec.get('batch') or spec.get('batch_parent'):
                directory = root / job['id']
                if job['state'] == 'expired':
                    if directory.exists():
                        shutil.rmtree(directory)
                else:
                    (directory / 'source').unlink(missing_ok=True)
                    (directory / 'music').unlink(missing_ok=True)
                    (directory / 'captions').unlink(missing_ok=True)
                    (directory / 'source-replacement').unlink(missing_ok=True)
                    (directory / 'bundle-staged').unlink(missing_ok=True)
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
    insights = Insights(queue)
    plan_key = os.environ.get('OPENAI_API_KEY', '')
    media = PrivateMedia.configured()
    owner_id = os.environ.get('CLIPFLOW_OWNER_ID')
    if media and not owner_id:
        parser.error('Private cloud storage requires a configured owner ID')
    source_seconds = source_retention_seconds()
    output_seconds = max(1, int(os.environ.get('CLIPFLOW_OUTPUT_RETENTION_HOURS', '168'))) * 3600
    next_sweep = 0
    while True:
        now = time.time()
        if now >= next_sweep:
            sweep(root, queue, media, owner_id, now=now, source_seconds=source_seconds,
                  output_seconds=output_seconds)
            insights.expire_platform_metrics(now)
            next_sweep = now + 300
        job = queue.claim()
        if job:
            work(root, queue, job, transcriber, media, owner_id)
        elif not plans.process_one(plan_key, planner_budget()):
            time.sleep(0.5)


if __name__ == '__main__':
    main()
