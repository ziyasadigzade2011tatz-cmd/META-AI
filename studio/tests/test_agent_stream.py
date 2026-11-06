import asyncio,json,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
import httpx
from meta_studio import agent_stream
from meta_studio.agent import Sessions,parse_action
from meta5 import transport
from meta5.phase11_config import load

class Delayed(httpx.AsyncByteStream):
    async def __aiter__(self):
        await asyncio.sleep(.2)
        yield (json.dumps({'message':{'content':'{"action":"write","args":{"path":"index.html","content":"<h1>Draft'}})+'\n').encode()
        await asyncio.sleep(.12)
        yield (json.dumps({'message':{'content':'</h1>"}}'},'done':True})+'\n').encode()

class StreamTests(unittest.TestCase):
    def setUp(self):
        # Network is mocked: these tests must not occupy the user's real GPU queue.
        patcher=patch.object(transport,'COMPUTE',threading.Semaphore(1));patcher.start();self.addCleanup(patcher.stop)
    def client(self):
        actual=httpx.AsyncClient
        def response(req):
            if req.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
            return httpx.Response(200,stream=Delayed())
        return lambda **kw:actual(transport=httpx.MockTransport(response))
    def config(self):return {**load('agent'),'heartbeat_seconds':.05,'progress_seconds':.05}
    def test_heartbeat_and_partial_code_before_action_finishes(self):
        events=[];factory=self.client()
        with patch.object(agent_stream.httpx,'AsyncClient',side_effect=factory),patch.object(agent_stream,'load',return_value=self.config()):
            raw=agent_stream.generate('fixture',[{'role':'user','content':'task'}],threading.Event(),lambda k,d:events.append(d))
        self.assertEqual(json.loads(raw)['args']['path'],'index.html')
        self.assertTrue(any(e['phase']=='generating' and e['characters']==0 for e in events))
        self.assertTrue(any(e.get('path')=='index.html' and e.get('code_preview') for e in events))
    def test_token_ceiling_returns_a_recoverable_fragment(self):
        actual=httpx.AsyncClient
        def response(req):
            if req.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
            line=json.dumps({'message':{'content':'{"action":"write","args":{"path":"a.py","content":"x = ('},'done':True,'done_reason':'length'})+'\n'
            return httpx.Response(200,content=line)
        factory=lambda **kw:actual(transport=httpx.MockTransport(response))
        from meta_studio.fragments import IncompleteAction,recover
        with patch.object(agent_stream.httpx,'AsyncClient',side_effect=factory):
            with self.assertRaises(IncompleteAction) as result:agent_stream.generate('fixture',[],threading.Event(),lambda *a:None)
        self.assertEqual(recover(result.exception.raw)['args']['content'],'x = (')
        self.assertTrue(transport.COMPUTE.acquire(blocking=False));transport.COMPUTE.release()
    def test_cancel_during_silent_stream_releases_compute(self):
        cancel=threading.Event();timer=threading.Timer(.1,cancel.set);timer.start();factory=self.client();started=time.monotonic()
        try:
            with patch.object(agent_stream.httpx,'AsyncClient',side_effect=factory),patch.object(agent_stream,'load',return_value=self.config()):
                with self.assertRaises(InterruptedError):agent_stream.generate('fixture',[],cancel,lambda *a:None)
        finally:timer.join()
        self.assertLess(time.monotonic()-started,1)
        self.assertTrue(transport.COMPUTE.acquire(blocking=False));transport.COMPUTE.release()
    def test_temporary_failure_is_retried_without_user_resume(self):
        with tempfile.TemporaryDirectory() as d:
            attempts=[TimeoutError('fixture'),{'action':'write','args':{'path':'main.py','content':'x=1\n'}},{'action':'check','args':{}},{'action':'finish','args':{}}]
            def client(messages):
                value=attempts.pop(0)
                if isinstance(value,Exception):raise value
                return json.dumps(value)
            sessions=Sessions(Path(d)/'projects',Path(d)/'sessions',client=client);obj=sessions.start({'task':'Создай программу'})
            deadline=time.monotonic()+5
            while sessions.active and time.monotonic()<deadline:time.sleep(.01)
            data=sessions.get(obj['id']);self.assertEqual(data['status'],'completed');self.assertTrue(any(e['type']=='recovery' for e in data['events']))
    def test_cancel_while_server_has_not_sent_headers(self):
        actual=httpx.AsyncClient
        async def response(req):
            if req.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
            await asyncio.sleep(10)
            return httpx.Response(200,json={})
        factory=lambda **kw:actual(transport=httpx.MockTransport(response))
        cancel=threading.Event();timer=threading.Timer(.15,cancel.set);timer.start();started=time.monotonic()
        try:
            with patch.object(agent_stream.httpx,'AsyncClient',side_effect=factory),patch.object(agent_stream,'load',return_value=self.config()):
                with self.assertRaises(InterruptedError):agent_stream.generate('fixture',[],cancel,lambda *a:None)
        finally:timer.join()
        self.assertLess(time.monotonic()-started,1)
        self.assertTrue(transport.COMPUTE.acquire(blocking=False));transport.COMPUTE.release()
    def test_total_deadline_interrupts_silent_server(self):
        factory=self.client();started=time.monotonic()
        with patch.object(agent_stream.httpx,'AsyncClient',side_effect=factory),patch.object(agent_stream,'load',return_value=self.config()):
            with self.assertRaises(TimeoutError):agent_stream.generate('fixture',[],threading.Event(),lambda *a:None,deadline=started+.1)
        self.assertLess(time.monotonic()-started,.5)
        self.assertTrue(transport.COMPUTE.acquire(blocking=False));transport.COMPUTE.release()
    def test_cancel_during_understanding_request(self):
        actual=httpx.AsyncClient
        async def response(req):
            if req.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
            await asyncio.sleep(10);return httpx.Response(200,json={'message':{'content':'{}'}})
        factory=lambda **kw:actual(transport=httpx.MockTransport(response))
        cancel=threading.Event();timer=threading.Timer(.15,cancel.set);timer.start();started=time.monotonic()
        try:
            with patch.object(transport.httpx,'AsyncClient',side_effect=factory):
                with self.assertRaises(InterruptedError):transport.complete('fixture',[],cancel=cancel)
        finally:timer.join()
        self.assertLess(time.monotonic()-started,1)
        self.assertTrue(transport.COMPUTE.acquire(blocking=False));transport.COMPUTE.release()
    def test_history_marks_orphaned_running_session(self):
        with tempfile.TemporaryDirectory() as d:
            sessions=Sessions(Path(d)/'projects',Path(d)/'sessions');ident='a'*32
            sessions.path(ident).write_text(json.dumps({'id':ident,'status':'running','created':1}))
            self.assertEqual(sessions.history()[0]['status'],'interrupted')
    def test_progress_is_latest_snapshot_not_endless_event_log(self):
        with tempfile.TemporaryDirectory() as d:
            sessions=Sessions(Path(d)/'projects',Path(d)/'sessions');ident='a'*32;sessions.path(ident).write_text(json.dumps({'id':ident,'events':[]}))
            for i in range(10):sessions.emit(ident,'generation',{'characters':i})
            data=json.loads(sessions.path(ident).read_text('utf-8'));self.assertEqual(data['events'],[]);self.assertEqual(data['progress']['characters'],9)
    def test_flat_actions_create_files_and_keep_plan(self):
        with tempfile.TemporaryDirectory() as d:
            actions=iter([{'action':'plan','steps':['Создать файл']},{'action':'write','path':'main.py','content':'x=1\n'},{'action':'check'},{'action':'finish','summary':'Готово'}])
            sessions=Sessions(Path(d)/'projects',Path(d)/'sessions',client=lambda messages:json.dumps(next(actions)))
            obj=sessions.start({'task':'Создай программу'});deadline=time.monotonic()+5
            while sessions.active and time.monotonic()<deadline:time.sleep(.01)
            data=sessions.get(obj['id']);self.assertEqual(data['status'],'completed')
            self.assertEqual((Path(data['root'])/'main.py').read_text('utf-8'),'x=1\n')
            self.assertTrue(any(e['type']=='plan' and e['data']['steps']==['Создать файл'] for e in data['events']))
    def test_ambiguous_or_unknown_action_is_rejected(self):
        for value in ({'action':'write','path':'a.py','args':{'path':'b.py'}},{'action':'shell','command':'anything'},{'action':'read','args':[]}):
            with self.assertRaises(ValueError):parse_action(json.dumps(value))

if __name__=='__main__':unittest.main()
