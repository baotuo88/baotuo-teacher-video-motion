"""One independent worker per local data volume, enforced by an OS lock."""
import fcntl
import json
import os
import signal
import time
import threading
from contextlib import contextmanager
from pathlib import Path

from . import providers
from .production import Cancelled, render
from .runtime import release
from .store import Store
from .media_generation import execute_media
from .providers import UnknownOutcome


def execute(store, job, runtimes):
    try:
        if store.job(job['id'])['cancel_requested']:
            raise Cancelled()
        if job['kind'] == 'render':
            result = render(store, job, runtimes)
        elif job['kind'] in ('image', 'speech'):
            result = execute_media(store, job)
        elif job['kind'] == 'storyboard':
            path, _ = release(runtimes, job['runtime_id'])
            store.event(job['id'], '调用分镜模型；不会自动重试付费请求')
            scenes = providers.generate(store, job['snapshot']['options'], job['snapshot']['project'],
                                        (path / 'skill/SKILL.md').read_text())
            if store.job(job['id'])['cancel_requested']:
                raise Cancelled()
            # Keep the result independent. Applying it uses optimistic concurrency.
            result = {'scenes': scenes, 'project_version': job['snapshot']['project']['version']}
        else:
            raise ValueError('未知任务类型')
        if store.job(job['id'])['cancel_requested']:
            raise Cancelled()
        store.finish(job['id'], 'succeeded', result=result)
        store.event(job['id'], '任务完成')
    except UnknownOutcome as error:
        store.finish(job['id'], 'unknown_outcome', error=str(error))
        store.event(job['id'], str(error))
    except Cancelled:
        store.finish(job['id'], 'cancelled')
        store.event(job['id'], '任务已取消；已发送的远端请求可能仍计费')
    except Exception as error:
        # Known errors contain sanitized messages; unexpected exceptions never leak keys.
        from .production import ProductionError
        from .assets import AssetError
        from .runtime import RuntimeError_
        message = str(error) if isinstance(error, (ProductionError, providers.ProviderError, RuntimeError_, AssetError)) else '任务执行异常：' + type(error).__name__
        store.finish(job['id'], 'failed', error=message)
        store.event(job['id'], message)


@contextmanager
def heartbeat(data):
    """Independent of long-running rendering/API requests; remove on clean exit."""
    stopped = threading.Event()
    target = data / 'worker-heartbeat'

    def beat():
        temporary = data / 'worker-heartbeat.tmp'
        while not stopped.is_set():
            temporary.write_text(str(time.time()))
            temporary.replace(target)
            stopped.wait(5)

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=6)
        target.unlink(missing_ok=True)


def main():
    data = Path(os.environ.get('DATA_ROOT', '.data')).resolve()
    runtimes = Path(os.environ.get('RUNTIME_ROOT', '.data/runtimes')).resolve()
    store = Store(data)
    with (data / 'worker.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('已有 Worker 正在运行，当前仅支持单 Worker')
        # Unhandled BaseException unwinds running subprocess cleanup on shutdown.
        def stop(*_):
            raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM, stop)
        store.recover()
        with heartbeat(data):
            try:
                while True:
                    job = store.claim()
                    if job:
                        execute(store, job, runtimes)
                    else:
                        time.sleep(1)
            except KeyboardInterrupt:
                pass


if __name__ == '__main__':
    main()
