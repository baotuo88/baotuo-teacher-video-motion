"""Admin sessions, CSRF protection and legacy Basic support for CLI clients."""
import base64
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

COOKIE = 'studio_session'


def password():
    value = os.environ.get('ADMIN_PASSWORD', '')
    if len(value) < 16:
        raise HTTPException(503, '请配置至少 16 位 ADMIN_PASSWORD')
    return value


def sign(value):
    return hmac.new(password().encode(), value.encode(), hashlib.sha256).hexdigest()


def issue():
    payload = f'{int(time.time())}.{secrets.token_hex(24)}'
    return payload + '.' + sign(payload)


def verify(token):
    try:
        timestamp, nonce, signature = token.split('.')
        age = time.time() - int(timestamp)
        return 0 <= age < 12 * 3600 and hmac.compare_digest(signature, sign(timestamp + '.' + nonce))
    except (ValueError, AttributeError):
        return False


def check_origin(request):
    origin = request.headers.get('origin')
    if origin:
        parsed = urlsplit(origin)
        if parsed.netloc != request.headers.get('host') or parsed.scheme != request.url.scheme:
            raise HTTPException(403, '跨站请求已拒绝')


def admin(request: Request):
    expected = password()
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        check_origin(request)
    header = request.headers.get('authorization', '')
    if header.startswith('Basic '):
        try:
            username, supplied = base64.b64decode(header[6:], validate=True).decode().split(':', 1)
            if secrets.compare_digest(username.encode(), b'admin') and secrets.compare_digest(supplied.encode(), expected.encode()):
                return
        except (ValueError, UnicodeError):
            pass
    token = request.cookies.get(COOKIE, '')
    if verify(token):
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and not secrets.compare_digest(
                request.headers.get('x-csrf-token', ''), sign('csrf:' + token)):
            raise HTTPException(403, 'CSRF 校验失败，请重新登录')
        return
    raise HTTPException(401, '请先登录')
