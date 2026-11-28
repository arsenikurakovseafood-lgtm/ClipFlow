import tempfile
import time
import unittest
from pathlib import Path

from clipflow.render import Cue, render, run, subtitles


class RenderTest(unittest.TestCase):
    def test_subtitles_are_rebased_and_trimmed(self):
        self.assertEqual(
            subtitles([Cue(0, 2, '<Hello>'), Cue(2, 4, 'World')], 1, 3),
            '1\n00:00:00,000 --> 00:00:01,000\n‹Hello›\n\n'
            '2\n00:00:01,000 --> 00:00:02,000\nWorld\n',
        )

    def test_real_vertical_export_and_subtitle_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output, plain = (Path(directory) / name for name in ('source.mp4', 'clip.mp4', 'plain.mp4'))
            run('ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=black:size=640x360:rate=30',
                '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '4',
                '-c:v', 'libx264', '-c:a', 'aac', str(source))
            start = time.monotonic()
            result = render(source, output, 1, 3, [Cue(1.5, 2.5, 'Cloud render fixture')])
            print(f'\nRender wall time: {time.monotonic() - start:.2f}s, {result}')
            render(source, plain, 1, 3, [])
            for position, changed in [(0.2, False), (1, True), (1.8, False)]:
                def frame_hash(path):
                    return run('ffmpeg', '-v', 'error', '-ss', str(position), '-i', str(path),
                               '-map', '0:v:0', '-frames:v', '1', '-f', 'md5', '-')
                self.assertEqual(frame_hash(output) != frame_hash(plain), changed)
            self.assertEqual(list(Path(directory).glob('.clipflow-*')), [])
            with self.assertRaises(ValueError):
                render(source, output, 3, 5, [])
            self.assertEqual(output.stat().st_size, result['output_bytes'])
