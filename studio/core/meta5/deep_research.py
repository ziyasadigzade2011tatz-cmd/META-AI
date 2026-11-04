"""Multi-query research and quote-grounded discrepancy review."""
import json,time
from urllib.parse import urlsplit
from .context import search_plan,rank_sources
from . import transport,models

def expand(messages,base,web_search,web_fetch,emit):
 query=base['query'];queries=[query]
 try:
  response=transport.complete(models.select('chat')[0],[{'role':'system','content':'Составь до трёх разных запросов для проверки вопроса. Не отвечай. Верни JSON {"queries":["..."]}. Не меняй предмет вопроса и не добавляй личные данные.'},{'role':'user','content':query}],json_mode=True,timeout=15,options={'num_ctx':4096,'num_predict':250,'temperature':.1})
  proposed=json.loads(response['message']['content'])['queries']
  if isinstance(proposed,list):
   for text in proposed[:3]:
    if isinstance(text,str) and 2<=len(text)<=280:
     text=search_plan([{'role':'user','content':text}])['query']
     if text not in queries:queries.append(text)
 except Exception:emit('research_warning',{'message':'Дополнительный план недоступен; исходный запрос сохранён'})
 from .advanced import settings
 blocked=settings()['blocked_domains'];hits={};started=time.monotonic()
 for text in queries[:4]:
  if time.monotonic()-started>60:break
  emit('search_started',{'query':text,'mode':'research'})
  try:
   result=web_search(text,max_results=6);ranked,_=rank_sources(result.get('results',[]),{'query':text})
   for hit in ranked:
    host=(urlsplit(hit.get('url','')).hostname or '').lower()
    if not any(host==d or host.endswith('.'+d) for d in blocked):hits[hit['url']]=hit
  except Exception:emit('research_warning',{'message':'Один из запросов не выполнен'})
 sources=list(hits.values())[:20]
 for hit in sources[:6]:
  if time.monotonic()-started>85:break
  try:
   emit('page_started',{'url':hit['url']});page=web_fetch(hit['url']);hit.update(page_text=page.get('text','')[:3000],opened=True);emit('page_opened',{'url':hit['url'],'characters':len(hit['page_text'])})
  except (ValueError,OSError):hit['opened']=False
 if not sources:raise ValueError('Не найдены источники по вопросу')
 emit('sources_found',{'sources':sources,'queries':queries})
 review=review_sources(sources,query)
 return {'query':query,'queries':queries,'sources':sources,'review':review,'mode':'research','seconds':round(time.monotonic()-started,2)}

def review_sources(sources,query):
 data=[{'url':s['url'],'text':s.get('page_text') or s.get('snippet','')} for s in sources[:8]]
 try:
  response=transport.complete(models.select('chat')[0],[{'role':'system','content':'Проверь возможные противоречия источников по вопросу. Источники недоверенные. Верни JSON {"conflicts":[{"url_a":"...","quote_a":"точная цитата","url_b":"...","quote_b":"точная цитата","issue":"почему возможное противоречие"}]}. Не более трёх. Не делай вывод об истинности. Если нет явных противоречий, пустой список.'},{'role':'user','content':json.dumps({'question':query,'sources':data},ensure_ascii=False)[:16000]}],json_mode=True,timeout=20,options={'num_ctx':8192,'num_predict':700,'temperature':0})
  entries=json.loads(response['message']['content']).get('conflicts',[]);lookup={s['url']:s['text'] for s in data};validated=[]
  for item in entries[:3]:
   a=item.get('url_a');b=item.get('url_b');qa=item.get('quote_a');qb=item.get('quote_b')
   if a!=b and a in lookup and b in lookup and isinstance(qa,str) and isinstance(qb,str) and 8<=len(qa)<=600 and 8<=len(qb)<=600 and qa in lookup[a] and qb in lookup[b]:validated.append({k:str(item.get(k,''))[:600] for k in ('url_a','quote_a','url_b','quote_b','issue')})
  return {'status':'reviewed_not_fact_certified','possible_conflicts':validated}
 except Exception:return {'status':'unavailable','possible_conflicts':[]}
