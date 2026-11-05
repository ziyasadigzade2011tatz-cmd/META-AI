"""Optional local services: project memory, embeddings, skills, plans and scheduled analysis."""
import hashlib,json,math,re,sqlite3,time,uuid,threading
from contextlib import closing
from pathlib import Path
import httpx
from .storage import STATE,atomic_json,read_json
from . import transport,models
DEFAULT={'semantic_memory':False,'embed_model':'embeddinggemma:latest','thinking':False,'thinking_model':'qwen3.5:4b','chat_model':'','deep_research':False,'schedules_enabled':False,'mcp_servers':{},'blocked_domains':['t.me','telegram.me'],'hooks':True}
LOCK=threading.RLock()
def settings():return {**DEFAULT,**read_json(STATE/'advanced.json',{})}
def configure(value):
 if not isinstance(value,dict) or set(value)-set(DEFAULT):raise ValueError('Unknown settings')
 out=settings()
 for key,val in value.items():
  if isinstance(DEFAULT[key],bool) and type(val) is not bool:raise ValueError('Expected boolean: '+key)
  if key.endswith('_model') and (not isinstance(val,str) or (val and not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}',val))):raise ValueError('Invalid model')
  if key=='blocked_domains' and (not isinstance(val,list) or len(val)>100 or any(not isinstance(d,str) or not re.fullmatch(r'[A-Za-z0-9.-]{1,200}',d) for d in val)):raise ValueError('Invalid domains')
  if key=='mcp_servers':
   if not isinstance(val,dict) or len(val)>8:raise ValueError('Up to eight MCP servers')
   from .mcp_client import validate_server
   for name,server in val.items():validate_server(name,server)
  out[key]=val
 atomic_json(STATE/'advanced.json',out);return out

def scope(project):
 import os
 from .storage import CORE
 path=Path(project)
 if not path.is_absolute():
  config=read_json(Path(os.environ.get('META_CORE_CONFIG_DIR',str(CORE)))/'meta40_config.json',{})
  path=Path(config.get('projects',os.environ.get('META_PROJECTS_DIR',str(STATE/'projects'))))/path
 return hashlib.sha256(str(path.resolve()).casefold().encode()).hexdigest()
def note_path(project):return STATE/'project_notes'/(scope(project)+'.json')
def notes(project):return read_json(note_path(project),{'text':'','updated':None})
def save_notes(project,text):
 if not isinstance(text,str) or len(text)>16000:raise ValueError('Notes up to 16000 characters')
 from .search_planner import search_plan
 # Notes remain local and are always labelled untrusted when injected.
 value={'text':text,'updated':time.time()};atomic_json(note_path(project),value);return value

def embed(texts,model=None):
 if not texts or len(texts)>100 or sum(len(t) for t in texts)>60000:raise ValueError('Embedding batch limit')
 model=model or settings()['embed_model']
 if not transport.COMPUTE.acquire(timeout=10):raise TimeoutError('Model queue busy')
 try:
  with httpx.Client(timeout=45,trust_env=False) as c:
   r=c.post(transport.BASE+'/api/embed',json={'model':model,'input':texts,'truncate':True,'keep_alive':'3m'});r.raise_for_status();vectors=r.json()['embeddings']
 finally:transport.COMPUTE.release()
 if len(vectors)!=len(texts) or any(not isinstance(v,list) or not v or any(type(n) not in (int,float) or not math.isfinite(n) for n in v) for v in vectors):raise ValueError('Invalid embeddings')
 return vectors

def semantic(query,items):
 if not settings()['semantic_memory'] or not items:return []
 selected=items[:60];texts=[str(i['value'])[:600] for i in selected];model=settings()['embed_model'];folder=STATE/'semantic';folder.mkdir(parents=True,exist_ok=True)
 with LOCK,closing(sqlite3.connect(folder/'vectors.sqlite')) as db,db:
  db.execute('create table if not exists vectors(key text primary key,value text)')
  vectors=[];missing=[]
  for i,text in enumerate(texts):
   key=hashlib.sha256((model+'\0'+text).encode()).hexdigest();row=db.execute('select value from vectors where key=?',(key,)).fetchone()
   vectors.append(json.loads(row[0]) if row else None)
   if not row:missing.append((i,key,text))
  if missing:
   new=embed([m[2] for m in missing],model)
   for (i,key,_),v in zip(missing,new):vectors[i]=v;db.execute('insert or replace into vectors values(?,?)',(key,json.dumps(v)))
 q=embed([query[:2000]],model)[0];den=math.sqrt(sum(n*n for n in q));rank=[]
 for item,v in zip(selected,vectors):
  if len(v)!=len(q):continue
  norm=math.sqrt(sum(n*n for n in v));score=sum(a*b for a,b in zip(q,v))/(den*norm) if den*norm else 0
  if score>.25:rank.append((score,item))
 return [item for _,item in sorted(rank,key=lambda p:-p[0])[:8]]

def project_context(project):
 value=notes(project)['text'][:6000]
 folder=STATE/'skills';skills=[]
 if folder.exists():
  for p in sorted(folder.glob('*.md'))[:8]:
   if not p.is_symlink() and p.stat().st_size<=12000:skills.append({'name':p.stem,'text':p.read_text('utf-8')[:2000]})
 return {'project_notes_untrusted':value,'skills_untrusted':skills}

def save_skill(name,text):
 if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}',name) or not isinstance(text,str) or len(text)>12000:raise ValueError('Invalid skill')
 path=STATE/'skills'/(name+'.md');path.parent.mkdir(parents=True,exist_ok=True)
 if path.is_symlink():raise ValueError('Linked skill')
 path.write_text(text,'utf-8');return {'name':name}

def audit(event,tool,job):
 if not settings()['hooks']:return
 # Declarative hook: bounded audit, no arbitrary shell commands or secret arguments.
 with LOCK:
  path=STATE/'tool_events.json';events=read_json(path,[]);events.append({'time':time.time(),'event':event,'tool':tool,'job':job});atomic_json(path,events[-500:])

def make_plan(task,project):
 if not isinstance(task,str) or not 3<=len(task)<=12000:raise ValueError('Invalid task')
 result=transport.complete(models.select('chat')[0],[{'role':'system','content':'Составь краткий план задачи. Только JSON {"steps":["шаг"]}. Не выполняй задачу. До восьми шагов.'},{'role':'user','content':task}],json_mode=True,timeout=45,options={'num_ctx':4096,'num_predict':500,'temperature':.1})
 value=json.loads(result['message']['content']);steps=value['steps']
 if not isinstance(steps,list) or not 1<=len(steps)<=8 or any(not isinstance(s,str) or not 1<=len(s)<=500 for s in steps):raise ValueError('Invalid plan')
 pid=uuid.uuid4().hex;record={'id':pid,'task':task,'project':project,'steps':steps,'status':'awaiting_approval'};atomic_json(STATE/'plans'/(pid+'.json'),record);return record

def read_plan(pid):
 if not re.fullmatch('[a-f0-9]{32}',pid):raise ValueError('Invalid plan id')
 value=read_json(STATE/'plans'/(pid+'.json'))
 if not value:raise ValueError('Plan not found')
 return value

def schedules():return read_json(STATE/'schedules.json',[])
def add_schedule(project,task,interval):
 if not isinstance(task,str) or not 3<=len(task)<=2000 or type(interval) is not int or not 300<=interval<=604800:raise ValueError('Analysis interval: 300..604800 seconds')
 with LOCK:
  rows=schedules()
  if len(rows)>=20:raise ValueError('Schedule limit')
  row={'id':uuid.uuid4().hex,'project':project,'task':task,'interval':interval,'next':time.time()+interval,'enabled':True};rows.append(row);atomic_json(STATE/'schedules.json',rows);return row

def tick(manager):
 if not settings()['schedules_enabled'] or manager.active:return
 with LOCK:
  rows=schedules()
  for row in rows:
   if row.get('enabled') and row['next']<=time.time():
    # Unattended jobs are analysis-only: no execution, writes, browser or Git changes.
    req={'task':'Только анализ. Не меняй файлы. Не запускай код. '+row['task'],'project':row['project'],'allow_tests':False,'allow_web':False,'permissions':{'files_read':True,'files_create':False,'files_write':False,'git':False,'terminal':False,'browser':False,'mcp':False},'max_steps':12,'seconds':300}
    try:row['last_job']=manager.start(req)['id'];row.pop('error',None)
    except (ValueError,OSError) as exc:row['error']=type(exc).__name__
    row['next']=time.time()+row['interval'];break
  atomic_json(STATE/'schedules.json',rows)

def start_scheduler(manager):
 def loop():
  while True:
   time.sleep(10)
   try:tick(manager)
   except Exception:pass
 threading.Thread(target=loop,daemon=True,name='META-scheduled-analysis').start()
