import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.memory import Memory

class RetrievalTests(unittest.TestCase):
    def test_profile_category_isolation(self):
        with tempfile.TemporaryDirectory() as d,patch('meta5.memory_retrieval.Embeddings.metadata',side_effect=OSError):
            m=Memory(Path(d)/'memory.sqlite')
            for fact in ('Я люблю керамику','Меня зовут Алекс','У меня ноутбук с 16 ГБ ОЗУ'):m.add(fact)
            for query in ('Привет','Что такое керамика?','Как приготовить рис?','Расскажи о себе','Как устроен двигатель?'):
                self.assertEqual(m.relevant(query),[],query)
            self.assertEqual(len(m.relevant('Как меня зовут?')),1)
            self.assertEqual(len(m.relevant('Помнишь, я люблю керамику?')),1)
            self.assertTrue(all('зовут' not in r['value'] for r in m.relevant('Какая модель потянет на моём ноутбуке?')))
    def test_candidate_and_budget(self):
        with tempfile.TemporaryDirectory() as d,patch('meta5.memory_retrieval.Embeddings.metadata',side_effect=OSError):
            m=Memory(Path(d)/'memory.sqlite');pid=m.add('Я люблю акварель')
            with m.db() as c:c.execute("UPDATE facts SET status='candidate' WHERE id=?",(pid,))
            self.assertEqual(m.relevant('Я люблю акварель?'),[])

if __name__=='__main__':unittest.main()
