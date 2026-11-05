"""82 fixture checks plus semantic retrieval; component metrics, not LLM accuracy."""
import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.memory import Memory
from meta5.memory_extract import parse,observe,command
from meta5.memory_retrieval import retrieve
from meta5.embeddings import Embeddings

CASES=json.loads(Path(__file__).with_name('memory_cases.json').read_text('utf-8'))

class MemoryCases(unittest.TestCase):
    def test_thirty_unrelated_prompts_receive_zero(self):
        with tempfile.TemporaryDirectory() as d,patch('meta5.memory_retrieval.Embeddings.metadata',side_effect=OSError):
            m=Memory(Path(d)/'memory.sqlite')
            for topic,activity,_ in CASES['hobbies']:m.add('Я люблю '+activity,'preference')
            for query in CASES['unrelated']:
                with self.subTest(query=query):self.assertEqual(m.relevant(query),[])
    def test_twenty_hobby_recall_and_lifecycle(self):
        with tempfile.TemporaryDirectory() as d,patch('meta5.memory_retrieval.Embeddings.metadata',side_effect=OSError),patch('meta5.memory_extract.semantic_duplicate',return_value=None):
            m=Memory(Path(d)/'memory.sqlite')
            for topic,activity,_ in CASES['hobbies']:
                with self.subTest(topic=topic):
                    text='Я люблю '+activity
                    raw={'facts':[{'fact':text,'evidence':text,'type':'preference','confidence':.95,'ttl_days':None}]}
                    fact=parse(text,lambda _:raw)[0];pid=observe(m,fact,'A',topic+'1')
                    self.assertEqual(next(r for r in m.records() if r['id']==pid)['status'],'candidate')
                    observe(m,fact,'A',topic+'2')
                    self.assertTrue(any(r['id']==pid for r in m.relevant('Помнишь, я люблю '+activity+'?')))
                    self.assertEqual(m.add(text,'preference'),pid)
    def test_twelve_private_or_transient_inputs(self):
        inputs=['Мой пароль: пример','Моя карта 4111 1111 1111 1111','Мой паспорт 1234 567890','Мой адрес проживания Примерная','Моя почта sample@example.org','Мой файл C:\\private\\sample.txt','Мой token=placeholder','Мой api_key=placeholder','Я сегодня устал','Я сейчас голоден','У меня завтра встреча','Мне сегодня грустно']
        for text in inputs:
            with self.subTest(text=text):
                raw={'facts':[{'fact':text,'evidence':text,'type':'fact','confidence':1.,'ttl_days':None}]}
                self.assertEqual(parse(text,lambda _:raw),[])
    def test_semantic_no_shared_subject_words(self):
        with tempfile.TemporaryDirectory() as d:
            m=Memory(Path(d)/'memory.sqlite');pid=m.add('Я люблю читать романы','preference')
            engine=Embeddings(m.path,lambda _:[[1.,0.]])
            engine.index(m.indexable())
            with patch.object(engine,'metadata',return_value=('mock','test')):
                result,trace=retrieve(m,'Мне нравится художественная проза?',engine=engine)
            self.assertEqual([r['id'] for r in result],[pid]);self.assertEqual(trace[0]['reason'],'hybrid')

if __name__=='__main__':unittest.main()
