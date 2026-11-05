import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.memory import Memory
from meta5.memory_extract import parse,observe,command

def parser(text):return lambda messages:{'facts':[{'fact':text,'evidence':text,'type':'preference','confidence':.9,'ttl_days':None}]}
class ExtractTests(unittest.TestCase):
    def test_evidence_and_privacy(self):
        self.assertEqual(parse('Я люблю орнаменты',parser('Я люблю полёты')),[])
        self.assertEqual(parse('Я сегодня устал',parser('Я сегодня устал')),[])
        self.assertEqual(parse('Мой пароль: abcdef',parser('Мой пароль: abcdef')),[])
        self.assertEqual(len(parse('Я люблю орнаменты',parser('Я люблю орнаменты'))),1)
    def test_repeat_confirm_forget_and_history(self):
        with tempfile.TemporaryDirectory() as d,patch('meta5.memory_extract.semantic_duplicate',return_value=None):
            m=Memory(Path(d)/'memory.sqlite')
            f=parse('Меня зовут Алекс',parser('Меня зовут Алекс'))[0]
            pid=observe(m,f,'chat','event1');self.assertEqual(m.records()[0]['status'],'candidate')
            observe(m,f,'chat','event1');self.assertEqual(m.records()[0]['status'],'candidate')
            observe(m,f,'chat','event2');self.assertEqual(m.records()[0]['status'],'confirmed')
            new=parse('Меня зовут Саша',parser('Меня зовут Саша'))[0];newid=observe(m,new,'chat','event3')
            command(m,'/memory confirm '+newid)
            self.assertEqual(next(r for r in m.records() if r['id']==pid)['status'],'superseded')
            with m.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM memory_history').fetchone()[0],1)
            command(m,'/memory forget Саша');self.assertFalse(any(r['id']==newid for r in m.records()))

if __name__=='__main__':unittest.main()
