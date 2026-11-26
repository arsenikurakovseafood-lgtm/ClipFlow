"""Single-service, password-protected Render preview with ephemeral storage."""
import os
import signal
import subprocess
import sys
import time

from clipflow.auth import PreviewAuth

DATA = '/var/lib/clipflow'


def main():
    password = os.environ.get('CLIPFLOW_PREVIEW_PASSWORD', '')
    try:
        PreviewAuth(password)
        port = int(os.environ.get('PORT', '10000'))
        if not 1 <= port <= 65535:
            raise ValueError('PORT must be a valid port number')
    except ValueError as error:
        sys.exit(str(error))

    # Free preview uses its own settings and never calls paid providers.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('CLIPFLOW_', 'OPENAI_'))}
    env['CLIPFLOW_INTERNAL_RENDER_PREVIEW'] = 'true'

    children = []
    stopping = False

    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        children.append(subprocess.Popen([sys.executable, '-m', 'clipflow.worker', DATA], env=env))
        children.append(subprocess.Popen([
            sys.executable, '-m', 'clipflow.web', DATA, '--bind', '0.0.0.0',
            '--port', str(port), '--render-preview',
        ], env={**env, 'CLIPFLOW_PREVIEW_PASSWORD': password}))
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
