
// META40_UI_BEGIN
(() => {
  const nav = document.querySelector('.nav-primary');
  if (!nav) return;
  const button = document.createElement('button');
  button.className = 'nav-link'; button.textContent = '✦ Агент 4.0'; nav.append(button);
  const panel = document.createElement('div'); panel.className = 'overlay'; panel.hidden = true;
  panel.innerHTML = `<section role="dialog" aria-modal="true" aria-label="Агент META 4.0" style="width:min(1100px,95vw);max-height:92vh;overflow:auto;background:var(--bg,#18181c);border:1px solid #555;border-radius:16px;padding:24px">
  <header style="display:flex;justify-content:space-between"><div><small>META CODE · LOCAL</small><h2>Агент 4.0</h2></div><button id="m40close" class="outline-btn">Закрыть</button></header>
  <p>Изучает проект → предлагает код → проверяет → готовит заявку. Файлы меняются после твоего подтверждения.</p>
  <div style="display:flex;gap:12px;flex-wrap:wrap"><label>Проект внутри D:\\META\\Projects<input id="m40project" class="setting-input" value="." placeholder="имя-проекта"></label>
  <label>Модель Ollama<select id="m40model" class="setting-select"><option>qwen2.5-coder:14b</option></select></label>
  <label>Шагов<input id="m40steps" type="number" min="1" max="30" value="16" class="setting-input"></label></div>
  <label style="display:block;margin-top:12px"><input type="checkbox" id="m40create" checked> Создать папку проекта, если её нет</label>
  <p class="fineprint">Укажи имя папки, например my_app. Она будет создана внутри Projects при запуске задачи. Точка (.) выбирает всю папку Projects.</p>
  <textarea id="m40task" class="setting-textarea" style="width:100%;min-height:100px;margin:16px 0" maxlength="12000" placeholder="Например: прочитай проект, исправь ошибку и добавь unittest. Подготовь общую заявку."></textarea>
  <label style="display:block"><input type="checkbox" id="m40tests"> Разрешить Python unittest для этой задачи</label>
  <p class="fineprint">Тесты запускаются в временной копии, с правами твоего пользователя. Это не защитная песочница: код может обращаться к другим файлам и сети. Включай только для доверенного проекта. Лимит запуска — 30 секунд.</p>
  <div style="display:flex;gap:12px;margin:16px 0"><button id="m40run" class="action-primary">Запустить задачу</button><button id="m40stop" class="danger-btn" disabled>Остановить</button><button id="m40history" class="outline-btn">История</button></div>
  <strong id="m40status" role="status">Готов к работе</strong><div id="m40historylist"></div><pre id="m40log" style="white-space:pre-wrap;max-height:220px;overflow:auto;font-size:12px"></pre>
  <div id="m40result"></div><pre id="m40diff" style="white-space:pre-wrap;max-height:360px;overflow:auto;font-size:12px"></pre><div id="m40approval"></div></section>`;
  document.body.append(panel);
  const el = id => document.getElementById('m40'+id);
  let job = null, polling = false, busy40 = false, proposal = null;
  const states = {queued:'В очереди',running:'Работает',pending:'Ожидает подтверждения',completed:'Завершено',failed:'Ошибка',cancelled:'Остановлено',interrupted:'Прервано перезапуском',step_limit:'Лимит шагов',time_limit:'Лимит времени'};
  async function call(path, method='GET', data) {
    const r = await fetch('/api/meta40'+path, {method,headers:{'Content-Type':'application/json'},body:data === undefined ? undefined : JSON.stringify(data)});
    const result = await r.json(); if(!r.ok) throw Error(typeof result.error === 'string' ? result.error : JSON.stringify(result.error)); return result;
  }
  function error(e){el('status').textContent=e.message;}
  function controls(){el('run').disabled=busy40;el('stop').disabled=!busy40;}
  async function refresh(){
    if (!job || polling) return; polling=true;
    try {
      const d=await call('/tasks/'+job);
      busy40=['running','queued','cancelling'].includes(d.status); controls();
      el('status').textContent=states[d.status]||d.status;
      el('log').textContent=(d.events||[]).map(e=>new Date(e.at*1000).toLocaleTimeString()+' · '+e.type+' · '+JSON.stringify(e.data)).join('\n');
      el('result').textContent=d.error||d.result?.summary||'';
      if(d.result?.tests?.length){
        const t=d.result.tests.at(-1);el('result').textContent+='\nПоследний запуск тестов: '+t.status+(t.superseded_by_edits?' (после него код изменён)':'');
      }
      const pid=d.result?.proposal?.id;
      if(pid && proposal!==pid){proposal=pid;await preview(pid);}
    } catch(e){error(e);} finally{polling=false;}
  }
  async function preview(pid){
    const r=await fetch('/api/proposals/'+pid);const d=await r.json();if(!r.ok)throw Error(d.error||'Заявка недоступна');
    el('diff').textContent=d.diff;el('approval').replaceChildren();
    for(const [action,label] of [['apply','Применить показанные изменения'],['reject','Отклонить']]){
      const b=document.createElement('button');b.className='outline-btn';b.textContent=label;
      b.onclick=async()=>{if(!confirm(action==='apply'?'Применить все файлы из показанной заявки?':'Отклонить заявку?'))return;
        b.disabled=true;try{const r=await fetch('/api/proposals/'+pid+'/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const d=await r.json();if(!r.ok)throw Error(d.error);el('status').textContent=d.status==='applied'?'Изменения применены':'Заявка отклонена';el('approval').replaceChildren();}catch(e){b.disabled=false;error(e);}};
      el('approval').append(b);
    }
  }
  button.onclick=async()=>{panel.hidden=false;try{
    const s=await call('/status');if(s.active){job=s.active;await refresh();}
    const d=await call('/models');const previous=el('model').value;el('model').replaceChildren();
    for(const name of d.models){const option=document.createElement('option');option.textContent=name;option.value=name;el('model').append(option);}
    if(d.models.includes(previous))el('model').value=previous;
  }catch(e){error(e);}};
  el('close').onclick=()=>{panel.hidden=true;};
  panel.onclick=e=>{if(e.target===panel)panel.hidden=true;};
  el('run').onclick=async()=>{busy40=true;controls();try{
    const enabled=el('tests').checked;
    if(enabled&&!confirm('Разрешить выполнение Python-кода этого проекта с правами твоего пользователя?')){busy40=false;controls();return;}
    const d=await call('/tasks','POST',{project:el('project').value.trim(),create_project:el('create').checked,task:el('task').value,model:el('model').value,max_steps:Number(el('steps').value),allow_tests:enabled,test_consent:enabled?'EXECUTE_PROJECT_PYTHON':''});
    job=d.id;localStorage.setItem('meta40-last-task',job);proposal=null;el('diff').textContent='';el('approval').replaceChildren();await refresh();
  }catch(e){busy40=false;controls();error(e);}};
  el('stop').onclick=async()=>{try{await call('/tasks/'+job+'/cancel','POST',{});el('status').textContent='Остановка… текущий запрос модели может занять до 60 секунд';}catch(e){error(e);}};
  el('history').onclick=async()=>{try{const d=await call('/tasks');el('historylist').replaceChildren();for(const t of d.tasks){const b=document.createElement('button');b.className='outline-btn';b.textContent=(states[t.status]||t.status)+' · '+t.task.slice(0,80);b.onclick=()=>{job=t.id;proposal=null;el('diff').textContent='';el('approval').replaceChildren();refresh();};el('historylist').append(b);}}catch(e){error(e);}};
  job=localStorage.getItem('meta40-last-task');
  setInterval(()=>{if(!panel.hidden)refresh();},1500);
})();
// META40_UI_END
