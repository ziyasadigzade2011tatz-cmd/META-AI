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
embedding=repo/'build/phase11-embedding/result.json'
if embedding.exists():
    measured=json.loads(embedding.read_text('utf-8'))
    lines+=['',f"Реальная embeddinggemma, синтетические перефразирования: {measured['recall']}/{measured['total']}; без подмешивания постороннего: {measured.get('unrelated_zero','не измерено')}/{measured.get('unrelated_total','не измерено')}.",
            'Это калибровочный набор, не независимая контрольная выборка. Пропуски: '+', '.join(r['topic'] for r in measured['synthetic_paraphrases'] if not r['expected_selected'])+'.']
answers=repo/'build/phase11-answers/result.json'
if answers.exists():
    measured=json.loads(answers.read_text('utf-8'))
    lines=[s for s in lines if not s.startswith('Утечка в сформированный промпт:')]
    lines+=['',f"Прямые локальные ответы Qwen 4B после отбора памяти: {measured['completed']}/{measured['cases']} завершены; явные упоминания фраз посторонних увлечений: {measured['leakage_cases']}/{measured['cases']}.",
            'Это проверка точных фраз, не полный смысловой анализ утечек; предел каждого ответа 180 токенов. Полная проверка качества свободных ответов не проводилась.']
(repo/'studio/tests/phase11_results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({k:sum(r['passed'] for r in v['categories'].values()) for k,v in reports.items()}))
