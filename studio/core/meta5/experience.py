"""Scoped, user-controlled experience. No model training or network calls."""
import json
from pathlib import Path
import re
import sqlite3
import time
from contextlib import contextmanager
from .storage import STATE
from .privacy import sensitive

def terms(text):
    stop={'используй','нужно','всегда','правило','проект','вместо','только','чтобы','этого','этой','впредь','пожалуйста'}
    return {s[:6] for s in re.findall(r'[a-zа-яё]{4,}',text.lower()) if s not in stop}

class Experience:
    def __init__(self,path=None):
        self.path=Path(path) if path else STATE/'experience.sqlite'
    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        db.executescript('''CREATE TABLE IF NOT EXISTS rules(
        id INTEGER PRIMARY KEY, rule TEXT, issue TEXT, scope TEXT, scope_key TEXT,
        source TEXT, confidence REAL, status TEXT, created REAL, updated REAL,
        replaced_by INTEGER, evidence TEXT);
        CREATE TABLE IF NOT EXISTS options(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS outcomes(task TEXT PRIMARY KEY, checks TEXT, created REAL);''')
        try:
            with db:yield db
        finally:db.close()
    def enabled(self):
        with self.db() as db:
            row=db.execute("SELECT value FROM options WHERE key='enabled'").fetchone()
            return not row or row[0]=='1'
    def add(self,rule,project='.',task='',source='user',confirmed=False,scope=None):
        rule=str(rule).strip()
        if not 4<=len(rule)<=400 or sensitive(rule) or re.search(r'```|[{};]|https?://|\bdef\s|\bclass\s',rule):
            raise ValueError('Правило должно быть коротким, без кода, документов и личных данных')
        scope=scope or ('project' if project and project!='.' else 'task')
        if scope not in ('task','project','global'):raise ValueError('Неверная область правила')
        key=project if scope=='project' else task if scope=='task' else ''
        if scope!='global' and not key:raise ValueError('Нужна задача или проект')
        now=time.time();status='confirmed' if confirmed and source=='user' else 'candidate'
        with self.db() as db:
            row=db.execute('SELECT id FROM rules WHERE rule=? AND scope=? AND scope_key=? AND status IN (\'candidate\',\'confirmed\')',(rule,scope,key)).fetchone()
            if row:return row[0]
            return db.execute('INSERT INTO rules(rule,issue,scope,scope_key,source,confidence,status,created,updated,evidence) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (rule,'explicit correction' if confirmed else 'unconfirmed suggestion',scope,key,source,1 if status=='confirmed' else .4,status,now,now,'[]')).lastrowid
    def capture(self,text,project='.',task=''):
        if not self.enabled() or re.search(r'например|как пример|for example',text,re.I):return None
        match=re.fullmatch(r'\s*(запомни(?: правило)?|поправка|впредь)\s*[:—-]\s*(.{4,400})',text,re.I|re.S)
        candidate=re.fullmatch(r'\s*(?:нет[, ]+|не так[, :]+|я имел в виду[, :]+)(.{4,300})',text,re.I|re.S)
        if not match and not candidate:return None
        try:return self.add(match[2] if match else candidate[1],project,task,confirmed=bool(match))
        except ValueError:return None
    def select(self,text,project='.',task='',limit=6):
        if not self.enabled():return []
        query=terms(text);rows=[]
        with self.db() as db:
            for row in db.execute("SELECT * FROM rules WHERE status='confirmed' ORDER BY updated DESC LIMIT 500"):
                if row['scope']=='task' and row['scope_key']!=task:continue
                if row['scope']=='project' and row['scope_key']!=project:continue
                overlap=len(query & terms(row['rule']))
                if overlap<(2 if row['scope']=='global' else 1):continue
                rows.append({'id':row['id'],'rule':row['rule'],'scope':row['scope'],'reason':'scope_match_and_keywords','score':overlap})
        result=sorted(rows,key=lambda r:-r['score'])[:limit]
        if task and result:
            with self.db() as db:db.execute('INSERT OR REPLACE INTO options VALUES(?,?)',('last:'+task,json.dumps([r['id'] for r in result])))
        return result
    def outcome(self,task,checks):
        # Only check categories/status; never file contents or model answers.
        safe=[{'status':r.get('status'),'scope':str(r.get('scope',''))[:100]} for r in checks[:50]]
        with self.db() as db:db.execute('INSERT OR REPLACE INTO outcomes VALUES(?,?,?)',(task,json.dumps(safe),time.time()))
    def command(self,text,project='.',task=''):
        if text.strip().lower()=='забудь это правило':
            with self.db() as db:
                row=db.execute('SELECT value FROM options WHERE key=?',('last:'+task,)).fetchone()
                ids=json.loads(row[0]) if row else []
                if len(ids)!=1:return 'Укажи номер правила: /learn list, затем /learn forget ID'
                db.execute('DELETE FROM rules WHERE id=?',(ids[0],));return 'Правило забыто'
        parts=text.strip().split(maxsplit=2);action=parts[1] if len(parts)>1 else 'list';arg=parts[2] if len(parts)>2 else ''
        with self.db() as db:
            if action in ('on','off'):
                db.execute("INSERT OR REPLACE INTO options VALUES('enabled',?)",('1' if action=='on' else '0',));return 'Опыт '+('включён' if action=='on' else 'выключен')
            if action in ('list','candidates'):
                rows=db.execute('SELECT id,rule,scope,status FROM rules'+(" WHERE status='candidate'" if action=='candidates' else '')+' ORDER BY id DESC LIMIT 50').fetchall()
                return json.dumps([dict(r) for r in rows],ensure_ascii=False)
            if action in ('forget','remove','reject','confirm'):
                ident=int(arg)
                if action in ('forget','remove'):db.execute('DELETE FROM rules WHERE id=?',(ident,))
                elif action=='confirm':db.execute("UPDATE rules SET status='confirmed',source='user',confidence=1,updated=? WHERE id=?",(time.time(),ident))
                else:db.execute("UPDATE rules SET status='rejected',updated=? WHERE id=?",(time.time(),ident))
                return 'Правило обновлено'
        if action in ('add','global'):return 'Правило '+str(self.add(arg,project,task,confirmed=True,scope='global' if action=='global' else None))
        if action=='edit':
            ident,rule=arg.split(maxsplit=1)
            with self.db() as db:old=db.execute('SELECT * FROM rules WHERE id=?',(int(ident),)).fetchone()
            if not old:raise ValueError('Правило не найдено')
            new=self.add(rule,old['scope_key'] if old['scope']=='project' else '.',old['scope_key'] if old['scope']=='task' else '',confirmed=True,scope=old['scope'])
            if new!=old['id']:
                with self.db() as db:db.execute("UPDATE rules SET status='replaced',replaced_by=?,updated=? WHERE id=?",(new,time.time(),old['id']))
            return 'Правило '+str(new)
        raise ValueError('/learn list|candidates|add текст|global текст|confirm ID|reject ID|edit ID текст|forget ID|on|off')
