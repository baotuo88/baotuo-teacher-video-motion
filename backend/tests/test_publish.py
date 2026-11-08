"""Publication guard tests without modifying the actual working tree's Git state."""
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[2] / 'scripts/check-publish-files.py'


@pytest.fixture
def repository(tmp_path):
    subprocess.run(['git', 'init', str(tmp_path)], check=True, capture_output=True)
    return tmp_path


def stage(root, relative):
    file = root / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text('test fixture, not a secret')
    subprocess.run(['git', '-C', str(root), 'add', '--', relative], check=True)


def check(root):
    return subprocess.run([sys.executable, str(GUARD)], cwd=root, capture_output=True, text=True)


def test_example_config_is_publishable(repository):
    stage(repository, '.env.example')
    stage(repository, 'backend/app/main.py')
    assert check(repository).returncode == 0


@pytest.mark.parametrize('path', ['.env', '.env.production', '.data/studio.sqlite3',
                                  'secrets/private.pem', 'backups/export.json',
                                  'nested/.env', 'studio.sqlite3-wal'])
def test_tracked_local_data_is_rejected(repository, path):
    stage(repository, path)
    result = check(repository)
    assert result.returncode != 0
    assert path in result.stderr
