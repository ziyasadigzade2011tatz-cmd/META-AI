import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.context import standalone,compact

class ContextTests(unittest.TestCase):
    def test_no_entity_means_question(self):
        self.assertTrue(standalone([{'role':'user','content':'А это?'}])['ambiguous'])
    def test_single_quoted_entity(self):
        r=standalone([{'role':'user','content':'обсуждаем «предмет»'},{'role':'assistant','content':'да'},{'role':'user','content':'Расскажи про это'}])
        self.assertFalse(r['ambiguous']);self.assertIn('предмет',r['standalone_query'])
    def test_multiple_entities_are_not_guessed(self):
        r=standalone([{'role':'user','content':'сравним «первый» и «второй»'},{'role':'user','content':'А он?'}])
        self.assertTrue(r['ambiguous'])
    def test_new_chat_does_not_reuse_anchor(self):
        standalone([{'role':'user','content':'предмет «первый»'},{'role':'user','content':'А это?'}])
        self.assertTrue(standalone([{'role':'user','content':'А это?'}])['ambiguous'])
    def test_recent_window_is_eight(self):
        messages=[{'role':'user','content':'вопрос '+str(i)} for i in range(30)]
        kept,_=compact(messages);self.assertEqual(len([m for m in kept if m['role']!='system']),8)

if __name__=='__main__':unittest.main()
