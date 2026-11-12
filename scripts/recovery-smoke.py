"""Offline recovery rehearsal on an isolated copy of generation-smoke output.

Run generation-smoke.py first. Does not stop, modify, or back up the live service.
Includes the shared runtime in the fixture so absolute upstream links can rebase.
"""
import hashlib
import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.backup import backup, restore, verify
from app.store import Store
from app.runtime import release

report = json.loads((ROOT / '.data/e2e/generation-report.json').read_text())
base = ROOT / '.data/e2e' / ('recovery-' + uuid.uuid4().hex[:8])
source, archive, target = (base / name for name in ('source', 'backup', 'restored'))
runtimes = ROOT / '.data/runtimes'
shutil.copytree(report['workspace'], source, symlinks=True)
shutil.copytree(runtimes, source / 'runtimes', symlinks=True)
for link in (source / 'jobs').rglob('*'):
    if link.is_symlink():
        suffix = link.resolve().relative_to(runtimes.resolve())
        link.unlink()
        link.symlink_to((source / 'runtimes' / suffix).resolve())
# Include active and trashed projects, settings and real task outputs in the v4 rehearsal.
from app.models import ProductionSettings
source_store = Store(source)
source_job = source_store.job(report['job'])
source_project = source_store.project(source_job['project_id'])
source_store.save_production_settings(source_project['id'], ProductionSettings(audio='uploaded').model_dump())
source_store.delete_project(source_project['id'], source_project['version'])
backup(source, archive)
verify(archive)
restore(archive, target)
verify(archive)
# Removing the fixture proves restored links do not depend on the source volume.
shutil.rmtree(source)
store = Store(target)
job = store.job(report['job'])
assert job['status'] == 'succeeded'
for artifact in job['result']['artifacts']:
    relative = Path('jobs') / job['id'] / 'project/out' / artifact['name']
    expected = Path(report['workspace']) / relative
    assert hashlib.sha256(expected.read_bytes()).digest() == hashlib.sha256((target / relative).read_bytes()).digest()
assert len(store.trashed_projects()) == 1
trashed = store.trashed_projects()[0]
assert trashed['id'] == source_project['id']
restored_project = store.restore_trashed_project(trashed['id'], trashed['version'])
assert restored_project['version'] == source_project['version'] + 1
assert restored_project['confirmed'] == source_project['confirmed']
assert restored_project['scenes'] == source_project['scenes']
assert store.production_settings(restored_project['id'])['audio'] == 'uploaded'
assert store.project_job_history(restored_project['id'])['items']
assert len(store.revisions(restored_project['id'])) == restored_project['version']
assert len(store.provider_rows()) == 3
release(target / 'runtimes', report['runtime'])
for link in (target / 'jobs').rglob('*'):
    if link.is_symlink():
        assert link.exists() and link.resolve().is_relative_to(target.resolve())
result = {'archive': str(archive), 'restored': str(target), 'job': job['id'],
          'artifacts_verified': len(job['result']['artifacts']), 'providers_preserved': 3,
          'runtime_preserved': True, 'source_removed': True,
          'trash_restored': True, 'settings_preserved': True, 'schema': 4,
          'scope': 'isolated complete workspace; not production volume; no real credentials'}
(ROOT / '.data/e2e/recovery-report.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
