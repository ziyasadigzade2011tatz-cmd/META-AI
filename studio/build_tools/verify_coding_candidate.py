"""One real model coding session on fresh synthetic data, with a total deadline."""
import json,os,sys,time
from pathlib import Path
repo=Path(__file__).resolve().parents[2];folder=repo/'build/code-upgrade';folder.mkdir(parents=True,exist_ok=True)
os.environ['META5_STATE']=str(folder/'agent-state');sys.path.insert(0,str(repo/'studio/core'))
from meta_studio.agent import Sessions
sessions=Sessions(folder/'projects',folder/'sessions')
obj=sessions.start({'task':'Создай небольшую страницу списка задач с самостоятельным названием. Нужны index.html и app.js, подключённые друг к другу. Поле ввода, добавление и удаление задачи. До 45 строк на файл. Без интернета.','model':'qwen3.5:4b','context':4096,'allow_web':False})
started=time.monotonic();last=None
while sessions.active and time.monotonic()-started<420:
    current=sessions.get(obj['id']);events=current.get('events',[])
    if events and events[-1]!=last:
        last=events[-1];print(json.dumps({'seconds':round(time.monotonic()-started,1),'event':last['type'],'action':last['data'].get('action'),'path':last['data'].get('path')},ensure_ascii=False),flush=True)
    time.sleep(1)
if sessions.active:
    sessions.stop(obj['id']);raise SystemExit('Real coding deadline; inspect saved synthetic session')
result=sessions.get(obj['id']);files=[p.name for p in Path(result['root']).iterdir() if p.is_file()]
report={'status':result['status'],'applied':result['applied'],'files':files,'seconds':round(time.monotonic()-started,2),'model':result['model'],'summary':result['summary'],'passed':result['applied'] and {'index.html','app.js'}<=set(files),'task_id':obj['id']}
(folder/'agent-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(report,ensure_ascii=False))
if not report['passed']:raise SystemExit(1)
