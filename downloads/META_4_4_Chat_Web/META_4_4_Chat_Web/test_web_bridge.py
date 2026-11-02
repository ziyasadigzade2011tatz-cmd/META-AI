import asyncio
import json
import unittest
from unittest.mock import patch
from meta_web_bridge import should_research, query_from, WebChatMiddleware

class WebBridgeTests(unittest.TestCase):
    def test_web_intent(self):
        self.assertTrue(should_research([{'role':'user','content':'Найди в интернете документацию HOI4'}]))
    def test_not_for_offline(self):
        self.assertFalse(should_research([{'role':'user','content':'Найди новости без интернета'}]))
    def test_followup(self):
        self.assertTrue(should_research([{'role':'user','content':'Найди документацию'}, {'role':'user','content':'а ссылки?'}]))
    def test_general(self):
        self.assertFalse(should_research([{'role':'user','content':'Привет братан'}]))
    def test_query_followup(self):
        self.assertIn('HOI4',query_from([{'role':'user','content':'Проверь HOI4 скрипты'},{'role':'user','content':'а где?'}]))
    def test_request_injection_legacy_route(self):
        async def exercise():
            observed={}
            async def downstream(scope,receive,send):
                msg=await receive(); observed.update(json.loads(msg['body']))
                await send({'type':'http.response.start','status':200,'headers':[]})
                await send({'type':'http.response.body','body':b'ok'})
            app=WebChatMiddleware(downstream)
            payload={'messages':[{'role':'user','content':'Привет'}], 'stream': True}
            async def receive(): return {'type':'http.request','body':json.dumps(payload).encode(),'more_body':False}
            results=[]
            async def send(m):results.append(m)
            await app({'type':'http','path':'/v1/chat/completions','method':'POST'},receive,send)
            self.assertTrue(observed['stream'])
            self.assertEqual(observed['messages'][1]['content'],'Привет')
            self.assertEqual(results[0]['status'],200)
        asyncio.run(exercise())
    def test_research_injected_with_real_urls_only(self):
        async def exercise():
            observed={}
            async def downstream(scope,receive,send):
                observed.update(json.loads((await receive())['body']))
            app=WebChatMiddleware(downstream)
            data={'messages':[{'role':'user','content':'Найди источники по HOI4'}]}
            async def receive(): return {'type':'http.request','body':json.dumps(data).encode()}
            async def send(message): pass
            with patch('meta_web_bridge.research',return_value={'sources':[{'url':'https://hoi4.paradoxwikis.com/Modding','title':'Modding'}]}):
                await app({'type':'http','method':'POST','path':'/chat'},receive,send)
            self.assertIn('hoi4.paradoxwikis.com',observed['messages'][0]['content'])
        asyncio.run(exercise())

if __name__=='__main__':unittest.main()
