import base64
import http.cookiejar
import json
from pathlib import Path
import urllib.error
import urllib.request

repo=Path(__file__).resolve().parents[2];base=repo/'build/verification';fixture=json.loads((base/'fixture.json').read_text(encoding='utf-8'));url=fixture['url']
cookie='; '.join(c['name']+'='+c['value'] for c in fixture['test_cookie'])
def request(path,body=None,origin=True):
    headers={'Content-Type':'application/json','Cookie':cookie}
    if origin:headers['Origin']=url
    req=urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    with urllib.request.urlopen(req,timeout=140) as response:return json.load(response)
project=base/'projects/service-fixture';project.mkdir(exist_ok=True)
(project/'test_example.py').write_text('import unittest\nclass Example(unittest.TestCase):\n def test_sum(self): self.assertEqual(2+2,4)\n',encoding='utf-8')
(project/'app.js').write_text('const answer = 42;\n',encoding='utf-8')
results={}
results['python_unittest']=request('/studio/run-tests',{'project':'service-fixture','profile':'python-unittest','allow':True})
results['javascript_syntax']=request('/studio/run-tests',{'project':'service-fixture','profile':'javascript-syntax','allow':True})
try:request('/studio/run-tests',{'project':'service-fixture','profile':'python-unittest','allow':False});results['consent_required']=False
except urllib.error.HTTPError as exc:results['consent_required']=exc.code==400
obj=request('/studio/read?project=service-fixture&path=app.js');request('/studio/save',{'project':'service-fixture','path':'app.js','hash':obj['hash'],'content':'const answer = 43;\n'})
try:request('/studio/save',{'project':'service-fixture','path':'app.js','hash':obj['hash'],'content':'const answer = 44;\n'});results['save_conflict_rejected']=False
except urllib.error.HTTPError as exc:results['save_conflict_rejected']=exc.code==400
try:request('/studio/preferences',{'baseColor':'#ffffff'},origin=False);results['origin_required']=False
except urllib.error.HTTPError as exc:results['origin_required']=exc.code==403
text='A local source about the blue lighthouse.'
extracted=request('/next/extract',{'name':'fixture.txt','data':base64.b64encode(text.encode()).decode()})
results['extract_text']=text in extracted.get('text','')
added=request('/next/knowledge',{'project':'service-fixture','name':'fixture.txt','text':extracted['text']})
listed=request('/next/knowledge?project=service-fixture');results['material_listing_shape']=type(listed).__name__
results['material_added']=bool(added)
results['passed']=all([results['python_unittest']['status']=='passed','Ran 1 test' in results['python_unittest']['output'],
    results['javascript_syntax']['status']=='passed',results['consent_required'],results['save_conflict_rejected'],results['origin_required'],results['extract_text'],results['material_added']])
(base/'services-result.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
