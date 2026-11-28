"""Single-service, password-protected Render preview with ephemeral storage."""
import os
import signal
import subprocess
import sys
import time

from clipflow.auth import PreviewAuth
from clipflow.converter import VidFetch
from clipflow.publishing import SECRET_NAMES, YouTubePublisher

DATA = '/var/lib/clipflow'
PERSISTENT_DATA = '/var/data'


def service_settings():
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(('CLIPFLOW_', 'OPENAI_'))}
    env['CLIPFLOW_INTERNAL_RENDER_PREVIEW'] = 'true'
    path = PERSISTENT_DATA if os.path.ismount(PERSISTENT_DATA) and os.access(PERSISTENT_DATA, os.W_OK) else DATA
    owner_env, worker_env = dict(env), dict(env)
    if path == PERSISTENT_DATA and YouTubePublisher.configured():
        owner_env['CLIPFLOW_YOUTUBE_PUBLISHING'] = worker_env['CLIPFLOW_YOUTUBE_PUBLISHING'] = 'true'
        for name in SECRET_NAMES:
            key = 'CLIPFLOW_YOUTUBE_' + name
            worker_env[key] = os.environ[key]
    builtin = os.environ.get('CLIPFLOW_BUILTIN_YOUTUBE', 'true') == 'true'
    if builtin:
        owner_env['CLIPFLOW_BUILTIN_YOUTUBE'] = worker_env['CLIPFLOW_BUILTIN_YOUTUBE'] = 'true'
    if os.environ.get('CLIPFLOW_YOUTUBE_DATA_API_KEY'):
        owner_env['CLIPFLOW_YOUTUBE_DATA_API_KEY'] = os.environ['CLIPFLOW_YOUTUBE_DATA_API_KEY']
    for name in ('CLIPFLOW_SOURCE_RETENTION_HOURS', 'CLIPFLOW_OUTPUT_RETENTION_HOURS'):
        value = os.environ.get(name, '')
        if value.isascii() and value.isdecimal() and 0 < int(value) <= 2160:
            owner_env[name] = worker_env[name] = value
    converter = None if builtin else VidFetch.configured()
    if converter and (path == PERSISTENT_DATA or converter.free_only):
        owner_env.update(CLIPFLOW_VIDFETCH_ENABLED='true', CLIPFLOW_VIDFETCH_MONTHLY_JOBS=str(converter.limit))
        worker_env.update(CLIPFLOW_VIDFETCH_ENABLED='true', CLIPFLOW_VIDFETCH_MONTHLY_JOBS=str(converter.limit),
                          CLIPFLOW_VIDFETCH_API_KEY=converter.key, CLIPFLOW_VIDFETCH_DELIVERY_ORIGIN=converter.delivery_origin)
        if converter.free_only:
            worker_env['CLIPFLOW_VIDFETCH_FREE_ONLY'] = 'true'
    if os.environ.get('CLIPFLOW_PAID_WORKLOADS_ENABLED') == 'true':
        key = os.environ.get('OPENAI_API_KEY', '').strip()
        budgets = {name: os.environ.get(name, '') for name in ('CLIPFLOW_TRANSCRIPTION_MONTHLY_MICRO_USD',
                                                                'CLIPFLOW_PLANNING_MONTHLY_MICRO_USD')}
        approved = {name: value for name, value in budgets.items()
                    if value.isascii() and value.isdecimal() and 0 < int(value)}
        if path == PERSISTENT_DATA and key and approved:
            owner_env.update(approved, CLIPFLOW_PAID_WORKLOADS_ENABLED='true')
            worker_env.update(approved, CLIPFLOW_PAID_WORKLOADS_ENABLED='true', OPENAI_API_KEY=key)
        else:
            print('Paid workloads paused. Configure a mounted /var/data disk, an API key, and a positive USD budget.',
                  file=sys.stderr)
    return path, owner_env, worker_env


def main():
    password = os.environ.get('CLIPFLOW_PREVIEW_PASSWORD', '')
    try:
        PreviewAuth(password)
        port = int(os.environ.get('PORT', '10000'))
        if not 1 <= port <= 65535:
            raise ValueError('PORT must be a valid port number')
    except ValueError as error:
        sys.exit(str(error))

    path, owner_env, worker_env = service_settings()

    children = []
    stopping = False

    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        children.append(subprocess.Popen([sys.executable, '-m', 'clipflow.worker', path], env=worker_env))
        children.append(subprocess.Popen([
            sys.executable, '-m', 'clipflow.web', path, '--bind', '0.0.0.0',
            '--port', str(port), '--render-preview',
        ], env={**owner_env, 'CLIPFLOW_PREVIEW_PASSWORD': password}))
        while not stopping:
            if any(child.poll() is not None for child in children):
                return 1
            time.sleep(0.25)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    sys.exit(main())
