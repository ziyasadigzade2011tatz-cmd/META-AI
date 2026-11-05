const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const runs={chat:{visible:true,open:true,events:[],status:'idle'},code:{visible:true,open:true,events:[],status:'idle'}};
const terminal=new Set(['completed','cancelled','failed','review','paused','interrupted','idle']);
export function describe(e){const d=e.data||{},type=e.type;
 if(type==='file')return 'Подготовлен файл: '+(d.path||'');
 if(type==='action')return (({read:'Читаю',write:'Готовлю',edit:'Исправляю',check:'Проверяю',search:'Ищу в проекте',plan:'Составляю план',finish:'Завершаю',web_search:'Ищу в интернете'})[d.action]||d.action||'Действие')+' '+(d.path||'');
 if(type==='check')return 'Проверка: '+(d.checks||[]).filter(c=>c.status==='passed').length+' успешно, '+(d.checks||[]).filter(c=>c.status==='failed').length+' ошибок';
 if(type==='plan')return 'План: '+(d.steps||[]).map(s=>typeof s==='string'?s:s.text).join(' → ');
 if(type==='model'||type==='model_selected')return 'Модель: '+(d.model||'');
 if(type==='search_started')return 'Ищу: '+(d.query||'');
 if(type==='page_opened')return 'Прочитан источник: '+(d.url||'');
 if(type==='research_done')return 'Источников прочитано: '+(d.sources||0);
 return d.message||d.error||({context:'Контекст запроса разобран',context_usage:'Контекст подготовлен',image_analyzed:'Изображение прочитано локально',recovery:'Повторяю действие автоматически',test_started:'Запускаю проверку',test_result:'Проверка завершена'})[type]||null;
}
export function begin(kind){runs[kind]={...runs[kind],visible:true,status:'running',events:[],started:Date.now(),progress:null,session:null};}
export function record(kind,event){const run=runs[kind];if(event.data?.session_id)run.session=event.data.session_id;
 if(event.type==='token')return;
 if(event.type==='done'){run.status=event.data?.cancelled?'cancelled':'completed';return;}
 if(['error','model_error'].includes(event.type))run.status='failed';
 if(describe(event)){run.events.push(event);run.events=run.events.slice(-100);}
}
export function markup(kind){const run=runs[kind],id='activity-'+kind;
 if(!run.visible)return `<div id="${id}"><button type="button" data-activity="${kind}" data-operation="show">Показать действия</button></div>`;
 const active=!terminal.has(run.status),p=run.progress||{},last=run.events.at(-1),stage=p.message||describe(last||{})||(active?'Подготавливаю запрос':'Действия завершены');
 const elapsed=run.started?Math.max(0,Math.round((Date.now()-run.started)/1000)):0;
 return `<section id="${id}" class="activity-panel" aria-label="Действия ${kind==='chat'?'чата':'META Code'}"><div class="activity-bar"><button type="button" data-activity="${kind}" data-operation="toggle" aria-expanded="${run.open}">${run.open?'▾':'▸'} Действия <small>${active?'В работе':({failed:'Ошибка',cancelled:'Остановлено',review:'Готово к применению',paused:'Нужно уточнение',interrupted:'Прервано'})[run.status]||'Завершено'}</small></button>${active?`<button type="button" data-activity="${kind}" data-operation="stop">Стоп</button>`:''}<button type="button" data-activity="${kind}" data-operation="hide" aria-label="Закрыть панель действий">×</button></div><div class="activity-stage" role="status">${esc(stage)}${active?` <small>· ${elapsed} с${p.characters?' · '+Number(p.characters)+' символов':''}</small>`:''}</div>${run.open?`<div class="activity-body">${run.events.slice(-35).map(e=>`<div class="activity-entry ${e.type==='warning'?'warning':''}">${esc(describe(e)||'')}</div>`).join('')}${p.code_preview?`<div class="draft-label">Потоковый черновик ${esc(p.path||'')} · ещё не записан</div><pre class="activity-code">${esc(p.code_preview)}</pre>`:''}</div>`:''}</section>`;
}
export function refresh(kind){const el=document.getElementById('activity-'+kind);if(el)el.outerHTML=markup(kind);}
export function wire(onStop){document.addEventListener('click',async e=>{const b=e.target.closest('[data-activity]');if(!b)return;const kind=b.dataset.activity,run=runs[kind],op=b.dataset.operation;
 if(op==='stop'){b.disabled=true;try{await onStop(kind);}catch(error){run.events.push({type:'warning',data:{message:error.message}});}finally{refresh(kind);}return;}
 if(op==='toggle')run.open=!run.open;if(op==='hide')run.visible=false;if(op==='show')run.visible=true;refresh(kind);
});}
