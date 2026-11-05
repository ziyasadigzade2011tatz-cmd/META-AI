import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
import httpx
from meta5 import memory_extract,debug_state,transport
from meta5.memory import Memory
from meta5.embeddings import Embeddings,unpack
from meta5.search_ranking import command,domains

class IntegrationTests(unittest.TestCase):
    def test_background_extract_preserves_speed_residency(self):
        calls=[];actual=httpx.Client
        def respond(req):
            if req.url.path=='/api/ps':return httpx.Response(200,json={'models':[{'name':'qwen3.5:4b'}]})
            calls.append(json.loads(req.content));return httpx.Response(200,json={'message':{'content':'{"facts":[]}'}})
        import threading
        with patch.object(transport,'COMPUTE',threading.Semaphore(1)),patch.object(memory_extract.httpx,'Client',side_effect=lambda **kw:actual(transport=httpx.MockTransport(respond))),patch('meta5.models.select',return_value=('qwen3.5:4b','test')):
            self.assertEqual(memory_extract.local_parser([]),'{"facts":[]}')
        self.assertEqual(calls[0]['keep_alive'],900)
    def test_domain_command_persists_and_is_read(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'META_CORE_CONFIG_DIR':d}):
            command('/domains block sample.example.org');self.assertIn('sample.example.org',domains()['blocked'])
            command('/domains allow sample.example.org');self.assertNotIn('sample.example.org',domains()['blocked']);self.assertIn('sample.example.org',domains()['allowed'])
    def test_derived_summary_never_stores_secret(self):
        with tempfile.TemporaryDirectory() as d:
            memory=Memory(Path(d)/'memory.sqlite');memory.summary('A','Мой пароль: sample')
            self.assertEqual(memory.summary('A'),'')
    def test_sensitive_category_precedes_hobby(self):
        from meta5.memory_retrieval import category
        self.assertEqual(category('Я люблю обсуждать свой диагноз'),'health')
    def test_corrupted_vector_rejected(self):
        import struct
        with self.assertRaises(ValueError):unpack(struct.pack('<f',float('nan')),1)
    def test_negated_preference_supersedes_only_after_confirm(self):
        with tempfile.TemporaryDirectory() as d,patch('meta5.memory_extract.semantic_duplicate',return_value=None):
            m=Memory(Path(d)/'memory.sqlite')
            def fact(text):return memory_extract.parse(text,lambda _:{'facts':[{'fact':text,'evidence':text,'type':'preference','confidence':1,'ttl_days':None}]})[0]
            old=memory_extract.observe(m,fact('Я люблю керамику'),'A','first')
            memory_extract.command(m,'/memory confirm '+old)
            new=memory_extract.observe(m,fact('Я больше не люблю керамику'),'A','second')
            self.assertEqual(next(r for r in m.records() if r['id']==old)['status'],'confirmed')
            memory_extract.command(m,'/memory confirm '+new)
            self.assertEqual(next(r for r in m.records() if r['id']==old)['status'],'superseded')
    def test_quoted_or_hypothetical_self_is_not_learned(self):
        text='Он сказал «Я люблю рассветы»'
        row={'fact':'Я люблю рассветы','evidence':'Я люблю рассветы','type':'preference','confidence':1,'ttl_days':None}
        self.assertEqual(memory_extract.parse(text,lambda _:{'facts':[row]}),[])
        self.assertEqual(memory_extract.parse('Это пример: Я люблю рассветы',lambda _:{'facts':[row]}),[])

if __name__=='__main__':unittest.main()
