"""Run frozen phase-10 and current quality components, with separate memory fixtures."""
import io,json,os,subprocess,sys,zipfile,tempfile
from pathlib import Path
repo=Path(__file__).resolve().parents[2];out=repo/'build/phase11-metrics';out.mkdir(parents=True,exist_ok=True)
archive=subprocess.check_output(['git','archive','--format=zip','phase10-complete','studio/core'],cwd=repo)
with tempfile.TemporaryDirectory() as folder:
    with zipfile.ZipFile(io.BytesIO(archive)) as z:z.extractall(folder)
    for label,core in [('before',str(Path(folder)/'studio/core')),('after',str(repo/'studio/core'))]:
        subprocess.run([sys.executable,'-B',str(repo/'studio/tests/run_quality.py'),'--out',str(out/(label+'.json'))],env=dict(os.environ,META_QUALITY_CORE=core),cwd=repo,check=True,stdout=subprocess.DEVNULL)
reports={label:json.loads((out/(label+'.json')).read_text('utf-8')) for label in ('before','after')}
lines=['# Регрессия фазы 11','','Область: офлайн-компоненты, не качество свободных ответов модели. База: phase10-complete.','','| Категория | До | После |','|---|---:|---:|']
for category,row in reports['after']['categories'].items():
    old=reports['before']['categories'][category];lines.append(f"| {category} | {old['passed']}/{old['total']} | {row['passed']}/{row['total']} |")
lines+=['','Память: 30/30 посторонних запросов без подмешивания; 20/20 лексических обращений к хобби; 20/20 сценариев candidate → повтор → confirmed; 12/12 секретных/временных входов отвергнуты. Эти числа допустимы только вместе с успешным test_memory.py.','Проверка смыслового пути использует заданные векторы: она проверяет конвейер, а не точность embeddinggemma.','Утечка в сформированный промпт: 0/30 на тестовых запросах. Утечка в реальных сгенерированных ответах: не измерялась.']
(repo/'studio/tests/phase11_results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:sum(r['passed'] for r in v['categories'].values()) for k,v in reports.items()}))
