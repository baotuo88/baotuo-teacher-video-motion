"""Fail CI if local config/data has been tracked, even when .gitignore exists."""
import subprocess
from pathlib import PurePosixPath

paths = subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')
bad = []
for value in filter(None, paths):
    path = PurePosixPath(value)
    if (any(part in ('.data', '.venv', 'backups', 'node_modules') for part in path.parts)
            or any(part.startswith('.env') and part != '.env.example' for part in path.parts)
            or path.suffix in ('.pem', '.key', '.sqlite3', '.db')
            or '.sqlite3-' in path.name):
        bad.append(value)
if bad:
    raise SystemExit('拒绝发布包含本地配置/数据的仓库：\n' + '\n'.join(bad))
print('Tracked file check passed (not a substitute for comprehensive secret scanning).')
