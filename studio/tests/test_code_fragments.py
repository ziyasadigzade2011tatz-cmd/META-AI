import json,sys,tempfile,time,unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta_studio.agent import Sessions,check_files,verified_summary
from meta_studio.fragments import IncompleteAction,recover,string_prefix,append_without_repeat,python_checkpoint
from meta_studio.coding_languages import guidance,css_structure,reference
from meta_studio.agent_context import compact
from meta5.project import digest,Project

def action(name,**args):return json.dumps({'action':name,'args':args})
def wait(s):
    deadline=time.monotonic()+8
    while s.active and time.monotonic()<deadline:time.sleep(.01)
    if s.active:raise AssertionError('worker did not finish')

class FragmentTests(unittest.TestCase):
    def test_decode_escapes_without_inventing_incomplete_escape(self):
        self.assertEqual(string_prefix('hello\\n\\u0410\\u04'),'hello\nА')
        self.assertEqual(string_prefix('abc\\'),'abc')
        self.assertIsNone(string_prefix('abc\\q'))
        self.assertEqual(string_prefix('\\uD83D'),'')
    def test_recovery_requires_valid_tool_prefix(self):
        for value in ('{"action":"shell","args":{"path":"a.py","content":"x',
                      '{"action":"write","content":"x',
                      '{"action":"append","args":{"path":"a.py","content":"x'):
            self.assertIsNone(recover(value))
        value=recover('{"action":"write","args":{"path":"a.py","content":"a=1\\n')
        self.assertEqual(value['args']['content'],'a=1\n');self.assertFalse(value['args']['complete'])
    def test_checkpoint_and_overlapping_append(self):
        self.assertEqual(python_checkpoint('','import re\n\ndef f():\n    return ('),'import re\n\n')
        old='intro\n'+'line content already saved\n'*3
        self.assertEqual(append_without_repeat(old,'line content already saved\n'*2+'NEW','a.txt'),old+'NEW')
        with self.assertRaises(ValueError):append_without_repeat('def f():\n    return 1\n','def f():\n    return 2\n','a.py')
    def test_truncated_python_resumes_and_cannot_finish_before_append(self):
        with tempfile.TemporaryDirectory() as d:
            count=0;observations=[]
            def client(messages):
                nonlocal count
                count+=1;observations.append(messages[-1]['content'])
                if count==1:raise IncompleteAction('{"action":"write","args":{"path":"main.py","content":"def add(a, b):\\n    return a +','fixture length')
                if count==2:return action('finish',summary='not ready')
                if count==3:return action('check')
                if count==4:return action('append',path='main.py',sha256=digest(b'def add(a, b):\n    return a +'),content=' b\n',complete=True)
                if count==5:return action('check')
                return action('finish',summary='done')
            s=Sessions(Path(d)/'p',Path(d)/'s',client=client);obj=s.start({'task':'Создай функцию на Python'});wait(s);result=s.get(obj['id'])
            self.assertEqual(result['status'],'completed');self.assertFalse(result['incomplete_files'])
            self.assertEqual((Path(result['root'])/'main.py').read_text('utf-8'),'def add(a, b):\n    return a + b\n')
            self.assertTrue(any('Заверши файлы' in text for text in observations));self.assertTrue(any(e['type']=='check' and any(c['status']=='failed' for c in e['data']['checks']) for e in result['events']))
    def test_append_hash_prevents_duplicate_retry(self):
        with tempfile.TemporaryDirectory() as d:
            values=iter([action('write',path='a.py',content='x=1\n'),action('append',path='a.py',sha256='0'*64,content='x=2\n',complete=True),action('check'),action('finish')])
            s=Sessions(Path(d)/'p',Path(d)/'s',client=lambda m:next(values));o=s.start({'task':'Создай программу на Python'});wait(s);r=s.get(o['id'])
            self.assertEqual(r['status'],'completed');self.assertEqual(r['edits']['a.py'],'x=1\n')
            self.assertTrue(any('sha256' in e.get('data',{}).get('error','') for e in r['events']))
    def test_incomplete_draft_survives_worker_failure_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            count=0
            def client(m):
                nonlocal count
                count+=1
                if count==1:raise IncompleteAction('{"action":"write","args":{"path":"a.py","content":"x = (','fixture')
                raise RuntimeError('fixture restart')
            s=Sessions(Path(d)/'p',Path(d)/'s',client=client);o=s.start({'task':'Создай программу на Python'});wait(s);r=s.get(o['id'])
            self.assertEqual(r['incomplete_files'],['a.py']);self.assertFalse((Path(r['root'])/'a.py').exists())
            values=iter([action('append',path='a.py',sha256=digest(b'x = ('),content='1)\n',complete=True),action('check'),action('finish')])
            next_s=Sessions(Path(d)/'p',Path(d)/'s',client=lambda m:next(values));next_s.resume(o['id']);wait(next_s)
            self.assertEqual(next_s.get(o['id'])['status'],'completed')
    def test_recovered_path_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            s=Sessions(Path(d)/'p',Path(d)/'s',client=lambda m:(_ for _ in ()).throw(IncompleteAction('{"action":"write","args":{"path":"../../outside.py","content":"x=1','fixture')))
            o=s.start({'task':'Создай программу'});wait(s);self.assertFalse(s.get(o['id'])['edits']);self.assertFalse((Path(d)/'outside.py').exists())
    def test_language_profiles_selected_without_web_bias(self):
        self.assertEqual(guidance('Напиши обработчик на C#')['languages'],['csharp'])
        self.assertEqual(guidance('Исправь обработчик', ['main.py'])['languages'],['python'])
        self.assertEqual(set(guidance('Сделай лендинг')['languages']),{'javascript','css'})
        self.assertEqual(guidance('Расскажи о погоде')['languages'],[])
        self.assertEqual(guidance('Улучши стиль Python-кода')['languages'],['python'])
        self.assertEqual(guidance('Не сайт, а консольная программа C#')['languages'],['csharp'])
    def test_explicit_resume_recovers_entire_legacy_preview(self):
        with tempfile.TemporaryDirectory() as d:
            s=Sessions(Path(d)/'p',Path(d)/'s',client=lambda m:(_ for _ in ()).throw(RuntimeError('fixture')))
            o=s.start({'task':'Создай программу на Python'});wait(s);r=s.get(o['id'])
            r.update(progress={'action':'write','path':'a.py','code_preview':'x = (','characters':99})
            s.path(o['id']).write_text(json.dumps(r),encoding='utf-8')
            values=iter([action('append',path='a.py',sha256=digest(b'x = ('),content='1)\n',complete=True),action('check'),action('finish')])
            s.client=lambda m:next(values);s.resume(o['id']);wait(s)
            self.assertEqual(s.get(o['id'])['status'],'completed');self.assertEqual((Path(r['root'])/'a.py').read_text('utf-8'),'x = (1)\n')
    def test_css_comments_strings_and_broken_blocks(self):
        self.assertEqual(css_structure('a{content:"}";background:url("x(y)");/* } */}')['status'],'passed')
        self.assertEqual(css_structure('a{color:red;')['status'],'failed')
        self.assertEqual(check_files({'main.csproj':'<Project>'})[0]['status'],'failed')
        self.assertEqual(check_files({'main.csproj':'<Project Sdk="Microsoft.NET.Sdk" />'})[0]['status'],'passed')
    def test_local_reference_is_selected_and_path_is_allowlisted(self):
        self.assertIn('AbortController',reference('javascript','async отмена')['text'])
        for language in ('python','javascript','css','csharp','cpp'):
            self.assertTrue(reference(language)['reference'].startswith('https://'))
        with self.assertRaises(ValueError):reference('../../secrets')
    def test_source_formats_can_be_created(self):
        with tempfile.TemporaryDirectory() as d:
            p=Project(d)
            for name in ('app.csproj','a.hpp','a.cxx','script.cjs','drawing.svg'):self.assertEqual(p.path(name).parent,Path(d))
    def test_summary_does_not_repeat_unverified_test_claim(self):
        result=verified_summary('Создана функция. Добавлены unittest. Все тесты прошли.',{'main.py':'x=1'},[{'status':'passed'}])
        self.assertNotIn('Все тесты прошли',result);self.assertNotIn('Добавлены unittest',result)
        self.assertIn('тесты приложения не запускались',result);self.assertIn('Создана функция',result)
    def test_initial_worker_failure_releases_active_task(self):
        with tempfile.TemporaryDirectory() as d:
            s=Sessions(Path(d)/'p',Path(d)/'s',client=lambda m:None)
            with patch('meta_studio.agent.Project',side_effect=ValueError('fixture missing root')):
                o=s.start({'task':'Создай программу'});wait(s)
            self.assertEqual(s.get(o['id'])['status'],'failed');self.assertNotIn(o['id'],s.cancel)
    def test_compaction_keeps_goal_and_latest_checkpoint(self):
        messages=[{'role':'system','content':'SYSTEM_POLICY'},{'role':'user','content':json.dumps({'task':'USER_GOAL','brief':{'original_task':'USER_GOAL','goal':'USER_GOAL'}})}]
        for i in range(12):messages.extend([{'role':'assistant','content':action('write',path='a.txt',content='x'*4000)},{'role':'user','content':'TOOL_RESULT '+str(i)}])
        result=compact(messages,4096)
        self.assertIn('USER_GOAL',result[1]['content']);self.assertEqual(result[0]['content'],'SYSTEM_POLICY');self.assertEqual(result[-1]['content'],'TOOL_RESULT 11')
        self.assertLess(sum(len(m['content']) for m in result),8192)

if __name__=='__main__':unittest.main()
