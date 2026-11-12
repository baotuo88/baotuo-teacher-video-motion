"""Media results may cross media-only revisions, never content edits or target replacement."""
import io
import copy

import pytest
from PIL import Image

from app.assets import upload
from app.models import ProjectInput
from app.store import Store


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path)
    p = store.create(ProjectInput(title='生成期间编辑', scenes=[
        {'title': '一', 'narration': '第一段'}, {'title': '二', 'narration': '第二段'},
    ]).model_dump())
    store.confirm(p['id'], 1)
    assets = []
    for color in ['red', 'blue']:
        data = io.BytesIO()
        Image.new('RGB', (80, 80), color).save(data, format='PNG')
        assets.append(upload(store, color, 'image', data.getvalue()))
    jobs = [store.enqueue(p['id'], 1, 'image', {'auto_apply': True, 'scene_index': i}, None, 'media-'+str(i)) for i in [1]]
    for _ in jobs: store.claim()
    return store, p, jobs, assets


def finish(store, job, asset):
    store.complete_generated(job['id'], {'asset': asset, 'scene_index': job['snapshot']['options']['scene_index']})


def test_different_pages_apply_without_losing_first_result(setup):
    store, p, jobs, assets = setup
    edited = {k: copy.deepcopy(p[k]) for k in ('title', 'topic', 'style', 'scenes')}
    edited['scenes'][0]['image_id'] = assets[0]['id']
    store.edit(p['id'], 1, edited)
    store.confirm(p['id'], 2)
    finish(store, jobs[0], assets[1])
    current = store.project(p['id'])
    assert current['version'] == 3
    assert current['confirmed']
    assert [s['image_id'] for s in current['scenes']] == [a['id'] for a in assets]
    assert store.job(jobs[0]['id'])['result']['application']['version'] == 3
    assert jobs[0]['snapshot']['project']['scenes'][0]['image_id'] is None
    finish(store, jobs[0], assets[1])
    assert store.project(p['id'])['version'] == 3


@pytest.mark.parametrize('change', ['narration', 'reorder', 'style', 'target', 'reverted_text', 'reverted_target'])
def test_unsafe_intervening_edits_remain_conflicts(setup, change):
    store, p, jobs, assets = setup
    original = {k: copy.deepcopy(p[k]) for k in ('title', 'topic', 'style', 'scenes')}
    edited = copy.deepcopy(original)
    if change in ('narration', 'reverted_text'): edited['scenes'][1]['narration'] = '新口播'
    elif change == 'reorder': edited['scenes'].reverse()
    elif change == 'style': edited['style'] = 'study'
    else: edited['scenes'][1]['image_id'] = assets[0]['id']
    store.edit(p['id'], 1, edited)
    if change.startswith('reverted'): store.edit(p['id'], 2, original)
    before = store.project(p['id'])
    finish(store, jobs[0], assets[1])
    assert store.project(p['id']) == before
    assert store.job(jobs[0]['id'])['result']['application']['status'] == 'conflict'


def test_media_rebase_does_not_confirm_unconfirmed_draft(setup):
    store, p, jobs, assets = setup
    edited = {k: copy.deepcopy(p[k]) for k in ('title', 'topic', 'style', 'scenes')}
    edited['scenes'][0]['image_id'] = assets[0]['id']
    store.edit(p['id'], 1, edited)
    finish(store, jobs[0], assets[1])
    assert store.project(p['id'])['version'] == 3
    assert not store.project(p['id'])['confirmed']


def test_same_page_other_media_binding_is_preserved(setup):
    import wave
    store, p, jobs, assets = setup
    store.finish(jobs[0]['id'], 'cancelled')
    job = store.enqueue(p['id'], 1, 'speech', {'auto_apply': True, 'scene_index': 1}, None, 'speech-safe-merge')
    store.claim()
    data = io.BytesIO()
    with wave.open(data, 'wb') as stream:
        stream.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\0\0' * 24000)
    audio = upload(store, 'voice', 'audio', data.getvalue())
    edited = {k: copy.deepcopy(p[k]) for k in ('title', 'topic', 'style', 'scenes')}
    edited['scenes'][1]['image_id'] = assets[0]['id']
    store.edit(p['id'], 1, edited)
    finish(store, job, audio)
    current = store.project(p['id'])
    assert current['version'] == 3
    assert current['scenes'][1]['image_id'] == assets[0]['id']
    assert current['scenes'][1]['audio_id'] == audio['id']


def test_deleted_project_never_recreated_by_result(setup):
    store, p, jobs, assets = setup
    # Deletion is normally blocked during work; simulate external removal.
    with store.connect() as db:
        db.execute('DELETE FROM projects WHERE id=?', (p['id'],))
    finish(store, jobs[0], assets[1])
    assert store.job(jobs[0]['id'])['result']['application']['status'] == 'conflict'
