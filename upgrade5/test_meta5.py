import asyncio
import copy
import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

HERE=Path(__file__).resolve().parent
SUITE=tempfile.TemporaryDirectory(prefix='meta5-suite-')
os.environ['META5_STATE']=str(Path(SUITE.name)/'state')
sys.path.insert(0,str(HERE/'candidate/core'))
from meta5 import context,models,transport,dialogue,api,agent,changes
from meta5.project import Project,digest
from meta5.tools import ToolContext,REGISTRY
from meta5.process import run,test_profile,capabilities
from meta5.memory import Memory
from meta5.jobs import Jobs
from meta5.storage import STATE,atomic_json,read_json
from meta5.research import research
import agent_tools,agent_pending


def users(*messages):return [{'role':'user','content':m} for m in messages]
def fake_complete(actions):
    stream=iter(actions)
    def complete(*args,**kwargs):return {'message':{'content':json.dumps(next(stream),ensure_ascii=False)}}
    return complete


class Meta5(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='meta5-test-');self.root=Path(self.temp.name)
        self.project=self.root/'project';self.project.mkdir();self.pending=self.root/'pending';self.pending.mkdir()
        self.patches=[patch.object(agent_tools,'WORKSPACE',self.project),patch.object(agent_pending,'STORE',self.pending)]
        for p in self.patches:p.start()
        self.contexts=[]
    def tearDown(self):
        for ctx in self.contexts:ctx.close()
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def ctx(self,allow=False):
        ctx=ToolContext.create(self.project,uuid.uuid4().hex,allow_run=allow);self.contexts.append(ctx);return ctx
    def app(self):
        core=self.root/'core';core.mkdir(exist_ok=True)
        atomic_json(core/'meta40_config.json',{'token':'test-only-token','projects':str(self.project)})
        app=FastAPI();api.install(app,core);return app
    @property
    def headers(self):return {'X-Meta40-Token':'test-only-token'}

    def test_alias_hoika_is_resolved_from_previous_message(self):
        c=context.resolve(users('Я люблю играть в Хойку','Расскажи мне про парадокс скрипт и сделай веб-сёрчинг'))
        self.assertEqual(c['game'],'hoi4');self.assertEqual(c['origin'],'conversation');self.assertTrue(c['web_requested'])
        plan=context.search_plan(users('Я люблю играть в Хойку','Расскажи мне про парадокс скрипт и сделай веб-сёрчинг'))
        self.assertIn('Hearts of Iron IV',plan['query']);self.assertIn('scripting',plan['query']);self.assertNotIn('Хойку',plan['query'])

    def test_current_game_and_correction_override_old_context(self):
        self.assertEqual(context.resolve(users('Играю в Хойку','Paradox Script в CK3'))['game'],'ck3')
        self.assertEqual(context.resolve(users('Играю в Хойку','Не про Хойку, а CK3 и скрипты'))['game'],'ck3')
    def test_other_person_is_not_forced_into_game_context(self):
        c=context.resolve(users('Играю в Хойку','Нет, я про девушку Парадокс в Telegram'))
        self.assertIsNone(c['game']);self.assertIsNone(c['topic'])
    def test_game_context_does_not_leak_into_weather_or_python(self):
        prefs=[{'value':'Я люблю играть в Хойку'}]
        plan=context.search_plan(users('Играю в Хойку','Найди погоду в Баку'),prefs)
        self.assertNotIn('Hearts',plan['query']);self.assertIsNone(plan['context']['game'])
        plan=context.search_plan(users('Играю в Хойку','Найди Python скрипт для CSV'),prefs)
        self.assertIn('Python',plan['query']);self.assertIsNone(plan['context']['topic'])
    def test_comparison_does_not_inherit_single_old_game(self):
        c=context.resolve(users('Играю в Хойку','Сравни Paradox Script в HOI4 и CK3'))
        self.assertIsNone(c['game']);self.assertEqual(len(c['games']),2)
    def test_preferences_can_supply_game_but_current_topic_wins(self):
        prefs=[{'value':'Я люблю играть в Хойку'}]
        self.assertEqual(context.resolve(users('Paradox Script'),prefs)['game'],'hoi4')
        self.assertEqual(context.resolve(users('Paradox Script для Stellaris'),prefs)['game'],'stellaris')
    def test_social_irrelevance_is_filtered_and_official_wiki_ranked(self):
        plan=context.search_plan(users('Я люблю играть в Хойку','Paradox Script веб-сёрчинг'))
        rows=[{'url':'https://t.me/paradox_girl','title':'Парадокс девочка','snippet':'Чат'},
              {'url':'https://example.com/random','title':'Paradox code','snippet':'unrelated'},
              {'url':'https://hoi4.paradoxwikis.com/Scripting','title':'Scripting','snippet':'Hearts of Iron IV scripting'},
              {'url':'https://example.com/hoi4','title':'HOI4 modding','snippet':'Hearts of Iron IV modding'}]
        good,bad=context.rank_sources(rows,plan)
        self.assertEqual(good[0]['url'],rows[2]['url']);self.assertEqual(len(good),2);self.assertEqual(len(bad),2)
    def test_general_scripting_prefers_general_article_over_gui_subtopic(self):
        plan=context.search_plan(users('Играю в Хойку','Расскажи про парадокс скрипт'))
        rows=[{'url':'https://hoi4.paradoxwikis.com/Scripted_GUI_modding','title':'HOI4 Scripted GUI modding','snippet':'scripting modding'},
              {'url':'https://hoi4.paradoxwikis.com/Modding','title':'HOI4 Modding','snippet':'modding'}]
        good,_=context.rank_sources(rows,plan);self.assertTrue(good[0]['url'].endswith('/Modding'))
    def test_offline_and_secrets_never_trigger_public_query(self):
        self.assertTrue(context.resolve(users('Paradox Script без интернета'))['web_disabled'])
        with self.assertRaises(ValueError):context.search_plan(users('Найди api_key=secret'))
    def test_compaction_preserves_recent_user_and_labels_summary(self):
        history=users(*['старый вопрос '+str(i)+'x'*500 for i in range(30)],'Последнее уточнение')
        messages,usage=context.compact(history,budget=2000)
        self.assertEqual(messages[-1]['content'],'Последнее уточнение');self.assertGreater(usage['older_turns_summarized'],0)
        self.assertIn('недоверенные',messages[0]['content'])
    def test_large_file_ranges_and_symbols(self):
        text='\n'.join('value_'+str(i)+' = '+str(i) for i in range(1000))+'\ndef important(a):\n return a+1\n'
        (self.project/'big.py').write_text(text,encoding='utf-8')
        p=Project(self.project);piece=p.read('big.py',995,1010)
        self.assertIn('important',piece['text']);self.assertEqual(piece['start'],995)
        index=p.index();self.assertTrue(any(s['name']=='important' for s in index['symbols']))
        self.assertTrue(p.search('value_999'))
    def test_project_paths_and_sensitive_files_are_rejected(self):
        p=Project(self.project)
        for name in ('../a.py','C:/a.py','a\\b.py','.env','CON.py','x/../a.py','secret_key.json'):
            with self.subTest(name=name),self.assertRaises(ValueError):p.path(name)
    def test_exact_edit_keeps_original_unchanged(self):
        (self.project/'a.py').write_text('def add(a,b):\n return a-b\n')
        ctx=self.ctx();REGISTRY.call(ctx,'read',{'path':'a.py'})
        REGISTRY.call(ctx,'edit',{'path':'a.py','old':'return a-b','new':'return a+b'})
        self.assertIn('a-b',(self.project/'a.py').read_text());self.assertIn('a+b',ctx.work.path('a.py').read_text())
        self.assertIn('a.py',ctx.edits)
    def test_full_write_of_partially_read_large_file_is_blocked(self):
        (self.project/'a.py').write_text('\n'.join('x=1' for _ in range(500)))
        ctx=self.ctx();REGISTRY.call(ctx,'read',{'path':'a.py','start':1,'end':10})
        with self.assertRaises(ValueError):REGISTRY.call(ctx,'write',{'path':'a.py','content':'x=2'})
    def test_rename_delete_and_transactional_rollback(self):
        (self.project/'a.py').write_text('x=1\n');(self.project/'b.py').write_text('y=2\n')
        ctx=self.ctx()
        for name in ('a.py','b.py'):REGISTRY.call(ctx,'read',{'path':name})
        REGISTRY.call(ctx,'rename',{'path':'a.py','destination':'new/a.py'})
        REGISTRY.call(ctx,'delete',{'path':'b.py'})
        proposal=changes.stage(self.project,ctx.edits,ctx.expected)
        self.assertIn('new/a.py',changes.preview(proposal['id'])['files'])
        agent_pending.proposal_approve(proposal['id'])
        self.assertFalse((self.project/'a.py').exists());self.assertFalse((self.project/'b.py').exists());self.assertTrue((self.project/'new/a.py').exists())
        changes.rollback(proposal['id']);self.assertEqual((self.project/'a.py').read_text(),'x=1\n');self.assertTrue((self.project/'b.py').exists())
    def test_stale_source_blocks_apply(self):
        (self.project/'a.py').write_text('x=1')
        proposal=changes.stage(self.project,{'a.py':'x=2'},{'a.py':digest(b'x=1')})
        (self.project/'a.py').write_text('x=3')
        with self.assertRaises(ValueError):changes.approve(proposal['id'])
    def test_group_write_failure_restores_original(self):
        (self.project/'a.py').write_text('x=1')
        proposal=changes.stage(self.project,{'a.py':'x=2','b.py':'y=3'},{'a.py':digest(b'x=1')})
        real=changes.replace
        def fail(path,raw):
            if path.name=='b.py':raise OSError('disk failure')
            return real(path,raw)
        with patch.object(changes,'replace',side_effect=fail):
            with self.assertRaises(OSError):changes.approve(proposal['id'])
        self.assertEqual((self.project/'a.py').read_text(),'x=1');self.assertFalse((self.project/'b.py').exists())
    def test_execution_permission_is_enforced(self):
        ctx=self.ctx()
        with self.assertRaises(PermissionError):REGISTRY.call(ctx,'test',{'profile':'python-syntax'})
        with self.assertRaises(PermissionError):REGISTRY.call(ctx,'process_start',{})
    def test_python_unittest_and_pytest_profiles(self):
        (self.project/'test_a.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_ok(self):self.assertEqual(2+3,5)\n')
        ctx=self.ctx(True)
        for profile in ('python-unittest','python-pytest','python-syntax'):
            r=REGISTRY.call(ctx,'test',{'profile':profile});self.assertEqual(r['exit_code'],0,msg=r['output'])
    def test_node_package_and_typescript_profiles(self):
        (self.project/'test_a.js').write_text("const t=require('node:test');const a=require('node:assert');t('sum',()=>a.equal(2+3,5));")
        (self.project/'package.json').write_text(json.dumps({'scripts':{'test':'node --test'}}))
        (self.project/'tsconfig.json').write_text(json.dumps({'compilerOptions':{'strict':True,'noEmit':True},'include':['a.ts']}))
        (self.project/'a.ts').write_text('const value: number = 3;')
        ctx=self.ctx(True)
        for profile in ('node-test','package-test','typescript'):
            r=REGISTRY.call(ctx,'test',{'profile':profile});self.assertEqual(r['exit_code'],0,msg=profile+': '+r['output'])
    def test_timeout_and_cancellation_kill_process_tree(self):
        marker=self.root/'late.txt'
        child='import time,pathlib;time.sleep(2);pathlib.Path('+repr(str(marker))+').write_text("bad")'
        code='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(child)+']);time.sleep(20)'
        result=run([sys.executable,'-c',code],self.project,timeout=.4)
        self.assertEqual(result['status'],'timeout');time.sleep(2.1);self.assertFalse(marker.exists())
        event=threading.Event();event.set()
        self.assertEqual(run([sys.executable,'-c','import time;time.sleep(10)'],self.project,event,timeout=5)['status'],'cancelled')
    def test_docker_absence_does_not_fall_back_to_native(self):
        with patch('meta5.process.shutil.which',return_value=None):
            with self.assertRaisesRegex(ValueError,'Docker'):test_profile('python-unittest',self.project,True,backend='docker')
    def test_dependency_installation_requires_separate_consent(self):
        ctx=self.ctx(True)
        with self.assertRaises(PermissionError):REGISTRY.call(ctx,'prepare_environment',{'language':'python'})
    def test_git_worktree_and_local_commit(self):
        from meta5 import git_tools
        (self.project/'a.py').write_text('x=1')
        git_tools.command(self.project,'init');git_tools.command(self.project,'add','--all')
        result=git_tools.command(self.project,'-c','user.name=Test','-c','user.email=test@localhost','commit','-m','base')
        self.assertEqual(result['exit_code'],0,result['output'])
        ctx=self.ctx();self.assertEqual(ctx.workspace_info['kind'],'git_worktree')
        REGISTRY.call(ctx,'read',{'path':'a.py'});REGISTRY.call(ctx,'edit',{'path':'a.py','old':'x=1','new':'x=2'})
        r=REGISTRY.call(ctx,'git_commit',{'message':'change only working copy'});self.assertEqual(r['exit_code'],0,r['output'])
        self.assertEqual((self.project/'a.py').read_text(),'x=1')
    def test_checkpoint_restores_edit_and_plan(self):
        ctx=self.ctx();REGISTRY.call(ctx,'write',{'path':'a.py','content':'x=1'});REGISTRY.call(ctx,'plan',{'steps':['Изучить','Проверить']})
        restored=ToolContext.restore(read_json(ctx.checkpoint));self.contexts.append(restored)
        self.assertEqual(restored.edits,ctx.edits);self.assertEqual(len(restored.plan),2)
    def test_agent_pause_resume_retains_prepared_files(self):
        ctx=self.ctx();request={'task':'Создай файл a.py','max_steps':1,'model':'auto'}
        with patch.object(agent.transport,'complete',fake_complete([{'action':'write','args':{'path':'a.py','content':'x=1'}}])):
            first=agent.execute(ctx,request)
        self.assertEqual(first['status'],'paused');self.assertFalse((self.project/'a.py').exists())
        restored=ToolContext.restore(read_json(ctx.checkpoint));self.contexts.append(restored)
        with patch.object(agent.transport,'complete',fake_complete([{'action':'finish','summary':'prepared'}])):
            result=agent.execute(restored,request,read_json(ctx.checkpoint.with_name(ctx.job_id+'.loop.json')))
        self.assertEqual(result['status'],'pending');self.assertIn('a.py',result['proposal']['files'])
    def test_successful_read_loop_is_paused(self):
        ctx=self.ctx()
        with patch.object(agent.transport,'complete',fake_complete([{'action':'list'}]*3)):
            result=agent.execute(ctx,{'task':'Изучи проект','max_steps':10})
        self.assertEqual(result['status'],'paused')
    def test_model_failure_preserves_checkpoint(self):
        ctx=self.ctx()
        with patch.object(agent.transport,'complete',side_effect=httpx.ReadTimeout('slow')):
            result=agent.execute(ctx,{'task':'Изучи проект'})
        self.assertEqual(result['status'],'paused');self.assertTrue(ctx.checkpoint.exists())
    def test_memory_capture_edit_delete_and_secret_guard(self):
        m=Memory(self.root/'memory.sqlite');m.capture('Я люблю играть в Хойку')
        item=m.list()[0];self.assertEqual(item['kind'],'preference')
        with self.assertRaises(ValueError):m.update(item['id'],'password=secret')
        self.assertEqual(m.list()[0]['value'],item['value']);m.update(item['id'],'Люблю Stellaris','preference')
        self.assertIn('Stellaris',m.list()[0]['value']);m.delete(item['id']);self.assertEqual(m.list(),[])
    def test_memory_capture_can_be_disabled(self):
        m=Memory(self.root/'memory.sqlite');m.set_enabled(False);m.capture('Я люблю играть в Хойку');self.assertEqual(m.list(),[])
    def test_model_profiles_use_measured_grounding_and_coding(self):
        report={'hardware':{},'scope':'smoke','results':[{'model':'fast:3b','test':'grounded_context','passed':True,'seconds':1},
            {'model':'fast:3b','test':'code','passed':True,'seconds':1},{'model':'coder:7b','test':'code','passed':True,'seconds':3},
            {'model':'quality:14b','test':'context','passed':True,'seconds':15}]}
        with patch.object(models,'PROFILE_FILE',self.root/'models.json'):
            p=models.from_benchmark(report);self.assertEqual(p['chat'],'fast:3b');self.assertEqual(p['code'],'coder:7b')
            self.assertEqual(models.select('chat','auto-quality')[0],'quality:14b');self.assertEqual(models.select('code','manual:7b')[0],'manual:7b')
    def test_research_exposes_query_filters_and_actual_page_status(self):
        events=[];hits={'results':[{'url':'https://hoi4.paradoxwikis.com/Scripting','title':'HOI4 Scripting','snippet':'Hearts of Iron IV modding'}, {'url':'https://t.me/girl','title':'Paradox','snippet':'girl'}]}
        with patch('meta5.research.web_search',return_value=hits),patch('meta5.research.web_fetch',side_effect=ValueError('HTTP 403')):
            r=research(users('Я играю в Хойку','Paradox Script веб-сёрчинг'),emit=lambda k,v:events.append((k,v)))
        self.assertIn('Hearts of Iron IV',r['query']);self.assertEqual(len(r['sources']),1);self.assertFalse(r['sources'][0]['opened'])
        self.assertIn('page_failed',[k for k,_ in events]);self.assertIn('sources_found',[k for k,_ in events])
    def test_api_authentication_profiles_memory_and_project_index(self):
        (self.project/'a.py').write_text('def hello(): return 1')
        with TestClient(self.app()) as c:
            self.assertEqual(c.get('/agent40/status').status_code,401)
            self.assertEqual(c.get('/agent40/status',headers=self.headers).json()['version'],'5.0.0')
            self.assertEqual(c.get('/agent40/project/index',headers=self.headers).json()['symbols'][0]['name'],'hello')
            self.assertEqual(c.post('/agent40/tasks',headers=self.headers,json={'task':'test','allow_tests':True}).status_code,400)
            self.assertEqual(c.get('/agent40/project/read',headers=self.headers,params={'path':'../bad.py'}).status_code,400)
    def test_api_jobs_are_restart_safe(self):
        jobs=Jobs(self.project,self.root/'tasks')
        jid=uuid.uuid4().hex;atomic_json(jobs.path(jid),{'id':jid,'status':'running'})
        restored=Jobs(self.project,self.root/'tasks');self.assertEqual(restored.get(jid)['status'],'interrupted')
    def test_actual_browser_checks_task_server(self):
        (self.project/'index.html').write_text('<!doctype html><title>META test</title><h1>Local browser check</h1>')
        ctx=self.ctx(True);server=REGISTRY.call(ctx,'process_start',{})
        try:
            result=REGISTRY.call(ctx,'browser_inspect',{'url':server['url']})
            self.assertEqual(result['status'],200);self.assertIn('Local browser check',result['text'])
            self.assertTrue((STATE/'artifacts'/ctx.job_id/'screenshot.png').is_file())
        finally:REGISTRY.call(ctx,'process_stop',{'process_id':server['process_id']})
    def test_browser_will_not_open_arbitrary_local_services(self):
        ctx=self.ctx(True)
        with self.assertRaises(ValueError):REGISTRY.call(ctx,'browser_inspect',{'url':'http://127.0.0.1:8000/health'})
    def test_archive_only_removes_own_working_copy_and_disables_resume(self):
        (self.project/'a.py').write_text('x=1')
        ctx=self.ctx();jobs=Jobs(self.project,self.root/'tasks')
        atomic_json(jobs.path(ctx.job_id),{'id':ctx.job_id,'status':'paused','project':str(self.project),'request':{}})
        jobs.archive_workspace(ctx.job_id)
        self.assertFalse(ctx.work.root.exists());self.assertTrue((self.project/'a.py').exists())
        with self.assertRaises(ValueError):jobs.resume(ctx.job_id)
    def test_readonly_task_cannot_stage_test_side_effects(self):
        ctx=self.ctx();ctx.allow_write=False;(ctx.work.root/'generated.py').write_text('x=1')
        with self.assertRaises(ValueError):ctx.sync_edits()
    def test_manifest_uses_typed_parameters(self):
        entry=next(e for e in REGISTRY.manifest() if e['name']=='read')
        self.assertEqual(entry['parameters']['properties']['start']['type'],'integer')
        self.assertEqual(entry['parameters']['properties']['start']['default'],1)
    def test_search_retries_preferred_query_when_first_provider_fails(self):
        from meta40.web_research import WebError
        hit={'url':'https://hoi4.paradoxwikis.com/Modding','title':'HOI4 Modding','snippet':'modding'}
        with patch('meta5.research.web_search',side_effect=[WebError('provider failed'),{'results':[hit]}]),patch('meta5.research.web_fetch',return_value={'text':'HOI4 modding'}):
            result=research(users('Играю в Хойку','Paradox Script веб-сёрчинг'))
        self.assertEqual(len(result['sources']),1);self.assertTrue(result['sources'][0]['opened'])

    def test_installer_requires_existing_roots_and_restores_exact_bytes(self):
        sys.path.insert(0,str(HERE))
        import installer
        package=self.root/'package';core=self.root/'core';desktop=self.root/'desktop'
        for p in (package/'candidate/core',package/'candidate/desktop',core,desktop):p.mkdir(parents=True,exist_ok=True)
        with self.assertRaises(ValueError):installer.roots(core,desktop)
        (core/'main.py').write_bytes(b'old core');(desktop/'meta_desktop.py').write_bytes(b'old desktop')
        entries=[]
        for area,name,old,new in [('core','main.py',b'old core',b'new core'),('core','meta5/new.py',None,b'new file'),('desktop','meta_desktop.py',b'old desktop',b'new desktop')]:
            path=package/'candidate'/area/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(new)
            entries.append({'area':area,'path':name,'old_hash':installer.sha(old),'new_hash':installer.sha(new)})
        atomic_json(package/'upgrade_manifest.json',entries)
        with patch.object(installer,'HERE',package):
            dest=installer.roots(core,desktop);receipt=installer.install(dest)
            self.assertEqual((core/'main.py').read_bytes(),b'new core')
            (core/'main.py').write_bytes(b'user modification')
            with self.assertRaises(ValueError):installer.rollback(receipt['backup'])
            (core/'main.py').write_bytes(b'new core');installer.rollback(receipt['backup'])
            self.assertEqual((core/'main.py').read_bytes(),b'old core');self.assertFalse((core/'meta5/new.py').exists())


class Streaming(unittest.IsolatedAsyncioTestCase):
    async def test_real_ndjson_is_delivered_before_completion_and_can_cancel(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.end_headers()
                try:
                    for word in ('first','second','last'):
                        self.wfile.write((json.dumps({'message':{'content':word}})+'\n').encode());self.wfile.flush();time.sleep(.4)
                except (BrokenPipeError,ConnectionResetError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.object(transport,'BASE','http://127.0.0.1:'+str(server.server_port)):
                cancel=threading.Event();started=time.monotonic();stream=transport.stream('test',users('hello'),cancel=cancel)
                event=await anext(stream);self.assertEqual(event['content'],'first');self.assertLess(time.monotonic()-started,.8)
                cancel.set();remaining=[e async for e in stream];self.assertEqual(remaining,[])
                self.assertTrue(transport.COMPUTE.acquire(blocking=False));transport.COMPUTE.release()
        finally:server.shutdown();server.server_close()

    async def test_cancel_before_first_token_releases_compute(self):
        cancel=threading.Event();cancel.set()
        result=[e async for e in transport.stream('unused',users('hi'),cancel=cancel)]
        self.assertEqual(result,[]);self.assertTrue(transport.COMPUTE.acquire(blocking=False));transport.COMPUTE.release()

    async def test_dialogue_grounding_and_citation_filter(self):
        data={'query':'Hearts of Iron IV scripting','sources':[{'url':'https://hoi4.paradoxwikis.com/Scripting','title':'Scripting','opened':False}]}
        async def chunks(model,messages,**kwargs):
            self.assertEqual(model,'qwen2.5-coder:7b')
            self.assertIn('hoi4',messages[0]['content'])
            for word in ('В HOI4 используется Paradox Script. https://t.', 'me/girl ', 'Описание игры.'):yield {'type':'token','content':word}
        with tempfile.TemporaryDirectory() as temp:
            memory=Memory(Path(temp)/'memory.sqlite')
            with patch.object(dialogue,'Memory',return_value=memory),patch.object(dialogue,'research',return_value=data),patch.object(transport,'stream',chunks):
                events=[e async for e in dialogue.converse({'messages':users('Я люблю играть в Хойку','Расскажи про парадокс скрипт, веб-сёрчинг')})]
        text=''.join(e.get('content','') for e in events)
        self.assertNotIn('t.me/girl',text);self.assertIn(data['sources'][0]['url'],text)
        self.assertIn('citation_warning',[e['type'] for e in events])

    async def test_offline_prevents_research_even_for_paradox(self):
        async def chunks(*args,**kwargs):yield {'type':'token','content':'Офлайн ответ'}
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(dialogue,'Memory',return_value=Memory(Path(temp)/'memory.sqlite')),patch.object(dialogue,'research') as search,patch.object(transport,'stream',chunks):
                events=[e async for e in dialogue.converse({'messages':users('HOI4 Paradox Script без интернета')})]
                search.assert_not_called()
        self.assertEqual(events[-1]['type'],'done')


class Citations(unittest.TestCase):
    def test_chunk_boundaries_and_code_are_preserved(self):
        from meta5.citations import LinkFilter
        f=LinkFilter([{'url':'https://example.org/source'}]);value='Ссылка [источник](https://example.org/source). ```python\nurl="https://test.invalid/code"\n```\nhttps://t.me/wrong '
        text=''.join(f.feed(value[n:n+2]) for n in range(0,len(value),2))+f.feed('',final=True)
        self.assertIn('https://example.org/source',text);self.assertIn('https://test.invalid/code',text);self.assertNotIn('https://t.me/wrong',text)
        self.assertEqual(f.removed,1)


if __name__=='__main__':unittest.main(verbosity=2)
