import json
import tempfile
import unittest
from pathlib import Path

from clipflow.batch import BATCH_OUTPUT_BYTES, parse_captions, speech_windows
from clipflow.queue import Queue
from clipflow.render import Cue, probe, run
from clipflow.worker import work


class BatchTests(unittest.TestCase):
    def test_speech_selection_prioritizes_goal_and_keeps_whole_nonoverlapping_clips(self):
        cues = parse_captions("""WEBVTT

00:00.000 --> 00:03.500
Last night's football scores.

00:04.000 --> 00:07.500
Persistence makes a difficult goal possible.

00:08.000 --> 00:12.000
Keep showing up for your goal.
""")
        self.assertEqual(speech_windows(cues, 12, 'Persistence', 1, 4), [(4, 7.5)])
        self.assertEqual(speech_windows(cues, 12, 'Persistence', 3, 10),
                         [(0, 3.5), (4, 7.5), (8, 12)])
        self.assertEqual(speech_windows([Cue(0, 4, 'An unfinished thought')], 10, 'goal', 2, 10), [])

    def test_real_music_batch_has_distinct_outputs_private_audio_and_release_days(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            queue = Queue(root / 'jobs.sqlite')
            spec = {'batch': True, 'mode': 'music', 'goal': 'Promote my track', 'count': 2,
                    'days': 3, 'caption_style': 'pink', 'source_seconds': 120, 'clip_seconds': 10}
            job_id, _ = queue.reserve('test', 'My batch', json.dumps(spec), 4 * BATCH_OUTPUT_BYTES,
                                       cost=0, budget=0, quota=250 * 1024 * 1024)
            batch = root / job_id
            batch.mkdir()
            run('ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                'color=black:size=320x180:rate=30', '-t', '7', '-c:v', 'libx264',
                '-f', 'mp4', str(batch / 'source'))
            run('ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440',
                '-t', '4', '-f', 'wav', str(batch / 'music'))
            source_subtitles = '1\n00:00:00,000 --> 00:00:01,000\nMusic preview\n'
            (batch / 'captions').write_text(source_subtitles)
            queue.uploaded(job_id)
            work(root, queue, queue.claim())
            self.assertEqual(queue.get(job_id)['state'], 'prepared')
            for _ in range(2):
                work(root, queue, queue.claim())
            clips = [job for job in queue.all() if job['state'] == 'ready']
            self.assertEqual(len(clips), 2)
            self.assertEqual({job['release_day'] for job in clips}, {1, 2})
            self.assertEqual(len({json.loads(queue.get(job['id'])['spec'])['start'] for job in clips}), 2)
            for job in clips:
                streams = probe(root / job['id'] / (job['lease_token'] + '.mp4'))['streams']
                self.assertEqual([(s['codec_type'], s['codec_name']) for s in streams],
                                 [('video', 'h264'), ('audio', 'aac')])

    def test_direct_r2_video_download_is_bounded_and_rejects_other_hosts(self):
        from io import BytesIO
        from unittest.mock import Mock
        from clipflow.batch import direct_source_url, fetch_source

        host = 'pub-' + 'a' * 32 + '.r2.dev'
        url = 'https://' + host + '/authorized.mp4'
        for candidate in ('http://' + host + '/file', 'https://youtube.com/watch?v=123',
                          'https://' + host + '@localhost/file', 'https://' + host + '.example.com/file'):
            with self.assertRaises(ValueError):
                direct_source_url(candidate)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'source'
            opener = Mock()
            stream = BytesIO(b'preview fixture')
            stream.headers = {'Content-Length': str(len(stream.getvalue()))}
            stream.status = 200
            opener.open.return_value = stream
            fetch_source(url, output, opener)
            self.assertEqual(output.read_bytes(), b'preview fixture')
