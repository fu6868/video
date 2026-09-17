from __future__ import annotations
import os
import stat
import threading
import time
import uuid
from pathlib import Path
from . import storage as db
from .texts import parse_srt

EXTENSIONS={'.mp4','.mkv','.mov','.avi','.webm','.m4v','.wmv','.flv','.mpeg','.mpg','.ts','.mts','.m2ts'}


def key(path):
    return os.path.normcase(os.path.abspath(path))


def fingerprint(path):
    s=Path(path).stat()
    return {'size':s.st_size,'mtime_ns':s.st_mtime_ns}


def is_link(path):
    p=Path(path)
    return p.is_symlink() or bool(getattr(p.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024))


def checked_path(raw):
    p=Path(raw)
    if not p.is_absolute():
        raise ValueError('请输入本机绝对路径')
    if not p.exists():
        raise ValueError('路径不存在或无法访问')
    p=Path(os.path.abspath(p))
    # Preserve lexical filename; never normalize Unicode or letter case for outputs.
    parents=[p,*list(p.parents)[:-1]]
    try:
        if any(is_link(x) for x in parents):
            raise ValueError('第一版不跟随符号链接或目录联接')
    except OSError as e:
        raise ValueError('路径无法安全检查：'+str(e)) from e
    return p


def validate_media(m):
    try:
        p=checked_path(m['path'])
        if fingerprint(p)!=m['fingerprint']:
            return '源视频已被替换或修改，请重新扫描'
        return None
    except (OSError,ValueError):
        return '源视频已移动、删除或不可访问'


def existing(path):
    result={}
    for kind in ('srt','txt'):
        p=path.with_suffix('.'+kind)
        if not p.exists():
            result[kind]={'exists':False,'valid':False}
            continue
        try:
            if p.stat().st_size>20*1024*1024:
                raise ValueError('文本超过 20 MB 读取限制')
            text=p.read_text(encoding='utf-8-sig')
            if not text.strip():
                raise ValueError('文件为空')
            if kind=='srt':
                parse_srt(text)
            result[kind]={'exists':True,'valid':True}
        except Exception as e:
            result[kind]={'exists':True,'valid':False,'error':str(e)}
    return result


def metadata(path,root,source_id):
    import av
    error=None
    duration=None
    audio=False
    try:
        with av.open(str(path)) as c:
            audio=bool(c.streams.audio)
            duration=float(c.duration/av.time_base) if c.duration and c.duration>0 else None
            if not audio:
                error='没有可读取的音轨'
    except Exception as e:
        error='无法读取媒体：'+str(e)[:250]
    return {
        'id':uuid.uuid4().hex,'path':str(path),'name':path.name,'parent':str(path.parent),
        'root':str(root),'source_id':source_id,'fingerprint':fingerprint(path),
        'duration':duration,'audio':audio,'error':error,'existing':existing(path),
    }


def register(paths):
    if not paths or len(paths)>200:
        raise ValueError('请选择 1 至 200 个来源')
    known={s['canonical']:s for s in db.all_rows('sources')}
    out=[]
    valid=[checked_path(p) for p in paths]
    for p in valid:
        if p.is_file() and p.suffix.lower() not in EXTENSIONS:
            raise ValueError('不支持的视频扩展名：'+p.name)
    for p in valid:
        k=key(p)
        if k not in known:
            known[k]=db.put('sources',{'path':str(p),'canonical':k,'kind':'directory' if p.is_dir() else 'video','order':len(known)})
        if known[k] not in out:
            out.append(known[k])
    return out


def scan(source_ids):
    sources=[db.get('sources',i) for i in dict.fromkeys(source_ids)]
    if not sources:
        raise ValueError('没有已登记来源')
    sources.sort(key=lambda s:s['order'])
    obj=db.put('scans',{'source_ids':[s['id'] for s in sources],'status':'running','found':0,'errors':[],'current_directory':'','media_ids':[]})
    threading.Thread(target=_scan,args=(obj['id'],sources),daemon=True,name=f'vidoe-scan-{obj["id"][:8]}').start()
    return obj


def _scan(id,sources):
    seen=set()
    ids=[]
    errors=[]
    last_publish=0.0
    last_stop_check=0.0
    cached_stopped=False

    def stopped(force=False):
        nonlocal last_stop_check,cached_stopped
        now=time.monotonic()
        if force or now-last_stop_check>=0.2:
            cached_stopped=db.get('scans',id)['status']=='cancelled'
            last_stop_check=now
        return cached_stopped

    def publish(force=False,**more):
        nonlocal last_publish
        now=time.monotonic()
        if not force and not more and now-last_publish<0.25:
            return
        db.update('scans',id,found=len(ids),media_ids=list(ids),errors=list(errors),**more)
        last_publish=now

    def accept(p,root,s):
        if stopped() or key(p) in seen or p.suffix.lower() not in EXTENSIONS:
            return
        try:
            if is_link(p):
                return
        except OSError as e:
            errors.append({'path':str(p),'error':str(e)})
            publish()
            return
        seen.add(key(p))
        try:
            m=db.put('media',metadata(p,root,s['id']))
            ids.append(m['id'])
            publish()
        except Exception as e:
            errors.append({'path':str(p),'error':str(e)[:500]})
            publish()

    try:
        for s in sources:
            if stopped(True):
                return
            p=checked_path(s['path'])
            root=p if p.is_dir() else p.parent
            if p.is_file():
                accept(p,root,s)
                continue
            def onerror(e):
                errors.append({'path':e.filename or '','error':str(e)[:500]})
                publish()
            for directory,dirs,files in os.walk(p,followlinks=False,onerror=onerror):
                if stopped():
                    return
                publish(force=True,current_directory=directory)
                allowed=[]
                for d in dirs:
                    candidate=Path(directory)/d
                    try:
                        if not is_link(candidate):
                            allowed.append(d)
                    except OSError as e:
                        errors.append({'path':str(candidate),'error':str(e)[:500]})
                dirs[:]=allowed
                for name in files:
                    accept(Path(directory)/name,root,s)
        if not stopped(True):
            publish(force=True,status='completed',current_directory='')
    except Exception as e:
        errors.append({'path':'','error':str(e)[:500]})
        publish(force=True,status='failed',current_directory='')
