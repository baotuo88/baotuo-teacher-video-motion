"""Encrypted provider configuration and a narrow chat-compatible HTTPS adapter.

Pin DNS resolution to a public address for each request, preserving TLS hostname
verification. No redirects, proxy inheritance, arbitrary request headers or retries.
"""
import http.client
import ipaddress
import json
import os
import socket
import ssl
import uuid
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from .models import Scene


class ProviderError(ValueError):
    pass


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
    def __init__(self, host, address):
        super().__init__(host, timeout=90, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def post_json(config, key, suffix, payload):
    parsed = validate_url(config['base_url'])
    address = public_addresses(parsed.hostname)[0]
    connection = PinnedHTTPS(parsed.hostname, address)
    try:
        connection.request('POST', parsed.path.rstrip('/') + suffix,
                           body=json.dumps(payload).encode(), headers={
                               'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            # Never include remote response body: it may echo credentials.
            raise ProviderError(f'服务返回 HTTP {response.status}，未自动重试；请检查额度和服务配置')
        content = response.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise ProviderError('服务响应超过大小限制')
        return json.loads(content)
    except (OSError, ValueError, http.client.HTTPException) as error:
        if isinstance(error, ProviderError):
            raise
        raise ProviderError('调用失败或响应格式无效；远端可能已计费，请确认后再重试') from error
    finally:
        connection.close()


def public_config(row):
    return {**json.loads(row['config']), 'id': row['id'], 'has_key': bool(row['secret']),
            'updated': row['updated'], 'capability': 'storyboard'}


def save(store, payload, pid=None):
    validate_url(payload.base_url)
    config = payload.model_dump(exclude={'api_key'})
    config['base_url'] = config['base_url'].rstrip('/')
    old = store.provider(pid) if pid else None
    if payload.api_key:
        if '\n' in payload.api_key or '\r' in payload.api_key:
            raise ProviderError('API Key 包含无效换行')
        secret = cipher().encrypt(payload.api_key.encode()).decode()
    elif old:
        secret = old['secret']
    else:
        raise ProviderError('新配置必须提供 API Key')
    pid = pid or uuid.uuid4().hex
    store.save_provider(pid, config, secret)
    return public_config(store.provider(pid))


def generate(store, options, project, skill_docs):
    row = store.provider(options['provider_id'])
    if row['updated'] != options['provider_version']:
        raise ProviderError('服务配置已更新，请重新提交以明确使用的服务版本')
    config = json.loads(row['config'])
    if not config['enabled']:
        raise ProviderError('服务配置已禁用')
    key = cipher().decrypt(row['secret'].encode()).decode()
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
        return [Scene.model_validate(item).model_dump() for item in items]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ProviderError('模型未返回有效分镜格式；未自动重试，以免重复计费') from error
