"""Compatibility endpoints backed by the common META 5 conversation runtime."""
import json
import time
import uuid
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from meta5.api import ChatRequest,data,consent
from meta5 import dialogue,models


async def run_agent(request):
    from meta5.api import MANAGER
    consent(request);reply=''
    async for event in dialogue.converse(data(request),MANAGER):
        if event['type']=='token':reply+=event['content']
    return reply


async def agent_completions(request:ChatRequest):
    from meta5.api import MANAGER
    consent(request);cid='chatcmpl-'+uuid.uuid4().hex;created=int(time.time())
    if not request.stream:
        try:reply=await run_agent(request)
        except Exception as exc:raise HTTPException(502,str(exc)[:500]) from exc
        return {'id':cid,'object':'chat.completion','created':created,'model':'meta-core',
                'choices':[{'index':0,'message':{'role':'assistant','content':reply},'finish_reason':'stop'}]}
    async def generate():
        try:
            async for event in dialogue.converse(data(request),MANAGER):
                if event['type']=='token':packet={'id':cid,'object':'chat.completion.chunk','created':created,'model':'meta-core','choices':[{'index':0,'delta':{'content':event['content']},'finish_reason':None}]}
                else:packet={'id':cid,'object':'chat.completion.chunk','choices':[],'meta':event}
                yield 'data: '+json.dumps(packet,ensure_ascii=False)+'\n\n'
        except Exception as exc:yield 'data: '+json.dumps({'error':{'message':str(exc)[:500]}},ensure_ascii=False)+'\n\n'
        yield 'data: '+json.dumps({'id':cid,'object':'chat.completion.chunk','choices':[{'index':0,'delta':{},'finish_reason':'stop'}]})+'\n\n'
        yield 'data: [DONE]\n\n'
    return StreamingResponse(generate(),media_type='text/event-stream')


def model_settings(request):return models.select('chat',request.model)[0],models.profiles()
