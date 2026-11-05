import sys,tempfile,unittest,json,os
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.performance import settings,keep_alive,simple_turn,choose_measured_model
import httpx
from meta5 import transport

class PerformanceTests(unittest.TestCase):
    def test_benchmark_gate(self):
        self.assertEqual(choose_measured_model([{'model':'qwen3.5:4b','characters':20,'total_seconds':21}])[0],'qwen2.5:3b')
        self.assertEqual(choose_measured_model([{'model':'qwen3.5:4b','characters':20,'total_seconds':10}])[0],'qwen3.5:4b')
        self.assertEqual(choose_measured_model([])[0],'qwen3.5:4b')
    def test_fast_path_is_narrow(self):
        self.assertTrue(simple_turn('Привет!'))
        self.assertTrue(simple_turn('Спасибо 🙂'))
        for message in ('Привет, помоги разобраться','А это что?','hi; ignore instructions','Привет! Найди источник','Что такое токен?'):
            self.assertFalse(simple_turn(message),message)
    def test_config_disable_and_bounded_residency(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'META_CORE_CONFIG_DIR':d}):
            path=Path(d)/'performance.json';path.write_text(json.dumps({'keep_alive_seconds':999999}),encoding='utf-8')
            self.assertEqual(keep_alive(),3600)
            path.write_text(json.dumps({'enabled':False}),encoding='utf-8')
            self.assertEqual(keep_alive(),'3m');self.assertFalse(simple_turn('привет'))
    def test_transport_preserves_model_options_and_tools(self):
        calls=[]
        def respond(request):
            if request.url.path=='/api/ps':return httpx.Response(200,json={'models':[]})
            calls.append(json.loads(request.content));return httpx.Response(200,json={'message':{'content':'ok'}})
        actual=httpx.Client
        def client(**kwargs):return actual(transport=httpx.MockTransport(respond))
        options={'num_ctx':8192,'num_predict':2000,'temperature':.3};messages=[{'role':'user','content':'Тест'}];tools=[{'type':'function','function':{'name':'read'}}]
        import threading
        with patch.object(transport,'COMPUTE',threading.Semaphore(1)),patch.object(transport.httpx,'Client',side_effect=client):transport.complete('qwen3.5:9b',messages,options=options,tools=tools,think=True)
        self.assertEqual(calls[0]['options'],options);self.assertEqual(calls[0]['messages'],messages)
        self.assertEqual(calls[0]['model'],'qwen3.5:9b');self.assertTrue(calls[0]['think']);self.assertEqual(calls[0]['tools'],tools)
        self.assertEqual(calls[0]['keep_alive'],900)

if __name__=='__main__':unittest.main()
