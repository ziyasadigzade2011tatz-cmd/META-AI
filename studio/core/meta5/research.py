"""Bounded multi-query research using opened pages and cached local fragments."""
import hashlib,time,sqlite3
from .phase11_config import load
from .privacy import sensitive
from .search_ranking import rank,chunks,allowed,primary_required,primary
from .knowledge import cache,database
from .embeddings import Embeddings
from meta40.web_research import web_search,web_fetch,WebError


def research(messages,preferences=(),emit=lambda *a:None,plan_override=None):
    from .search_query_builder import plan as build_plan
    plan=plan_override or build_plan(messages,preferences)
    query=plan.get('original_query') or plan['query'];cfg=load('search');emit('research_plan',plan)
    if sensitive(query):raise ValueError('Личные данные не отправляются в поиск')
    recent=plan.get('context',{}).get('verification_required',False)
    ttl=cfg['ttl_current'] if recent else cfg['ttl_general']
    try:saved=cache(query,max_age=ttl)
    except (OSError,sqlite3.Error,ValueError):saved=[]
    saved=[s for s in saved if s.get('opened') and allowed(s['url'],query) and allowed(s.get('resolved_url') or s['url'],query)]
    if primary_required(query):saved=[s for s in saved if primary(s.get('resolved_url') or s['url'],query)]
    if saved:return {'query':query,'sources':saved,'cached':True,'excluded':[]}
    started=time.monotonic();results=[];warnings=[]
    queries=list(dict.fromkeys(plan.get('queries') or [plan['query'],plan.get('alternative')]))
    for q in [q for q in queries if q][:max(1,min(3,int(cfg['max_queries'])))]:
        if time.monotonic()-started>cfg['search_seconds']:break
        emit('search_started',{'query':q})
        try:results.append(web_search(q,max_results=8).get('results',[]))
        except (OSError,ValueError,TimeoutError) as exc:
            warnings.append(type(exc).__name__);emit('research_warning',{'message':'Поиск недоступен или ограничен; пробую доступные источники.'})
    try:engine=Embeddings(database())
    except (OSError,sqlite3.Error):engine=None
    hits,excluded=rank(results,query,engine,recent)
    emit('sources_found',{'query':query,'sources':hits,'excluded':excluded})
    opened=[]
    for hit in hits[:max(1,min(6,int(cfg['max_open_pages'])))]:
        if time.monotonic()-started>cfg['search_seconds']:break
        emit('page_started',{'url':hit['url']})
        try:
            page=web_fetch(hit['url']);resolved=page.get('url') or hit['url']
            if not allowed(resolved,query):excluded.append({'url':resolved,'reason':'redirect_domain_policy'});continue
            if primary_required(query) and not primary(resolved,query):excluded.append({'url':resolved,'reason':'official_redirect_not_verified'});continue
            text=page.get('text','')[:max(1000,min(20000,int(cfg['page_characters'])))]
            if sensitive(text):excluded.append({'url':hit['url'],'reason':'private_page_data'});continue
            pieces=chunks(text,query,engine)
            if not pieces:continue
            hit.update(opened=True,resolved_url=resolved,chunks=pieces,page_text='\n'.join(p['text'] for p in pieces))
            if engine:
                try:engine.index([{'type':'chunk','id':hashlib.sha256((resolved+str(p['offset'])).encode()).hexdigest(),'text':p['text']} for p in pieces],background=False)
                except (OSError,sqlite3.Error,ValueError):pass
            opened.append(hit);emit('page_opened',{'url':hit['url'],'characters':len(text),'fragments':len(pieces)})
        except (ValueError,OSError,TimeoutError) as exc:
            excluded.append({'url':hit['url'],'reason':'page_unavailable'});emit('page_failed',{'url':hit['url'],'error':type(exc).__name__})
    if not opened:raise WebError('Не нашла подтверждённой информации: нет доступных относящихся к вопросу страниц.')
    try:cache(query,opened,max_age=ttl)
    except (OSError,sqlite3.Error,ValueError):pass
    result={'query':query,'context':plan.get('context',{}),'sources':opened,'excluded':excluded,'seconds':round(time.monotonic()-started,2),'warnings':warnings}
    emit('research_done',{'sources':len(opened),'seconds':result['seconds']});return result
