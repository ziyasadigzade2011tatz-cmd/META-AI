"""Observable, cancellable model actions. Never exposes private chain of thought."""
import asyncio,contextlib,json,re,time
import httpx
from meta5 import transport
from meta5.performance import keep_alive
from meta5.phase11_config import load

def preview(raw):
    value={}
    for key in ('action','path'):
        found=re.search(r'"'+key+r'"\s*:\s*("(?:\\.|[^"\\])*")',raw)
        if found:
            try:value[key]=json.loads(found[1])[:240]
            except ValueError:pass
    found=re.search(r'"content"\s*:\s*"((?:\\.|[^"\\])*)',raw,re.S)
    if found:
        try:value['code_preview']=json.loads('"'+found[1]+'"')[-12000:].encode('utf-8',errors='replace').decode('utf-8')
        except ValueError:pass
    return value

def payload(model,messages,context):
    return {'model':model,'messages':messages,'format':'json','think':False,'stream':True,'keep_alive':keep_alive(),
            'options':{'num_ctx':context,'num_predict':3200,'temperature':.1}}

async def _exchange(model,messages,cancel,emit,context):
    cfg=load('agent');started=time.monotonic();owned=False;parts=[];characters=0;last_emit=0;last_preview={}
    heartbeat=max(.05,min(2,cfg['heartbeat_seconds']));step_limit=max(1,min(900,cfg['step_seconds']))
    def progress(phase,message):
        emit('generation',{'phase':phase,'message':message,'elapsed_seconds':round(time.monotonic()-started,1),'characters':characters,**last_preview})
    try:
        while not owned:
            if cancel.is_set():raise InterruptedError('Остановлено пользователем')
            owned=transport.COMPUTE.acquire(blocking=False)
            if not owned:
                progress('queued','Ожидаю свободную очередь локальной модели')
                if time.monotonic()-started>max(1,min(900,cfg['queue_seconds'])):raise TimeoutError('Очередь локальной модели остаётся занятой')
                await asyncio.sleep(heartbeat)
        progress('loading','Подготавливаю модель')
        async with httpx.AsyncClient(timeout=httpx.Timeout(None,connect=10),trust_env=False) as client:
            prepare=asyncio.create_task(transport.prepare_model_async(client,model))
            try:
                while not prepare.done():
                    if cancel.is_set():raise InterruptedError('Остановлено пользователем')
                    if time.monotonic()-started>step_limit:raise TimeoutError('Превышено время подготовки модели')
                    await asyncio.wait({prepare},timeout=heartbeat);progress('loading','Подготавливаю модель')
                await prepare
            finally:
                if not prepare.done():prepare.cancel()
                with contextlib.suppress(asyncio.CancelledError):await prepare
            request=payload(model,messages,context)
            progress('generating','Модель обрабатывает контекст')
            async with client.stream('POST',transport.BASE+'/api/chat',json=request) as response:
                response.raise_for_status();iterator=response.aiter_lines().__aiter__();pending=None
                try:
                    while True:
                        if cancel.is_set():raise InterruptedError('Остановлено пользователем; черновик сохранён')
                        if time.monotonic()-started>step_limit:raise TimeoutError('Лимит времени одного действия модели')
                        if pending is None:pending=asyncio.create_task(iterator.__anext__())
                        ready,_=await asyncio.wait({pending},timeout=heartbeat)
                        if not ready:
                            progress('generating','Получаю действие модели' if not last_preview.get('path') else 'Готовлю '+last_preview['path']);continue
                        try:line=pending.result()
                        except StopAsyncIteration:break
                        pending=None
                        if not line:continue
                        if len(line)>600000:raise ValueError('Слишком большой фрагмент ответа')
                        event=json.loads(line)
                        if event.get('error'):raise ValueError('Ollama не завершила действие')
                        content=event.get('message',{}).get('content','')
                        if content:parts.append(content);characters+=len(content)
                        if characters>500000:raise ValueError('Ответ модели слишком большой')
                        if time.monotonic()-last_emit>=max(.05,min(5,cfg['progress_seconds'])) or event.get('done'):
                            last_preview=preview(''.join(parts));progress('generating','Готовлю '+last_preview.get('path','действие'));last_emit=time.monotonic()
                        if event.get('done_reason')=='length':raise ValueError('Действие оборвалось по длине. Раздели код на меньшие файлы.')
                finally:
                    if pending is not None:
                        pending.cancel()
                        with contextlib.suppress(asyncio.CancelledError,StopAsyncIteration):await pending
        return ''.join(parts)
    finally:
        if owned:transport.COMPUTE.release()

async def exchange(model,messages,cancel,emit,context,deadline=None):
    """Also cancel while HTTP headers are pending, not only between body chunks."""
    cfg=load('agent');started=time.monotonic();last=[started,{}]
    heartbeat=max(.05,min(2,cfg['heartbeat_seconds']))
    limit=started+max(1,min(900,cfg['queue_seconds']))+max(1,min(900,cfg['step_seconds']))
    if deadline is not None:limit=min(limit,deadline)
    def forward(kind,data):
        last[:]=[time.monotonic(),data];emit(kind,data)
    task=asyncio.create_task(_exchange(model,messages,cancel,forward,context))
    try:
        while not task.done():
            if cancel.is_set():raise InterruptedError('Остановлено пользователем')
            if time.monotonic()>=limit:raise TimeoutError('Исчерпан бюджет времени задачи')
            await asyncio.wait({task},timeout=heartbeat)
            if not task.done() and time.monotonic()-last[0]>=heartbeat*2:
                data={**last[1],'message':last[1].get('message','Ожидаю ответ локальной модели'),'elapsed_seconds':round(time.monotonic()-started,1)}
                forward('generation',data)
        return await task
    finally:
        if not task.done():task.cancel()
        with contextlib.suppress(asyncio.CancelledError):await task

def generate(model,messages,cancel,emit,context=4096,deadline=None):return asyncio.run(exchange(model,messages,cancel,emit,context,deadline))
