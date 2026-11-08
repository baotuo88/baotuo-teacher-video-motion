"""Versioned upstream sources. Inspection never executes upstream code.

Activation is gated by an externally executed smoke test, not static file presence.
No automatic preparation/installation of unreviewed remote code.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

SKILL_REPO = 'https://github.com/liangdabiao/whiteboard-teacher-video-motion.git'
ENGINE_REPO = 'https://github.com/sitor-ai/frametell.git'
ADAPTER_VERSION = '1'
REQUIRED = ('SKILL.md', 'package.json', 'package-lock.json', 'scripts/ftnew.py',
            'scripts/ftasset.py', 'scripts/ftvoice.py', 'scripts/ftrender.py',
            'lib/motion-svg.js', 'examples/sample/script.js')
SHA = re.compile(r'^[0-9a-f]{40}$')


class RuntimeError_(ValueError):
    pass


def git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', *args], cwd=cwd,
                            text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError_('Git 操作失败: ' + result.stderr[-1200:])
    return result.stdout.strip()


def remote_head(repo: str) -> str:
    # Repositories are platform constants, never arbitrary browser input.
    value = git('ls-remote', repo, 'HEAD').split()[0]
    if not SHA.fullmatch(value):
        raise RuntimeError_('远端未返回有效 commit')
    return value


def validate_sha(value: str) -> str:
    if not SHA.fullmatch(value):
        raise RuntimeError_('必须使用完整的 40 位小写 commit SHA')
    return value


def runtime_id(skill: str, engine: str) -> str:
    validate_sha(skill)
    validate_sha(engine)
    return hashlib.sha256(f'{skill}:{engine}:{ADAPTER_VERSION}'.encode()).hexdigest()[:24]


def snapshot(repo: str, commit: str, destination: Path, subpath: str | None = None) -> None:
    validate_sha(commit)
    with tempfile.TemporaryDirectory(prefix='upstream-') as directory:
        checkout = Path(directory)
        git('init', str(checkout))
        git('remote', 'add', 'origin', repo, cwd=checkout)
        git('fetch', '--depth=1', 'origin', commit, cwd=checkout)
        git('checkout', '--detach', 'FETCH_HEAD', cwd=checkout)
        if git('rev-parse', 'HEAD', cwd=checkout) != commit:
            raise RuntimeError_('下载的 commit 与请求不一致')
        source = checkout / subpath if subpath else checkout
        if not source.is_dir():
            raise RuntimeError_('上游目录不存在')
        # Reject symlinks rather than importing references to arbitrary host paths.
        for path in source.rglob('*'):
            if '.git' not in path.relative_to(source).parts and path.is_symlink():
                raise RuntimeError_(f'源码包含不受支持的符号链接: {path.relative_to(source)}')
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('.git'), dirs_exist_ok=True)
        if subpath:
            for name in ('LICENSE', 'NOTICE'):
                notice = checkout / name
                if notice.is_file() and not notice.is_symlink():
                    shutil.copy2(notice, destination / ('UPSTREAM-' + name))


def source_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if any(p in ('node_modules', '__pycache__', '.git') for p in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            raise RuntimeError_('运行时源码不允许符号链接')
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b'\0')
            digest.update(path.read_bytes())
    return digest.hexdigest()


def inspect_source(skill: Path, engine: Path) -> dict:
    errors = [f'缺少 {name}' for name in REQUIRED if not (skill / name).is_file()]
    if not (engine / 'tools/render.mjs').is_file():
        errors.append('缺少引擎 tools/render.mjs')
    try:
        for file in (skill / 'scripts').glob('*.py'):
            ast.parse(file.read_text(encoding='utf-8'), filename=str(file))
        package = json.loads((skill / 'package.json').read_text())
        lock = json.loads((skill / 'package-lock.json').read_text())
        if not lock.get('lockfileVersion'):
            errors.append('无有效依赖锁文件')
    except (SyntaxError, OSError, ValueError) as error:
        errors.append(str(error))
        package = {}
    return {'static_ok': not errors, 'errors': errors,
            'node': package.get('engines', {}).get('node'),
            'dependencies': package.get('dependencies', {}),
            'warning': '静态检查不执行源码，不能证明可以渲染；必须完成候选环境冒烟测试。'}


def stage(root: Path, skill_sha: str, engine_sha: str) -> dict:
    rid = runtime_id(skill_sha, engine_sha)
    destination = root / rid
    if destination.exists():
        return json.loads((destination / 'manifest.json').read_text())
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.candidate-', dir=root) as directory:
        candidate = Path(directory)
        snapshot(SKILL_REPO, skill_sha, candidate / 'skill')
        snapshot(ENGINE_REPO, engine_sha, candidate / 'skill/engine', 'packages/engine')
        report = inspect_source(candidate / 'skill', candidate / 'skill/engine')
        manifest = {'id': rid, 'skill_commit': skill_sha, 'engine_commit': engine_sha,
                    'adapter_version': ADAPTER_VERSION,
                    'source_digest': source_digest(candidate / 'skill'), 'inspection': report}
        (candidate / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        # Atomic publish. Existing immutable releases are never overwritten.
        os.rename(candidate, destination)
    return manifest


def release(root: Path, rid: str) -> tuple[Path, dict]:
    if not re.fullmatch(r'[0-9a-f]{24}', rid):
        raise RuntimeError_('无效运行时 ID')
    path = root / rid
    if not (path / 'manifest.json').is_file():
        raise RuntimeError_('运行时不存在')
    manifest = json.loads((path / 'manifest.json').read_text())
    if manifest['id'] != rid or source_digest(path / 'skill') != manifest['source_digest']:
        raise RuntimeError_('运行时源码已被修改，拒绝使用')
    return path, manifest


def change_summary(old: Path, new: Path) -> dict:
    def hashes(root: Path) -> dict:
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file() and not p.is_symlink()
                and not any(x in ('node_modules', '__pycache__', '.git') for x in p.relative_to(root).parts)}
    before, after = hashes(old), hashes(new)
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    return {'files': changed, 'requires_adapter_review': any(
        p.startswith(('scripts/', 'engine/')) or p in ('package.json', 'package-lock.json') for p in changed),
        'note': '文件差异仅用于审阅，不自动断言新增功能已被平台支持。'}
