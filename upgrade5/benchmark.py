import ast,json,time
from pathlib import Path
import httpx

root=Path(__file__).resolve().parent
models=['qwen2.5:3b','qwen3:4b','qwen2.5-coder:7b','qwen2.5-coder:14b']
tests=[('context','Верни JSON {"game":"полное английское название игры"}. Пользователь: Я люблю играть в Хойку. Затем: Расскажи про Paradox Script для этой игры. О какой игре речь?'),
       ('code','Верни JSON {"code":"исходный код"}. Исправь Python функцию def add(a,b): return a-b так, чтобы она складывала a и b. Только определение функции, без импорта и пояснений.')]
rows=[]
with httpx.Client(timeout=160,trust_env=False) as c:
    installed={m['name'] for m in c.get('http://127.0.0.1:11434/api/tags').json()['models']}
    for model in models:
        if model not in installed:continue
        for kind,prompt in tests:
            start=time.monotonic();row={'model':model,'test':kind}
            try:
                r=c.post('http://127.0.0.1:11434/api/chat',json={'model':model,'stream':False,'format':'json','think':False,'keep_alive':'30s','messages':[{'role':'user','content':prompt}],'options':{'num_ctx':4096,'num_predict':180,'temperature':0}})
                r.raise_for_status();d=r.json();answer=json.loads(d['message']['content']);ok=False
                if kind=='context':ok='hearts of iron' in str(answer.get('game','')).lower()
                else:
                    tree=ast.parse(answer.get('code',''))
                    allowed=(ast.Module,ast.FunctionDef,ast.arguments,ast.arg,ast.Return,ast.BinOp,ast.Add,ast.Name,ast.Load)
                    if all(isinstance(n,allowed) for n in ast.walk(tree)) and len(tree.body)==1 and tree.body[0].name=='add':
                        ns={'__builtins__':{}};exec(compile(tree,'<benchmark>','exec'),ns)
                        ok=ns['add'](2,3)==5 and ns['add'](-1,1)==0
                row.update(passed=ok,answer=answer,tokens=d.get('eval_count'),tokens_per_second=round(d.get('eval_count',0)/max(d.get('eval_duration',1)/1e9,.001),2))
            except Exception as exc:row.update(passed=False,error=type(exc).__name__+': '+str(exc)[:300])
            row['seconds']=round(time.monotonic()-start,2);rows.append(row)
            (root/'benchmark_results.json').write_text(json.dumps({'hardware':{'ram_gb':16,'gpu':'RTX 3050 Laptop','vram_gb':4},'scope':'Two short local smoke tasks; not a comprehensive intelligence benchmark','results':rows},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(row,ensure_ascii=True),flush=True)
