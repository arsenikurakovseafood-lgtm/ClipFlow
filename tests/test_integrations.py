import json
from io import BytesIO
import tempfile
import unittest
from contextlib import closing
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock
from uuid import uuid4

from clipflow.auth import OwnerAuth
from clipflow.queue import Queue
from clipflow.r2 import PrivateMedia
from clipflow.render import run
from clipflow.transcription import Transcriber
from clipflow.web import OwnerAPI
from clipflow.worker import work


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.queue = Queue(self.root / 'jobs.sqlite3')

    @staticmethod
    def opener(payload):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        return opener

    def test_owner_session_and_r2_job(self):
        owner_id = str(uuid4())
        auth = OwnerAuth('https://example.supabase.co', 'fixture', owner_id, 'x' * 40,
                         self.opener({'user': {'id': owner_id}, 'expires_in': 120}))
        self.queue.bind_owner(owner_id)
        with self.assertRaises(ValueError):
            self.queue.bind_owner(str(uuid4()))
        source = self.root / 'fixture.mp4'
        self.fixture(source)
        sdk = MagicMock()
        sdk.generate_presigned_url.side_effect = lambda op, **kw: (
            'https://fixture.r2.cloudflarestorage.com/private/' + op)
        sdk.head_object.return_value = {'ContentType': 'video/mp4', 'ContentLength': source.stat().st_size,
                                        'ETag': '"valid-revision"'}
        media = PrivateMedia(sdk, 'private-fixture')
        media.origin = 'https://fixture.r2.cloudflarestorage.com'
        server = ThreadingHTTPServer(('127.0.0.1', 0), OwnerAPI)
        server.auth, server.media, server.queue = auth, media, self.queue
        server.root, server.owner_id, server.transcription_enabled = self.root, owner_id, False
        runner = Thread(target=server.serve_forever, daemon=True)
        runner.start()

        def stop():
            server.shutdown()
            runner.join()
            server.server_close()

        self.addCleanup(stop)

        def request(method, path, body=None, headers=None):
            with closing(HTTPConnection(*server.server_address, timeout=5)) as connection:
                connection.request(method, path, body=body, headers=headers or {})
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read()

        self.assertEqual(request('GET', '/api/jobs')[0], 401)
        self.assertEqual(request('GET', '/')[1]['Location'], '/signin')
        login = json.dumps({'email': 'owner@example.test', 'password': 'fixture'})
        code, headers, _ = request('POST', '/api/session', login, {'Content-Type': 'application/json'})
        self.assertEqual(code, 200)
        self.assertIn('Secure; HttpOnly; SameSite=Strict', headers['Set-Cookie'])
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertFalse(auth.authenticated(cookie + 'x'))
        other = OwnerAuth('https://example.supabase.co', 'fixture', owner_id, 'x' * 40,
                          self.opener({'user': {'id': str(uuid4())}}))
        self.assertIsNone(other.login('other@example.test', 'fixture'))
        self.assertEqual(request('POST', '/api/uploads')[0], 401)
        upload_headers = {'Cookie': cookie, 'X-Upload-Mime': 'video/mp4',
                          'X-Upload-Size': str(source.stat().st_size),
                          'X-Clip-Start': '0', 'X-Clip-End': '2', 'Idempotency-Key': str(uuid4())}
        code, _, body = request('POST', '/api/uploads', headers=upload_headers)
        self.assertEqual(code, 201)
        reservation = json.loads(body)
        self.assertIn('put_object', reservation['url'])
        self.assertEqual(request('POST', f"/api/uploads/{reservation['id']}/complete",
                                 headers={'Cookie': cookie})[0], 202)
        job = self.queue.claim()
        with source.open('rb') as file:
            sdk.get_object.return_value = {'ContentLength': source.stat().st_size, 'Body': file}
            written_sizes = []
            sdk.put_object.side_effect = lambda **kwargs: written_sizes.append(len(kwargs['Body'].read()))
            work(self.root, self.queue, job, media=media, owner_id=owner_id)
        self.assertGreater(written_sizes[0], 0)
        self.assertEqual(sdk.get_object.call_args.kwargs['IfMatch'], '"valid-revision"')
        self.assertEqual(self.queue.get(job['id'])['state'], 'ready')
        self.assertEqual(request('GET', '/media/' + job['id'])[0], 401)
        code, headers, _ = request('GET', '/media/' + job['id'], headers={'Cookie': cookie})
        self.assertEqual(code, 307)
        self.assertIn('get_object', headers['Location'])
        self.assertTrue(sdk.generate_presigned_url.call_args.kwargs['Params']['Key'].endswith(job['lease_token'] + '.mp4'))
        self.assertEqual(list(self.root.glob('media-*')), [])

        batch_source = self.root / 'batch-fixture.mp4'
        self.fixture(batch_source, seconds=8)
        captions = b'WEBVTT\n\n00:00.000 --> 00:03.500\nPersistence is a habit.\n\n00:04.000 --> 00:07.500\nKeep showing up.\n'
        bundle = batch_source.read_bytes() + captions
        mime = 'application/octet-stream'
        batch_headers = {'Cookie': cookie, 'Content-Type': mime, 'Idempotency-Key': str(uuid4()),
                         'X-Source-Bytes': str(batch_source.stat().st_size), 'X-Music-Bytes': '0',
                         'X-Subtitle-Bytes': str(len(captions)), 'X-Batch-Mode': 'speech',
                         'X-Caption-Style': 'white', 'X-Clip-Count': '2', 'X-Release-Days': '3',
                         'X-Content-Goal': 'Persistence'}
        code, _, body = request('POST', '/api/batches', headers=batch_headers)
        self.assertEqual(code, 201)
        batch_id = json.loads(body)['id']
        self.assertEqual(sdk.generate_presigned_url.call_args.kwargs['Params']['ContentLength'], len(bundle))
        self.assertEqual(sdk.generate_presigned_url.call_args.kwargs['Params']['ContentType'], mime)
        sdk.head_object.return_value = {'ContentType': mime, 'ContentLength': len(bundle) - 1, 'ETag': 'wrong'}
        complete = f'/api/uploads/{batch_id}/complete'
        self.assertEqual(request('POST', complete, headers={'Cookie': cookie})[0], 409)
        sdk.head_object.return_value.update(ContentLength=len(bundle), ETag='"batch-revision"')
        self.assertEqual(request('POST', complete, headers={'Cookie': cookie})[0], 202)
        sdk.get_object.return_value = {'ContentLength': len(bundle), 'Body': BytesIO(bundle)}
        work(self.root, self.queue, self.queue.claim(), media=media, owner_id=owner_id)
        self.assertEqual(sdk.get_object.call_args.kwargs['IfMatch'], '"batch-revision"')
        self.assertEqual(self.queue.get(batch_id)['state'], 'prepared')
        for _ in range(2):
            child = self.queue.claim()
            work(self.root, self.queue, child, media=media, owner_id=owner_id)
            self.assertEqual(self.queue.get(child['id'])['state'], 'ready')
            self.assertEqual(request('GET', '/media/' + child['id'], headers={'Cookie': cookie})[0], 307)
            self.assertFalse((self.root / child['id'] / (child['lease_token'] + '.mp4')).exists())
        self.assertEqual(len(written_sizes), 3)

    @staticmethod
    def fixture(source, seconds=2):
        run('ffmpeg', '-nostdin', '-loglevel', 'error', '-f', 'lavfi', '-i',
            'color=c=black:s=320x180:r=30', '-f', 'lavfi', '-i', 'sine=frequency=440',
            '-t', str(seconds), '-c:v', 'libx264', '-c:a', 'aac', str(source))

    def test_transcription_reservation_and_cache(self):
        source = self.root / 'fixture.mp4'
        self.fixture(source)
        job, _ = self.queue.reserve('fixture', 'Clip', '{}', 1, cost=0, budget=0, quota=10)
        self.queue.uploaded(job)
        claim = self.queue.claim()
        too_low = Transcriber('fixture-key', 1, self.opener({'text': 'Fixture transcription'}))
        with self.assertRaisesRegex(ValueError, 'budget'):
            too_low.captions(self.queue, claim, source, 0, 2)
        too_low.opener.open.assert_not_called()
        client = Transcriber('fixture-key', 4500, self.opener({'text': 'Fixture transcription'}))
        caption, = client.captions(self.queue, claim, source, 0, 2)
        self.assertEqual((caption.start, caption.end, caption.text), (0, 2, 'Fixture transcription'))
        self.assertEqual(client.captions(self.queue, claim, source, 0, 2), [caption])
        self.assertEqual(client.opener.open.call_count, 1)
        request = client.opener.open.call_args.args[0]
        self.assertIn(b'gpt-transcribe', request.data)
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/audio/transcriptions')

    def test_worker_sweeps_source_then_output_and_reclaims_quota(self):
        from clipflow.worker import sweep
        job_id, _ = self.queue.reserve('fixture', 'Clip', '{"size":4}', 34, cost=0, budget=0, quota=40)
        directory = self.root / job_id
        directory.mkdir()
        (directory / 'source').write_bytes(b'test')
        self.queue.uploaded(job_id)
        job = self.queue.claim()
        output = directory / (job['lease_token'] + '.mp4')
        output.write_bytes(b'fixture video')
        self.queue.finish(job, output_bytes=13)
        completed = self.queue.get(job_id)['finished_at']
        sweep(self.root, self.queue, None, None, now=completed + 20, source_seconds=10, output_seconds=30)
        self.assertFalse((directory / 'source').exists())
        self.assertTrue(output.exists())
        self.assertEqual(self.queue.get(job_id)['bytes'], 30)
        sweep(self.root, self.queue, None, None, now=completed + 40, source_seconds=10, output_seconds=30)
        self.assertFalse(directory.exists())
        saved = self.queue.get(job_id)
        self.assertEqual((saved['state'], saved['bytes']), ('expired', 0))

    def test_ai_plan_is_review_only_and_fences_unconfirmed_requests(self):
        from clipflow.campaigns import Campaigns
        from clipflow.planner import Plans
        from clipflow.queue import Limit

        plans = Plans(self.queue)
        campaign_store = Campaigns(self.queue)
        goal = 'Publish weekly clips from my own recording.'
        with self.assertRaises(Limit):
            plans.request(goal, 1999)
        plans.request(goal, 4000)
        self.assertFalse(plans.process_one('', 4000))
        draft = {'name': 'Weekly recording', 'channel': 'youtube', 'duration_days': 21,
                 'cadence_days': 7, 'reason': 'Give each clip time for manual review.'}
        model = self.opener({'status': 'completed', 'output': [{
            'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(draft)}]
        }]})
        self.assertTrue(Plans(Queue(self.queue.path)).process_one('fixture', 4000, model))
        self.assertEqual(plans.list()[0]['result'], draft)
        self.assertEqual(campaign_store.snapshot()['campaigns'], [])
        self.assertFalse(plans.process_one('fixture', 4000, model))
        self.assertEqual(model.open.call_count, 1)
        plans.request(goal, 4000)
        self.assertTrue(plans.process_one('fixture', 4000, self.opener({'status': 'incomplete'})))
        self.assertEqual(plans.list()[0]['state'], 'failed')
        with self.assertRaises(Limit):
            plans.request(goal, 4000)
