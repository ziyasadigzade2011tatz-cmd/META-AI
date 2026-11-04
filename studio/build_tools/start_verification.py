import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import http.cookiejar
import argparse

parser=argparse.ArgumentParser();parser.add_argument('--runtime');parser.add_argument('--name',default='verification');args=parser.parse_args()
repo=Path(__file__).resolve().parents[2];base=repo/'build'/args.name;base.mkdir(parents=True,exist_ok=True)
runtime=Path(args.runtime) if args.runtime else repo/'build/META-Next'
env=dict(os.environ,META_DATA_DIR=str(base/'data'),META_STUDIO_HOME=str(base/'profiles'),META_PROJECTS_DIR=str(base/'projects'))
for key in ('META_CORE_PORT','META_CORE_CONFIG_DIR','META5_STATE','META_PENDING_DIR'):env.pop(key,None)
log=(base/'server.log').open('w',encoding='utf-8')
ready_file=base/'data/studio-ready.json'
if ready_file.exists():ready_file.unlink()
proc=subprocess.Popen([str(runtime/'META-Next.exe'),'--studio-server'],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
(base/'pid.txt').write_text(str(proc.pid),encoding='utf-8')
for _ in range(100):
    if (base/'data/studio-ready.json').exists():break
    if proc.poll() is not None:raise SystemExit('Frozen server exited; inspect verification log')
    time.sleep(.5)
else:raise SystemExit('Frozen server readiness timed out')
ready=json.loads((base/'data/studio-ready.json').read_text(encoding='utf-8'));url='http://127.0.0.1:'+str(ready['port'])
cookies=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
def request(path,body=None):
    req=urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Origin':url,'Content-Type':'application/json'})
    with opener.open(req,timeout=15) as response:return json.load(response)
account=request('/api/account')
password='MetaStudioSyntheticFixture!2026'
request('/api/account/login' if account.get('configured') else '/api/account/register',{'name':'Fixture','password':password})
status=request('/studio/status');projects=request('/studio/projects');prefs=request('/studio/preferences',{'baseColor':'#242528','accent':'#dc955d','motion':True})
result={'url':url,'pid':proc.pid,'core_url':ready['core_url'],'status':status,'projects':projects,'preferences':prefs,
        'test_cookie':[{'name':c.name,'value':c.value,'domain':'127.0.0.1','path':'/','httpOnly':True,'sameSite':'Strict'} for c in cookies]}
(base/'fixture.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'url':url,'pid':proc.pid,'core_url':ready['core_url'],'version':status['version']}))
