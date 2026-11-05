import collections,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.slang import Glossary,ROOT

class SlangTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.g=Glossary(Path(self.tmp.name)/'slang.sqlite')
    def tearDown(self):self.tmp.cleanup()
    def test_seed_schema_balance(self):
        rows=json.loads((ROOT/'slang.json').read_text('utf-8'));self.assertGreaterEqual(len(rows),300)
        for count in collections.Counter(r['domain'] for r in rows).values():self.assertLessEqual(count/len(rows),.08)
        for r in rows:
            for key in ('term','forms','meaning','domain','register','language','confidence','status','source','seen_count','chats_count','first_seen','last_seen','context_hints'):self.assertIn(key,r)
    def test_user_commands_and_rejection(self):
        self.g.command('/slang add шурум=понятное обозначение')
        self.assertEqual(self.g.resolve('шурум')['normalized'],'понятное обозначение')
        self.g.command('/slang reject шурум');self.assertEqual(self.g.resolve('шурум')['normalized'],'шурум')
        self.g.command('/slang confirm шурум');self.assertIn('шурум',self.g.command('/slang export'))
        self.g.command('/slang remove шурум');self.assertEqual(self.g.resolve('шурум')['normalized'],'шурум')
    def test_ambiguous_and_boundaries(self):
        self.assertIsNotNone(self.g.resolve('кк')['question'])
        self.assertEqual(self.g.resolve('какой')['normalized'],'какой')
    def test_candidate_not_substituted(self):
        self.g.add('шурум','возможное обозначение',source='context',status='candidate',confidence=.5)
        result=self.g.resolve('шурум');self.assertEqual(result['normalized'],'шурум');self.assertEqual(len(result['candidates']),1)
    def test_private_definitions_rejected(self):
        for value in ('пароль скрыт','ключ api_key секретен','адрес улица неизвестна','email a@b.net'):
            with self.assertRaises(ValueError):self.g.add('шурум',value)

if __name__=='__main__':unittest.main()
