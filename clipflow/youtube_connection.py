"""Owner OAuth enrollment for one explicitly configured YouTube channel."""
import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from clipflow.auth import NoRedirect
from clipflow.publishing import SERVICE, TOKEN, YouTubePublisher, publishing_enabled

CALLBACK = '/oauth/youtube/callback'
COOKIE = '__Secure-reelattice-youtube-flow'
SCOPES = ('https://www.googleapis.com/auth/youtube.upload',
          'https://www.googleapis.com/auth/youtube.readonly')
STATE_SECONDS = 600
CONFIG = ('CLIENT_ID', 'CLIENT_SECRET', 'CHANNEL_ID', 'OAUTH_ORIGIN', 'TOKEN_KEY')


class YouTubeConnection:
    def __init__(self, queue, client_id, secret, channel, origin, token_key, opener=None):
        from cryptography.fernet import Fernet

        self.queue = queue
        self.client_id, self.secret, self.channel = client_id, secret, channel
        self.redirect = origin.rstrip('/') + CALLBACK
        self.cipher = Fernet(token_key.encode('ascii'))
        self.opener = opener
        with queue.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS youtube_oauth (
                id INTEGER PRIMARY KEY CHECK(id=1), state_digest TEXT, expires_at INTEGER,
                verifier TEXT, channel_id TEXT, refresh_token BLOB)""")
            db.execute('INSERT OR IGNORE INTO youtube_oauth(id) VALUES (1)')

    @classmethod
    def configured(cls, queue):
        config = [os.environ.get('CLIPFLOW_YOUTUBE_' + name, '') for name in CONFIG]
        if not publishing_enabled() or not all(config):
            return None
        origin = urlsplit(config[3])
        if (not re.fullmatch(r'UC[A-Za-z0-9_-]{22}', config[2]) or origin.scheme != 'https'
                or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment
                or origin.path not in ('', '/')):
            raise ValueError('Configure a valid YouTube channel ID and HTTPS OAuth origin')
        return cls(queue, *config)

    def begin(self):
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        with self.queue.transaction() as db:
            db.execute('UPDATE youtube_oauth SET state_digest=?,expires_at=?,verifier=? WHERE id=1',
                       (self.digest(state), int(time.time()) + STATE_SECONDS, verifier))
        query = urlencode(dict(client_id=self.client_id, redirect_uri=self.redirect, response_type='code',
                               scope=' '.join(SCOPES), access_type='offline', prompt='consent', state=state,
                               code_challenge=challenge, code_challenge_method='S256'))
        return 'https://accounts.google.com/o/oauth2/v2/auth?' + query, state

    @staticmethod
    def digest(state):
        return hashlib.sha256(state.encode('ascii')).hexdigest()

    def complete(self, code, state, raw_cookie):
        cookies = SimpleCookie()
        try:
            cookies.load(raw_cookie)
            valid = bool(re.fullmatch(r'[A-Za-z0-9_-]{43}', state)
                         and hmac.compare_digest(cookies[COOKIE].value, state))
        except (CookieError, KeyError, TypeError):
            valid = False
        if not valid:
            raise ValueError('OAuth state mismatch')
        with self.queue.transaction() as db:
            row = db.execute('SELECT verifier FROM youtube_oauth WHERE id=1 AND state_digest=? AND expires_at>? AND verifier IS NOT NULL',
                             (self.digest(state), int(time.time()))).fetchone()
            if not row:
                raise ValueError('OAuth attempt expired or already used')
            db.execute('UPDATE youtube_oauth SET verifier=NULL WHERE id=1')
        if not code or len(code) > 2048:
            raise ValueError('Google did not return an authorization code')
        publisher = YouTubePublisher(self.client_id, self.secret, '', self.channel, self.opener)
        body = urlencode(dict(client_id=self.client_id, client_secret=self.secret, code=code,
                              grant_type='authorization_code', redirect_uri=self.redirect,
                              code_verifier=row['verifier'])).encode()
        grant = publisher.json(TOKEN, data=body)
        if not set(SCOPES).issubset(grant.get('scope', '').split()) or not grant.get('refresh_token'):
            raise ValueError('Both YouTube permissions and offline access are required')
        # Verify the identity held by the refresh token the worker will actually use.
        publisher = YouTubePublisher(self.client_id, self.secret, grant['refresh_token'], self.channel, self.opener)
        publisher.check_channel(publisher.token())
        with self.queue.transaction() as db:
            if not db.execute("""UPDATE youtube_oauth SET channel_id=?,refresh_token=?,state_digest=NULL,expires_at=NULL
                    WHERE id=1 AND state_digest=? AND expires_at>? AND verifier IS NULL""",
                              (self.channel, self.cipher.encrypt(grant['refresh_token'].encode()),
                               self.digest(state), int(time.time()))).rowcount:
                raise ValueError('OAuth attempt expired or was replaced')

    def connected(self):
        with self.queue.transaction() as db:
            return bool(db.execute('SELECT 1 FROM youtube_oauth WHERE id=1 AND channel_id=? AND refresh_token IS NOT NULL',
                                   (self.channel,)).fetchone())

    def publisher(self):
        from cryptography.fernet import InvalidToken

        with self.queue.transaction() as db:
            row = db.execute('SELECT refresh_token FROM youtube_oauth WHERE id=1 AND channel_id=?',
                             (self.channel,)).fetchone()
        if not row or not row['refresh_token']:
            return None
        try:
            refresh_token = self.cipher.decrypt(row['refresh_token']).decode()
        except InvalidToken:
            return None
        return YouTubePublisher(self.client_id, self.secret, refresh_token, self.channel, self.opener)

    def disconnect(self):
        from cryptography.fernet import InvalidToken

        with self.queue.transaction() as db:
            row = db.execute('SELECT refresh_token FROM youtube_oauth WHERE id=1').fetchone()
            db.execute("""UPDATE youtube_oauth SET state_digest=NULL,expires_at=NULL,verifier=NULL,
                channel_id=NULL,refresh_token=NULL WHERE id=1""")
        if not row['refresh_token']:
            return True
        try:
            token = self.cipher.decrypt(row['refresh_token']).decode()
            request = Request('https://oauth2.googleapis.com/revoke', data=urlencode({'token': token}).encode())
            with (self.opener or build_opener(NoRedirect)).open(request, timeout=8):
                return True
        except (InvalidToken, OSError):
            return False


def flow_cookie(state='', age=0):
    return f'{COOKIE}={state}; Path={CALLBACK}; Max-Age={age}; Secure; HttpOnly; SameSite=Lax'
