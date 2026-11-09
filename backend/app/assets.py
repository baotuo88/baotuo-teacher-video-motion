"""Immutable, normalized media assets for one authenticated workspace.

Uploads are decoded and re-encoded: no HTML/SVG, metadata or supplied filenames
are executed. Archive hides an asset without breaking historic job snapshots.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import time
import uuid
import warnings
import wave
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .store import Conflict, Missing

MAX_UPLOAD = 20 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_SECONDS = 120
ID = re.compile(r'^[a-f0-9]{32}$')


class AssetError(ValueError):
    pass


def normalize(data: bytes, kind: str) -> tuple[bytes, dict]:
    if not data or len(data) > MAX_UPLOAD:
        raise AssetError('素材必须为 1 字节至 20MB')
    if kind == 'image':
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as source:
                    if source.format not in ('PNG', 'JPEG', 'WEBP') or getattr(source, 'n_frames', 1) != 1:
                        raise AssetError('仅支持静态 PNG/JPEG/WebP，不接受 SVG、GIF 或动画图片')
                    if source.width * source.height > MAX_PIXELS:
                        raise AssetError('图片不得超过 1600 万像素')
                    source.load()
                    image = ImageOps.exif_transpose(source).convert('RGBA')
                    image.thumbnail((4096, 4096))
                    # New image strips EXIF, ICC, text and all other source metadata.
                    clean = Image.new('RGBA', image.size)
                    clean.paste(image)
                    output = io.BytesIO()
                    clean.save(output, format='PNG')
                    encoded = output.getvalue()
                    if len(encoded) > MAX_UPLOAD:
                        raise AssetError('规范化后的图片超过 20MB，请缩小图片')
                    return encoded, {'kind': kind, 'width': clean.width, 'height': clean.height,
                                     'extension': 'png', 'mime': 'image/png'}
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as error:
            if isinstance(error, AssetError):
                raise
            raise AssetError('无法解码图片，或图片尺寸超出限制') from error
    if kind == 'audio':
        try:
            with wave.open(io.BytesIO(data), 'rb') as source:
                channels, width, rate, frames = (source.getnchannels(), source.getsampwidth(),
                                               source.getframerate(), source.getnframes())
                duration = frames / rate if rate else 0
                if (source.getcomptype() != 'NONE' or channels not in (1, 2) or width != 2
                        or not 8000 <= rate <= 96000 or not .2 <= duration <= MAX_SECONDS):
                    raise AssetError('配音需要 16-bit PCM WAV，单/双声道，8–96kHz，时长 0.2–120 秒')
                samples = source.readframes(frames)
                if len(samples) != frames * channels * width:
                    raise AssetError('WAV 音频数据不完整')
            output = io.BytesIO()
            with wave.open(output, 'wb') as clean:
                clean.setparams((channels, width, rate, 0, 'NONE', 'not compressed'))
                clean.writeframes(samples)
            return output.getvalue(), {'kind': kind, 'duration': round(duration, 4),
                                      'extension': 'wav', 'mime': 'audio/wav',
                                      'channels': channels, 'sample_rate': rate}
        except (wave.Error, EOFError, OSError) as error:
            raise AssetError('无效 WAV 文件；请导出为 16-bit PCM WAV') from error
    raise AssetError('不支持的素材类型')


def public_row(row) -> dict:
    return {**json.loads(row['metadata']), 'id': row['id'], 'name': row['name'],
            'sha256': row['sha256'], 'bytes': row['bytes'], 'created': row['created'],
            'archived': bool(row['archived'])}


def upload(store, name: str, kind: str, data: bytes) -> dict:
    if not name.strip() or len(name) > 120 or any(ord(c) < 32 for c in name):
        raise AssetError('素材名称需为 1–120 字，不含控制字符')
    content, metadata = normalize(data, kind)
    aid = uuid.uuid4().hex
    root = store.root / 'assets'
    root.mkdir(exist_ok=True)
    directory = root / aid
    digest = hashlib.sha256(content).hexdigest()
    # Publish bytes before DB row. Readers never observe partial uploads.
    with tempfile.TemporaryDirectory(prefix='.upload-', dir=root) as temporary:
        path = Path(temporary)
        (path / ('original.' + metadata['extension'])).write_bytes(content)
        if kind == 'image':
            with Image.open(io.BytesIO(content)) as image:
                image.thumbnail((480, 320))
                image.save(path / 'thumbnail.png', format='PNG')
        os.rename(path, directory)
    try:
        with store.connect() as db:
            db.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?,0)', (
                aid, name.strip(), kind, digest, len(content), json.dumps(metadata), time.time()))
    except BaseException:
        shutil.rmtree(directory)
        raise
    return get(store, aid)


def get(store, aid: str) -> dict:
    if not ID.fullmatch(aid):
        raise Missing('素材不存在')
    with store.connect() as db:
        row = db.execute('SELECT * FROM assets WHERE id=?', (aid,)).fetchone()
    if row is None:
        raise Missing('素材不存在')
    return public_row(row)


def listing(store, kind: str | None = None):
    if kind not in (None, 'image', 'audio'):
        raise AssetError('素材类型错误')
    with store.connect() as db:
        return [public_row(r) for r in db.execute(
            'SELECT * FROM assets WHERE archived=0 AND (? IS NULL OR kind=?) ORDER BY created DESC', (kind, kind))]


def archive(store, aid: str):
    get(store, aid)
    with store.connect() as db:
        db.execute('UPDATE assets SET archived=1 WHERE id=?', (aid,))
    return {'ok': True}


def content_path(store, aid: str, thumbnail=False):
    asset = get(store, aid)
    if thumbnail and asset['kind'] != 'image':
        raise Missing('该素材没有缩略图')
    file = store.root / 'assets' / aid / ('thumbnail.png' if thumbnail else 'original.' + asset['extension'])
    if not file.is_file() or file.is_symlink():
        raise Missing('素材文件不存在')
    return file, 'image/png' if thumbnail else asset['mime']


def validate_references(db, document: dict):
    """Called inside project transactions. Archived references remain valid."""
    for scene in document.get('scenes', []):
        for field, kind in (('image_id', 'image'), ('audio_id', 'audio')):
            aid = scene.get(field)
            if aid is None:
                continue
            if not isinstance(aid, str) or not ID.fullmatch(aid):
                raise Conflict('无效素材引用')
            row = db.execute('SELECT kind FROM assets WHERE id=?', (aid,)).fetchone()
            if row is None or row['kind'] != kind:
                raise Conflict('引用的素材不存在或类型不匹配')


def copy_verified(store, aid, expected_kind, destination):
    asset = get(store, aid)
    file, _ = content_path(store, aid)
    if asset['kind'] != expected_kind:
        raise AssetError('素材类型不匹配')
    # Hash the very bytes we copy, rather than hash then reopen (TOCTOU).
    content = file.read_bytes()
    if hashlib.sha256(content).hexdigest() != asset['sha256']:
        raise AssetError('素材文件已被修改，拒绝渲染')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return asset
