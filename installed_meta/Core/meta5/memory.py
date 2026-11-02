import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from .storage import STATE


class Memory:
    def __init__(self,path=None):self.path=path or STATE/'memory.sqlite'
    @contextmanager
    def db(self):
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
        with self.db() as c:c.execute('INSERT OR IGNORE INTO facts VALUES(?,?,?,?)',(pid,kind,value,time.time()))
        return pid
    def delete(self,pid):
        with self.db() as c:c.execute('DELETE FROM facts WHERE id=?',(pid,))
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
        explicit=re.match(r'^запомни\s*:\s*(.+)',text,re.I|re.S)
        pref=re.fullmatch(r'\s*(?:я (?:люблю|предпочитаю|играю в)|мне нравится)\s+.{2,250}[.!]?\s*',text,re.I)
        if explicit or pref:
            try:self.add(explicit.group(1) if explicit else text.strip(),'fact' if explicit else 'preference')
            except ValueError:pass
    def summary(self,session,value=None):
        with self.db() as c:
            if value is None:
                r=c.execute('SELECT value FROM summaries WHERE session=?',(session,)).fetchone();return r[0] if r else ''
            c.execute('INSERT OR REPLACE INTO summaries VALUES(?,?,?)',(session,str(value)[:5000],time.time()))
