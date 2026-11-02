import hashlib
import hmac
import json
import re
import threading
import time
import uuid
import urllib.request
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from .engine import Ollama, run
from .proposals import atomic_json, stage
from .workspace import project_root
from . import VERSION


class TaskRequest(BaseModel):
    task: str = Field(min_length=3, max_length=12000)
    project: str = Field(default='.', max_length=220)
    create_project: bool = False
    model: str = Field(default='qwen2.5-coder:14b', pattern=r'^[A-Za-z0-9_.:/-]{1,100}$')
    max_steps: int = Field(default=16, ge=1, le=30)
    seconds: int = Field(default=600, ge=30, le=1200)
    allow_tests: bool = False
    test_consent: Literal['', 'EXECUTE_PROJECT_PYTHON'] = ''


class Manager:
    def __init__(self, config, state):
        self.config, self.state = config, Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.active = None
        self.cancel = None
        # Surviving records are useful after restart, but no task is silently resumed.
        for p in self.state.glob('*.json'):
            data = json.loads(p.read_text(encoding='utf-8'))
            if data.get('status') in ('running', 'queued', 'cancelling'):
                data['status'] = 'interrupted'
                atomic_json(p, data)

    def get(self, jid):
        if not re.fullmatch('[a-f0-9]{32}', jid):
            raise HTTPException(400, 'Invalid task ID')
        with self.lock:
            try: return json.loads((self.state/(jid+'.json')).read_text(encoding='utf-8'))
            except FileNotFoundError: raise HTTPException(404, 'Task not found')

    def start(self, request):
        if request.allow_tests and request.test_consent != 'EXECUTE_PROJECT_PYTHON':
            raise HTTPException(400, 'Explicit test execution consent required')
        with self.lock:
            if self.active:
                raise HTTPException(409, 'One task is already running')
            root = project_root(self.config['projects'], request.project, create=request.create_project)
            # Bound history disk usage to 100 task records, retain newest.
            records = sorted(self.state.glob('*.json'), key=lambda p:p.stat().st_mtime)
            for p in records[:-99]: p.unlink()
            jid = uuid.uuid4().hex
            event = threading.Event()
            data = {'id':jid, 'status':'queued', 'created':time.time(), 'project':str(root),
                    'task':request.task, 'model':request.model, 'allow_tests':request.allow_tests,
                    'events':[], 'result':None}
            atomic_json(self.state/(jid+'.json'), data)
            self.active, self.cancel = jid, event
            threading.Thread(target=self.worker, args=(jid, root, request, event), daemon=True).start()
            return {'id':jid, 'status':'queued'}

    def worker(self, jid, root, request, cancel):
        path = self.state/(jid+'.json')
        def update(fn):
            with self.lock:
                data = self.get(jid)
                fn(data)
                atomic_json(path, data)
        def emit(kind, payload):
            def change(data):
                data['events'].append({'at':time.time(), 'type':kind, 'data':payload})
                data['events'] = data['events'][-120:]
            update(change)
        try:
            update(lambda d:d.update(status='running'))
            memory_dir = self.state/'memory'
            memory_file = memory_dir/(hashlib.sha256(str(root).encode()).hexdigest()+'.txt')
            memory = memory_file.read_text(encoding='utf-8') if memory_file.exists() else ''
            result = run(root, request.task, Ollama(request.model, timeout=min(60, request.seconds)),
                         stage, emit, cancel, request.max_steps, request.seconds,
                         request.allow_tests, memory)
            update(lambda d:d.update(status=result['status'], result=result, finished=time.time()))
            if result['status'] in ('completed', 'pending'):
                memory_dir.mkdir(exist_ok=True)
                memory_file.write_text('Previous task (untrusted): '+request.task[:1000]+'\n'
                                       +result.get('summary','')[:3000], encoding='utf-8')
        except Exception as exc:
            update(lambda d:d.update(status='failed', error=type(exc).__name__+': '+str(exc)[:3000]))
        finally:
            with self.lock:
                self.active = None
                self.cancel = None


def install(app, core=None):
    core = Path(core or Path(__file__).resolve().parents[1])
    config = json.loads((core/'meta40_config.json').read_text(encoding='utf-8'))
    manager = Manager(config, core/'meta40_state')
    def authorize(x_meta40_token: str = Header(default='')):
        if not hmac.compare_digest(x_meta40_token, config['token']):
            raise HTTPException(401, 'META 4.0 authentication required')
    router = APIRouter(prefix='/agent40', dependencies=[Depends(authorize)])

    @router.get('/status')
    def status():
        return {'version':VERSION, 'active':manager.active,
                'projects':config['projects'], 'profiles':['python-unittest'],
                'test_security':'Disposable copy, NOT an OS sandbox'}

    @router.get('/models')
    def models():
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open('http://127.0.0.1:11434/api/tags', timeout=5) as r:
                data = json.loads(r.read(100000))
            return {'models':[m['name'] for m in data.get('models', [])][:100]}
        except Exception as exc:
            raise HTTPException(503, 'Ollama unavailable: '+str(exc)[:500])

    @router.get('/tasks')
    def history():
        with manager.lock:
            records = sorted(manager.state.glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True)[:30]
            return {'tasks':[{k:d.get(k) for k in ('id','status','created','task','project')}
                              for d in (json.loads(p.read_text(encoding='utf-8')) for p in records)]}

    @router.post('/tasks', status_code=202)
    def create(request: TaskRequest):
        try: return manager.start(request)
        except (ValueError, OSError) as exc: raise HTTPException(400, str(exc))

    @router.get('/tasks/{jid}')
    def detail(jid: str): return manager.get(jid)

    @router.post('/tasks/{jid}/cancel')
    def stop(jid: str):
        manager.get(jid)
        with manager.lock:
            if manager.active == jid and manager.cancel:
                manager.cancel.set()
                return {'status':'cancelling', 'note':'Current model request may take up to 60 seconds'}
        return {'status':manager.get(jid)['status']}

    app.include_router(router)
    app.state.meta40 = manager
