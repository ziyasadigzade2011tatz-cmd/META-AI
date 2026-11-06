"""Allocation/guard tests only; not evidence of tokenizer parity with Ollama."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from meta5.token_budget import limits,fit,prepare,BudgetExceeded


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

    def test_unvalidated_feature_is_disabled(self):
        with self.assertRaises(BudgetExceeded):prepare([{'role':'user','content':'hello'}],'qwen3.5:4b',8192,count=lambda rows:1)


if __name__=='__main__':unittest.main()
