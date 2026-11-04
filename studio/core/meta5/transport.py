"""Single Ollama transport and local compute queue for both modes."""
import asyncio
import contextlib
import json
import threading
import time
import httpx
import os
from urllib.parse import urlsplit

COMPUTE=threading.Semaphore(1)
BASE=os.environ.get('META_OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')
_target=urlsplit(BASE)
if _target.scheme!='http' or _target.hostname!='127.0.0.1' or _target.username or _target.password or _target.path or _target.query or _target.fragment:raise ValueError('Ollama URL must be local HTTP')


def complete(model,messages,*,timeout=120,json_mode=False,options=None,tools=None,think=False):
    if not COMPUTE.acquire(timeout=timeout):raise TimeoutError('Очередь локальной модели занята')
    try:
        payload={'model':model,'messages':messages,'stream':False,'think':think,'keep_alive':'3m','options':options or {'num_ctx':8192,'num_predict':2400,'temperature':.15}}
        if json_mode:payload['format']='json'
        if tools:payload['tools']=tools
        with httpx.Client(timeout=timeout,trust_env=False) as client:
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
            async with client.stream('POST',BASE+'/api/chat',json={'model':model,'messages':messages,'stream':True,'think':think,'keep_alive':'3m','options':options or {'num_ctx':8192,'num_predict':1600,'temperature':.3}}) as r:
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
