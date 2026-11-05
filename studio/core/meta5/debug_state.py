"""Per-chat debug switch, no message text in the state database."""
from contextlib import closing
import hashlib,json,sqlite3
from .storage import STATE
from .understanding_config import settings
from .slang import private

def key(session):return hashlib.sha256(session.encode()).hexdigest()

def enabled(session):
    path=STATE/'understanding.sqlite'
    if not path.exists():return bool(settings()['debug'])
    with closing(sqlite3.connect(path)) as c:
        row=c.execute('SELECT enabled FROM debug_sessions WHERE chat=?',(key(session),)).fetchone()
    return bool(row[0]) if row else bool(settings()['debug'])

def toggle(session,value):
    STATE.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(STATE/'understanding.sqlite')) as c,c:
        c.execute('CREATE TABLE IF NOT EXISTS debug_sessions(chat TEXT PRIMARY KEY,enabled INTEGER)')
        c.execute('INSERT OR REPLACE INTO debug_sessions VALUES(?,?)',(key(session),int(value)))

def render(understanding,resolved,queries,memory):
    if understanding.get('private'):return '\n\nДиагностика: личное сообщение, подробности скрыты.'
    from .relevance import score
    value={'normalized':understanding['normalized'],'topic':resolved['topic'],'intent':understanding['intent'],
           'unknown_terms':understanding['unknown_terms'],'standalone_query':resolved['standalone_query'],
           'search_queries':queries,'dictionary':understanding.get('used_slang',[]),
           'memory':[{'id':r['id'],'text':'***' if private(r['value'],numbers=False) else r['value'],
                      'score':score(understanding['normalized'],r['value']),'reason':'строгая лексическая релевантность'} for r in memory]}
    return '\n\nДиагностика понимания:\n```json\n'+json.dumps(value,ensure_ascii=False,indent=2)+'\n```'
