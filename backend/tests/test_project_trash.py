import pytest
from fastapi.testclient import TestClient

from app import main, auth
from app.models import ProjectInput, ProductionSettings
from app.store import Store, Missing, Conflict


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setenv('ADMIN_PASSWORD', 'trash-test-password')
    db = Store(tmp_path)
    p = db.create(ProjectInput(title='恢复测试', scenes=[{'title':'一','narration':'口播'}]).model_dump())
    db.confirm(p['id'], 1)
    db.save_production_settings(p['id'], ProductionSettings(audio='edge').model_dump())
    job = db.enqueue(p['id'], 1, 'storyboard', {}, None, 'trash-job')
    db.finish(job['id'], 'failed', error='old result')
    return db, p, job


def test_trash_restore_preserves_history_settings_and_jobs(workspace):
    db, p, job = workspace
    db.delete_project(p['id'], 1)
    assert db.projects() == []
    assert db.trashed_projects()[0]['id'] == p['id']
    with pytest.raises(Missing): db.project(p['id'])
    with pytest.raises(Missing): db.save_production_settings(p['id'], ProductionSettings().model_dump())
    with pytest.raises(Missing): db.enqueue(p['id'], 1, 'storyboard', {}, None, 'while-trashed')
    restored = db.restore_trashed_project(p['id'], 1)
    assert restored['version'] == 2 and restored['confirmed']
    assert restored['scenes'] == p['scenes']
    assert len(db.revisions(p['id'])) == 2
    assert db.production_settings(p['id'])['audio'] == 'edge'
    assert db.production_settings(p['id'])['version'] == 2
    assert db.project_job_history(p['id'])['items'][0]['id'] == job['id']
    assert db.job(job['id'])['snapshot']['project']['version'] == 1
    assert db.trashed_projects() == []
    with pytest.raises(Conflict): db.edit(p['id'], 1, {k:p[k] for k in ('title','topic','style','scenes')})
    with pytest.raises(Conflict): db.save_production_settings(p['id'], {**ProductionSettings().model_dump(),'version':1})
    with pytest.raises(Missing): db.restore_trashed_project(p['id'], 1)
    db.delete_project(p['id'], 2)
    with pytest.raises(Conflict): db.restore_trashed_project(p['id'], 1)
    assert db.restore_trashed_project(p['id'], 2)['version'] == 3


def test_trash_endpoints_auth_csrf_version_and_no_purge(workspace):
    db,p,job = workspace
    db.delete_project(p['id'], 1)
    client = TestClient(main.app)
    listing = '/api/project-trash'
    restore = listing+'/'+p['id']+'/restore'
    assert client.get(listing).status_code == 401
    assert client.post(restore,json={'version':1}).status_code == 401
    token=auth.issue(); client.cookies.set(auth.COOKIE,token)
    assert client.get(listing).json()[0]['id'] == p['id']
    assert client.post(restore,json={'version':1}).status_code == 403
    headers={'X-CSRF-Token':auth.sign('csrf:'+token)}
    assert client.post(restore,json={'version':2},headers=headers).status_code == 409
    assert client.post(restore,json={'version':1},headers=headers).status_code == 200
    assert client.delete(listing+'/'+p['id'],headers=headers).status_code in (404,405)


def test_v3_upgrade_and_restore_unconfirmed(tmp_path):
    db=Store(tmp_path)
    p=db.create(ProjectInput(title='未确认').model_dump())
    with db.connect() as connection:
        connection.execute('DROP TABLE IF EXISTS project_trash')
        connection.execute('PRAGMA user_version=3')
    db=Store(tmp_path)
    assert db.project(p['id']) == p
    db.delete_project(p['id'],1)
    restored=db.restore_trashed_project(p['id'],1)
    assert not restored['confirmed']
    with db.connect() as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 4


def test_concurrent_restore_only_creates_one_revision(workspace):
    from concurrent.futures import ThreadPoolExecutor
    db,p,job=workspace
    db.delete_project(p['id'],1)
    def restore():
        try:
            return db.restore_trashed_project(p['id'],1)['version']
        except Missing:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _: restore(), range(2)))
    assert sorted(value for value in results if value is not None) == [2]
    assert len(db.revisions(p['id'])) == 2


def test_restore_invalidates_default_settings_and_survives_store_reopen(tmp_path):
    db=Store(tmp_path)
    p=db.create(ProjectInput(title='默认制作配置').model_dump())
    db.delete_project(p['id'],1)
    db=Store(tmp_path)
    assert db.trashed_projects()[0]['id'] == p['id']
    db.restore_trashed_project(p['id'],1)
    assert db.production_settings(p['id'])['audio'] == 'silent'
    with pytest.raises(Conflict):
        db.save_production_settings(p['id'], ProductionSettings(audio='edge').model_dump())
