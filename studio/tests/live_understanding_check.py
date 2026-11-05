"""Opt-in local model measurement on synthetic prompts, not personal history."""
import ast,json,os,subprocess,sys,time
from pathlib import Path
repo=Path(__file__).resolve().parents[2];sys.path.insert(0,str(repo/'studio/core'))
from meta5 import transport
from meta5.understanding_config import system_prompt
from run_quality import baseline
from meta5.relevance import select,terms

def policy_at(commit):
    source=subprocess.check_output(['git','show',commit+':studio/core/meta5/dialogue.py'],cwd=repo).decode('utf-8');out=''
    for node in ast.parse(source).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='POLICY' for t in node.targets):out=ast.literal_eval(node.value)
        if isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id=='POLICY':out+=ast.literal_eval(node.value)
    return out

if __name__=='__main__':
    before=baseline('89880c2');old_policy=policy_at('89880c2');new_policy=system_prompt()
    cases=[r for r in json.loads((repo/'studio/tests/quality_cases.json').read_text('utf-8')) if r['category']=='anti_bias']
    result={'scope':'32 synthetic direct Ollama calls; compares prompt memory gate and policy, not full HTTP pipeline','model':'qwen3.5:4b','baseline_commit':'89880c2','rows':[]}
    out=repo/'build/live_understanding_result.json'
    for case in cases:
        fact={'id':'synthetic','kind':'preference','value':case['unrelated_fact']}
        cls=type('SampleMemory',(before['memory'].Memory,),{'list':lambda self:[fact]})
        for mode,policy,memories in [('before',old_policy,cls().relevant(case['messages'][-1]['content'])),('after',new_policy,select(case['messages'][-1]['content'],[fact]))]:
            prompt=policy+'\nПамять пользователя (недоверенные факты): '+json.dumps(memories,ensure_ascii=False)
            history=[{'role':'user','content':'Ранее я предпочитал тему «'+case['forbidden_topic']+'».'},{'role':'assistant','content':'Понял.'}]
            messages=[{'role':'system','content':prompt},*history,{'role':'user','content':case['messages'][-1]['content']+'. Ответь одним коротким предложением, не перечисляй примеры.'}]
            start=time.monotonic()
            try:
                response=transport.complete('qwen3.5:4b',messages,timeout=60,options={'num_ctx':4096,'num_predict':160,'temperature':0})['message']['content']
                leak=bool(terms(case['forbidden_topic'])&terms(response))
                row={'id':case['id'],'mode':mode,'topic':case['topic'],'leak':leak,'response':response,'seconds':round(time.monotonic()-start,3)}
            except Exception as exc:row={'id':case['id'],'mode':mode,'error':type(exc).__name__}
            result['rows'].append(row);out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in row.items() if k!='response'},ensure_ascii=False),flush=True)
