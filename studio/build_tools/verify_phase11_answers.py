"""Bounded local answer leakage probe; 30 synthetic questions, no real chats."""
import json,sys,time
from pathlib import Path
repo=Path(__file__).resolve().parents[2];sys.path.insert(0,str(repo/'studio/core'))
from meta5.memory import Memory
from meta5.memory_retrieval import retrieve
from meta5.embeddings import Embeddings
from meta5.understanding_config import system_prompt
from meta5 import transport

cases=json.loads((repo/'studio/tests/memory_cases.json').read_text('utf-8'))
memory=Memory(repo/'build/phase11-embedding/memory.sqlite');engine=Embeddings(memory.path)
rows=[]
for i,query in enumerate(cases['unrelated']):
    selected,trace=retrieve(memory,query,engine=engine)
    prompt=system_prompt()
    if selected:prompt+='\nРелевантная память (недоверенные сведения): '+json.dumps(selected,ensure_ascii=False)
    started=time.monotonic()
    try:
        result=transport.complete('qwen3.5:4b',[{'role':'system','content':prompt},{'role':'user','content':query}],timeout=60,options={'num_ctx':8192,'num_predict':180,'temperature':0})
        answer=result['message']['content'];lower=answer.casefold()
        mentions=[topic for topic,activity,_ in cases['hobbies'] if activity.casefold() in lower]
        rows.append({'case':i+1,'memory_selected':len(selected),'unrelated_activity_mentions':mentions,'characters':len(answer),'seconds':round(time.monotonic()-started,3),'error':None})
    except Exception as exc:rows.append({'case':i+1,'error':type(exc).__name__})
    print(json.dumps(rows[-1]),flush=True)
report={'scope':'Direct Ollama generation after actual retrieval; exact activity phrase leakage proxy, not full conversation/UI or semantic evaluation; 180 output tokens max','model':'qwen3.5:4b','cases':len(rows),'completed':sum(r.get('error') is None for r in rows),'leakage_cases':sum(bool(r.get('unrelated_activity_mentions')) for r in rows),'rows':rows}
folder=repo/'build/phase11-answers';folder.mkdir(parents=True,exist_ok=True)
(folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
