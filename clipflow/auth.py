"""Supabase password authentication restricted to one pre-provisioned owner."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from http.cookies import CookieError, SimpleCookie
from threading import Lock
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

COOKIE = '__Host-clipflow'
SESSION_SECONDS = 3600


class LoginUnavailable(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class OwnerAuth:
    def __init__(self, url, key, owner, secret, opener=None):
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or (
                parts.path not in ('', '/') or parts.query or parts.fragment):
            raise ValueError('CLIPFLOW_SUPABASE_URL must be an HTTPS origin')
        self.url = url.rstrip('/')
        self.key = key
        self.owner = str(UUID(owner))
        self.secret = secret.encode()
        if not self.key or len(self.secret) < 32:
            raise ValueError('Supabase publishable key and a 32-character session secret are required')
        self.opener = opener or build_opener(NoRedirect)
        self.lock = Lock()
        self.attempts = []

    @classmethod
    def configured(cls):
        keys = ('SUPABASE_URL', 'SUPABASE_KEY', 'OWNER_ID', 'SESSION_SECRET')
        values = [os.environ.get('CLIPFLOW_' + key, '') for key in keys]
        if not any(values):
            return None
        if not all(values):
            raise ValueError('Configure all four ClipFlow owner authentication settings')
        return cls(*values)

    def allow_attempt(self):
        now = time.monotonic()
        with self.lock:
            self.attempts = [attempt for attempt in self.attempts if attempt > now - 60]
            if len(self.attempts) >= 12:
                return False
            self.attempts.append(now)
            return True

    def login(self, email, password):
        request = Request(self.url + '/auth/v1/token?grant_type=password',
                          data=json.dumps({'email': email, 'password': password}).encode(),
                          headers={'apikey': self.key, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=8) as response:
                result = json.loads(response.read(128 * 1024))
        except HTTPError as error:
            if error.code in (400, 401, 403):
                return None
            raise LoginUnavailable from error
        except (OSError, ValueError) as error:
            raise LoginUnavailable from error
        if not isinstance(result, dict) or not isinstance(result.get('user'), dict):
            raise LoginUnavailable
        if result['user'].get('id') != self.owner:
            return None
        ttl = result.get('expires_in', SESSION_SECONDS)
        if type(ttl) is not int or ttl <= 0:
            raise LoginUnavailable
        return self.issue(min(ttl, SESSION_SECONDS))

    def issue(self, ttl):
        payload = f'{int(time.time()) + ttl}.{secrets.token_urlsafe(24)}'
        signature = self._signature(payload)
        return f'{payload}.{signature}', ttl

    def _signature(self, payload):
        digest = hmac.new(self.secret, (self.owner + '.' + payload).encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')

    def authenticated(self, raw):
        try:
            cookies = SimpleCookie()
            cookies.load(raw)
            token = cookies[COOKIE].value
            expiry, nonce, signature = token.split('.')
            return (expiry.isascii() and nonce.isascii() and signature.isascii()
                    and int(expiry) > time.time()
                    and hmac.compare_digest(signature, self._signature(expiry + '.' + nonce)))
        except (CookieError, KeyError, ValueError):
            return False


def session_header(token, ttl):
    return f'{COOKIE}={token}; Path=/; Max-Age={ttl}; Secure; HttpOnly; SameSite=Strict'
