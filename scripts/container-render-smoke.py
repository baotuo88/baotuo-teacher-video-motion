"""Run INSIDE the built container: pinned upstream sample + workspace MP4 render.

Executes reviewed pinned upstream code, needs GitHub/npm, never calls paid APIs.
"""
import os
import uuid
from pathlib import Path

from app.runtime import stage
from app.verification import verify, activate
from app.store import Store
from app.worker import execute

root = Path('/data/runtimes')
manifest = stage(root, 'b19409957a9b08a3ae5e779a04f2f42559dc84d8',
                 '6145f7e3482628543bd6f2d68fe3b618d366213a')
rid = manifest['id']
verify(root, rid)
activate(root, rid)
store = Store(Path('/data'))
p = store.create({'title': '容器渲染验收', 'topic': '', 'style': 'whiteboard', 'scenes': [
    {'title': '真实视频输出', 'narration': '本样片仅检查渲染，不验证配音模型。',
     'points': ['容器内 Chromium', '真实 FFmpeg 编码'], 'layout': 'points', 'duration': 3}]})
p = store.confirm(p['id'], p['version'])
job = store.enqueue(p['id'], p['version'], 'render', {'audio': 'silent', 'fps': 12, 'voice': 'zh-CN-XiaoxiaoNeural'}, rid, uuid.uuid4().hex)
execute(store, store.claim(), root)
result = store.job(job['id'])
assert result['status'] == 'succeeded', result['error']
assert any(a['name'].endswith('.mp4') for a in result['result']['artifacts'])
print('Container sample + real workspace render passed (no paid API calls).')
