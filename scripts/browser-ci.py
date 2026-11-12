"""Run mocked UI regressions against an isolated API, with no Worker or paid requests.

Install: npm ci --prefix scripts/browser-tests &&
         cd scripts/browser-tests && npx playwright install chromium
Run: python scripts/browser-ci.py
"""
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
CASES = ('workspace', 'studio', 'project-tasks', 'scene-scroll',
         'production-state', 'task-history', 'capabilities')


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def main():
    output = Path(os.environ.get('BROWSER_TEST_OUTPUT', ROOT / '.data/browser-ci')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not (ROOT / 'scripts/browser-tests/node_modules/playwright').is_dir():
        raise SystemExit('Run npm ci --prefix scripts/browser-tests first')
    # Fail rather than fall back to a user's live API if a local port is occupied.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='baotuo-browser-ci-') as temporary:
        data = Path(temporary)
        # Do not inherit provider proxy, production paths, admin credentials or runtime settings.
        env = {key: value for key, value in os.environ.items() if key in (
            'PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT',
            'PLAYWRIGHT_BROWSERS_PATH', 'BROWSER_TEST_CHROME',
        )}
        env.update({
            'PYTHONPATH': str(ROOT / 'backend'), 'PYTHONUNBUFFERED': '1',
            'DATA_ROOT': str(data / 'workspace'), 'RUNTIME_ROOT': str(data / 'runtimes'),
            'ADMIN_PASSWORD': secrets.token_urlsafe(32),
            'PROVIDER_ENCRYPTION_KEY': Fernet.generate_key().decode(),
            'COOKIE_SECURE': '0', 'BASE_URL': f'http://127.0.0.1:{port}',
            'BROWSER_TEST_ISOLATED': '1', 'BROWSER_TEST_OUTPUT': str(output),
        })
        log = (output / 'api.log').open('w')
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app',
                                   '--host', '127.0.0.1', '--port', str(port)],
                                  cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                  start_new_session=True)
        results = []
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Isolated API exited; see api.log')
                try:
                    with opener.open(env['BASE_URL'] + '/health', timeout=1) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(.1)
            else:
                raise RuntimeError('Isolated API startup timed out')
            for case in CASES:
                start = time.monotonic()
                with (output / (case + '.log')).open('w') as case_log:
                    child = subprocess.Popen(['node', 'scripts/browser-' + case + '.cjs'],
                                             cwd=ROOT, env=env, stdout=case_log,
                                             stderr=subprocess.STDOUT, start_new_session=True)
                    try:
                        code = child.wait(timeout=180)
                    except subprocess.TimeoutExpired:
                        stop(child)
                        code = 124
                    finally:
                        if child.poll() is None:
                            stop(child)
                        # Also terminate browser descendants on a failed test.
                        if child.poll() != 0:
                            try:
                                os.killpg(child.pid, signal.SIGTERM)
                            except ProcessLookupError:
                                pass
                results.append({'case': case, 'exit_code': code, 'seconds': round(time.monotonic() - start, 2)})
                print(f'{case}: {"PASS" if code == 0 else "FAIL"}', flush=True)
                if code:
                    print((output / (case + '.log')).read_text(), flush=True)
                    break
        finally:
            stop(server)
            log.close()
            (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        if len(results) != len(CASES) or any(row['exit_code'] for row in results):
            raise SystemExit(1)
        print(f'All {len(CASES)} browser regressions passed. Artifacts: {output}')


if __name__ == '__main__':
    main()
