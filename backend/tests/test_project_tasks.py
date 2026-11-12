import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import main
from app.store import Store, Conflict, Missing


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setenv('ADMIN_PASSWORD', 'project-tasks-test-password')
    store = Store(tmp_path)
    project = store.create({'title':'task project', 'topic':'', 'style':'whiteboard', 'scenes':[]})
    return store, project


def test_delete_requires_auth_confirmation_and_current_version(workspace):
    store, p = workspace
    client = TestClient(main.app)
    url = '/api/projects/' + p['id']
    body = {'version':1, 'confirm':True}
    assert client.request('DELETE',url,json=body).status_code == 401
    auth = ('admin','project-tasks-test-password')
    assert client.request('DELETE',url,json={'version':1,'confirm':False},auth=auth).status_code == 400
    assert client.request('DELETE',url,json={'version':2,'confirm':True},auth=auth).status_code == 409
    assert client.request('DELETE',url,json=body,auth=auth).status_code == 200
    assert client.get(url,auth=auth).status_code == 404
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0] == 1


@pytest.mark.parametrize('running', [False,True])
def test_delete_blocks_active_jobs_and_preserves_finished_history(workspace,running):
    store,p = workspace
    j = store.enqueue(p['id'],1,'storyboard',{},None,'fixture')
    if running: store.claim()
    with pytest.raises(Conflict,match='任务'):
        store.delete_project(p['id'],1)
    store.finish(j['id'],'failed',error='fixture')
    store.delete_project(p['id'],1)
    assert store.job(j['id'])['snapshot']['project']['title'] == 'task project'
    with pytest.raises(Missing):
        store.enqueue(p['id'],1,'storyboard',{},None,'new-fixture')


def test_project_jobs_are_scoped_and_stream_requires_auth(workspace):
    store,p = workspace
    store.enqueue(p['id'],1,'storyboard',{},None,'fixture')
    other = store.create({'title':'other','scenes':[]})
    client = TestClient(main.app)
    auth = ('admin','project-tasks-test-password')
    assert client.get('/api/projects/'+p['id']+'/events').status_code == 401
    assert client.get('/api/projects/'+other['id']+'/jobs',auth=auth).json() == []
    assert len(client.get('/api/projects/'+p['id']+'/jobs',auth=auth).json()) == 1


def test_stream_updates_log_then_reports_removed_project(workspace):
    store,p = workspace
    j=store.enqueue(p['id'],1,'storyboard',{},None,'fixture')
    class Request:
        async def is_disconnected(self): return False
    async def check():
        response=await main.project_events(p['id'],Request())
        assert response.media_type=='text/event-stream'
        stream=response.body_iterator
        first=await anext(stream)
        assert 'event: snapshot' in first and j['id'] in first
        store.event(j['id'],'new progress')
        second=await anext(stream)
        assert 'new progress' in second
        store.finish(j['id'],'succeeded',result={'scenes':[]})
        third=await anext(stream)
        assert 'succeeded' in third
        store.delete_project(p['id'],1)
        assert 'event: removed' in await anext(stream)
        await stream.aclose()
    asyncio.run(check())
