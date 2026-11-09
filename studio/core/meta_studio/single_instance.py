"""One Windows desktop process per data directory; repeated launch activates it."""
import atexit
import hashlib
import os
import threading

_handles=[]

def acquire(data_directory):
    if os.name!='nt':return True
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.CreateEventW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateEventW.restype=wintypes.HANDLE
    for name in ('SetEvent','CloseHandle'):
        getattr(kernel,name).argtypes=[wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    key=hashlib.sha256(os.path.normcase(os.path.realpath(data_directory)).encode()).hexdigest()[:24]
    mutex=kernel.CreateMutexW(None,False,'Local\\META.Desktop.'+key)
    if not mutex:raise ctypes.WinError(ctypes.get_last_error())
    exists=ctypes.get_last_error()==183
    event=kernel.CreateEventW(None,False,False,'Local\\META.Activate.'+key)
    if not event:
        kernel.CloseHandle(mutex);raise ctypes.WinError(ctypes.get_last_error())
    if exists:
        kernel.SetEvent(event);kernel.CloseHandle(event);kernel.CloseHandle(mutex);return False
    _handles.extend((mutex,event))
    atexit.register(lambda:[kernel.CloseHandle(h) for h in (event,mutex)])
    def listen():
        user=ctypes.WinDLL('user32',use_last_error=True)
        callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        user.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
        user.SetForegroundWindow.argtypes=[wintypes.HWND]
        user.GetWindowTextLengthW.argtypes=[wintypes.HWND]
        @callback
        def activate(hwnd,_):
            pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value==os.getpid() and user.GetWindowTextLengthW(hwnd)>0:
                user.ShowWindow(hwnd,9);user.SetForegroundWindow(hwnd)
            return True
        while kernel.WaitForSingleObject(event,0xffffffff)==0:
            user.EnumWindows(activate,0)
    threading.Thread(target=listen,daemon=True,name='META-activate').start()
    return True
