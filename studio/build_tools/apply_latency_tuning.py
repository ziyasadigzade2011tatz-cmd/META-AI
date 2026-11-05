"""Deploy only the measured latency patch; never deploy unfinished Phase 11."""
import argparse,hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
repo=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(repo/'studio/core'))
from meta5.performance import choose_measured_model
from meta5.storage import atomic_json

OLD="        understanding=await asyncio.to_thread(normalize,last,'\\n'.join(users[-8:]),parse_local)"
NEW="        from .performance import simple_turn\n        parser=None if simple_turn(last) else parse_local\n        understanding=await asyncio.to_thread(normalize,last,'\\n'.join(users[-8:]),parser)"
def text(path):return path.read_text('utf-8').replace('\r\n','\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def apply(runtime,configure=False):
    runtime=runtime.resolve();core=runtime/'_internal/core'
    if not (runtime/'META-Next.exe').is_file() or not (core/'meta5/dialogue.py').is_file():raise ValueError('Existing Desktop project required')
    transport_path=core/'meta5/transport.py';dialogue=core/'meta5/dialogue.py'
    before=text(transport_path)
    baseline=subprocess.check_output(['git','show','phase10-complete:studio/core/meta5/transport.py'],cwd=repo).decode('utf-8').replace('\r\n','\n')
    source=text(repo/'studio/core/meta5/transport.py')
    if before not in (baseline,source):raise ValueError('Transport differs from verified baseline; refusing overwrite')
    old=text(dialogue)
    if OLD in old and old.count(OLD)==1:patched=old.replace(OLD,NEW)
    elif NEW in old:patched=old
    else:raise ValueError('Dialogue patch context differs; refusing overwrite')
    # Validate everything before any mutation.
    compile(source,str(transport_path),'exec');compile(patched,str(dialogue),'exec')
    protected=[runtime/'META-Next.exe',*sorted((runtime/'_internal/frontend').rglob('*'))]
    protected={str(p):sha(p) for p in protected if p.is_file()}
    writes={transport_path:source,dialogue:patched,core/'meta5/performance.py':text(repo/'studio/core/meta5/performance.py'),core/'config/performance.json':text(repo/'studio/core/config/performance.json')}
    for path,value in writes.items():
        path.parent.mkdir(parents=True,exist_ok=True)
        atomic_text(path,value)
    changes={}
    if configure:
        state=Path(os.environ['LOCALAPPDATA'])/'META/core_state'
        report=json.loads((repo/'build/chat-speed.json').read_text('utf-8'))
        measured=json.loads((repo/'build/speed-baseline/latency-qwen3.5-4b.json').read_text('utf-8'))
        report.extend({**r,'model':r.get('model',{}).get('model')} for r in measured)
        selected,reason=choose_measured_model(report)
        path=state/'advanced.json';value=json.loads(path.read_text('utf-8'))
        fields={'chat_model':selected,'thinking':False,'deep_research':False}
        changes['before']={k:value.get(k) for k in fields};value.update(fields);atomic_json(path,value)
        path=state/'models.json';value=json.loads(path.read_text('utf-8'));value['chat']=selected;atomic_json(path,value)
        changes.update(after=fields,reason=reason)
    if any(sha(Path(p))!=digest for p,digest in protected.items()):raise RuntimeError('Protected runtime files changed')
    return {'runtime':str(runtime),'updated':[str(p.relative_to(core)) for p in writes],'protected_unchanged':len(protected),'settings':changes,'hashes':{str(p.relative_to(core)):sha(p) for p in writes}}

def atomic_text(path,value):
    fd,tmp=tempfile.mkstemp(prefix='.latency-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:f.write(value);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--configure',action='store_true');p.add_argument('--report',default='build/latency-deployment.json');args=p.parse_args()
    result=apply(Path(args.runtime),args.configure);out=repo/args.report;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
