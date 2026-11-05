"""Opt-in real local coding smoke test; uses only isolated generated projects."""
import argparse,json,sys,time
from pathlib import Path
repo=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(repo/'studio/core'))
from meta_studio.agent import Sessions
base=repo/'build/activity-real';base.mkdir(parents=True,exist_ok=True)
sessions=Sessions(base/'projects',base/'sessions')
parser=argparse.ArgumentParser();parser.add_argument('--resume');args=parser.parse_args()
started=time.monotonic();first_preview=None;first_file=None
obj=sessions.resume(args.resume) if args.resume else sessions.start({'task':'Создай одностраничный лендинг Meta. Светлый бежевый фон, заголовок Meta, кнопка Скачать, справа окно приложения, ниже три карточки и футер. Чистые HTML CSS JS, без зависимостей. Сделай реальные файлы index.html, style.css, app.js. Без веб-поиска. Компактный код, не больше 40 строк на файл.','model':'qwen3.5:9b','context':4096,'allow_web':False})
while sessions.active:
    data=sessions.get(obj['id']);elapsed=round(time.monotonic()-started,1)
    if data.get('progress',{}).get('code_preview') and first_preview is None:first_preview=elapsed
    if data.get('edits') and first_file is None:first_file=elapsed
    print(json.dumps({'seconds':elapsed,'status':data['status'],'phase':data.get('progress',{}).get('phase'),'characters':data.get('progress',{}).get('characters',0),'files':list(data.get('edits',{}))}),flush=True)
    if elapsed>600:sessions.stop(obj['id'])
    time.sleep(10)
data=sessions.get(obj['id'])
report={'status':data['status'],'seconds':round(time.monotonic()-started,1),'resumed':bool(args.resume),'first_preview_seconds':first_preview,'first_file_seconds':first_file,'files':list(data.get('edits',{})),'summary':data.get('summary'),'model':'qwen3.5:9b','task_id':obj['id']}
(base/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
if data['status']!='completed' or 'index.html' not in data.get('edits',{}):raise SystemExit(1)
