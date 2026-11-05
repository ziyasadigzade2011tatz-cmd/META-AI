"""Offline pipeline metrics, not a measurement of free-form LLM response quality."""
import argparse,collections,json,os,subprocess,sys,tempfile,types
from pathlib import Path
repo=Path(__file__).resolve().parents[2];sys.path.insert(0,str(repo/'studio/core'))

def baseline(commit):
    package=types.ModuleType('_meta_baseline');package.__path__=[];sys.modules[package.__name__]=package
    storage=types.ModuleType('_meta_baseline.storage');storage.STATE=Path(tempfile.gettempdir());sys.modules[storage.__name__]=storage
    advanced=types.ModuleType('_meta_baseline.advanced');advanced.semantic=lambda *args:[];sys.modules[advanced.__name__]=advanced
    result={}
    for name in ('context','memory'):
        code=subprocess.check_output(['git','show',commit+':studio/core/meta5/'+name+'.py'],cwd=repo).decode('utf-8')
        module=types.ModuleType('_meta_baseline.'+name);module.__package__='_meta_baseline';sys.modules[module.__name__]=module;exec(compile(code,name+'.py','exec'),module.__dict__);result[name]=module
    return result

def evaluate(case,old=None):
    text=case['messages'][-1]['content'];category=case['category']
    if category=='anti_bias':
        fact={'id':'fact','kind':'preference','value':case['unrelated_fact']}
        if old:
            cls=type('SampleMemory',(old['memory'].Memory,),{'list':lambda self:[fact]})
            selected=cls().relevant(text)
        else:
            from meta5.relevance import select
            selected=select(text,[fact])
        return not selected
    if category=='reference':
        if old:return False
        from meta5.context import standalone
        r=standalone(case['messages']);return not r['ambiguous'] and case['entity'] in r['standalone_query']
    if category=='learning':
        if old:return False
        from meta5.slang import Glossary
        from meta5.slang_learning import Learner
        from datetime import datetime,timezone,timedelta
        with tempfile.TemporaryDirectory() as folder:
            g=Glossary(Path(folder)/'slang.sqlite');learner=Learner(g);mode=case['mode'];meaning='условное обозначение: '+case['topic']
            if mode=='explicit':return learner.explicit('шурум это '+meaning,'a')['status']=='confirmed'
            if mode=='promote':
                for chat in ('a','a','b'):r=learner.observe('шурум',chat,meaning,confidence=.9)
                return r['status']=='confirmed'
            if mode=='contradiction':
                learner.observe('шурум','a',meaning,confidence=.9)
                return learner.observe('шурум','a',contradiction=True)['status']=='rejected'
            if mode=='private':return learner.observe('шурум','a','пароль неизвестен') is None
            if mode=='one_chat':
                for _ in range(3):r=learner.observe('шурум','a',meaning,confidence=.9)
                return r['status']=='candidate'
            learner.observe('шурум','a');return learner.expire(datetime.now(timezone.utc)+timedelta(days=91))==1
    if old:result={'normalized':text,'question':None}
    else:
        from meta5.normalizer import normalize
        result=normalize(text)
    if category=='rough':return text==case['messages'][-1]['content'] and not any(w in result['normalized'].casefold() for w in ('нельзя так','не ругай','не матерись'))
    if category=='ambiguous':return bool(result.get('question'))
    if 'exact' in case:return result['normalized']==case['exact']
    return case['contains'].casefold() in result['normalized'].casefold()

def run(commit=None):
    cases=json.loads((repo/'studio/tests/quality_cases.json').read_text('utf-8'));old=baseline(commit) if commit else None
    counts=collections.defaultdict(lambda:{'passed':0,'total':0});failures=[]
    for case in cases:
        passed=evaluate(case,old);row=counts[case['category']];row['total']+=1;row['passed']+=int(passed)
        if not passed:failures.append({'id':case['id'],'category':case['category']})
    return {'scope':'offline component checks; no generated-answer accuracy claim','baseline_commit':commit,'categories':dict(counts),'failures':failures}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--baseline');parser.add_argument('--out');args=parser.parse_args();report=run(args.baseline)
    if args.out:Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
