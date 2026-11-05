import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.memory import Memory
from meta5.memory_summaries import checkpoint,recall

class SummaryTests(unittest.TestCase):
    def test_scoped_and_explicit_recall(self):
        with tempfile.TemporaryDirectory() as d,patch('meta5.memory_summaries.Embeddings.metadata',side_effect=OSError):
            m=Memory(Path(d)/'memory.sqlite');m.summary('A','Акварельные наброски')
            self.assertEqual(recall(m,'B','Акварельные наброски'),[])
            self.assertEqual(len(recall(m,'A','Акварельные наброски')),1)
            self.assertEqual(len(recall(m,'B','Помнишь, мы говорили: акварельные наброски?')),1)
    def test_snapshot_interval_and_private_exclusion(self):
        with tempfile.TemporaryDirectory() as d:
            m=Memory(Path(d)/'memory.sqlite')
            turns=[{'role':'user' if i%2==0 else 'assistant','content':'План занятия'} for i in range(6)]
            self.assertTrue(checkpoint(m,'A',turns));self.assertEqual(m.summary('B'),'')
            self.assertFalse(checkpoint(m,'A',turns[:5]))

if __name__=='__main__':unittest.main()
