import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta_studio.agent import Sessions,parse_action
from meta_studio.team import review_files,consult
from meta5.storage import atomic_json,read_json

class TeamTests(unittest.TestCase):
    def test_1000_progress_ticks_do_not_rewrite_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);sessions=Sessions(root/'projects',root/'sessions');ident='a'*32
            atomic_json(sessions.path(ident),{'status':'running','events':[]})
            with patch('meta_studio.agent.atomic_json',wraps=atomic_json) as write:
                for i in range(1000):sessions.emit(ident,'generation',{'characters':i})
                self.assertEqual(write.call_count,0)
                self.assertEqual(sessions.get(ident)['progress']['characters'],999)
                sessions.emit(ident,'status',{'message':'checkpoint'})
                self.assertEqual(write.call_count,1)
            self.assertEqual(read_json(sessions.path(ident))['progress']['characters'],999)

    def test_two_checker_agents_work_in_parallel_keep_order(self):
        gate=threading.Barrier(2)
        files={'page.html':'<html/>','data.json':'{}'}
        def check(paths):
            gate.wait(timeout=2)
            return [{'path':path,'status':'passed'} for path in paths]
        result=review_files(files,check)
        self.assertEqual([row['path'] for row in result],list(files))
        self.assertEqual({row['agent'] for row in result},{'syntax','integration'})

    def test_specialist_is_read_only_and_uses_same_selected_model(self):
        files={'main.py':'print(1)'}
        with patch('meta5.transport.complete',return_value={'message':{'content':json.dumps({'issues':[],'suggestion':'check'})}}) as complete:
            result=consult('reviewer','Проверь изменения','Создай программу',files,'fixture',8192,threading.Event())
        self.assertEqual(complete.call_args.args[0],'fixture')
        self.assertFalse(complete.call_args.kwargs['think'])
        self.assertEqual(files,{'main.py':'print(1)'})
        self.assertEqual(result['agent'],'reviewer')
        self.assertEqual(parse_action('{"action":"consult","args":{"role":"reviewer","question":"Check code"}}')[0],'consult')

if __name__=='__main__':unittest.main()
