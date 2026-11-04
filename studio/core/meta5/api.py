import asyncio
import hmac
import json
import re
from pathlib import Path
from typing import Literal
import httpx
from fastapi import APIRouter,Depends,Header,HTTPException
from fastapi.responses import StreamingResponse,FileResponse
from pydantic import BaseModel,Field
from . import VERSION,models,dialogue
from .storage import CORE,STATE,read_json,atomic_json
from .jobs import Jobs
from .process import capabilities
from .project import Project
from .memory import Memory

MANAGER=None


class ConversationMessage(BaseModel):
    role:Literal['user','assistant'];content:str=Field(max_length=12000)
class TaskRequest(BaseModel):
    tool_mode:Literal['auto','json']='auto'
    permissions:dict[str,bool]=Field(default_factory=dict)
    task:str=Field(min_length=3,max_length=20000)
    project:str=Field(default='.',max_length=240)
    create_project:bool=False
    model:str=Field(default='auto',pattern=r'^[A-Za-z0-9_.:/-]{1,100}$')
    max_steps:int=Field(default=24,ge=1,le=60)
    seconds:int=Field(default=900,ge=30,le=3600)
    allow_tests:bool=False
    allow_install:bool=False
    test_consent:Literal['','EXECUTE_PROJECT_PYTHON','EXECUTE_TRUSTED_PROJECT']=''
    backend:Literal['native','docker']='native'
    history:list[ConversationMessage]=Field(default_factory=list,max_length=30)
    allow_web:bool=True
    allow_self_inspect:bool=True


class ChatRequest(BaseModel):
    temperature:float=Field(default=.3,ge=0,le=2)
    context:int=Field(default=8192,ge=2048,le=16384)
    model:str=Field(default='auto',pattern=r'^[A-Za-z0-9_.:/-]{1,100}$')
    messages:list[dict]=Field(min_length=1,max_length=200)
    session_id:str=Field(default='',pattern=r'^[A-Za-z0-9_:-]{0,100}$')
    project:str=Field(default='.',max_length=240)
    stream:bool=False
    allow_tests:bool=False
    test_consent:str=''
    backend:Literal['native','docker']='native'


def data(request):return request.model_dump() if hasattr(request,'model_dump') else request.dict()
def consent(request):
    if request.allow_tests and request.test_consent not in ('EXECUTE_PROJECT_PYTHON','EXECUTE_TRUSTED_PROJECT'):raise HTTPException(400,'Нужно согласие на выполнение кода этой задачи')


def install(app,core=None):
    global MANAGER
    import os
    core=Path(core or CORE);config=read_json(Path(os.environ.get('META_CORE_CONFIG_DIR',str(core)))/'meta40_config.json')
    if not config or not config.get('token'):raise ValueError('Нужен существующий локальный meta40_config.json')
    manager=Jobs(config['projects']);MANAGER=manager;app.state.meta40=manager;app.state.meta5=manager
    def auth(x_meta40_token:str=Header(default='')):
        if not hmac.compare_digest(x_meta40_token.encode(),config['token'].encode()):raise HTTPException(401,'Требуется локальная авторизация META')
    router=APIRouter(prefix='/agent40',dependencies=[Depends(auth)])
    def checked_project(name):
        from meta40.workspace import project_root
        return Project(project_root(config['projects'],name))

    @router.get('/status')
    def status():return {'version':VERSION,'active':manager.active,'projects':config['projects'],'profiles':['python-unittest','python-pytest','python-syntax','node-test','package-test','typescript'],'capabilities':capabilities(),'models':models.profiles(),'test_security':'Native user permissions or optional Docker; never an automatic sandbox fallback'}
    @router.get('/models')
    def installed_models():
        try:
            with httpx.Client(timeout=5,trust_env=False) as c:return {'models':[m['name'] for m in c.get(transport_url()+'/api/tags').json().get('models',[])]}
        except Exception as exc:raise HTTPException(503,str(exc)[:400])
    @router.get('/model-profiles')
    def profiles():return models.profiles()
    @router.get('/model-benchmark')
    def benchmark_status():return read_json(STATE/'benchmark.json',{'status':'not_started'})
    @router.post('/model-benchmark',status_code=202)
    def benchmark_start(payload:dict):
        import threading
        from . import benchmarks
        if manager.active or benchmarks.LOCK.locked():raise HTTPException(409,'Дождись завершения текущей задачи или измерения')
        available=installed_models()['models'];names=payload.get('models') or [n for n in available if n in ('qwen2.5:3b','qwen3:4b','qwen2.5-coder:7b','qwen2.5-coder:14b')]
        if not isinstance(names,list) or not 1<=len(names)<=4 or any(n not in available for n in names):raise HTTPException(400,'Выбери от одной до четырёх установленных моделей')
        if not benchmarks.LOCK.acquire(blocking=False):raise HTTPException(409,'Измерение уже запущено')
        try:threading.Thread(target=benchmarks.run,args=(names,),kwargs={'lock_held':True},daemon=True).start()
        except RuntimeError:benchmarks.LOCK.release();raise
        return {'status':'running'}
    @router.post('/model-profiles')
    def set_profiles(payload:dict):
        current=models.profiles();available=installed_models()['models']
        for key in ('chat','code','vision','quality'):
            if key in payload:
                if payload[key] not in available:raise HTTPException(400,'Модель не установлена: '+str(payload[key]))
                current[key]=payload[key]
        if 'context' in payload:current['context']=min(16384,max(4096,int(payload['context'])))
        current['source']='user_configured';atomic_json(models.PROFILE_FILE,current);return current
    @router.get('/tasks')
    def history():return {'tasks':manager.history()}
    @router.post('/tasks',status_code=202)
    def create(request:TaskRequest):
        consent(request)
        try:return manager.start(data(request))
        except (ValueError,OSError) as exc:raise HTTPException(409,str(exc))
    @router.get('/tasks/{jid}')
    def detail(jid:str):
        try:return manager.get(jid)
        except FileNotFoundError as exc:raise HTTPException(404,str(exc))
    @router.post('/tasks/{jid}/cancel')
    def cancel(jid:str):return manager.stop(jid)
    @router.post('/tasks/{jid}/resume')
    def resume(jid:str):
        try:return manager.resume(jid)
        except (ValueError,FileNotFoundError) as exc:raise HTTPException(409,str(exc))
    @router.post('/tasks/{jid}/archive-workspace')
    def archive_workspace(jid:str):
        try:return manager.archive_workspace(jid)
        except (ValueError,FileNotFoundError,OSError) as exc:raise HTTPException(409,str(exc))
    @router.get('/tasks/{jid}/artifacts/{name}')
    def artifact(jid:str,name:str):
        manager.path(jid)
        if name not in ('screenshot.png','screen.png','document.md','document.csv','document.html','document.docx','document.xlsx','document.pptx'):raise HTTPException(404)
        p=STATE/'artifacts'/jid/name
        if not p.is_file():raise HTTPException(404)
        return FileResponse(p,filename=name,media_type='image/png' if name.endswith('.png') else 'application/octet-stream')
    @router.get('/project/index')
    def index(project:str='.'):
        try:return checked_project(project).index()
        except (ValueError,OSError) as exc:raise HTTPException(400,str(exc))
    @router.get('/project/read')
    def read(project:str='.',path:str='',start:int=1,end:int=200):
        try:return checked_project(project).read(path,start,end)
        except (ValueError,OSError) as exc:raise HTTPException(400,str(exc))
    @router.get('/project/search')
    def search(project:str='.',query:str=''):
        try:return {'matches':checked_project(project).search(query)}
        except (ValueError,OSError) as exc:raise HTTPException(400,str(exc))
    @router.get('/memory')
    def memory():return {'enabled':Memory().enabled(),'facts':Memory().list()}
    @router.post('/memory')
    def add_memory(payload:dict):
        m=Memory()
        try:
            if 'enabled' in payload:m.set_enabled(bool(payload['enabled']))
            if 'delete' in payload:m.delete(str(payload['delete']))
            if 'value' in payload:
                if payload.get('id'):m.update(str(payload['id']),payload['value'],payload.get('kind','fact'))
                else:m.add(payload['value'],payload.get('kind','fact'))
            return {'enabled':m.enabled(),'facts':m.list()}
        except ValueError as exc:raise HTTPException(400,str(exc))
    @router.post('/dialogue/stream')
    async def stream_chat(request:ChatRequest):
        consent(request)
        async def events():
            try:
                async for event in dialogue.converse(data(request),manager):yield 'data: '+json.dumps(event,ensure_ascii=False)+'\n\n'
            except Exception as exc:yield 'data: '+json.dumps({'type':'error','data':{'message':str(exc)[:500]}},ensure_ascii=False)+'\n\n'
        return StreamingResponse(events(),media_type='text/event-stream')
    @router.post('/dialogue/{session}/cancel')
    def cancel_chat(session:str):return {'cancelled':dialogue.stop(session)}
    from .advanced_api import install as install_advanced
    install_advanced(router,manager,checked_project)
    app.include_router(router)


def transport_url():
    from .transport import BASE
    return BASE
