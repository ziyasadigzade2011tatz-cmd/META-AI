import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.normalizer import normalize

class NormalizerTests(unittest.TestCase):
    def test_layout_translit_stretch_typo_and_join(self):
        for source,target in [('ghbdtn','привет'),('privet','привет'),('оооочень','очень'),('прииивет','привет'),('тюея','тебя'),('мнэ','мне'),('какдела','как дела'),('привeт','привет')]:
            with self.subTest(source=source):self.assertEqual(normalize(source)['normalized'],target)
    def test_opaque_and_emoji_preserved(self):
        self.assertEqual(normalize('`ghbdtn`')['normalized'],'`ghbdtn`')
        self.assertEqual(normalize('`спс`')['normalized'],'`спс`')
        self.assertEqual(normalize('привет 🙂')['normalized'],'привет 🙂')
    def test_broken_json_retries_once_and_falls_back(self):
        calls=[]
        def broken(messages):calls.append(messages);return '{broken'
        r=normalize('шурум',client=broken)
        self.assertEqual(len(calls),2);self.assertEqual(r['normalized'],'шурум');self.assertTrue(r['parser_failed'])
    def test_clean_text_skips_model(self):
        def fail(_):raise AssertionError('Unnecessary model call')
        self.assertEqual(normalize('Привет',client=fail)['normalized'],'Привет')
    def test_private_text_never_calls_parser(self):
        def fail(_):raise AssertionError('Private text parsed')
        self.assertEqual(normalize('пароль ghbdtn',client=fail)['normalized'],'пароль ghbdtn')
    def test_parser_cannot_invent_named_entity(self):
        import json
        def wrong(_):return json.dumps({'normalized':'Другое название','intent':'chat','topic':'','entities':['Другое'],'needs_search':False,'confidence':.9,'ambiguous':False,'unknown_terms':[],'tone':'neutral'})
        self.assertEqual(normalize('шурум',client=wrong)['normalized'],'шурум')

if __name__=='__main__':unittest.main()
