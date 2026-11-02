import json,sys,time
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'candidate/core'))
from meta5 import transport,models
from meta5.benchmarks import evaluate,TESTS
report=json.loads((root/'benchmark_results.json').read_text(encoding='utf-8'))
for name in ('qwen2.5:3b','qwen3:4b','qwen2.5-coder:7b','qwen2.5-coder:14b'):
    start=time.monotonic();row={'model':name,'test':'grounded_context'}
    try:
        d=transport.complete(name,[{'role':'user','content':dict(TESTS)['grounded_context']}],json_mode=True,timeout=180,options={'num_ctx':4096,'num_predict':100,'temperature':0})
        answer=json.loads(d['message']['content']);row.update(passed=evaluate('grounded_context',answer),answer=answer,tokens=d.get('eval_count'),tokens_per_second=round(d.get('eval_count',0)/max(.001,d.get('eval_duration',1)/1e9),2))
    except Exception as exc:row.update(passed=False,error=type(exc).__name__+': '+str(exc)[:200])
    row['seconds']=round(time.monotonic()-start,2);report['results'].append(row);print(json.dumps(row,ensure_ascii=True),flush=True)
(root/'benchmark_results_full.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
profile=models.from_benchmark(report)
(root/'candidate/core/meta5_models_seed.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
print('Selected profiles:',json.dumps({k:profile[k] for k in ('chat','code','quality','vision')}))
