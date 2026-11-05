"""CLI bridge for supervised Python profiles inside a frozen Desktop executable."""
import os,runpy,sys

def restore_stdio():
    for name,number in (('stdout',1),('stderr',2)):
        if getattr(sys,name) is not None:continue
        try:stream=os.fdopen(os.dup(number),'w',encoding='utf-8',buffering=1)
        except OSError:
            if os.name!='nt':stream=open(os.devnull,'w')
            else:
                import ctypes,msvcrt
                from ctypes import wintypes as w
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                kernel.GetStdHandle.argtypes=[w.DWORD];kernel.GetStdHandle.restype=w.HANDLE
                kernel.GetCurrentProcess.restype=w.HANDLE
                kernel.DuplicateHandle.argtypes=[w.HANDLE,w.HANDLE,w.HANDLE,ctypes.POINTER(w.HANDLE),w.DWORD,w.BOOL,w.DWORD]
                handle=kernel.GetStdHandle(-11 if number==1 else -12);duplicate=w.HANDLE();current=kernel.GetCurrentProcess()
                if not handle or not kernel.DuplicateHandle(current,handle,current,ctypes.byref(duplicate),0,False,2):stream=open(os.devnull,'w')
                else:stream=os.fdopen(msvcrt.open_osfhandle(duplicate.value,os.O_WRONLY),'w',encoding='utf-8',buffering=1)
        setattr(sys,name,stream)

def argv(*arguments,executable=None):
    target=executable or sys.executable
    frozen=getattr(sys,'frozen',False) and os.path.normcase(os.path.abspath(target))==os.path.normcase(os.path.abspath(sys.executable))
    return [target,*(['--meta5-python'] if frozen else []),*arguments]

def dispatch(arguments):
    restore_stdio()
    args=list(arguments)
    while args and args[0] in ('-I','-B','-u'):
        flag=args.pop(0)
        if flag=='-B':sys.dont_write_bytecode=True
        if flag=='-u':
            for stream in (sys.stdout,sys.stderr):
                if hasattr(stream,'reconfigure'):stream.reconfigure(write_through=True)
    if len(args)<2 or args[0] not in ('-c','-m'):raise ValueError('Unsupported internal Python profile')
    mode,value,*rest=args
    sys.argv=[value if mode=='-m' else '-c',*rest]
    if mode=='-c':exec(compile(value,'<META supervised profile>','exec'),{'__name__':'__main__','__package__':None})
    else:runpy.run_module(value,run_name='__main__',alter_sys=True)
    return 0
