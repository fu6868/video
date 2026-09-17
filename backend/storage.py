"""SQLite repository with explicit migrations and transactional helpers."""
from __future__ import annotations
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('VIDOE_DATA', ROOT / 'data'))
TABLES = {'sources','scans','media','batches','jobs','artifacts','exports'}
SCHEMA_VERSION = 2
FILTER_COLUMNS = {('jobs','batch_id'),('jobs','media_id'),('artifacts','job_id')}


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DATA / 'app.sqlite3', timeout=30)
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA busy_timeout=30000')
    return c


def _migrate(c: sqlite3.Connection):
    current = int(c.execute('PRAGMA user_version').fetchone()[0])
    if current > SCHEMA_VERSION:
        raise RuntimeError(f'数据库版本 {current} 高于当前程序支持的 {SCHEMA_VERSION}')
    if current < 1:
        for name in ('sources','scans','media','batches','exports'):
            c.execute(f'CREATE TABLE IF NOT EXISTS {name} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL, batch_id TEXT REFERENCES batches(id), media_id TEXT REFERENCES media(id))')
        c.execute('CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, payload TEXT NOT NULL, job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE)')
        c.execute('CREATE INDEX IF NOT EXISTS jobs_batch ON jobs(batch_id)')
        c.execute('PRAGMA user_version=1')
        current = 1
    if current < 2:
        c.execute('CREATE INDEX IF NOT EXISTS jobs_media ON jobs(media_id)')
        c.execute('CREATE INDEX IF NOT EXISTS artifacts_job ON artifacts(job_id)')
        c.execute('PRAGMA user_version=2')


def init():
    for folder in ('artifacts','exports','temp','logs'):
        (DATA / folder).mkdir(parents=True, exist_ok=True)
    with connect() as c:
        _migrate(c)


def schema_version():
    with connect() as c:
        return int(c.execute('PRAGMA user_version').fetchone()[0])


def all_rows(table):
    assert table in TABLES
    with connect() as c:
        return [json.loads(r[0]) for r in c.execute(f'SELECT payload FROM {table} ORDER BY rowid')]


def rows_by(table, column, value):
    if (table, column) not in FILTER_COLUMNS:
        raise ValueError('不允许的查询列')
    with connect() as c:
        return [json.loads(r[0]) for r in c.execute(f'SELECT payload FROM {table} WHERE {column}=? ORDER BY rowid', (value,))]


def get_many(table, ids):
    assert table in TABLES
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    found = {}
    with connect() as c:
        for start in range(0, len(ids), 800):
            chunk = ids[start:start+800]
            q = ','.join('?' for _ in chunk)
            for row_id, payload in c.execute(f'SELECT id,payload FROM {table} WHERE id IN ({q})', chunk):
                found[row_id] = json.loads(payload)
    return [found[i] for i in ids if i in found]


def get(table, id):
    assert table in TABLES
    with connect() as c:
        r = c.execute(f'SELECT payload FROM {table} WHERE id=?', (id,)).fetchone()
    if not r:
        raise KeyError(f'{table}: 未找到记录 {id}')
    return json.loads(r[0])


def put(table, value):
    assert table in TABLES
    value = dict(value)
    value.setdefault('id', uuid.uuid4().hex)
    value.setdefault('created_at', time.time())
    cols = ['id','payload']
    vals = [value['id'], json.dumps(value, ensure_ascii=False)]
    for key in {'jobs':('batch_id','media_id'),'artifacts':('job_id',)}.get(table,()):
        cols.append(key)
        vals.append(value[key])
    with connect() as c:
        c.execute(
            f'INSERT INTO {table} ({",".join(cols)}) VALUES ({",".join("?" for _ in vals)}) '
            f'ON CONFLICT(id) DO UPDATE SET ' + ','.join(f'{k}=excluded.{k}' for k in cols[1:]),
            vals,
        )
    return value


def update(table, id, **values):
    assert table in TABLES
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        r = c.execute(f'SELECT payload FROM {table} WHERE id=?', (id,)).fetchone()
        if not r:
            raise KeyError(id)
        obj = json.loads(r[0])
        obj.update(values)
        c.execute(f'UPDATE {table} SET payload=? WHERE id=?', (json.dumps(obj, ensure_ascii=False), id))
    return obj


def delete(table, id):
    assert table in TABLES
    with connect() as c:
        c.execute(f'DELETE FROM {table} WHERE id=?', (id,))


def claim_status(table, id, expected, **values):
    """Atomically transition a status-bearing row; return None if another caller won."""
    assert table in TABLES
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        r = c.execute(f'SELECT payload FROM {table} WHERE id=?', (id,)).fetchone()
        if not r:
            raise KeyError(id)
        obj = json.loads(r[0])
        if obj.get('status') != expected:
            return None
        obj.update(values)
        c.execute(f'UPDATE {table} SET payload=? WHERE id=?', (json.dumps(obj, ensure_ascii=False), id))
    return obj


def create_batch(media_ids, settings):
    """Create a batch and all jobs in one SQLite transaction."""
    now = time.time()
    batch = {'id':uuid.uuid4().hex,'created_at':now,'settings':dict(settings),'status':'running'}
    jobs = [
        {'id':uuid.uuid4().hex,'created_at':now,'media_id':mid,'batch_id':batch['id'],'status':'queued','processed':0,'attempts':0,'available':[]}
        for mid in media_ids
    ]
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('INSERT INTO batches (id,payload) VALUES (?,?)', (batch['id'], json.dumps(batch, ensure_ascii=False)))
        for job in jobs:
            c.execute('INSERT INTO jobs (id,payload,batch_id,media_id) VALUES (?,?,?,?)', (job['id'], json.dumps(job, ensure_ascii=False), job['batch_id'], job['media_id']))
    return batch


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with tmp.open('w', encoding='utf-8', newline='\n') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
