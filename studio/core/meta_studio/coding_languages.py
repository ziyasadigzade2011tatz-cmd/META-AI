"""Small task-selected engineering references, not model training or web downloads."""
import json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'config/coding'

def guidance(task,paths=()):
    data=json.loads((ROOT/'languages.json').read_text('utf-8'));selected=[]
    for name,p in data.items():
        if re.search(p['pattern'],task,re.I) or any(str(path).lower().endswith(tuple(p['extensions'])) for path in paths):selected.append(name)
    web_task=re.sub(r'\bне\s+(?:сайт\w*|лендинг\w*)|\bбез\s+веб[ -]?интерфейс\w*','',task,flags=re.I)
    if re.search(r'\b(?:сайт\w*|лендинг\w*|веб[ -]?страниц\w*|website|landing|frontend|front-end)\b',web_task,re.I):selected=list(dict.fromkeys([*selected,'javascript','css']))
    return {'languages':selected,'guidance':[{'language':name,'rules':data[name]['rules'],'reference':data[name]['reference']} for name in selected]}

def reference(language,topic=''):
    profiles=json.loads((ROOT/'languages.json').read_text('utf-8'))
    if language not in profiles:raise ValueError('Выбери python, javascript, css, csharp или cpp')
    document=(ROOT/(language+'.md')).read_text('utf-8')
    words=set(re.findall(r'[a-zа-яё]{3,}',topic.lower()))
    sections=re.split(r'(?m)^## ',document)
    ranked=sorted(enumerate(sections),key=lambda item:(-sum(word in item[1].lower() for word in words),item[0]))
    text='\n## '.join(value for _,value in ranked[:2])
    return {'language':language,'topic':topic[:100],'text':text[:2400],'truncated':len(text)>2400,'reference':profiles[language]['reference'],'scope':'Локальная инженерная памятка, не результат компиляции или обучения модели'}

def css_structure(text):
    """Lexical balance only: not a full CSS grammar or browser compatibility test."""
    stack=[];quote=None;comment=False;i=0
    while i<len(text):
        c=text[i];pair=text[i:i+2]
        if comment:
            if pair=='*/':comment=False;i+=2;continue
        elif quote:
            if c=='\\':i+=2;continue
            if c==quote:quote=None
        elif pair=='/*':comment=True;i+=2;continue
        elif c=='\\':i+=2;continue
        elif c in ('"',"'"):quote=c
        elif c in '{[(':stack.append(c)
        elif c in '}])':
            if not stack or stack.pop()!={'}':'{',']':'[',')':'('}[c]:return {'status':'failed','scope':'CSS delimiter check only','error':'Несогласованные скобки CSS'}
        i+=1
    if stack or quote or comment:return {'status':'failed','scope':'CSS delimiter check only','error':'Незавершённая строка, комментарий или блок CSS'}
    return {'status':'passed','scope':'CSS delimiter check only; properties/layout/browser not checked'}
