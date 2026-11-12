import io
import json
import sqlite3
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

from app import assets, main
from app.models import ProjectInput
from app.production import compile_project, create_audio
from app.store import Store, Conflict, Missing


def png():
    out = io.BytesIO()
    metadata = PngImagePlugin.PngInfo(); metadata.add_text('secret-comment', 'do not retain')
    Image.new('RGB', (100, 80), '#b9d9c9').save(out, format='PNG', pnginfo=metadata)
    return out.getvalue()


def wav(seconds=1, width=2):
    out = io.BytesIO()
    with wave.open(out, 'wb') as f:
        f.setparams((1, width, 24000, 0, 'NONE', 'not compressed'))
        f.writeframes(b'\x00' * width * int(24000 * seconds))
    return out.getvalue()


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


def doc(image=None, audio=None):
    return ProjectInput(title='Asset test', scenes=[{'title': 'Example', 'narration': 'Test.',
        'points': ['First'], 'image_id': image, 'audio_id': audio}]).model_dump()


def test_normalizes_image_and_strips_metadata(store):
    item = assets.upload(store, '<img onerror=alert(1)>.png', 'image', png())
    path, mime = assets.content_path(store, item['id'])
    assert mime == 'image/png' and path.suffix == '.png'
    with Image.open(path) as image:
        assert 'secret-comment' not in image.info
        assert image.size == (100, 80)
    assert assets.content_path(store, item['id'], True)[0].is_file()
    assert len(assets.listing(store)) == 1


@pytest.mark.parametrize('payload', [b'<svg onload="alert(1)"></svg>', b'<html>bad</html>', b'GIF89a', b''])
def test_rejects_unsafe_or_invalid_images(payload):
    with pytest.raises(assets.AssetError):
        assets.normalize(payload, 'image')


def test_animation_and_oversized_image_rejected(monkeypatch):
    output = io.BytesIO()
    Image.new('RGB', (2, 2), 'red').save(output, format='GIF')
    with pytest.raises(assets.AssetError):
        assets.normalize(output.getvalue(), 'image')
    monkeypatch.setattr(assets, 'MAX_PIXELS', 100)
    with pytest.raises(assets.AssetError):
        assets.normalize(png(), 'image')


def test_audio_bounds_and_normalization(store):
    item = assets.upload(store, 'Narration.wav', 'audio', wav(2))
    assert item['duration'] == 2 and item['sample_rate'] == 24000
    with pytest.raises(assets.AssetError):
        assets.normalize(wav(.1), 'audio')
    with pytest.raises(assets.AssetError):
        assets.normalize(wav(1, 1), 'audio')
    with pytest.raises(assets.AssetError):
        assets.normalize(wav(1)[:-100], 'audio')
    with pytest.raises(Missing):
        assets.content_path(store, item['id'], True)


def test_archive_keeps_old_projects_and_snapshots_renderable(store):
    image = assets.upload(store, 'image', 'image', png())
    p = store.create(doc(image['id']))
    store.confirm(p['id'], 1)
    job = store.enqueue(p['id'], 1, 'render', {'audio': 'silent'}, 'pinned', 'archive-check')
    assets.archive(store, image['id'])
    assert assets.listing(store) == []
    assert store.job(job['id'])['snapshot']['project']['scenes'][0]['image_id'] == image['id']
    assets.copy_verified(store, image['id'], 'image', store.root / 'copy.png')
    assert (store.root / 'copy.png').is_file()
    assert store.edit(p['id'], 1, doc(image['id']))['version'] == 2


def test_reference_validation_rejects_wrong_kind_or_missing(store):
    audio = assets.upload(store, 'voice', 'audio', wav())
    with pytest.raises(Conflict):
        store.create(doc(image=audio['id']))
    with pytest.raises(Conflict):
        store.create(doc(image='f'*32))


def test_upload_audio_mode_requires_every_scene(store):
    p = store.create(doc()); store.confirm(p['id'], 1)
    with pytest.raises(Conflict, match='每一页'):
        store.enqueue(p['id'], 1, 'render', {'audio': 'uploaded'}, 'pinned', 'missing-audio')


def test_tampered_bytes_rejected(store):
    item = assets.upload(store, 'image', 'image', png())
    path, _ = assets.content_path(store, item['id'])
    path.write_bytes(b'corrupted')
    with pytest.raises(assets.AssetError, match='已被修改'):
        assets.copy_verified(store, item['id'], 'image', store.root / 'copy.png')


def test_project_compiles_asset_path_and_audio_duration(store):
    image = assets.upload(store, 'pic', 'image', png())
    audio = assets.upload(store, 'voice', 'audio', wav(2))
    project = doc(image['id'], audio['id'])
    work = store.root / 'project'
    compile_project(project, work)
    source = (work / 'pages/p01.js').read_text()
    assert f'assets/{image["id"]}.png' in source and 'P.img(' in source
    class Runner:
        def check(self): pass
        def run(self, *a, **kw): pass
    create_audio(project, {'audio':'uploaded', 'voice':'test'}, work, store.root, Runner(), store)
    payload = json.loads((work/'voice.js').read_text().removeprefix('SCRIPT.VOICE = ').removesuffix(';'))
    assert payload['pages'][0][0]['d'] == 2


def test_api_upload_auth_size_and_archive(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setenv('ADMIN_PASSWORD', 'asset-test-password-long')
    client = TestClient(main.app)
    assert client.post('/api/assets?name=x&kind=image', content=png()).status_code == 401
    auth = ('admin', 'asset-test-password-long')
    response = client.post('/api/assets?name=x&kind=image', content=png(), auth=auth)
    assert response.status_code == 200
    aid = response.json()['id']
    assert client.get(f'/api/assets/{aid}/thumbnail', auth=auth).headers['content-type'] == 'image/png'
    assert client.get(f'/api/assets/{aid}/content').status_code == 401
    assert client.post('/api/assets?name=x&kind=image', content=b'a', headers={'content-length':str(assets.MAX_UPLOAD+1)}, auth=auth).status_code == 413
    assert client.delete(f'/api/assets/{aid}', auth=auth).status_code == 200
    assert client.get('/api/assets', auth=auth).json() == []
    assert client.get(f'/api/assets/{aid}/content', auth=auth).status_code == 200


def test_database_migration_preserves_existing_projects(tmp_path):
    original = Store(tmp_path)
    p = original.create(doc())
    with original.connect() as db:
        db.execute('DROP TABLE assets')
        db.execute('PRAGMA user_version=1')
    migrated = Store(tmp_path)
    assert migrated.project(p['id'])['title'] == 'Asset test'
    assert assets.listing(migrated) == []
    with migrated.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 4
        db.execute('PRAGMA user_version=999')
    with pytest.raises(RuntimeError, match='数据库版本'):
        Store(tmp_path)
