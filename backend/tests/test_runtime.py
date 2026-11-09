import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.runtime import (RuntimeError_, change_summary, inspect_source, release,
                         runtime_id, source_digest, validate_sha)
from app.verification import activate


def candidate(root: Path):
    skill, engine = 'a' * 40, 'b' * 40
    rid = runtime_id(skill, engine)
    path = root / rid
    (path / 'skill').mkdir(parents=True)
    (path / 'skill/SKILL.md').write_text('sample')
    manifest = {'id': rid, 'skill_commit': skill, 'engine_commit': engine,
                'source_digest': source_digest(path / 'skill'),
                'inspection': {'static_ok': True}}
    (path / 'manifest.json').write_text(json.dumps(manifest))
    return path, manifest


def certify(path, manifest):
    (path / 'sample.mp4').write_bytes(b'test-fixture-only')
    (path / 'verification.json').write_text(json.dumps({
        'runtime_id': manifest['id'], 'source_digest': manifest['source_digest'], 'passed': True,
        'artifacts': [{'name': 'sample.mp4', 'sha256': hashlib.sha256(b'test-fixture-only').hexdigest()}]}))


@pytest.mark.parametrize('value', ['main', '--help', '../x', 'A' * 40, 'a' * 39])
def test_only_full_commits(value):
    with pytest.raises(RuntimeError_):
        validate_sha(value)


def test_identity_includes_engine():
    assert runtime_id('a'*40, 'b'*40) != runtime_id('a'*40, 'c'*40)


def test_missing_contract_never_passes(tmp_path):
    report = inspect_source(tmp_path, tmp_path)
    assert not report['static_ok']
    assert '缺少 SKILL.md' in report['errors']


def test_source_tampering_rejected(tmp_path):
    path, manifest = candidate(tmp_path)
    (path / 'skill/SKILL.md').write_text('changed')
    with pytest.raises(RuntimeError_, match='已被修改'):
        release(tmp_path, manifest['id'])


def test_unverified_cannot_activate(tmp_path):
    _, manifest = candidate(tmp_path)
    with pytest.raises(RuntimeError_, match='真实渲染'):
        activate(tmp_path, manifest['id'])
    assert not (tmp_path / 'active.json').exists()


def test_activate_and_retain_version(tmp_path):
    path, manifest = candidate(tmp_path)
    certify(path, manifest)
    activate(tmp_path, manifest['id'])
    assert json.loads((tmp_path / 'active.json').read_text())['runtime_id'] == manifest['id']
    assert (path / 'skill/SKILL.md').exists()


def test_modified_proof_rejected(tmp_path):
    path, manifest = candidate(tmp_path)
    certify(path, manifest)
    (path / 'sample.mp4').write_bytes(b'corrupted')
    with pytest.raises(RuntimeError_, match='产物'):
        activate(tmp_path, manifest['id'])


def test_symlinks_rejected(tmp_path):
    (tmp_path / 'escape').symlink_to('/tmp')
    with pytest.raises(RuntimeError_, match='符号链接'):
        source_digest(tmp_path)


def test_changes_flag_code_review(tmp_path):
    old, new = tmp_path / 'old', tmp_path / 'new'
    old.mkdir(); (new / 'scripts').mkdir(parents=True)
    (old / 'SKILL.md').write_text('a'); (new / 'SKILL.md').write_text('b')
    assert not change_summary(old, new)['requires_adapter_review']
    (new / 'scripts/new.py').write_text('print(1)')
    assert change_summary(old, new)['requires_adapter_review']


def test_api_is_protected(monkeypatch, tmp_path):
    monkeypatch.setenv('ADMIN_PASSWORD', 'a-long-test-password')
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    client = TestClient(main.app)
    assert client.get('/api/runtimes').status_code == 401
    assert client.get('/api/runtimes', auth=('admin', 'wrong')).status_code == 401
    assert client.get('/api/runtimes', auth=('admin', 'a-long-test-password')).json()['items'] == []


def test_api_fail_closed_without_password(monkeypatch):
    monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
    client = TestClient(main.app)
    assert client.get('/api/runtimes', auth=('admin', 'anything')).status_code == 503


def test_runtime_path_traversal_rejected(tmp_path):
    with pytest.raises(RuntimeError_, match='无效'):
        release(tmp_path, '../outside')


def test_activation_keeps_previous_default_on_failure(tmp_path):
    path, manifest = candidate(tmp_path)
    certify(path, manifest)
    activate(tmp_path, manifest['id'])
    previous = (tmp_path / 'active.json').read_bytes()
    (path / 'verification.json').unlink()
    with pytest.raises(RuntimeError_):
        activate(tmp_path, manifest['id'])
    assert (tmp_path / 'active.json').read_bytes() == previous


def test_api_rejects_unverified_activation(monkeypatch, tmp_path):
    _, manifest = candidate(tmp_path)
    monkeypatch.setenv('ADMIN_PASSWORD', 'a-long-test-password')
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    client = TestClient(main.app)
    response = client.post('/api/runtimes/activate', auth=('admin', 'a-long-test-password'),
                           json={'runtime_id': manifest['id'], 'confirm': True})
    assert response.status_code == 400
    assert not (tmp_path / 'active.json').exists()


def test_dependency_install_normalizes_mirror_without_modifying_source(tmp_path, monkeypatch):
    from app import verification
    skill = tmp_path / 'skill'
    skill.mkdir()
    package = '{"name":"fixture","version":"1.0.0"}'
    lock = {'lockfileVersion': 3, 'packages': {'node_modules/demo': {
        'version': '1.0.0', 'resolved': 'https://registry.npmmirror.com/demo/-/demo-1.0.0.tgz',
        'integrity': 'sha512-fixture'}}}
    (skill / 'package.json').write_text(package)
    original = json.dumps(lock)
    (skill / 'package-lock.json').write_text(original)
    def install(command, cwd=None, **kwargs):
        assert command == ['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund']
        copied = json.loads((cwd / 'package-lock.json').read_text())
        item = copied['packages']['node_modules/demo']
        assert item['resolved'] == 'https://registry.npmjs.org/demo/-/demo-1.0.0.tgz'
        assert item['version'] == '1.0.0' and item['integrity'] == 'sha512-fixture'
        (cwd / 'node_modules').mkdir()
        (cwd / 'node_modules/fixture').write_text('installed')
    monkeypatch.setattr(verification, 'run', install)
    verification.install_dependencies(skill)
    assert (skill / 'package-lock.json').read_text() == original
    assert (skill / 'package.json').read_text() == package
    assert (skill / 'node_modules/fixture').read_text() == 'installed'
