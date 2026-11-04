import sqlite3,time,json
from contextlib import closing
from .storage import STATE

def cache(query,sources=None,*,max_age=86400):
    folder=STATE/'knowledge';folder.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(folder/'sources.sqlite')) as db,db:
        db.execute('PRAGMA max_page_count='+str(20_000_000_000//db.execute('pragma page_size').fetchone()[0]))
        db.execute('create table if not exists knowledge(q text primary key,at real,data text)')
        key=query.casefold().strip()
        if sources is None:
            row=db.execute('select data,at from knowledge where q=?',(key,)).fetchone()
            if not row or time.time()-row[1]>max_age:return []
            result=json.loads(row[0])
            return [{**source,'retrieved_at':row[1],'cached':True} for source in result]
        db.execute('insert or replace into knowledge values(?,?,?)',(key,time.time(),json.dumps(sources,ensure_ascii=False)))
