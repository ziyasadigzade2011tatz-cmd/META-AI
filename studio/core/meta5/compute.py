"""One local model operation across META processes in the current Windows session."""
import hashlib,os,threading,time
from pathlib import Path

class ComputeGate:
    def __init__(self):
        self.fallback=threading.Semaphore(1)
        self.handle=None
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes
            self.ctypes=ctypes;self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            self.kernel.CreateMutexW.argtypes=(ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR);self.kernel.CreateMutexW.restype=wintypes.HANDLE
            self.kernel.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD);self.kernel.WaitForSingleObject.restype=wintypes.DWORD
            self.kernel.ReleaseMutex.argtypes=(wintypes.HANDLE,);self.kernel.ReleaseMutex.restype=wintypes.BOOL
            name='Local\\META-Compute-'+hashlib.sha256(str(Path.home()).casefold().encode()).hexdigest()[:20]
            self.handle=self.kernel.CreateMutexW(None,False,name)
            if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
    def acquire(self,blocking=True,timeout=None):
        started=time.monotonic()
        if not self.fallback.acquire(blocking,timeout):return False
        if self.handle:
            remaining=None if timeout is None else max(0,timeout-(time.monotonic()-started))
            milliseconds=0 if not blocking else 0xffffffff if remaining is None else max(0,min(0xfffffffe,int(remaining*1000)))
            result=self.kernel.WaitForSingleObject(self.handle,milliseconds)
            if result in (0,0x80):return True
            self.fallback.release()
            if result==0x102:return False
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        return True
    def release(self):
        if self.handle:
            if not self.kernel.ReleaseMutex(self.handle):raise self.ctypes.WinError(self.ctypes.get_last_error())
        self.fallback.release()
