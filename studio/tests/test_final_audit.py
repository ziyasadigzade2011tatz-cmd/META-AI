import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.python_child import argv,dispatch
from meta5.mcp_client import validate_server
from meta5.native_tools import action
from meta5 import transport

class FinalAuditTests(unittest.TestCase):
    def test_frozen_python_is_explicit_child_mode(self):
        with patch.object(sys,'frozen',True,create=True):
            self.assertEqual(argv('-c','pass'),[sys.executable,'--meta5-python','-c','pass'])
            self.assertEqual(argv('-c','pass',executable='other-python.exe'),['other-python.exe','-c','pass'])
    def test_python_child_preserves_arguments(self):
        previous=sys.argv
        try:
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/'result.json'
                code='import json,sys;\nwith open(sys.argv[1],"w") as stream: stream.write(json.dumps(sys.argv[2:]))'
                dispatch(['-I','-c',code,str(path),'sample'])
                self.assertEqual(json.loads(path.read_text()),['sample'])
        finally:sys.argv=previous
    def test_native_protocol_keeps_core_instructions(self):
        seen=[]
        def complete(model,messages,**kw):
            seen.extend(messages);return {'message':{'tool_calls':[{'function':{'name':'finish','arguments':{'summary':'done'}}}]}}
        with patch.object(transport,'complete',side_effect=complete):action('fixture',[{'role':'system','content':'REFERENCE_POLICY_MUST_SURVIVE'},{'role':'user','content':'task'}],[],10,{})
        self.assertIn('REFERENCE_POLICY_MUST_SURVIVE',seen[0]['content'])
    def test_mcp_invalid_types_are_validation_errors(self):
        for config in ({'url':12},{'url':'http://127.0.0.1:8000/mcp','tools':[12]}, {'url':'https://example.org'}):
            with self.assertRaises(ValueError):validate_server('local',config)
    def test_stale_machine_tool_path_does_not_hide_available_node(self):
        from meta5 import storage,process
        with tempfile.TemporaryDirectory() as d,patch.object(storage,'CORE',Path(d)),patch.object(process.shutil,'which',side_effect=lambda name:'available-node.exe' if name=='node' else None):
            (Path(d)/'meta5_tools.json').write_text(json.dumps({'node':'Z:/missing/node.exe','edge':'Z:/missing/edge.exe'}))
            cap=process.capabilities();self.assertEqual(cap['node'],'available-node.exe');self.assertIsNone(cap['edge'])
    def test_legacy_database_closes_and_rejects_private_values(self):
        import importlib.util,os,sqlite3
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'META_DATA_DIR':d}):
            spec=importlib.util.spec_from_file_location('legacy_memory_fixture',Path(__file__).resolve().parents[1]/'core/memory.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertFalse(module.remember('Мой пароль: fixture'))
            self.assertTrue(module.remember('Предпочитаю краткие ответы'))
            with module.connect() as connection:self.assertEqual(connection.execute('SELECT count(*) FROM memories').fetchone()[0],1)
            with self.assertRaises(sqlite3.ProgrammingError):connection.execute('SELECT 1')

if __name__=='__main__':unittest.main()
