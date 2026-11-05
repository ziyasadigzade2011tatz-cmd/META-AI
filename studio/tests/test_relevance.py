import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.relevance import select
from meta5.context import topic_state

SUBJECTS=('география','литература','транспорт','ремесло','музыка','образование','природа','быт','работа','астрономия','архитектура','язык','одежда','спорт','кулинария','садоводство')

class RelevanceTests(unittest.TestCase):
    def test_greeting_and_unrelated_queries_get_no_memory(self):
        for subject in SUBJECTS:
            with self.subTest(subject=subject):
                facts=[{'id':'1','kind':'preference','value':'Я люблю '+subject}]
                self.assertEqual(select('Привет',facts),[])
                self.assertEqual(select('Расскажи о другом',facts),[])
                self.assertEqual(select(subject,facts),facts)
    def test_no_topic_between_chats(self):
        for subject in SUBJECTS:
            self.assertTrue(topic_state([{'role':'user','content':subject}]))
            self.assertIsNone(topic_state([{'role':'user','content':'Привет'}]))
    def test_topic_decays(self):
        for subject in SUBJECTS:
            history=[{'role':'user','content':s} for s in (subject,'А?','Это?','Нет')]
            self.assertIsNone(topic_state(history))

if __name__=='__main__':unittest.main()
