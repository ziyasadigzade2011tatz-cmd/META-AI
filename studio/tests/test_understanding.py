import collections,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from run_quality import evaluate

class UnderstandingTests(unittest.TestCase):
    def test_120_dialogues_and_topic_balance(self):
        cases=json.loads(Path(__file__).with_name('quality_cases.json').read_text('utf-8'));self.assertGreaterEqual(len(cases),120)
        for count in collections.Counter(c['topic'] for c in cases).values():self.assertLessEqual(count/len(cases),.08)
        for case in cases:
            with self.subTest(case=case['id'],category=case['category']):self.assertTrue(evaluate(case))

if __name__=='__main__':unittest.main()
