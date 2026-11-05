"""Local glossary. Seed is immutable; user decisions live in a separate SQLite file."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime,timezone
from .understanding_config import ROOT
from .storage import STATE
from .relevance import terms

LOCK=threading.RLock()
DOMAINS={
 'компьютеры':'компьютер ноутбук устройство драйвер память экран',
 'программирование':'код программа функция python javascript ошибка репозиторий',
 'музыка':'музыка композиция песня слушать ритм звук', 'спорт':'спорт тренировка матч упражнение',
 'учёба':'учеба университет школа предмет экзамен занятие', 'работа':'работа сотрудник офис задача встреча',
 'еда':'еда готовить блюдо продукт обед ужин овощ', 'транспорт':'транспорт дорога автомобиль поезд поездка',
 'покупки':'купить покупка магазин товар заказ цена', 'быт':'дом квартира уборка прибор электричество',
 'путешествия':'путешествие рейс аэропорт гостиница турист поездка', 'одежда':'одежда образ носить обувь стиль',
 'книги':'книга читать автор чтение издание', 'кино':'кино фильм сериал смотреть сюжет',
 'природа':'природа погода лес дождь снег холод', 'творчество':'рисовать творчество рисунок изделие узор',
 'отношения':'отношения общение друг свидание человек', 'игры':'игра игрок играть персонаж матч',
 'интернет':'интернет сообщение форум сеть эфир', 'общение':''}

def private(text,numbers=True):
    pattern=r'парол|password|api[ _-]?key|секрет|токен|паспорт|номер карты|cvv|github_pat_|gh[pousr]_|sk-[\w-]{8,}|[\w.+-]+@[\w.-]+|[A-Za-z]:[\\/]|\b(?:улица|адрес|телефон)\b'
    return bool(re.search(pattern,str(text),re.I) or re.search(r'\d' if numbers else r'(?<!\d)(?:\d[ -]?){13,19}(?!\d)',str(text)))

def safe_term(term):
    return bool(re.fullmatch(r'[a-zа-яё][a-zа-яё-]{1,31}',term)) and not private(term) and term not in {
        'вася','петя','коля','маша','даша','саша','зия','лионель','месси','анна','мария','иван','павел','алексей','ольга','никита','дарья'}

def utc():return datetime.now(timezone.utc).isoformat()

class Glossary:
    def __init__(self,path=None):self.path=Path(path or STATE/'slang.sqlite')
    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        c=sqlite3.connect(self.path,timeout=10)
        try:
            c.execute('CREATE TABLE IF NOT EXISTS entries(term TEXT PRIMARY KEY, data TEXT NOT NULL)')
            with c:yield c
        finally:c.close()
    def records(self):
        value={r['term']:r for r in json.loads((ROOT/'slang.json').read_text('utf-8'))}
        if self.path.exists():
            with self.db() as c:
                for term,data in c.execute('SELECT term,data FROM entries'):value[term]=json.loads(data)
        return list(value.values())
    def put(self,record,action):
        if not safe_term(record['term']) or private(json.dumps(record['meaning'],ensure_ascii=False)):
            raise ValueError('Личные данные и секреты не записываются в словарь')
        with LOCK,self.db() as c:
            c.execute('INSERT OR REPLACE INTO entries VALUES(?,?)',(record['term'],json.dumps(record,ensure_ascii=False)))
            with self.path.with_name('slang_changes.log').open('a',encoding='utf-8') as log:
                log.write(json.dumps({'word':record['term'],'action':action,'source':record['source']},ensure_ascii=False)+'\n')
    def add(self,term,meaning,source='user',status='confirmed',domain='общение',confidence=1.):
        term=term.strip().casefold();meaning=meaning.strip()
        if not 2<=len(meaning)<=500:raise ValueError('Определение: от 2 до 500 символов')
        old=next((r for r in self.records() if r['term']==term),{})
        row=dict(term=term,forms=[term],meaning=[{'definition':meaning,'context_hints':[]}],domain=domain,
            register='разговорный',language='ru',confidence=confidence,status=status,source=source,
            seen_count=old.get('seen_count',0)+1,chats_count=old.get('chats_count',0),
            first_seen=old.get('first_seen') or utc(),last_seen=utc(),context_hints=[])
        if old.get('rejected_meanings'):row['rejected_meanings']=old['rejected_meanings']
        self.put(row,'add');return row
    def command(self,text):
        rest=text[len('/slang'):].strip();parts=rest.split(maxsplit=1);verb=parts[0] if parts else '';arg=parts[1] if len(parts)>1 else ''
        rows=self.records()
        if not verb:return '\n'.join(r['term']+' — '+r['meaning'][0]['definition'] for r in rows if r['status']=='confirmed')
        if verb=='candidates':return '\n'.join(r['term']+' — '+r['meaning'][0]['definition'] for r in rows if r['status']=='candidate') or 'Кандидатов нет.'
        if verb=='export':return json.dumps(rows,ensure_ascii=False,indent=2)
        if verb=='add':
            if '=' not in arg:raise ValueError('Формат: /slang add слово=значение')
            term,definition=arg.split('=',1);r=self.add(term,definition);return 'Подтверждено: '+r['term']
        if verb in ('confirm','reject','remove'):
            term=arg.strip().casefold();r=next((r for r in rows if r['term']==term),None)
            if r is None:raise ValueError('Слово не найдено')
            r=dict(r,status='confirmed' if verb=='confirm' else 'rejected',source='user',last_seen=utc())
            self.put(r,verb);return 'Сохранено: '+term+' — '+r['status']
        raise ValueError('Команды: /slang, candidates, add слово=значение, confirm, reject, remove, export')
    def resolve(self,text,context=''):
        vocabulary=terms(context+' '+text);used=[];questions=[];replacements=[];candidates=[]
        for record in self.records():
            if record['status']=='rejected':continue
            forms=record.get('forms') or [record['term']]
            pattern=re.compile(r'(?<!\w)(?:'+'|'.join(re.escape(s) for s in sorted(forms,key=len,reverse=True))+r')(?!\w)',re.I)
            matches=list(pattern.finditer(text))
            if not matches:continue
            if record['status']=='candidate':
                candidates.append({'term':record['term'],'possible_meaning':record['meaning'],'status':'candidate'});continue
            meanings=record['meaning'];rank=[]
            for meaning in meanings:
                hints=terms(' '.join(meaning.get('context_hints',[])))
                weight=len(vocabulary&hints)
                rank.append((weight,meaning))
            rank.sort(key=lambda p:-p[0])
            if len(rank)>1 and rank[0][0]==rank[1][0]:
                options=[m['definition'] for _,m in rank[:3]]
                questions.append('«'+record['term']+'» — '+ ' или '.join(options)+'?');continue
            domain_hints=terms(DOMAINS.get(record['domain'],''))
            general_internet=record['domain']=='интернет' and record['term'] in ('имхо','лол','рофл','кринж','хейт','респект','пруф','фейк','флекс')
            if len(meanings)==1 and domain_hints and not general_internet and not vocabulary&domain_hints:continue
            meaning=rank[0][1]['definition']
            used.append({'term':record['term'],'meaning':meaning,'reason':'контекст' if rank[0][0] else 'однозначное общее слово'})
            # A normal polysemous word is kept verbatim; its selected sense is a hint.
            if len(meanings)==1 or record['term']=='кк':
                for match in matches:replacements.append((match.start(),match.end(),meaning))
        # Prefer longer matched phrases and never apply overlapping substitutions.
        accepted=[]
        for start,end,value in sorted(replacements,key=lambda x:-(x[1]-x[0])):
            if not any(start<b and end>a for a,b,_ in accepted):accepted.append((start,end,value))
        normalized=text
        for start,end,value in sorted(accepted,reverse=True):normalized=normalized[:start]+value+normalized[end:]
        return {'normalized':normalized,'used':used,'candidates':candidates,'question':questions[0] if questions else None}
