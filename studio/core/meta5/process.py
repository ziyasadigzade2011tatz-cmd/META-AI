"""Supervised fixed-argv processes. Native execution is never called a sandbox."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from meta40.runner import WindowsJob
from .python_child import argv as python_argv

BOOT="""import os,time,sys,json,subprocess
while not os.path.exists(sys.argv[1]):time.sleep(.01)
argv=json.loads(sys.argv[2])
p=subprocess.Popen(argv,stdin=subprocess.DEVNULL)
sys.exit(p.wait())
"""


class Managed:
    def __init__(self,argv,cwd,*,seconds=60):
        if argv and os.path.normcase(os.path.abspath(argv[0]))==os.path.normcase(os.path.abspath(sys.executable)) and len(argv)>1 and argv[1] in ('-I','-B','-u','-c','-m'):
            argv=python_argv(*argv[1:])
        self.argv=argv;self.cwd=Path(cwd);self.seconds=seconds;self.output=bytearray();self.lock=threading.Lock();self.started=time.monotonic();self.reason=None
        self.temp=tempfile.TemporaryDirectory(prefix='meta5-process-');self.gate=Path(self.temp.name)/'go';self.job=None;self.process=None;self.closed=threading.Event();self.close_lock=threading.Lock()
        env={k:v for k,v in os.environ.items() if k.upper() in {'PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','HOMEDRIVE','HOMEPATH'}}
        from .storage import CORE,read_json
        tool_node=read_json(CORE/'meta5_tools.json',{}).get('node')
        env['PATH']=str(Path(argv[0]).parent)+os.pathsep+(str(Path(tool_node).parent)+os.pathsep if tool_node else '')+env.get('PATH','')
        env.update(HOME=self.temp.name,PYTHONUTF8='1',PYTHONUNBUFFERED='1',NO_COLOR='1')
        try:
            self.job=WindowsJob(max_processes=20,memory_mb=768,total_memory_mb=2048)
            self.process=subprocess.Popen(python_argv('-I','-u','-c',BOOT,str(self.gate),json.dumps(argv)),cwd=self.cwd,env=env,
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
            self.job.assign(self.process);self.gate.touch()
            self.reader=threading.Thread(target=self._drain,daemon=True);self.reader.start()
            threading.Thread(target=self._watch,daemon=True).start()
        except BaseException:
            self.close();raise

    def _watch(self):
        while not self.closed.wait(.1):
            if self.process.poll() is not None:return
            if self.reason or time.monotonic()-self.started>self.seconds:
                self.reason=self.reason or 'timeout';self.close();return

    def _drain(self):
        while True:
            block=self.process.stdout.read(1024)
            if not block:return
            with self.lock:
                available=64000-len(self.output);self.output.extend(block[:max(0,available)])
                if len(block)>available:self.reason='output_limit'

    def status(self):
        with self.lock:
            return {'running':self.process.poll() is None,'exit_code':self.process.poll(),
                    'output':self.output.decode('utf-8','replace'),'status':self.reason or ('running' if self.process.poll() is None else ('passed' if self.process.returncode==0 else 'failed')),
                    'seconds':round(time.monotonic()-self.started,2),'isolation':'native_user_permissions'}

    def close(self):
        with self.close_lock:
            if self.closed.is_set():return
            self.closed.set()
            if self.job:self.job.close()
            if self.process:
                if os.name!='nt':
                    import signal
                    try:os.killpg(self.process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                if self.process.poll() is None:self.process.kill()
                self.process.wait(timeout=5)
                if hasattr(self,'reader'):self.reader.join(timeout=2)
                if self.process.stdout:self.process.stdout.close()
            self.temp.cleanup()


def run(argv,cwd,cancel=None,timeout=60):
    managed=Managed(argv,cwd,seconds=timeout)
    try:
        while managed.process.poll() is None:
            if cancel and cancel.is_set():managed.reason='cancelled';break
            if time.monotonic()-managed.started>timeout:managed.reason='timeout';break
            if managed.reason:break
            time.sleep(.03)
        if managed.process.poll() is None:
            managed.job.close()
            if managed.process.poll() is None:managed.process.kill()
        managed.process.wait(timeout=5);managed.reader.join(timeout=2)
        return managed.status()
    finally:managed.close()


def capabilities():
    import importlib.util
    from .storage import CORE,read_json
    config=read_json(CORE/'meta5_tools.json',{})
    def present(name,fallback=None):
        value=config.get(name)
        if isinstance(value,str) and Path(value).exists():return value
        return fallback
    return {'python':sys.executable,'node':present('node',shutil.which('node')),
            'npm':present('npm'),'typescript':present('typescript'),
            'playwright':present('playwright'),'edge':present('edge'),
            'pytest':bool(importlib.util.find_spec('pytest')),'git':shutil.which('git'),
            'docker':shutil.which('docker'),'docker_ready':False,
            'native_warning':'Код запускается с правами пользователя; это не OS sandbox.'}


def profile_argv(name,root):
    cap=capabilities();root=Path(root)
    venv=root/'.meta5/venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    py=str(venv) if venv.is_file() else sys.executable
    if name=='python-unittest':return [py,'-I','-B','-c',"import sys,unittest;sys.path.insert(0,sys.argv[1]);s=unittest.defaultTestLoader.discover(sys.argv[1],pattern='test*.py');n=s.countTestCases();print('META_TEST_COUNT='+str(n),flush=True);sys.exit(5 if not n else (0 if unittest.TextTestRunner(verbosity=2).run(s).wasSuccessful() else 1))",str(root)]
    if name=='python-pytest':
        if not cap['pytest']:raise ValueError('pytest не установлен в окружении META')
        return [py,'-B','-m','pytest','-q','--disable-warnings']
    if name=='python-syntax':return [sys.executable,'-I','-B','-c',"import ast,pathlib;fs=list(pathlib.Path('.').rglob('*.py'));[(ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p))) for p in fs if not any(x in p.parts for x in ('.git','.venv','node_modules'))];print('Python syntax OK')"]
    if name=='node-test' and cap['node']:return [cap['node'],'--test']
    if name=='package-test' and cap['node'] and (root/'package.json').is_file():
        return [cap['node'],cap['npm'],'test'] if cap['npm'] else [cap['node'],'--run','test']
    if name=='typescript' and cap['node'] and cap['typescript']:return [cap['node'],cap['typescript'],'--noEmit','--pretty','false']
    raise ValueError('Профиль недоступен: '+str(name))


def test_profile(name,root,enabled,cancel=None,backend='native',timeout=60):
    if not enabled:raise PermissionError('Выполнение кода не разрешено для этой задачи')
    argv=profile_argv(name,root)
    if backend=='native':return run(argv,root,cancel,timeout)
    if backend!='docker':raise ValueError('Неизвестный backend исполнения')
    docker=shutil.which('docker')
    if not docker:raise ValueError('Docker не установлен. Изолированный запуск недоступен; автоматического перехода к native нет.')
    image='python:3.12-slim' if name.startswith('python') else 'node:22-slim'
    check=subprocess.run([docker,'image','inspect',image],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
    if check.returncode:raise ValueError('Нет локального образа '+image+'; автоматическое скачивание отключено')
    if name=='python-unittest':command=['python','-m','unittest','discover','-v']
    elif name=='node-test':command=['node','--test']
    else:raise ValueError('Для этого профиля нужен подготовленный образ с зависимостями проекта')
    import uuid
    name='meta5-'+uuid.uuid4().hex
    try:
        result=run([docker,'run','--name',name,'--rm','--pull','never','--network','none','--memory','1g','--cpus','2','--pids-limit','64','--cap-drop','ALL','--security-opt','no-new-privileges','--read-only','--tmpfs','/tmp:rw,size=64m','-e','PYTHONDONTWRITEBYTECODE=1','-v',str(Path(root).resolve())+':/workspace:ro','-w','/workspace',image,*command],root,cancel,timeout)
        result['isolation']='docker_no_network_readonly';return result
    finally:
        subprocess.run([docker,'rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
