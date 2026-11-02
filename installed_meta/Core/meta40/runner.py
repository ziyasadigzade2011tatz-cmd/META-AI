"""Opt-in Python unittest runner. A disposable copy is NOT a security sandbox."""
import ctypes
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# The model selects a profile, never a command, executable, argument, or shell.
BOOT = """import sys, unittest
sys.path.insert(0, sys.argv[1])
suite = unittest.defaultTestLoader.discover(sys.argv[1], pattern='test*.py')
count = suite.countTestCases()
print('META_TEST_COUNT=' + str(count), flush=True)
if not count: sys.exit(5)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
"""


class WindowsJob:
    """Kill all children on close; fail closed if assignment is unavailable."""
    def __init__(self,max_processes=8,memory_mb=512,total_memory_mb=2048):
        self.handle = None
        if os.name != 'nt':
            return
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', w.DWORD), ('min_ws', ctypes.c_size_t),
                        ('max_ws', ctypes.c_size_t), ('active', w.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ('ro','wo','oo','rb','wb','ob')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                        ('peak_job', ctypes.c_size_t)]
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        k.CreateJobObjectW.restype = w.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.CloseHandle.argtypes = [w.HANDLE]
        self.k = k
        self.handle = k.CreateJobObjectW(None, None)
        limits = Extended()
        limits.basic.flags = 0x2000 | 0x100 | 0x8 | 0x200
        limits.basic.active = max(1,min(24,int(max_processes)))
        limits.process_memory = max(64,min(1024,int(memory_mb))) * 1024 * 1024
        limits.job_memory = max(256,min(4096,int(total_memory_mb))) * 1024 * 1024
        if not self.handle or not k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError('Cannot create restricted test process job')

    def assign(self, process):
        if self.handle and not self.k.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise OSError('Cannot supervise test process tree')

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


def run_tests(snapshot, edits, enabled, cancel, timeout=30, profile='python-unittest'):
    if not enabled:
        raise PermissionError('Tests require explicit opt-in for this task')
    if profile != 'python-unittest':
        raise ValueError('Only python-unittest is allowed')
    from .workspace import Workspace
    with tempfile.TemporaryDirectory(prefix='meta40-test-') as temp:
        root = Path(temp)/'project'
        root.mkdir()
        ws = Workspace(root)
        for name, raw in {**snapshot, **{k:v.encode('utf-8') for k,v in edits.items()}}.items():
            p = ws.path(name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
        job = WindowsJob()
        process = None
        output = bytearray()
        clipped = threading.Event()
        try:
            # Gate prevents user code running before the process joins the Job Object.
            gate = Path(temp)/'go'
            bootstrap = "import os,time,sys;\nwhile not os.path.exists(sys.argv[2]): time.sleep(.01)\n" + BOOT
            env = {k:v for k,v in os.environ.items() if k.upper() in
                   {'SYSTEMROOT','WINDIR','TEMP','TMP','PATH','COMSPEC'}}
            process = subprocess.Popen([sys.executable, '-I', '-c', bootstrap, str(root), str(gate)],
                cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, shell=False,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                start_new_session=(os.name != 'nt'))
            job.assign(process)
            gate.touch()
            def drain():
                while True:
                    block = process.stdout.read(1024)
                    if not block:
                        return
                    space = 32000-len(output)
                    output.extend(block[:max(0, space)])
                    if len(block) > space:
                        clipped.set()
            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            start = time.monotonic()
            reason = None
            while process.poll() is None:
                if cancel.is_set() or time.monotonic()-start > timeout or clipped.is_set():
                    reason = 'cancelled' if cancel.is_set() else ('output_limit' if clipped.is_set() else 'timeout')
                    break
                time.sleep(.03)
            if reason:
                process.kill()
            job.close()
            if os.name != 'nt':
                import signal
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            process.wait(timeout=5)
            reader.join(timeout=3)
            return {'profile':profile, 'exit_code':process.returncode,
                    'status':reason or ('passed' if process.returncode == 0 else 'failed'),
                    'output':output.decode('utf-8', errors='replace'), 'disposable_copy':True}
        finally:
            job.close()
            if process:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                if process.stdout:
                    process.stdout.close()
