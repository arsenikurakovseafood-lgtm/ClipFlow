"""Single-service, password-protected Render preview with ephemeral storage."""
import os
import signal
import subprocess
import sys
import time

from clipflow.auth import PreviewAuth

DATA = '/var/lib/clipflow'
PERSISTENT_DATA = '/var/data'


def service_settings():
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(('CLIPFLOW_', 'OPENAI_'))}
    env['CLIPFLOW_INTERNAL_RENDER_PREVIEW'] = 'true'
    path = PERSISTENT_DATA if os.path.ismount(PERSISTENT_DATA) and os.access(PERSISTENT_DATA, os.W_OK) else DATA
    owner_env, worker_env = dict(env), dict(env)
    if os.environ.get('CLIPFLOW_PAID_WORKLOADS_ENABLED') == 'true':
        key = os.environ.get('OPENAI_API_KEY', '').strip()
        budget = os.environ.get('CLIPFLOW_TRANSCRIPTION_MONTHLY_MICRO_USD', '')
        if path == PERSISTENT_DATA and key and budget.isascii() and budget.isdecimal() and 0 < int(budget):
            owner_env.update(CLIPFLOW_PAID_WORKLOADS_ENABLED='true',
                             CLIPFLOW_TRANSCRIPTION_MONTHLY_MICRO_USD=budget)
            worker_env.update(owner_env, OPENAI_API_KEY=key)
        else:
            print('Automatic captions paused. Configure a mounted /var/data disk, an API key, and a positive USD budget.',
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
