"""Start both local processes; generate secrets once without logging them."""
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
file = ROOT / '.env'
if not file.exists():
    from cryptography.fernet import Fernet
    content = (f'ADMIN_PASSWORD={secrets.token_urlsafe(32)}\n'
               f'PROVIDER_ENCRYPTION_KEY={Fernet.generate_key().decode()}\nPORT=8000\nCOOKIE_SECURE=0\n')
    with os.fdopen(os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
        output.write(content)
    print('已生成 .env（权限600），请从该文件读取管理员密码。')
env = dict(os.environ)
for line in file.read_text().splitlines():
    if line.strip() and not line.lstrip().startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        env.setdefault(key.strip(), value.strip())
if len(env.get('ADMIN_PASSWORD', '')) < 16:
    raise SystemExit('请设置 .env 中至少16位的 ADMIN_PASSWORD')
env['PYTHONPATH'] = str(ROOT / 'backend')
port = str(int(env.get('PORT', '8000')))
children = []
try:
    children.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', port], env=env))
    children.append(subprocess.Popen([sys.executable, '-m', 'app.worker'], env=env))
    print(f'工作台 http://127.0.0.1:{port}；Ctrl+C 停止。')
    while all(p.poll() is None for p in children):
        time.sleep(.5)
except KeyboardInterrupt:
    pass
finally:
    for child in children:
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
