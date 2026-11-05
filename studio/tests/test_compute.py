import os,sys,subprocess,unittest
from pathlib import Path
core=Path(__file__).resolve().parents[1]/'core';sys.path.insert(0,str(core))
from meta5.compute import ComputeGate
from meta5.transport import prepare_model

class ComputeTests(unittest.TestCase):
    def test_same_thread_cannot_reenter_for_another_async_request(self):
        gate=ComputeGate();self.assertTrue(gate.acquire(timeout=2))
        try:self.assertFalse(gate.acquire(blocking=False))
        finally:gate.release()
    @unittest.skipUnless(os.name=='nt','Windows named mutex')
    def test_gate_shared_across_processes(self):
        gate=ComputeGate();self.assertTrue(gate.acquire(timeout=2))
        try:
            code='import sys;sys.path.insert(0,'+repr(str(core))+');from meta5.compute import ComputeGate;print(ComputeGate().acquire(blocking=False))'
            result=subprocess.check_output([sys.executable,'-B','-c',code],text=True,timeout=10)
            self.assertEqual(result.strip(),'False')
        finally:gate.release()
    def test_other_resident_model_unloaded_before_switch(self):
        class Response:
            def raise_for_status(self):pass
            def json(self):return {'models':[{'name':'other:latest'},{'name':'selected:latest'}]}
        class Client:
            def __init__(self):self.calls=[]
            def get(self,url):return Response()
            def post(self,url,json):self.calls.append(json);return Response()
        client=Client();prepare_model(client,'selected')
        self.assertEqual(client.calls,[{'model':'other:latest','keep_alive':0,'stream':False}])

if __name__=='__main__':unittest.main()
