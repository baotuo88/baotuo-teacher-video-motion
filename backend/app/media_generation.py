"""Bounded image and speech protocol adapters; generation never auto-applies.

Supported protocols: POST /images/generations (data[0].b64_json/url),
POST /audio/speech (binary audio). No redirects or automatic charge retries.
"""
import base64
import binascii
import http.client
import json
import shutil
import time
from urllib.parse import urlsplit

from . import assets, providers
from .production import ProcessRunner, Cancelled

MAX_MEDIA = 20 * 1024 * 1024
MAX_JSON = 28 * 1024 * 1024


from .providers import UnknownOutcome


def fetch_bytes(base_url, key=None, *, suffix='', payload=None, download=False):
    if any(c.isspace() or ord(c) < 32 for c in base_url):
        raise providers.ProviderError('媒体地址包含无效字符')
    try:
        parsed = urlsplit(base_url)
    except ValueError as error:
        raise providers.ProviderError('媒体地址格式无效') from error
    if download:
        if len(base_url) > 8192:
            raise providers.ProviderError('图片下载地址过长')
        # Signed CDN queries are allowed, credentials/fragments/private destinations aren't.
        providers.validate_url(parsed._replace(query='').geturl())
    else:
        providers.validate_url(base_url)
        providers.validate_key(key)
    addresses = providers.public_addresses(parsed.hostname)
    connection = providers.PinnedHTTPS(parsed.hostname, addresses[0], timeout=90)
    connection.fallback_addresses = addresses[1:]
    limit = MAX_JSON if suffix == '/images/generations' else MAX_MEDIA
    started = False
    try:
        headers = {'Accept': '*/*'}
        if not download:
            headers.update({'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
        target = (parsed.path or '/') if download else parsed.path.rstrip('/') + suffix
        if download and parsed.query:
            target += '?' + parsed.query
        started = True
        connection.request('GET' if download else 'POST', target,
                           body=None if download else json.dumps(payload).encode(), headers=headers)
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            if not download and response.status >= 500:
                raise UnknownOutcome(f'服务返回 HTTP {response.status}，生成结果待确认；请核对服务商任务或账单后再重试')
            raise providers.ProviderError(f'媒体服务返回 HTTP {response.status}；未跟随重定向或重试')
        content = response.read(limit + 1)
        if len(content) > limit:
            raise providers.ProviderError('生成结果超出大小限制，可能已计费，请核对后再重试')
        return content
    except (OSError, http.client.HTTPException) as error:
        if started and not download:
            raise UnknownOutcome('生成请求中断或超时，远端可能已接受；请核对任务或账单，禁止盲目重试') from error
        raise providers.ProviderError('媒体下载失败；原生成可能已计费，未自动重试') from error
    finally:
        connection.close()


def image_bytes(config, key, prompt):
    payload = {'model': config['model'], 'prompt': prompt, 'n': 1}
    if config.get('image_size', 'auto') != 'auto':
        payload['size'] = config['image_size']
    content = fetch_bytes(config['base_url'], key, suffix='/images/generations', payload=payload)
    try:
        result = json.loads(content)
        item = result['data'][0]
        if isinstance(item.get('b64_json'), str):
            if len(item['b64_json']) > (MAX_MEDIA * 4 // 3 + 8):
                raise ValueError('oversize')
            decoded = base64.b64decode(item['b64_json'], validate=True)
        elif isinstance(item.get('url'), str):
            # Never forward provider credentials to a generated CDN URL.
            decoded = fetch_bytes(item['url'], download=True)
        else:
            raise ValueError('unsupported response')
        if len(decoded) > MAX_MEDIA:
            raise ValueError('oversize')
        return decoded
    except (KeyError, IndexError, TypeError, ValueError, binascii.Error) as error:
        if isinstance(error, providers.ProviderError):
            raise
        raise providers.ProviderError('图片返回格式无效：需要 data[0].b64_json 或 url；原请求可能已计费') from error


def execute_media(store, job):
    options, project = job['snapshot']['options'], job['snapshot']['project']
    capability = job['kind']
    config, key = providers.resolve(store, options, capability)
    scene = project['scenes'][options['scene_index']]
    work = store.root / 'jobs' / job['id']
    work.mkdir(parents=True, exist_ok=False)
    runner = ProcessRunner(store, job['id'], work)
    runner.check()
    store.event(job['id'], '调用图片模型' if capability == 'image' else '调用语音模型')
    if capability == 'image':
        content = image_bytes(config, key, options['prompt'])
        kind = 'image'
    else:
        content = fetch_bytes(config['base_url'], key, suffix='/audio/speech', payload={
            'model': config['model'], 'input': scene['narration'], 'voice': config.get('voice', 'alloy'),
            'speed': config.get('speed', 1.0), 'response_format': 'wav'})
        runner.check()
        # Even unexpected MP3/other returned audio is decoded under protocol/resource limits.
        raw = work / 'response.audio'
        output = work / 'normalized.wav'
        raw.write_bytes(content)
        runner.run([shutil.which('ffmpeg') or 'ffmpeg', '-nostdin', '-y', '-v', 'error',
                    '-protocol_whitelist', 'file,pipe', '-threads', '1', '-i', str(raw),
                    '-vn', '-map_metadata', '-1', '-ac', '1', '-ar', '24000',
                    '-c:a', 'pcm_s16le', '-t', '121', str(output)], timeout=60)
        content = output.read_bytes()
        raw.unlink(missing_ok=True)
        kind = 'audio'
    runner.check()
    asset = assets.upload(store, scene['title'][:70] + (' · AI图片' if kind == 'image' else ' · AI配音'), kind, content)
    # Provenance is independent from bytes and never includes credentials.
    provenance = {'job_id': job['id'], 'project_id': job['project_id'], 'project_version': project['version'],
                  'scene_index': options['scene_index'], 'provider_id': options['provider_id'],
                  'provider_version': options['provider_version'], 'model': config['model'],
                  'capability': capability, 'created': time.time()}
    with store.connect() as db:
        row = db.execute('SELECT metadata FROM assets WHERE id=?', (asset['id'],)).fetchone()
        metadata = json.loads(row['metadata'])
        metadata['generation'] = provenance
        db.execute('UPDATE assets SET metadata=? WHERE id=?', (json.dumps(metadata), asset['id']))
    store.event(job['id'], '产物已保存到素材库，等待审核应用')
    return {'asset': assets.get(store, asset['id']), 'scene_index': options['scene_index'],
            'project_version': project['version'], 'capability': capability}
