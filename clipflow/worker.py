"""Independent cloud demonstration worker."""
import argparse
import json
import time
from pathlib import Path

from clipflow.queue import Queue
from clipflow.render import Cue, render


def work(root, queue, job):
    data = json.loads(job['spec'])
    directory = root / job['id']
    output = directory / (job['lease_token'] + '.mp4')
    start = time.monotonic()
    try:
        result = render(directory / 'source', output, data['start'], data['end'],
                        [Cue(**cue) for cue in data['cues']])
    except (ValueError, OSError, KeyError, StopIteration):
        queue.finish(job, error='Source or clip could not be processed. Check the video and clip range.')
    except Exception:
        queue.finish(job, error='The renderer timed out or could not decode this source.')
    else:
        if not queue.finish(job, elapsed=time.monotonic() - start, output_bytes=result['output_bytes']):
            output.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    root = parser.parse_args().root.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    queue = Queue(root / 'jobs.sqlite3')
    while True:
        job = queue.claim()
        if job:
            work(root, queue, job)
        else:
            time.sleep(0.5)


if __name__ == '__main__':
    main()
