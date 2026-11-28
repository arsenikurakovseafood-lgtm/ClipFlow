import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet

from clipflow.queue import Queue
from clipflow.youtube_connection import COOKIE, SCOPES, YouTubeConnection

CHANNEL = 'UC' + 'a' * 22


class GoogleFixture:
    def __init__(self, channel=CHANNEL):
        self.channel = channel
        self.exchanges = 0

    def open(self, request, timeout):
        url = urlsplit(request.full_url)
        if url.hostname == 'oauth2.googleapis.com':
            grant = parse_qs(request.data.decode())
            if url.path == '/revoke':
                assert grant['token'] == ['fixture-refresh']
                return io.BytesIO()
            if grant['grant_type'] == ['authorization_code']:
                self.exchanges += 1
                assert len(grant['code_verifier'][0]) >= 43
                assert grant['redirect_uri'] == ['https://workspace.example/oauth/youtube/callback']
                payload = {'refresh_token': 'fixture-refresh', 'scope': ' '.join(SCOPES)}
            else:
                assert grant['refresh_token'] == ['fixture-refresh']
                payload = {'access_token': 'fixture-access'}
        else:
            assert url.hostname == 'www.googleapis.com'
            assert request.headers['Authorization'] == 'Bearer fixture-access'
            payload = {'items': [{'id': self.channel}]}
        return io.BytesIO(json.dumps(payload).encode())


class YouTubeConnectionTests(unittest.TestCase):
    def test_callback_verifies_browser_channel_and_single_use_then_recovers_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = Queue(Path(directory) / 'queue.db')
            google = GoogleFixture()
            setup = ('fixture-client', 'fixture-secret', CHANNEL, 'https://workspace.example',
                     Fernet.generate_key().decode(), google)
            connection = YouTubeConnection(queue, *setup)
            url, state = connection.begin()
            params = parse_qs(urlsplit(url).query)
            self.assertEqual(params['code_challenge_method'], ['S256'])
            self.assertEqual(params['access_type'], ['offline'])
            self.assertFalse(connection.connected())
            with self.assertRaises(ValueError):
                connection.complete('fixture', state, COOKIE + '=different')
            self.assertEqual(google.exchanges, 0)
            cookies = COOKIE + '=' + state
            connection.complete('fixture', state, cookies)
            with self.assertRaises(ValueError):
                connection.complete('fixture', state, cookies)
            self.assertEqual(google.exchanges, 1)
            with queue.transaction() as db:
                stored = db.execute('SELECT refresh_token FROM youtube_oauth').fetchone()['refresh_token']
            self.assertNotIn(b'fixture-refresh', stored)
            restarted = YouTubeConnection(Queue(queue.path), *setup)
            self.assertEqual(restarted.publisher().token(), 'fixture-access')
            self.assertTrue(restarted.disconnect())
            self.assertIsNone(connection.publisher())

    def test_wrong_channel_is_never_connected(self):
        with tempfile.TemporaryDirectory() as directory:
            google = GoogleFixture('UC' + 'b' * 22)
            connection = YouTubeConnection(Queue(Path(directory) / 'queue.db'), 'id', 'secret', CHANNEL,
                                           'https://workspace.example', Fernet.generate_key().decode(), google)
            _, state = connection.begin()
            with self.assertRaisesRegex(ValueError, 'does not match'):
                connection.complete('fixture', state, COOKIE + '=' + state)
            self.assertIsNone(connection.publisher())
