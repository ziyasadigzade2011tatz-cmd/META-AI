import asyncio
import json
import sys
import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))
from meta_studio.agent_context import fit_request
from meta_studio import agent_stream
from meta_studio.fragments import IncompleteAction
from meta5.token_budget import BudgetExceeded
from meta5 import transport
from meta_studio.agent import Sessions


class BudgetRegressionTests(unittest.TestCase):
    def test_plan_can_name_project_without_extra_model_request(self):
        actions=iter([{'action':'plan','args':{'title':'Органайзер','steps':['Создать файл']}},
                      {'action':'write','args':{'path':'data.json','content':'{}'}},
                      {'action':'check','args':{}},
                      {'action':'finish','args':{'summary':'Готово'}}])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            sessions=Sessions(root/'projects',root/'sessions',client=lambda messages:json.dumps(next(actions)))
            obj=sessions.start({'task':'Создай JSON файл'})
            deadline=time.monotonic()+5
            while sessions.active and time.monotonic()<deadline:time.sleep(.01)
            saved=sessions.get(obj['id'])
            self.assertEqual(saved['status'],'completed')
            self.assertEqual(saved['title'],'Органайзер')

    def test_mimo_uses_its_vocabulary_counter_and_keeps_selected_model(self):
        rows=[{'role':'system','content':'Инструкция ' * 500},
              {'role':'user','content':'Create a file'}]
        with patch('meta5.qwen_tokens.agent_counter',return_value=lambda messages:1800) as lookup:
            request=agent_stream.payload('mimo-v2.6:9b',rows,8192)
        lookup.assert_called_once_with('mimo-v2.6:9b')
        self.assertEqual(request['model'],'mimo-v2.6:9b')
        self.assertEqual(request['options']['num_predict'],3000)
        self.assertFalse(request['think'])

    def test_rechecking_changed_files_is_not_a_repeated_action_loop(self):
        actions=[{'action':'write','args':{'path':'data.json','content':'{"value":0}'}}]
        for i in range(4):
            actions.append({'action':'check','args':{}})
            if i<3:actions.append({'action':'edit','args':{'path':'data.json','old':str(i),'new':str(i+1)}})
        actions.append({'action':'finish','args':{'summary':'Готово'}})
        iterator=iter(actions)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            sessions=Sessions(root/'projects',root/'sessions',client=lambda messages:json.dumps(next(iterator)))
            obj=sessions.start({'task':'Создай JSON файл'})
            deadline=time.monotonic()+5
            while sessions.active and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(sessions.get(obj['id'])['status'],'completed')

    def test_15_steps_evict_old_tools_preserve_goal_and_latest_hash(self):
        rows = [{'role': 'system', 'content': 'Policy'},
                {'role': 'user', 'content': json.dumps({'task': 'Maintain this project'})}]
        for i in range(15):
            rows += [{'role': 'assistant', 'content': json.dumps({'action': 'read', 'args': {'path': str(i)}})},
                     {'role': 'user', 'content': 'TOOL_RESULT ' + str(i) + 'x' * 1500}]
        count = lambda values: sum(len(m['content']) for m in values)
        kept, allocation = fit_request(rows, 8192, 'fixture', count=count)
        self.assertLessEqual(count(kept), 5000)
        self.assertEqual(kept[:2], rows[:2])
        self.assertEqual(kept[-2:], rows[-2:])
        self.assertEqual(allocation['output_limit'], 3000)

    def test_oversized_goal_is_rejected_without_clipping(self):
        rows = [{'role': 'system', 'content': 'Policy'}, {'role': 'user', 'content': 'z' * 6000}]
        with self.assertRaises(BudgetExceeded):
            fit_request(rows, 8192, 'fixture', count=lambda values: sum(len(m['content']) for m in values))

    def test_stale_session_output_limit_cannot_exceed_context(self):
        for context in (4096, 8192, 16384):
            payload = agent_stream.payload('fixture', [{'role': 'user', 'content': 'hello'}], context, 32768)
            self.assertEqual(payload['options']['num_predict'], 3000 * context // 8192)
            self.assertFalse(payload['think'])

    def run_stream(self, stream):
        actual = httpx.AsyncClient
        def response(request):
            if request.url.path == '/api/ps':
                return httpx.Response(200, json={'models': []})
            return httpx.Response(200, stream=stream)
        with patch.object(transport, 'COMPUTE', threading.Semaphore(1)), \
             patch.object(agent_stream.httpx, 'AsyncClient', side_effect=lambda **kw: actual(transport=httpx.MockTransport(response))):
            return agent_stream.generate('fixture', [], threading.Event(), lambda *args: None)

    def test_done_frame_finishes_without_waiting_for_connection_close(self):
        class OpenStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield (json.dumps({'message': {'content': '{"action":"list","args":{}}'}, 'done': True}) + '\n').encode()
                raise AssertionError('Must not request another chunk after done')
        self.assertEqual(json.loads(self.run_stream(OpenStream()))['action'], 'list')

    def test_unexpected_eof_preserves_partial_action(self):
        class BrokenStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield (json.dumps({'message': {'content': '{"action":"write"'}}) + '\n').encode()
        with self.assertRaises(IncompleteAction) as result:
            self.run_stream(BrokenStream())
        self.assertIn('write', result.exception.raw)


if __name__ == '__main__':
    unittest.main()
