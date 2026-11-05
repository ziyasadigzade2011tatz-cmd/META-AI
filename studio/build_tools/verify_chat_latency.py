"""Measure the complete Desktop HTTP bridge with synthetic chats only."""
import argparse,json,time,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('--model',default='auto');p.add_argument('--repeat',type=int,default=2);args=p.parse_args()
repo=Path(__file__).resolve().parents[2];base=repo/'build'/args.name;f=json.loads((base/'fixture.json').read_text('utf-8'));url=f['url'];cookie='; '.join(c['name']+'='+c['value'] for c in f['test_cookie'])
def request(path,body=None):
    return urllib.request.urlopen(urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Cookie':cookie,'Origin':url,'Content-Type':'application/json'}),timeout=180)
with request('/next/settings') as r:settings=json.load(r)
with request('/next/settings',{**settings,'context':8192,'web':True}) as r:json.load(r)
results=[]
for repeat in range(args.repeat):
    with request('/api/chats',{'title':'Synthetic latency measurement','mode':'chat'}) as r:cid=json.load(r)['id']
    start=time.monotonic();first=None;count=0;events=[];selection=None;errors=[]
    with request('/api/message/stream',{'conversation_id':cid,'text':'привет','model':args.model,'project':'.','attachments':[]}) as response:
        for raw in response:
            line=raw.decode('utf-8').strip()
            if not line.startswith('data: '):continue
            e=json.loads(line[6:]);events.append(e.get('type'))
            if e.get('type')=='model_selected':selection=e.get('data')
            if e.get('type') in ('error','model_error'):errors.append(e.get('type'))
            if e.get('type')=='token' and e.get('content'):
                if first is None:first=time.monotonic()-start
                count+=len(e['content'])
    row={'repeat':repeat,'requested_model':args.model,'model':selection,'first_text_seconds':round(first,3) if first is not None else None,'total_seconds':round(time.monotonic()-start,3),'characters':count,'errors':errors,'searched':any(e=='search_started' for e in events)}
    results.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    (base/('latency-'+args.model.replace(':','-')+'.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not count or errors:raise SystemExit('Synthetic chat failed')
