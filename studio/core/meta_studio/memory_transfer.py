"""Preview-first memory transfer. Imported text is data, never an instruction."""
import hashlib,io,json,re,sqlite3,threading,time,uuid,zipfile
from contextlib import closing
from meta5.privacy import sensitive

MAX_BYTES=5_000_000
INSTRUCTION=re.compile(r'ignore.{0,30}(?:instructions|previous)|(?:system|developer)\s*(?:prompt|message)|игнорируй.{0,30}(?:инструкц|правил)|системн\w*\s+инструкц|<\/?(?:system|assistant|script)',re.I)
FIRST=re.compile(r'^(?:я\b|мне\b|меня\b|мой\b|моя\b|мо[её]\b|мои\b|у меня\b|I\b|my\b)',re.I)

def _text(value):
    if isinstance(value,str):return value
    if isinstance(value,list):return '\n'.join(_text(v) for v in value)
    if isinstance(value,dict):return _text(value.get('text',''))
    return ''

def extract(raw,name):
    if len(raw)>MAX_BYTES:raise ValueError('Импорт: файл больше 5 МБ')
    suffix=name.lower().rsplit('.',1)[-1]
    if suffix=='zip':
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=[i for i in archive.infolist() if i.filename.rsplit('/',1)[-1] in ('conversations.json','memories.json')]
            if len(entries)!=1:raise ValueError('ZIP должен содержать один conversations.json или memories.json')
            item=entries[0]
            if item.file_size>MAX_BYTES or item.flag_bits&1:raise ValueError('ZIP слишком большой или зашифрован')
            return extract(archive.read(item),item.filename)
    text=raw.decode('utf-8-sig')
    if suffix in ('txt','md'):
        return [(re.sub(r'^\s*(?:[-*•]|\d+[.)])\s*','',line).strip(),'fact','memory') for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if suffix!='json':raise ValueError('Поддерживаются JSON, TXT, MD и ZIP экспорта')
    data=json.loads(text);rows=[]
    if isinstance(data,dict):
        for key in ('memories','saved_memories','facts'):
            if key in data:data=data[key];break
    if not isinstance(data,list):raise ValueError('JSON: нужен список memories/facts или экспорт conversations')
    for item in data[:5000]:
        if isinstance(item,str):rows.append((item,'fact','memory'));continue
        if not isinstance(item,dict):continue
        if isinstance(item.get('mapping'),dict):
            for node in list(item['mapping'].values())[:2000]:
                if not isinstance(node,dict):continue
                m=node.get('message') or {}
                if not isinstance(m,dict):continue
                author=m.get('author',{});content=m.get('content',{})
                if isinstance(author,dict) and author.get('role')=='user':rows.append((_text(content.get('parts',[]) if isinstance(content,dict) else content),'fact','conversation'))
        elif isinstance(item.get('chat_messages'),list):
            for m in item['chat_messages'][:2000]:
                if isinstance(m,dict) and m.get('sender') in ('human','user'):rows.append((_text(m.get('text') or m.get('content',[])),'fact','conversation'))
        elif item.get('role')=='user':rows.append((_text(item.get('content','')),'fact','conversation'))
        elif any(k in item for k in ('value','memory','fact')):
            rows.append((_text(item.get('value') or item.get('memory') or item.get('fact')), 'preference' if item.get('kind')=='preference' else 'fact','memory'))
        if len(rows)>3000:break
    return rows

class MemoryTransfer:
    def __init__(self,memory):self.memory=memory;self.pending={};self.lock=threading.RLock()
    def _existing(self):
        if not self.memory.path.exists():return set()
        with closing(sqlite3.connect(self.memory.path.as_uri()+'?mode=ro',uri=True)) as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='facts'").fetchone():return set()
            return {r[0] for r in c.execute('SELECT value FROM facts')}
    def preview(self,raw,name):
        if not isinstance(name,str) or len(name)>200:raise ValueError('Неверное имя файла')
        try:source=extract(raw,name)
        except (zipfile.BadZipFile,NotImplementedError,RuntimeError,RecursionError):raise ValueError('Не удалось прочитать структуру экспорта')
        rows=[];seen=set();blocked=0;skipped=0;existing=self._existing()
        for value,kind,origin in source[:3000]:
            values=re.split(r'(?<=[.!?])\s+|\n+',value) if origin=='conversation' else [value]
            for text in values:
                text=text.strip()
                if not 3<=len(text)<=600 or (origin=='conversation' and (not FIRST.search(text) or '```' in text)):
                    skipped+=1;continue
                if sensitive(text) or INSTRUCTION.search(text):blocked+=1;continue
                digest=hashlib.sha256(text.encode('utf-8')).hexdigest()
                if digest in seen:continue
                seen.add(digest);rows.append({'id':digest[:24],'value':text,'kind':kind,'duplicate':text in existing,'origin':origin})
                if len(rows)>=300:break
            if len(rows)>=300:break
        ident=uuid.uuid4().hex
        with self.lock:
            self.pending={k:v for k,v in self.pending.items() if v['expires']>time.monotonic()}
            if len(self.pending)>=4:raise ValueError('Закрой предыдущие предпросмотры импорта')
            self.pending[ident]={'rows':rows,'expires':time.monotonic()+600}
        return {'preview_id':ident,'rows':rows,'blocked':blocked,'skipped':skipped,'expires_in':600,'note':'Выбери только верные факты о себе. Текст импорта не меняет инструкции META.'}
    def apply(self,ident,selected,approved=False):
        if approved is not True:raise ValueError('Нужно явно подтвердить выбранные факты')
        if not isinstance(selected,list) or not 1<=len(selected)<=300 or not all(isinstance(v,str) for v in selected):raise ValueError('Выбери от 1 до 300 записей')
        with self.lock:
            preview=self.pending.get(ident)
            if not preview or preview['expires']<time.monotonic():raise ValueError('Предпросмотр истёк; открой файл заново')
            rows={r['id']:r for r in preview['rows']}
            if any(key not in rows for key in selected):raise ValueError('Запись отсутствует в предпросмотре')
            added=0;duplicates=0
            from meta5.memory_retrieval import category
            with self.memory.db() as c:
                for key in dict.fromkeys(selected):
                    row=rows[key];value=row['value']
                    if sensitive(value) or INSTRUCTION.search(value):raise ValueError('Запись не прошла проверку')
                    if c.execute('SELECT id FROM facts WHERE value=?',(value,)).fetchone():duplicates+=1;continue
                    c.execute('INSERT INTO facts(id,kind,value,created,category,source,confidence,status) VALUES(?,?,?,?,?,?,?,?)',
                              (uuid.uuid4().hex,row['kind'],value,time.time(),category(value),'import:'+ident,1.0,'confirmed'));added+=1
            self.pending.pop(ident,None)
            return {'added':added,'duplicates':duplicates,'batch_id':ident,'existing_records_overwritten':False}
