"""META local Core. Shared chat, research, project tools and coding services."""
import httpx
from fastapi import FastAPI,HTTPException
from pydantic import BaseModel
from agent_chat import ChatRequest,run_agent,agent_completions,model_settings
from meta5 import VERSION
from meta5.api import install,consent

app=FastAPI(title='META Core',version=VERSION)


@app.get('/')
async def home():return {'name':'META Core','version':VERSION,'status':'online'}
@app.get('/health')
async def health():
    try:
        async with httpx.AsyncClient(timeout=5,trust_env=False) as c:
            r=await c.get('http://127.0.0.1:11434/api/tags');r.raise_for_status()
        return {'status':'online','ollama':'connected','version':VERSION}
    except httpx.HTTPError as exc:raise HTTPException(503,'Ollama недоступна') from exc
@app.get('/v1/models')
async def model_list():return {'object':'list','data':[{'id':'meta-core','object':'model','owned_by':'META'}]}
@app.post('/chat')
async def chat(request:ChatRequest):
    consent(request)
    try:return {'assistant':'META','task_type':'chat','internal_model':model_settings(request)[0],'reply':await run_agent(request)}
    except Exception as exc:raise HTTPException(502,str(exc)[:500]) from exc
app.add_api_route('/v1/chat/completions',agent_completions,methods=['POST'])


@app.get('/memory')
async def legacy_memory():
    from memory import recall
    return {'memories':recall()}
@app.delete('/memory/{memory_id}')
async def delete_legacy_memory(memory_id:int):
    from memory import forget
    if not forget(memory_id):raise HTTPException(404,'Memory not found')
    return {'deleted':True,'id':memory_id}


class CreateFileRequest(BaseModel):path:str;content:str
@app.get('/agent/files')
async def files(folder:str='.'):
    from agent_tools import list_files
    try:return {'files':list_files(folder)}
    except (ValueError,OSError) as exc:raise HTTPException(400,str(exc))
@app.get('/agent/read')
async def read(path:str):
    from agent_tools import read_file
    try:return {'path':path,'content':read_file(path)}
    except (ValueError,OSError) as exc:raise HTTPException(400,str(exc))
@app.post('/agent/create')
async def create(request:CreateFileRequest):raise HTTPException(403,'Используй заявку и подтверждение')
@app.post('/agent/stage')
async def stage(request:CreateFileRequest):
    from agent_pending import stage
    try:return stage(request.path,request.content)
    except (ValueError,OSError) as exc:raise HTTPException(400,str(exc))
@app.post('/agent/propose')
async def preview(request:CreateFileRequest):
    from agent_pending import inspect
    try:
        _,_,diff=inspect(request.path,request.content)
        return {'status':'preview_only','path':request.path,'diff':diff,'applied':False}
    except (ValueError,OSError) as exc:raise HTTPException(400,str(exc))

install(app)
