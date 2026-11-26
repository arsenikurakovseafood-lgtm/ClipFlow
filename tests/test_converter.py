import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from clipflow.converter import API, CONVERSION_FAILED, USAGE_API, ConversionError, VidFetch, segment_range
from clipflow.queue import Queue
from clipflow.render import probe, run
from clipflow.worker import work


class ConverterTests(unittest.TestCase):
    def test_timecodes_require_a_bounded_forward_range(self):
        self.assertEqual(segment_range('12:00', '00:13:00'), {'start': 720, 'end': 780})
        for pair in [('01:60', '02:05'), ('15', '12'), ('1:00', '3:01'), ('', '80'),
                     ('12:00:00', '12:00:03')]:
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                segment_range(*pair)

    def test_converter_only_stages_the_selected_range_and_real_clips_render(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = Queue(root / 'jobs.sqlite3')
            window = {'start': 720, 'end': 728}
            url = 'https://www.youtube.com/watch?v=abcdefghijk'
            spec = {'batch': True, 'mode': 'speech', 'goal': 'Test range', 'count': 2, 'days': 3,
                    'caption_style': 'pink', 'source_seconds': 120, 'clip_seconds': 10,
                    'source_url': url, 'trim': window}
            batch_id, _ = queue.reserve('batch', 'Range', json.dumps(spec), 24, cost=0, budget=0, quota=100)
            target = root / batch_id
            target.mkdir()
            (target / 'captions').write_text('WEBVTT\n\n12:00.000 --> 12:03.500\nStart of selected range.\n\n'
                                             '12:04.000 --> 12:08.000\nEnd of selected range.\n')
            sample = root / 'segment.mp4'
            run('ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                'color=c=blue:s=320x180:r=30', '-t', '8', '-c:v', 'libx264', str(sample))
            media = sample.read_bytes()
            download = BytesIO(media)
            download.status = 200
            download.headers = {'Content-Type': 'video/mp4', 'Content-Length': str(len(media))}
            origin = 'https://delivery.example.com'
            remote_id = 'dl_converter_fixture'
            opener = Mock()
            usage = {'plan': 'free', 'remaining_gb': 0.8, 'payg_balance_cents': 0,
                     'pack_remaining_gb': 0, 'active_jobs': 0}
            opener.open.side_effect = [
                BytesIO(json.dumps(usage).encode()),
                BytesIO(json.dumps({'id': remote_id}).encode()),
                BytesIO(json.dumps({'id': remote_id, 'status': 'completed', 'trim': window,
                                    'size_bytes': len(media), 'download_url': origin + '/segment.mp4'}).encode()),
                download,
                BytesIO(),
            ]
            converter = VidFetch('fixture-key', origin, limit=1, opener=opener, free_only=True)
            queue.uploaded(batch_id)
            work(root, queue, queue.claim(), converter=converter)
            self.assertEqual(queue.get(batch_id)['state'], 'prepared')
            preflight, create, status, fetch, cleanup = [call.args[0] for call in opener.open.call_args_list]
            self.assertEqual((preflight.get_method(), preflight.full_url), ('GET', USAGE_API))
            self.assertEqual((create.get_method(), create.full_url), ('POST', API))
            self.assertEqual(json.loads(create.data), {'url': url, 'format': '360p', 'trim': window, 'destination': 'url'})
            self.assertEqual((status.get_method(), status.full_url), ('GET', API + '/' + remote_id))
            self.assertIsNone(fetch.get_header('Authorization'))
            self.assertEqual((cleanup.get_method(), cleanup.full_url), ('DELETE', API + '/' + remote_id))
            for start in (0, 4):
                clip = queue.claim()
                self.assertEqual(json.loads(clip['spec'])['start'], start)
                work(root, queue, clip)
                self.assertEqual(queue.get(clip['id'])['state'], 'ready')
                output = root / clip['id'] / (clip['lease_token'] + '.mp4')
                video = probe(output)['streams'][0]
                self.assertEqual((video['width'], video['height']), (720, 1280))

    def test_delivery_origin_and_unconfirmed_requests_are_fenced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = Queue(root / 'jobs.sqlite3')
            job_id, _ = queue.reserve('first', 'First', '{}', 1, cost=0, budget=0, quota=10)
            queue.uploaded(job_id)
            job = queue.claim()
            self.assertEqual(queue.reserve_conversion(job, 1), (None, True))
            self.assertEqual(queue.reserve_conversion(job, 1), (None, False))
            second, _ = queue.reserve('second', 'Second', '{}', 1, cost=0, budget=0, quota=10)
            queue.uploaded(second)
            self.assertEqual(queue.reserve_conversion(queue.claim(), 1), (None, False))
            opener = Mock()
            converter = VidFetch('fixture-key', 'https://delivery.example.com', 1, opener)
            with self.assertRaisesRegex(ConversionError, 'selected segment'):
                converter.download('https://delivery.example.com@localhost/file', root / 'source', 8)
            opener.open.assert_not_called()
            with self.assertRaisesRegex(ConversionError, 'selected segment'):
                converter.stage(queue, job, 'https://www.youtube.com/watch?v=abcdefghijk',
                                {'start': 0, 'end': 8}, root / 'source')
            opener.open.assert_not_called()
            self.assertFalse((root / 'source').exists())
            self.assertIn('selected segment', CONVERSION_FAILED)

    def test_free_mode_never_submits_on_funded_or_unconfirmed_accounts(self):
        quota = {'plan': 'free', 'remaining_gb': 0.8, 'payg_balance_cents': 0,
                 'pack_remaining_gb': 0, 'active_jobs': 0}
        for unsafe in [{'plan': 'starter'}, {'remaining_gb': 0.01}, {'payg_balance_cents': 1},
                       {'pack_remaining_gb': 0.1}, {'active_jobs': 1}]:
            with self.subTest(unsafe=unsafe):
                opener = Mock()
                opener.open.return_value = BytesIO(json.dumps(quota | unsafe).encode())
                queue = Mock()
                queue.reserve_conversion.return_value = (None, True)
                adapter = VidFetch('fixture-key', '', 1, opener, free_only=True)
                with self.assertRaisesRegex(ConversionError, 'free quota'):
                    adapter.stage(queue, {'id': 'sample'}, 'https://youtu.be/abcdefghijk',
                                  {'start': 0, 'end': 30}, Path('unused.mp4'))
                self.assertEqual(opener.open.call_count, 1)
                self.assertEqual(opener.open.call_args.args[0].full_url, USAGE_API)

    def test_render_free_mode_needs_no_persistent_disk_and_hides_key_from_web(self):
        from clipflow.render_preview import DATA, service_settings

        environment = {'CLIPFLOW_VIDFETCH_FREE_ONLY': 'true', 'CLIPFLOW_VIDFETCH_API_KEY': 'fixture'}
        with patch.dict('os.environ', environment, clear=True), \
                patch('clipflow.render_preview.os.path.ismount', return_value=False):
            root, web, worker = service_settings()
        self.assertEqual(root, DATA)
        self.assertEqual(web['CLIPFLOW_VIDFETCH_MONTHLY_JOBS'], '5')
        self.assertNotIn('CLIPFLOW_VIDFETCH_API_KEY', web)
        self.assertEqual(worker['CLIPFLOW_VIDFETCH_API_KEY'], 'fixture')
        self.assertEqual(worker['CLIPFLOW_VIDFETCH_FREE_ONLY'], 'true')
