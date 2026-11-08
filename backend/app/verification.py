"""Operator-run compatibility checks. Never triggered automatically by discovery."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

from .runtime import RuntimeError_, release


def run(command: list[str], cwd: Path | None = None, timeout: int = 900) -> None:
    subprocess.run(command, cwd=cwd, check=True, timeout=timeout)


def verify(root: Path, rid: str) -> dict:
    """Execute reviewed upstream code and a silent sample render without paid APIs."""
    path, manifest = release(root, rid)
    if not manifest['inspection']['static_ok']:
        raise RuntimeError_('静态检查失败，无法准备运行环境')
    # A failed revalidation must invalidate an earlier certificate.
    (path / 'verification.json').unlink(missing_ok=True)
    skill = path / 'skill'
    run(['npm', 'ci', '--ignore-scripts'], cwd=skill)
    # FFmpeg comes from the host/container, not an npm lifecycle download.
    with tempfile.TemporaryDirectory(prefix='whiteboard-smoke-') as directory:
        import shutil
        project = Path(directory) / 'project'
        shutil.copytree(skill / 'examples/sample', project)
        scripts = skill / 'scripts'
        def script(name: str, *args: str) -> None:
            run([sys.executable, str(scripts / name), str(project), *args])
        script('ftnew.py', '--title', '运行时兼容性样片', '--style', 'whiteboard')
        script('ftasset.py', '--spec', str(project / 'assets.json'))
        # This sample validates timing/rendering, not speech synthesis quality.
        audio = Path(directory) / 'audio'
        audio.mkdir()
        for i in range(3):
            with wave.open(str(audio / f'{i}.wav'), 'wb') as output:
                output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                output.writeframes(b'\0\0' * 48000)
        script('ftvoice.py', '--backend', 'user', '--user-audio', str(audio))
        script('ftrender.py', '--fps', '12', '--workers', '1')
        videos = sorted((project / 'out').glob('*.mp4'))
        if not videos:
            raise RuntimeError_('冒烟测试没有生成视频')
        artifacts = []
        for video in videos:
            probe = json.loads(subprocess.check_output([
                'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(video)
            ], text=True, timeout=30))
            kinds = {s['codec_type'] for s in probe['streams']}
            if not {'video', 'audio'} <= kinds or float(probe['format']['duration']) <= 0:
                raise RuntimeError_('样片缺少有效音视频轨')
            artifacts.append({'name': video.name, 'sha256': hashlib.sha256(video.read_bytes()).hexdigest(),
                              'duration': probe['format']['duration']})
            shutil.copy2(video, path / video.name)
    # Recheck source integrity after executing upstream tools.
    release(root, rid)
    certificate = {'runtime_id': rid, 'source_digest': manifest['source_digest'],
                   'passed': True, 'checked_at': time.time(), 'artifacts': artifacts,
                   'scope': '自带单页 SVG/GIF + 静音音轨 + MP4；不证明在线 API 或所有新增功能兼容'}
    (path / 'verification.json').write_text(json.dumps(certificate, ensure_ascii=False, indent=2))
    return certificate


def activate(root: Path, rid: str) -> dict:
    path, manifest = release(root, rid)
    try:
        certificate = json.loads((path / 'verification.json').read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError_('尚未通过真实渲染验证，不允许激活') from error
    if (certificate.get('passed') is not True or certificate.get('runtime_id') != rid
            or certificate.get('source_digest') != manifest['source_digest'] or not certificate.get('artifacts')):
        raise RuntimeError_('兼容性验证记录无效')
    for artifact in certificate['artifacts']:
        name = artifact['name']
        if Path(name).name != name:
            raise RuntimeError_('无效验证产物路径')
        file = path / name
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != artifact['sha256']:
            raise RuntimeError_('兼容性验证产物丢失或已修改')
    # Switching affects only future task submissions; consumers pin runtime_id.
    with tempfile.NamedTemporaryFile(mode='w', dir=root, delete=False) as output:
        json.dump({'runtime_id': rid, 'activated_at': time.time()}, output)
        name = output.name
    os.replace(name, root / 'active.json')
    return manifest
