import json,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.task_brief import build
from meta5.web_code_checks import brief_check,javascript
from meta_studio.agent import Sessions,check_files,slug

REFERENCES=[('software','Claude Code'),('museum','Atlas Museum'),('science','Nova Lab'),('travel','Waypoint'),('music','Aria'),('garden','Greenhouse'),('transport','Transit Map'),('books','Open Shelf'),('health','Wellness Guide'),('finance','Budget Lens'),('food','Harvest Table'),('language','Lingua'),('photo','Prism Gallery'),('sports','Trail Club'),('history','Archive Hall'),('fashion','Studio Loom'),('architecture','Urban Forms'),('theatre','Curtain House'),('astronomy','Skywatch'),('craft','Clay Studio')]
def call(action,**args):return json.dumps({'action':action,'args':args})

class CodingReliabilityTests(unittest.TestCase):
    def test_twenty_references_are_not_product_names(self):
        for topic,name in REFERENCES:
            with self.subTest(topic=topic):
                task='Сделай сайт по подобию '+name+' (Web searching)'
                brief=build(task);self.assertEqual(brief['reference_targets'],[name]);self.assertTrue(brief['web_requested'])
                self.assertIsNone(brief['product_name']);self.assertNotIn('searching',brief['goal'].lower())
                self.assertTrue(brief_check('<title>'+name+'</title>',brief))
                self.assertFalse(brief_check('<title>Новый проект</title>',brief))
    def test_explicit_name_and_search_feature_preserved(self):
        brief=build('Создай сайт в стиле Aria, назови проект «My Studio» (Web searching)')
        self.assertEqual(brief['product_name'],'My Studio');self.assertFalse(brief_check('<title>My Studio</title>',brief))
        feature=build('Создай сайт с функцией веб-поиска')
        self.assertFalse(feature['web_requested']);self.assertIn('веб-поиска',feature['goal'])
        self.assertTrue(slug('Сайт по подобию «Aria»').startswith('website-'))
    def run_task(self,actions,task,web=True,researcher=None):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);root=Path(temporary.name)
        iterator=iter(actions);observations=[]
        def client(messages):observations.append(json.loads(json.dumps(messages)));return next(iterator)
        sessions=Sessions(root/'projects',root/'state',client=client,researcher=researcher)
        result=sessions.start({'task':task,'allow_web':web});deadline=time.monotonic()+10
        while sessions.active and time.monotonic()<deadline:time.sleep(.01)
        self.assertIsNone(sessions.active);return sessions,sessions.get(result['id']),observations
    def test_reference_research_precedes_generation_and_not_in_title(self):
        queries=[]
        def researcher(messages,emit):
            queries.append(messages[-1]['content'])
            return {'sources':[{'url':'https://docs.example.org/reference','opened':True,'chunks':[{'text':'Interface uses a sidebar and readable spacing.'}]}]}
        sessions,data,observations=self.run_task([call('write',path='index.html',content='<title>Clay Studio</title>'),call('check'),call('edit',path='index.html',old='Clay Studio',new='Independent Studio'),call('check'),call('finish',summary='Готово')],
            'Сделай сайт по подобию Clay Studio (Web searching)',researcher=researcher)
        self.assertEqual(data['status'],'completed');self.assertEqual(len(queries),1)
        self.assertTrue(any('REFERENCE_RESEARCH' in m['content'] for m in observations[0]))
        self.assertIn('Independent Studio',(Path(data['root'])/'index.html').read_text('utf-8'))
        self.assertTrue(any(e['type']=='check' and any(c['status']=='failed' for c in e['data']['checks']) for e in data['events']))
    def test_disabled_search_never_runs(self):
        def network(*args,**kwargs):self.fail('Network must not be called')
        _,data,_=self.run_task([], 'Сделай сайт в стиле Atlas Museum (Web searching)',False,network)
        self.assertNotEqual(data['status'],'completed');self.assertFalse(data['edits'])
    def test_negative_search_directive_allows_offline_creation(self):
        for directive in ('Без веб-поиска','Без веб поиска','Без поиска','Не используй веб-поиск'):
            brief=build('Создай страницу. '+directive)
            self.assertTrue(brief['web_forbidden']);self.assertFalse(brief['web_requested'])
        def network(*args,**kwargs):self.fail('Offline task must not access network')
        _,data,_=self.run_task([call('write',path='index.html',content='<title>Meta</title>'),call('check'),call('finish')], 'Создай страницу. Без веб-поиска.',False,network)
        self.assertEqual(data['status'],'completed')
    def test_unopened_search_results_do_not_count(self):
        _,data,_=self.run_task([], 'Сделай сайт по подобию Nova Lab (Web searching)',researcher=lambda *a,**k:{'sources':[{'url':'https://example.org','opened':False}]})
        self.assertFalse(data['applied']);self.assertNotEqual(data['status'],'completed')
    def test_draft_search_and_repeat_stop(self):
        _,data,observations=self.run_task([call('write',path='main.py',content='marker = 1\n'),call('search',query='marker'),call('check'),call('finish')],'Создай программу')
        self.assertTrue(any('marker = 1' in m['content'] and 'TOOL_RESULT' in m['content'] for m in observations[-1]))
        _,failed,_=self.run_task([call('unknown')]*4,'Создай программу')
        self.assertEqual(failed['status'],'paused');self.assertLess(len(failed['events']),15)
    def test_missing_web_assets_and_javascript_syntax(self):
        self.assertEqual(check_files({'index.html':'<script src="missing.js"></script>'})[0]['status'],'failed')
        self.assertEqual(check_files({'index.html':'<script src="app.js"></script>','app.js':'const x = 1;'})[0]['status'],'passed')
        result=javascript('const broken = ;')
        if result['status']=='not_run':self.skipTest('Node unavailable')
        self.assertEqual(result['status'],'failed');self.assertEqual(javascript('export const x = 1;')['status'],'passed')
    def test_malformed_response_can_recover(self):
        sessions,data,_=self.run_task(['broken json',call('write',path='main.py',content='x=1\n'),call('check'),call('finish')],'Создай программу')
        self.assertEqual(data['status'],'completed');self.assertFalse(sessions.cancel)
    def test_official_claim_requires_primary_domain(self):
        from meta5.search_ranking import rank
        sources=[{'url':'https://unverified.example.org','title':'Официальный сайт организации','snippet':'Официальный сайт организации'}]
        hits,rejected=rank([sources],'Найди официальный сайт организации')
        self.assertFalse(hits);self.assertTrue(any(r['reason']=='official_domain_not_verified' for r in rejected))

if __name__=='__main__':unittest.main()
