import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5 import models

class ModelSelectionTests(unittest.TestCase):
    def test_benchmark_uses_all_results_not_fastest_single_success(self):
        report={'hardware':{},'scope':'test','results':[
            {'model':'fast','test':'grounded_context','passed':True,'seconds':.1},
            {'model':'fast','test':'grounded_context','passed':False,'seconds':.1},
            {'model':'accurate','test':'grounded_context','passed':True,'seconds':2},
            {'model':'accurate','test':'grounded_context','passed':True,'seconds':2}]}
        with patch.object(models,'atomic_json'),patch.object(models,'profiles',return_value={'chat':'fallback'}):result=models.from_benchmark(report)
        self.assertEqual(result['chat'],'accurate');self.assertEqual(result['quality'],'accurate')

if __name__=='__main__':unittest.main()
