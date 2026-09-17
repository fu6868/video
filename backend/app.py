from __future__ import annotations
import asyncio
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal
from . import storage as db, filesystem as fs, exports
from .inference import model_path

TOKEN=secrets.token_urlsafe(32)
WORKER=None
WORKER_LOG=None
SUPERVISOR=None
SHUTTING_DOWN=False
WORKER_LAST_EXIT=None


def _rotate_log(path:Path,max_bytes=5*1024*1024):
    if path.exists() and path.stat().st_size>max_bytes:
        old=path.with_suffix(path.suffix+'.1')
        old.unlink(missing_ok=True)
        path.replace(old)


def _spawn_worker():
    global WORKER,WORKER_LOG,WORKER_LAST_EXIT
    log_path=db.DATA/'logs'/'worker-process.log'
    _rotate_log(log_path)
    if WORKER_LOG:
        with suppress(Exception):WORKER_LOG.close()
    WORKER_LOG=log_path.open('a',encoding='utf-8',buffering=1)
    env=os.environ.copy();env['VIDOE_PARENT_PID']=str(os.getpid())
    WORKER=subprocess.Popen(
        [sys.executable,'-m','backend.worker'],cwd=db.ROOT,stdout=WORKER_LOG,stderr=WORKER_LOG,env=env,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
    )
    WORKER_LAST_EXIT=None
    return WORKER


def _terminate_tree(proc):
    if not proc or proc.poll() is not None:
        return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    else:
        proc.terminate()
        try:proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait()


def _interrupt_active(reason):
    active_ids=[]
    for j in db.all_rows('jobs'):
        if j.get('status') in ('preparing','transcribing','finalizing'):
            db.update('jobs',j['id'],status='interrupted',error=reason,stage='工作进程中断')
            active_ids.append(j['batch_id'])
    for batch_id in set(active_ids):
        with suppress(KeyError):db.update('batches',batch_id,status='interrupted')


async def _supervise_worker():
    global WORKER,WORKER_LAST_EXIT
    while not SHUTTING_DOWN:
        await asyncio.sleep(1.5)
        if SHUTTING_DOWN or os.environ.get('VIDOE_NO_WORKER')=='1':
            continue
        if WORKER is None:
            _spawn_worker();continue
        code=WORKER.poll()
        if code is None:
            continue
        WORKER_LAST_EXIT=code
        if code!=73:
            _interrupt_active(f'工作进程异常退出（代码 {code}），任务已中断，可点击继续重试')
        await asyncio.sleep(1.5 if code!=73 else 4)
        if not SHUTTING_DOWN:
            _spawn_worker()


@asynccontextmanager
async def lifespan(app):
    global SUPERVISOR,SHUTTING_DOWN,WORKER,WORKER_LOG
    SHUTTING_DOWN=False
    db.init()
    # Restart semantics: only in-flight jobs are interrupted; untouched queue entries remain queued.
    for j in db.all_rows('jobs'):
        if j.get('status') in ('preparing','transcribing','finalizing'):
            db.update('jobs',j['id'],status='interrupted',error='本地服务已重启，请选择继续或重试',stage='服务重启中断')
    for b in db.all_rows('batches'):
        if b.get('status') in ('running','pausing'):
            db.update('batches',b['id'],status='interrupted')
    for s in db.all_rows('scans'):
        if s.get('status')=='running':
            db.update('scans',s['id'],status='cancelled',current_directory='')
    for e in db.all_rows('exports'):
        if e.get('status') in ('queued','running'):
            db.update('exports',e['id'],status='failed',error='导出因服务重启中断；请重新预检查。已写入文件会保留并在下次跳过。')
    if os.environ.get('VIDOE_NO_WORKER')!='1':
        _spawn_worker()
        SUPERVISOR=asyncio.create_task(_supervise_worker(),name='vidoe-worker-supervisor')
    try:
        yield
    finally:
        SHUTTING_DOWN=True
        if SUPERVISOR:
            SUPERVISOR.cancel()
            with suppress(asyncio.CancelledError):await SUPERVISOR
            SUPERVISOR=None
        _terminate_tree(WORKER)
        WORKER=None
        if WORKER_LOG:
            with suppress(Exception):WORKER_LOG.close()
            WORKER_LOG=None


app=FastAPI(title='映言 · 本地视频转写工作台',lifespan=lifespan,docs_url=None,redoc_url=None)


@app.middleware('http')
async def local_boundary(request,call_next):
    raw_host=request.headers.get('host','')
    host=raw_host.rsplit(':',1)[0] if raw_host.count(':')==1 else raw_host
    if host not in ('127.0.0.1','localhost','testserver') or (host=='testserver' and os.environ.get('VIDOE_TEST')!='1'):
        return JSONResponse({'detail':'仅允许本机访问'},403)
    origin=request.headers.get('origin')
    if origin and (urlparse(origin).netloc!=raw_host or urlparse(origin).scheme not in ('http','https')):
        return JSONResponse({'detail':'跨域访问已拒绝'},403)
    if request.headers.get('sec-fetch-site')=='cross-site':
        return JSONResponse({'detail':'跨站访问已拒绝'},403)
    public_api={'/api/session','/api/system/status','/api/health'}
    if request.url.path.startswith('/api/') and request.url.path not in public_api:
        if not secrets.compare_digest(request.cookies.get('vidoe_session',''),TOKEN):
            return JSONResponse({'detail':'本地会话失效，请刷新页面'},401)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    return response


@app.exception_handler(ValueError)
async def bad_value(request,e):return JSONResponse({'detail':str(e)},400)
@app.exception_handler(KeyError)
async def missing(request,e):return JSONResponse({'detail':str(e)},404)
@app.exception_handler(OSError)
async def filesystem_error(request,e):return JSONResponse({'detail':'本地文件操作失败：'+str(e)},400)


@app.get('/api/session')
def session():
    r=JSONResponse({'ok':True})
    r.set_cookie('vidoe_session',TOKEN,httponly=True,samesite='strict',path='/')
    r.headers['Cache-Control']='no-store'
    return r


@app.get('/api/health')
def health():
    return {'ok':True,'app':'vidoe','schema':db.schema_version(),'worker_alive':WORKER is not None and WORKER.poll() is None}


@app.get('/api/system/status')
def status():
    models={}
    for name in ('small','medium'):
        try:models[name]={'available':True,'path':str(model_path(name))}
        except Exception as e:models[name]={'available':False,'error':str(e)}
    jobs=db.all_rows('jobs')
    current=next((j for j in jobs if j.get('status') in ('preparing','transcribing','finalizing')),None)
    latest=next((j for j in reversed(jobs) if j.get('device')),None)
    probe=db.DATA/'environment.json'
    try:environment=json.loads(probe.read_text(encoding='utf-8')) if probe.exists() else {}
    except Exception:environment={'error':'环境记录损坏，可重新运行 scripts/preflight.py --smoke'}
    return {
        'app':'vidoe','online':True,'schema':db.schema_version(),'models':models,
        'device':(current or {}).get('device') or (latest or {}).get('device') or environment.get('device','待首次推理验证'),
        'fallback':(current or latest or {}).get('fallback') or environment.get('fallback'),'current_job':current,
        'worker_alive':WORKER is not None and WORKER.poll() is None,'worker_pid':WORKER.pid if WORKER and WORKER.poll() is None else None,
        'worker_last_exit':WORKER_LAST_EXIT,'environment':environment,
    }


class Paths(BaseModel):paths:list[str]=Field(min_length=1,max_length=200)
class Directory(BaseModel):path:str='';offset:int=Field(0,ge=0);limit:int=Field(200,ge=1,le=500)
class ScanRequest(BaseModel):source_ids:list[str]=Field(min_length=1,max_length=200)
class Settings(BaseModel):
    formats:list[Literal['srt','txt']]=Field(min_length=1,max_length=2)
    model:Literal['small','medium']='medium'
    language:Literal['','zh','en','ja','ko','fr','de','es','ru']=''
class BatchRequest(BaseModel):media_ids:list[str]=Field(min_length=1,max_length=20000);settings:Settings
class Selection(BaseModel):job_ids:list[str]=[]
class ExportRequest(Selection):batch_id:str;artifact_kind:Literal['srt','txt'];mode:Literal['zip','distribute']
class ExportConfirm(BaseModel):preflight_id:str


@app.get('/api/fs/roots')
def roots():
    if os.name=='nt':paths=[f'{c}:\\' for c in string.ascii_uppercase if Path(f'{c}:\\').exists()]
    else:paths=[str(Path.home()),'/tmp']
    return {'roots':paths}


@app.post('/api/fs/list')
def directory(body:Directory):
    p=fs.checked_path(body.path)
    if not p.is_dir():raise ValueError('请选择文件夹进行浏览')
    items=[]
    with os.scandir(p) as entries:
        for entry in entries:
            try:
                if fs.is_link(Path(entry.path)):continue
                isdir=entry.is_dir(follow_symlinks=False)
                if isdir or Path(entry.name).suffix.lower() in fs.EXTENSIONS:
                    items.append({'name':entry.name,'path':entry.path,'kind':'directory' if isdir else 'video'})
            except OSError:continue
    items.sort(key=lambda x:(x['kind']!='directory',x['name'].casefold()))
    return {'path':str(p),'parent':str(p.parent) if p.parent!=p else None,'items':items[body.offset:body.offset+body.limit],'total':len(items)}


@app.post('/api/sources')
def sources(body:Paths):return {'sources':fs.register(body.paths)}
@app.post('/api/scans')
def scans(body:ScanRequest):return fs.scan(body.source_ids)
@app.get('/api/scans/{id}/items')
def scan_items(id:str,offset:int=0,limit:int=300):
    s=db.get('scans',id);limit=max(1,min(1000,limit));offset=max(0,offset)
    ids=s['media_ids'][offset:offset+limit]
    return {'scan':s,'items':db.get_many('media',ids),'total':len(s['media_ids'])}
@app.post('/api/scans/{id}/cancel')
def cancel_scan(id:str):
    s=db.get('scans',id)
    if s['status']!='running':return s
    return db.update('scans',id,status='cancelled',current_directory='')


def snapshot(id):
    b=db.get('batches',id)
    jobs=db.rows_by('jobs','batch_id',id)
    media_map={m['id']:m for m in db.get_many('media',[j['media_id'] for j in jobs])}
    enriched=[dict(j,media=media_map.get(j['media_id'])) for j in jobs]
    return dict(b,jobs=enriched,exports=[e for e in db.all_rows('exports') if e.get('batch_id')==id and e.get('status')!='preflight'])


@app.post('/api/batches')
def create_batch(body:BatchRequest):
    ids=list(dict.fromkeys(body.media_ids))
    medias=db.get_many('media',ids)
    if len(medias)!=len(ids):raise ValueError('选择中包含不存在的媒体记录，请重新扫描')
    problems=[m for m in medias if m.get('error') or fs.validate_media(m)]
    if problems:raise ValueError('部分视频已不可处理或源文件发生变化，请重新扫描')
    settings=body.settings.model_dump();settings['formats']=list(dict.fromkeys(settings['formats']))
    b=db.create_batch(ids,settings)
    return snapshot(b['id'])


@app.get('/api/batches')
def batches():
    jobs=db.all_rows('jobs');result=[]
    for b in reversed(db.all_rows('batches')):
        members=[j for j in jobs if j['batch_id']==b['id']]
        result.append(dict(b,total=len(members),success=sum(j['status'] in ('completed','reused') for j in members),failed=sum(j['status'] in ('failed','interrupted') for j in members)))
    return {'batches':result}
@app.get('/api/batches/{id}')
def batch(id:str):return snapshot(id)
@app.post('/api/batches/{id}/pause')
def pause(id:str):
    b=db.get('batches',id)
    if b['status']!='running':raise ValueError('只有进行中的批次可以请求暂停')
    return db.update('batches',id,status='pausing')
@app.post('/api/batches/{id}/resume')
def resume(id:str):
    b=db.get('batches',id)
    if b['status'] not in ('paused','interrupted','completed'):
        raise ValueError('当前批次状态不能继续')
    for j in db.rows_by('jobs','batch_id',id):
        if j['status']=='interrupted':db.update('jobs',j['id'],status='queued',error=None,stage='等待重试')
    return db.update('batches',id,status='running')
@app.post('/api/batches/{id}/retry')
def retry(id:str,body:Selection):
    members=db.rows_by('jobs','batch_id',id)
    member_ids={j['id'] for j in members}
    if body.job_ids and set(body.job_ids)-member_ids:raise ValueError('重试列表包含不属于此批次的任务')
    touched=False
    for j in members:
        if j['status'] in ('failed','interrupted','cancelled') and (not body.job_ids or j['id'] in body.job_ids):
            db.update('jobs',j['id'],status='queued',error=None,stage='等待重试',processed=0);touched=True
    if not touched:raise ValueError('没有可重试的任务')
    return db.update('batches',id,status='running')
@app.post('/api/batches/{id}/cancel')
def cancel(id:str):
    b=db.get('batches',id)
    members=db.rows_by('jobs','batch_id',id)
    for j in members:
        if j['status']=='queued':db.update('jobs',j['id'],status='cancelled',stage='已取消排队')
    active=any(j['status'] in ('preparing','transcribing','finalizing') for j in members)
    db.update('batches',id,status='pausing' if active else 'completed')
    return snapshot(id)


@app.delete('/api/batches/{id}')
def cleanup(id:str):
    b=db.get('batches',id)
    if b['status'] in ('running','pausing'):raise ValueError('请等待当前视频结束并暂停后再清理')
    if any(e.get('batch_id')==id and e.get('status') in ('running','queued') for e in db.all_rows('exports')):raise ValueError('请等待导出完成后再清理')
    for e in db.all_rows('exports'):
        if e.get('batch_id')==id:
            (db.DATA/'exports'/(e['id']+'.zip')).unlink(missing_ok=True);db.delete('exports',e['id'])
    for j in db.rows_by('jobs','batch_id',id):
        shutil.rmtree(db.DATA/'artifacts'/j['id'],ignore_errors=True);db.delete('jobs',j['id'])
    db.delete('batches',id);return {'ok':True}


def _safe_internal(path):
    p=Path(path).resolve();root=db.DATA.resolve()
    try:p.relative_to(root)
    except ValueError:raise ValueError('内部结果路径异常')
    return p


@app.get('/api/jobs/{id}/artifacts/{kind}')
def read_artifact(id:str,kind:Literal['srt','txt']):
    a=db.get('artifacts',id+'-'+kind);text=_safe_internal(a['path']).read_text(encoding='utf-8')
    from .texts import parse_srt
    return dict(a,text=text,segments=parse_srt(text) if kind=='srt' else [])
@app.post('/api/exports/preflight')
def preflight(body:ExportRequest):return exports.preflight(body.batch_id,body.job_ids,body.artifact_kind,body.mode)
@app.post('/api/exports')
def export(body:ExportConfirm):return exports.start(body.preflight_id)
@app.get('/api/exports/{id}')
def get_export(id:str):return db.get('exports',id)
@app.get('/api/exports/{id}/download')
def download(id:str):
    e=db.get('exports',id)
    if e['status'] not in ('completed','partial_failed') or e['mode']!='zip' or not e.get('download_path'):raise ValueError('ZIP 尚未准备好')
    path=_safe_internal(e['download_path'])
    if not path.is_file():raise ValueError('ZIP 文件已不存在')
    return FileResponse(path,filename=('字幕' if e['artifact_kind']=='srt' else '文字稿')+'.zip',media_type='application/zip')


def event_state(batch_id):
    b=db.get('batches',batch_id)
    jobs=db.rows_by('jobs','batch_id',batch_id)
    return {
        'batch_id':batch_id,'status':b['status'],'time':time.time(),
        'jobs':[{'id':j['id'],'status':j['status'],'stage':j.get('stage'),'processed':j.get('processed',0),'device':j.get('device'),'language':j.get('language'),'available':j.get('available',[]),'error':j.get('error')} for j in jobs],
    }


@app.get('/api/events')
async def events(request:Request,batch_id:str|None=None):
    if batch_id:db.get('batches',batch_id)
    async def stream():
        previous=None;heartbeat=0
        while not await request.is_disconnected():
            now=time.monotonic()
            if batch_id:
                state=event_state(batch_id)
                signature=json.dumps(state['jobs'],ensure_ascii=False,sort_keys=True)+state['status']
                if signature!=previous:
                    previous=signature
                    yield 'event: update\ndata: '+json.dumps(state,ensure_ascii=False)+'\n\n'
                    heartbeat=0
                else:heartbeat+=1
            else:heartbeat+=1
            if heartbeat>=10:
                yield 'event: heartbeat\ndata: '+json.dumps({'time':time.time()})+'\n\n';heartbeat=0
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})


FRONTEND=db.ROOT/'frontend'/'dist'
if FRONTEND.exists():app.mount('/',StaticFiles(directory=FRONTEND,html=True),name='frontend')
else:
    @app.get('/')
    def not_built():return JSONResponse({'detail':'前端尚未构建，请运行 setup.bat'},503)
