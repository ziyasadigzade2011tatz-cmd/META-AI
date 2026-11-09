"""Keep the task and recent tool state within an approximate text budget."""
import json
from meta5.project import digest

def fit_request(messages, context, model, count=None):
    """Budget the complete outbound prompt, preserving policy and task.

    Tokenization is exact only for validated Qwen renderers; other models use
    a conservative UTF-8 upper bound. Oversized mandatory input fails locally.
    """
    from meta5.token_budget import limits, utf8_upper_bound, BudgetExceeded
    allocation = limits(context, 'code')
    if count is None:
        try:
            from meta5.qwen_tokens import agent_counter
            if not model.startswith(('qwen3.5:', 'mimo-v2.6:')):
                raise ValueError('Unvalidated tokenizer')
            count = agent_counter(model)
        except Exception:
            count = utf8_upper_bound
    rows = compact(messages, context)
    cap = allocation['input_limit']
    # Optional project metadata must never displace the user's actual goal.
    if len(rows) > 1:
        try:
            task = json.loads(rows[1]['content'])
            if isinstance(task, dict) and 'task' in task and count(rows[:2]) > cap:
                rows[1] = {**rows[1], 'content': json.dumps(
                    {k: task[k] for k in ('task', 'new_project', 'brief') if k in task}, ensure_ascii=False)}
        except (ValueError, TypeError):
            pass
    # Evict oldest complete action/result pairs first. Keep latest tool state
    # (including append hashes and tails) intact; never silently clip code.
    while count(rows) > cap and len(rows) > 4:
        index = next((i for i in range(2, len(rows)-2)
                      if rows[i].get('role') == 'assistant'), None)
        if index is None:
            rows.pop(2)
        else:
            del rows[index:index+2]
    while count(rows) > cap and len(rows) > 2:
        if len(rows) <= 4:
            raise BudgetExceeded('Последний результат инструмента слишком велик для контекста. Прочитай меньший диапазон строк или увеличь контекст.')
        rows.pop(2)
    if count(rows) > cap:
        raise BudgetExceeded('Задача и обязательные инструкции не помещаются в контекст агента.')
    return rows, allocation

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
