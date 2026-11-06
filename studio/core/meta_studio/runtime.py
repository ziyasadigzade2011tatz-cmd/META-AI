"""Additive Desktop Full integration. No chat database migration or backup copies."""
import json
import marshal
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import uuid
import types
from urllib.parse import urlsplit,parse_qs
from . import VERSION

def free_port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

def boot(namespace):
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))
    data_home=Path(os.environ.get('META_STUDIO_HOME',str(Path(os.environ['LOCALAPPDATA'])/'META Profiles')))
    data_home.mkdir(parents=True,exist_ok=True)
    registry=data_home/'profiles.json'
    if registry.exists():profiles=json.loads(registry.read_text(encoding='utf-8'))
    else:profiles=[{'id':'default','name':'Основной профиль'}]
    profile=os.environ.get('META_PROFILE','default')
    if profile!='default' and not re.fullmatch('[a-f0-9]{32}',profile):raise ValueError('Неверный идентификатор профиля')
    os.environ.setdefault('META_DEFAULT_DATA_DIR',os.environ.get('META_DATA_DIR',str(Path(os.environ['LOCALAPPDATA'])/'META')))
    if not any(p['id']==profile for p in profiles):raise ValueError('Неизвестный профиль')
    if profile!='default':os.environ['META_DATA_DIR']=str(data_home/profile)
    # Existing default data directory is retained exactly.
    if '--core' in sys.argv:
        import uvicorn
        uvicorn.run('main:app',host='127.0.0.1',port=int(os.environ['META_CORE_PORT']))
        return
    code=marshal.loads((root/'studio_base.bin').read_bytes())
    def retitle(c):
        return c.replace(co_consts=tuple(retitle(x) if isinstance(x,types.CodeType) else
            'META Studio 5.3' if isinstance(x,str) and x in ('META — Desktop Preview','META — Next Desktop') else x for x in c.co_consts))
    code=retitle(code)
    # Only disable the original entry guard; module definitions remain unchanged.
    code=code.replace(co_consts=tuple('__studio_base__' if x=='__main__' else x for x in code.co_consts))
    exec(code,namespace)
    namespace['DEFAULT']['context']=4096
    legacy=namespace['legacy'];legacy.PORT=free_port()
    data=namespace['DATA'];config=json.loads((namespace['CONFIG']/'meta40_config.json').read_text(encoding='utf-8'))
    from .agent import Sessions
    sessions=Sessions(config['projects'],data/'studio_sessions')
    extra_file=data/'studio_preferences.json'
    from meta5.storage import read_json,atomic_json
    enhanced=read_json(extra_file,{'preset':'graphite','baseColor':'#222326','accent':'#d48a52','motion':True,'sidebarCollapsed':False})
    original=namespace['Handler']
    original_messages=legacy.core_messages
    def studio_messages(cid,prefs):
        # Transfer the web preference to Core without editing persisted user text.
        from meta5.understanding_config import OFFLINE_MARKER
        result=original_messages(cid,prefs)
        if not namespace['settings']()['web']:result=[*result,{'role':'system','content':OFFLINE_MARKER}]
        return result
    legacy.core_messages=studio_messages
    lock=threading.RLock()
    download={'status':'idle'}
    previews={}
    def pull_model(model):
        import httpx
        try:
            with httpx.Client(timeout=httpx.Timeout(60,connect=10),trust_env=False) as http:
                with http.stream('POST','http://127.0.0.1:11434/api/pull',json={'model':model,'stream':True}) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:continue
                        item=json.loads(line)
                        if item.get('error'):raise ValueError('Model download failed')
                        download.update(message=str(item.get('status','Загрузка'))[:100],completed=item.get('completed',0),total=item.get('total',0))
            download['status']='completed'
        except Exception:download.update(status='failed',message='Загрузка не завершена. Проверь Ollama, интернет и свободное место.')

    class StudioHandler(original):
        def body(self):
            if urlsplit(self.path).path!='/api/message/stream':return super().body()
            with namespace['SETTINGS_LOCK']:
                no_web=not namespace['settings']()['web']
                value=super().body()
                prefix='Без интернета. '
                if no_web and isinstance(value.get('text'),str) and value['text'].startswith(prefix):value['text']=value['text'][len(prefix):]
                return value
        def studio_guard(self,post=False):
            host=self.headers.get('Host','')
            if host!=f'127.0.0.1:{legacy.PORT}' or (post and self.headers.get('Origin')!=f'http://127.0.0.1:{legacy.PORT}'):
                self.json_response({'error':'Неверный источник'},403);return False
            return self.auth_guard()
        def do_GET(self):
            url=urlsplit(self.path)
            if not url.path.startswith('/studio/'):return super().do_GET()
            if not self.studio_guard():return
            query={k:v[0] for k,v in parse_qs(url.query).items()}
            try:
                from meta5.project import Project,digest
                from meta40.workspace import project_root
                path=url.path
                if path=='/studio/preview':
                    ident=query.get('id','')
                    if ident not in previews:raise ValueError('Предпросмотр устарел; открой его заново')
                    raw=previews[ident].encode('utf-8')
                    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
                    self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'; sandbox allow-scripts")
                    self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                    self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
                if path=='/studio/status':
                    profiles[:]=read_json(registry,profiles)
                    result={'version':VERSION,'profile':profile,'profiles':profiles,'preferences':enhanced,'projects_root':config['projects']}
                elif path=='/studio/download-status':result=dict(download)
                elif path=='/studio/role-models':
                    from meta5 import models,advanced
                    result={'profiles':models.profiles(),'settings':{**advanced.settings(),'understand_model':models.select('understand')[0]}}
                elif path=='/studio/projects':
                    base=Path(config['projects']);result={'projects':[p.name for p in sorted(base.iterdir()) if p.is_dir() and not p.name.startswith('.') and not p.is_symlink()]}
                elif path=='/studio/files':
                    p=Project(project_root(config['projects'],query.get('project','.')));result={'files':p.files()}
                elif path=='/studio/read':
                    p=Project(project_root(config['projects'],query['project']));file=p.path(query['path']);raw=file.read_bytes()
                    if len(raw)>1_000_000:raise ValueError('Файл больше 1 МБ')
                    result={'path':query['path'],'content':raw.decode('utf-8-sig'),'hash':digest(raw)}
                elif path=='/studio/search':
                    p=Project(project_root(config['projects'],query['project']));result={'matches':p.search(query['query'])}
                elif path=='/studio/sessions':result={'sessions':[{k:s.get(k) for k in ('id','project','task','status','created')} for s in sessions.history()]}
                elif path=='/studio/task':result=sessions.detail(query['id'])
                elif path=='/studio/models':
                    from urllib.request import urlopen
                    with urlopen('http://127.0.0.1:11434/api/tags',timeout=10) as response:obj=json.load(response)
                    result={'models':[x['name'] for x in obj.get('models',[])]}
                else:raise ValueError('Неизвестный маршрут')
                self.json_response(result)
            except (ValueError,KeyError,OSError,UnicodeError) as exc:self.json_response({'error':str(exc)[:500]},400)
        def do_POST(self):
            path=urlsplit(self.path).path
            if path=='/next/settings':
                # Same validation as Full, but no .backup.json copies.
                if not self.studio_guard(True):return
                try:
                    obj=namespace['validate']({**namespace['settings'](),**self.body()})
                    with namespace['SETTINGS_LOCK']:atomic_json(namespace['SETTINGS'],obj)
                    self.json_response(obj)
                except (ValueError,TypeError) as exc:self.json_response({'error':str(exc)},400)
                return
            if not path.startswith('/studio/'):return super().do_POST()
            if not self.studio_guard(True):return
            try:
                body=self.body()
                if path=='/studio/role-models':
                    import httpx
                    from meta5 import models,advanced
                    from meta5.native_tools import supports
                    with httpx.Client(timeout=10,trust_env=False) as http:
                        response=http.get('http://127.0.0.1:11434/api/tags');response.raise_for_status()
                        available={m['name'] for m in response.json().get('models',[])}
                    for role in ('fast','thinking','code','understand'):
                        if not isinstance(body.get(role),str) or body[role] not in available:raise ValueError('Выбери установленную модель для '+role)
                    if type(body.get('thinking_enabled')) is not bool:raise ValueError('Нужен режим Thinking')
                    if body['thinking_enabled'] and not supports(body['thinking'],'thinking'):raise ValueError('Модель не объявляет поддержку Thinking')
                    current=models.profiles();current.update(chat=body['fast'],quality=body['thinking'],code=body['code'],source='user_configured')
                    advanced.configure({'chat_model':body['fast'],'thinking_model':body['thinking'],'thinking':body['thinking_enabled']})
                    atomic_json(models.PROFILE_FILE,current)
                    role_file=namespace['CONFIG']/'models.json';roles=read_json(role_file,{})
                    roles['understand']=body['understand'];atomic_json(role_file,roles)
                    result={'saved':True}
                elif path=='/studio/task':
                    body['allow_web']=bool(namespace['settings']()['web']) and body.get('allow_web',True) is True
                    result=sessions.start(body)
                elif path=='/studio/preview':
                    html=body.get('html','')
                    if not isinstance(html,str) or len(html.encode('utf-8'))>1_500_000:raise ValueError('Предпросмотр больше 1,5 МБ')
                    ident=uuid.uuid4().hex
                    with lock:
                        if len(previews)>=8:previews.pop(next(iter(previews)))
                        previews[ident]=html
                    result={'url':'/studio/preview?id='+ident}
                elif path=='/studio/open-project':
                    from meta40.workspace import project_root
                    root=project_root(config['projects'],body['project'])
                    os.startfile(str(root));result={'opened':True}
                elif path=='/studio/install-ollama':
                    import webbrowser
                    webbrowser.open('https://ollama.com/download/windows');result={'opened':True}
                elif path=='/studio/download-model':
                    model=str(body.get('model','qwen3.5:4b'))
                    if model not in ('qwen3.5:4b','qwen3.5:9b','qwen2.5vl:3b','embeddinggemma:latest'):raise ValueError('Модель не входит в список загрузки')
                    if download['status']=='running':raise ValueError('Уже идёт загрузка модели')
                    download.update(status='running',model=model,message='Подключение к Ollama',completed=0,total=0)
                    threading.Thread(target=pull_model,args=(model,),daemon=True).start();result={'started':True}
                elif path=='/studio/cancel':result=sessions.stop(body['id'])
                elif path=='/studio/cancel-chat':
                    import httpx
                    session=str(body.get('session_id',''))
                    if not re.fullmatch('[A-Za-z0-9_:-]{1,100}',session):raise ValueError('Нет активного сеанса чата')
                    with httpx.Client(timeout=10,trust_env=False) as client:
                        try:
                            response=client.post(legacy.CORE_URL+'/agent40/dialogue/'+session+'/cancel',headers={'X-Meta40-Token':config['token']});response.raise_for_status();result=response.json()
                        except httpx.HTTPError:
                            self.json_response({'error':'Core не подтвердил остановку. Проверь его состояние.'},503);return
                elif path=='/studio/resume':result=sessions.resume(body['id'],body.get('model'))
                elif path=='/studio/apply':result=sessions.apply(body['id'])
                elif path=='/studio/run-tests':
                    from meta40.workspace import project_root
                    from .runner import run_tests
                    result=run_tests(project_root(config['projects'],body['project']),str(body.get('profile','python-unittest')),body.get('allow') is True)
                elif path=='/studio/save':
                    from meta40.workspace import project_root
                    from meta5.project import Project,digest,validate
                    project=Project(project_root(config['projects'],body['project']));file=project.path(body['path'])
                    raw=file.read_bytes() if file.exists() else None
                    if digest(raw)!=body.get('hash'):raise ValueError('Файл изменился. Открой его заново перед сохранением.')
                    validate(body['path'],body['content']);file.parent.mkdir(parents=True,exist_ok=True)
                    temp=file.with_name(file.name+'.meta-write-tmp');temp.write_text(body['content'],encoding='utf-8',newline='\n');temp.replace(file)
                    result={'saved':True,'hash':digest(file.read_bytes())}
                elif path=='/studio/preferences':
                    with lock:
                        for key in ('baseColor','accent'):
                            if key in body:
                                if not re.fullmatch('#[0-9a-fA-F]{6}',str(body[key])):raise ValueError('Неверный цвет')
                                enhanced[key]=body[key]
                        for key in ('motion','sidebarCollapsed'):
                            if key in body:enhanced[key]=bool(body[key])
                        if 'preset' in body:enhanced['preset']=str(body['preset'])[:30]
                        atomic_json(extra_file,enhanced)
                    result=enhanced
                elif path=='/studio/profile':
                    name=str(body.get('name','')).strip()
                    if not 1<=len(name)<=60:raise ValueError('Имя профиля: 1–60 символов')
                    with lock:
                        from .profiles import add_profile
                        rows,ident=add_profile(data_home,name);profiles[:]=rows
                    result={'profiles':profiles,'id':ident}
                elif path=='/studio/open-profile':
                    ident=str(body['id'])
                    profiles[:]=read_json(registry,profiles)
                    if not any(p['id']==ident for p in profiles):raise ValueError('Профиль не найден')
                    env=dict(os.environ,META_PROFILE=ident)
                    if ident=='default':env['META_DATA_DIR']=os.environ['META_DEFAULT_DATA_DIR']
                    for key in ('META_CORE_PORT','META5_STATE','META_CORE_CONFIG_DIR','META_PENDING_DIR','META_PROJECTS_DIR'):env.pop(key,None)
                    subprocess.Popen([sys.executable],env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    result={'opened':True}
                else:raise ValueError('Неизвестный маршрут')
                self.json_response(result)
            except (ValueError,KeyError,OSError,TypeError) as exc:self.json_response({'error':str(exc)[:500]},400)
    # Legacy streaming resolves its database helpers through type(self).__module__.
    # Retain that module when extending the handler, as the original shell does.
    StudioHandler.__module__=original.__module__
    namespace['Handler']=StudioHandler
    if '--studio-server' in sys.argv:
        from http.server import ThreadingHTTPServer
        legacy.connect().close();legacy.auth_db().close();legacy.start_core()
        atomic_json(data/'studio-ready.json',{'port':legacy.PORT,'core_url':legacy.CORE_URL,'version':VERSION})
        ThreadingHTTPServer(('127.0.0.1',legacy.PORT),StudioHandler).serve_forever()
        return
    namespace['main']()
