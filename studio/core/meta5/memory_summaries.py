"""Summary snapshots are scoped to a chat; cross-chat recall requires an explicit request."""
import hashlib,re,time
from .privacy import sensitive
from .embeddings import Embeddings,unpack,cosine
from .relevance import score

PAST=re.compile(r'помнишь.{0,50}(?:говорили|обсуждали|разговаривали)|(?:прошл\w+|друг\w+)\s+чат|в прошлый раз',re.I)

def checkpoint(memory,session,messages):
    turns=[m for m in messages if m.get('role') in ('user','assistant')]
    if len(turns)<6 or len(turns)%6:return False
    # Extractive baseline retains only user evidence, without inventing a summary.
    older=turns[:-4]
    lines=[m['content'][:500] for m in older[-12:] if m['role']=='user' and isinstance(m.get('content'),str) and not sensitive(m['content'])]
    if not lines:return False
    memory.summary(session,'\n'.join(lines)[:3500]);return True

def recall(memory,session,query):
    if sensitive(query):return []
    with memory.db() as c:
        if PAST.search(query):rows=c.execute('SELECT session,value FROM summaries').fetchall()
        else:rows=c.execute('SELECT session,value FROM summaries WHERE session=?',(session,)).fetchall()
    rows=[r for r in rows if not sensitive(r[1])];semantic={}
    if not rows:return []
    engine=Embeddings(memory.path)
    try:
        model,version=engine.metadata()
        with memory.db() as c:stored={r[0]:r[1:] for r in c.execute("SELECT owner_id,vector,dimensions,text_hash FROM embeddings WHERE owner_type='summary' AND model=? AND version=?",(model,version))}
        vectors=engine.vectors([query]) if stored else None
        if vectors:
            semantic={sid:cosine(vectors[0],unpack(stored[sid][0],stored[sid][1])) for sid,value in rows if sid in stored and stored[sid][2]==hashlib.sha256(value.encode()).hexdigest()}
    except Exception:pass
    ranked=[(max(score(query,value),semantic.get(sid,0)),sid,value) for sid,value in rows]
    return [{'session':sid,'value':value[:1800],'score':round(weight,4)} for weight,sid,value in sorted(ranked,reverse=True)[:2] if weight>=.88]
