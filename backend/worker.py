"""Single persistent transcription worker with parent monitoring and process lock."""
from __future__ import annotations
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from . import storage as db
from .filesystem import validate_media,existing
from .texts import parse_srt,srt_text,paragraphs,cues_from_words
from .inference import Engine

ACTIVE={'preparing','transcribing','finalizing'}
SUCCESS={'completed','reused'}
PARENT_PID=int(os.environ.get('VIDOE_PARENT_PID','0') or 0)
_LOCK_HANDLE=None


class ParentGone(RuntimeError):
    pass


def parent_alive(pid=PARENT_PID):
    if not pid:
        return True
    if os.name=='nt':
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION=0x1000
        handle=ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,False,pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid,0)
        return True
    except OSError:
        return False


def acquire_worker_lock():
    """Acquire one cross-process worker lock for this data directory."""
    global _LOCK_HANDLE
    path=db.DATA/'worker.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    f=open(path,'a+b')
    if f.seek(0,os.SEEK_END)==0:
        f.write(b'0');f.flush()
    f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _LOCK_HANDLE=f
    return True


def release_worker_lock():
    global _LOCK_HANDLE
    f=_LOCK_HANDLE
    _LOCK_HANDLE=None
    if not f:
        return
    try:
        f.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_UN)
    except OSError:
        pass
    f.close()


def ensure_parent():
    if not parent_alive():
        raise ParentGone('父服务已退出，工作进程停止')


def update_environment(engine,model):
    path=db.DATA/'environment.json'
    try:
        current=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except Exception:
        current={}
    current.update({'device':engine.device,'fallback':engine.fallback,'last_model':model,'verified_at':time.time()})
    db.atomic_text(path,json.dumps(current,ensure_ascii=False,indent=2))


def artifact(job,kind,text,origin):
    path=db.DATA/'artifacts'/job['id']/('result.'+kind)
    db.atomic_text(path,text)
    return db.put('artifacts',{
        'id':job['id']+'-'+kind,'job_id':job['id'],'kind':kind,'path':str(path),
        'size':path.stat().st_size,'sha256':hashlib.sha256(text.encode()).hexdigest(),'origin':origin,
    })


def execute(job,engine):
    ensure_parent()
    m=db.get('media',job['media_id'])
    batch=db.get('batches',job['batch_id'])
    settings=batch['settings']
    error=validate_media(m)
    if error:
        raise ValueError(error)
    job=db.update('jobs',job['id'],status='preparing',error=None,started_at=time.time(),attempts=job.get('attempts',0)+1,processed=0)
    state=existing(Path(m['path']))
    results={}
    origins={}
    for kind in settings['formats']:
        if state[kind]['valid']:
            results[kind]=Path(m['path']).with_suffix('.'+kind).read_text(encoding='utf-8-sig')
            origins[kind]='已有同名文件'
    if 'txt' in settings['formats'] and 'txt' not in results and state['srt']['valid']:
        segments=parse_srt(Path(m['path']).with_suffix('.srt').read_text(encoding='utf-8-sig'))
        results['txt']=paragraphs(segments)
        origins['txt']='由已有字幕生成'
    reused=all(k in results for k in settings['formats'])
    if not reused:
        db.update('jobs',job['id'],stage='正在加载本地 '+settings['model']+' 模型')
        engine.load(settings['model'])
        update_environment(engine,settings['model'])
        ensure_parent()
        db.update('jobs',job['id'],status='transcribing',stage='正在识别语音',device=engine.device,fallback=engine.fallback)
        def progress(seconds,lang):
            ensure_parent()
            db.update('jobs',job['id'],processed=seconds,language=lang)
        def checkpoint(words):
            ensure_parent()
            db.atomic_text(db.DATA/'artifacts'/job['id']/'checkpoint.json',json.dumps(words,ensure_ascii=False))
        try:
            words,language,end=engine.transcribe(m['path'],settings['language'] or None,progress,checkpoint)
        except ParentGone:
            raise
        except Exception as e:
            if not engine.device.startswith('cuda'):
                raise
            reason=str(e)[:500]
            engine.load(settings['model'],'cpu')
            engine.fallback=reason
            update_environment(engine,settings['model'])
            db.update('jobs',job['id'],processed=0,device=engine.device,fallback=reason,stage='GPU 推理失败，使用相同模型从头 CPU 重试')
            words,language,end=engine.transcribe(m['path'],settings['language'] or None,progress,checkpoint)
        error=validate_media(m)
        if error:
            raise ValueError(error)
        segments=cues_from_words(words)
        if not segments:
            for k,text in results.items():
                artifact(job,k,text,origins[k])
            db.update('jobs',job['id'],status='no_speech',stage='未检测到语音',processed=end,available=list(results),finished_at=time.time())
            return
        for k in settings['formats']:
            if k not in results:
                results[k]=srt_text(segments) if k=='srt' else paragraphs(segments)
                origins[k]='本地模型转写'
    db.update('jobs',job['id'],status='finalizing',stage='正在保存内部结果')
    for k,text in results.items():
        artifact(job,k,text,origins[k])
    db.update(
        'jobs',job['id'],status='reused' if reused else 'completed',
        stage='已复用结果' if reused else '已转写 · 尚未分发',available=list(results),finished_at=time.time(),
        processed=m['duration'] or db.get('jobs',job['id']).get('processed',0),
    )


def reconcile_batches():
    jobs=db.all_rows('jobs')
    for b in db.all_rows('batches'):
        members=[j for j in jobs if j['batch_id']==b['id']]
        if not members:
            continue
        active=any(j['status'] in ACTIVE for j in members)
        queued=any(j['status']=='queued' for j in members)
        if b['status']=='pausing' and not active:
            db.update('batches',b['id'],status='paused')
        elif b['status']=='running' and not active and not queued:
            db.update('batches',b['id'],status='completed')


def loop():
    db.init()
    if not acquire_worker_lock():
        print('另一个转写 worker 已经持有单实例锁。',file=sys.stderr,flush=True)
        return 73
    engine=Engine()
    try:
        while True:
            ensure_parent()
            try:
                reconcile_batches()
                runnable={b['id'] for b in db.all_rows('batches') if b['status']=='running'}
                jobs=db.all_rows('jobs')
                candidate=next((j for j in jobs if j['status']=='queued' and j['batch_id'] in runnable),None)
                if not candidate:
                    time.sleep(.5)
                    continue
                job=db.claim_status('jobs',candidate['id'],'queued',status='preparing')
                if not job:
                    continue
                try:
                    execute(job,engine)
                except ParentGone as e:
                    db.update('jobs',job['id'],status='interrupted',error=str(e),stage='服务已退出')
                    return 0
                except Exception as e:
                    db.update('jobs',job['id'],status='failed',error=str(e)[:1000],stage='处理失败',finished_at=time.time())
                    with (db.DATA/'logs'/'worker.log').open('a',encoding='utf-8') as log:
                        log.write(time.strftime('%F %T')+' '+job['id']+' '+type(e).__name__+'\n')
            except ParentGone:
                return 0
            except Exception as e:
                with (db.DATA/'logs'/'worker-loop.log').open('a',encoding='utf-8') as log:
                    log.write(time.strftime('%F %T')+' '+type(e).__name__+' '+str(e)[:300]+'\n')
                time.sleep(1)
    finally:
        release_worker_lock()


if __name__=='__main__':
    raise SystemExit(loop())
