"""One local model operation across META processes in the current Windows session."""
import hashlib,os,threading,time
from pathlib import Path

class ComputeGate:
    def __init__(self,name=None,folder=None):
        self.fallback=threading.Semaphore(1);self.file=None
        base=Path(folder or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'META Compute')
        name=name or 'model-'+hashlib.sha256(str(Path.home()).casefold().encode()).hexdigest()[:20]
        self.path=base/(hashlib.sha256(name.encode()).hexdigest()+'.lock')
    def acquire(self,blocking=True,timeout=None):
        started=time.monotonic()
        if not self.fallback.acquire(blocking,timeout):return False
        if os.name!='nt':return True
        import msvcrt
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            file=self.path.open('a+b');file.seek(0,2)
            if file.tell()==0:file.write(b'0');file.flush()
            while True:
                try:
                    file.seek(0);msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
                    self.file=file;return True
                except OSError:
                    if not blocking or (timeout is not None and time.monotonic()-started>=timeout):
                        file.close();self.fallback.release();return False
                    time.sleep(.05)
        except BaseException:
            self.fallback.release();raise
    def release(self):
        try:
            if self.file is not None:
                import msvcrt
                file=self.file;self.file=None
                try:file.seek(0);msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
                finally:file.close()
        finally:self.fallback.release()
