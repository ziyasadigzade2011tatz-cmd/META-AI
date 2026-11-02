import ast
import json
import threading
import time
from . import transport,models
from .storage import STATE,atomic_json,read_json

LOCK=threading.Lock()
TESTS=[('context','Верни JSON {"game":"полное английское название игры"}. Пользователь любит играть в Хойку. Про какую игру речь?'),
       ('grounded_context','Верни JSON {"game":"полное английское название игры"}. Контекст приложения: Хойка в этом разговоре означает Hearts of Iron IV. Пользователь просит Paradox Script для этой игры. Назови игру.'),
       ('code','Верни JSON {"code":"Python исходник"}. Напиши только def add(a,b), возвращающую сумму a и b. Без импорта, декораторов, пояснений.')]


def evaluate(kind,answer):
    if kind in ('context','grounded_context'):return 'hearts of iron' in str(answer.get('game','')).lower()
    tree=ast.parse(answer.get('code',''))
    allowed=(ast.Module,ast.FunctionDef,ast.arguments,ast.arg,ast.Return,ast.BinOp,ast.Add,ast.Name,ast.Load)
    if len(tree.body)!=1 or tree.body[0].name!='add' or not all(isinstance(n,allowed) for n in ast.walk(tree)):return False
    ns={'__builtins__':{}};exec(compile(tree,'<controlled-benchmark>','exec'),ns)
    return ns['add'](2,3)==5 and ns['add'](-1,1)==0


def run(names,hardware=None,lock_held=False):
    if not lock_held and not LOCK.acquire(blocking=False):raise ValueError('Измерение уже выполняется')
    status=STATE/'benchmark.json';report={'hardware':hardware or models.profiles().get('hardware',{}),'scope':'Short local context/code smoke tasks; not an intelligence benchmark','results':[],'status':'running'}
    try:
        atomic_json(status,report)
        for name in names[:4]:
            for kind,prompt in TESTS:
                started=time.monotonic();row={'model':name,'test':kind}
                try:
                    data=transport.complete(name,[{'role':'user','content':prompt}],json_mode=True,timeout=180,options={'num_ctx':4096,'num_predict':180,'temperature':0})
                    answer=json.loads(data['message']['content']);row.update(passed=evaluate(kind,answer),tokens=data.get('eval_count'),tokens_per_second=round(data.get('eval_count',0)/max(.001,data.get('eval_duration',1)/1e9),2))
                except Exception as exc:row.update(passed=False,error=type(exc).__name__+': '+str(exc)[:300])
                row['seconds']=round(time.monotonic()-started,2);report['results'].append(row);atomic_json(status,report)
        report['status']='completed';models.from_benchmark(report);atomic_json(status,report);return report
    finally:LOCK.release()
