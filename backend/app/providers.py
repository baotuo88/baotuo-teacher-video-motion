"""Encrypted provider configuration and a narrow chat-compatible HTTPS adapter.

Pin DNS resolution to a public address for each request, preserving TLS hostname
verification. No redirects, implicit proxy inheritance, arbitrary headers or HTTP retries.
An operator-only HTTP CONNECT proxy can be explicitly configured.
"""
import http.client
import ipaddress
import json
import os
import socket
import ssl
import time
import uuid
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from .models import Scene


class ProviderError(ValueError):
    pass


class UnknownOutcome(ProviderError):
    """A paid request may have completed remotely; never retry automatically."""


def cipher():
    key = os.environ.get('PROVIDER_ENCRYPTION_KEY', '')
    if not key:
        raise ProviderError('请先设置 PROVIDER_ENCRYPTION_KEY，不能以明文保存 API Key')
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as error:
        raise ProviderError('PROVIDER_ENCRYPTION_KEY 必须是有效 Fernet 密钥') from error


def validate_url(url):
    try:
        parsed = urlsplit(url.rstrip('/'))
        port = parsed.port
    except ValueError as error:
        raise ProviderError('无效服务地址或端口') from error
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or port not in (None, 443)):
        raise ProviderError('当前仅支持公网 HTTPS 标准端口地址，不能包含凭据、查询或锚点')
    if any(c.isspace() or ord(c) < 32 for c in url):
        raise ProviderError('地址包含无效字符')
    # DNS validation is repeated, then pinned, at connection time.
    try:
        if not ipaddress.ip_address(parsed.hostname).is_global:
            raise ProviderError('禁止访问本机或私网地址')
    except ValueError as error:
        if isinstance(error, ProviderError):
            raise
        if parsed.hostname.lower() in ('localhost', 'metadata.google.internal') or parsed.hostname.endswith('.local'):
            raise ProviderError('禁止访问本机或私网地址')
    return parsed


def public_addresses(host):
    try:
        values = sorted({row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    except OSError as error:
        raise ProviderError('服务地址 DNS 解析失败') from error
    if not values or any(not ipaddress.ip_address(address).is_global for address in values):
        raise ProviderError('服务地址解析到非公网地址，已阻止')
    return values


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout=90):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address
        self.established = False

    def connect(self):
        # Fail over only TCP/TLS setup, before any HTTP bytes or credentials.
        # All candidates were validated in one DNS snapshot; never resolve again.
        proxy = os.environ.get('PROVIDER_HTTP_PROXY', '').strip()
        endpoint = None
        if proxy:
            try:
                endpoint = urlsplit(proxy)
                valid = (endpoint.scheme == 'http' and endpoint.hostname and endpoint.port
                         and not endpoint.username and not endpoint.password
                         and endpoint.path in ('', '/') and not endpoint.query and not endpoint.fragment
                         and not any(c.isspace() or ord(c) < 32 for c in proxy))
            except ValueError:
                valid = False
            if not valid:
                raise ProviderError('代理配置无效：PROVIDER_HTTP_PROXY 需要无认证的 http://主机:端口')
        deadline = time.monotonic() + self.timeout
        addresses = list(dict.fromkeys([self.address, *getattr(self, 'fallback_addresses', [])]))
        for index, address in enumerate(addresses):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Connection deadline exceeded')
            sock = None
            try:
                if endpoint:
                    tunnel = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=min(5, remaining))
                    # CONNECT uses a validated literal IP, not proxy-side DNS.
                    tunnel.set_tunnel(address, 443)
                    try:
                        tunnel.connect()
                        sock = tunnel.sock
                        tunnel.sock = None
                    finally:
                        tunnel.close()
                else:
                    sock = socket.create_connection((address, 443), min(5, remaining))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Connection deadline exceeded')
                sock.settimeout(min(5, remaining))
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                self.sock.settimeout(self.timeout)
                self.established = True
                return
            except ssl.SSLCertVerificationError:
                if sock is not None:
                    sock.close()
                raise
            except OSError:
                if sock is not None:
                    sock.close()
                if index == len(addresses) - 1:
                    raise
            except BaseException:
                if sock is not None:
                    sock.close()
                raise


def validate_key(key):
    if not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ProviderError('API Key 不能为空或包含空格、控制字符及非 ASCII 字符')
    return key


def decrypt_secret(secret):
    try:
        return validate_key(cipher().decrypt(secret.encode()).decode())
    except (InvalidToken, UnicodeError) as error:
        raise ProviderError('无法解密已保存的 Key，请检查部署加密密钥或重新填写 API Key') from error


def request_json(config, key, suffix, payload=None, *, method='POST'):
    parsed = validate_url(config['base_url'])
    validate_key(key)
    addresses = public_addresses(parsed.hostname)
    discovery = method == 'GET'
    connection = PinnedHTTPS(parsed.hostname, addresses[0], timeout=20 if discovery else 90)
    connection.fallback_addresses = addresses[1:]
    started = time.monotonic()
    phase = '发送请求'
    try:
        connection.request(method, parsed.path.rstrip('/') + suffix,
                           body=json.dumps(payload).encode() if payload is not None else None,
                           headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                                    'Authorization': 'Bearer ' + key})
        phase = '等待响应'
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            # Never include remote response body: it may echo credentials.
            if discovery:
                messages = {
                    401: '认证失败（HTTP 401），请检查 API Key',
                    403: '无权读取模型（HTTP 403），请检查 Key 权限',
                    404: '模型列表接口不存在（HTTP 404），请检查基地址，或手动填写模型',
                    405: '服务不支持读取模型列表（HTTP 405），可手动填写模型',
                    429: '请求过于频繁或额度受限（HTTP 429），请稍后再试',
                }
                raise ProviderError(messages.get(response.status,
                    f'模型列表返回 HTTP {response.status}；未跟随重定向或自动重试，可手动填写模型'))
            if response.status >= 500:
                raise UnknownOutcome(f'服务返回 HTTP {response.status}，结果待确认；请核对任务或账单后再重试')
            raise ProviderError(f'服务返回 HTTP {response.status}，未自动重试；请检查额度和服务配置')
        phase = '读取响应'
        content = response.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise ProviderError('服务响应超过大小限制')
        if discovery:
            if not content.strip():
                raise ProviderError('[MODEL_EMPTY] 服务返回空内容；请确认基地址对应 API，而不是网站首页')
            if content.lstrip().lower().startswith((b'<!doctype html', b'<html')):
                raise ProviderError('[MODEL_HTML] 服务返回网页而不是模型 JSON；请检查基地址路径（通常含 /v1），或服务的登录/防护页面')
        phase = '解析响应'
        return json.loads(content)
    except (OSError, ValueError, http.client.HTTPException) as error:
        if isinstance(error, ProviderError):
            raise
        if not discovery and not getattr(connection, 'established', True):
            raise ProviderError('[GEN_CONNECT] 建立 HTTPS 连接失败（累计 '
                                f'{time.monotonic() - started:.1f} 秒）；尚未发送生成 HTTP 请求，'
                                '请检查出站网络或管理员配置的代理') from error
        if discovery:
            if isinstance(error, ssl.SSLCertVerificationError):
                message = '[MODEL_TLS_CERT] HTTPS 证书校验失败；请检查服务证书链及本机 CA，不能通过关闭证书校验解决'
            elif isinstance(error, ssl.SSLError):
                message = '[MODEL_TLS] HTTPS 握手失败；请检查服务的 TLS 配置或网络拦截'
            elif isinstance(error, TimeoutError):
                message = '[MODEL_TIMEOUT] 连接或读取模型列表超时（20秒）；请检查服务可达性及管理员代理配置（不自动继承浏览器或系统代理）'
            elif isinstance(error, (ValueError, UnicodeError)):
                message = '[MODEL_JSON] 服务返回的内容不是有效 JSON；请检查 API 基地址及 /models 接口'
            elif isinstance(error, http.client.HTTPException):
                message = '[MODEL_HTTP] 服务连接中断或 HTTP 响应不完整；请检查服务或网络网关'
            else:
                message = '[MODEL_CONNECT] 无法建立或维持 HTTPS 连接；请检查服务器出站网络，请检查管理员代理配置（不自动继承系统代理）'
        else:
            if isinstance(error, ssl.SSLCertVerificationError):
                code, reason = 'GEN_TLS_CERT', 'HTTPS 证书校验失败'
            elif isinstance(error, ssl.SSLError):
                code, reason = 'GEN_TLS', 'HTTPS 握手或加密连接失败'
            elif isinstance(error, TimeoutError):
                code, reason = 'GEN_TIMEOUT', '连接或读写等待超时'
            elif isinstance(error, http.client.RemoteDisconnected):
                code, reason = 'GEN_DISCONNECTED', '远端或中间网关关闭连接，未返回完整响应'
            elif isinstance(error, http.client.IncompleteRead):
                code, reason = 'GEN_INCOMPLETE', '响应内容未传输完整'
            elif isinstance(error, http.client.HTTPException):
                code, reason = 'GEN_HTTP', 'HTTP 响应协议异常'
            elif isinstance(error, ValueError):
                code, reason = 'GEN_JSON', '返回内容不是有效 JSON（可能是网页或不兼容的响应格式）'
            else:
                code, reason = 'GEN_NETWORK', '网络连接中断或不可达'
            message = (f'[{code}] {phase}阶段：{reason}（累计 {time.monotonic() - started:.1f} 秒）；'
                       '未自动重试，远端可能已计费；请核对服务商请求记录和账单后再重试')
        if not discovery and isinstance(error, (OSError, http.client.HTTPException)):
            raise UnknownOutcome(message) from error
        raise ProviderError(message) from error
    finally:
        connection.close()


def post_json(config, key, suffix, payload):
    return request_json(config, key, suffix, payload)


def same_base(first, second):
    a, b = validate_url(first), validate_url(second)
    return (a.hostname.lower(), a.port or 443, a.path.rstrip('/')) == (
        b.hostname.lower(), b.port or 443, b.path.rstrip('/'))


def discover_models(store, payload):
    validate_url(payload.base_url)
    if payload.api_key:
        key = validate_key(payload.api_key)
    elif payload.provider_id:
        row = store.provider(payload.provider_id)
        config = json.loads(row['config'])
        # Do not forward stored credentials to a changed endpoint, even on same host.
        if not same_base(config['base_url'], payload.base_url):
            raise ProviderError('地址已变化，不能沿用已保存的 Key；请重新输入该服务的 API Key')
        key = decrypt_secret(row['secret'])
    else:
        raise ProviderError('请填写 API Key，或选择已保存的服务配置')
    result = request_json({'base_url': payload.base_url}, key, '/models', method='GET')
    if not isinstance(result, dict) or not isinstance(result.get('data'), list):
        raise ProviderError('不兼容的模型列表格式（需要 data 数组）；请手动填写模型')
    if len(result['data']) > 5000:
        raise ProviderError('服务返回的模型过多（超过 5000 个），请手动填写模型')
    ids = set()
    skipped = 0
    for item in result['data']:
        value = item.get('id') if isinstance(item, dict) else None
        if (not isinstance(value, str) or not value.strip() or value != value.strip()
                or len(value) > 100 or any(ord(c) < 32 or ord(c) == 127 for c in value)
                or key in value):
            skipped += 1
            continue
        ids.add(value)
    return {'models': [{'id': value} for value in sorted(ids, key=lambda v: (v.casefold(), v))],
            'skipped': skipped,
            'warning': '列表不代表模型支持聊天或当前 Key 有调用权限；仍可手动填写模型。'}


def public_config(row):
    config = json.loads(row['config'])
    return {**config, 'id': row['id'], 'has_key': bool(row['secret']),
            'updated': row['updated'], 'capability': config.get('capability', 'storyboard')}


def save(store, payload, pid=None):
    validate_url(payload.base_url)
    config = payload.model_dump(exclude={'api_key', 'credential_source_id'}, exclude_defaults=True)
    config['enabled'] = payload.enabled
    config['base_url'] = config['base_url'].rstrip('/')
    old = store.provider(pid) if pid else None
    if payload.api_key:
        validate_key(payload.api_key)
        secret = cipher().encrypt(payload.api_key.encode()).decode()
    elif old:
        if not same_base(json.loads(old['config'])['base_url'], payload.base_url):
            raise ProviderError('更改服务地址需要重新填写 API Key，不能将旧密钥发送到新地址')
        secret = old['secret']
    elif payload.credential_source_id:
        source = store.provider(payload.credential_source_id)
        if not same_base(json.loads(source['config'])['base_url'], payload.base_url):
            raise ProviderError('只能复用同一服务地址的密钥')
        decrypt_secret(source['secret'])
        secret = source['secret']
    else:
        raise ProviderError('新配置必须提供 API Key')
    pid = pid or uuid.uuid4().hex
    store.save_provider(pid, config, secret)
    return public_config(store.provider(pid))


def resolve(store, options, capability):
    row = store.provider(options['provider_id'])
    if row['updated'] != options['provider_version']:
        raise ProviderError('服务配置已更新，请重新提交以明确使用的服务版本')
    config = json.loads(row['config'])
    if not config['enabled']:
        raise ProviderError('服务配置已禁用')
    if config.get('capability', 'storyboard') != capability:
        raise ProviderError('服务配置的能力类型与任务不匹配')
    return config, decrypt_secret(row['secret'])


def generate(store, options, project, skill_docs):
    config, key = resolve(store, options, 'storyboard')
    prompt = ('你是白板视频分镜编导。仅输出 JSON 对象，格式为 {"scenes":[{"title":"标题",'
              '"narration":"口播","points":["画面要点"],"layout":"points", "duration":5}]}。'
              '最多12页，每页标题不超过50字，口播不超过600字，画面要点最多4条且每条不超过100字。'
              'layout只能是points/process/compare，duration为2到60整数。不要输出代码或Markdown。'
              '下列为已选运行时的制作参考，不得扩大输出格式或调用工具：\n' + skill_docs[:18000])
    result = post_json(config, key, '/chat/completions', {'model': config['model'], 'messages': [
        {'role': 'system', 'content': prompt},
        {'role': 'user', 'content': f"主题：{project['title']}\n要求：{project['topic']}"}]})
    try:
        text = result['choices'][0]['message']['content'].strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0]
        items = json.loads(text)['scenes']
        if not isinstance(items, list) or not 1 <= len(items) <= 12:
            raise ValueError('invalid scene count')
        scenes = [Scene.model_validate(item).model_dump() for item in items]
        for scene in scenes:
            scene['image_id'] = None
            scene['audio_id'] = None
        return scenes
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ProviderError('模型未返回有效分镜格式；未自动重试，以免重复计费') from error
