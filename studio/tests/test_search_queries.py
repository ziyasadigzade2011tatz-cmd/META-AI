import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.search_query_builder import build

class SearchQueriesTests(unittest.TestCase):
    def test_missing_reference_stops_search(self):
        self.assertEqual(build([{'role':'user','content':'А это?'}])['queries'],[])
    def test_no_extra_year_or_product(self):
        def client(_):return '{"query":"Python error 2099"}'
        r=build([{'role':'user','content':'Python ошибка'}],client)
        self.assertNotIn('2099',' '.join(r['queries']));self.assertTrue(r['technical'])
    def test_private_query_rejected(self):
        with self.assertRaises(ValueError):build([{'role':'user','content':'пароль личный'}])
    def test_non_technical_language_preserved(self):
        r=build([{'role':'user','content':'найди определение'}]);self.assertEqual(r['queries'],['найди определение'])
    def test_public_version_not_treated_as_secret(self):
        self.assertIn('3.12',build([{'role':'user','content':'Python 3.12 документация'}])['queries'][0])

if __name__=='__main__':unittest.main()
