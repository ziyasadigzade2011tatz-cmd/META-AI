"""Verify a fresh self-development project through the packaged test runner."""
import json,re,urllib.request
from pathlib import Path
repo=Path(__file__).resolve().parents[2];base=repo/'build/extensions-ui'
f=json.loads((base/'fixture.json').read_text('utf-8'));ui=json.loads((base/'ui-result.json').read_text('utf-8'))
root=Path(f['status']['projects_root'])/ui['workspace_project']
assert (root/'core/config/search_domains.json').is_file()
(root/'tests/test_workspace_identity.py').write_text("import unittest\nfrom pathlib import Path\nimport meta_studio.agent\nclass Identity(unittest.TestCase):\n def test_workspace_source(self):\n  self.assertTrue(Path(meta_studio.agent.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]/'core'))\n",encoding='utf-8')
headers={'Origin':f['url'],'Content-Type':'application/json','Cookie':'; '.join(c['name']+'='+c['value'] for c in f['test_cookie'])}
body={'project':ui['workspace_project'],'profile':'python-unittest','allow':True}
with urllib.request.urlopen(urllib.request.Request(f['url']+'/studio/run-tests',data=json.dumps(body).encode(),headers=headers),timeout=180) as response:r=json.load(response)
match=re.search(r'Ran (\d+) tests',r.get('output',''))
report={'status':r['status'],'exit_code':r.get('exit_code'),'tests':int(match[1]) if match else None,'workspace_source_identity': 'test_workspace_source' in r.get('output',''),'output_tail':r.get('output','')[-1800:]}
(base/'self-tests.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
if r['status']!='passed':raise SystemExit(1)
