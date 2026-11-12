import pytest
from fastapi.testclient import TestClient

from app import main
from app.models import ProductionSettings, ProjectInput
from app.store import Store, Conflict, Missing


def test_settings_persist_without_changing_content_version(tmp_path):
    store = Store(tmp_path)
    p = store.create(ProjectInput(title='配置', scenes=[{'title':'第一页','narration':'测试口播','points':['要点']}]).model_dump())
    store.confirm(p['id'], 1)
    defaults = store.production_settings(p['id'])
    assert defaults == ProductionSettings().model_dump()
    saved = store.save_production_settings(p['id'], {**defaults, 'audio': 'edge'})
    assert saved['version'] == 1
    assert Store(tmp_path).production_settings(p['id']) == saved
    assert store.project(p['id'])['version'] == 1
    assert store.project(p['id'])['confirmed']
    with pytest.raises(Conflict):
        store.save_production_settings(p['id'], defaults)
    store.delete_project(p['id'], 1)
    with pytest.raises(Missing):
        store.save_production_settings(p['id'], saved)
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM production_settings').fetchone()[0] == 1


def test_v2_migration_preserves_project(tmp_path):
    store = Store(tmp_path)
    p = store.create(ProjectInput(title='旧项目').model_dump())
    with store.connect() as db:
        db.execute('DROP TABLE production_settings')
        db.execute('PRAGMA user_version=2')
    migrated = Store(tmp_path)
    assert migrated.project(p['id']) == p
    assert migrated.production_settings(p['id'])['audio'] == 'silent'
    with migrated.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 4


def test_settings_api_auth_validation_and_conflict(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setenv('ADMIN_PASSWORD', 'settings-test-password')
    store = Store(tmp_path)
    p = store.create(ProjectInput(title='设置').model_dump())
    client = TestClient(main.app)
    auth = ('admin', 'settings-test-password')
    url = '/api/projects/' + p['id'] + '/production-settings'
    body = ProductionSettings(audio='edge').model_dump()
    assert client.get(url).status_code == 401
    assert client.put(url, json=body).status_code == 401
    assert client.put(url, json={**body, 'audio': 'invalid'}, auth=auth).status_code == 422
    assert client.put(url, json=body, auth=auth).status_code == 200
    assert client.put(url, json=body, auth=auth).status_code == 409
    assert client.get(url, auth=auth).json()['audio'] == 'edge'
    assert client.get('/api/projects/missing/production-settings', auth=auth).status_code == 404


def test_settings_cookie_session_requires_csrf(tmp_path, monkeypatch):
    from app import auth
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setenv('ADMIN_PASSWORD', 'settings-test-password')
    p = Store(tmp_path).create(ProjectInput(title='安全设置').model_dump())
    token = auth.issue()
    client = TestClient(main.app)
    client.cookies.set(auth.COOKIE, token)
    url = '/api/projects/' + p['id'] + '/production-settings'
    body = ProductionSettings(audio='edge').model_dump()
    assert client.get(url).status_code == 200
    assert client.put(url, json=body).status_code == 403
    assert client.put(url, json=body, headers={'X-CSRF-Token': auth.sign('csrf:' + token)}).status_code == 200
