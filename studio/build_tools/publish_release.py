"""Publish an explicitly authorized release using existing Git credentials, never logging them."""
import argparse,hashlib,json,os,shutil,subprocess
from pathlib import Path

repo=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser();parser.add_argument('--tag',required=True);parser.add_argument('--asset',required=True);parser.add_argument('--notes',required=True);args=parser.parse_args()
asset=(repo/args.asset).resolve();notes=(repo/args.notes).resolve()
if not asset.is_file() or not notes.is_file():raise SystemExit('Existing asset and release notes required')
gh=shutil.which('gh') or str(repo/'build/tools/gh.exe')
env=dict(os.environ,GIT_TERMINAL_PROMPT='0')
credentials=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',capture_output=True,text=True,timeout=40,env=env)
if credentials.returncode:raise SystemExit('GitHub login must be completed by the user')
fields=dict(line.split('=',1) for line in credentials.stdout.splitlines() if '=' in line)
if not fields.get('password'):raise SystemExit('GitHub credential missing')
env['GH_TOKEN']=fields['password'];del fields,credentials
target='ziyasadigzade2011tatz-cmd/META-AI'
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
tag=subprocess.run(['git','rev-parse',args.tag+'^{commit}'],cwd=repo,text=True,capture_output=True)
if tag.returncode:subprocess.run(['git','tag','-a',args.tag,'-m','META Studio '+args.tag],cwd=repo,check=True)
elif tag.stdout.strip()!=head:raise SystemExit('Tag points to a different commit; refusing overwrite')
subprocess.run(['git','push','origin','main',args.tag],cwd=repo,env=env,check=True)
exists=subprocess.run([gh,'release','view',args.tag,'--repo',target,'--json','url'],env=env,capture_output=True)
if exists.returncode==0:raise SystemExit('Release already exists; refusing to replace public assets automatically')
subprocess.run([gh,'release','create',args.tag,str(asset),'--repo',target,'--verify-tag','--latest','--title','META Studio '+args.tag.lstrip('v'),'--notes-file',str(notes)],env=env,check=True)
release=json.loads(subprocess.check_output([gh,'api','repos/'+target+'/releases/tags/'+args.tag],env=env))
digest='sha256:'+hashlib.sha256(asset.read_bytes()).hexdigest()
assets=[a for a in release['assets'] if a['name']==asset.name]
if len(assets)!=1 or assets[0]['size']!=asset.stat().st_size or assets[0].get('digest') not in (None,digest):raise SystemExit('Published asset verification failed')
report={'url':release['html_url'],'commit':head,'asset':assets[0]['browser_download_url'],'bytes':assets[0]['size'],'local_digest':digest,'github_digest':assets[0].get('digest')}
folder=repo/'build/final-audit';folder.mkdir(parents=True,exist_ok=True);(folder/'published.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(report))
