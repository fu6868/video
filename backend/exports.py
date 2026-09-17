import os, shutil, threading, uuid, zipfile
from pathlib import Path, PurePosixPath
from . import storage as db
from .filesystem import validate_media

def collect(batch_id,job_ids,kind,mode):
    db.get('batches',batch_id)
    if kind not in ('srt','txt') or mode not in ('zip','distribute'):raise ValueError('无效的导出类型')
    jobs=[j for j in db.all_rows('jobs') if j['batch_id']==batch_id and (not job_ids or j['id'] in job_ids)]
    if job_ids and set(job_ids)-{j['id'] for j in jobs}:raise ValueError('选择包含其他批次或无效任务')
    arts={a['job_id']:a for a in db.all_rows('artifacts') if a['kind']==kind}
    # Stable root aliases derived from entire batch, never from export selection.
    alljobs=[j for j in db.all_rows('jobs') if j['batch_id']==batch_id]
    roots=list(dict.fromkeys(db.get('media',j['media_id'])['root'] for j in alljobs))
    aliases={};used=set()
    for root in roots:
        base=Path(root).name or Path(root).drive.replace(':','') or 'Root';alias=base;i=2
        while alias.casefold() in used:alias=f'{base} ({i})';i+=1
        used.add(alias.casefold());aliases[root]=alias
    items=[]
    for j in jobs:
        m=db.get('media',j['media_id']);a=arts.get(j['id'])
        if not a:continue
        p=Path(m['path']);target=p.with_suffix('.'+kind)
        relative=p.relative_to(Path(m['root'])).with_suffix('.'+kind)
        entry=PurePosixPath(aliases[m['root']],*relative.parts).as_posix()
        if PurePosixPath(entry).is_absolute() or '..' in PurePosixPath(entry).parts:raise ValueError('不安全的 ZIP 条目')
        error=validate_media(m)
        status='error' if error else 'ready'
        if not error and mode=='distribute' and target.exists():status='exists';error='目标已存在，保留并跳过'
        items.append({'job_id':j['id'],'artifact_id':a['id'],'name':target.name,'target':str(target),'entry':entry,'status':status,'reason':error})
    seen={}
    for item in items:
        k=(item['entry'] if mode=='zip' else item['target']).casefold()
        seen.setdefault(k,[]).append(item)
    for group in seen.values():
        if len(group)>1:
            for item in group:item.update(status='conflict',reason='同名不同扩展名视频产出冲突，请仅选择其中一个')
    return items

def preflight(batch_id,job_ids,kind,mode):
    items=collect(batch_id,job_ids,kind,mode)
    return db.put('exports',{'batch_id':batch_id,'job_ids':job_ids,'artifact_kind':kind,'mode':mode,'status':'preflight','items':items,'processed':0,'total':len(items)})

def start(id):
    e=db.get('exports',id)
    if e['status']!='preflight':raise ValueError('此预检查已执行，请重新预检查')
    fresh=collect(e['batch_id'],e['job_ids'],e['artifact_kind'],e['mode'])
    if not fresh:raise ValueError('没有可导出的结果')
    if any(i['status']=='conflict' for i in fresh):raise ValueError('请先解决命名冲突：每组只勾选一个视频')
    claimed=db.claim_status('exports',id,'preflight',status='queued',items=fresh)
    if not claimed:raise ValueError('此预检查已由其他请求执行，请重新预检查')
    threading.Thread(target=execute,args=(id,),daemon=True).start()
    return claimed

def exclusive_write(source,target):
    """Same-volume temporary file + atomic no-replace publish, even after preflight races."""
    target=Path(target);temp=target.parent/('.vidoe-'+uuid.uuid4().hex+'.tmp')
    try:
        with open(source,'rb') as src,open(temp,'xb') as out:
            shutil.copyfileobj(src,out);out.flush();os.fsync(out.fileno())
        if os.name=='nt':os.rename(temp,target)  # Windows rename fails when destination exists.
        else:os.link(temp,target)
    finally:temp.unlink(missing_ok=True)

def execute(id):
    e=db.update('exports',id,status='running');items=e['items'];zip_path=db.DATA/'exports'/(id+'.zip');temp=zip_path.with_suffix('.tmp');archive=None
    try:
        if e['mode']=='zip':archive=zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED)
        for idx,item in enumerate(items):
            try:
                m=db.get('media',db.get('jobs',item['job_id'])['media_id']);err=validate_media(m)
                if err:raise ValueError(err)
                a=db.get('artifacts',item['artifact_id'])
                if e['mode']=='zip':archive.write(a['path'],item['entry']);item.update(status='completed',reason=None)
                elif Path(item['target']).exists():item.update(status='skipped',reason='目标已存在，未覆盖')
                else:
                    try:exclusive_write(a['path'],item['target']);item.update(status='completed',reason=None)
                    except FileExistsError:item.update(status='skipped',reason='目标在预检查后出现，未覆盖')
            except Exception as ex:item.update(status='failed',reason=str(ex)[:500])
            db.update('exports',id,items=items,processed=idx+1)
        if archive:archive.close();archive=None;os.replace(temp,zip_path)
        failures=sum(i['status']=='failed' for i in items)
        db.update('exports',id,status='failed' if failures==len(items) else 'partial_failed' if failures else 'completed',items=items,download_path=str(zip_path) if e['mode']=='zip' else None)
    except Exception as ex:db.update('exports',id,status='failed',error=str(ex)[:500])
    finally:
        if archive:archive.close()
        temp.unlink(missing_ok=True)
