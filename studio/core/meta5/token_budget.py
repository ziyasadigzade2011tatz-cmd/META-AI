"""One budget for the full chat prompt, including all system blocks and framing."""
import copy
import math
import re
from .phase11_config import load


class BudgetExceeded(ValueError):
    pass


def limits(context,mode='chat'):
    if type(context) is not int or not 2048<=context<=16384:raise ValueError('Invalid context window')
    if mode not in ('chat','thinking','code'):raise ValueError('Invalid budget mode')
    cfg=load('context_budget');base=cfg['base_context']
    if type(base) is not int or base<2048:raise ValueError('Invalid base context')
    inp=math.floor(cfg[mode+'_input']*context/base);out=math.floor(cfg[mode+'_output']*context/base)
    if inp<1 or out<1 or inp+out>=context:raise ValueError('Invalid token allocation')
    return {'mode':mode,'context_tokens':context,'input_limit':inp,'output_limit':out,'reserve_tokens':context-inp-out}


def utf8_upper_bound(messages):
    # Qwen byte BPE cannot exceed one token per UTF-8 byte. The extra 128 per
    # message and 256 cover text framing with ample margin; never called exact.
    return 256+sum(len(str(m.get('content','')).encode('utf-8'))+128 for m in messages)


def system_blocks(policy,system):
    """Keep policy mandatory and make optional context independently budgetable."""
    if not system.startswith(policy):raise BudgetExceeded('Неверная базовая инструкция')
    extras=system[len(policy):].strip()
    rows=[{'role':'system','content':policy}]
    if extras:
        for part in re.split(r'\n(?=(?:Системное локальное время:|Контекст темы:|Значения слов,|Неподтверждённые предположения|Материалы проекта|Память пользователя|Релевантные выдержки|WEB EVIDENCE|Поиск не удался))',extras):
            if part.strip():rows.append({'role':'system','content':part.strip()})
    return rows


def fit(messages,allocation,count,method='qwen35_gguf'):
    kept=copy.deepcopy(messages)
    if not kept or kept[-1].get('role')!='user':raise BudgetExceeded('Ожидается последнее сообщение пользователя')
    if not isinstance(kept[0].get('content'),str):raise BudgetExceeded('Некорректная инструкция')
    before=count(kept);dropped=0;shortened=0;cap=allocation['input_limit']
    # Preserve the leading system instruction and the latest question. Older
    # turns go first; optional system blocks are shortened next, as data only.
    while count(kept)>cap:
        removable=next((i for i,m in enumerate(kept[1:-1],1) if m.get('role')!='system'),None)
        if removable is None:break
        kept.pop(removable);dropped+=1
    while count(kept)>cap:
        optional=next((i for i in range(len(kept)-2,0,-1) if kept[i].get('role')=='system'),None)
        if optional is None:break
        original=kept[optional]['content'];marker='\n[Недоверенные данные сокращены по бюджету контекста.]'
        # Find a fitting prefix without touching the mandatory policy/question.
        low=0;high=len(original);best=None
        while low<=high:
            mid=(low+high)//2;kept[optional]['content']=original[:mid]+marker
            if count(kept)<=cap:best=original[:mid]+marker;low=mid+1
            else:high=mid-1
        if best is not None and len(best)>len(marker)+80:
            kept[optional]['content']=best;shortened+=1
            if count(kept)<=cap:break
        kept.pop(optional);dropped+=1
    # The first system message is structured into required policy + optional
    # context sections by prepare(); never silently clip a user question/policy.
    while count(kept)>cap and len(kept)>2:
        kept.pop(1);dropped+=1
    actual=count(kept)
    if actual>cap:raise BudgetExceeded('Вопрос и обязательные инструкции не помещаются в контекст. Сократи сообщение или увеличь контекст в настройках.')
    usage={**allocation,'input_tokens':actual,'count_method':method,'exact':method=='qwen35_gguf',
           'input_tokens_before':before,'dropped_messages':dropped,'shortened_blocks':shortened,'history_truncated':bool(dropped or shortened),
           'estimated_characters':sum(len(m['content']) for m in kept),
           'input_percent':round(actual/allocation['context_tokens']*100,1),
           'allocated_percent':round((actual+allocation['output_limit'])/allocation['context_tokens']*100,1)}
    return kept,usage


def prepare(messages,model,context,thinking=False,count=None):
    allocation=limits(context,'thinking' if thinking else 'chat')
    method='qwen35_gguf'
    if count is None:
        try:
            from .qwen_tokens import counter
            count=counter(model,thinking)
        except Exception:
            # The upper bound remains conservative for the supported Qwen
            # text path. Do not mislabel an approximation as exact tokenization.
            if not model.startswith('qwen3.5:') or load('context_budget').get('fallback')!='utf8_upper_bound':raise BudgetExceeded('Для выбранной модели недоступен проверенный счётчик контекста')
            count=utf8_upper_bound;method='utf8_upper_bound'
    try:return fit(messages,allocation,count,method)
    except BudgetExceeded:raise
    except Exception as exc:raise BudgetExceeded('Не удалось проверить размер контекста; запрос не отправлен') from exc
