from __future__ import annotations
import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from backend.inference import Engine,model_path
from backend import storage as db


def main():
    ap=argparse.ArgumentParser(description='映言本地环境检查')
    ap.add_argument('--smoke',action='store_true',help='实际加载 small 模型并执行 CUDA/CPU 初始化探针')
    args=ap.parse_args()
    import av,ctranslate2,faster_whisper
    db.init()
    path=ROOT/'data'/'environment.json'
    try:previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except Exception:previous={}
    result={
        'checked_at':time.time(),'python':sys.version.split()[0],'platform':platform.platform(),
        'av':av.__version__,'ctranslate2':ctranslate2.__version__,'faster_whisper':faster_whisper.__version__,
        'cuda_device_count':ctranslate2.get_cuda_device_count(),'schema':db.schema_version(),
        'models':{name:str(model_path(name)) for name in ('small','medium')},
        'device':previous.get('device','未执行推理探针'),'fallback':previous.get('fallback'),
        'verified_at':previous.get('verified_at'),'last_model':previous.get('last_model'),
    }
    try:
        out=subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader'],text=True,timeout=10).strip()
        result['nvidia_smi']=out
    except Exception as e:result['nvidia_smi_error']=str(e)
    if args.smoke:
        engine=Engine();t=time.time();engine.load('small')
        result.update({'device':engine.device,'fallback':engine.fallback,'small_probe_seconds':round(time.time()-t,3),'verified_at':time.time(),'last_model':'small'})
    db.atomic_text(path,json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__':raise SystemExit(main())
