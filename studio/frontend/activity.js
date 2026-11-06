const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const runs={chat:{visible:true,open:true,events:[],status:'idle'},code:{visible:true,open:true,events:[],status:'idle'}};
const terminal=new Set(['completed','cancelled','failed','review','paused','interrupted','idle']);
const active=run=>!terminal.has(run.status);
export function describe(e){const d=e.data||{},type=e.type;
 if(type==='status'&&d.step)return (d.message||'Действие')+' '+d.step+' / '+d.max_steps;
 if(type==='file')return (d.incomplete?'Сохранена порция: ':'Подготовлен файл: ')+(d.path||'');
 if(type==='action')return (({read:'Читаю',write:'Готовлю',append:'Продолжаю файл',edit:'Исправляю',check:'Проверяю',search:'Ищу в проекте',plan:'Составляю план',finish:'Завершаю',web_search:'Ищу в интернете',language_help:'Читаю локальную справку'})[d.action]||d.action||'Действие')+' '+(d.path||'');
 if(type==='check')return 'Проверка: '+(d.checks||[]).filter(c=>c.status==='passed').length+' успешно, '+(d.checks||[]).filter(c=>c.status==='failed').length+' ошибок';
 if(type==='plan')return 'План: '+(d.steps||[]).map(s=>typeof s==='string'?s:s.text).join(' → ');
 if(type==='model'||type==='model_selected')return 'Модель: '+(d.model||'');
 if(type==='search_started')return 'Ищу: '+(d.query||'');
 if(type==='page_opened')return 'Прочитан источник: '+(d.url||'');
 if(type==='research_done')return 'Источников прочитано: '+(d.sources||0);
 return d.message||d.error||({context:'Контекст запроса разобран',context_usage:'Контекст подготовлен',image_analyzed:'Изображение прочитано локально',recovery:'Продолжаю автоматически',test_started:'Запускаю проверку',test_result:'Проверка завершена'})[type]||null;
}
export function begin(kind){runs[kind]={...runs[kind],visible:true,status:'running',events:[],started:Date.now(),progress:null,session:null,lastContact:Date.now(),pollError:null,stopping:false,loadedTask:null};}
export function record(kind,event){const run=runs[kind];run.lastContact=Date.now();if(event.data?.session_id)run.session=event.data.session_id;
 if(event.type==='token')return;
 if(event.type==='done'){run.status=event.data?.cancelled?'cancelled':'completed';return;}
 if(['error','model_error'].includes(event.type))run.status='failed';
 if(describe(event)){run.events.push(event);run.events=run.events.slice(-100);}
}
function clock(run){if(!active(run))return '';
 const elapsed=run.started?Math.max(0,Math.floor((Date.now()-run.started)/1000)):0;
 const stale=run.pollError||(run.lastContact&&Date.now()-run.lastContact>10000);
 return '· '+elapsed+' с'+(run.progress?.characters?' · '+Number(run.progress.characters)+' символов в текущей порции':'')+(stale?' · нет связи с Core, переподключаюсь':'');
}
function status(run){return active(run)?(run.stopping?'Останавливаю':'В работе'):({failed:'Ошибка',cancelled:'Остановлено',review:'Готово к применению',paused:'Нужно уточнение',interrupted:'Прервано',idle:'Готово'})[run.status]||'Завершено';}
function stage(run){return run.pollError||run.progress?.message||describe(run.events.at(-1)||{})||(active(run)?'Подготавливаю запрос':'Действия завершены');}
function events(run){return run.events.slice(-35).map(e=>`<div class="activity-entry ${e.type==='warning'?'warning':''}">${esc(describe(e)||'')}</div>`).join('');}
export function markup(kind){const run=runs[kind],id='activity-'+kind,p=run.progress||{};
 if(!run.visible)return `<div id="${id}"><button type="button" data-activity="${kind}" data-operation="show">Показать действия</button></div>`;
 return `<section id="${id}" class="activity-panel" aria-label="Действия ${kind==='chat'?'чата':'META Code'}"><div class="activity-bar"><button type="button" data-activity="${kind}" data-operation="toggle" aria-expanded="${run.open}"><span data-toggle-label>${run.open?'▾':'▸'} Действия</span> <small data-run-status>${status(run)}</small></button><button type="button" data-activity="${kind}" data-operation="stop" ${active(run)?'':'hidden'} ${run.stopping?'disabled':''}>Стоп</button><button type="button" data-activity="${kind}" data-operation="hide" aria-label="Закрыть панель действий">×</button></div><div class="activity-stage" role="status"><span data-stage-text>${esc(stage(run))}</span> <small data-activity-clock aria-live="off">${esc(clock(run))}</small></div><div class="activity-body" ${run.open?'':'hidden'}><div class="activity-events">${events(run)}</div><div class="draft-label" ${p.code_preview?'':'hidden'}>Потоковый черновик ${esc(p.path||'')} · ещё не применён</div><pre class="activity-code" ${p.code_preview?'':'hidden'}>${esc(p.code_preview||'')}</pre></div></section>`;
}
function text(el,value){if(el&&el.textContent!==value)el.textContent=value;}
function keepScroll(el,fn){const top=el.scrollTop,left=el.scrollLeft,follow=el.scrollHeight-el.clientHeight-top<24;fn();el.scrollTop=follow?el.scrollHeight:top;el.scrollLeft=left;}
export function refresh(kind){const run=runs[kind],el=document.getElementById('activity-'+kind);if(!el)return;
 if(!run.visible||!el.classList.contains('activity-panel')){const t=document.createElement('template');t.innerHTML=markup(kind);el.replaceWith(t.content.firstElementChild);return;}
 const body=el.querySelector('.activity-body'),pre=el.querySelector('.activity-code'),p=run.progress||{};
 text(el.querySelector('[data-toggle-label]'),(run.open?'▾':'▸')+' Действия');el.querySelector('[data-operation="toggle"]').setAttribute('aria-expanded',String(run.open));
 text(el.querySelector('[data-run-status]'),status(run));const stop=el.querySelector('[data-operation="stop"]');stop.hidden=!active(run);stop.disabled=!!run.stopping;
 text(el.querySelector('[data-stage-text]'),stage(run));text(el.querySelector('[data-activity-clock]'),clock(run));
 if(!run.open){if(!body.hidden)run.savedScroll={body:body.scrollTop,code:pre.scrollTop,left:pre.scrollLeft};body.hidden=true;return;}
 if(body.hidden){body.hidden=false;if(run.savedScroll){body.scrollTop=run.savedScroll.body;pre.scrollTop=run.savedScroll.code;pre.scrollLeft=run.savedScroll.left;}}
 keepScroll(body,()=>{
  const log=el.querySelector('.activity-events'),html=events(run);if(log._activityHTML!==html){log.innerHTML=html;log._activityHTML=html;}
  const label=el.querySelector('.draft-label');label.hidden=!p.code_preview;text(label,'Потоковый черновик '+(p.path||'')+' · ещё не применён');
  const selection=document.getSelection(),selected=selection&&!selection.isCollapsed&&selection.containsNode(pre,true);
  if(!selected){pre.hidden=!p.code_preview;const next=p.code_preview||'';if(pre.textContent!==next)keepScroll(pre,()=>{if(next.startsWith(pre.textContent)&&pre.firstChild?.nodeType===Node.TEXT_NODE)pre.firstChild.appendData(next.slice(pre.textContent.length));else pre.textContent=next;});}
 });
}
export function wire(onStop){
 setInterval(()=>{for(const kind of ['chat','code']){const el=document.querySelector('#activity-'+kind+' [data-activity-clock]');text(el,clock(runs[kind]));}},1000);
 document.addEventListener('click',async e=>{const b=e.target.closest('[data-activity]');if(!b)return;const kind=b.dataset.activity,run=runs[kind],op=b.dataset.operation;
  if(op==='stop'){run.stopping=true;refresh(kind);try{await onStop(kind);}catch(error){run.stopping=false;run.events.push({type:'warning',data:{message:error.message}});}finally{refresh(kind);}return;}
  if(op==='toggle')run.open=!run.open;if(op==='hide')run.visible=false;if(op==='show')run.visible=true;refresh(kind);
 });
}
