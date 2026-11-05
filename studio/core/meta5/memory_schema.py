"""Additive migration, protected by a separate cross-process lock and SQLite backup."""
import hashlib,sqlite3
from pathlib import Path
from contextlib import closing
from .compute import ComputeGate

COLUMNS={'category':"TEXT DEFAULT 'general'",'source':"TEXT DEFAULT 'legacy'",'confidence':'REAL DEFAULT 1',
         'status':"TEXT DEFAULT 'confirmed'",'last_used':'REAL','use_count':'INTEGER DEFAULT 0','expires':'REAL','slot':"TEXT DEFAULT ''",'supersedes':'TEXT'}

def migrate(path):
    path=Path(path).resolve();path.parent.mkdir(parents=True,exist_ok=True)
    gate=ComputeGate('memory-schema-'+hashlib.sha256(str(path.resolve()).encode()).hexdigest())
    if not gate.acquire(timeout=15):raise TimeoutError('Миграция памяти уже выполняется')
    try:
        existed=path.exists();backup=path.with_name(path.name+'.pre11')
        if existed:
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as source:
                columns={r[1] for r in source.execute('PRAGMA table_info(facts)')}
                tables={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if set(COLUMNS)<=columns and {'embeddings','embedding_cache','memory_history','schema_metadata'}<=tables:
                    return {'backup':str(backup) if backup.exists() else None,'version':11}
                needed=not set(COLUMNS)<=columns
                if needed and not backup.exists():
                    with closing(sqlite3.connect(backup)) as dest:source.backup(dest)
                if needed:
                    with closing(sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True)) as check:
                        if check.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Копия .pre11 не прошла проверку')
        with closing(sqlite3.connect(path,timeout=15)) as c,c:
            c.execute('CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY,kind TEXT,value TEXT UNIQUE,created REAL)')
            c.execute('CREATE TABLE IF NOT EXISTS summaries(session TEXT PRIMARY KEY,value TEXT,updated REAL)')
            c.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)')
            columns={r[1] for r in c.execute('PRAGMA table_info(facts)')}
            for name,definition in COLUMNS.items():
                if name not in columns:c.execute('ALTER TABLE facts ADD COLUMN '+name+' '+definition)
            c.execute('CREATE TABLE IF NOT EXISTS memory_history(id TEXT PRIMARY KEY,fact_id TEXT,old_value TEXT,new_value TEXT,at REAL,reason TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS embeddings(owner_type TEXT,owner_id TEXT,model TEXT,version TEXT,dimensions INTEGER,vector BLOB,text_hash TEXT,updated REAL,PRIMARY KEY(owner_type,owner_id,model,version))')
            c.execute('CREATE TABLE IF NOT EXISTS embedding_cache(key TEXT PRIMARY KEY,model TEXT,version TEXT,dimensions INTEGER,vector BLOB,updated REAL)')
            c.execute('CREATE TABLE IF NOT EXISTS schema_metadata(key TEXT PRIMARY KEY,value TEXT)')
            c.execute("INSERT OR REPLACE INTO schema_metadata VALUES('memory_version','11')")
        return {'backup':str(backup) if backup.exists() else None,'version':11}
    finally:gate.release()
