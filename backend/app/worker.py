"""One independent worker per local data volume, enforced by an OS lock."""
import fcntl
import json
import os
import signal
import time
from pathlib import Path

from . import providers
from .production import Cancelled, render
from .runtime import release
from .store import Store


def execute(store, job, runtimes):
    try:
        if store.job(job['id'])['cancel_requested']:
            raise Cancelled()
        if job['kind'] == 'render':
            result = render(store, job, runtimes)
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
    except Cancelled:
        store.finish(job['id'], 'cancelled')
        store.event(job['id'], '任务已取消；已发送的远端请求可能仍计费')
    except Exception as error:
        # Known errors contain sanitized messages; unexpected exceptions never leak keys.
        from .production import ProductionError
        from .runtime import RuntimeError_
        message = str(error) if isinstance(error, (ProductionError, providers.ProviderError, RuntimeError_)) else '任务执行异常：' + type(error).__name__
        store.finish(job['id'], 'failed', error=message)
        store.event(job['id'], message)


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
        (data / 'worker-heartbeat').write_text(str(time.time()))
        try:
            while True:
                (data / 'worker-heartbeat').write_text(str(time.time()))
                job = store.claim()
                if job:
                    execute(store, job, runtimes)
                else:
                    time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
