import sys,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.slang import Glossary
from meta5.slang_learning import Learner

class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.g=Glossary(Path(self.tmp.name)/'slang.sqlite');self.l=Learner(self.g)
    def tearDown(self):self.tmp.cleanup()
    def test_explicit_definition_and_correction(self):
        r=self.l.explicit('шурум это короткое обозначение','chat-a');self.assertEqual(r['status'],'confirmed')
        r=self.l.explicit('нет, это значит другое обозначение','chat-a');self.assertEqual(r['meaning'][0]['definition'],'другое обозначение')
    def test_three_observations_two_chats(self):
        for chat in ('chat-a','chat-a','chat-b'):r=self.l.observe('шурум',chat,'новое обозначение',confidence=.8)
        self.assertEqual(r['status'],'confirmed');self.assertEqual(r['chats_count'],2)
    def test_unknown_sightings_are_not_confirmation(self):
        for chat in ('chat-a','chat-a','chat-b','chat-b'):r=self.l.observe('шурум',chat)
        self.assertEqual(r['status'],'candidate')
    def test_rejected_not_repeated(self):
        self.l.observe('шурум','chat-a','обозначение',confidence=.8)
        self.l.observe('шурум','chat-a',contradiction=True)
        self.assertEqual(self.l.observe('шурум','chat-b','обозначение',confidence=.8)['status'],'rejected')
    def test_expiry(self):
        self.l.observe('шурум','chat-a')
        self.assertEqual(self.l.expire(datetime.now(timezone.utc)+timedelta(days=91)),1)
    def test_no_private_observations(self):
        self.assertIsNone(self.l.observe('шурум','chat-a','пароль не записывай'))
        self.assertIsNone(self.l.explicit('шурум это адрес улица неизвестна','chat-a'))

if __name__=='__main__':unittest.main()
