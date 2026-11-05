"""Explicit offline SQLite backup-API restoration; never runs automatically."""
import argparse,sqlite3
from contextlib import closing
from pathlib import Path

def restore(path):
    path=Path(path).resolve();copy=path.with_name(path.name+'.pre11')
    if not path.is_file() or not copy.is_file():raise ValueError('Both existing database and adjacent .pre11 are required')
    with closing(sqlite3.connect(copy.as_uri()+'?mode=ro',uri=True)) as source:
        if source.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Invalid .pre11 database')
        with closing(sqlite3.connect(path,timeout=1)) as target:source.backup(target)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Close every META process first. Later memory changes will be lost; original chat DB is not touched.')
    parser.add_argument('database');parser.add_argument('--confirm-loss-of-later-memory',action='store_true');args=parser.parse_args()
    if not args.confirm_loss_of_later_memory:parser.error('Explicit --confirm-loss-of-later-memory is required')
    restore(args.database);print('SQLite database restored from adjacent .pre11')
