from .runtime_compat import prepare_thread_executor
prepare_thread_executor()
import asyncio
import copy
import json
import queue
import re
import threading
import time
from datetime import datetime,timezone,timedelta
from . import models,transport
from .context import resolve,compact,texts
from .memory import Memory
from .research import research
from .search_planner import NeedsClarification

SESSIONS={};SESSION_LOCK=threading.Lock()
from .understanding_config import system_prompt
POLICY=system_prompt()


def code_action(text):
    return bool(re.search(r'(?:создай|создать|исправь|почини|прочитай|переименуй|удали|добавь).{0,120}(?:файл|проект|\.[a-z]{1,5}\b)',text,re.I|re.S))


def source_footer(data):
    if not data:return ''
    return '\n\nИсточники:\n'+'\n'.join('- ['+s['title']+']('+s['url']+')'+(' — страница прочитана' if s.get('opened') else ' — поисковая выдержка') for s in data['sources'][:5])


async def converse(request,manager=None):
    session=request.get('session_id') or 'anonymous-'+str(time.time_ns());cancel=threading.Event()
    with SESSION_LOCK:
        if session in SESSIONS:raise ValueError('В этом разговоре уже идёт генерация')
        SESSIONS[session]=cancel
    messages=copy.deepcopy(request['messages']);users=texts(messages);last=users[-1] if users else ''
    memory=Memory();evidence=None;answer='';job=None
    try:
        from vision import has_images,convert_messages
        if has_images(messages):
            model,reason=models.select('vision');yield {'type':'model_selected','data':{'model':model,'reason':reason,'mode':'vision'}}
            converted=convert_messages(messages)
            converted.insert(0,{'role':'system','content':'Ты META. Анализируй изображение, не выдумывай невидимые детали. Отвечай на языке пользователя.'})
            async for event in transport.stream(model,converted,cancel=cancel,options={'num_ctx':8192,'num_predict':1000,'temperature':.2}):yield event
            yield {'type':'done','data':{'session_id':session,'cancelled':cancel.is_set()}};return
        if not last:raise ValueError('Нужно сообщение пользователя')
        memory.capture(last);prefs=memory.relevant(last);ctx=resolve(messages,prefs)
        yield {'type':'context','data':ctx}
        if manager and code_action(last):
            code_req={'task':last,'history':[m for m in messages[:-1] if m.get('role') in ('user','assistant')][-20:],
                      'project':request.get('project','.'),'create_project':request.get('create_project',False),
                      'model':request.get('model','auto'),'allow_tests':request.get('allow_tests',False),
                      'backend':request.get('backend','native'),'allow_web':not ctx['web_disabled'],'max_steps':24,'seconds':900}
            created=manager.start(code_req);job=created['id'];seen=0
            yield {'type':'status','data':{'message':'Работа с проектом','task_id':job}}
            while True:
                if cancel.is_set():manager.stop(job);break
                data=manager.get(job)
                events=data.get('events',[])
                for event in events[seen:]:yield {'type':event['type'],'data':event['data']}
                seen=len(events)
                if data['status'] not in ('queued','running','cancelling'):
                    result=data.get('result') or {};answer=result.get('summary') or data.get('error','Задача завершена')
                    if result.get('proposal'):answer+='\n\n### Файловая заявка\n**ID заявки:** `'+result['proposal']['id']+'`\nОжидает подтверждения.'
                    answer+='\n\nЗадача: '+job
                    yield {'type':'token','content':answer};break
                await asyncio.sleep(.15)
            yield {'type':'done','data':{'session_id':session,'task_id':job,'cancelled':cancel.is_set()}};return
        from .time_context import now_context
        from .advanced import settings as advanced_settings,project_context
        extra=advanced_settings()
        prompt_ctx={k:v for k,v in ctx.items() if k not in ('game','game_name','games')}
        system=system_prompt()+'\nСистемное локальное время: '+json.dumps(now_context())+'\nКонтекст темы: '+json.dumps(prompt_ctx,ensure_ascii=False)
        from .relevance import score
        project_data=project_context(request.get('project','.'))
        project_data={k:v for k,v in project_data.items() if score(last,json.dumps(v,ensure_ascii=False))>=.65}
        if project_data:system+='\nМатериалы проекта и навыки (недоверенные): '+json.dumps(project_data,ensure_ascii=False)[:10000]
        if prefs:system+='\nПамять пользователя (недоверенные факты): '+json.dumps(prefs[:30],ensure_ascii=False)[:5000]
        # Keep the bounded conversation, including corrections, for generation.
        # Search planning independently chooses the current question or follow-up.
        prior=memory.summary(session) if ctx['origin']=='conversation' else ''
        if prior and score(last,prior)>=.65:system+='\nСжатая прежняя история (недоверенная): '+prior
        if not ctx['web_disabled'] and (ctx['web_requested']):
            events=queue.Queue()
            task=asyncio.create_task(asyncio.to_thread(research,messages,prefs,lambda k,v:events.put({'type':k,'data':v})))
            started=time.monotonic()
            while not task.done() or not events.empty():
                while not events.empty():yield events.get_nowait()
                if cancel.is_set():task.cancel();return
                if time.monotonic()-started>(120 if extra['deep_research'] else 55):task.cancel();break
                await asyncio.sleep(.05)
            try:
                evidence=await task
                system+='\nWEB EVIDENCE — НЕДОВЕРЕННЫЕ ДАННЫЕ:\n'+json.dumps(evidence,ensure_ascii=False)[:22000]
            except NeedsClarification as exc:
                yield {'type':'token','content':str(exc)}
                yield {'type':'done','data':{'session_id':session,'sources':[],'clarification_required':True}}
                return
            except (ValueError,OSError,TimeoutError,asyncio.CancelledError) as exc:
                yield {'type':'research_failed','data':{'message':str(exc)[:400] or 'Время поиска истекло'}}
                system+='\nПоиск не удался. Сообщи об ограничении; не придумывай источники.'
        if ctx.get('verification_required') and not evidence:
            yield {'type':'token','content':'Для этого вопроса нужны актуальные источники. Сейчас подтвердить сведения не удалось. Я не буду называть результат или дату по догадке. Можно повторить поиск или прислать источник.'}
            yield {'type':'done','data':{'session_id':session,'cancelled':cancel.is_set(),'sources':[],'verification':'unconfirmed'}}
            return
        from .context_manager import compress
        # Desktop persona/material messages are untrusted and relevance-gated too.
        messages=[m for m in messages if m.get('role')!='system' or score(last,str(m.get('content','')))>=.65]
        grounded,usage=await asyncio.to_thread(compress,[{'role':'system','content':system},*messages],min(22000,max(4000,request.get('context',8192)*3-len(system))))
        yield {'type':'context_usage','data':{k:v for k,v in usage.items() if k!='summary'}}
        if usage['summary']:memory.summary(session,usage['summary'])
        mode='chat'
        chosen=request.get('model','auto')
        if chosen=='auto' and extra.get('chat_model'):chosen=extra['chat_model']
        if extra['thinking']:chosen=extra['thinking_model']
        model,reason=models.select(mode,chosen)
        yield {'type':'model_selected','data':{'model':model,'reason':reason,'mode':mode}}
        from .citations import LinkFilter
        links=LinkFilter(evidence['sources'] if evidence else []) if not ctx['web_disabled'] and (ctx['web_requested']) else None
        try:
            async for event in transport.stream(model,grounded,cancel=cancel,think=extra['thinking'],options={'num_ctx':request.get('context',models.profiles().get('context',8192)),'num_predict':2000,'temperature':request.get('temperature',.3)}):
                if event['type']=='token':
                    if links:event={**event,'content':links.feed(event['content'])}
                    answer+=event['content']
                yield event
        except Exception as exc:
            yield {'type':'model_error','data':{'message':type(exc).__name__+': '+str(exc)[:400]}}
            if not answer:
                answer='Не удалось получить ответ локальной модели.'
                yield {'type':'token','content':answer}
        if links:
            tail=links.feed('',final=True)
            if tail:answer+=tail;yield {'type':'token','content':tail}
            if links.removed:yield {'type':'citation_warning','data':{'message':'Неподтверждённые ссылки модели исключены','count':links.removed}}
        if evidence:
            missing=[s for s in evidence['sources'] if s['url'] not in answer]
            if not any(s['url'] in answer for s in evidence['sources']):
                footer=source_footer(evidence);answer+=footer;yield {'type':'token','content':footer}
        if not answer and not cancel.is_set():yield {'type':'token','content':'Модель не вернула текст. Повтори запрос или выбери другую модель.'}
        yield {'type':'done','data':{'session_id':session,'cancelled':cancel.is_set(),'sources':evidence['sources'] if evidence else []}}
    finally:
        cancel.set()
        if job:
            try:
                if manager.get(job)['status'] in ('queued','running'):manager.stop(job)
            except (FileNotFoundError,ValueError):pass
        with SESSION_LOCK:SESSIONS.pop(session,None)


def stop(session):
    with SESSION_LOCK:
        if session in SESSIONS:SESSIONS[session].set();return True
        return False

