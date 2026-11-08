"""Real Docker image smoke test, without external model calls or runtime downloads.

Checks the API, a real worker task cancellation, persistence, and required binaries.
Not a video rendering acceptance test; that requires a reviewed upstream runtime.
"""
import base64
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, timeout=120).strip()


image = sys.argv[1] if len(sys.argv) == 2 else 'whiteboard-ci:smoke'
suffix = secrets.token_hex(6)
api_name, worker_name, volume = (f'whiteboard-{kind}-{suffix}' for kind in ('api', 'worker', 'data'))
password = secrets.token_urlsafe(32)
os.environ['ADMIN_PASSWORD'] = password
headers = {'Authorization': 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()}
base = ''


def request(path, payload=None, authenticated=True):
    h = dict(headers) if authenticated else {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        h['Content-Type'] = 'application/json'
    with urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=h), timeout=10) as response:
        return json.load(response)


def wait_health():
    for _ in range(45):
        try:
            if request('/health')['status'] == 'ok':
                return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError('API did not become healthy')


try:
    docker('volume', 'create', volume)
    docker('run', '-d', '--name', api_name, '--init', '--cap-drop=ALL',
           '--security-opt=no-new-privileges:true', '-e', 'ADMIN_PASSWORD', '-e', 'DATA_ROOT=/data',
           '-p', '127.0.0.1::8000', '-v', volume + ':/data', image)
    port = docker('port', api_name, '8000/tcp').split(':')[-1]
    base = 'http://127.0.0.1:' + port
    wait_health()
    try:
        request('/api/projects', authenticated=False)
        raise AssertionError('Unauthenticated request unexpectedly accepted')
    except urllib.error.HTTPError as error:
        assert error.code == 401
    project = request('/api/projects', {'title': 'CI smoke project', 'topic': '', 'scenes': []})
    docker('restart', api_name)
    # Docker may allocate a different ephemeral port after restart.
    base = 'http://127.0.0.1:' + docker('port', api_name, '8000/tcp').split(':')[-1]
    wait_health()
    assert request('/api/projects/' + project['id'])['title'] == 'CI smoke project'
    assert docker('exec', api_name, 'id', '-u') != '0'
    for command in [('node', '--version'), ('npm', '--version'), ('ffmpeg', '-version'),
                    ('ffprobe', '-version'), ('chromium', '--version')]:
        docker('exec', api_name, *command)
    # Exercise the worker without installing/executing remote upstream code.
    setup = """
import os
from pathlib import Path
from app.store import Store
s = Store(Path('/data'))
p = s.create({'title':'worker check','topic':'','style':'whiteboard','scenes':[]})
j = s.enqueue(p['id'],1,'storyboard',{},None,'ci-worker-check')
with s.connect() as db:
    db.execute('UPDATE jobs SET cancel_requested=1 WHERE id=?',(j['id'],))
print(j['id'])
"""
    jid = docker('exec', api_name, 'python', '-c', setup)
    docker('run', '-d', '--name', worker_name, '--init', '--cap-drop=ALL',
           '--security-opt=no-new-privileges:true', '-e', 'DATA_ROOT=/data',
           '-v', volume + ':/data', image, 'python', '-m', 'app.worker')
    for _ in range(30):
        if request('/api/jobs/' + jid)['status'] == 'cancelled':
            break
        time.sleep(1)
    else:
        raise AssertionError('Independent worker did not process task')
    assert docker('inspect', '-f', '{{.State.Running}}', worker_name) == 'true'
    docker('exec', api_name, 'python', '-c',
           "from pathlib import Path; assert not Path('/app/.env').exists(); assert not Path('/app/.data').exists()")
    print('Image smoke passed: API, auth, persistence, non-root, worker, Node/Chromium/FFmpeg.')
finally:
    for name in (worker_name, api_name):
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['docker', 'volume', 'rm', volume], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
