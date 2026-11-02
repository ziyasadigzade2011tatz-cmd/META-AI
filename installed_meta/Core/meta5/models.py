import re
from .storage import STATE,read_json,atomic_json

PROFILE_FILE=STATE/'models.json'


def profiles():
    from .storage import CORE
    fallback=read_json(CORE/'meta5_models_seed.json',{'chat':'qwen2.5:3b','code':'qwen2.5-coder:7b','vision':'qwen2.5vl:3b','source':'fallback_not_benchmarked','context':8192})
    return read_json(PROFILE_FILE,fallback)


def select(mode='chat',explicit='auto'):
    data=profiles()
    if explicit=='auto-quality':return data.get('quality',data.get(mode,data['chat'])),'local_quality_profile'
    if explicit and explicit not in ('auto','meta-core'):
        if not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}',explicit):raise ValueError('Неверное имя модели')
        return explicit,'manual'
    return data.get(mode,data['chat']),data.get('source','configured')


def from_benchmark(report):
    rows=report['results'];groups={}
    for row in rows:groups.setdefault(row['model'],[]).append(row)
    def best(kind):
        ranked=[]
        candidates=groups
        if kind=='code' and any('coder' in n and any(r.get('passed') and r['test']=='code' for r in it) for n,it in groups.items()):candidates={n:it for n,it in groups.items() if 'coder' in n}
        for name,items in candidates.items():
            relevant=[r for r in items if r['test']==kind and r.get('passed')]
            if relevant:ranked.append((min(r['seconds'] for r in relevant),name))
        return min(ranked)[1] if ranked else ('qwen2.5:3b' if kind=='context' else 'qwen2.5-coder:7b')
    # Chat suitability includes correct domain interpretation. Explicit context
    # resolution still runs before every model call and is not delegated to it.
    result={'chat':best('grounded_context'),'quality':best('context'),'code':best('code'),'vision':'qwen2.5vl:3b','source':'local_smoke_benchmark',
            'context':8192,'hardware':report['hardware'],'results':rows,'benchmark_scope':report['scope']}
    atomic_json(PROFILE_FILE,result);return result
