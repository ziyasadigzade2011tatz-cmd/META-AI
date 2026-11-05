"""Run the changed Core and Desktop bridge against isolated synthetic data."""
import argparse,json,os,shutil,subprocess,sys,urllib.request
from pathlib import Path

parser=argparse.ArgumentParser();parser.add_argument('step');args=parser.parse_args()
repo=Path(__file__).resolve().parents[2];os.chdir(repo)
runtime=repo/'build/META-Next'
if not (runtime/'META-Next.exe').exists():raise SystemExit('Build a verification runtime first')
shutil.copytree(repo/'studio/core',runtime/'_internal/core',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
name='phase10-step'+args.step
try:
 subprocess.run([sys.executable,'-B','studio/build_tools/start_verification.py','--name',name],check=True)
 fixture=json.loads((repo/'build'/name/'fixture.json').read_text('utf-8'))
 health=json.load(urllib.request.urlopen(fixture['core_url']+'/health',timeout=10))
 subprocess.run([r'D:\META\Tools\node.exe','studio/build_tools/verify_chat.cjs'],check=True,env=dict(os.environ,META_VERIFY_DIR=name))
 report={'step':args.step,'health':health,'chat':json.loads((repo/'build'/name/'chat-result.json').read_text('utf-8')),'desktop':'isolated native runtime HTTP bridge; working shortcut not automated'}
 (repo/'build'/name/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False))
finally:
 pid=repo/'build'/name/'pid.txt'
 if pid.exists():subprocess.run(['taskkill','/PID',pid.read_text().strip(),'/T','/F'],capture_output=True)
