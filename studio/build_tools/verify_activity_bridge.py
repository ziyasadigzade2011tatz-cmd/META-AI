"""Verify installed bridge forwards Core session IDs and accepts cancellation."""
import json,urllib.request
from pathlib import Path
base=Path(__file__).resolve().parents[2]/'build/activity-ui'
fixture=json.loads((base/'fixture.json').read_text('utf-8'));url=fixture['url']
headers={'Content-Type':'application/json','Origin':url,'Cookie':'; '.join(c['name']+'='+c['value'] for c in fixture['test_cookie'])}
def post(path,body):return urllib.request.urlopen(urllib.request.Request(url+path,data=json.dumps(body).encode(),headers=headers),timeout=30)
with post('/api/chats',{'title':'Synthetic cancellation probe','mode':'chat'}) as response:chat=json.load(response)['id']
with post('/api/message/stream',{'conversation_id':chat,'text':'Объясни, почему меняется длина тени.','model':'qwen3.5:4b','project':'.','attachments':[]}) as response:
    session=None
    for line in response:
        if not line.startswith(b'data:'):continue
        event=json.loads(line[5:]);session=event.get('data',{}).get('session_id')
        if session:break
    if not session:raise RuntimeError('Core session ID was not forwarded by Desktop bridge')
    with post('/studio/cancel-chat',{'session_id':session}) as cancelled:result=json.load(cancelled)
    if not result.get('cancelled'):raise RuntimeError('Core did not acknowledge cancellation')
report={'real_bridge_forwards_session_id':True,'real_core_acknowledges_cancel':True,'scope':'Synthetic profile only; cancelled before generation'}
(base/'bridge-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
