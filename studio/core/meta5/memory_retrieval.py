"""Hybrid retrieval with explicit profile/category gates and auditable exclusions."""
import hashlib,math,re,time,sqlite3,httpx
from .relevance import terms
from .privacy import sensitive
from .phase11_config import load
from .embeddings import Embeddings,unpack,cosine

CATEGORY_PATTERNS={
 'name':r'\b(?:меня зовут|мо[её] имя)\b',
 'language':r'\b(?:мой язык|говорю на|предпочитаю.*язык)\b',
 'hardware':r'\b(?:vram|озу|видеокарт|ноутбук|процессор|оперативн|ram|gpu)\w*',
 'hobby':r'\b(?:люблю|нравится|увлекаюсь|хобби|предпочитаю|играю)\b',
 'health':r'\b(?:диагноз|болею|аллерги|лекарств)\w*',
 'identity':r'\b(?:гражданств|национальност|религи)\w*',
 'finances':r'\b(?:зарплат|доход|долг|кредит)\w*',
 'relationships':r'\b(?:моя жена|мой муж|развод|отношени)\w*'}

def category(text):
    return next((k for k,p in CATEGORY_PATTERNS.items() if re.search(p,text,re.I)),'general')

def personal(query):
    return bool(re.search(r'\b(?:я|мне|меня|мой|моя|мо[её]|мои|моих|моём|моем|помнишь)\b',query,re.I))

def lexical(query,value,documents):
    """Saturating BM25-like overlap; normalized to [0,1] for mixed scoring."""
    q,d=terms(query),terms(value)
    if not q or not d:return 0.
    scores={t:math.log(1+(len(documents)+.5)/(1+sum(t in doc for doc in documents))) for t in q}
    denominator=sum(scores.values())
    coverage=sum(scores[t] for t in q&d)/denominator if denominator else 0
    short=len(q&d)/min(len(q),len(d))
    return min(1.,max(coverage,short*.95))

def retrieve(memory,query,limit=5,engine=None):
    cfg=load('memory');trace=[];now=time.time();rows=memory.records()
    qterms=terms(query)
    if sensitive(query) or not qterms or re.fullmatch(r'\s*(?:расскажи о себе|что ты умеешь|как дела)[?!.\s]*',query,re.I):
        return [],[{'id':r['id'],'reason':'general_or_private','selected':False} for r in rows]
    eligible=[]
    for row in rows:
        cat=row.get('category') or 'general'
        if cat=='general':cat=category(row['value'])
        reason=None;overlap=bool(qterms & terms(row['value']))
        if row['status']!='confirmed':reason='not_confirmed'
        elif row['expires'] and row['expires']<=now:reason='expired'
        elif sensitive(row['value']):reason='private'
        elif cat in cfg['sensitive_categories'] and (not personal(query) or not overlap):reason='sensitive_category_requires_direct_question'
        elif cat=='name' and not (personal(query) and re.search(r'зовут|имя',query,re.I)):reason='name_not_requested'
        elif cat=='language' and not (personal(query) and re.search(r'язык|говор|перев',query,re.I)):reason='language_not_requested'
        elif cat=='hardware' and not re.search(CATEGORY_PATTERNS['hardware']+r'|модел|ollama|потянет|запуст',query,re.I):reason='hardware_not_requested'
        elif cat=='hobby' and not personal(query):reason='hobby_requires_personal_question'
        if reason:trace.append({'id':row['id'],'selected':False,'reason':reason})
        else:eligible.append(row)
    semantic={};engine=engine or Embeddings(memory.path)
    if cfg['embeddings_enabled'] and eligible:
        try:
            model,version=engine.metadata()
            with memory.db() as c:
                stored={r[0]:r for r in c.execute("SELECT owner_id,vector,dimensions,text_hash FROM embeddings WHERE owner_type='fact' AND model=? AND version=?",(model,version))}
            valid={r['id']:stored[r['id']] for r in eligible if r['id'] in stored and stored[r['id']][3]==hashlib.sha256(r['value'].encode()).hexdigest()}
            vector=engine.vectors([query]) if valid else None
            if vector:
                semantic={pid:max(0.,cosine(vector[0],unpack(r[1],r[2]))) for pid,r in valid.items()}
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error,httpx.HTTPError):pass
    documents=[terms(r['value']) for r in eligible];ranked=[]
    for row in eligible:
        lex=lexical(query,row['value'],documents);sem=semantic.get(row['id'])
        w=max(.001,cfg['cosine_weight']+cfg['lexical_weight'])
        weight=(cfg['cosine_weight']*sem+cfg['lexical_weight']*lex)/w if sem is not None else lex
        allowed=weight>=cfg['memory_gate_threshold'] and (lex>0 or sem is not None and sem>=cfg['semantic_only_threshold'])
        detail={'id':row['id'],'score':round(weight,4),'lexical':round(lex,4),'cosine':round(sem,4) if sem is not None else None,'selected':False,'reason':'below_threshold'}
        trace.append(detail)
        if allowed:ranked.append((weight,row,detail))
    result=[];used=0
    for weight,row,detail in sorted(ranked,key=lambda x:-x[0]):
        size=math.ceil(len(row['value'])/3)
        if len(result)>=min(5,limit,max(0,int(cfg['top_k']))) or used+size>min(600,int(cfg['token_budget'])):detail['reason']='budget';continue
        result.append({k:row[k] for k in ('id','kind','value','created')});used+=size
        detail.update(selected=True,reason='hybrid' if detail['cosine'] is not None else 'lexical_fallback')
    if result:
        with memory.db() as c:c.executemany('UPDATE facts SET last_used=?,use_count=use_count+1 WHERE id=?',[(now,r['id']) for r in result])
    return result,trace
