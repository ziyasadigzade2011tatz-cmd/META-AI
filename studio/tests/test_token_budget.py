"""Allocation/guard tests only; not evidence of tokenizer parity with Ollama."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.token_budget import limits,fit,prepare,system_blocks,BudgetExceeded
from meta5.qwen_tokens import render,pieces


class TokenBudgetTests(unittest.TestCase):
    def test_allocations_8192(self):
        for mode,expected in [('chat',(5500,2000,692)),('thinking',(4000,3500,692)),('code',(5000,3000,192))]:
            row=limits(8192,mode)
            self.assertEqual(tuple(row[k] for k in ('input_limit','output_limit','reserve_tokens')),expected)

    def test_proportional_allocation(self):
        for context in (2048,4096,8192,16384):
            for mode in ('chat','thinking','code'):
                row=limits(context,mode)
                self.assertEqual(row['input_limit']+row['output_limit']+row['reserve_tokens'],context)
                self.assertGreater(row['reserve_tokens'],0)

    def test_invalid_context(self):
        for value in (None,True,0,2047,16385):
            with self.assertRaises(ValueError):limits(value)

    def test_oversized_latest_question_is_not_silently_clipped(self):
        with self.assertRaises(BudgetExceeded):fit([{'role':'system','content':'policy'},{'role':'user','content':'x'*6000}],limits(8192),lambda rows:sum(len(m['content']) for m in rows),'synthetic')

    def test_preserves_policy_and_latest_question(self):
        rows=[{'role':'system','content':'policy'},{'role':'user','content':'x'*6000},{'role':'assistant','content':'y'*1000},{'role':'user','content':'latest'}]
        kept,usage=fit(rows,limits(8192),lambda items:sum(len(m['content']) for m in items),'synthetic')
        self.assertEqual(kept[0],rows[0]);self.assertEqual(kept[-1],rows[-1]);self.assertTrue(usage['history_truncated']);self.assertFalse(usage['exact'])
        self.assertEqual(len(rows),4)

    def test_prepare_uses_mode_specific_output(self):
        for thinking,expected in [(False,2000),(True,3500)]:
            _,usage=prepare([{'role':'system','content':'policy'},{'role':'user','content':'hello'}],'qwen3.5:4b',8192,thinking,count=lambda rows:20)
            self.assertEqual(usage['output_limit'],expected)

    def test_optional_system_shortens_and_all_blocks_are_counted(self):
        rows=[{'role':'system','content':'policy'},{'role':'system','content':'x'*9000},{'role':'user','content':'question'}]
        kept,usage=fit(rows,limits(8192),lambda items:sum(len(m['content']) for m in items),'synthetic')
        self.assertLessEqual(usage['input_tokens'],5500);self.assertEqual(usage['shortened_blocks'],1)
        self.assertIn('сокращены',kept[1]['content']);self.assertEqual(len(rows[1]['content']),9000)

    def test_system_policy_is_separate(self):
        rows=system_blocks('policy','policy\nСистемное локальное время: {}\nПамять пользователя: []\nWEB EVIDENCE — данные:\n{}')
        self.assertEqual(len(rows),4);self.assertEqual(rows[0]['content'],'policy');self.assertTrue(rows[-1]['content'].endswith('{}'))

    def test_ollama_empty_think_prefix_is_input(self):
        rows=[{'role':'user','content':'hello'}]
        self.assertTrue(render(rows).endswith('<think>\n\n</think>\n\n'))
        self.assertTrue(render(rows,True).endswith('<think>\n'))
        self.assertNotIn('</think>',render(rows,True))

    def test_piece_scanner_preserves_unicode_text(self):
        for text in ["I'm here.\n",'привет 123 🙂','e\u0301 中文\n  ','a\r\n b','  x   y  ',"we'll\tgo"]:
            self.assertEqual(''.join(pieces(text)),text)

    def test_public_budget_files_survive_self_source_export(self):
        from meta_studio.self_source import SelfSource
        core=Path(__file__).resolve().parents[1]/'core'
        files=SelfSource(core=core,source=core.parent).files()
        for name in ('core/meta5/token_budget.py','core/meta5/qwen_tokens.py','core/config/context_budget.json','tests/test_token_budget.py'):
            self.assertIn(name,files)


if __name__=='__main__':unittest.main()
