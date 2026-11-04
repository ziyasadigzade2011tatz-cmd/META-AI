import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

def child(project):
    stream=open(os.environ['META_TEST_OUTPUT'],'w',encoding='utf-8',buffering=1)
    sys.stdout=stream;sys.stderr=stream
    gate=Path(os.environ['META_TEST_GATE']);deadline=time.monotonic()+15
    while not gate.exists():
        if time.monotonic()>deadline:return 4
        time.sleep(.02)
    import unittest
    root=Path(project).resolve();os.chdir(root);sys.path.insert(0,str(root))
    start=root/'tests' if (root/'tests').is_dir() else root
    suite=unittest.TestLoader().discover(str(start),pattern='test*.py')
    if suite.countTestCases()==0:
        print('Python unittest: tests not found.');return 3
    result=unittest.TextTestRunner(verbosity=2,stream=stream).run(suite)
    return 0 if result.wasSuccessful() else 1

def execute(argv,root):
    from meta40.runner import WindowsJob
    with tempfile.TemporaryDirectory(prefix='meta-studio-check-') as temp:
        gate=Path(temp)/'start';test_output=Path(temp)/'output.txt';env=dict(os.environ,META_TEST_GATE=str(gate),META_TEST_OUTPUT=str(test_output))
        process=subprocess.Popen(argv,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        job=WindowsJob(max_processes=12,memory_mb=768,total_memory_mb=1536);output=bytearray();limited=threading.Event()
        try:
            job.assign(process)
            def drain():
                for block in iter(lambda:process.stdout.read(4096),b''):
                    remaining=64000-len(output)
                    output.extend(block[:max(0,remaining)])
                    if len(block)>remaining:limited.set();job.close();return
            thread=threading.Thread(target=drain,daemon=True);thread.start();gate.touch()
            timeout=False
            deadline=time.monotonic()+120
            while process.poll() is None:
                if test_output.exists() and test_output.stat().st_size>64000:limited.set();job.close();break
                if time.monotonic()>deadline:timeout=True;job.close();break
                time.sleep(.05)
            process.wait(timeout=5)
            thread.join(timeout=5)
            if test_output.exists():
                with test_output.open('rb') as result_file:output.extend(result_file.read(max(0,64000-len(output))))
            return {'status':'timeout' if timeout else 'output_limit' if limited.is_set() else 'passed' if process.returncode==0 else 'no_tests' if process.returncode==3 else 'failed',
                    'exit_code':process.returncode,'output':output.decode('utf-8','replace'),'isolation':'native_user_permissions'}
        finally:
            job.close()
            if process.poll() is None:process.kill();process.wait(timeout=5)
            process.stdout.close()

def run_tests(root,profile,allow):
    if not allow:raise ValueError('Нужно явно разрешить выполнение тестов проекта')
    if profile=='python-unittest':return execute([sys.executable,'--studio-unittest',str(root)],root)
    if profile=='javascript-syntax':
        node=shutil.which('node')
        if not node and Path(r'D:\META\Tools\node.exe').is_file():node=r'D:\META\Tools\node.exe'
        if not node:return {'status':'not_available','output':'Node.js не установлен. Проверка JavaScript не запускалась.'}
        from meta5.project import Project
        files=[f['path'] for f in Project(root).files() if f['path'].endswith(('.js','.cjs','.mjs'))]
        if not files:return {'status':'no_tests','output':'JavaScript-файлов не найдено.'}
        results=[execute([node,'--check',str(Project(root).path(name))],root) for name in files[:30]]
        return {'status':'passed' if all(r['status']=='passed' for r in results) else 'failed',
                'output':'\n'.join(name+': '+result['status']+'\n'+result['output'] for name,result in zip(files,results)),
                'scope':'JavaScript syntax only; no browser/runtime tests'}
    raise ValueError('Разрешены только python-unittest и javascript-syntax')
