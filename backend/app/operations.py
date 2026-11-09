"""Single-host operational probes and resource admission limits."""
import json
import os
import shutil
import time
import threading
from pathlib import Path

from cryptography.fernet import Fernet


class CapacityError(ValueError):
    pass


def ensure_capacity(root):
    minimum = int(os.environ.get('MIN_FREE_DISK_MB', '1024')) * 1024 * 1024
    if shutil.disk_usage(root).free < minimum:
        raise CapacityError('剩余磁盘不足，已暂停新任务和素材上传，请扩容或备份后清理')


def worker_alive(root):
    try:
        age = time.time() - float((Path(root) / 'worker-heartbeat').read_text())
        return 0 <= age < 30
    except (OSError, ValueError):
        return False


def readiness(store, runtimes):
    checks = {}
    try:
        with store.connect() as db:
            checks['database'] = db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    except Exception:
        checks['database'] = False
    checks['worker'] = worker_alive(store.root)
    try:
        ensure_capacity(store.root)
        checks['disk'] = True
    except (OSError, CapacityError):
        checks['disk'] = False
    checks['admin_password'] = len(os.environ.get('ADMIN_PASSWORD', '')) >= 16
    try:
        cipher = Fernet(os.environ.get('PROVIDER_ENCRYPTION_KEY', '').encode())
        for row in store.provider_rows():
            cipher.decrypt(row['secret'].encode())
        checks['encryption_key'] = True
    except Exception:
        checks['encryption_key'] = False
    try:
        from .runtime import release
        rid = json.loads((runtimes / 'active.json').read_text())['runtime_id']
        path, manifest = release(runtimes, rid)
        certificate = json.loads((path / 'verification.json').read_text())
        checks['runtime'] = (certificate.get('passed') is True
                             and certificate.get('runtime_id') == rid
                             and certificate.get('source_digest') == manifest['source_digest']
                             and bool(certificate.get('artifacts'))
                             and all(Path(a['name']).name == a['name'] and (path / a['name']).is_file()
                                     for a in certificate['artifacts']))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        checks['runtime'] = False
    return {'ready': all(checks.values()), 'checks': checks,
            'free_disk_mb': shutil.disk_usage(store.root).free // (1024 * 1024)}


class ReadinessProbe:
    """Serialize/cache expensive checks to bound unauthenticated probe traffic."""
    def __init__(self, ttl=10):
        self.ttl = ttl
        self.lock = threading.Lock()
        self.result = None
        self.checked = 0
        self.identity = None

    def check(self, root, runtimes):
        identity = (root, runtimes)
        with self.lock:
            now = time.monotonic()
            if self.result is not None and identity == self.identity and now - self.checked < self.ttl:
                return self.result
            try:
                from .store import Store
                result = readiness(Store(root), runtimes)
            except Exception:
                # Database startup/schema/read-only volume failures must fail closed,
                # not leak local paths/tracebacks or report the API as ready.
                result = {'ready': False, 'checks': {'database': False}, 'free_disk_mb': 0}
            self.result, self.checked, self.identity = result, time.monotonic(), identity
            return result


class BodyLimitMiddleware:
    """Bound raw streamed bodies too, before FastAPI buffers JSON/uploads."""
    def __init__(self, app, limit=21 * 1024 * 1024):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        # JSON configurations should never need the media upload allowance.
        limit = self.limit if scope['path'] == '/api/assets' else 1024 * 1024
        from starlette.responses import JSONResponse
        from starlette.exceptions import HTTPException
        headers = dict(scope['headers'])
        try:
            size = int(headers.get(b'content-length', b'0'))
            if size < 0:
                raise ValueError()
        except ValueError:
            return await JSONResponse({'detail': '无效 Content-Length'}, 400)(scope, receive, send)
        if size > limit:
            return await JSONResponse({'detail': '请求体超过大小限制'}, 413)(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get('body', b''))
            if received > limit:
                raise HTTPException(413, '请求体超过大小限制')
            return message

        await self.app(scope, limited_receive, send)
