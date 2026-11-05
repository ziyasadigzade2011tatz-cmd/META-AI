const fs=require('fs'),path=require('path'),http=require('http');
const {chromium}=require('D:/META/Tools/node_modules/playwright');
const repo=path.resolve(__dirname,'../..'),folder=path.join(repo,'build/activity-ui');
(async()=>{
 const f=JSON.parse(fs.readFileSync(path.join(folder,'fixture.json'),'utf8'));
 let chatClosed=false,chatCancel=false,codeCancelled=false;
 const stream=http.createServer((req,res)=>{res.writeHead(200,{'Content-Type':'text/event-stream','Access-Control-Allow-Origin':'*'});res.write('data: '+JSON.stringify({type:'status',data:{message:'Читаю источники',session_id:'fixture-session'}})+'\n\n');
  const timer=setInterval(()=>res.write('data: '+JSON.stringify({type:'token',content:'Текст '})+'\n\n'),400);req.on('close',()=>{clearInterval(timer);chatClosed=true;});});
 await new Promise(r=>stream.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{
 const ctx=await browser.newContext({viewport:{width:1440,height:1000}});await ctx.addCookies(f.test_cookie);const p=await ctx.newPage(),errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.route('**/api/message/stream',r=>r.continue({url:'http://127.0.0.1:'+stream.address().port+'/stream'}));
 await p.route('**/studio/cancel-chat',r=>{chatCancel=true;return r.fulfill({json:{cancelled:true}});});
 await p.route('**/studio/task',r=>r.request().method()==='POST'?r.fulfill({json:{id:'fixture-task',project:'fixture-project'}}):r.continue());
 await p.route('**/studio/task?id=fixture-task',r=>r.fulfill({json:{id:'fixture-task',project:'fixture-project',task:'Проверка интерфейса',model:'fixture',status:codeCancelled?'cancelled':'running',summary:codeCancelled?'Остановлено':'',created:Date.now()/1000-8,events:[{type:'plan',data:{steps:['Создать файлы','Проверить']}},{type:'file',data:{path:'index.html',content:'<h1>Meta</h1>'}}],progress:{message:'Готовлю style.css',path:'style.css',characters:230,code_preview:'body { background: beige; }'},edits:{},diffs:[]}}));
 await p.route('**/studio/cancel',r=>{codeCancelled=true;return r.fulfill({json:{ok:true}});});
 await p.goto(f.url);await p.locator('#chatInput').fill('Расскажи интересный факт');await p.locator('#sendChat').click();
 await p.locator('#activity-chat').getByText('Читаю источники',{exact:true}).waitFor();
 await p.locator('[data-activity="chat"][data-operation="toggle"]').click();if(await p.locator('#activity-chat .activity-body').count())throw Error('Chat collapse failed');
 await p.locator('[data-activity="chat"][data-operation="hide"]').click();await p.locator('[data-activity="chat"][data-operation="show"]').click();
 await p.locator('[data-activity="chat"][data-operation="stop"]').click();await p.waitForFunction(()=>!document.querySelector('#sendChat').disabled);
 if(!chatCancel)throw Error('Chat cancellation endpoint not called');
 await p.locator('[data-nav="code"]').click();await p.locator('#taskInput').fill('Создай сайт');await p.locator('#codeForm').evaluate(e=>e.requestSubmit());
 await p.locator('#activity-code .activity-code').waitFor();await p.screenshot({path:path.join(folder,'code-activity.png')});
 await p.locator('[data-activity="code"][data-operation="toggle"]').click();await p.waitForTimeout(1800);if(await p.locator('#activity-code .activity-body').count())throw Error('Code collapse did not survive polling');
 if((await p.locator('#taskFeed').innerText()).includes('Продолжить задачу'))throw Error('Old continue prompt present');
 await p.locator('[data-nav="chat"]').click();await p.locator('#activity-code').waitFor();await p.locator('[data-activity="code"][data-operation="stop"]').click();
 await p.waitForFunction(()=>document.querySelector('#activity-code').textContent.includes('Остановлено'));
 await p.screenshot({path:path.join(folder,'chat-activity.png')});
 if(!codeCancelled||!chatClosed||errors.length)throw Error(JSON.stringify({codeCancelled,chatClosed,errors}));
 const result={chat_activity:true,chat_collapse_hide_reopen:true,chat_stop_aborts_stream:true,code_stream_preview:true,code_collapse_survives_poll:true,code_visible_in_chat:true,code_stop:true,page_errors:errors};fs.writeFileSync(path.join(folder,'ui-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();await new Promise(r=>stream.close(r));}
})().catch(e=>{console.error(e.stack);process.exit(1);});
