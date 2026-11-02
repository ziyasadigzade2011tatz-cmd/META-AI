"""Conversation trimming, intent cues, and evidence-aware task context.

Intent hints are advisory, not permissions and not proof of task completion.
"""
from __future__ import annotations
import re

SELF_TERMS = ('улучши себя', 'улучшить себя', 'прокачай себя', 'самоулучш',
              'улучши мета', 'улучши meta', 'improve yourself', 'upgrade yourself',
              'свой код', 'свой движок', 'тебя самого')
RESEARCH_TERMS = ('найди', 'поищи', 'документаци', 'в интернете', 'в сети',
                  'latest', 'look up', 'research', 'search online', 'актуальн', 'проверь в сети')
CODE_TERMS = ('напиши код', 'исправ', 'почин', 'баг', 'fix', 'debug',
              'создай файл', 'реализуй', 'добавь функцию', 'refactor')


def intent(task: str) -> str:
    text = str(task).casefold()
    if any(x in text for x in SELF_TERMS): return 'self_development'
    if any(x in text for x in CODE_TERMS): return 'coding'
    if any(x in text for x in RESEARCH_TERMS): return 'research'
    return 'general'


def bounded_history(history, max_items=12, max_chars=10000):
    if not isinstance(history, (list, tuple)): return []
    out = []
    budget = max_chars
    for msg in reversed(history[-40:]):
        if not isinstance(msg, dict) or msg.get('role') not in ('user', 'assistant'): continue
        content = msg.get('content')
        if not isinstance(content, str) or not content.strip(): continue
        trimmed = content[:min(1800, budget)]
        if not trimmed: break
        out.append({'role': msg['role'], 'content': trimmed})
        budget -= len(trimmed)
        if len(out) >= max_items or budget <= 0: break
    return list(reversed(out))


def context_note(task: str, paths=None):
    mode = intent(task)
    return {
        'intent_hint': mode,
        'hint_is_not_verified': True,
        'self_development': {
            'target': 'installed META software, not the user',
            'workflow': 'self_inspect -> analyze -> write patch inside selected Project -> test -> pending approval',
            'core_source_read_only': True,
            'core_install_automatic': False,
        } if mode == 'self_development' else None,
    }
