"""Probe the installed Core on a free port; no Desktop chat is created."""
import json,os,socket,subprocess,time,urllib.request
from pathlib import Path

repo=Path(__file__).resolve().parents[2]
runtime=Path('C:/Users/user/Documents/GitHub/META-AI/local/app')
data=repo/'local/data';config=data/'core_config'
out=repo/'build/budget-installed';out.mkdir(parents=True,exist_ok=True)
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
env=dict(os.environ,META_CORE_PORT=str(port),META5_STATE=str(data/'core_state'),META_CORE_CONFIG_DIR=str(config),META_DATA_DIR=str(data),PYTHONDONTWRITEBYTECODE='1')
token=json.loads((config/'meta40_config.json').read_text('utf-8'))['token'];url='http://127.0.0.1:'+str(port)
def request(path,body=None):
    return urllib.request.urlopen(urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','X-Meta40-Token':token}),timeout=180)
with (out/'core.log').open('w',encoding='utf-8') as log:
    process=subprocess.Popen([str(runtime/'META-Next.exe'),'--core'],cwd=runtime,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(60):
            if process.poll() is not None:raise RuntimeError('Installed Core exited')
            try:
                with request('/health') as r:health=json.load(r)
                break
            except OSError:time.sleep(.5)
        else:raise TimeoutError('Installed Core not ready')
        assert health['version']=='5.5.0',health
        events=[];characters=0;started=time.monotonic()
        with request('/agent40/dialogue/stream',{'session_id':'synthetic-installed-budget-'+str(time.time_ns()),'messages':[{'role':'user','content':'привет'}],'model':'qwen3.5:4b','context':8192,'temperature':.3}) as r:
            for raw in r:
                if not raw.startswith(b'data:'):continue
                event=json.loads(raw[5:])
                if event['type']=='token':characters+=len(event.get('content',''))
                if event['type'] in ('context_usage','metrics','model_selected','model_error','error'):events.append(event)
        usage=next(e['data'] for e in events if e['type']=='context_usage')
        metrics=next(e['data'] for e in events if e['type']=='metrics')
        assert characters and not any(e['type'] in ('error','model_error') for e in events)
        assert usage['input_limit']==5500 and usage['output_limit']==2000 and usage['context_tokens']==8192
        assert usage['input_tokens']==metrics['prompt_eval_count']<=5500
        result={'health':health,'usage':usage,'metrics':metrics,'answer_characters':characters,'seconds':round(time.monotonic()-started,3),'desktop_chats_created':False}
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
    finally:
        if process.poll() is None:process.terminate()
        try:process.wait(10)
        except subprocess.TimeoutExpired:process.kill();process.wait()
