"""Compile trusted scene layouts and drive a pinned upstream runtime."""
import json
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import time
import wave
from pathlib import Path

from .runtime import release
from . import assets


class Cancelled(Exception):
    pass


class ProductionError(ValueError):
    pass


class ProcessRunner:
    def __init__(self, store, jid, work):
        self.store, self.jid, self.work = store, jid, work

    def check(self):
        if self.store.job(self.jid)['cancel_requested']:
            raise Cancelled()

    def run(self, command, cwd=None, timeout=1200):
        self.check()
        # Never pass provider secrets / admin password to upstream subprocesses.
        allowed = ('PATH', 'HOME', 'TMPDIR', 'LANG', 'CHROME_PATH', 'FFMPEG_PATH', 'SYSTEMROOT')
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1')
        env['FFMPEG_PATH'] = os.environ.get('FFMPEG_PATH') or shutil.which('ffmpeg') or 'ffmpeg'
        with (self.work / 'process.log').open('ab') as output:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=output, stderr=output, start_new_session=True)
            start = time.monotonic()
            try:
                while process.poll() is None:
                    self.check()
                    if time.monotonic() - start > timeout:
                        raise ProductionError('阶段执行超时')
                    time.sleep(.3)
                if process.returncode:
                    raise ProductionError('执行失败：' + Path(command[1] if len(command) > 1 else command[0]).name
                                          + '，请检查任务运行日志')
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
        self.check()


def js(value):
    # Embedded in external JS, not HTML. Escape line separators for old parsers.
    return json.dumps(value, ensure_ascii=False).replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def compile_project(project: dict, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    pages = directory / 'pages'
    pages.mkdir(exist_ok=True)
    script = {'META': {'title': project['title'], 'name': 'video', 'style': project['style'],
                       'voice': {'speaker': 'studio'}, 'gap': .3},
              'PAGES': [{'id': f'p{i+1:02}', 'title': scene['title'], 'section': '讲解',
                         'cues': [scene['narration']]} for i, scene in enumerate(project['scenes'])]}
    (directory / 'script.js').write_text('globalThis.SCRIPT = ' + js(script) + ';\n')
    for i, scene in enumerate(project['scenes']):
        points = scene['points'] or [scene['narration'][:100]]
        lines = [f"ENGINE.visual('p{i+1:02}', P => {{", f"P.title({js(scene['title'])}, {{accent:'blue'}});"]
        if scene.get('image_id'):
            lines.append(f"P.img({js('assets/' + scene['image_id'] + '.png')},980,240,780,580,{{fit:'contain',at:P.c(0)}});")
        for index, point in enumerate(points):
            at = f'P.c(0) + {index * .5}'
            if scene.get('image_id'):
                lines.append(f"P.text({js(point)},{{x:160,y:{260+index*145},w:720,size:32,at:{at},mode:'fade'}});")
            elif scene['layout'] == 'process':
                x, y, width = 150 + index * 420, 330, 350
                lines += [f"P.box({x},{y},350,300,{{at:{at},color:'blue',sw:2}});",
                          f"P.text({js(str(index+1).zfill(2))},{{x:{x+24},y:{y+24},size:32,color:'blue',at:{at},mode:'fade'}});",
                          f"P.text({js(point)},{{x:{x+24},y:{y+92},w:302,size:30,at:{at},mode:'fade'}});"]
                if index:
                    lines.append(f"P.arrow({x-65},480,{x-14},480,{{at:{at},color:'blue'}});")
            elif scene['layout'] == 'compare':
                x, y = 160 + (index % 2) * 850, 250 + (index // 2) * 290
                lines += [f"P.box({x},{y},750,240,{{at:{at},color:'blue',sw:2}});",
                          f"P.text({js(point)},{{x:{x+28},y:{y+40},w:690,size:34,at:{at},mode:'fade'}});"]
            else:
                lines += [f"P.text({js(str(index+1).zfill(2))},{{x:170,y:{250+index*145},size:38,color:'blue',at:{at},mode:'fade'}});",
                          f"P.text({js(point)},{{x:270,y:{250+index*145},w:1430,size:38,at:{at},mode:'fade'}});"]
        lines.append('});')
        (pages / f'p{i+1:02}.js').write_text('\n'.join(lines))
    (directory / 'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="engine-modules" content="engine_modules/">'
        '<script src="script.js"></script><script src="engine/boot.js"></script><body></body></html>')


def create_audio(project, options, directory, skill, runner, store=None):
    if options['audio'] == 'edge' and importlib.util.find_spec('edge_tts') is None:
        raise ProductionError('本地缺少 edge-tts 依赖；请使用运行 Worker 的 Python 安装 backend/requirements.txt，或改用上传 WAV 配音')
    audio = directory / 'audio'
    audio.mkdir()
    pages = []
    for index, scene in enumerate(project['scenes']):
        runner.check()
        file = audio / f'p{index+1:02}.wav'
        if options['audio'] == 'uploaded':
            if store is None or not scene.get('audio_id'):
                raise ProductionError('每页必须绑定上传的 WAV 配音')
            assets.copy_verified(store, scene['audio_id'], 'audio', file)
        elif options['audio'] == 'edge':
            mp3 = audio / f'p{index+1:02}.mp3'
            runner.run([sys.executable, str(skill / 'scripts/edge_tts_speak.py'), '--text', scene['narration'],
                        '--voice', options['voice'], '--out', str(mp3)], timeout=180)
            runner.run([shutil.which('ffmpeg') or 'ffmpeg', '-y', '-i', str(mp3), '-ar', '24000', '-ac', '1', str(file)])
        else:
            with wave.open(str(file), 'wb') as output:
                output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                output.writeframes(b'\0\0' * 24000 * scene['duration'])
        with wave.open(str(file), 'rb') as source:
            duration = source.getnframes() / source.getframerate()
        pages.append([{'t': scene['narration'], 'f': 'audio/' + file.name, 'd': duration, 'o': 0.0}])
    (directory / 'voice.js').write_text('SCRIPT.VOICE = ' + js({'speaker': options['voice'], 'provider': options['audio'], 'pages': pages}) + ';')
    (directory / 'out').mkdir(exist_ok=True)
    # Delegate timestamps to this runtime's actual TIMING implementation.
    # In particular, o=0 cues do not insert the pageEnd pause.
    runner.run(['node', str(skill / 'engine/tools/script.mjs')], cwd=directory)


def render(store, job, runtimes):
    path, manifest = release(runtimes, job['runtime_id'])
    skill = path / 'skill'
    project, options = job['snapshot']['project'], job['snapshot']['options']
    work = store.root / 'jobs' / job['id']
    work.mkdir(parents=True, exist_ok=False)
    runner = ProcessRunner(store, job['id'], work)
    directory = work / 'project'
    store.event(job['id'], '编译分镜；使用锁定运行时 ' + job['runtime_id'])
    compile_project(project, directory)
    for scene in project['scenes']:
        if scene.get('image_id'):
            assets.copy_verified(store, scene['image_id'], 'image', directory / 'assets' / (scene['image_id'] + '.png'))
    runner.run([sys.executable, str(skill / 'scripts/ftnew.py'), str(directory), '--title', project['title'], '--style', project['style']])
    store.event(job['id'], {'edge': '生成在线配音', 'uploaded': '核验并使用逐页 WAV 配音', 'silent': '生成静音预览音轨（不是真实配音）'}[options['audio']])
    create_audio(project, options, directory, skill, runner, store)
    store.event(job['id'], '截图预览')
    runner.run(['node', str(skill / 'engine/tools/snap.mjs'), '--subs', '1.5'], cwd=directory)
    store.event(job['id'], '渲染 MP4；此阶段可能耗时数分钟')
    runner.run([sys.executable, str(skill / 'scripts/ftrender.py'), str(directory), '--fps', str(options['fps']), '--workers', '1'], timeout=3600)
    artifacts = []
    for file in sorted((directory / 'out').glob('*.mp4')):
        info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(file)], timeout=30))
        if not {'video', 'audio'} <= {s['codec_type'] for s in info['streams']}:
            raise ProductionError('产物缺少音视频轨')
        artifacts.append({'name': file.name, 'kind': 'video', 'bytes': file.stat().st_size, 'duration': info['format']['duration']})
    if not artifacts:
        raise ProductionError('没有生成 MP4')
    for file in (directory / 'out').glob('*.srt'):
        artifacts.append({'name': file.name, 'kind': 'subtitle', 'bytes': file.stat().st_size})
    preview = directory / 'out/snap/snap-1.5.png'
    if preview.is_file():
        shutil.copy2(preview, directory / 'out/preview.png')
        artifacts.append({'name': 'preview.png', 'kind': 'image', 'bytes': preview.stat().st_size})
    runner.check()
    return {'artifacts': artifacts, 'project_version': project['version'], 'runtime_id': job['runtime_id']}
