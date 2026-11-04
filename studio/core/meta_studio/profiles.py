"""Serialize profile-index updates across desktop processes."""
import json
from pathlib import Path
import time
import uuid
from contextlib import contextmanager
from meta5.storage import atomic_json,read_json

@contextmanager
def index_lock(folder):
    import msvcrt
    path=Path(folder)/'profiles.lock'
    with path.open('a+b') as stream:
        stream.seek(0,2)
        if stream.tell()==0:stream.write(b'1');stream.flush()
        deadline=time.monotonic()+10
        while True:
            try:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1);break
            except OSError:
                if time.monotonic()>deadline:raise ValueError('Другой профиль обновляет список. Повтори попытку.')
                time.sleep(.05)
        try:yield
        finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

def add_profile(folder,name):
    path=Path(folder)/'profiles.json'
    with index_lock(folder):
        rows=read_json(path,[{'id':'default','name':'Основной профиль'}]);ident=uuid.uuid4().hex
        rows.append({'id':ident,'name':name});atomic_json(path,rows)
    return rows,ident
