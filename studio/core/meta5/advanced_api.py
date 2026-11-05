"""Authenticated extension routes, attached to the existing /agent40 router."""
import re,json,threading
from pathlib import Path
from fastapi import HTTPException
from .storage import STATE,read_json,atomic_json
from . import advanced,models,transport

def install(router,manager,checked_project):
 @router.get('/advanced/status')
 def status():
  return {'settings':advanced.settings(),'schedules':advanced.schedules(),'plans':[read_json(p,{}) for p in sorted((STATE/'plans').glob('*.json'))[-30:]],'skills':[p.stem for p in (STATE/'skills').glob('*.md')], 'features':['native_tools','verification_loop','readonly_specialists','project_memory','semantic_memory','skills','audit_hooks','mcp_local_http','research','thinking','artifacts','scheduled_analysis','plan_approval','opt_in_computer']}
 @router.get('/advanced/notes')
 def notes(project:str='.'):
  try:return advanced.notes(str(checked_project(project).root))
  except (ValueError,OSError) as exc:raise HTTPException(400,str(exc))
 @router.post('/advanced/action')
 def action(payload:dict):
  try:
   operation=payload.get('operation');value=payload.get('value',{})
   if not isinstance(value,dict):raise ValueError('Object required')
   if operation=='configure':
    from .native_tools import supports
    # Model names must exist; never trigger downloads or switch to cloud.
    with __import__('httpx').Client(timeout=5,trust_env=False) as c:
     response=c.get(transport.BASE+'/api/tags');response.raise_for_status();available={m['name'] for m in response.json().get('models',[])}
    for name in ('embed_model','thinking_model','chat_model','understand_model'):
     if value.get(name) and value[name] not in available and value[name]+':latest' not in available:raise ValueError('Model not installed: '+value[name])
    if value.get('thinking',advanced.settings()['thinking']) and not supports(value.get('thinking_model',advanced.settings()['thinking_model']),'thinking'):raise ValueError('Selected model does not advertise thinking')
    return advanced.configure(value)
   if operation=='init_project':
    project=checked_project(value.get('project','.'));index=project.index();text='# Проект\n\nЯзыки: '+', '.join(index['languages'])+'\n\nМанифесты: '+', '.join(index['manifests'])+'\n\n## Цель\nУточнить у пользователя.\n\n## Команды проверок\nУказать проверенные команды.\n'
    if advanced.notes(str(project.root))['text']:raise ValueError('Project notes already exist; refusing overwrite')
    return advanced.save_notes(str(project.root),text)
   if operation=='notes':return advanced.save_notes(str(checked_project(value.get('project','.')).root),value.get('text',''))
   if operation=='skill':return advanced.save_skill(value['name'],value['text'])
   if operation=='plan':return advanced.make_plan(value['task'],value.get('project','.')) if checked_project(value.get('project','.')) else None
   if operation=='approve_plan':
    with advanced.LOCK:
     plan=advanced.read_plan(value['id'])
     if plan['status']!='awaiting_approval':raise ValueError('Plan already handled')
     result=manager.start({'task':plan['task'],'project':plan['project'],'history':[{'role':'user','content':'План, одобренный пользователем: '+json.dumps(plan['steps'],ensure_ascii=False)}],'allow_tests':False,'allow_web':True})
     plan.update(status='started',job=result['id']);atomic_json(STATE/'plans'/(plan['id']+'.json'),plan);return plan
   if operation=='schedule':
    checked_project(value.get('project','.'));return advanced.add_schedule(value.get('project','.'),value['task'],value['interval'])
   if operation=='schedule_toggle':
    with advanced.LOCK:
     rows=advanced.schedules();found=False
     for row in rows:
      if row['id']==value['id']:
       if type(value.get('enabled')) is not bool:raise ValueError('Boolean required')
       row['enabled']=value['enabled'];found=True
     if not found:raise ValueError('Schedule not found')
     atomic_json(STATE/'schedules.json',rows);return rows
   if operation=='semantic_search':
    from .memory import Memory
    return {'facts':advanced.semantic(value['query'],Memory().list())}
   if operation=='mcp_probe':
    from .mcp_client import Client
    name=value['server'];server=advanced.settings()['mcp_servers'].get(name)
    if not server:raise ValueError('MCP server not configured')
    with Client(name,server) as c:return {'tools':c.tools()}
   raise ValueError('Unknown operation')
  except HTTPException:raise
  except Exception as exc:raise HTTPException(400,type(exc).__name__+': '+str(exc)[:300])
 advanced.start_scheduler(manager)
