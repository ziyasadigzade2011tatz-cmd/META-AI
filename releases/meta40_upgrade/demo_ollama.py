"""Live Ollama smoke test on an included disposable sample, no live META edits."""
import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE/'core'))
from meta40.engine import run, Ollama


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='qwen2.5-coder:14b')
    args = parser.parse_args()
    events = []
    with TemporaryDirectory(prefix='meta40-demo-') as temp:
        root = Path(temp)
        (root/'calc.py').write_text('def add(a, b):\n    return a - b\n', encoding='utf-8')
        (root/'test_calc.py').write_text('import unittest\nfrom calc import add\n\n'
            'class TestAdd(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(add(2, 3), 5)\n', encoding='utf-8')
        def emit(kind, data):
            events.append({'type':kind,'data':data})
            print(kind+': '+json.dumps(data,ensure_ascii=False), flush=True)
        def preview(root, edits, snapshot):
            return {'status':'preview_only','files':list(edits),'content':edits,'applied':False}
        result = run(root, 'Прочитай calc.py и test_calc.py. Запусти тесты, исправь ошибку add, '
                     'повтори тесты и заверши задачу. Не меняй тест. Не добавляй другие файлы.',
                     Ollama(args.model),preview,emit,max_steps=10,seconds=420,allow_tests=True)
        report = {'model':args.model,'result':result,'events':events,
                  'live_file_unchanged':(root/'calc.py').read_text()=='def add(a, b):\n    return a - b\n'}
        (HERE/'LIVE_DEMO_RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Result: '+result['status'])
        passed = result['tests'] and result['tests'][-1]['status']=='passed'
        return 0 if passed and result.get('proposal') else 1


if __name__ == '__main__': raise SystemExit(main())
