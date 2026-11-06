import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
os.environ.setdefault('META5_STATE',str(Path(tempfile.gettempdir())/'meta-studio-unit-state'))
from meta_studio.agent import Sessions,check_files,slug

def call(action,**args):return json.dumps({'action':action,'args':args})

class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'projects').mkdir()
    def tearDown(self):self.temp.cleanup()
    def run_task(self,actions,request=None):
        it=iter(actions);s=Sessions(self.root/'projects',self.root/'state',client=lambda _:next(it))
        result=s.start(request or {'task':'Создай сайт для новой идеи'})
        deadline=time.monotonic()+5
        while s.active and time.monotonic()<deadline:time.sleep(.01)
        self.assertIsNone(s.active);return s,result,s.get(result['id'])
    def test_new_project_creates_real_files(self):
        s,r,d=self.run_task([call('plan',steps=['создать сайт']),call('write',path='index.html',content='<h1>Project</h1>'),call('check'),call('finish',summary='Создан сайт')])
        self.assertEqual(d['status'],'completed');self.assertTrue((self.root/'projects'/r['project']/'index.html').exists())
    def test_analysis_is_not_creation_success(self):
        _,_,d=self.run_task([call('finish',summary='Анализ проекта завершён')]*4)
        self.assertNotEqual(d['status'],'completed');self.assertFalse(d['applied'])
    def test_existing_project_requires_apply(self):
        folder=self.root/'projects/existing';folder.mkdir();file=folder/'main.py';file.write_text('x=1\n')
        s,r,d=self.run_task([call('read',path='main.py'),call('write',path='main.py',content='x=2\n'),call('check'),call('finish',summary='Изменено')],{'task':'Исправь код','project':'existing'})
        self.assertEqual(file.read_text(),'x=1\n');self.assertEqual(d['status'],'review');s.apply(r['id']);self.assertEqual(file.read_text(),'x=2\n')
    def test_apply_rejects_changed_source(self):
        folder=self.root/'projects/existing';folder.mkdir();file=folder/'main.py';file.write_text('x=1\n')
        s,r,_=self.run_task([call('read',path='main.py'),call('write',path='main.py',content='x=2\n'),call('check'),call('finish')],{'task':'Исправь код','project':'existing'})
        file.write_text('x=3\n')
        with self.assertRaises(ValueError):s.apply(r['id'])
        self.assertEqual(file.read_text(),'x=3\n')
    def test_traversal_is_rejected(self):
        _,_,d=self.run_task([call('write',path='../outside.py',content='x=1'),call('finish')])
        self.assertFalse((self.root/'projects/outside.py').exists());self.assertFalse(d['edits'])
    def test_readonly_cannot_write(self):
        folder=self.root/'projects/existing';folder.mkdir()
        _,_,d=self.run_task([call('write',path='main.py',content='x=1'),call('check'),call('finish')],{'task':'Только анализ, не меняй файлы','project':'existing'})
        self.assertFalse(d['edits']);self.assertFalse((folder/'main.py').exists())
    def test_finish_requires_check_after_changes(self):
        _,_,d=self.run_task([call('write',path='a.py',content='x=1'),call('finish'),call('check'),call('finish')])
        self.assertEqual(d['status'],'completed')
    def test_syntax_is_not_faked(self):
        checks=check_files({'bad.py':'def broken(', 'app.js':'const x = 1;'})
        self.assertEqual(checks[0]['status'],'failed');self.assertIn(checks[1]['status'],('passed','not_run'))
        self.assertIn('syntax',checks[1]['scope'].lower())
    def test_ascii_project_slug(self):self.assertRegex(slug('сделай сайт'),r'^[a-z0-9-]+$')
    def test_invalid_session_id(self):
        s=Sessions(self.root/'projects',self.root/'state')
        with self.assertRaises(ValueError):s.get('../secrets')
    def test_profile_updates_do_not_overwrite_previous_entries(self):
        from meta_studio.profiles import add_profile
        rows,first=add_profile(self.root,'Работа')
        rows,second=add_profile(self.root,'Личное')
        self.assertEqual(len(rows),3);self.assertNotEqual(first,second)

if __name__=='__main__':unittest.main()
