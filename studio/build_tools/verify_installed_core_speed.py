"""Check installed Core/settings with an ephemeral greeting; no Desktop chat writes."""
import json,os,socket,subprocess,time,urllib.request
from pathlib import Path

repo=Path(__file__).resolve().parents[2]
runtime=Path('C:/Users/Desktop/META_FULL_DESKTOP/META-Next')
data=Path(os.environ['LOCALAPPDATA'])/'META'
config=data/'core_config';state=data/'core_state'
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
env=dict(os.environ,META_CORE_PORT=str(port),META5_STATE=str(state),META_CORE_CONFIG_DIR=str(config),META_DATA_DIR=str(data),PYTHONDONTWRITEBYTECODE='1')
base=repo/'build/speed-installed';base.mkdir(parents=True,exist_ok=True)
token=json.loads((config/'meta40_config.json').read_text('utf-8'))['token']
url='http://127.0.0.1:'+str(port)
def request(path,value=None):
    return urllib.request.urlopen(urllib.request.Request(url+path,data=json.dumps(value).encode() if value is not None else None,headers={'Content-Type':'application/json','X-Meta40-Token':token}),timeout=180)

with (base/'core.log').open('w',encoding='utf-8') as log:
    process=subprocess.Popen([str(runtime/'META-Next.exe'),'--core'],cwd=runtime,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for attempt in range(60):
            if process.poll() is not None:raise RuntimeError('Installed Core exited')
            try:
                with request('/health') as response:health=json.load(response)
                break
            except OSError:time.sleep(.5)
        else:raise TimeoutError('Installed Core not ready')
        with request('/agent40/advanced/status') as response:settings=json.load(response)['settings']
        assert settings['thinking'] is False and settings['deep_research'] is False
        assert settings['chat_model']=='qwen3.5:4b'
        rows=[]
        for i in range(2):
            started=time.monotonic();first=None;count=0;errors=[];selected=None;searched=False
            with request('/agent40/dialogue/stream',{'session_id':'synthetic-speed-check-'+str(time.time_ns()),'messages':[{'role':'user','content':'привет'}],'model':'auto','context':8192,'temperature':.3}) as response:
                for raw in response:
                    line=raw.decode('utf-8').strip()
                    if not line.startswith('data: '):continue
                    event=json.loads(line[6:]);kind=event.get('type')
                    if kind=='token' and event.get('content'):
                        if first is None:first=time.monotonic()-started
                        count+=len(event['content'])
                    if kind=='model_selected':selected=event['data']['model']
                    if kind in ('error','model_error'):errors.append(kind)
                    if kind=='search_started':searched=True
            row={'first_text_seconds':round(first,3) if first is not None else None,'total_seconds':round(time.monotonic()-started,3),'characters':count,'selected':selected,'errors':errors,'searched':searched}
            assert count and not errors and selected=='qwen3.5:4b' and not searched,row
            rows.append(row);print(json.dumps(row),flush=True)
        result={'health':health,'settings':{k:settings[k] for k in ('chat_model','thinking','deep_research')},'context':8192,'chats_persisted':False,'results':rows}
        (base/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    finally:
        if process.poll() is None:process.terminate()
        try:process.wait(10)
        except subprocess.TimeoutExpired:process.kill();process.wait()
