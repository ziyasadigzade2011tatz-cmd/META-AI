"""Sequential local cold/warm comparison, without touching user chats or weights."""
import argparse,json,sys,time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'studio/core'))
from meta5 import transport

def run(model,label):
    if not transport.COMPUTE.acquire(timeout=120):raise TimeoutError('Model queue busy')
    try:
        with httpx.Client(timeout=180,trust_env=False) as c:
            transport.prepare_model(c,model)
            if label=='cold':
                c.post(transport.BASE+'/api/generate',json={'model':model,'keep_alive':0}).raise_for_status()
            system=(ROOT/'studio/core/config/system.md').read_text('utf-8')
            started=time.monotonic();first=None;chars=0;metrics={}
            with c.stream('POST',transport.BASE+'/api/chat',json={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':'привет'}],
                'stream':True,'think':False,'keep_alive':'15m','options':{'num_ctx':4096,'num_predict':2000,'temperature':.3,'seed':42}}) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:continue
                    data=json.loads(line)
                    if data.get('error'):raise ValueError(data['error'])
                    content=data.get('message',{}).get('content','')
                    if content:
                        if first is None:first=time.monotonic()-started
                        chars+=len(content)
                    if data.get('done'):metrics={k:data.get(k) for k in ('load_duration','prompt_eval_duration','eval_count','eval_duration','done_reason')}
            result={'model':model,'run':label,'first_text_seconds':round(first,3) if first is not None else None,'total_seconds':round(time.monotonic()-started,3),'characters':chars,**metrics}
            resident=c.get(transport.BASE+'/api/ps').json().get('models',[])
            result['placement']=[{k:m.get(k) for k in ('name','size','size_vram','context_length')} for m in resident]
            return result
    finally:transport.COMPUTE.release()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',default='build/chat-speed.json');args=p.parse_args();rows=[]
    output=ROOT/args.out;output.parent.mkdir(parents=True,exist_ok=True)
    for model in ('qwen3.5:4b','qwen2.5:3b'):
        for label in ('cold','warm','warm_repeat'):
            try:row=run(model,label)
            except Exception as exc:row={'model':model,'run':label,'error':type(exc).__name__}
            rows.append(row);output.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(row),flush=True)
