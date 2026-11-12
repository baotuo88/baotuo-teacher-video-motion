import json
import socket
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import main, providers
from app.models import ProjectInput, ProviderInput, Scene
from app.production import compile_project, create_audio
from app.store import Store, Conflict


def document():
    return {'title': '铅笔的制作', 'topic': '面向小学生', 'style': 'whiteboard', 'scenes': [
        {'title': '原料', 'narration': '铅笔芯不是铅。', 'points': ['石墨与黏土'], 'layout': 'points', 'duration': 3}]}


@pytest.fixture
def db(tmp_path):
    return Store(tmp_path)


def test_edit_conflict_and_confirmation_invalidation(db):
    p = db.create(document())
    assert db.confirm(p['id'], 1)['confirmed']
    new = db.edit(p['id'], 1, document())
    assert new['version'] == 2 and not new['confirmed']
    with pytest.raises(Conflict):
        db.edit(p['id'], 1, document())


def test_render_requires_confirmation_and_pins_snapshot(db):
    p = db.create(document())
    with pytest.raises(Conflict, match='确认'):
        db.enqueue(p['id'], 1, 'render', {}, 'runtime-old', 'idempotent-key')
    db.confirm(p['id'], 1)
    j = db.enqueue(p['id'], 1, 'render', {}, 'runtime-old', 'idempotent-key')
    doc = document(); doc['title'] = 'new'
    db.edit(p['id'], 1, doc)
    assert db.job(j['id'])['snapshot']['project']['title'] == '铅笔的制作'
    assert db.job(j['id'])['runtime_id'] == 'runtime-old'


def test_duplicate_submission_and_conflicting_key(db):
    p = db.create(document()); db.confirm(p['id'], 1)
    first = db.enqueue(p['id'], 1, 'render', {}, 'runtime', 'idem')
    assert db.enqueue(p['id'], 1, 'render', {}, 'runtime-new', 'idem')['id'] == first['id']
    with pytest.raises(Conflict, match='幂等'):
        db.enqueue(p['id'], 1, 'render', {'fps': 30}, 'runtime', 'idem')


def test_claim_cancel_recover(db):
    p = db.create(document()); db.confirm(p['id'], 1)
    j = db.enqueue(p['id'], 1, 'render', {}, 'runtime', 'one')
    assert db.claim()['id'] == j['id']
    assert db.claim() is None
    db.recover()
    assert db.job(j['id'])['status'] == 'interrupted'
    j2 = db.enqueue(p['id'], 1, 'render', {}, 'runtime', 'two')
    assert db.cancel(j2['id'])['status'] == 'cancelled'
    assert db.claim() is None


def test_concurrent_claims_only_one(db):
    import concurrent.futures
    p = db.create(document()); db.confirm(p['id'], 1)
    db.enqueue(p['id'], 1, 'render', {}, 'runtime', 'one')
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: db.claim(), range(4)))
    assert sum(r is not None for r in results) == 1


@pytest.mark.parametrize('url', ['http://example.com/v1', 'https://127.0.0.1/v1',
    'https://localhost/v1', 'https://169.254.169.254', 'https://user:pass@example.com',
    'https://example.com:8080', 'https://example.com?a=b', 'https://[::1]'])
def test_unsafe_provider_urls_rejected(url):
    with pytest.raises(ValueError):
        providers.validate_url(url)


def test_dns_private_address_rejected(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, 1, 6, '', ('10.0.0.2', 443))])
    with pytest.raises(providers.ProviderError):
        providers.public_addresses('provider.example')


def test_provider_secret_encrypted_and_preserved(db, monkeypatch):
    monkeypatch.setenv('PROVIDER_ENCRYPTION_KEY', Fernet.generate_key().decode())
    data = ProviderInput(name='test', base_url='https://example.com/v1', model='model', api_key='very-secret')
    result = providers.save(db, data)
    assert 'very-secret' not in json.dumps(result)
    assert 'very-secret' not in db.provider(result['id'])['secret']
    original = db.provider(result['id'])['secret']
    data.api_key = None
    providers.save(db, data, result['id'])
    assert db.provider(result['id'])['secret'] == original


def test_provider_returns_validated_scene_data(db, monkeypatch):
    monkeypatch.setenv('PROVIDER_ENCRYPTION_KEY', Fernet.generate_key().decode())
    result = providers.save(db, ProviderInput(name='test', base_url='https://example.com/v1', model='model', api_key='secret'))
    row = db.provider(result['id'])
    seen = []
    def fake(config, key, suffix, payload):
        seen.append((key, suffix, payload))
        return {'choices': [{'message': {'content': json.dumps({'scenes': document()['scenes']})}}]}
    monkeypatch.setattr(providers, 'post_json', fake)
    scenes = providers.generate(db, {'provider_id': row['id'], 'provider_version': row['updated']}, document(), 'REFERENCE')
    assert scenes[0]['title'] == '原料'
    assert 'REFERENCE' in seen[0][2]['messages'][0]['content']
    assert seen[0][1] == '/chat/completions'


def test_compiler_escapes_js_injection(tmp_path):
    p = document(); p['scenes'][0]['title'] = "');globalThis.pwned=true;//"
    compile_project(p, tmp_path / 'project')
    import subprocess
    js = tmp_path / 'project/pages/p01.js'
    subprocess.run(['node', '--check', str(js)], check=True)
    script = "globalThis.ENGINE={visual:(_,f)=>f({title:()=>{},text:()=>{},c:()=>0})};require("+json.dumps(str(js))+ ");if(globalThis.pwned)process.exit(1)"
    subprocess.run(['node', '-e', script], check=True)


def test_audio_is_distinct_per_page_and_srt_timing(tmp_path):
    p = document(); p['scenes'].append({**p['scenes'][0], 'narration': '第二页', 'duration': 6})
    compile_project(p, tmp_path / 'project')
    class Runner:
        def check(self): pass
        def run(self, command, cwd=None):
            assert command == ['node', str(tmp_path / 'engine/tools/script.mjs')]
            assert cwd == tmp_path / 'project'
    create_audio(p, {'audio': 'silent', 'voice': 'test'}, tmp_path / 'project', tmp_path, Runner())
    text = (tmp_path / 'project/voice.js').read_text()
    pages = json.loads(text.removeprefix('SCRIPT.VOICE = ').removesuffix(';'))['pages']
    assert pages[0][0]['f'] != pages[1][0]['f']
    assert pages[0][0]['d'] == 3 and pages[1][0]['d'] == 6
    # No locally reimplemented timing rules: the upstream timing tool writes SRT.
    assert not (tmp_path / 'project/out/字幕.srt').exists()


def test_sessions_csrf_and_project_routes(monkeypatch, tmp_path):
    monkeypatch.setenv('ADMIN_PASSWORD', 'long-test-password-123')
    monkeypatch.setattr(main, 'DATA', tmp_path)
    main.LOGIN_ATTEMPTS.clear()
    client = TestClient(main.app)
    assert client.get('/api/projects').status_code == 401
    login = client.post('/api/auth/login', json={'password': 'long-test-password-123'})
    assert login.status_code == 200
    assert 'HttpOnly' in login.headers['set-cookie']
    assert client.post('/api/projects', json=document()).status_code == 403
    headers = {'x-csrf-token': login.json()['csrf']}
    response = client.post('/api/projects', json=document(), headers=headers)
    assert response.status_code == 200
    assert client.post('/api/projects', json=document(), headers={**headers, 'origin': 'https://attacker.example'}).status_code == 403
    pid = response.json()['id']
    assert client.get('/api/projects/'+pid).json()['title'] == '铅笔的制作'
    assert client.get('/api/jobs/unknown/artifacts/foo.mp4').status_code == 404


def test_login_rate_limit(monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'long-test-password-123')
    main.LOGIN_ATTEMPTS.clear()
    client = TestClient(main.app)
    for _ in range(10):
        assert client.post('/api/auth/login', json={'password': 'bad'}).status_code == 401
    assert client.post('/api/auth/login', json={'password': 'bad'}).status_code == 429
    main.LOGIN_ATTEMPTS.clear()


def test_running_subprocess_cancelled(db, tmp_path):
    import concurrent.futures
    import sys
    import time
    from app.production import ProcessRunner, Cancelled
    p = db.create(document()); db.confirm(p['id'], 1)
    job = db.enqueue(p['id'], 1, 'render', {}, 'runtime', 'cancel-test')
    db.claim()
    runner = ProcessRunner(db, job['id'], tmp_path)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(runner.run, [sys.executable, '-c', 'import time; time.sleep(30)'])
        time.sleep(.2)
        db.cancel(job['id'])
        with pytest.raises(Cancelled):
            future.result(timeout=5)


def test_upstream_timing_matches_srt_for_multiple_pages(tmp_path):
    import subprocess
    root = Path(__file__).resolve().parents[2]
    active = root / '.data/runtimes/active.json'
    if not active.exists():
        pytest.skip('需要准备本机运行时才能执行引擎集成测试')
    runtime = root / '.data/runtimes' / json.loads(active.read_text())['runtime_id'] / 'skill'
    project = document(); project['scenes'].append({**project['scenes'][0], 'duration': 6})
    directory = tmp_path / 'project'
    compile_project(project, directory)
    class Runner:
        def check(self): pass
        def run(self, command, cwd=None): subprocess.run(command, cwd=cwd, check=True, capture_output=True)
    create_audio(project, {'audio': 'silent', 'voice': 'test'}, directory, runtime, Runner())
    # Actual timing: 0.2 lead + 3s clip + .3 gap + .2 lead = 3.7s.
    assert '00:00:03,700 --> 00:00:09,700' in (directory / 'out/字幕.srt').read_text()


def test_revision_history_is_immutable(db):
    p = db.create(document())
    doc = document(); doc['title'] = 'edited'
    db.edit(p['id'], 1, doc)
    rows = db.revisions(p['id'])
    assert rows[0]['document']['title'] == 'edited'
    assert rows[1]['document']['title'] == '铅笔的制作'
    restored = db.edit(p['id'], 2, rows[1]['document'])
    assert restored['version'] == 3 and not restored['confirmed']


def test_edge_missing_dependency_is_actionable_before_subprocess(tmp_path, monkeypatch):
    from app.production import ProductionError
    import importlib.util
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: None)
    class Runner:
        def check(self): pass
        def run(self, *args, **kwargs): pytest.fail('must fail before invoking upstream')
    directory = tmp_path / 'project'
    directory.mkdir()
    with pytest.raises(ProductionError, match='edge-tts'):
        create_audio(document(), {'audio':'edge','voice':'zh-CN-XiaoxiaoNeural'}, directory, tmp_path, Runner())
