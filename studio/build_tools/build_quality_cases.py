"""Build a reproducible component-level corpus. No live user chats are used."""
import json
from pathlib import Path
TOPICS=['общение','интернет','компьютеры','программирование','музыка','спорт','учёба','работа','еда','транспорт','покупки','быт','путешествия','одежда','книги','кино','природа','творчество','отношения','игры']
rows=[]
def add(category,text,**expected):
    i=len(rows);rows.append({'id':i+1,'category':category,'topic':TOPICS[i%20],'messages':[{'role':'user','content':text}],**expected})
for a,b in [('хз','не знаю'),('имхо','по моему мнению'),('ща','сейчас'),('чо','что'),('норм','нормально'),('спс','спасибо'),('пжл','пожалуйста'),('ваще','вообще'),('щас','сейчас'),('ок','хорошо'),('сорян','извини'),('прив','привет'),('лол','смех'),('рофл','шутка'),('кринж','неловкость'),('респект','уважение'),('пофиг','безразлично'),('плиз','пожалуйста'),('пасиб','спасибо'),('оке','хорошо')]:add('slang',a,contains=b)
for word in ['бля','блять','ебать','нахуй','похуй','ёпт','заебись','блин']:add('rough',word,original_preserved=True,not_moralizing=True)
for a,b in [('тюея','тебя'),('мнэ','мне'),('ваще','вообще'),('чё','что'),('сяс','сейчас'),('здрв','здравствуй'),('пнтн','понятно'),('привeт','привет'),('пoгода','погода'),('прeдмет','предмет'),('сeгодня','сегодня'),('oчень','очень'),('дeла','дела'),('спасибo','спасибо')]:add('typo',a,contains=b)
for a,b in [('ghbdtn','привет'),('rfr','как'),('gjrf','пока'),('privet','привет'),('spasibo','спасибо'),('kak','как'),('gde','где'),('tebya','тебя'),('mne','мне'),('poka','пока')]:add('layout',a,contains=b)
for a,b in [('оооочень','очень'),('прииивет','привет'),('спасииибо','спасибо'),('даааа','да'),('неееет','нет'),('хооорошо','хорошо'),('какдела','как дела'),('гдеты','где ты')]:add('stretch',a,contains=b)
for index in range(14):
    entity=TOPICS[len(rows)%20]
    add('reference','А это?',entity=entity)
    rows[-1]['messages']=[{'role':'user','content':'Обсуждаем «'+entity+'»'},{'role':'assistant','content':'Продолжим.'},{'role':'user','content':'А это?'}]
for word in ['кк','лук','пара','бит','кк','лук','пара','бит']:add('ambiguous',word,clarify=True)
for index in range(12):add('learning','шурум',mode=['explicit','promote','contradiction','private','one_chat','expire'][index%6])
for index in range(16):
    b=TOPICS[len(rows)%20];a=TOPICS[(len(rows)+7)%20]
    add('anti_bias','Расскажи про '+b,unrelated_fact='Предпочитаю '+a+'. Объясняй подробно.',forbidden_topic=a)
for text in ['Привет','Спасибо за ответ','Сколько стоит билет?','Где лежит книга?','Не меняй файл Python','Хочу узнать время','Погода сегодня','У меня новая лампа','Расскажи коротко','🙂 Всё хорошо']:
    add('clean',text,exact=text)
assert len(rows)==120
assert max(sum(r['topic']==t for r in rows) for t in TOPICS)/len(rows)<=.08
target=Path(__file__).resolve().parents[1]/'tests/quality_cases.json'
target.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('quality_dialogues',len(rows))
if __name__=='__main__':pass
