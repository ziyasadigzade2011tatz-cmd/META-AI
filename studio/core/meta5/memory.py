import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from .storage import STATE


class Memory:
    def __init__(self,path=None):
        from pathlib import Path
        self.path=Path(path or STATE/'memory.sqlite').resolve();self._ready=False
    @contextmanager
    def db(self):
        if not self._ready:
            from .memory_schema import migrate
            migrate(self.path);self._ready=True
        from pathlib import Path
        Path(self.path).parent.mkdir(parents=True,exist_ok=True)
        c=sqlite3.connect(self.path,timeout=10)
        c.execute('CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY,kind TEXT,value TEXT UNIQUE,created REAL)')
        c.execute('CREATE TABLE IF NOT EXISTS summaries(session TEXT PRIMARY KEY,value TEXT,updated REAL)')
        c.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)')
        try:
            with c:yield c
        finally:c.close()
    def enabled(self):
        with self.db() as c:r=c.execute("SELECT value FROM settings WHERE key='capture'").fetchone()
        return not r or r[0]=='true'
    def set_enabled(self,value):
        with self.db() as c:c.execute("INSERT OR REPLACE INTO settings VALUES('capture',?)",('true' if value else 'false',))
    def list(self):
        with self.db() as c:rows=c.execute('SELECT id,kind,value,created FROM facts ORDER BY created DESC LIMIT 100').fetchall()
        return [dict(zip(('id','kind','value','created'),r)) for r in rows]
    def add(self,value,kind='fact'):
        if not isinstance(value,str) or not 1<=len(value)<=600:raise ValueError('Память: 1–600 символов')
        if re.search(r'пароль|password|api.?key|секрет|паспорт|cvv|github_pat_|ghp_|sk-',value,re.I):raise ValueError('Секреты не сохраняются в памяти')
        if kind not in ('fact','preference'):raise ValueError('Неверный тип памяти')
        pid=uuid.uuid4().hex
        with self.db() as c:
            c.execute('INSERT OR IGNORE INTO facts(id,kind,value,created) VALUES(?,?,?,?)',(pid,kind,value,time.time()))
            return c.execute('SELECT id FROM facts WHERE value=?',(value,)).fetchone()[0]
    def delete(self,pid):
        with self.db() as c:c.execute('DELETE FROM facts WHERE id=?',(pid,))
    def relevant(self,query,limit=30):
        from .memory_retrieval import retrieve
        selected,self.last_trace=retrieve(self,query,limit)
        return selected
    def update(self,pid,value,kind='fact'):
        if not isinstance(value,str) or not 1<=len(value)<=600:raise ValueError('Память: 1–600 символов')
        if re.search(r'пароль|password|api.?key|секрет|паспорт|cvv|github_pat_|ghp_|sk-',value,re.I):raise ValueError('Секреты не сохраняются')
        if kind not in ('fact','preference'):raise ValueError('Неверный тип памяти')
        try:
            with self.db() as c:c.execute('UPDATE facts SET value=?,kind=? WHERE id=?',(value,kind,pid))
        except sqlite3.IntegrityError as exc:raise ValueError('Такое сведение уже сохранено') from exc
    def capture(self,text):
        if not self.enabled():return
        if re.search(r'не запоминай|не сохраняй|без запоминания',text,re.I):return
        explicit=re.match(r'^(?:запомни\s*:\s*|когда я говорю\s+|в моём словаре\s+)(.+)',text,re.I|re.S)
        pref=re.fullmatch(r'\s*(?:я (?:люблю|предпочитаю|играю в)|мне нравится)\s+.{2,250}[.!]?\s*',text,re.I)
        if explicit or pref:
            try:self.add(explicit.group(1) if explicit else text.strip(),'fact' if explicit else 'preference')
            except ValueError:pass
    def summary(self,session,value=None):
        with self.db() as c:
            if value is None:
                r=c.execute('SELECT value FROM summaries WHERE session=?',(session,)).fetchone();return r[0] if r else ''
            c.execute('INSERT OR REPLACE INTO summaries VALUES(?,?,?)',(session,str(value)[:5000],time.time()))

    def records(self):
        with self.db() as c:
            c.row_factory=sqlite3.Row
            return [dict(r) for r in c.execute('SELECT * FROM facts ORDER BY created DESC')]

    def indexable(self):
        from .privacy import sensitive
        with self.db() as c:
            facts=[{'type':'fact','id':r[0],'text':r[1]} for r in c.execute("SELECT id,value FROM facts WHERE status='confirmed' AND (expires IS NULL OR expires>?)",(time.time(),))]
            summaries=[{'type':'summary','id':r[0],'text':r[1]} for r in c.execute('SELECT session,value FROM summaries')]
        return [r for r in facts+summaries if r['text'] and not sensitive(r['text'])]

