"""Bounded audio windows and exclusive word ownership across overlapping windows."""
from __future__ import annotations
import os
from pathlib import Path
import numpy as np
from .storage import ROOT

RATE=16000
WINDOW_SECONDS=60
BUFFER_SECONDS=62
OVERLAP_SECONDS=1
_DLL_HANDLES=[]
_DLL_PATHS=set()


def configure_cuda():
    if os.name!='nt':return
    import site
    known=_DLL_PATHS
    for base in site.getsitepackages():
        nvidia=Path(base)/'nvidia'
        if nvidia.exists():
            for folder in nvidia.glob('*/bin'):
                folder=str(folder.resolve())
                if folder not in known:
                    os.environ['PATH']=folder+os.pathsep+os.environ.get('PATH','')
                    _DLL_HANDLES.append(os.add_dll_directory(folder));known.add(folder)
    for name in ('CUDA_PATH','CUDA_PATH_V12_8'):
        raw=os.environ.get(name)
        if not raw:continue
        folder=Path(raw)/'bin'
        if folder.is_dir():
            resolved=str(folder.resolve())
            if resolved not in known:_DLL_HANDLES.append(os.add_dll_directory(resolved));known.add(resolved)


def model_path(name):
    if name not in ('small','medium'):raise ValueError('不支持的模型')
    base=ROOT/'huggingface_cache'/'hub'/f'models--Systran--faster-whisper-{name}'/'snapshots'
    for p in sorted(base.glob('*')):
        if all((p/f).is_file() and (p/f).stat().st_size for f in ('config.json','model.bin','tokenizer.json','vocabulary.txt')):return p
    raise RuntimeError(f'{name} 本地模型缺失；应用不会自动下载模型')


def audio_windows(path):
    """Yield <=~60s mono float32 windows with 1s overlap without growing with media length."""
    import av
    pieces=[]
    buffered=0
    start_samples=0
    with av.open(str(path)) as c:
        if not c.streams.audio:raise ValueError('视频没有音轨')
        streams=list(c.streams.audio)
        stream=next((s for s in streams if bool(s.disposition & av.stream.Disposition.default)),streams[0])
        offset=float(stream.start_time*stream.time_base) if stream.start_time is not None else 0
        offset=max(0,offset)
        resampler=av.AudioResampler(format='fltp',layout='mono',rate=RATE)

        def append(arr):
            nonlocal buffered
            arr=np.asarray(arr,dtype=np.float32).reshape(-1)
            if arr.size:
                pieces.append(arr);buffered+=arr.size

        def take(final=False):
            nonlocal pieces,buffered,start_samples
            if not buffered:return
            if not final and buffered<BUFFER_SECONDS*RATE:return
            buffer=pieces[0] if len(pieces)==1 else np.concatenate(pieces)
            pieces=[];buffered=0
            while len(buffer)>=BUFFER_SECONDS*RATE or (final and len(buffer)):
                if final and len(buffer)<BUFFER_SECONDS*RATE:
                    cut=len(buffer);last=True
                else:
                    # Search 55–60 s for the quietest 100 ms boundary; otherwise cut at 60 s.
                    candidates=[(float(np.mean(buffer[i:i+1600]**2)),i+800) for i in range(55*RATE,WINDOW_SECONDS*RATE,1600)]
                    energy,pos=min(candidates)
                    cut=pos if energy<0.0001 else WINDOW_SECONDS*RATE;last=False
                audio=buffer[:cut].copy()
                start=offset+start_samples/RATE
                end=offset+(start_samples+cut)/RATE
                owner_end=end if last else end-.5
                yield audio,start,end,owner_end,last
                if last:
                    buffer=np.empty(0,dtype=np.float32);break
                advance=cut-OVERLAP_SECONDS*RATE
                buffer=buffer[advance:]
                start_samples+=advance
            if len(buffer):
                pieces=[buffer];buffered=len(buffer)

        for frame in c.decode(stream):
            for f in resampler.resample(frame):
                append(f.to_ndarray())
                if buffered>=BUFFER_SECONDS*RATE:yield from take(False)
        for f in resampler.resample(None):append(f.to_ndarray())
        yield from take(True)


def owned_words(segments,start,lower,upper):
    words=[]
    for s in segments:
        if s.words:
            candidates=[{'start':start+w.start,'end':start+w.end,'word':w.word} for w in s.words]
        else:candidates=[{'start':start+s.start,'end':start+s.end,'word':s.text}]
        for w in candidates:
            mid=(w['start']+w['end'])/2
            if lower<=mid<upper and w['word'].strip():words.append(w)
    return words


class Engine:
    def __init__(self):self.model=None;self.loaded=None;self.device='尚未初始化';self.fallback=None
    def load(self,name,device=None):
        configure_cuda()
        from faster_whisper import WhisperModel
        path=model_path(name)
        if self.loaded==(name,device) and self.model:return
        self.model=None;self.fallback=None
        if device!='cpu':
            try:
                self.model=WhisperModel(str(path),device='cuda',compute_type='int8_float16',local_files_only=True)
                # Exercise CUDA kernels, not merely device discovery.
                segs,_=self.model.transcribe(np.zeros(RATE,dtype=np.float32),language='en',vad_filter=False,beam_size=1)
                list(segs);self.device='cuda · int8_float16'
            except Exception as e:self.fallback=str(e)[:500];self.model=None
        if self.model is None:
            self.model=WhisperModel(str(path),device='cpu',compute_type='int8',local_files_only=True)
            self.device='cpu · int8'
        self.loaded=(name,device)
    def transcribe(self,path,language,callback,checkpoint):
        words=[];lower=0.;detected=language;last_end=0.
        for audio,start,end,owner_end,last in audio_windows(path):
            segs,info=self.model.transcribe(audio,language=detected or None,task='transcribe',vad_filter=True,word_timestamps=True,beam_size=5,condition_on_previous_text=True)
            segs=list(segs)
            if not detected and segs:detected=info.language
            words.extend(owned_words(segs,start,lower,owner_end+(.001 if last else 0)))
            lower=owner_end;last_end=end
            checkpoint(words);callback(end,detected)
        return words,detected,last_end
