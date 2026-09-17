import re

def timestamp(seconds):
    n=max(0,round(seconds*1000)); h,n=divmod(n,3600000);m,n=divmod(n,60000);s,ms=divmod(n,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def parse_srt(text):
    result=[]
    for block in re.split(r'\n\s*\n',text.replace('\r','').strip().lstrip('\ufeff')):
        lines=block.splitlines()
        if len(lines)<3 or not lines[0].strip().isdigit(): raise ValueError('SRT 序号或正文无效')
        m=re.fullmatch(r'(\d{2,}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+(\d{2,}):(\d{2}):(\d{2}),(\d{3})',lines[1].strip())
        if not m: raise ValueError('SRT 时间轴无效')
        v=list(map(int,m.groups()))
        if any(v[i]>=60 for i in (1,2,5,6)): raise ValueError('SRT 时间超出范围')
        a=v[0]*3600+v[1]*60+v[2]+v[3]/1000;b=v[4]*3600+v[5]*60+v[6]+v[7]/1000
        body='\n'.join(lines[2:]).strip()
        if a>=b or not body or (result and a<result[-1]['start']): raise ValueError('SRT 顺序或内容无效')
        result.append({'start':a,'end':b,'text':body})
    if not result: raise ValueError('SRT 为空')
    return result

def srt_text(segments):
    return '\n\n'.join(f'{i+1}\n{timestamp(s["start"])} --> {timestamp(s["end"])}\n{s["text"].strip()}' for i,s in enumerate(segments))+'\n'

def join_text(a,b):
    if not a:return b.strip()
    # Keep multilingual spacing, without introducing spaces between Chinese characters.
    space=bool(re.search(r'[A-Za-z0-9]$',a) and re.match(r'[A-Za-z0-9]',b.strip())) or b.startswith(' ')
    return a+(' ' if space else '')+b.strip()

def paragraphs(segments):
    out=[];current='';last=0
    for seg in segments:
        if current and (seg['start']-last>1.5 or (len(current)>220 and re.search(r'[。！？.!?]$',current)) or len(current)>600):
            out.append(current);current=''
        current=join_text(current,seg['text']);last=seg['end']
    if current:out.append(current)
    return '\n\n'.join(out)+'\n' if out else ''

def cues_from_words(words):
    cues=[];current=[];text=''
    def emit():
        if current:
            start=max(0,current[0]['start']);end=max(start+.001,current[-1]['end'])
            cues.append({'start':start,'end':end,'text':text.strip()})
    for w in words:
        candidate=join_text(text,w['word'])
        if current and (len(candidate)>48 or w['start']-current[-1]['end']>1.2 or w['end']-current[0]['start']>7):
            emit();current=[];text=''
        current.append(w);text=join_text(text,w['word'])
        if re.search(r'[。！？.!?]$',text):emit();current=[];text=''
    emit();return cues
