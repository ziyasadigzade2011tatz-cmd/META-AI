import time
from .context import search_plan,rank_sources
from meta40.web_research import web_search,web_fetch,WebError


def research(messages,preferences=(),emit=lambda *a:None,plan_override=None):
    from .search_query_builder import plan as build_plan
    plan=plan_override or build_plan(messages,preferences);emit('research_plan',plan)
    from .advanced import settings
    if settings()['deep_research']:
        from .deep_research import expand
        return expand(messages,plan,web_search,web_fetch,emit)
    from .knowledge import cache
    max_age=300 if plan['context'].get('verification_required') else 86400
    saved=cache(plan['query'],max_age=max_age)
    from urllib.parse import urlsplit
    blocked=[d.casefold() for d in settings()['blocked_domains']]
    saved=[h for h in saved if not any((urlsplit(h.get('url','')).hostname or '').casefold()==d or (urlsplit(h.get('url','')).hostname or '').casefold().endswith('.'+d) for d in blocked)]
    if saved:
        emit('sources_found',{'query':plan['query'],'sources':saved,'cached':True})
        return {'query':plan['query'],'sources':saved,'cached':True}
    started=time.monotonic();emit('search_started',{'query':plan['query']})
    try:first=web_search(plan['query'],max_results=5)
    except WebError as exc:
        emit('research_warning',{'message':str(exc)[:400]});first={'results':[]}
        from .knowledge import cache
        saved=cache(plan['query'],max_age=max_age)
        saved=[h for h in saved if not any((urlsplit(h.get('url','')).hostname or '').casefold()==d or (urlsplit(h.get('url','')).hostname or '').casefold().endswith('.'+d) for d in blocked)]
        if saved:
            emit('research_warning',{'message':'Использованы ранее сохранённые источники'})
            return {'query':plan['query'],'sources':saved,'cached':True}
        if not plan['alternative']:raise
    from urllib.parse import urlsplit
    blocked=[d.casefold() for d in settings()['blocked_domains']]
    filtered=[h for h in first.get('results',[]) if not any((urlsplit(h.get('url','')).hostname or '').lower()==d or (urlsplit(h.get('url','')).hostname or '').lower().endswith('.'+d) for d in blocked)]
    hits,excluded=rank_sources(filtered,plan)
    if plan['alternative'] and (not hits or not any(h['preferred_source'] for h in hits)):
        emit('search_started',{'query':plan['alternative'],'reason':'alternative_query'})
        try:
            second=web_search(plan['alternative'],max_results=5)
            combined={h['url']:h for h in [*first.get('results',[]),*second.get('results',[])] if isinstance(h,dict) and h.get('url')}
            hits,excluded=rank_sources(list(combined.values()),plan)
        except WebError as exc:emit('research_warning',{'message':str(exc)[:250]})
    if not hits:raise WebError('Нет источников, относящихся к этому вопросу. Уточни формулировку.')
    emit('sources_found',{'query':plan['query'],'sources':hits,'excluded':excluded})
    for hit in hits[:2]:
        if time.monotonic()-started>25:break
        emit('page_started',{'url':hit['url']})
        try:
            page=web_fetch(hit['url']);hit.update(page_text=page.get('text','')[:6000],opened=True,resolved_url=page.get('url'))
            emit('page_opened',{'url':hit['url'],'characters':len(page.get('text',''))})
        except (ValueError,OSError) as exc:
            hit.update(opened=False,fetch_error=type(exc).__name__+': '+str(exc)[:180]);emit('page_failed',{'url':hit['url'],'error':hit['fetch_error']})
    from .knowledge import cache
    try:cache(plan['query'],hits)
    except (OSError,__import__('sqlite3').Error):pass
    result={'query':plan['query'],'context':plan['context'],'sources':hits,'excluded':excluded,'seconds':round(time.monotonic()-started,2)}
    emit('research_done',{'sources':len(hits),'seconds':result['seconds']});return result

