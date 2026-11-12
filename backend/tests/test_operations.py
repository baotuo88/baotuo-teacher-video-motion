import fcntl
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import main
from app.backup import backup, restore, verify
from app.operations import CapacityError, ensure_capacity, worker_alive
from app.store import Store
from app.worker import heartbeat


def test_disk_limit(tmp_path, monkeypatch):
    monkeypatch.setenv('MIN_FREE_DISK_MB', '10')
    with patch('app.operations.shutil.disk_usage', return_value=SimpleNamespace(free=9 * 1024**2)):
        with pytest.raises(CapacityError):
            ensure_capacity(tmp_path)


def test_pending_limit_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.setenv('MAX_PENDING_JOBS', '1')
    monkeypatch.setenv('MIN_FREE_DISK_MB', '0')
    db = Store(tmp_path)
    a = db.create({'title': 'a', 'scenes': []})
    b = db.create({'title': 'b', 'scenes': []})
    first = db.enqueue(a['id'], 1, 'storyboard', {}, None, 'first')
    assert db.enqueue(a['id'], 1, 'storyboard', {}, None, 'first')['id'] == first['id']
    with pytest.raises(CapacityError):
        db.enqueue(b['id'], 1, 'storyboard', {}, None, 'second')


def test_heartbeat_lifecycle(tmp_path):
    assert not worker_alive(tmp_path)
    (tmp_path / 'worker-heartbeat').write_text(str(time.time() - 60))
    assert not worker_alive(tmp_path)
    with heartbeat(tmp_path):
        for _ in range(100):
            if worker_alive(tmp_path):
                break
            time.sleep(.01)
        assert worker_alive(tmp_path)
    assert not worker_alive(tmp_path)


def test_readiness_private_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setattr(main, 'ROOT', tmp_path / 'runtimes')
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password-with-entropy')
    client = TestClient(main.app)
    assert client.get('/health').status_code == 200
    result = client.get('/ready')
    assert result.status_code == 503
    assert result.json() == {'status': 'not_ready'}
    assert client.get('/api/system/status').status_code == 401
    result = client.get('/api/system/status', auth=('admin', 'test-password-with-entropy'))
    assert result.status_code == 200
    assert result.json()['checks']['worker'] is False
    assert result.json()['checks']['runtime'] is False


@pytest.mark.parametrize('streamed', [False, True])
def test_json_body_limit(streamed):
    client = TestClient(main.app)
    body = b'x' * (1024 * 1024 + 1)
    response = client.post('/api/auth/login', content=iter([body]) if streamed else body,
                           headers={'Content-Type': 'application/json'})
    assert response.status_code == 413


def test_backup_restore_and_tamper(tmp_path):
    source, archive, target = [tmp_path / name for name in ('source', 'archive', 'restore')]
    store = Store(source)
    project = store.create({'title': 'backed up', 'scenes': []})
    (source / 'assets').mkdir()
    (source / 'assets/picture.png').write_bytes(b'fixture')
    (source / 'assets/alias').symlink_to('picture.png')
    (source / 'absolute').symlink_to((source / 'assets').resolve(), target_is_directory=True)
    backup(source, archive)
    verify(archive)
    restore(archive, target)
    assert Store(target).project(project['id'])['title'] == 'backed up'
    assert (target / 'assets/alias').read_bytes() == b'fixture'
    assert (target / 'absolute/picture.png').read_bytes() == b'fixture'
    assert not (target / 'absolute').readlink().is_absolute()
    with pytest.raises(ValueError, match='空目录'):
        restore(archive, target)
    (archive / 'data/assets/picture.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='校验失败'):
        verify(archive)


def test_backup_refuses_active_worker(tmp_path):
    source = tmp_path / 'source'
    Store(source)
    with (source / 'worker.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='停止'):
            backup(source, tmp_path / 'archive')


def test_backup_rejects_external_symlink(tmp_path):
    source = tmp_path / 'source'
    Store(source)
    (source / 'escape').symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError, match='外部'):
        backup(source, tmp_path / 'archive')


def test_basic_auth_cannot_bypass_login_limit(tmp_path, monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password-with-entropy')
    monkeypatch.setattr(main, 'DATA', tmp_path)
    main.LOGIN_ATTEMPTS.clear()
    client = TestClient(main.app)
    try:
        for _ in range(10):
            assert client.get('/api/projects', auth=('admin', 'wrong')).status_code == 401
        assert client.post('/api/auth/login', json={'password': 'wrong'}).status_code == 429
        assert client.get('/api/projects', auth=('admin', 'wrong')).status_code == 429
    finally:
        main.LOGIN_ATTEMPTS.clear()


@pytest.mark.parametrize('token', ['1.' + 'a' * 48 + '.' + '宝' * 64, '1.' * 1000, '\ud800', None])
def test_malformed_session_is_rejected_not_server_error(token):
    from app import auth
    assert auth.verify(token) is False


def test_malformed_origin_is_forbidden(monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', 'test-password-with-entropy')
    client = TestClient(main.app)
    assert client.post('/api/auth/login', json={'password': 'irrelevant'},
                       headers={'Origin': 'https://[broken'}).status_code == 403


def test_probe_handles_database_initialization_failure(tmp_path):
    from app.operations import ReadinessProbe
    (tmp_path / 'studio.sqlite3').write_bytes(b'not a database')
    probe = ReadinessProbe()
    assert probe.check(tmp_path, tmp_path / 'runtimes')['checks']['database'] is False


def test_probe_caches_expensive_validation(tmp_path):
    from app.operations import ReadinessProbe
    probe = ReadinessProbe()
    expected = {'ready': False, 'checks': {}, 'free_disk_mb': 1}
    with patch('app.operations.readiness', return_value=expected) as check:
        assert probe.check(tmp_path, tmp_path / 'runtimes') == expected
        assert probe.check(tmp_path, tmp_path / 'runtimes') == expected
        assert check.call_count == 1


def test_probe_detects_wrong_but_valid_encryption_key(tmp_path, monkeypatch):
    from app.operations import readiness
    from cryptography.fernet import Fernet
    db = Store(tmp_path)
    original = Fernet.generate_key()
    db.save_provider('test', {}, Fernet(original).encrypt(b'secret').decode())
    monkeypatch.setenv('PROVIDER_ENCRYPTION_KEY', Fernet.generate_key().decode())
    assert readiness(db, tmp_path / 'runtimes')['checks']['encryption_key'] is False
    monkeypatch.setenv('PROVIDER_ENCRYPTION_KEY', original.decode())
    assert readiness(db, tmp_path / 'runtimes')['checks']['encryption_key'] is True


def test_v4_backup_restores_trash_preferences_and_task_history(tmp_path):
    from app.models import ProjectInput, ProductionSettings
    source, archive, target = (tmp_path / name for name in ('source', 'backup', 'restored'))
    db = Store(source)
    p = db.create(ProjectInput(title='备份恢复').model_dump())
    db.save_production_settings(p['id'], ProductionSettings(audio='edge').model_dump())
    job = db.enqueue(p['id'], 1, 'storyboard', {}, None, 'backup-job')
    db.finish(job['id'], 'failed', error='fixture')
    db.event(job['id'], '备份前日志')
    db.delete_project(p['id'], 1)
    backup(source, archive)
    restore(archive, target)
    recovered = Store(target)
    assert recovered.projects() == []
    assert recovered.trashed_projects()[0]['id'] == p['id']
    restored = recovered.restore_trashed_project(p['id'], 1)
    assert restored['version'] == 2
    assert recovered.production_settings(p['id'])['audio'] == 'edge'
    assert len(recovered.revisions(p['id'])) == 2
    assert recovered.project_job_history(p['id'])['items'][0]['id'] == job['id']
    assert recovered.events(job['id'])[0]['message'] == '备份前日志'
    assert db.trashed_projects()[0]['id'] == p['id']  # original unchanged
