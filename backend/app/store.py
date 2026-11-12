"""Single-host durable workspace and task queue.

SQLite transactions are the Interface for concurrency: compare-and-swap edits,
immutable task snapshots, atomic task claiming. No in-process background jobs.
"""
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Conflict(ValueError):
    pass


class Missing(ValueError):
    pass


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.database = root / 'studio.sqlite3'
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > 4:
                raise RuntimeError('数据库版本高于本程序，请勿使用旧镜像覆盖新数据库')
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, version INTEGER NOT NULL, confirmed INTEGER,
                document TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS revisions (
                project_id TEXT NOT NULL, version INTEGER NOT NULL, document TEXT NOT NULL,
                PRIMARY KEY(project_id,version));
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
                status TEXT NOT NULL, snapshot TEXT NOT NULL, runtime_id TEXT,
                idempotency TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL, error TEXT,
                result TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                created REAL NOT NULL, message TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS providers (
                id TEXT PRIMARY KEY, config TEXT NOT NULL, secret TEXT NOT NULL,
                updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, metadata TEXT NOT NULL,
                created REAL NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
            ''')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS production_settings (
                project_id TEXT PRIMARY KEY, version INTEGER NOT NULL, config TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS project_trash (
                id TEXT PRIMARY KEY, version INTEGER NOT NULL, confirmed INTEGER,
                document TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                deleted_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS jobs_project_created ON jobs(project_id,created DESC,id DESC);
            CREATE INDEX IF NOT EXISTS events_job_id ON events(job_id,id);
            ''')
            db.execute('PRAGMA user_version=4')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def project_row(row):
        if row is None:
            raise Missing('项目不存在')
        return {**json.loads(row['document']), 'id': row['id'], 'version': row['version'],
                'confirmed': row['confirmed'] == row['version'], 'updated': row['updated']}

    def projects(self):
        with self.connect() as db:
            return [self.project_row(r) for r in db.execute('SELECT * FROM projects ORDER BY updated DESC')]

    def project(self, pid):
        with self.connect() as db:
            return self.project_row(db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone())

    def delete_project(self, pid, version):
        # Serialize with enqueue/claim; retain immutable job snapshots and shared assets.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
            project = self.project_row(row)
            if project['version'] != version:
                raise Conflict('项目已变化，请刷新后再删除')
            if db.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')", (pid,)).fetchone():
                raise Conflict('项目还有排队或运行中的任务，请先取消并等待任务结束')
            db.execute('INSERT INTO project_trash SELECT *,? FROM projects WHERE id=?', (time.time(), pid))
            db.execute('DELETE FROM projects WHERE id=?', (pid,))
        return {'deleted': True, 'recoverable': True}

    def trashed_projects(self):
        with self.connect() as db:
            return [{**self.project_row(row), 'deleted_at': row['deleted_at']}
                    for row in db.execute('SELECT * FROM project_trash ORDER BY deleted_at DESC,id DESC')]

    def restore_trashed_project(self, pid, version):
        # Moving rows between active/trash tables keeps all existing active-project
        # guards effective, including edits, enqueue, confirmation and auto-apply.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM project_trash WHERE id=?', (pid,)).fetchone()
            if row is None:
                raise Missing('回收站中没有此项目；可能已恢复')
            if row['version'] != version:
                raise Conflict('回收站项目版本已变化，请刷新后重试')
            if db.execute('SELECT 1 FROM projects WHERE id=?', (pid,)).fetchone():
                raise Conflict('项目已存在，不能覆盖')
            next_version = version + 1
            confirmed = next_version if row['confirmed'] == version else None
            db.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)',
                       (pid, next_version, confirmed, row['document'], row['created'], time.time()))
            db.execute('INSERT INTO revisions VALUES (?,?,?)', (pid, next_version, row['document']))
            # Invalidate settings writes from pre-deletion tabs, including version=0 defaults.
            from .models import ProductionSettings
            settings = db.execute('SELECT * FROM production_settings WHERE project_id=?', (pid,)).fetchone()
            config = json.loads(settings['config']) if settings else ProductionSettings().model_dump()
            settings_version = settings['version'] + 1 if settings else 1
            config['version'] = settings_version
            db.execute('INSERT INTO production_settings VALUES (?,?,?) ON CONFLICT(project_id) DO UPDATE SET '
                       'version=excluded.version,config=excluded.config', (pid, settings_version, json.dumps(config)))
            db.execute('DELETE FROM project_trash WHERE id=?', (pid,))
        return self.project(pid)

    def project_jobs(self, pid):
        with self.connect() as db:
            return [self.job_row(r) for r in db.execute(
                'SELECT * FROM jobs WHERE project_id=? ORDER BY created DESC,id DESC LIMIT 100', (pid,))]

    def project_job_history(self, pid, before=None, limit=50):
        with self.connect() as db:
            self.project_row(db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone())
            params = [pid]
            cursor = ''
            if before:
                row = db.execute('SELECT created,id FROM jobs WHERE project_id=? AND id=?', (pid, before)).fetchone()
                if row is None:
                    raise Missing('任务分页位置不存在或不属于当前项目')
                cursor = ' AND (created<? OR (created=? AND id<?))'
                params.extend([row['created'], row['created'], row['id']])
            rows = db.execute('SELECT * FROM jobs WHERE project_id=?' + cursor +
                              ' ORDER BY created DESC,id DESC LIMIT ?', (*params, limit + 1)).fetchall()
            items = [self.job_row(row) for row in rows[:limit]]
            return {'items': items, 'next_cursor': items[-1]['id'] if len(rows) > limit else None}

    def event_cutoff(self, jid):
        self.job(jid)
        with self.connect() as db:
            return db.execute('SELECT COALESCE(MAX(id),0) FROM events WHERE job_id=?', (jid,)).fetchone()[0]

    def export_events(self, jid, cutoff):
        # Fixed cutoff: running jobs cannot turn a download into an endless stream.
        # Close each transaction before yielding; do not pin the SQLite WAL during download.
        from datetime import datetime, timezone
        after = 0
        while True:
            with self.connect() as db:
                rows = db.execute('SELECT id,created,message FROM events WHERE job_id=? AND id>? AND id<=? ORDER BY id LIMIT 200',
                                  (jid, after, cutoff)).fetchall()
            if not rows:
                return
            yield ''.join(datetime.fromtimestamp(row['created'], timezone.utc).isoformat() + ' ' + row['message'] + '\n' for row in rows)
            after = rows[-1]['id']

    def recent_events(self, jid):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                'SELECT * FROM (SELECT * FROM events WHERE job_id=? ORDER BY id DESC LIMIT 200) ORDER BY id', (jid,))]

    def production_settings(self, pid):
        from .models import ProductionSettings
        self.project(pid)
        with self.connect() as db:
            row = db.execute('SELECT * FROM production_settings WHERE project_id=?', (pid,)).fetchone()
            return {**json.loads(row['config']), 'version': row['version']} if row else ProductionSettings().model_dump()

    def save_production_settings(self, pid, settings):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.project_row(db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone())
            row = db.execute('SELECT version FROM production_settings WHERE project_id=?', (pid,)).fetchone()
            current = row['version'] if row else 0
            if current != settings['version']:
                raise Conflict('制作设置已在其他页面修改，请重新打开项目后选择')
            result = {**settings, 'version': current + 1}
            db.execute('INSERT INTO production_settings VALUES (?,?,?) ON CONFLICT(project_id) DO UPDATE SET '
                       'version=excluded.version,config=excluded.config',
                       (pid, current + 1, json.dumps(result)))
        return result

    def create(self, document):
        pid, now = uuid.uuid4().hex, time.time()
        encoded = json.dumps(document, ensure_ascii=False)
        with self.connect() as db:
            from .assets import validate_references
            validate_references(db, document)
            db.execute('INSERT INTO projects VALUES (?,1,NULL,?,?,?)', (pid, encoded, now, now))
            db.execute('INSERT INTO revisions VALUES (?,1,?)', (pid, encoded))
        return self.project(pid)

    def edit(self, pid, version, document):
        encoded = json.dumps(document, ensure_ascii=False)
        with self.connect() as db:
            from .assets import validate_references
            validate_references(db, document)
            if db.execute('UPDATE projects SET document=?,version=version+1,confirmed=NULL,updated=? '
                          'WHERE id=? AND version=?', (encoded, time.time(), pid, version)).rowcount != 1:
                raise Conflict('项目已在其他页面修改，请刷新后重试')
            db.execute('INSERT INTO revisions VALUES (?,?,?)', (pid, version + 1, encoded))
        return self.project(pid)

    def confirm(self, pid, version):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
            project = self.project_row(row)
            if project['version'] != version:
                raise Conflict('分镜版本已变化，请刷新')
            if not project['scenes']:
                raise Conflict('请先添加分镜')
            db.execute('UPDATE projects SET confirmed=? WHERE id=?', (version, pid))
        return self.project(pid)

    def enqueue(self, pid, version, kind, options, runtime_id, idempotency):
        import hashlib
        request_hash = hashlib.sha256(json.dumps([pid, version, kind, options], sort_keys=True).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM jobs WHERE idempotency=?', (idempotency,)).fetchone()
            if existing:
                if existing['request_hash'] != request_hash:
                    raise Conflict('幂等键已用于不同请求')
                return self.job_row(existing)
            row = db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
            project = self.project_row(row)
            if project['version'] != version:
                raise Conflict('项目已变化，请刷新后提交')
            if kind == 'render' and options.get('audio') == 'uploaded' and any(
                    not scene.get('audio_id') for scene in project['scenes']):
                raise Conflict('上传配音模式需要为每一页选择 WAV 素材')
            if kind == 'render' and not project['confirmed']:
                raise Conflict('必须先确认当前版本分镜')
            if db.execute("SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','running')", (pid,)).fetchone():
                raise Conflict('本项目已有待处理任务')
            from .operations import ensure_capacity, CapacityError
            ensure_capacity(self.root)
            if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= int(os.environ.get('MAX_PENDING_JOBS', '20')):
                raise CapacityError('任务队列已满，请等待已有任务完成')
            jobid, now = uuid.uuid4().hex, time.time()
            db.execute('INSERT INTO jobs (id,project_id,kind,status,snapshot,runtime_id,idempotency,request_hash,created,updated) '
                       'VALUES (?,?,?,?,?,?,?,?,?,?)', (jobid, pid, kind, 'queued',
                       json.dumps({'project': project, 'options': options}, ensure_ascii=False),
                       runtime_id, idempotency, request_hash, now, now))
        return self.job(jobid)

    @staticmethod
    def job_row(row):
        if row is None:
            raise Missing('任务不存在')
        result = dict(row)
        result['snapshot'] = json.loads(result['snapshot'])
        result['result'] = json.loads(result['result']) if result['result'] else None
        return result

    def jobs(self):
        with self.connect() as db:
            return [self.job_row(r) for r in db.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 200')]

    def job(self, jid):
        with self.connect() as db:
            return self.job_row(db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone())

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (time.time(), row['id']))
            return self.job_row({**dict(row), 'status': 'running'})

    def finish(self, jid, status, result=None, error=None):
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?, result=?,error=?,updated=? WHERE id=?',
                       (status, json.dumps(result, ensure_ascii=False) if result else None, error, time.time(), jid))

    def complete_generated(self, jid, result):
        """Commit generated result and version-checked application atomically.

        Old tasks without auto_apply retain their original manual semantics.
        """
        from .review import result_document, review_document, media_revision_compatible
        from .assets import validate_references
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            job = self.job_row(db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone())
            if job['status'] != 'running':
                return
            if job['cancel_requested']:
                db.execute("UPDATE jobs SET status='cancelled',updated=? WHERE id=?", (time.time(), jid))
                return
            document = result_document(job, result)
            result = {**result, 'review': review_document(document, job['kind'])}
            if job['snapshot']['options'].get('auto_apply'):
                row = db.execute('SELECT * FROM projects WHERE id=?', (job['project_id'],)).fetchone()
                expected = job['snapshot']['project']['version']
                if row is not None and row['version'] > expected and job['kind'] in ('image', 'speech'):
                    source = {key: job['snapshot']['project'][key] for key in ('title', 'topic', 'style', 'scenes')}
                    index = job['snapshot']['options']['scene_index']
                    field = 'image_id' if job['kind'] == 'image' else 'audio_id'
                    revisions = db.execute('SELECT version,document FROM revisions WHERE project_id=? AND version>? AND version<=? ORDER BY version',
                                           (job['project_id'], expected, row['version'])).fetchall()
                    # Check every intervening revision, not just the final state (ABA protection).
                    if (len(revisions) == row['version'] - expected
                            and all(media_revision_compatible(source, json.loads(r['document']), index, field) for r in revisions)):
                        document = json.loads(row['document'])
                        document['scenes'][index][field] = result['asset']['id']
                        expected = row['version']
                if row is None or row['version'] != expected:
                    result['application'] = {'status': 'conflict', 'message': '项目已变化，生成结果已保留，未覆盖新版本。'}
                else:
                    validate_references(db, document)
                    encoded = json.dumps(document, ensure_ascii=False)
                    # Media bindings do not alter the previously confirmed storyboard.
                    confirmed = expected + 1 if job['kind'] in ('image', 'speech') and row['confirmed'] == expected else None
                    db.execute('UPDATE projects SET document=?,version=version+1,confirmed=?,updated=? WHERE id=?',
                               (encoded, confirmed, time.time(), job['project_id']))
                    db.execute('INSERT INTO revisions VALUES (?,?,?)', (job['project_id'], expected + 1, encoded))
                    result['application'] = {'status': 'applied', 'version': expected + 1,
                                             'message': ('媒体已自动应用，保留分镜确认状态；可在历史版本恢复。' if confirmed
                                                         else '结果已自动应用为新草稿版本；可在历史版本恢复。')}
            db.execute("UPDATE jobs SET status='succeeded',result=?,error=NULL,updated=? WHERE id=?",
                       (json.dumps(result, ensure_ascii=False), time.time(), jid))
            if result.get('application'):
                db.execute('INSERT INTO events(job_id,created,message) VALUES (?,?,?)',
                           (jid, time.time(), result['application']['message']))

    def cancel(self, jid):
        self.job(jid)
        with self.connect() as db:
            db.execute("UPDATE jobs SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END "
                       "WHERE id=? AND status IN ('queued','running')", (jid,))
        return self.job(jid)

    def recover(self):
        # Single-worker OS lock guarantees the previous worker is no longer alive.
        # Never replay a possibly charged remote request automatically.
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='interrupted',error='Worker 意外退出；请检查供应商账单后显式重试',updated=? "
                       "WHERE status='running'", (time.time(),))

    def event(self, jid, message):
        with self.connect() as db:
            db.execute('INSERT INTO events(job_id,created,message) VALUES (?,?,?)', (jid, time.time(), message[:2000]))

    def events(self, jid, after=0):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id LIMIT 200', (jid, after))]

    def provider_rows(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM providers ORDER BY updated DESC')]

    def provider(self, pid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM providers WHERE id=?', (pid,)).fetchone()
            if row is None:
                raise Missing('服务配置不存在')
            return dict(row)

    def save_provider(self, pid, config, secret):
        with self.connect() as db:
            db.execute('INSERT INTO providers VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                       'config=excluded.config,secret=excluded.secret,updated=excluded.updated',
                       (pid, json.dumps(config, ensure_ascii=False), secret, time.time()))

    def revisions(self, pid):
        self.project(pid)
        with self.connect() as db:
            return [{'version': row['version'], 'document': json.loads(row['document'])}
                    for row in db.execute('SELECT * FROM revisions WHERE project_id=? ORDER BY version DESC', (pid,))]
