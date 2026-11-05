"""One tool registry and permission model shared by coding and conversation."""
import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path
from .project import Project,digest,validate,MAX_EDIT,SKIP
from .storage import atomic_json,read_json,STATE,CORE
from . import git_tools
from .process import test_profile,capabilities,Managed,run


class ToolContext:
    def __init__(self,original,work,job_id,*,allow_run=False,allow_install=False,allow_write=True,protected=(),backend='native',cancel=None,emit=lambda *a:None,permissions=None):
        self.permissions=dict(permissions or {})
        self.original=Project(original);self.work=Project(work);self.job_id=job_id;self.allow_run=allow_run;self.backend=backend;self.cancel=cancel;self.emit=emit
        self.allow_install=allow_install
        self.allow_write=allow_write;self.protected={p.casefold() for p in protected}
        self.expected={};self.read=set();self.full_read=set();self.edits={};self.processes={};self.plan=[];self.revision=0
        self.checkpoint=STATE/'checkpoints'/(job_id+'.json')

    @classmethod
    def create(cls,original,job_id,**kwargs):
        target=STATE/'workspaces'/job_id;target.parent.mkdir(parents=True,exist_ok=True)
        if len(list(target.parent.iterdir()))>=40:raise ValueError('Сохранено 40 рабочих копий. Сначала разберите старые задачи.')
        info=git_tools.prepare(original,target)
        ctx=cls(original,target,job_id,**kwargs);ctx.workspace_info=info
        total=0;copied=[];excluded=[]
        for entry in ctx.original.files():
            if entry['bytes']>2_000_000:excluded.append(entry['path']);continue
            total+=entry['bytes']
            if total>50_000_000:raise ValueError('Рабочая копия превышает 50 МБ текстов')
            raw=ctx.original.path(entry['path']).read_bytes()
            try:raw.decode('utf-8-sig')
            except UnicodeError:continue
            p=ctx.work.path(entry['path']);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            ctx.expected[entry['path']]=digest(raw);copied.append(entry['path'])
        # Copy small assets for realistic builds/browser checks; never follow links.
        for folder,dirs,names in os.walk(ctx.original.root,followlinks=False):
            dirs[:]=[d for d in dirs if d not in SKIP and not d.startswith('.') and not (Path(folder)/d).is_symlink()]
            for name in names:
                p=Path(folder)/name
                if p.suffix.lower() not in {'.png','.jpg','.jpeg','.gif','.webp','.ico','.svg','.woff','.woff2'}:continue
                rel=p.relative_to(ctx.original.root).as_posix()
                try:source=ctx.original.path(rel,text_only=False);destination=ctx.work.path(rel,text_only=False)
                except ValueError:continue
                if source.stat().st_size>2_000_000:continue
                total+=source.stat().st_size
                if total>70_000_000:break
                destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
        if info['kind']=='disposable_copy':
            git_tools.command(target,'init');git_tools.command(target,'add','--all')
            git_tools.command(target,'-c','user.name=META Local','-c','user.email=meta@localhost','commit','-m','META task baseline')
        ctx.workspace_info.update(copied_files=len(copied),excluded_large_files=excluded[:50]);ctx.save();return ctx

    @classmethod
    def restore(cls,data,**kwargs):
        ctx=cls(data['original'],data['work'],data['job_id'],**kwargs)
        ctx.expected=data['expected'];ctx.read=set(data.get('read',[]));ctx.full_read=set(data.get('full_read',[]));ctx.edits=data.get('edits',{});ctx.plan=data.get('plan',[]);ctx.revision=data.get('revision',0);ctx.workspace_info=data.get('workspace_info',{})
        return ctx

    def data(self):return {'original':str(self.original.root),'work':str(self.work.root),'job_id':self.job_id,'expected':self.expected,'read':list(self.read),'full_read':list(self.full_read),'edits':self.edits,'plan':self.plan,'revision':self.revision,'workspace_info':self.workspace_info}
    def save(self):atomic_json(self.checkpoint,self.data())
    def close(self):
        for proc in self.processes.values():proc.close()
        self.processes.clear()
    def sync_edits(self):
        previous=json.dumps(self.edits,sort_keys=True,ensure_ascii=False)
        current={f['path'] for f in self.work.files()}
        for name in current|set(self.expected):
            p=self.work.path(name)
            raw=p.read_bytes() if p.exists() else None
            if digest(raw)==self.expected.get(name):self.edits.pop(name,None);continue
            if not self.allow_write:raise ValueError('Запрошен только анализ; изменения рабочей копии не будут предложены')
            if name.casefold() in self.protected:raise ValueError('Запрещённый пользователем файл изменён в рабочей копии: '+name)
            if raw is not None:
                if len(raw)>MAX_EDIT:raise ValueError('Изменённый файл больше 256 КБ: '+name)
                value=raw.decode('utf-8-sig');validate(name,value)
            else:value=None
            self.edits[name]=value
        if json.dumps(self.edits,sort_keys=True,ensure_ascii=False)!=previous:self.revision+=1
        self.save()


class Registry:
    def __init__(self):self.items={}
    def register(self,name,description,args,fn,permission='read'):
        self.items[name]={'name':name,'description':description,'args':args,'function':fn,'permission':permission}
    def manifest(self):
        import inspect
        result=[]
        for item in self.items.values():
            properties={};required=[]
            for name,param in inspect.signature(item['function']).parameters.items():
                if name=='ctx':continue
                properties[name]={'type':'integer' if name in ('start','end') else 'array' if name=='steps' else 'string','description':item['args'].get(name,'')}
                if name=='steps':properties[name]['items']={'type':'string'}
                if param.default is inspect.Parameter.empty:required.append(name)
                elif param.default is not None:properties[name]['default']=param.default
            result.append({'name':item['name'],'description':item['description'],'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}})
        return result
    def call(self,ctx,name,args):
        if name not in self.items:raise ValueError('Неизвестный инструмент '+str(name))
        if not isinstance(args,dict):raise ValueError('Аргументы должны быть JSON-объектом')
        item=self.items[name]
        group={'subagent':'files_read','project_memory':'files_read','project_memory_propose':'files_write','artifact_create':'files_create','mcp_call':'mcp','mcp_list':'mcp','computer':'computer','write':'files_write','edit':'files_write','rename':'files_write','delete':'files_write','git':'git','git_commit':'git','test':'tests','process_start':'terminal','browser_inspect':'browser'}.get(name,'files_read' if name in ('list','read','search','symbols','project_info') else None)
        if name=='write' and not ctx.work.path(args.get('path','')).exists():group='files_create'
        if name=='rename' and not getattr(ctx,'permissions',{}).get('files_create',True):raise PermissionError('Создание файла выключено')
        if group and not getattr(ctx,'permissions',{}).get(group,True):raise PermissionError('Инструмент выключен в разрешениях задачи: '+group)
        if item['permission']=='execute' and not ctx.allow_run:raise PermissionError('Выполнение кода не разрешено для этой задачи')
        if name in ('write','edit','delete','rename'):
            if not ctx.allow_write:raise PermissionError('Пользователь запросил только анализ')
            if any(str(args.get(k,'')).casefold() in ctx.protected for k in ('path','destination')):raise PermissionError('Пользователь запретил изменять этот файл')
        from .advanced import audit
        audit('before_tool',name,ctx.job_id)
        try:result=item['function'](ctx,**args)
        except Exception:
            audit('tool_error',name,ctx.job_id);raise
        audit('after_tool',name,ctx.job_id);ctx.save();return result


REGISTRY=Registry()
def register(name,description,args,permission='read'):
    def deco(fn):REGISTRY.register(name,description,args,fn,permission);return fn
    return deco


@register('list','Список текстовых файлов проекта',{})
def list_files(ctx):return ctx.work.files()
@register('read','Читать строки файла с номерами',{'path':'relative path','start':'line 1+','end':'up to start+299'})
def read(ctx,path,start=1,end=200):
    result=ctx.work.read(path,start,end);ctx.read.add(path.casefold())
    if int(start)==1 and not result['truncated']:ctx.full_read.add(path.casefold())
    return result
@register('search','Буквальный поиск по проекту',{'query':'literal text'})
def search(ctx,query):return ctx.work.search(query)
@register('symbols','Определения Python и JS/TS; импортирующие модули',{'name':'optional symbol'})
def symbols(ctx,name=''):
    index=ctx.work.index()
    return {'symbols':[s for s in index['symbols'] if not name or name.casefold() in s['name'].casefold()][:100],
            'references':ctx.work.search(name)[:30] if name else [],'imports':index['imports'][:60]}
@register('project_info','Зависимости, языки и правила проекта',{})
def project_info(ctx):
    data=ctx.work.index();return {k:v for k,v in data.items() if k not in ('symbols','imports','files')}


def check_name(ctx,path):
    aliases={f['path'].casefold():f['path'] for f in ctx.work.files()}
    if path.casefold() in aliases and aliases[path.casefold()]!=path:raise ValueError('Используй точный регистр: '+aliases[path.casefold()])


@register('write','Полный текст нового или полностью прочитанного файла',{'path':'relative path','content':'complete text'})
def write(ctx,path,content):
    p=ctx.work.path(path);check_name(ctx,path)
    if p.exists() and path.casefold() not in ctx.full_read:raise ValueError('Сначала прочитай файл целиком. Для большого файла используй edit.')
    validate(path,content);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content,encoding='utf-8');ctx.revision+=1;ctx.sync_edits()
    return {'prepared':path,'live_project_changed':False}
@register('edit','Точно заменить уникальный фрагмент прочитанного файла',{'path':'relative path','old':'exact text','new':'replacement'})
def edit(ctx,path,old,new):
    if path.casefold() not in ctx.read:raise ValueError('Сначала прочитай нужные строки')
    p=ctx.work.path(path);check_name(ctx,path);text=p.read_text(encoding='utf-8-sig')
    if not isinstance(old,str) or not old or text.count(old)!=1:raise ValueError('Фрагмент должен встречаться ровно один раз')
    value=text.replace(old,new,1);validate(path,value);p.write_text(value,encoding='utf-8');ctx.revision+=1;ctx.sync_edits()
    return {'edited':path,'live_project_changed':False}
@register('delete','Предложить удаление прочитанного файла',{'path':'relative path'})
def delete(ctx,path):
    if path.casefold() not in ctx.read:raise ValueError('Сначала прочитай удаляемый файл')
    ctx.work.path(path).unlink();ctx.revision+=1;ctx.sync_edits();return {'pending_delete':path,'live_project_changed':False}
@register('rename','Предложить переименование прочитанного файла',{'path':'old relative path','destination':'new relative path'})
def rename(ctx,path,destination):
    if path.casefold() not in ctx.read:raise ValueError('Сначала прочитай файл')
    source=ctx.work.path(path);target=ctx.work.path(destination);check_name(ctx,destination)
    if target.exists():raise ValueError('Целевой файл уже существует')
    validate(destination,source.read_text(encoding='utf-8-sig'));target.parent.mkdir(parents=True,exist_ok=True);source.rename(target);ctx.revision+=1;ctx.sync_edits()
    return {'rename':[path,destination],'live_project_changed':False}
@register('git','Git status/diff/log/branches только для рабочей копии',{'operation':'status|diff|log|branches','path':'optional'})
def git(ctx,operation='status',path=None):return git_tools.inspect(ctx.work.root,operation,path)
@register('git_commit','Локальный коммит подготовленных правок в рабочей копии',{'message':'short message'})
def git_commit(ctx,message):return git_tools.commit(ctx.work.root,list(ctx.edits),message)
@register('plan','Обновить краткий план и статус шагов',{'steps':'list of strings or {text,status}'})
def plan(ctx,steps):
    if not isinstance(steps,list) or len(steps)>12:raise ValueError('План: до 12 шагов')
    ctx.plan=[{'text':str(s.get('text',''))[:200],'status':str(s.get('status','pending'))[:30]} if isinstance(s,dict) else {'text':str(s)[:200],'status':'pending'} for s in steps]
    ctx.emit('plan',{'steps':ctx.plan});return ctx.plan
@register('test','Проверка рабочей копии фиксированным профилем',{'profile':'python-unittest|python-pytest|python-syntax|node-test|package-test|typescript'},permission='execute')
def test(ctx,profile='python-unittest'):
    ctx.emit('test_started',{'profile':profile,'backend':ctx.backend})
    result=test_profile(profile,ctx.work.root,ctx.allow_run,ctx.cancel,ctx.backend,timeout=90)
    ctx.sync_edits();ctx.emit('test_result',{'profile':profile,**result});return result
@register('process_start','Запустить локальный сервер рабочей копии',{'profile':'python-http|npm-dev'},permission='execute')
def process_start(ctx,profile='python-http'):
    if ctx.backend!='native':raise ValueError('Серверы поддерживаются только для доверенного native-кода')
    if len(ctx.processes)>=2:raise ValueError('Лимит: два сервера на задачу')
    cap=capabilities()
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    if profile=='python-http':args=[sys.executable,'-m','http.server',str(port),'--bind','127.0.0.1']
    elif profile=='npm-dev' and cap['node'] and cap['npm']:args=[cap['node'],cap['npm'],'run','dev','--','--host','127.0.0.1','--port',str(port)]
    else:raise ValueError('Профиль сервера недоступен')
    pid=str(len(ctx.processes)+1);ctx.processes[pid]=Managed(args,ctx.work.root,seconds=300)
    return {'process_id':pid,'url':f'http://127.0.0.1:{port}','expires':'end of task or 300 seconds'}
@register('process_status','Статус и ограниченный вывод сервера',{'process_id':'task-local id'})
def process_status(ctx,process_id):
    proc=ctx.processes[str(process_id)]
    if time.monotonic()-proc.started>300:proc.reason='timeout';proc.close()
    return proc.status()
@register('process_stop','Остановить свой сервер',{'process_id':'task-local id'})
def process_stop(ctx,process_id):
    proc=ctx.processes.pop(str(process_id));proc.close();return {'stopped':process_id}
@register('browser_inspect','Снимок и ошибки локальной страницы сервера этой задачи',{'url':'local task server URL'},permission='execute')
def browser_inspect(ctx,url):
    from urllib.parse import urlsplit
    p=urlsplit(url);ports=[]
    for proc in ctx.processes.values():
        for a in proc.argv:
            if a.isdigit():ports.append(int(a))
    if p.scheme!='http' or p.hostname!='127.0.0.1' or p.port not in ports:raise ValueError('Открывать можно только сервер, запущенный этой задачей')
    cap=capabilities()
    if not cap['node'] or not cap['playwright'] or not cap['edge']:raise ValueError('Browser tooling не настроен')
    directory=STATE/'artifacts'/ctx.job_id;directory.mkdir(parents=True,exist_ok=True)
    result=run([cap['node'],str(CORE/'meta5/browser_probe.cjs'),cap['playwright'],cap['edge'],url,str(directory)],ctx.work.root,ctx.cancel,timeout=40)
    if result['status']!='passed' or not (directory/'browser.json').is_file():raise ValueError('Browser check failed ('+result['status']+'): '+result['output'][-2000:])
    data=read_json(directory/'browser.json',{});data['screenshot']='/agent40/tasks/'+ctx.job_id+'/artifacts/screenshot.png';ctx.emit('browser_result',data);return data


@register('environment_info','Зависимости и доступные средства проверки',{})
def environment_info(ctx):
    return {'tools':capabilities(),'manifests':ctx.work.index()['manifests'],
            'project_python':str(ctx.work.root/'.meta5/venv/Scripts/python.exe'),
            'installation_allowed':ctx.allow_install}
@register('prepare_environment','Создать окружение рабочей копии и установить зависимости по отдельному разрешению',{'language':'python|node'},permission='execute')
def prepare_environment(ctx,language='python'):
    if not ctx.allow_install:raise PermissionError('Скачивание зависимостей не разрешено для этой задачи')
    if ctx.backend!='native':raise ValueError('Подготовь контейнерный образ отдельно; автоматический выход из Docker запрещён')
    if language=='python':
        if getattr(sys,'frozen',False):raise ValueError('Для создания отдельного venv нужен установленный Python. Встроенный Core выполняет проверки, но не является дистрибутивом Python для venv.')
        folder=ctx.work.root/'.meta5/venv';folder.parent.mkdir(parents=True,exist_ok=True)
        result=run([sys.executable,'-m','venv',str(folder)],ctx.work.root,ctx.cancel,90)
        if result['exit_code']!=0:return result
        py=folder/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        args=[str(py),'-m','pip','install','--disable-pip-version-check','pytest']
        if (ctx.work.root/'requirements.txt').is_file():args+=['-r','requirements.txt']
        elif (ctx.work.root/'pyproject.toml').is_file():args+=['-e','.']
        result=run(args,ctx.work.root,ctx.cancel,180)
    elif language=='node':
        cap=capabilities()
        if not cap['node'] or not cap['npm']:raise ValueError('npm не настроен')
        if not (ctx.work.root/'package.json').is_file():raise ValueError('Нет package.json')
        result=run([cap['node'],cap['npm'],'install','--ignore-scripts','--no-audit','--no-fund'],ctx.work.root,ctx.cancel,180)
    else:raise ValueError('Выбери python или node')
    ctx.sync_edits();return result
