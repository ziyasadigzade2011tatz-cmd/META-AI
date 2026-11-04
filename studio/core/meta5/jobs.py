import json
import re
import shutil
import os
import stat
import threading
import time
import uuid
from pathlib import Path
from .storage import STATE,CORE,atomic_json,read_json
from .tools import ToolContext
from .agent import execute
from .memory import Memory


class Jobs:
    def __init__(self,projects,state=None):
        self.projects=Path(projects);self.state=Path(state or STATE/'tasks');self.state.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.active=None;self.cancel=None
        for p in self.state.glob('*.json'):
            data=read_json(p,{})
            if data.get('status') in ('queued','running','cancelling'):
                data.update(status='interrupted',note='Core перезапущен. Можно продолжить вручную.');atomic_json(p,data)
    def path(self,jid):
        if not isinstance(jid,str) or not re.fullmatch('[a-f0-9]{32}',jid):raise ValueError('Неверный ID задачи')
        return self.state/(jid+'.json')
    def get(self,jid):
        with self.lock:
            data=read_json(self.path(jid))
            if data is None:data=read_json(CORE/'meta40_state'/(jid+'.json'))
            if data is None:raise FileNotFoundError('Задача не найдена')
            return data
    def history(self):
        rows={}
        for folder in (CORE/'meta40_state',self.state):
            for p in folder.glob('*.json'):
                data=read_json(p,{})
                if data.get('id'):rows[data['id']]={k:data.get(k) for k in ('id','status','created','task','project','model')}
        return sorted(rows.values(),key=lambda d:d.get('created',0),reverse=True)[:100]
    def start(self,request):
        with self.lock:
            if not request.get('permissions',{}).get('files_read',True):raise ValueError('Работа с проектом требует разрешения на чтение файлов')
            if self.active:raise ValueError('Уже выполняется другая задача')
            from .context import resolve,constraints
            request=dict(request);limits=constraints(request['task'])
            if limits['no_execution']:request.update(allow_tests=False,allow_install=False)
            if resolve([*request.get('history',[]),{'role':'user','content':request['task']}])['web_disabled']:request['allow_web']=False
            from meta40.workspace import project_root
            root=project_root(self.projects,request.get('project','.'),create=request.get('create_project',False))
            jid=uuid.uuid4().hex;data={'id':jid,'version':'5.0.0','status':'queued','created':time.time(),'task':request['task'],'project':str(root),'model':request.get('model','auto'),
                                     'request':request,'events':[],'result':None}
            atomic_json(self.path(jid),data);self._launch(jid,root,request,resume=False);return {'id':jid,'status':'queued'}
    def _launch(self,jid,root,request,resume):
        self.active=jid;event=threading.Event();self.cancel=event
        try:threading.Thread(target=self.worker,args=(jid,root,request,event,resume),daemon=True,name='META5-'+jid[:8]).start()
        except RuntimeError:self.active=None;self.cancel=None;raise
    def resume(self,jid):
        with self.lock:
            if self.active:raise ValueError('Уже выполняется другая задача')
            data=self.get(jid)
            if data.get('workspace_archived'):raise ValueError('Рабочая копия удалена пользователем; создай новую задачу')
            if data['status'] not in ('paused','interrupted','cancelled','failed'):raise ValueError('Эту задачу нельзя продолжить')
            checkpoint=read_json(STATE/'checkpoints'/(jid+'.json'))
            if not checkpoint:raise ValueError('У старой задачи нет совместимой контрольной точки. Создай новую задачу.')
            data.update(status='queued',result=None);atomic_json(self.path(jid),data)
            self._launch(jid,data['project'],data['request'],resume=True);return {'id':jid,'status':'queued'}
    def stop(self,jid):
        with self.lock:
            if self.active==jid and self.cancel:self.cancel.set();return {'status':'cancelling'}
            return {'status':self.get(jid)['status']}
    def archive_workspace(self,jid):
        with self.lock:
            data=self.get(jid)
            if self.active==jid or data['status'] in ('running','queued','cancelling'):raise ValueError('Сначала останови задачу')
            parent=(STATE/'workspaces').resolve();target=parent/jid
            if target.is_symlink() or (target.exists() and target.resolve()!=target):raise ValueError('Небезопасный путь рабочей копии')
            if target.parent!=parent:raise ValueError('Рабочая копия вне каталога задач')
            checkpoint=read_json(STATE/'checkpoints'/(jid+'.json'),{})
            if target.exists():
                if Path(checkpoint.get('work','')).resolve()!=target:raise ValueError('Путь не совпал с сохранённой задачей')
                if checkpoint.get('workspace_info',{}).get('kind')=='git_worktree':
                    from .git_tools import command
                    result=command(checkpoint['original'],'worktree','remove','--force',str(target),timeout=30)
                    if result['exit_code']:raise ValueError(result['output'][-600:])
                else:
                    def clear_readonly(fn,path,exc):
                        if not isinstance(exc,PermissionError):raise exc
                        if not Path(path).absolute().is_relative_to(target):raise ValueError('Cleanup path escaped workspace')
                        os.chmod(path,stat.S_IWRITE,follow_symlinks=False);fn(path)
                    shutil.rmtree(target,onexc=clear_readonly)
            data['workspace_archived']=True;atomic_json(self.path(jid),data)
            return {'archived':True,'note':'История и файловая заявка сохранены; продолжение этой задачи отключено'}
    def emit(self,jid,kind,payload):
        with self.lock:
            data=self.get(jid);data['events'].append({'at':time.time(),'type':kind,'data':payload});data['events']=data['events'][-300:]
            atomic_json(self.path(jid),data)
    def worker(self,jid,root,request,cancel,resume=False):
        ctx=None
        try:
            with self.lock:
                d=self.get(jid);d['status']='running';atomic_json(self.path(jid),d)
            from .context import constraints
            limits=constraints(request['task'])
            opts={'allow_run':request.get('allow_tests',False),'allow_install':request.get('allow_install',False),'allow_write':not limits['readonly'],'protected':limits['protected'],'backend':request.get('backend','native'),'cancel':cancel,'emit':lambda k,v:self.emit(jid,k,v)}
            opts['permissions']=request.get('permissions',{})
            if resume:ctx=ToolContext.restore(read_json(STATE/'checkpoints'/(jid+'.json')),**opts)
            else:ctx=ToolContext.create(root,jid,**opts)
            prior=read_json(STATE/'checkpoints'/(jid+'.loop.json'),{}) if resume else None
            result=execute(ctx,request,prior)
            with self.lock:
                d=self.get(jid);d.update(status=result['status'],result=result,finished=time.time(),workspace=ctx.workspace_info);atomic_json(self.path(jid),d)
            try:Memory().summary('project:'+str(root),'Предыдущая задача ('+result['status']+'): '+request['task'][:800]+'\n'+result.get('summary','')[:1800])
            except OSError:pass
        except Exception as exc:
            with self.lock:
                d=self.get(jid);d.update(status='failed',error=type(exc).__name__+': '+str(exc)[:2000],finished=time.time());atomic_json(self.path(jid),d)
            if ctx:ctx.close()
        finally:
            with self.lock:self.active=None;self.cancel=None
