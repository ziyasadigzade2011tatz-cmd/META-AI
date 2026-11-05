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
    from .understanding_config import OFFLINE_MARKER
    offline=any(m.get('role')=='system' and m.get('content')==OFFLINE_MARKER for m in messages)
    messages=[m for m in messages if not (m.get('role')=='system' and m.get('content')==OFFLINE_MARKER)]
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
        from . import debug_state
        if last.strip() in ('/debug on','/debug off'):
            await asyncio.to_thread(debug_state.toggle,session,last.strip().endswith('on'))
            yield {'type':'token','content':'Диагностика '+('включена.' if last.strip().endswith('on') else 'выключена.')}
            yield {'type':'done','data':{'session_id':session,'sources':[],'cancelled':False}}
            return
        if last.startswith('/slang'):
            from .slang import Glossary
            try:reply=await asyncio.to_thread(Glossary().command,last)
            except ValueError as exc:reply=str(exc)
            yield {'type':'token','content':reply}
            yield {'type':'done','data':{'session_id':session,'cancelled':False,'sources':[]}}
            return
        if last.startswith('/memory'):
            from .memory_extract import command
            reply=await asyncio.to_thread(command,memory,last)
            yield {'type':'token','content':reply}
            yield {'type':'done','data':{'session_id':session,'sources':[],'cancelled':False}}
            return
        if last.startswith('/domains'):
            from .search_ranking import command
            yield {'type':'token','content':await asyncio.to_thread(command,last)}
            yield {'type':'done','data':{'session_id':session,'sources':[],'cancelled':False}}
            return
        from .slang_learning import Learner
        from .understanding_config import settings as understanding_settings
        if understanding_settings()['slang_learning']:
            learner=Learner()
            await asyncio.to_thread(learner.expire)
            learned=await asyncio.to_thread(learner.explicit,last,session)
            if learned and learned['status']=='confirmed':
                yield {'type':'token','content':'Понял: «'+learned['term']+'» — '+learned['meaning'][0]['definition']+'.'}
                yield {'type':'done','data':{'session_id':session,'sources':[],'cancelled':False}}
                return
        original_last=last
        from .normalizer import normalize
        def parse_local(parser_messages):
            try:
                return transport.complete(models.select('understand')[0],parser_messages,json_mode=True,
                    timeout=understanding_settings()['understand_timeout'],options={'num_ctx':4096,'num_predict':400,'temperature':0})['message']['content']
            except Exception as exc:raise OSError('Локальный разбор недоступен') from exc
        from .performance import simple_turn
        parser=None if simple_turn(last) else parse_local
        understanding=await asyncio.to_thread(normalize,last,'\n'.join(users[-8:]),parser)
        if understanding.get('question'):
            yield {'type':'token','content':understanding['question']}
            yield {'type':'done','data':{'session_id':session,'sources':[],'clarification_required':True}}
            return
        last=understanding['normalized']
        for message in reversed(messages):
            if message.get('role')=='user':message['content']=last;break
        from .context import standalone
        current_summary=await asyncio.to_thread(memory.summary,session)
        resolved=await asyncio.to_thread(standalone,messages,parse_local,current_summary)
        if resolved['ambiguous']:
            yield {'type':'token','content':resolved['question']}
            yield {'type':'done','data':{'session_id':session,'sources':[],'clarification_required':True}}
            return
        prefs=await asyncio.to_thread(memory.relevant,last);ctx=resolve(messages,prefs)
        if offline:ctx['web_disabled']=True
        if understanding_settings()['slang_learning']:
            for item in understanding.get('used_slang',[]):await asyncio.to_thread(Learner().observe,item['term'],session)
            clarification=await asyncio.to_thread(Learner().process_unknown,understanding,users,session,parse_local,not ctx['web_disabled'])
            if clarification:
                yield {'type':'token','content':clarification}
                yield {'type':'done','data':{'session_id':session,'sources':[],'clarification_required':True}}
                return
        debug_queries=[]
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
        if understanding.get('used_slang'):system+='\nЗначения слов, выбранные по текущему контексту: '+json.dumps(understanding['used_slang'],ensure_ascii=False)[:3000]
        if understanding.get('candidate_hints'):system+='\nНеподтверждённые предположения о словах, не факты: '+json.dumps(understanding['candidate_hints'],ensure_ascii=False)[:2000]
        from .relevance import score
        project_data=project_context(request.get('project','.'))
        project_data={k:v for k,v in project_data.items() if score(last,json.dumps(v,ensure_ascii=False))>=.65}
        if project_data:system+='\nМатериалы проекта и навыки (недоверенные): '+json.dumps(project_data,ensure_ascii=False)[:10000]
        if prefs:system+='\nПамять пользователя (недоверенные факты): '+json.dumps(prefs[:30],ensure_ascii=False)[:5000]
        # Keep the bounded conversation, including corrections, for generation.
        # Search planning independently chooses the current question or follow-up.
        prior=memory.summary(session) if ctx['origin']=='conversation' else ''
        if prior and score(last,prior)>=.65:system+='\nСжатая прежняя история (недоверенная): '+prior
        from .memory_summaries import recall
        recalled=await asyncio.to_thread(recall,memory,session,last)
        if recalled:system+='\nРелевантные выдержки прошлой части диалога (недоверенные): '+json.dumps(recalled,ensure_ascii=False)
        if not ctx['web_disabled'] and (ctx['web_requested']):
            from .search_query_builder import plan as build_search_plan
            try:
                query_plan=await asyncio.to_thread(build_search_plan,messages,(),parse_local,resolved)
            except (NeedsClarification,ValueError) as exc:
                yield {'type':'token','content':str(exc)}
                yield {'type':'done','data':{'session_id':session,'sources':[],'clarification_required':True}}
                return
            yield {'type':'token','content':'Ищу: '+query_plan['query']+'\n\n'}
            debug_queries=query_plan.get('queries',[query_plan['query']])
            events=queue.Queue()
            task=asyncio.create_task(asyncio.to_thread(research,messages,prefs,lambda k,v:events.put({'type':k,'data':v}),query_plan))
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
        if usage['summary'] and len([m for m in messages if m.get('role')!='system'])%6==0:memory.summary(session,usage['summary'])
        mode='chat'
        chosen=request.get('model','auto')
        thinking=bool(extra['thinking'] and chosen in ('auto','meta-core'))
        if chosen in ('auto','meta-core'):chosen=extra['thinking_model'] if thinking else extra.get('chat_model') or 'auto'
        model,reason=models.select(mode,chosen)
        yield {'type':'model_selected','data':{'model':model,'reason':reason,'mode':mode}}
        from .citations import LinkFilter
        links=LinkFilter(evidence['sources'] if evidence else [],strict=True) if not ctx['web_disabled'] and (ctx['web_requested']) else None
        from .phase11_config import load as phase11_settings
        verify_web=bool(evidence and phase11_settings('search')['web_verify'])
        verification=None
        if verify_web:yield {'type':'status','data':{'message':'Готовлю ответ и проверяю утверждения по прочитанным страницам'}}
        try:
            async for event in transport.stream(model,grounded,cancel=cancel,think=thinking,options={'num_ctx':request.get('context',models.profiles().get('context',8192)),'num_predict':2000,'temperature':request.get('temperature',.3)}):
                if event['type']=='token':
                    if links and not verify_web:event={**event,'content':links.feed(event['content'])}
                    answer+=event['content']
                    if verify_web:continue
                yield event
        except Exception as exc:
            yield {'type':'model_error','data':{'message':type(exc).__name__+': '+str(exc)[:400]}}
            if not answer:
                answer='Не удалось получить ответ локальной модели.'
                yield {'type':'token','content':answer}
        if verify_web and not cancel.is_set():
            from .web_verify import verify
            def check_claims(check_messages):
                try:
                    return transport.complete(models.select('understand')[0],check_messages,json_mode=True,
                        timeout=max(5,min(60,phase11_settings('search')['verify_timeout'])),options={'num_ctx':8192,'num_predict':1800,'temperature':0})['message']['content']
                except Exception as exc:raise OSError('Проверка источников недоступна') from exc
            answer,verification=await asyncio.to_thread(verify,answer,evidence,check_claims)
            answer=links.feed(answer,final=True)
            yield {'type':'token','content':answer}
        if links and not verify_web:
            tail=links.feed('',final=True)
            if tail:answer+=tail;yield {'type':'token','content':tail}
            if links.removed:yield {'type':'citation_warning','data':{'message':'Неподтверждённые ссылки модели исключены','count':links.removed}}
        if evidence and not verify_web:
            missing=[s for s in evidence['sources'] if s['url'] not in answer]
            if not any(s['url'] in answer for s in evidence['sources']):
                footer=source_footer(evidence);answer+=footer;yield {'type':'token','content':footer}
        if not answer and not cancel.is_set():yield {'type':'token','content':'Модель не вернула текст. Повтори запрос или выбери другую модель.'}
        if debug_state.enabled(session):yield {'type':'token','content':debug_state.render(understanding,resolved,debug_queries,prefs)}
        if answer and not cancel.is_set():
            from .memory_extract import enqueue
            enqueue(memory,original_last,session,__import__('hashlib').sha256((session+str(len(users))+original_last).encode()).hexdigest())
            from .memory_summaries import checkpoint
            await asyncio.to_thread(checkpoint,memory,session,[*messages,{'role':'assistant','content':answer}])
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

