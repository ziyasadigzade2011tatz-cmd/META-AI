import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'core'))
from meta40.workspace import Workspace, project_root
from meta40.engine import run
from meta40.runner import run_tests
from meta40 import proposals
from meta40.api import install as install_api
from fastapi import FastAPI
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location('installer40', ROOT/'install_meta40.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def sequence(actions):
    iterator = iter(actions)
    return lambda messages: json.dumps(next(iterator))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='meta40-qa-')
        self.base = Path(self.temp.name)
        self.project = self.base/'projects'; self.project.mkdir()
        self.pending = self.base/'pending'; self.pending.mkdir()
        self.stubs = patch.dict(sys.modules, {
            'agent_tools':types.SimpleNamespace(WORKSPACE=self.project),
            'agent_pending':types.SimpleNamespace(STORE=self.pending)})
        self.stubs.start()

    def tearDown(self):
        self.stubs.stop()
        self.temp.cleanup()

    def test_path_boundaries_and_sensitive_files(self):
        ws = Workspace(self.project)
        for name in ('../x.py','C:/x.py','a\\b.py','/x.py','a/../b.py',
                     '.env','CON.py','foo:bar.py','secret.json','x./a.py','a//x.py'):
            with self.subTest(name=name), self.assertRaises(ValueError): ws.path(name)
        with self.assertRaises(ValueError): project_root(self.project, '../outside')

    def test_junction_denied(self):
        if os.name != 'nt': self.skipTest('Windows junction test')
        import subprocess
        outside = self.base/'outside'; outside.mkdir()
        junction = self.project/'linked'
        subprocess.run(['cmd','/c','mklink','/J',str(junction),str(outside)], check=True, capture_output=True)
        try:
            with self.assertRaises(ValueError): Workspace(self.project).path('linked/x.py')
            with self.assertRaises(ValueError): project_root(self.project,'linked/created',create=True)
            self.assertFalse((outside/'created').exists())
            self.assertEqual(Workspace(self.project).inventory(), {})
        finally: junction.rmdir()

    def test_snapshot_limits_and_exclusions(self):
        (self.project/'a.py').write_text('x=1\n')
        (self.project/'.env').write_text('PRIVATE')
        (self.project/'credentials.json').write_text('{}')
        (self.project/'huge.py').write_text(' '*20001)
        self.assertEqual(list(Workspace(self.project).inventory()), ['a.py'])

    def test_create_project_requires_optin_and_stays_inside_projects(self):
        with self.assertRaisesRegex(ValueError,'Создать папку'):
            project_root(self.project,'new_app')
        self.assertFalse((self.project/'new_app').exists())
        target=project_root(self.project,'new_app/src',create=True)
        self.assertEqual(target,(self.project/'new_app/src').resolve())
        self.assertTrue(target.is_dir())
        self.assertEqual(project_root(self.project,'new_app/src',create=True),target)
        for invalid in ('../outside','new/../../outside','C:/outside','new/.git/child'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                project_root(self.project,invalid,create=True)
        self.assertFalse((self.base/'outside').exists())
        self.assertFalse((self.project/'new').exists())
        (self.project/'occupied').write_text('x')
        with self.assertRaises(ValueError):project_root(self.project,'occupied/sub',create=True)

    def test_loop_repairs_tests_and_stages_without_writing(self):
        (self.project/'calc.py').write_text('def add(a,b): return a-b\n')
        original = (self.project/'calc.py').read_bytes()
        model = sequence([
            {'action':'read','path':'calc.py'},
            {'action':'write','path':'test_calc.py','content':'import unittest\nfrom calc import add\nclass TestAdd(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n'},
            {'action':'test','profile':'python-unittest'},
            {'action':'write','path':'calc.py','content':'def add(a,b): return a+b\n'},
            {'action':'test','profile':'python-unittest'},
            {'action':'finish','summary':'Исправлена сумма, тест пройден.'}])
        result = run(self.project,'Fix add',model,proposals.stage,lambda *a:None,allow_tests=True)
        self.assertEqual(result['status'],'pending')
        self.assertEqual([x['status'] for x in result['tests']], ['failed','passed'])
        self.assertTrue(result['tests'][0]['superseded_by_edits'])
        self.assertEqual((self.project/'calc.py').read_bytes(), original)
        pid = result['proposal']['id']
        self.assertIn('test_calc.py', proposals.preview(pid)['files'])
        self.assertEqual(proposals.approve(pid)['status'],'applied')
        self.assertEqual((self.project/'calc.py').read_text(), 'def add(a,b): return a+b\n')
        proposals.rollback(pid)
        self.assertEqual((self.project/'calc.py').read_bytes(), original)
        self.assertFalse((self.project/'test_calc.py').exists())

    def test_loop_limits_cancel_invalid_and_read_first(self):
        events = []
        result = run(self.project, 'task', sequence([{'action':'bogus'}]*3),
                     proposals.stage, lambda *a:events.append(a), max_steps=3)
        self.assertEqual(result['status'],'step_limit')
        self.assertEqual(len([e for e in events if e[0]=='tool_error']),3)
        event = threading.Event(); event.set()
        self.assertEqual(run(self.project,'task',lambda _:self.fail(),proposals.stage,
                             lambda *a:None,cancel=event)['status'],'cancelled')
        (self.project/'a.py').write_text('a=1')
        result = run(self.project,'task',sequence([{'action':'write','path':'a.py','content':'a=2'},
                     {'action':'finish','summary':'done'}]),proposals.stage,lambda *a:None)
        self.assertIsNone(result['proposal'])

    def test_stale_file_rejected_at_stage_and_approval(self):
        (self.project/'a.py').write_text('a=1')
        snap = Workspace(self.project).inventory()
        proposal = proposals.stage(self.project, {'a.py':'a=2'}, snap)
        (self.project/'a.py').write_text('a=3')
        with self.assertRaises(RuntimeError): proposals.preview(proposal['id'])
        with self.assertRaises(RuntimeError): proposals.approve(proposal['id'])
        with self.assertRaises(RuntimeError): proposals.stage(self.project, {'a.py':'a=2'},snap)

    def test_multifile_failure_rolls_back(self):
        (self.project/'a.py').write_text('a=1')
        snap = Workspace(self.project).inventory()
        proposal = proposals.stage(self.project, {'a.py':'a=2','nested/b.py':'b=1'},snap)
        real_replace = proposals.replace_bytes
        def fail_second(path, raw):
            if path.name == 'b.py': raise OSError('simulated disk failure')
            return real_replace(path, raw)
        with patch.object(proposals,'replace_bytes',side_effect=fail_second):
            with self.assertRaises(OSError): proposals.approve(proposal['id'])
        self.assertEqual((self.project/'a.py').read_text(),'a=1')
        self.assertFalse((self.project/'nested/b.py').exists())
        receipt = json.loads((self.pending/'meta40_receipts'/(proposal['id']+'.json')).read_text())
        self.assertEqual(receipt['status'],'rolled_back')

    def test_rollback_preserves_later_edits(self):
        p = proposals.stage(self.project, {'a.py':'a=2'}, {})
        proposals.approve(p['id'])
        (self.project/'a.py').write_text('a=3')
        with self.assertRaises(RuntimeError): proposals.rollback(p['id'])
        self.assertEqual((self.project/'a.py').read_text(),'a=3')

    def test_runner_optin_allowlist_no_tests_timeout_output_limit(self):
        cancel = threading.Event()
        with self.assertRaises(PermissionError): run_tests({}, {}, False, cancel)
        with self.assertRaises(ValueError): run_tests({}, {}, True,cancel,profile='cmd.exe')
        self.assertEqual(run_tests({}, {}, True,cancel)['exit_code'],5)
        slow = {'test_slow.py':b'import time\ntime.sleep(10)\n'}
        self.assertEqual(run_tests(slow,{},True,cancel,timeout=.25)['status'],'timeout')
        flood = {'test_flood.py':b'while True: print("x"*4096, flush=True)\n'}
        result = run_tests(flood,{},True,cancel,timeout=5)
        self.assertEqual(result['status'],'output_limit')
        self.assertLessEqual(len(result['output']),32000)

    def test_runner_cancels_and_kills_child_process_tree(self):
        cancel = threading.Event()
        marker = self.base/'escaped.txt'
        # A child would write outside the copy if supervision failed.
        child = 'import time,pathlib;time.sleep(2);pathlib.Path('+repr(str(marker))+').write_text("bad")'
        code = 'import subprocess,sys,time\nsubprocess.Popen([sys.executable,"-c",'+repr(child)+'])\ntime.sleep(10)\n'
        result = run_tests({'test_child.py':code.encode()},{},True,cancel,timeout=.4)
        self.assertEqual(result['status'],'timeout')
        time.sleep(2.1)
        self.assertFalse(marker.exists())
        cancel.set()
        self.assertEqual(run_tests({'test_wait.py':b'import time;time.sleep(10)'},{},True,cancel)['status'],'cancelled')

    def test_api_auth_validation_lifecycle_and_restart(self):
        core = self.base/'core';core.mkdir()
        (core/'meta40_config.json').write_text(json.dumps({'projects':str(self.project),'token':'test-token'}))
        app = FastAPI();install_api(app,core)
        headers={'X-Meta40-Token':'test-token'}
        with TestClient(app) as client:
            self.assertEqual(client.get('/agent40/status').status_code,401)
            self.assertEqual(client.post('/agent40/tasks',headers=headers,json={'task':'abc','max_steps':99}).status_code,422)
            self.assertEqual(client.post('/agent40/tasks',headers=headers,json={'task':'abc','allow_tests':True}).status_code,400)
            self.assertEqual(client.post('/agent40/tasks',headers=headers,json={'task':'abc','project':'../bad'}).status_code,400)
            def fake_model(*args,**kwargs):
                return sequence([{'action':'write','path':'hello.py','content':'print("hello")\n'},
                                 {'action':'finish','summary':'hello ready'}])
            with patch('meta40.api.Ollama',side_effect=fake_model):
                created=client.post('/agent40/tasks',headers=headers,json={'task':'create hello'})
                self.assertEqual(created.status_code,202)
                jid=created.json()['id']
                for _ in range(200):
                    data=client.get('/agent40/tasks/'+jid,headers=headers).json()
                    if data['status'] not in ('queued','running'): break
                    time.sleep(.01)
                self.assertEqual(data['status'],'pending')
                self.assertFalse((self.project/'hello.py').exists())
                self.assertEqual(client.get('/agent40/tasks',headers=headers).json()['tasks'][0]['id'],jid)
        from meta40.api import Manager
        interrupted = core/'meta40_state'/('f'*32+'.json')
        interrupted.write_text(json.dumps({'id':'f'*32,'status':'running'}))
        Manager({'projects':str(self.project)},core/'meta40_state')
        self.assertEqual(json.loads(interrupted.read_text())['status'],'interrupted')

    def installation_fixture(self):
        core=self.base/'install_core';desktop=self.base/'desktop'
        core.mkdir();(desktop/'assets').mkdir(parents=True)
        (core/'main.py').write_text('from fastapi import FastAPI\napp = FastAPI()\n')
        (core/'agent_tools.py').write_text('from pathlib import Path\nWORKSPACE = Path('+repr(str(self.project))+')\n')
        (core/'agent_pending.py').write_text('def proposal_preview(x): return x\ndef proposal_approve(x): return x\ndef proposal_reject(x): return x\n')
        (desktop/'meta_desktop.py').write_text('CORE_URL = "http://localhost"\ndef account_state(): return True\nclass Handler:\n    def authorized(self): return True\n    def do_GET(self):\n        pass\n    def do_POST(self):\n        pass\n')
        (desktop/'assets/app.js').write_text('// original\n')
        return core,desktop

    def test_api_single_task_and_cancel(self):
        from meta40.api import Manager, TaskRequest
        entered=threading.Event(); release=threading.Event()
        def blocked_model(messages):
            entered.set();release.wait(5)
            return '{"action":"finish","summary":"done"}'
        manager=Manager({'projects':str(self.project)},self.base/'state')
        with patch('meta40.api.Ollama',return_value=blocked_model):
            first=manager.start(TaskRequest(task='first task'))
            self.assertTrue(entered.wait(2))
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as exc: manager.start(TaskRequest(task='second task'))
            self.assertEqual(exc.exception.status_code,409)
            manager.cancel.set();release.set()
            for _ in range(200):
                if manager.get(first['id'])['status']=='cancelled':break
                time.sleep(.01)
            self.assertEqual(manager.get(first['id'])['status'],'cancelled')
            for _ in range(200):
                if manager.active is None:break
                time.sleep(.01)
            self.assertIsNone(manager.active)

    def test_desktop_proxy_rejects_untrusted_requests(self):
        import io
        spec=importlib.util.spec_from_file_location('proxy40',ROOT/'desktop/meta40_desktop.py')
        proxy=importlib.util.module_from_spec(spec);spec.loader.exec_module(proxy)
        class Handler:
            path='/api/meta40/tasks';command='POST'
            headers={'Host':'127.0.0.1:8767','Origin':'http://evil.example','Content-Length':'2'}
            rfile=io.BytesIO(b'{}')
            def authorized(self): return True
            def json_response(self,data,status=200): self.response=(data,status)
        h=Handler()
        self.assertTrue(proxy.handle(h,self.base,'http://127.0.0.1:8000',8767,True))
        self.assertEqual(h.response[1],403)
        h.headers={'Host':'evil.example','Origin':'http://127.0.0.1:8767'}
        proxy.handle(h,self.base,'http://127.0.0.1:8000',8767,True)
        self.assertEqual(h.response[1],403)
        h.headers={'Host':'127.0.0.1:8767','Origin':'http://127.0.0.1:8767'}
        proxy.handle(h,self.base,'http://127.0.0.1:8000',8767,False)
        self.assertEqual(h.response[1],403)
        h.path='/api/meta40/tasks/../../apply'
        proxy.handle(h,self.base,'http://127.0.0.1:8000',8767,True)
        self.assertEqual(h.response[1],404)

    def test_installer_failure_restores_originals(self):
        core,desktop=self.installation_fixture()
        originals={p:p.read_bytes() for root in (core,desktop) for p in root.rglob('*') if p.is_file()}
        real_write=installer.write
        def disk_failure(path,raw):
            if path==core/'meta40/engine.py':raise OSError('simulated install failure')
            real_write(path,raw)
        with patch.object(installer,'write',side_effect=disk_failure):
            with self.assertRaises(OSError):installer.install(core,desktop,self.project)
        for p,raw in originals.items():self.assertEqual(p.read_bytes(),raw)
        self.assertFalse((desktop/'meta40_desktop.py').exists())
        manifest=next((core/'meta40_backups').glob('*/manifest.json'))
        self.assertEqual(json.loads(manifest.read_text())['status'],'rolled_back')

    def test_patch401_preserves_legacy_ui_and_can_rollback(self):
        core,desktop=self.installation_fixture()
        installer.install(core,desktop,self.project)
        old_js=b'// original\n// META40_UI_BEGIN\n// old UI\n// META40_UI_END\n// trailing\n'
        (desktop/'assets/app.js').write_bytes(old_js)
        (core/'meta40/__init__.py').write_bytes(b'VERSION = "4.0.0"\n')
        previous={p:p.read_bytes() for p in [desktop/'assets/app.js',core/'meta40/__init__.py']}
        spec=importlib.util.spec_from_file_location('patch401',ROOT/'patch_meta401.py')
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'install_meta40':installer}):spec.loader.exec_module(module)
        module.apply(core,desktop,check=True)
        self.assertEqual((desktop/'assets/app.js').read_bytes(),old_js)
        module.apply(core,desktop)
        js=(desktop/'assets/app.js').read_text()
        self.assertTrue(js.startswith('// original\n'))
        self.assertTrue(js.endswith('// trailing\n'))
        self.assertIn('create_project:el(\'create\').checked',js)
        module.apply(core,desktop)
        manifests=list((core/'meta40_backups').glob('fix401_*/manifest.json'))
        self.assertEqual(len(manifests),1)
        installer.rollback(manifests[0],core,desktop)
        for p,raw in previous.items():self.assertEqual(p.read_bytes(),raw)

    def test_installer_compatibility_apply_idempotency_and_rollback(self):
        core,desktop=self.installation_fixture()
        originals={p:p.read_bytes() for root in (core,desktop) for p in root.rglob('*') if p.is_file()}
        installer.install(core,desktop,self.project,check=True)
        self.assertFalse((core/'meta40_backups').exists())
        installer.install(core,desktop,self.project)
        self.assertIn(installer.CORE_MARK,(core/'main.py').read_text())
        for p in [*core.rglob('*.py'),*desktop.rglob('*.py')]:
            compile(p.read_text(),str(p),'exec')
        with self.assertRaises(ValueError): installer.install(core,desktop,self.project)
        manifest=next((core/'meta40_backups').glob('*/manifest.json'))
        installed_js=(desktop/'assets/app.js').read_bytes()
        (desktop/'assets/app.js').write_text('later user change')
        with self.assertRaises(ValueError): installer.rollback(manifest,core,desktop)
        (desktop/'assets/app.js').write_bytes(installed_js)
        installer.rollback(manifest,core,desktop)
        for p,raw in originals.items(): self.assertEqual(p.read_bytes(),raw)
        self.assertFalse((core/'meta40_config.json').exists())


if __name__ == '__main__': unittest.main(verbosity=2)
