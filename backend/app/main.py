"""Single-host Alpha workspace and versioned runtime management API."""
import json
import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .runtime import RuntimeError_, change_summary, release
from .verification import activate

app = FastAPI(title='baotuo-teacher-video-motion', version='0.3.0',
              docs_url=None, redoc_url=None, openapi_url=None)
from .operations import BodyLimitMiddleware, CapacityError, ensure_capacity, ReadinessProbe
app.add_middleware(BodyLimitMiddleware)
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
from .models import ProjectInput, ProjectUpdate, RenderRequest, ProviderInput, GenerateRequest, ProductionSettings
from .store import Store, Conflict, Missing

DATA = Path(os.environ.get('DATA_ROOT', '.data')).resolve()
LOGIN_ATTEMPTS = auth.LOGIN_ATTEMPTS
READINESS = ReadinessProbe()


@app.get('/api/system/status', dependencies=[Depends(admin)])
def system_status():
    return READINESS.check(DATA, ROOT)


@app.get('/ready')
def ready():
    state = READINESS.check(DATA, ROOT)
    return JSONResponse({'status': 'ready' if state['ready'] else 'not_ready'},
                        status_code=200 if state['ready'] else 503)


@app.exception_handler(CapacityError)
async def capacity_handler(request, error):
    return JSONResponse(status_code=503, content={'detail': str(error)}, headers={'Retry-After': '60'})



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
    if not auth.check_credentials(request, 'admin', body.password):
        raise HTTPException(401, '密码错误')
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
    if name not in ('app.js', 'style.css', 'studio.css'):
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


@app.get('/api/projects/{pid}/production-settings', dependencies=[Depends(admin)])
def production_settings(pid: str):
    return store().production_settings(pid)


@app.put('/api/projects/{pid}/production-settings', dependencies=[Depends(admin)])
def save_production_settings(pid: str, body: ProductionSettings):
    return store().save_production_settings(pid, body.model_dump())


class Version(BaseModel):
    version: int = Field(ge=1)


@app.get('/api/project-trash', dependencies=[Depends(admin)])
def project_trash():
    return store().trashed_projects()


@app.post('/api/project-trash/{pid}/restore', dependencies=[Depends(admin)])
def restore_trashed_project(pid: str, body: Version):
    return store().restore_trashed_project(pid, body.version)


class DeleteProject(Version):
    confirm: bool


@app.delete('/api/projects/{pid}', dependencies=[Depends(admin)])
def delete_project(pid: str, body: DeleteProject):
    if not body.confirm:
        raise HTTPException(400, '请明确确认移入回收站；编辑历史、任务成片和共享素材将保留')
    return store().delete_project(pid, body.version)


@app.get('/api/projects/{pid}/jobs', dependencies=[Depends(admin)])
def project_jobs(pid: str):
    db = store()
    db.project(pid)
    return db.project_jobs(pid)


@app.get('/api/projects/{pid}/job-history', dependencies=[Depends(admin)])
def project_job_history(pid: str, before: str | None = Query(default=None, max_length=64), limit: int = Query(default=50, ge=1, le=100)):
    return store().project_job_history(pid, before, limit)


@app.get('/api/projects/{pid}/events', dependencies=[Depends(admin)])
async def project_events(pid: str, request: Request):
    import asyncio
    from starlette.responses import StreamingResponse
    db = await run_in_threadpool(store)
    await run_in_threadpool(db.project, pid)

    def snapshot():
        db.project(pid)
        items = db.project_jobs(pid)
        return {'jobs': items, 'events': {j['id']: db.recent_events(j['id']) for j in items[:20]}}

    async def stream():
        previous = None
        # Reconnect periodically to revalidate the HttpOnly session and project.
        for _ in range(50):
            if await request.is_disconnected():
                break
            try:
                data = json.dumps(await run_in_threadpool(snapshot), ensure_ascii=False)
            except Missing:
                yield 'event: removed\ndata: {}\n\n'
                break
            if data != previous:
                yield 'event: snapshot\ndata: ' + data + '\n\n'
                previous = data
            else:
                yield ': heartbeat\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


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
def events(jid: str, after: int = Query(default=0, ge=0)):
    store().job(jid)
    return store().events(jid, after)


@app.get('/api/jobs/{jid}/logs.txt', dependencies=[Depends(admin)])
def download_logs(jid: str):
    from starlette.responses import StreamingResponse
    db = store()
    item = db.job(jid)
    cutoff = db.event_cutoff(jid)
    return StreamingResponse(db.export_events(jid, cutoff), media_type='text/plain', headers={
        'Content-Disposition': f'attachment; filename="job-{item["id"]}-logs.txt"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    })


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
    config = json.loads(row['config'])
    if not config['enabled'] or config.get('capability', 'storyboard') != 'storyboard':
        raise HTTPException(409, '请选择已启用的文本分镜配置')
    return db.enqueue(pid, body.version, 'storyboard',
                      {'provider_id': body.provider_id, 'provider_version': row['updated'], 'auto_apply': True},
                      active_runtime(), body.idempotency_key)


@app.post('/api/jobs/{jid}/apply', dependencies=[Depends(admin)])
def apply_storyboard(jid: str, body: Version):
    db = store()
    item = db.job(jid)
    if (item.get('result') or {}).get('application', {}).get('status') == 'applied':
        raise HTTPException(409, '该结果已自动应用，无需再次应用')
    if item['kind'] in ('image', 'speech'):
        return apply_media_result(db, item, body.version)
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
    if original['status'] not in ('failed', 'interrupted', 'cancelled', 'unknown_outcome'):
        raise HTTPException(409, '只有失败、中断或取消的任务可以重试')
    if not body.confirm_cost:
        raise HTTPException(400, '请确认外部请求可能重复计费')
    # Reuse original version/runtime. Changes to project/provider must be resolved explicitly.
    return db.enqueue(original['project_id'], original['snapshot']['project']['version'], original['kind'],
                      original['snapshot']['options'], original['runtime_id'], body.idempotency_key)


# Raw-body uploads avoid multipart buffering and unbounded filename/path handling.
from . import assets
from starlette.concurrency import run_in_threadpool


@app.exception_handler(assets.AssetError)
async def asset_error_handler(request, error):
    return JSONResponse(status_code=400, content={'detail': str(error)})


@app.get('/api/assets', dependencies=[Depends(admin)])
def list_assets(kind: str | None = None):
    return assets.listing(store(), kind)


@app.post('/api/assets', dependencies=[Depends(admin)])
async def upload_asset(request: Request, name: str, kind: str):
    ensure_capacity(store().root)
    length = request.headers.get('content-length')
    if length:
        try:
            if int(length) < 0 or int(length) > assets.MAX_UPLOAD:
                raise HTTPException(413, '素材不能超过 20MB')
        except ValueError:
            raise HTTPException(400, '无效 Content-Length')
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > assets.MAX_UPLOAD:
            raise HTTPException(413, '素材不能超过 20MB')
        chunks.extend(chunk)
    return await run_in_threadpool(assets.upload, store(), name, kind, bytes(chunks))


@app.get('/api/assets/{aid}', dependencies=[Depends(admin)])
def get_asset(aid: str):
    return assets.get(store(), aid)


@app.get('/api/assets/{aid}/content', dependencies=[Depends(admin)])
def asset_content(aid: str):
    file, mime = assets.content_path(store(), aid)
    return FileResponse(file, media_type=mime)


@app.get('/api/assets/{aid}/thumbnail', dependencies=[Depends(admin)])
def asset_thumbnail(aid: str):
    file, mime = assets.content_path(store(), aid, thumbnail=True)
    return FileResponse(file, media_type=mime)


@app.delete('/api/assets/{aid}', dependencies=[Depends(admin)])
def archive_asset(aid: str):
    return assets.archive(store(), aid)


from .models import ModelDiscoveryInput


@app.post('/api/providers/models/discover', dependencies=[Depends(admin)])
def discover_provider_models(body: ModelDiscoveryInput):
    # Only a model-list request; never save credentials or invoke generation here.
    return providers.discover_models(store(), body)


from .models import MediaGenerateRequest


@app.post('/api/projects/{pid}/generate-media', dependencies=[Depends(admin)])
def generate_media(pid: str, body: MediaGenerateRequest):
    if not body.confirm_cost:
        raise HTTPException(400, '生成可能计费，必须确认')
    db = store()
    project = db.project(pid)
    if project['version'] != body.version or not project['confirmed']:
        raise HTTPException(409, '请保存并确认当前分镜再生成素材')
    if body.scene_index >= len(project['scenes']):
        raise HTTPException(400, '页面不存在')
    row = db.provider(body.provider_id)
    config = json.loads(row['config'])
    kind = config.get('capability', 'storyboard')
    if not config.get('enabled') or kind not in ('image', 'speech'):
        raise HTTPException(409, '请选择启用的图片或语音配置')
    scene = project['scenes'][body.scene_index]
    prompt = body.prompt.strip()
    if kind == 'image' and not prompt:
        prompt = ('为白板讲解制作清晰插图，不绘制文字。主题：' + project['title'] +
                  '。本页：' + scene['title'] + '。要点：' + '；'.join(scene['points']) +
                  '。口播：' + scene['narration'] + '。风格：' + project['style'])
    return db.enqueue(pid, body.version, kind, {'provider_id': body.provider_id,
        'provider_version': row['updated'], 'scene_index': body.scene_index, 'prompt': prompt, 'auto_apply': True},
        active_runtime(), body.idempotency_key)


def apply_media_result(db, item, version):
    if item['status'] != 'succeeded' or not item['result']:
        raise HTTPException(409, '素材尚未生成成功')
    old = db.project(item['project_id'])
    expected = item['snapshot']['project']['version']
    # A strict revision check also protects reordered/deleted pages, without guessing indices.
    if version != expected or old['version'] != expected:
        raise HTTPException(409, '项目已变化，请从素材库手动选择该结果，避免覆盖新稿')
    document = {key: old[key] for key in ('title', 'topic', 'style', 'scenes')}
    field = 'image_id' if item['kind'] == 'image' else 'audio_id'
    document['scenes'][item['result']['scene_index']][field] = item['result']['asset']['id']
    return db.edit(old['id'], version, ProjectInput.model_validate(document).model_dump())
