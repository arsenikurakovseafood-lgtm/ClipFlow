"""Cloud-side entry point for testing the renderer with a timestamped transcript."""
import argparse
import json
from pathlib import Path

from clipflow.render import Cue, render


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--start', type=float, required=True)
    parser.add_argument('--end', type=float, required=True)
    parser.add_argument('--captions', type=Path)
    args = parser.parse_args()
    cues = []
    if args.captions:
        if args.captions.stat().st_size > 1024 * 1024:
            parser.error('Caption file exceeds 1 MiB')
        cues = [Cue(**item) for item in json.loads(args.captions.read_text(encoding='utf-8'))]
    print(json.dumps(render(args.source, args.output, args.start, args.end, cues)))


if __name__ == '__main__':
    main()
