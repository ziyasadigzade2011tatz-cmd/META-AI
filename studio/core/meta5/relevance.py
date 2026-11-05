"""Conservative lexical gate; stemming is not a morphological dictionary."""
import re

STOP = set('я ты он она они мы вы это этот эта мне меня тебе тебя мой моя свои свой что как где когда почему зачем какой какая какие такое значит расскажи скажи ответ объясни люблю нравится предпочитаю про для или при без есть было будет очень пожалуйста привет здравствуй спасибо пока да нет хорошо понятно ладно ага угу ок так'.split())
SUFFIXES = ('иями','ями','ами','ого','ему','ому','ыми','ими','иях','ах','ях','ов','ев','ей','ия','ие','ий','ый','ой','ая','яя','ое','ее','ам','ям','ом','ем','ы','и','а','я','у','ю','е','о')

def terms(text):
    out = set()
    for word in re.findall(r'[\w-]{3,}', str(text).casefold().replace('ё','е')):
        if word in STOP: continue
        if re.fullmatch('[а-я]+',word):
            for ending in SUFFIXES:
                if word.endswith(ending) and len(word)-len(ending)>=4:
                    word=word[:-len(ending)];break
        out.add(word)
    return out

def score(query, value):
    a,b=terms(query),terms(value)
    if not a or not b: return 0.0
    overlap=a&b
    if not overlap:return 0.0
    return len(overlap)/min(len(a),len(b))

def select(query, facts, threshold=.65, limit=5, budget=2400):
    ranked=[]
    for fact in facts:
        weight=score(query,fact['value'])
        if weight>=threshold:ranked.append((weight,fact))
    result=[];used=0
    for weight,fact in sorted(ranked,key=lambda p:-p[0]):
        size=len(fact['value'])
        if used+size>budget:continue
        result.append(fact);used+=size
        if len(result)>=limit:break
    return result
