"""Single-host Alpha workspace and versioned runtime management API."""
import json
import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .runtime import RuntimeError_, change_summary, release
from .verification import activate

app = FastAPI(title='baotuo-teacher-video-motion', version='0.2.0')
ROOT = Path(os.environ.get('RUNTIME_ROOT', '.data/runtimes')).resolve()
WEB = Path(__file__).resolve().parents[2] / 'web'


from .auth import admin


@app.get('/health')
def health():
    return {'status': 'ok', 'phase': 'workspace-alpha'}


@app.get('/')
def index():
    return FileResponse(WEB / 'index.html')


@app.get('/api/runtimes', dependencies=[Depends(admin)])
def runtimes():
    items = []
    if ROOT.exists():
        for path in sorted(ROOT.glob('*/manifest.json')):
            entry = json.loads(path.read_text())
            entry['verified'] = (path.parent / 'verification.json').is_file()
            items.append(entry)
    active = json.loads((ROOT / 'active.json').read_text()) if (ROOT / 'active.json').exists() else None
    return {'items': items, 'active': active}


@app.get('/api/runtimes/{rid}/documents', dependencies=[Depends(admin)])
def documents(rid: str):
    try:
        path, _ = release(ROOT, rid)
        return {'skill': (path / 'skill/SKILL.md').read_text(),
                'verification': json.loads((path / 'verification.json').read_text())
                if (path / 'verification.json').exists() else None}
    except RuntimeError_ as error:
        raise HTTPException(400, str(error)) from error


@app.get('/api/runtimes/{rid}/compare/{other}', dependencies=[Depends(admin)])
def compare(rid: str, other: str):
    try:
        old, _ = release(ROOT, rid)
        new, _ = release(ROOT, other)
        return change_summary(old / 'skill', new / 'skill')
    except RuntimeError_ as error:
        raise HTTPException(400, str(error)) from error


class Activation(BaseModel):
    runtime_id: str = Field(pattern=r'^[0-9a-f]{24}$')
    confirm: bool


@app.post('/api/runtimes/activate', dependencies=[Depends(admin)])
def switch(body: Activation):
    if not body.confirm:
        raise HTTPException(400, '请确认切换默认运行时')
    try:
        return activate(ROOT, body.runtime_id)
    except RuntimeError_ as error:
        raise HTTPException(400, str(error)) from error


@app.get('/api/runtimes/{rid}/sample/{name}', dependencies=[Depends(admin)])
def sample(rid: str, name: str):
    try:
        path, _ = release(ROOT, rid)
        certificate = json.loads((path / 'verification.json').read_text())
        allowed = {entry['name'] for entry in certificate['artifacts']}
        if name not in allowed or Path(name).name != name:
            raise HTTPException(404, '样片不存在')
        return FileResponse(path / name, media_type='video/mp4', filename=name)
    except (RuntimeError_, OSError, ValueError) as error:
        raise HTTPException(404, '未找到有效的验证样片') from error


# Workspace routes use a durable store shared with the separate worker process.
import time
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from . import auth, providers
from .models import ProjectInput, ProjectUpdate, RenderRequest, ProviderInput, GenerateRequest
from .store import Store, Conflict, Missing

DATA = Path(os.environ.get('DATA_ROOT', '.data')).resolve()
LOGIN_ATTEMPTS = {}


def store():
    return Store(DATA)


@app.exception_handler(Conflict)
async def conflict_handler(request, error):
    return JSONResponse(status_code=409, content={'detail': str(error)})


@app.exception_handler(Missing)
async def missing_handler(request, error):
    return JSONResponse(status_code=404, content={'detail': str(error)})


@app.exception_handler(providers.ProviderError)
async def provider_handler(request, error):
    return JSONResponse(status_code=400, content={'detail': str(error)})


@app.middleware('http')
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


class Login(BaseModel):
    password: str = Field(max_length=4096)


@app.post('/api/auth/login')
def login(body: Login, request: Request, response: Response):
    auth.check_origin(request)
    expected = auth.password()
    ip = request.client.host if request.client else 'unknown'
    now = time.time()
    # Single API process in this deployment. Production multi-process needs a shared limiter.
    for key in list(LOGIN_ATTEMPTS):
        LOGIN_ATTEMPTS[key] = [t for t in LOGIN_ATTEMPTS[key] if now - t < 300]
        if not LOGIN_ATTEMPTS[key]:
            del LOGIN_ATTEMPTS[key]
    attempts = LOGIN_ATTEMPTS.setdefault(ip, [])
    if len(attempts) >= 10:
        raise HTTPException(429, '登录尝试过多，请五分钟后重试')
    if not secrets.compare_digest(body.password.encode(), expected.encode()):
        attempts.append(now)
        raise HTTPException(401, '密码错误')
    LOGIN_ATTEMPTS.pop(ip, None)
    token = auth.issue()
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite='strict',
                        secure=os.environ.get('COOKIE_SECURE') == '1', max_age=43200)
    return {'csrf': auth.sign('csrf:' + token)}


@app.get('/api/auth/session', dependencies=[Depends(admin)])
def session(request: Request):
    return {'csrf': auth.sign('csrf:' + request.cookies.get(auth.COOKIE, ''))}


@app.post('/api/auth/logout', dependencies=[Depends(admin)])
def logout(response: Response):
    response.delete_cookie(auth.COOKIE)
    return {'ok': True}


@app.get('/static/{name}')
def static(name: str):
    if name not in ('app.js', 'style.css'):
        raise HTTPException(404)
    return FileResponse(WEB / name)


@app.get('/api/projects', dependencies=[Depends(admin)])
def projects():
    return store().projects()


@app.post('/api/projects', dependencies=[Depends(admin)])
def create_project(body: ProjectInput):
    return store().create(body.model_dump())


@app.get('/api/projects/{pid}', dependencies=[Depends(admin)])
def get_project(pid: str):
    return store().project(pid)


@app.put('/api/projects/{pid}', dependencies=[Depends(admin)])
def edit_project(pid: str, body: ProjectUpdate):
    return store().edit(pid, body.version, body.model_dump(exclude={'version'}))


class Version(BaseModel):
    version: int = Field(ge=1)


@app.post('/api/projects/{pid}/confirm', dependencies=[Depends(admin)])
def confirm_project(pid: str, body: Version):
    return store().confirm(pid, body.version)


def active_runtime():
    try:
        rid = json.loads((ROOT / 'active.json').read_text())['runtime_id']
        path, manifest = release(ROOT, rid)
        certificate = json.loads((path / 'verification.json').read_text())
        if certificate.get('passed') is not True or certificate.get('source_digest') != manifest['source_digest']:
            raise ValueError('invalid certificate')
        return rid
    except (OSError, ValueError, KeyError) as error:
        raise HTTPException(409, '请先准备并激活已验证的运行时') from error


@app.post('/api/projects/{pid}/render', dependencies=[Depends(admin)])
def submit_render(pid: str, body: RenderRequest):
    return store().enqueue(pid, body.version, 'render', body.model_dump(exclude={'version', 'idempotency_key'}),
                           active_runtime(), body.idempotency_key)


@app.get('/api/jobs', dependencies=[Depends(admin)])
def jobs():
    return store().jobs()


@app.get('/api/jobs/{jid}', dependencies=[Depends(admin)])
def job(jid: str):
    return store().job(jid)


@app.get('/api/jobs/{jid}/events', dependencies=[Depends(admin)])
def events(jid: str, after: int = 0):
    store().job(jid)
    return store().events(jid, after)


@app.post('/api/jobs/{jid}/cancel', dependencies=[Depends(admin)])
def cancel(jid: str):
    return store().cancel(jid)


@app.get('/api/jobs/{jid}/artifacts/{name}', dependencies=[Depends(admin)])
def artifact(jid: str, name: str):
    item = store().job(jid)
    allowed = {a['name']: a for a in (item['result'] or {}).get('artifacts', [])}
    if item['status'] != 'succeeded' or name not in allowed or Path(name).name != name:
        raise HTTPException(404, '产物不存在')
    file = DATA / 'jobs' / jid / 'project/out' / name
    if not file.is_file():
        raise HTTPException(404, '产物文件已丢失')
    media = {'video': 'video/mp4', 'image': 'image/png', 'subtitle': 'text/plain; charset=utf-8'}[allowed[name]['kind']]
    return FileResponse(file, media_type=media)


@app.get('/api/providers', dependencies=[Depends(admin)])
def list_providers():
    return [providers.public_config(row) for row in store().provider_rows()]


@app.post('/api/providers', dependencies=[Depends(admin)])
def create_provider(body: ProviderInput):
    return providers.save(store(), body)


@app.put('/api/providers/{pid}', dependencies=[Depends(admin)])
def update_provider(pid: str, body: ProviderInput):
    return providers.save(store(), body, pid)


@app.post('/api/projects/{pid}/storyboard', dependencies=[Depends(admin)])
def storyboard(pid: str, body: GenerateRequest):
    if not body.confirm_cost:
        raise HTTPException(400, '调用可能计费，必须明确确认')
    db = store()
    row = db.provider(body.provider_id)
    if not json.loads(row['config'])['enabled']:
        raise HTTPException(409, '服务配置已禁用')
    return db.enqueue(pid, body.version, 'storyboard',
                      {'provider_id': body.provider_id, 'provider_version': row['updated']},
                      active_runtime(), body.idempotency_key)


@app.post('/api/jobs/{jid}/apply', dependencies=[Depends(admin)])
def apply_storyboard(jid: str, body: Version):
    db = store()
    item = db.job(jid)
    if item['kind'] != 'storyboard' or item['status'] != 'succeeded':
        raise HTTPException(409, '没有可应用的分镜结果')
    if body.version != item['snapshot']['project']['version']:
        raise HTTPException(409, '该生成结果基于旧版本，请重新生成或手动编辑')
    old = db.project(item['project_id'])
    doc = {key: old[key] for key in ('title', 'topic', 'style')}
    doc['scenes'] = item['result']['scenes']
    return db.edit(old['id'], body.version, ProjectInput.model_validate(doc).model_dump())


@app.get('/api/projects/{pid}/revisions', dependencies=[Depends(admin)])
def project_revisions(pid: str):
    return store().revisions(pid)


class RestoreVersion(BaseModel):
    version: int = Field(ge=1)
    target_version: int = Field(ge=1)


@app.post('/api/projects/{pid}/restore', dependencies=[Depends(admin)])
def restore_project(pid: str, body: RestoreVersion):
    db = store()
    revision = next((r for r in db.revisions(pid) if r['version'] == body.target_version), None)
    if revision is None:
        raise HTTPException(404, '版本不存在')
    return db.edit(pid, body.version, revision['document'])


@app.post('/api/projects/{pid}/duplicate', dependencies=[Depends(admin)])
def duplicate_project(pid: str):
    project = store().project(pid)
    document = {k: project[k] for k in ('title', 'topic', 'scenes', 'style')}
    document['title'] = document['title'][:55] + ' · 副本'
    return store().create(document)


class RetryRequest(BaseModel):
    confirm_cost: bool
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')


@app.post('/api/jobs/{jid}/retry', dependencies=[Depends(admin)])
def retry_job(jid: str, body: RetryRequest):
    db = store()
    original = db.job(jid)
    if original['status'] not in ('failed', 'interrupted', 'cancelled'):
        raise HTTPException(409, '只有失败、中断或取消的任务可以重试')
    if not body.confirm_cost:
        raise HTTPException(400, '请确认外部请求可能重复计费')
    # Reuse original version/runtime. Changes to project/provider must be resolved explicitly.
    return db.enqueue(original['project_id'], original['snapshot']['project']['version'], original['kind'],
                      original['snapshot']['options'], original['runtime_id'], body.idempotency_key)
