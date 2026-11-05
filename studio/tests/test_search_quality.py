import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.search_ranking import rank,chunks,allowed
from meta5.web_verify import verify,NO_EVIDENCE
from meta5.citations import LinkFilter
from meta5.privacy import sensitive

class SearchQualityTests(unittest.TestCase):
    def test_rrf_duplicates_domain_filter_and_diversity(self):
        first=[{'url':'https://t.me/random','title':'Керамика'},*({'url':'https://museum.example.org/page'+str(i),'title':'Керамика','snippet':'История керамики'} for i in range(4))]
        second=[{'url':'https://museum.example.org/page0?utm_source=x','title':'Керамика'},{'url':'https://archive.example.org/ceramics','title':'Керамика'}]
        result,excluded=rank([first,second],'История керамики')
        self.assertEqual(len(result),3)
        self.assertEqual(len([r for r in result if 'museum.example' in r['url']]),2)
        self.assertFalse(any('t.me' in r['url'] for r in result))
        self.assertTrue(any(r['reason']=='domain_policy' for r in excluded))
        self.assertTrue(allowed('https://t.me/channel','Найди канал в телеграм'))
    def test_claim_verification_drops_unsupported(self):
        source={'opened':True,'url':'https://observatory.example.org/a','chunks':[{'text':'Спектр измерен прибором в лаборатории.'}]}
        draft='Спектр измерен прибором в лаборатории. Измерение доказывает существование жизни.'
        parser=lambda _: {'checks':[{'claim':0,'status':'supported','fragment':1,'quote':'Спектр измерен прибором в лаборатории.'},{'claim':1,'status':'unsupported'}]}
        result,trace=verify(draft,{'sources':[source]},parser)
        self.assertIn('Спектр измерен',result);self.assertNotIn('жизни',result)
        self.assertEqual(trace['claims'][1]['status'],'unsupported')
    def test_invalid_quote_and_verifier_failure_close(self):
        evidence={'sources':[{'opened':True,'url':'https://example.org','chunks':[{'text':'Длина образца составляет пять сантиметров.'}]}]}
        bad=lambda _: {'checks':[{'claim':0,'status':'supported','fragment':1,'quote':'Выдуманная цитата про другое.'}]}
        self.assertEqual(verify('Свойство образца подтверждено.',evidence,bad)[0],NO_EVIDENCE)
        self.assertEqual(verify('Любое утверждение.',evidence,lambda _:'broken json')[0],NO_EVIDENCE)
    def test_conflicting_fragments_are_visible(self):
        evidence={'sources':[{'opened':True,'url':'https://one.example.org','chunks':[{'text':'По первому отчёту глубина составляет десять метров.'}]},{'opened':True,'url':'https://two.example.org','chunks':[{'text':'По второму отчёту глубина составляет двенадцать метров.'}]}]}
        parser=lambda _: {'checks':[{'claim':0,'status':'contradicts','fragment':1,'quote':'глубина составляет десять метров','other_fragment':2,'other_quote':'глубина составляет двенадцать метров'}]}
        result,_=verify('Глубина составляет десять метров.',evidence,parser);self.assertIn('расходятся',result)
    def test_unopened_and_fenced_links_filtered(self):
        f=LinkFilter([{'url':'https://fake.example.org','opened':False}],strict=True)
        self.assertNotIn('https://',f.feed('```text\nhttps://fake.example.org\n```',final=True))
    def test_empty_and_timeouts_do_not_fabricate(self):
        import meta5.research as module
        plan={'query':'Архитектура мостов','queries':['Архитектура мостов'],'context':{}}
        with patch.object(module,'cache',return_value=[]),patch.object(module,'web_search',side_effect=TimeoutError),patch.object(module,'database',side_effect=OSError):
            with self.assertRaises(ValueError):module.research([],plan_override=plan)
        self.assertEqual(verify('Любой текст.',{'sources':[]},lambda _: {})[0],NO_EVIDENCE)
    def test_educational_token_not_secret(self):
        self.assertFalse(sensitive('Что такое токен?'));self.assertTrue(sensitive('пароль личный'))

if __name__=='__main__':unittest.main()
