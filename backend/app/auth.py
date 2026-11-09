"""Admin sessions, CSRF protection and legacy Basic support for CLI clients."""
import base64
import hashlib
import hmac
import os
import secrets
import re
import time
import threading
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

COOKIE = 'studio_session'
LOGIN_ATTEMPTS = {}
LOGIN_LOCK = threading.Lock()


def check_credentials(request, username, supplied):
    expected = password()
    ip = request.client.host if request.client else 'unknown'
    now = time.time()
    with LOGIN_LOCK:
        for key in list(LOGIN_ATTEMPTS):
            LOGIN_ATTEMPTS[key] = [t for t in LOGIN_ATTEMPTS[key] if now - t < 300]
            if not LOGIN_ATTEMPTS[key]:
                del LOGIN_ATTEMPTS[key]
        attempts = LOGIN_ATTEMPTS.setdefault(ip, [])
        if len(attempts) >= 10:
            raise HTTPException(429, '登录尝试过多，请五分钟后重试')
        valid = (secrets.compare_digest(username.encode(), b'admin')
                 and secrets.compare_digest(supplied.encode(), expected.encode()))
        if valid:
            LOGIN_ATTEMPTS.pop(ip, None)
        else:
            attempts.append(now)
        return valid



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
        if not isinstance(token, str) or not re.fullmatch(r'[0-9]{1,12}\.[0-9a-f]{48}\.[0-9a-f]{64}', token):
            return False
        timestamp, nonce, signature = token.split('.')
        age = time.time() - int(timestamp)
        return 0 <= age < 12 * 3600 and hmac.compare_digest(signature, sign(timestamp + '.' + nonce))
    except (ValueError, AttributeError):
        return False


def check_origin(request):
    origin = request.headers.get('origin')
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            raise HTTPException(403, '无效请求来源') from None
        if parsed.netloc != request.headers.get('host') or parsed.scheme != request.url.scheme:
            raise HTTPException(403, '跨站请求已拒绝')


def admin(request: Request):
    password()
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        check_origin(request)
    header = request.headers.get('authorization', '')
    if header.startswith('Basic '):
        try:
            username, supplied = base64.b64decode(header[6:], validate=True).decode().split(':', 1)
        except (ValueError, UnicodeError):
            username, supplied = '', ''
        if check_credentials(request, username, supplied):
            return
        raise HTTPException(401, '请先登录')
    token = request.cookies.get(COOKIE, '')
    if verify(token):
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and not secrets.compare_digest(
                request.headers.get('x-csrf-token', '').encode(), sign('csrf:' + token).encode()):
            raise HTTPException(403, 'CSRF 校验失败，请重新登录')
        return
    raise HTTPException(401, '请先登录')
