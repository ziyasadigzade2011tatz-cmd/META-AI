import sqlite3,time,json,hashlib,threading
from contextlib import closing
from .storage import STATE
from .phase11_config import load
from .privacy import sensitive

_ready=set();_lock=threading.Lock()
def database():
    folder=STATE/'knowledge';folder.mkdir(parents=True,exist_ok=True);path=folder/'sources.sqlite'
    with _lock:
        if str(path) not in _ready:
            if path.exists():
                backup=path.with_name(path.name+'.pre11')
                if not backup.exists():
                    with closing(sqlite3.connect(path)) as src,closing(sqlite3.connect(backup)) as dst:src.backup(dst)
            with closing(sqlite3.connect(path,timeout=5)) as db,db:
                db.execute('create table if not exists knowledge(q text primary key,at real,data text)')
                if 'expires' not in {r[1] for r in db.execute('pragma table_info(knowledge)')}:db.execute('alter table knowledge add column expires REAL')
                db.execute('CREATE TABLE IF NOT EXISTS embedding_cache(key TEXT PRIMARY KEY,model TEXT,version TEXT,dimensions INTEGER,vector BLOB,updated REAL)')
                db.execute('CREATE TABLE IF NOT EXISTS embeddings(owner_type TEXT,owner_id TEXT,model TEXT,version TEXT,dimensions INTEGER,vector BLOB,text_hash TEXT,updated REAL,PRIMARY KEY(owner_type,owner_id,model,version))')
                db.execute('CREATE TABLE IF NOT EXISTS cache_metadata(key TEXT PRIMARY KEY,value REAL)')
            _ready.add(str(path))
    return path

def cache(query,sources=None,*,max_age=86400):
    if sensitive(query):return []
    path=database()
    with closing(sqlite3.connect(path,timeout=3)) as db,db:
        limit=max(8,min(1024,int(load('search')['cache_max_mb'])))*1024*1024
        db.execute('PRAGMA max_page_count='+str(max(db.execute('pragma page_count').fetchone()[0],limit//db.execute('pragma page_size').fetchone()[0])))
        key='v11:'+hashlib.sha256(query.casefold().strip().encode()).hexdigest()
        if sources is None:
            row=db.execute('select data,at,expires from knowledge where q=?',(key,)).fetchone()
            if not row or time.time()-row[1]>max_age or row[2] and row[2]<time.time():return []
            result=json.loads(row[0])
            return [{**source,'retrieved_at':row[1],'cached':True} for source in result]
        safe=[s for s in sources if s.get('opened') and not sensitive(s.get('page_text','')) and not any(sensitive(c.get('text','')) for c in s.get('chunks',[]))]
        db.execute('insert or replace into knowledge(q,at,data,expires) values(?,?,?,?)',(key,time.time(),json.dumps(safe,ensure_ascii=False),time.time()+max_age))

def cleanup():
    path=database();now=time.time();cfg=load('search')
    with closing(sqlite3.connect(path,timeout=1)) as db,db:
        row=db.execute("SELECT value FROM cache_metadata WHERE key='last_cleanup'").fetchone()
        if row and now-row[0]<86400:return
        db.execute('DELETE FROM knowledge WHERE expires<? OR expires IS NULL AND at<?',(now,now-cfg['ttl_general']))
        db.execute('DELETE FROM embedding_cache WHERE updated<?',(now-cfg['ttl_general'],))
        db.execute('DELETE FROM embeddings WHERE updated<?',(now-cfg['ttl_general'],))
        limit=max(8,min(1024,int(cfg['cache_max_mb'])))*1024*1024
        # Keep space for vectors; remove oldest cache entries under pressure.
        while (db.execute('PRAGMA page_count').fetchone()[0]-db.execute('PRAGMA freelist_count').fetchone()[0])*db.execute('PRAGMA page_size').fetchone()[0]>limit:
            tables=('knowledge','embedding_cache','embeddings');deleted=0
            for table in tables:
                deleted+=db.execute('DELETE FROM '+table+' WHERE rowid IN (SELECT rowid FROM '+table+' LIMIT 20)').rowcount
            if not deleted:break
        db.execute("INSERT OR REPLACE INTO cache_metadata VALUES('last_cleanup',?)",(now,))
    # Reclaim file pages only in this derived cache, never in chat/memory databases.
    with closing(sqlite3.connect(path,timeout=1)) as db:db.execute('VACUUM')

def start_cleanup():
    def work():
        while True:
            try:cleanup()
            except (OSError,sqlite3.Error,ValueError):pass
            time.sleep(86400)
    threading.Thread(target=work,daemon=True,name='META-source-cache-cleanup').start()
