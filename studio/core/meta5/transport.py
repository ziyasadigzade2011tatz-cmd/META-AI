"""Single Ollama transport and local compute queue for both modes."""
import asyncio
import contextlib
import json
import threading
import time
import httpx
import os
from urllib.parse import urlsplit

from .compute import ComputeGate
from .performance import keep_alive
COMPUTE=ComputeGate()
BASE=os.environ.get('META_OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')
_target=urlsplit(BASE)
if _target.scheme!='http' or _target.hostname!='127.0.0.1' or _target.username or _target.password or _target.path or _target.query or _target.fragment:raise ValueError('Ollama URL must be local HTTP')

def prepare_model(client,model):
    response=client.get(BASE+'/api/ps');response.raise_for_status()
    target=model if ':' in model else model+':latest'
    for item in response.json().get('models',[]):
        name=item.get('name')
        if name and name not in (model,target):
            r=client.post(BASE+'/api/generate',json={'model':name,'keep_alive':0,'stream':False});r.raise_for_status()

async def prepare_model_async(client,model):
    response=await client.get(BASE+'/api/ps');response.raise_for_status()
    target=model if ':' in model else model+':latest'
    for item in response.json().get('models',[]):
        name=item.get('name')
        if name and name not in (model,target):
            r=await client.post(BASE+'/api/generate',json={'model':name,'keep_alive':0,'stream':False});r.raise_for_status()


async def _complete_cancellable(model,messages,cancel,timeout,json_mode,options,tools,think):
    started=time.monotonic();owned=False;task=None
    try:
        while not owned:
            if cancel.is_set():raise InterruptedError('Генерация остановлена')
            if time.monotonic()-started>=timeout:raise TimeoutError('Очередь локальной модели занята')
            owned=COMPUTE.acquire(blocking=False)
            if not owned:await asyncio.sleep(.1)
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout,connect=10),trust_env=False) as client:
            async def request():
                await prepare_model_async(client,model)
                payload={'model':model,'messages':messages,'stream':False,'think':think,'keep_alive':keep_alive(),'options':options or {'num_ctx':8192,'num_predict':2400,'temperature':.15}}
                if json_mode:payload['format']='json'
                if tools:payload['tools']=tools
                response=await client.post(BASE+'/api/chat',json=payload);response.raise_for_status();return response.json()
            task=asyncio.create_task(request())
            try:
                while not task.done():
                    if cancel.is_set():raise InterruptedError('Генерация остановлена')
                    if time.monotonic()-started>=timeout:raise TimeoutError('Превышено время локального разбора')
                    await asyncio.wait({task},timeout=.1)
                result=await task
                if not isinstance(result.get('message',{}).get('content',''),str):raise ValueError('Модель вернула неверный ответ')
                return result
            finally:
                if not task.done():task.cancel()
                with contextlib.suppress(asyncio.CancelledError):await task
    finally:
        if owned:COMPUTE.release()

def complete(model,messages,*,timeout=120,json_mode=False,options=None,tools=None,think=False,cancel=None):
    if cancel is not None:return asyncio.run(_complete_cancellable(model,messages,cancel,timeout,json_mode,options,tools,think))
    if not COMPUTE.acquire(timeout=timeout):raise TimeoutError('Очередь локальной модели занята')
    try:
        payload={'model':model,'messages':messages,'stream':False,'think':think,'keep_alive':keep_alive(),'options':options or {'num_ctx':8192,'num_predict':2400,'temperature':.15}}
        if json_mode:payload['format']='json'
        if tools:payload['tools']=tools
        with httpx.Client(timeout=timeout,trust_env=False) as client:
            prepare_model(client,model)
            r=client.post(BASE+'/api/chat',json=payload);r.raise_for_status();data=r.json()
        if not isinstance(data.get('message',{}).get('content',''),str):raise ValueError('Модель вернула неверный ответ')
        return data
    finally:COMPUTE.release()


async def stream(model,messages,*,cancel=None,options=None,timeout=120,think=False):
    started=time.monotonic();owned=False
    try:
        while not owned:
            if cancel and cancel.is_set():return
            owned=COMPUTE.acquire(blocking=False)
            if not owned:await asyncio.sleep(.05)
            if time.monotonic()-started>timeout:raise TimeoutError('Очередь модели занята')
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout,connect=10),trust_env=False) as client:
            await prepare_model_async(client,model)
            async with client.stream('POST',BASE+'/api/chat',json={'model':model,'messages':messages,'stream':True,'think':think,'keep_alive':keep_alive(),'options':options or {'num_ctx':8192,'num_predict':1600,'temperature':.3}}) as r:
                r.raise_for_status()
                iterator=r.aiter_lines().__aiter__();pending=None
                try:
                    while True:
                        if cancel and cancel.is_set():return
                        if pending is None:pending=asyncio.create_task(iterator.__anext__())
                        ready,_=await asyncio.wait({pending},timeout=.15)
                        if not ready:continue
                        try:line=pending.result()
                        except StopAsyncIteration:break
                        pending=None
                        if not line:continue
                        if len(line)>250000:raise ValueError('Ответ модели слишком большой')
                        data=json.loads(line)
                        if data.get('error'):raise ValueError(str(data['error'])[:500])
                        content=data.get('message',{}).get('content','')
                        if content:yield {'type':'token','content':content}
                        if data.get('done'):yield {'type':'metrics','data':{k:data.get(k) for k in ('eval_count','eval_duration','prompt_eval_count','load_duration')}}
                finally:
                    if pending is not None:
                        pending.cancel()
                        with contextlib.suppress(asyncio.CancelledError,StopAsyncIteration):await pending
    finally:
        if owned:COMPUTE.release()
