"""Bounded conversation context and conservative intent hints for META Code.
Hints never bypass tool and approval checks.
"""
import re

def intent(task):
    t = task.casefold()
    self_terms = ("улучши себя", "улучшить себя", "прокачай себя", "самоулучш", "improve yourself", "upgrade yourself", "улучши мета", "улучши meta")
    research_terms = ("найди", "поищи", "документаци", "в интернете", "latest", "look up", "research", "search online")
    if any(x in t for x in self_terms): return "self_development"
    if any(x in t for x in research_terms): return "research"
    if any(x in t for x in ("исправ", "почин", "баг", "fix", "debug")): return "debug"
    return "general"

def bounded_history(history, max_items=12, max_chars=12000):
    if not isinstance(history, (list,tuple)): return []
    kept=[]; total=0
    for item in reversed(history[-max_items*3:]):
        if not isinstance(item,dict) or item.get("role") not in ("user","assistant"): continue
        content=item.get("content", "")
        if not isinstance(content,str): continue
        content=content[:2000]
        if total+len(content)>max_chars: break
        kept.append({"role":item["role"],"content":content})
        total+=len(content)
        if len(kept)>=max_items: break
    return list(reversed(kept))

def context_note(task, paths):
    mode=intent(task)
    note={"intent_hint":mode, "intent_hint_is_not_authority":True}
    if mode=="self_development":
        note["self_development"]={"target":"META software, not user", "core_access":"Only paths in selected workspace are accessible", "workflow":"inspect -> propose -> test -> review -> human approval", "no_auto_install":True}
    return note
