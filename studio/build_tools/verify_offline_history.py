"""Regression: offline preference must not alter stored user messages."""
import json,sys,urllib.request
from pathlib import Path
repo=Path(__file__).resolve().parents[2];sys.path.insert(0,str(repo/'studio/core'))
from meta5.compute import ComputeGate
base=repo/'build/phase10-offline';fixture=json.loads((base/'fixture.json').read_text('utf-8'))
url=fixture['url'];cookie='; '.join(c['name']+'='+c['value'] for c in fixture['test_cookie'])
def request(path,data=None):
    raw=json.dumps(data).encode() if data is not None else None
    return urllib.request.urlopen(urllib.request.Request(url+path,data=raw,headers={'Cookie':cookie,'Origin':url,'Content-Type':'application/json'}),timeout=90)
with request('/next/settings') as r:settings=json.load(r)
with request('/next/settings',{**settings,'web':False}) as r:json.load(r)
with request('/api/chats',{'title':'Synthetic raw-history check','mode':'chat'}) as r:cid=json.load(r)['id']
with request('/api/message/stream',{'conversation_id':cid,'text':'ghbdtn','model':'qwen3.5:4b','project':'.','attachments':[]}) as r:raw=r.read(500000).decode()
events=[]
for line in raw.splitlines():
    if line.startswith('data: '):
        try:events.append(json.loads(line[6:]))
        except ValueError:pass
assert any(e.get('type')=='token' and e.get('content') for e in events),'No model response'
assert not any(e.get('type') in ('error','model_error') for e in events),'Model error'
assert any(e.get('type')=='context' and e.get('data',{}).get('web_disabled') for e in events),'Offline preference lost'
assert not any(e.get('type')=='search_started' for e in events),'Offline search attempted'
with request('/api/chats/'+cid+'/messages') as r:messages=json.load(r)
if isinstance(messages,dict):messages=messages['messages']
assert [m['content'] for m in messages if m['role']=='user']==['ghbdtn'],'Original text altered'
with request('/api/message/stream',{'conversation_id':cid,'text':'/slang candidates','model':'qwen3.5:4b','project':'.','attachments':[]}) as r:command=r.read(500000).decode()
assert 'Кандидатов нет.' in command,'Offline command not recognized'
gate=ComputeGate();owned=gate.acquire(blocking=False)
assert owned,'Model gate was not released after reply'
gate.release()
result={'passed':True,'raw_history_preserved':True,'offline_preference_preserved':True,'offline_commands':True,'compute_gate_released':True}
(base/'offline-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
