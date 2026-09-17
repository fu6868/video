from __future__ import annotations
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
URL='http://127.0.0.1:8765'


def probe(timeout=.8):
    try:
        with urllib.request.urlopen(URL+'/api/health',timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def port_in_use():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
        s.settimeout(.4)
        return s.connect_ex(('127.0.0.1',8765))==0



def process_alive(pid):
    if not pid:return True
    if os.name=='nt':
        import ctypes
        handle=ctypes.windll.kernel32.OpenProcess(0x1000,False,pid)
        if not handle:return False
        ctypes.windll.kernel32.CloseHandle(handle);return True
    try:os.kill(pid,0);return True
    except OSError:return False


def guard_launcher_parent(pid):
    # The Windows venv redirector stays alive while this interpreter runs. If the
    # console/launcher tree is forcibly closed, do not leave a detached server.
    while True:
        time.sleep(1)
        if not process_alive(pid):os._exit(0)


def open_when_ready():
    for _ in range(100):
        state=probe()
        if state and state.get('app')=='vidoe':
            print('映言已启动：http://127.0.0.1:8765',flush=True)
            if os.environ.get('VIDOE_NO_BROWSER')!='1':webbrowser.open(URL)
            return
        time.sleep(.2)
    print('服务未在预期时间内就绪，请查看当前终端输出。',file=sys.stderr,flush=True)


def main():
    existing=probe()
    if existing:
        if existing.get('app')!='vidoe':
            print('端口 8765 已被其他程序占用。');return 2
        print('映言已经在运行，正在打开页面。')
        if os.environ.get('VIDOE_NO_BROWSER')!='1':webbrowser.open(URL)
        return 0
    if port_in_use():
        print('端口 8765 已被其他程序占用，但不是可识别的映言服务。请先关闭占用程序。');return 2
    if not (ROOT/'.venv'/'Scripts'/'python.exe').exists():
        print('未找到 .venv，请先双击 setup.bat。');return 2
    if not (ROOT/'frontend'/'dist'/'index.html').exists():
        print('前端尚未构建，请先双击 setup.bat。');return 2
    os.chdir(ROOT)
    threading.Thread(target=guard_launcher_parent,args=(os.getppid(),),daemon=True,name='vidoe-parent-guard').start()
    (ROOT/'data').mkdir(exist_ok=True)
    pid_file=ROOT/'data'/'service.pid'
    pid_file.write_text(str(os.getpid()),encoding='ascii')
    threading.Thread(target=open_when_ready,daemon=True,name='vidoe-browser-opener').start()
    try:
        import uvicorn
        # Run Uvicorn in this process: closing the launcher cannot leave a detached server tree behind.
        uvicorn.run('backend.app:app',host='127.0.0.1',port=8765,log_level='info',access_log=False)
        return 0
    finally:
        try:
            if pid_file.exists() and pid_file.read_text(encoding='ascii').strip()==str(os.getpid()):pid_file.unlink()
        except OSError:pass


if __name__=='__main__':raise SystemExit(main())
