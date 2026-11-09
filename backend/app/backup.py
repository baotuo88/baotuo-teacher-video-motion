"""Offline, checksummed backups. Stop BOTH API and worker before using this CLI.

Backups contain encrypted credentials and private media; protect them as secrets.
The encryption key is intentionally not included: escrow it separately.
"""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path


EXCLUDED = {'worker.lock', 'worker-heartbeat', 'worker-heartbeat.tmp',
            'studio.sqlite3-wal', 'studio.sqlite3-shm'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            # npm includes executable symlinks; preserve only internal links.
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('备份包含指向目录外部的符号链接')
            result[path.relative_to(root).as_posix()] = {'link': str(path.readlink())}
        elif path.is_file():
            result[path.relative_to(root).as_posix()] = {'sha256': digest(path)}
    return result


def backup(source, destination):
    source, destination = source.resolve(), destination.resolve()
    if destination.is_relative_to(source):
        raise ValueError('备份位置不能位于数据目录内')
    if not (source / 'studio.sqlite3').is_file():
        raise ValueError('源目录没有数据库')
    with (source / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('请先停止 Worker 和 API') from None
        destination.mkdir(parents=True, exist_ok=False, mode=0o700)
        payload = destination / 'data'
        # Only exclude ephemeral files at root; preserve all runtime source files.
        shutil.copytree(source, payload, symlinks=True,
                        ignore=lambda path, names: EXCLUDED if Path(path) == source else set())
        # Upstream render jobs create absolute engine links. Rebase internal links
        # to relative paths so restoring at another mount point remains portable.
        for copied in payload.rglob('*'):
            if copied.is_symlink():
                original = source / copied.relative_to(payload)
                resolved = original.resolve()
                if not resolved.is_relative_to(source):
                    raise ValueError('备份包含指向目录外部的符号链接；运行时必须位于数据根目录内')
                relative = os.path.relpath(payload / resolved.relative_to(source), copied.parent)
                copied.unlink()
                copied.symlink_to(relative)
        with closing(sqlite3.connect(source / 'studio.sqlite3')) as db:
            with closing(sqlite3.connect(payload / 'studio.sqlite3')) as output:
                db.backup(output)
                output.execute('PRAGMA journal_mode=DELETE')
        (destination / 'manifest.json').write_text(json.dumps(
            {'format': 1, 'files': inventory(payload)}, ensure_ascii=False, indent=2))
    verify(destination)


def verify(archive):
    manifest = json.loads((archive / 'manifest.json').read_text())
    if manifest.get('format') != 1 or inventory(archive / 'data') != manifest['files']:
        raise ValueError('备份文件校验失败（丢失、修改或多余文件）')
    with closing(sqlite3.connect((archive / 'data/studio.sqlite3').resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('数据库完整性检查失败')


def restore(archive, destination):
    verify(archive)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('仅允许恢复到空目录，不覆盖现有数据')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copytree(archive / 'data', destination, symlinks=True, dirs_exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['backup', 'verify', 'restore'])
    parser.add_argument('archive', type=Path)
    parser.add_argument('--data', type=Path)
    parser.add_argument('--confirm-services-stopped', action='store_true')
    args = parser.parse_args()
    if args.command != 'verify' and (not args.confirm_services_stopped or args.data is None):
        parser.error('先停止 API 和 Worker，再指定 --data 和 --confirm-services-stopped')
    if args.command == 'backup':
        backup(args.data, args.archive)
    elif args.command == 'restore':
        restore(args.archive, args.data)
    else:
        verify(args.archive)
    print('备份校验/操作完成；请另行保管 PROVIDER_ENCRYPTION_KEY')


if __name__ == '__main__':
    main()
