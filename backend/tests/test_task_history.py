import pytest
from fastapi.testclient import TestClient

from app import main
from app.store import Store, Missing


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setenv('ADMIN_PASSWORD', 'history-test-password')
    store = Store(tmp_path)
    p = store.create({'title': '历史', 'topic': '', 'style': 'whiteboard', 'scenes': []})
    jobs = []
    for index in range(105):
        job = store.enqueue(p['id'], 1, 'storyboard', {}, None, 'history-'+str(index))
        store.finish(job['id'], 'succeeded', {'scenes': []})
        jobs.append(job)
    with store.connect() as db:
        db.execute('UPDATE jobs SET created=100')  # Ties must not skip/duplicate rows.
    return store, p, jobs


def test_cursor_history_survives_new_jobs_and_scopes_cursor(workspace):
    store, p, jobs = workspace
    first = store.project_job_history(p['id'], limit=40)
    new = store.enqueue(p['id'], 1, 'storyboard', {}, None, 'newest')
    store.finish(new['id'], 'succeeded', {'scenes': []})
    second = store.project_job_history(p['id'], before=first['next_cursor'], limit=40)
    third = store.project_job_history(p['id'], before=second['next_cursor'], limit=40)
    ids = [j['id'] for page in [first, second, third] for j in page['items']]
    assert len(ids) == len(set(ids)) == 105
    assert set(ids) == {j['id'] for j in jobs}
    assert third['next_cursor'] is None
    assert store.project_jobs(p['id'])[0]['id'] == new['id']
    other = store.create({'title': '其他', 'scenes': []})
    with pytest.raises(Missing):
        store.project_job_history(other['id'], before=jobs[0]['id'])


def test_history_and_log_download_auth_validation_and_completeness(workspace):
    store, p, jobs = workspace
    jid = jobs[0]['id']
    with store.connect() as db:
        db.executemany('INSERT INTO events(job_id,created,message) VALUES (?,?,?)',
                       [(jid, i, f'日志 {i}') for i in range(451)])
        db.execute('INSERT INTO events(job_id,created,message) VALUES (?,?,?)', (jobs[1]['id'], 1, 'OTHER JOB SECRET'))
    client = TestClient(main.app)
    auth = ('admin', 'history-test-password')
    history = '/api/projects/'+p['id']+'/job-history'
    download = '/api/jobs/'+jid+'/logs.txt'
    for url in [history, download]:
        assert client.get(url).status_code == 401
    assert client.get(history+'?limit=101', auth=auth).status_code == 422
    assert client.get(history+'?before=missing', auth=auth).status_code == 404
    assert len(client.get(history+'?limit=40', auth=auth).json()['items']) == 40
    assert client.get('/api/projects/missing/job-history', auth=auth).status_code == 404
    assert client.get('/api/jobs/missing/logs.txt', auth=auth).status_code == 404
    response = client.get(download, auth=auth)
    assert response.status_code == 200
    assert 'attachment' in response.headers['content-disposition']
    assert 'no-store' in response.headers['cache-control']
    assert len(response.text.splitlines()) == 451
    assert '日志 450' in response.text and 'OTHER JOB SECRET' not in response.text
    events = '/api/jobs/'+jid+'/events'
    first = client.get(events, auth=auth).json()
    second = client.get(events+'?after='+str(first[-1]['id']), auth=auth).json()
    third = client.get(events+'?after='+str(second[-1]['id']), auth=auth).json()
    assert [len(first), len(second), len(third)] == [200, 200, 51]
    assert client.get(events+'?after=-1', auth=auth).status_code == 422


def test_download_has_fixed_cutoff_and_releases_read_transactions(workspace):
    store, p, jobs = workspace
    jid = jobs[0]['id']
    store.event(jid, '初始日志')
    cutoff = store.event_cutoff(jid)
    store.event(jid, '稍后日志')
    chunks = list(store.export_events(jid, cutoff))
    assert '初始日志' in ''.join(chunks)
    assert '稍后日志' not in ''.join(chunks)
