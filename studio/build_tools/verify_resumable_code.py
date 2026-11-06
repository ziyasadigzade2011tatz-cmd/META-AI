"""Real Ollama smoke test with deliberately small output portions, isolated data."""
import argparse,ast,json,os,sys,time
from pathlib import Path
repo=Path(__file__).resolve().parents[2];sys.path.insert(0,str(repo/'studio/core'))
parser=argparse.ArgumentParser();parser.add_argument('--model',default='qwen3.5:4b');args=parser.parse_args()
base=repo/'build/resumable-real';base.mkdir(parents=True,exist_ok=True)
config=base/'config';config.mkdir(exist_ok=True)
(config/'agent.json').write_text(json.dumps({'output_tokens':256,'step_seconds':180,'total_seconds':600,'max_steps':30}),encoding='utf-8')
os.environ['META_CORE_CONFIG_DIR']=str(config)
from meta_studio.agent import Sessions
s=Sessions(base/'projects',base/'sessions');started=time.monotonic()
o=s.start({'task':'Создай main.py с функциями slugify(text), summarize(numbers), unique(values) и CLI argparse. Нужны docstring, обработка пустого ввода и README.md с запуском. Стандартная библиотека Python, без интернета. Реальные файлы, без заглушек.','model':args.model,'context':4096,'allow_web':False})
while s.active:
    r=s.get(o['id']);elapsed=round(time.monotonic()-started,1)
    print(json.dumps({'seconds':elapsed,'status':r['status'],'files':list(r.get('edits',{})),'incomplete':r.get('incomplete_files',[]),'characters':r.get('progress',{}).get('characters',0)}),flush=True)
    if elapsed>650:s.stop(o['id'])
    time.sleep(10)
r=s.get(o['id']);events=r.get('events',[])
names=[]
try:names=[n.name for n in ast.parse(r.get('edits',{}).get('main.py','')).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
except SyntaxError:pass
report={'status':r['status'],'seconds':round(time.monotonic()-started,1),'model':args.model,'files':list(r.get('edits',{})),'functions':names,'generation_tokens':r.get('generation_tokens'),'incomplete_files':r.get('incomplete_files',[]),'fragment_recoveries':sum(e['type']=='recovery' and e['data'].get('reason')=='IncompleteAction' for e in events),'append_actions':sum(e['type']=='action' and e['data'].get('action')=='append' for e in events),'warnings':[e['data'].get('error','')[:180] for e in events if e['type']=='warning'],'summary':r.get('summary'),'task_id':o['id']}
(base/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)
if r['status']!='completed' or r.get('incomplete_files') or not report['append_actions'] or not report['fragment_recoveries'] or not {'slugify','summarize','unique'}.issubset(names) or len(names)!=len(set(names)):raise SystemExit(1)
