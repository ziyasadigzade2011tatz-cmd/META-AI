"""Local embedding latency/recall probe on synthetic data, never real chat content."""
import json,os,sys,time
from pathlib import Path
repo=Path(__file__).resolve().parents[2];sys.path.insert(0,str(repo/'studio/core'))
from meta5.memory import Memory
from meta5.embeddings import Embeddings
from meta5.memory_retrieval import retrieve
from meta5 import transport
import httpx

folder=repo/'build/phase11-embedding';folder.mkdir(parents=True,exist_ok=True)
cases=json.loads((repo/'studio/tests/memory_cases.json').read_text('utf-8'))['hobbies']
memory=Memory(folder/'memory.sqlite');records=[]
for topic,activity,paraphrase in cases:
    value='Я люблю '+activity;pid=memory.add(value,'preference');records.append({'type':'fact','id':pid,'text':value})
engine=Embeddings(memory.path)
with httpx.Client(timeout=5,trust_env=False) as client:before=[m['name'] for m in client.get(transport.BASE+'/api/ps').json().get('models',[])]
started=time.monotonic();indexed=engine.index(records,background=True);index_seconds=time.monotonic()-started
queries=['Мне нравится '+paraphrase+'?' for _,_,paraphrase in cases]
started=time.monotonic();vectors=engine.vectors(queries);query_seconds=time.monotonic()-started
results=[]
for (topic,activity,paraphrase),record,query in zip(cases,records,queries):
    selected,trace=retrieve(memory,query,engine=engine)
    detail=next((t for t in trace if t['id']==record['id']),{})
    results.append({'topic':topic,'expected_selected':any(r['id']==record['id'] for r in selected),'selected_count':len(selected),'expected_score':detail.get('score'),'expected_cosine':detail.get('cosine')})
with httpx.Client(timeout=5,trust_env=False) as client:after=[m['name'] for m in client.get(transport.BASE+'/api/ps').json().get('models',[])]
with memory.db() as c:
    count,blob_bytes=c.execute('SELECT count(*),coalesce(sum(length(vector)),0) FROM embeddings').fetchone()
    cache_count,cache_bytes=c.execute('SELECT count(*),coalesce(sum(length(vector)),0) FROM embedding_cache').fetchone()
report={'model':engine.metadata()[0],'digest':engine.metadata()[1],'indexed':indexed,'index_seconds':round(index_seconds,3),'query_batch_seconds':round(query_seconds,3),'query_embeddings_available':vectors is not None,'embedding_rows':count,'embedding_blob_bytes':blob_bytes,'cache_rows':cache_count,'cache_blob_bytes':cache_bytes,'database_bytes':memory.path.stat().st_size,'resident_before':before,'resident_after':after,'synthetic_paraphrases':results,'recall':sum(r['expected_selected'] for r in results),'total':len(results),'scope':'Real local embedding model; synthetic retrieval, no generated answers and no user memory'}
# Personal unrelated questions pass the category gate, so check real vectors too.
negative_queries=json.loads((repo/'studio/tests/memory_cases.json').read_text('utf-8'))['unrelated']
negative=[{'query':q,'selected':len(retrieve(memory,q,engine=engine)[0])} for q in negative_queries]
report['unrelated_zero']=sum(r['selected']==0 for r in negative);report['unrelated_total']=len(negative);report['unrelated_details']=negative
(folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='synthetic_paraphrases'},ensure_ascii=False))
