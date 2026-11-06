"""Synthetic real Ollama counts; no Desktop chats/memory/settings are touched."""
import json,sys,time
from pathlib import Path
repo=Path(__file__).resolve().parents[2];sys.path.insert(0,str(repo/'studio/core'))
from meta5 import transport
from meta5.qwen_tokens import counter
from meta5.token_budget import prepare
from meta5.context import compact

out=repo/'build/context-budget-step1';out.mkdir(parents=True,exist_ok=True)
rows=[]
samples=[
 ('greeting','Hello.'),('geography','Какая столица Исландии?'),('books','Кратко о библиотечном каталоге.'),
 ('garden','Как поливать рассаду?'),('code','const n = 2;\nconsole.log(n ** 3);'),
 ('music',"We'll discuss tempo, not pitch."),('transport','Трамвай № 17 — маршрут.'),
 ('math','17 × 23 = ? 123456789'),('language','e\u0301 café 中文 العربية'),('photo','ISO 100, f/2.8, 1/250 s'),
 ('cooking','Хлеб: вода, мука, соль.'),('craft','  Стежок\tпетля\n\n'),('astronomy','Как наблюдать Луну?'),
 ('theatre','Расскажи о сценическом свете.'),('architecture','Фасад и внутренний двор.'),('weather','Облака 🙂\r\n  ветер 🌦️')]

def run(model,messages,thinking=False,limit=1,label=''):
    predicted=counter(model,thinking)(messages);start=time.monotonic()
    result=transport.complete(model,messages,think=thinking,timeout=240,options={'num_ctx':8192,'num_predict':limit,'temperature':0})
    row={'case':label,'model':model,'think':thinking,'predicted_input':predicted,'prompt_eval_count':result['prompt_eval_count'],
         'eval_count':result.get('eval_count'),'done_reason':result.get('done_reason'),'seconds':round(time.monotonic()-start,3)}
    rows.append(row);(out/'counts.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(row),flush=True)
    if predicted!=row['prompt_eval_count']:raise AssertionError('Tokenizer mismatch: '+label)
    return row

for topic,text in samples:
    run('qwen3.5:4b',[{'role':'system','content':'You are META. Answer briefly.'},{'role':'user','content':text}],label=topic)

messages=[{'role':'system','content':'Ты META. Ответь только на последний вопрос.'}]
for i in range(6):
    text=' '.join(s[1] for s in samples)*6
    messages.append({'role':'user' if i%2==0 else 'assistant','content':text})
messages.append({'role':'user','content':'Сколько будет два плюс два? Ответь только числом.'})
# Match the prior character/messaging filter, then compare the exact same input.
before,_=compact(messages,22000)
run('qwen3.5:4b',before,limit=2000,label='before_character_budget')
after,usage=prepare(before,'qwen3.5:4b',8192)
row=run('qwen3.5:4b',after,limit=usage['output_limit'],label='after_chat_budget')
assert row['prompt_eval_count']<=5500
thinking,think_usage=prepare(before,'qwen3.5:9b',8192,True)
# One output token only validates framing/count, not thinking answer quality.
row=run('qwen3.5:9b',thinking,thinking=True,label='thinking_framing_only')
assert row['prompt_eval_count']<=4000
(out/'usage.json').write_text(json.dumps({'chat':usage,'thinking':think_usage},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('All real prompt counts match; answer-quality/15-step tests belong to later steps.',flush=True)
