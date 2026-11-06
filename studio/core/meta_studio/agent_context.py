"""Keep the task and recent tool state within an approximate text budget."""
import json
from meta5.project import digest

def compact(messages,context):
    budget=max(6000,min(28000,int(context)*2));out=[]
    for i,m in enumerate(messages):
        value=dict(m);content=value['content']
        if i==1:
            try:
                data=json.loads(content)
                if isinstance(data,dict) and 'task' in data:
                    if isinstance(data.get('brief'),dict):data['brief']={k:v for k,v in data['brief'].items() if k not in ('original_task','goal')}
                    for key,limit in (('files',30),('symbols',16),('relevant_files',8)):
                        if isinstance(data.get(key),list):data[key]=data[key][:limit]
                    value['content']=json.dumps(data,ensure_ascii=False)
            except ValueError:pass
        elif m['role']=='assistant':
            try:
                data=json.loads(content);args=data.get('args',{})
                if data.get('action') in ('write','append','edit') and isinstance(args,dict):
                    for key in ('content','old','new'):
                        if isinstance(args.get(key),str) and len(args[key])>600:
                            text=args.pop(key);data[key+'_omitted']={'characters':len(text),'sha256':digest(text.encode('utf-8'))}
                    value['content']=json.dumps(data,ensure_ascii=False)
            except (ValueError,AttributeError):pass
        out.append(value)
    pinned=[*out[:2],*[m for m in out[2:] if m['content'].startswith(('REFERENCE_RESEARCH','IMAGE_OBSERVATIONS'))]]
    rest=[m for m in out[2:] if not m['content'].startswith(('REFERENCE_RESEARCH','IMAGE_OBSERVATIONS'))]
    while len(rest)>2 and sum(len(m['content']) for m in [*pinned,*rest])>budget:rest=rest[2:]
    return [*pinned,*rest]
