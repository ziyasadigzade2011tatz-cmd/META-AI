import http.cookiejar
import json
from pathlib import Path
import time
import urllib.request

repo=Path(__file__).resolve().parents[2];base=repo/'build/verification';fixture=json.loads((base/'fixture.json').read_text(encoding='utf-8'));url=fixture['url']
cookie='; '.join(c['name']+'='+c['value'] for c in fixture['test_cookie'])
def request(path,body=None):
    req=urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Origin':url,'Content-Type':'application/json','Cookie':cookie})
    with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)
obj=request('/studio/task',{'task':'Создай небольшой законченный адаптивный сайт кофейни Aurora: index.html, style.css, script.js. Меню напитков, кнопка переключения темы. Каждый файл до 60 строк. Нужны реальные файлы. Без интернета.','model':'qwen3.5:4b','context':4096})
print(json.dumps({'started':obj}),flush=True)
(base/'real-task.json').write_text(json.dumps(obj)+'\n',encoding='utf-8')
for _ in range(250):
    task=request('/studio/task?id='+obj['id'])
    if task['status']!='running':break
    time.sleep(4)
files=request('/studio/files?project='+obj['project'])
result={'status':task['status'],'applied':task['applied'],'project':obj['project'],'files':files['files'],
        'model':task['model'],'events':[{'type':e['type'],'action':e.get('data',{}).get('action')} for e in task['events']],
        'summary':task['summary'],'passed':task['applied'] and len(files['files'])>=3}
(base/'real-agent-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
