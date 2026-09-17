"""Handoff baseline only, not full product acceptance. All writes are isolated in tmp_path."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from backend import storage as db
from backend.texts import parse_srt, srt_text, paragraphs, timestamp
from backend.exports import exclusive_write
from backend.filesystem import fingerprint, validate_media
from backend.inference import owned_words

SRT='1\n00:00:00,000 --> 00:00:01,500\n你好。\n\n2\n00:00:02,000 --> 00:00:03,000\nHello world.\n'

def test_srt_roundtrip():
    parsed=parse_srt(SRT)
    assert parse_srt(srt_text(parsed))==parsed
    assert '你好。' in paragraphs(parsed)
    assert 'Hello world.' in paragraphs(parsed)

@pytest.mark.parametrize('text',['','not srt','1\n00:00:03,000 --> 00:00:01,000\nwrong','1\n00:61:00,000 --> 00:62:00,000\nwrong'])
def test_invalid_srt(text):
    with pytest.raises(ValueError):parse_srt(text)

def test_time_format():assert timestamp(3661.125)=='01:01:01,125'

def test_exclusive_write(tmp_path):
    source=tmp_path/'internal.txt';source.write_text('new',encoding='utf-8')
    target=tmp_path/'01. Interview.final.txt'
    exclusive_write(source,target)
    assert target.read_text()=='new'
    source.write_text('changed')
    with pytest.raises(FileExistsError):exclusive_write(source,target)
    assert target.read_text()=='new'
    assert not list(tmp_path.glob('.vidoe-*.tmp'))

def test_source_fingerprint(tmp_path):
    p=tmp_path/'视频.MP4';p.write_bytes(b'one')
    m={'path':str(p),'fingerprint':fingerprint(p)}
    assert validate_media(m) is None
    p.write_bytes(b'changed')
    assert validate_media(m)

def test_word_ownership():
    seg=SimpleNamespace(words=[SimpleNamespace(start=0.,end=.4,word='a'),SimpleNamespace(start=.4,end=.8,word='b')])
    left=owned_words([seg],0,0,.4);right=owned_words([seg],0,.4,1)
    assert [w['word'] for w in left+right]==['a','b']

def test_sqlite_foreign_keys(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'db');db.init()
    b=db.put('batches',{'status':'paused'})
    m=db.put('media',{'path':'fixture'})
    j=db.put('jobs',{'batch_id':b['id'],'media_id':m['id'],'status':'queued'})
    db.update('jobs',j['id'],status='completed')
    assert db.get('jobs',j['id'])['status']=='completed'
    with db.connect() as c:assert c.execute('PRAGMA foreign_keys').fetchone()[0]==1

def test_api_boundary(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'db')
    monkeypatch.setenv('VIDOE_NO_WORKER','1');monkeypatch.setenv('VIDOE_TEST','1')
    from fastapi.testclient import TestClient
    from backend.app import app
    with TestClient(app) as c:
        assert c.get('/api/system/status').status_code==200
        assert c.get('/api/batches').status_code==401
        assert c.get('/api/session').status_code==200
        assert c.get('/api/batches').json()=={'batches':[]}
        assert c.get('/api/batches',headers={'Origin':'https://evil.invalid'}).status_code==403
        assert c.get('/api/system/status',headers={'Host':'evil.invalid'}).status_code==403


def test_atomic_status_claim(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'db');db.init()
    e=db.put('exports',{'status':'preflight'})
    assert db.claim_status('exports',e['id'],'preflight',status='queued')['status']=='queued'
    assert db.claim_status('exports',e['id'],'preflight',status='queued') is None

def test_transactional_batch_creation(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA',tmp_path/'db');db.init()
    m1=db.put('media',{'path':'a'});m2=db.put('media',{'path':'b'})
    b=db.create_batch([m1['id'],m2['id']],{'model':'small','language':'','formats':['srt']})
    jobs=[j for j in db.all_rows('jobs') if j['batch_id']==b['id']]
    assert b['status']=='running' and len(jobs)==2 and all(j['status']=='queued' for j in jobs)
