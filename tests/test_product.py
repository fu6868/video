"""Product-level regression tests. All filesystem writes stay inside pytest tmp_path."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path
import pytest
from backend import storage as db
from backend import filesystem as fs
from backend import exports


def reset(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'data')
    db.init()


def test_schema_migration_and_get_many(tmp_path,monkeypatch):
    reset(tmp_path,monkeypatch)
    assert db.schema_version()==db.SCHEMA_VERSION==2
    rows=[db.put('media',{'path':f'p{i}'}) for i in range(4)]
    ids=[rows[3]['id'],rows[0]['id'],rows[2]['id']]
    assert [x['id'] for x in db.get_many('media',ids)]==ids
    with db.connect() as c:c.execute('PRAGMA user_version=1')
    db.init();assert db.schema_version()==2


def test_scan_dedup_parent_child_and_large_result(tmp_path,monkeypatch):
    reset(tmp_path,monkeypatch)
    root=tmp_path/'source';child=root/'nested';child.mkdir(parents=True)
    for i in range(1205):(child/f'课程.{i:04}.mp4').write_bytes(b'x')
    def fake_metadata(path,root_path,source_id):
        return {'id':fs.uuid.uuid4().hex,'path':str(path),'name':path.name,'parent':str(path.parent),'root':str(root_path),'source_id':source_id,'fingerprint':fs.fingerprint(path),'duration':1.0,'audio':True,'error':None,'existing':{'srt':{'exists':False,'valid':False},'txt':{'exists':False,'valid':False}}}
    monkeypatch.setattr(fs,'metadata',fake_metadata)
    sources=fs.register([str(root),str(child)])
    scan=db.put('scans',{'source_ids':[s['id'] for s in sources],'status':'running','found':0,'errors':[],'current_directory':'','media_ids':[]})
    fs._scan(scan['id'],sources)
    done=db.get('scans',scan['id'])
    assert done['status']=='completed' and done['found']==1205 and len(done['media_ids'])==1205
    assert len(db.get_many('media',done['media_ids'][1000:]))==205
    assert not list((tmp_path/'data').rglob('*.mp4'))


def test_restart_keeps_queue_and_interrupts_only_active(tmp_path,monkeypatch):
    reset(tmp_path,monkeypatch)
    m1=db.put('media',{'path':'queued'});m2=db.put('media',{'path':'active'})
    b=db.create_batch([m1['id'],m2['id']],{'model':'small','language':'','formats':['srt']})
    jobs=db.rows_by('jobs','batch_id',b['id'])
    db.update('jobs',jobs[1]['id'],status='transcribing')
    monkeypatch.setenv('VIDOE_NO_WORKER','1');monkeypatch.setenv('VIDOE_TEST','1')
    from fastapi.testclient import TestClient
    from backend.app import app
    with TestClient(app) as c:
        assert c.get('/api/health').json()['schema']==2
        after=db.rows_by('jobs','batch_id',b['id'])
        assert after[0]['status']=='queued'
        assert after[1]['status']=='interrupted'
        assert db.get('batches',b['id'])['status']=='interrupted'


def test_security_headers_and_internal_path_guard(tmp_path,monkeypatch):
    reset(tmp_path,monkeypatch);monkeypatch.setenv('VIDOE_NO_WORKER','1');monkeypatch.setenv('VIDOE_TEST','1')
    m=db.put('media',{'path':'fixture'});b=db.create_batch([m['id']],{'model':'small','language':'','formats':['txt']});j=db.rows_by('jobs','batch_id',b['id'])[0]
    outside=tmp_path/'outside.txt';outside.write_text('secret',encoding='utf-8')
    db.put('artifacts',{'id':j['id']+'-txt','job_id':j['id'],'kind':'txt','path':str(outside),'origin':'test'})
    from fastapi.testclient import TestClient
    from backend.app import app
    with TestClient(app) as c:
        r=c.get('/api/session');assert 'Content-Security-Policy' in r.headers and r.headers['Cache-Control']=='no-store'
        assert c.get(f'/api/jobs/{j["id"]}/artifacts/txt').status_code==400


def _make_export_fixture(tmp_path,monkeypatch):
    reset(tmp_path,monkeypatch)
    roots=[];medias=[]
    for branch in ('a','b'):
        root=tmp_path/branch/'同名根';root.mkdir(parents=True);p=root/'01. Interview.终版.MP4';p.write_bytes(branch.encode())
        roots.append(root);medias.append(db.put('media',{'path':str(p),'name':p.name,'parent':str(p.parent),'root':str(root),'fingerprint':fs.fingerprint(p),'duration':3,'existing':{'srt':{'exists':False,'valid':False},'txt':{'exists':False,'valid':False}}}))
    b=db.create_batch([m['id'] for m in medias],{'model':'small','language':'','formats':['srt']});jobs=db.rows_by('jobs','batch_id',b['id'])
    for j in jobs:
        path=db.DATA/'artifacts'/j['id']/'result.srt';db.atomic_text(path,'1\n00:00:00,000 --> 00:00:01,000\n测试\n')
        db.put('artifacts',{'id':j['id']+'-srt','job_id':j['id'],'kind':'srt','path':str(path),'origin':'test'})
        db.update('jobs',j['id'],status='completed',available=['srt'])
    return b,jobs,medias


def _wait_export(eid,timeout=10):
    end=time.time()+timeout
    while time.time()<end:
        e=db.get('exports',eid)
        if e['status'] not in ('queued','running'):return e
        time.sleep(.05)
    raise TimeoutError(eid)


def test_zip_aliases_unicode_and_no_path_escape(tmp_path,monkeypatch):
    b,jobs,_=_make_export_fixture(tmp_path,monkeypatch)
    pf=exports.preflight(b['id'],[j['id'] for j in jobs],'srt','zip')
    entries=[i['entry'] for i in pf['items']]
    assert len(set(entries))==2 and any(x.startswith('同名根/') for x in entries) and any(x.startswith('同名根 (2)/') for x in entries)
    assert all(not x.startswith('/') and '..' not in Path(x).parts for x in entries)
    e=_wait_export(exports.start(pf['id'])['id']);assert e['status']=='completed'
    with zipfile.ZipFile(e['download_path']) as z:assert set(z.namelist())==set(entries)


def test_distribution_race_never_overwrites(tmp_path,monkeypatch):
    b,jobs,medias=_make_export_fixture(tmp_path,monkeypatch)
    job=jobs[0];media=medias[0];target=Path(media['path']).with_suffix('.srt')
    pf=exports.preflight(b['id'],[job['id']],'srt','distribute');assert pf['items'][0]['status']=='ready'
    target.write_text('someone else',encoding='utf-8')
    e=_wait_export(exports.start(pf['id'])['id'])
    assert e['status']=='completed' and e['items'][0]['status']=='skipped'
    assert target.read_text(encoding='utf-8')=='someone else'


def test_worker_singleton_lock_real_subprocess(tmp_path):
    data=tmp_path/'worker-data';env=os.environ.copy();env['VIDOE_DATA']=str(data);env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])
    holder_code="from backend import storage as db;db.init();from backend.worker import acquire_worker_lock,release_worker_lock;import time;print(acquire_worker_lock(),flush=True);time.sleep(4);release_worker_lock()"
    holder=subprocess.Popen([sys.executable,'-c',holder_code],cwd=Path(__file__).resolve().parents[1],env=env,stdout=subprocess.PIPE,text=True)
    try:
        assert holder.stdout and holder.stdout.readline().strip()=='True'
        second=subprocess.run([sys.executable,'-m','backend.worker'],cwd=Path(__file__).resolve().parents[1],env=env,timeout=8)
        assert second.returncode==73
    finally:
        holder.terminate();holder.wait(timeout=5)


def test_event_state_is_compact_and_real(tmp_path,monkeypatch):
    reset(tmp_path,monkeypatch);m=db.put('media',{'path':'x'});b=db.create_batch([m['id']],{'model':'small','language':'','formats':['srt']});j=db.rows_by('jobs','batch_id',b['id'])[0];db.update('jobs',j['id'],status='transcribing',processed=12.5,device='cuda · int8_float16')
    from backend.app import event_state
    state=event_state(b['id']);assert state['status']=='running' and state['jobs'][0]['processed']==12.5 and 'media' not in state['jobs'][0]

def test_audio_windows_are_bounded_and_cover_long_media(tmp_path):
    import wave
    import numpy as np
    from backend.inference import audio_windows,RATE
    wav=tmp_path/'130s.wav'
    one=(np.sin(2*np.pi*440*np.arange(RATE)/RATE)*0.1*32767).astype('<i2').tobytes()
    with wave.open(str(wav),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(RATE)
        for _ in range(130):w.writeframesraw(one)
    windows=list(audio_windows(wav))
    assert len(windows)==3
    assert all(len(audio)<=60*RATE for audio,*_ in windows)
    starts=[x[1] for x in windows];ends=[x[2] for x in windows]
    assert starts[0]==pytest.approx(0,abs=.02)
    assert starts[1]==pytest.approx(59,abs=.05) and starts[2]==pytest.approx(118,abs=.05)
    assert ends[-1]==pytest.approx(130,abs=.05)
    assert windows[-1][-1] is True and all(x[-1] is False for x in windows[:-1])
