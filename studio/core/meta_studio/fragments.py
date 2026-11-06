"""Recover text drafts from an interrupted JSON string; never execute fragments."""
import ast,json,re

class IncompleteAction(ValueError):
    def __init__(self,raw,reason,cause='unknown'):
        super().__init__(reason);self.raw=raw;self.cause=cause

def python_checkpoint(previous,fragment):
    combined=previous+fragment
    ends=[m.end() for m in re.finditer('\n',combined)][-200:]
    for end in reversed(ends):
        try:ast.parse(combined[:end])
        except (SyntaxError,ValueError):continue
        return fragment[:max(0,end-len(previous))]
    return fragment

def append_without_repeat(previous,fragment,path):
    # KMP: longest existing suffix matching the incoming prefix, linear time.
    values=[*fragment,None,*previous[-len(fragment):]] if fragment else []
    lengths=[0]*len(values)
    for i in range(1,len(values)):
        size=lengths[i-1]
        while size and values[i]!=values[size]:size=lengths[size-1]
        if values[i]==values[size]:size+=1
        lengths[i]=size
    overlap=lengths[-1] if lengths else 0
    if overlap>=24:fragment=fragment[overlap:]
    if not fragment.strip():raise ValueError('Порция не добавляет нового кода; продолжи с последней строки файла')
    if len(fragment)>160 and fragment[:160] in previous:raise ValueError('Порция повторяет уже сохранённый код. Прочитай конец файла и верни только продолжение, либо используй edit.')
    if path.endswith('.py'):
        old_names=set(re.findall(r'^def\s+(\w+)\s*\(',previous,re.M));new_names=set(re.findall(r'^def\s+(\w+)\s*\(',fragment,re.M))
        if old_names&new_names:raise ValueError('Функция уже существует: '+', '.join(sorted(old_names&new_names))+'. Исправь её через edit вместо дублирования.')
    return previous+fragment

def string_prefix(raw):
    end=0;i=0
    while i<len(raw):
        c=raw[i]
        if c=='"':break
        if ord(c)<32:return None
        if c=='\\':
            if i+1>=len(raw):break
            if raw[i+1]=='u':
                if i+6>len(raw):break
                if not re.fullmatch('[0-9a-fA-F]{4}',raw[i+2:i+6]):return None
                i+=6
            elif raw[i+1] in '"\\/bfnrt':i+=2
            else:return None
        else:i+=1
        end=i
    try:
        value=json.loads('"'+raw[:end]+'"')
        if value and 0xD800<=ord(value[-1])<=0xDBFF:value=value[:-1]
        value.encode('utf-8')
        return value
    except (ValueError,UnicodeError):return None

def recover(raw):
    content=re.search(r'"content"\s*:\s*"',raw)
    if not content:return None
    # Require a valid structured prefix, rather than matching keys inside code.
    try:head=json.loads(raw[:content.start()]+'"content":""}}')
    except ValueError:return None
    action=head.get('action');args=head.get('args',{})
    if action not in ('write','append') or not isinstance(args,dict) or not isinstance(args.get('path'),str):return None
    text=string_prefix(raw[content.end():])
    if not text:return None
    if action=='append' and not re.fullmatch('[a-f0-9]{64}',str(args.get('sha256',''))):return None
    args.update(content=text,complete=False)
    return {'action':action,'args':args}
