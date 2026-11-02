import sqlite3,time,json
from contextlib import closing
from .storage import STATE

def cache(query,sources=None):
    folder=STATE/'knowledge';folder.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(folder/'sources.sqlite')) as db,db:
        db.execute('PRAGMA max_page_count='+str(20_000_000_000//db.execute('pragma page_size').fetchone()[0]))
        db.execute('create table if not exists knowledge(q text primary key,at real,data text)')
        key=query.casefold().strip()
        if sources is None:
            row=db.execute('select data from knowledge where q=?',(key,)).fetchone()
            return json.loads(row[0]) if row else []
        db.execute('insert or replace into knowledge values(?,?,?)',(key,time.time(),json.dumps(sources,ensure_ascii=False)))
