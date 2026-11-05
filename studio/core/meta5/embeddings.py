"""Local-only CPU embeddings with versioned float32 cache and bounded background work."""
import hashlib,json,math,struct,threading,time
from contextlib import closing
from pathlib import Path
import sqlite3,httpx
from . import transport
from .phase11_config import load
from .privacy import sensitive

def pack(vector):
    if not vector or len(vector)>32768 or any(type(x) not in (float,int) or not math.isfinite(x) for x in vector):raise ValueError('Invalid embedding')
    return struct.pack('<'+'f'*len(vector),*vector)
def unpack(blob,dimensions):
    if len(blob)!=dimensions*4:raise ValueError('Invalid vector size')
    return list(struct.unpack('<'+'f'*dimensions,blob))
def cosine(a,b):
    if not a or len(a)!=len(b):return 0.
    norm=math.sqrt(sum(x*x for x in a)*sum(x*x for x in b))
    return sum(x*y for x,y in zip(a,b))/norm if norm else 0.

class Embeddings:
    def __init__(self,path,client=None):self.path=Path(path);self.client=client;self._metadata=None
    def metadata(self):
        cfg=load('memory');model=cfg['model']
        if self._metadata and self._metadata[0]==model and time.monotonic()-self._metadata[2]<60:return self._metadata[:2]
        with httpx.Client(timeout=3,trust_env=False) as c:
            r=c.get(transport.BASE+'/api/tags');r.raise_for_status()
        row=next((m for m in r.json().get('models',[]) if m['name'] in (model,model+':latest')),None)
        if row is None:raise ValueError('Embedding model not installed')
        self._metadata=(model,row['digest'],time.monotonic());return self._metadata[:2]
    def vectors(self,texts,background=False):
        cfg=load('memory')
        if not cfg['embeddings_enabled'] or not texts or any(sensitive(t) for t in texts):return None
        if self.client:return self.client(texts)
        try:
            model,version=self.metadata();keys=[hashlib.sha256((model+'\0'+version+'\0'+t).encode()).hexdigest() for t in texts]
            output=[None]*len(texts);missing=[]
            with closing(sqlite3.connect(self.path,timeout=5)) as db:
                for i,key in enumerate(keys):
                    row=db.execute('SELECT vector,dimensions FROM embedding_cache WHERE key=?',(key,)).fetchone()
                    if row:output[i]=unpack(*row)
                    else:missing.append(i)
            if not missing:return output
            if not transport.COMPUTE.acquire(blocking=False):return None
            try:
                with httpx.Client(timeout=max(1,min(30,cfg['embedding_timeout'])),trust_env=False) as c:
                    if background:
                        active=c.get(transport.BASE+'/api/ps');active.raise_for_status()
                        if any(m.get('name')!=model for m in active.json().get('models',[])):return None
                    for start in range(0,len(missing),max(1,min(32,int(cfg['embedding_batch'])))):
                        indices=missing[start:start+max(1,min(32,int(cfg['embedding_batch'])))]
                        r=c.post(transport.BASE+'/api/embed',json={'model':model,'input':[texts[i][:6000] for i in indices],
                            'truncate':True,'keep_alive':0,'options':{'num_gpu':0}});r.raise_for_status();vectors=r.json()['embeddings']
                        if len(vectors)!=len(indices):raise ValueError('Embedding batch mismatch')
                        with closing(sqlite3.connect(self.path,timeout=5)) as db,db:
                            for i,v in zip(indices,vectors):
                                blob=pack(v);db.execute('INSERT OR REPLACE INTO embedding_cache VALUES(?,?,?,?,?,?)',(keys[i],model,version,len(v),blob,time.time()));output[i]=v
                return output
            finally:transport.COMPUTE.release()
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error,httpx.HTTPError):return None
    def index(self,records,background=True):
        safe=[r for r in records if not sensitive(r['text'])]
        if not safe:return 0
        try:model,version=self.metadata() if not self.client else ('mock','test')
        except Exception:return 0
        with closing(sqlite3.connect(self.path,timeout=5)) as db:
            pending=[r for r in safe if not db.execute('SELECT 1 FROM embeddings WHERE owner_type=? AND owner_id=? AND model=? AND version=? AND text_hash=?',
                (r['type'],r['id'],model,version,hashlib.sha256(r['text'].encode()).hexdigest())).fetchone()]
        if not pending:return len(safe)
        vectors=self.vectors([r['text'] for r in pending],background)
        if vectors is None:return 0
        with closing(sqlite3.connect(self.path,timeout=5)) as db,db:
            for row,v in zip(pending,vectors):db.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?,?,?,?,?)',
                (row['type'],row['id'],model,version,len(v),pack(v),hashlib.sha256(row['text'].encode()).hexdigest(),time.time()))
        return len(safe)

_workers={};_lock=threading.Lock()
def start_indexer(memory):
    path=str(Path(memory.path).resolve())
    with _lock:
        if path in _workers:return
        stop=threading.Event();_workers[path]=stop
    def worker():
        try:
            if __import__('os').name=='nt':
                import ctypes
                ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(),-2)
            while not stop.is_set():
                started=time.monotonic();engine=Embeddings(memory.path)
                try:
                    records=memory.indexable();count=0
                    batch_size=max(1,min(32,int(load('memory')['embedding_batch'])))
                    for start in range(0,len(records),batch_size):
                        batch=records[start:start+batch_size]
                        done=engine.index(batch,True);count+=done
                        if done<len(batch):break
                        if stop.wait(.05):return
                    event={'indexed':count,'eligible':len(records),'seconds':round(time.monotonic()-started,3)}
                except Exception as exc:event={'error':type(exc).__name__}
                log=Path(memory.path).with_name('memory_index.log')
                with log.open('a',encoding='utf-8') as f:f.write(json.dumps(event)+'\n')
                if log.stat().st_size>1_000_000:
                    lines=log.read_text('utf-8').splitlines()[-500:];log.write_text('\n'.join(lines)+'\n',encoding='utf-8')
                stop.wait(max(5,load('memory')['background_interval']))
        finally:
            with _lock:_workers.pop(path,None)
    threading.Thread(target=worker,daemon=True,name='META-memory-index').start()
