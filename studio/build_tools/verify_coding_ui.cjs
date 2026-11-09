const fs=require('fs'),path=require('path'),{pathToFileURL}=require('url');
const {chromium}=require('C:/Users/user/Documents/GitHub/META-AI/local/tools/node_modules/playwright');
const repo=path.resolve(__dirname,'../..'),folder=path.join(repo,'build/code-upgrade');
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(path.join(repo,'build/code-upgrade-ui/fixture.json'),'utf8'));
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{
  const ctx=await browser.newContext({viewport:{width:1440,height:1000}});await ctx.addCookies(fixture.test_cookie);
  const page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(fixture.url);await page.waitForSelector('#chatInput');await page.locator('[data-nav="code"]').click();
  await page.locator('#codeImageFile').setInputFiles(path.join(folder,'vision-card.png'));await page.waitForFunction(()=>document.querySelector('#codeImageLabel').textContent.includes('vision-card'));
  let sent=null;
  await page.route('**/studio/task',async route=>{if(route.request().method()!=='POST')return route.continue();sent=route.request().postDataJSON();await route.fulfill({json:{id:'synthetic-ui-task',project:'synthetic-ui-project'}});});
  await page.route('**/studio/task?id=synthetic-ui-task',route=>route.fulfill({json:{id:'synthetic-ui-task',project:'synthetic-ui-project',task:'Synthetic image task',model:'fixture',status:'paused',summary:'UI request checked',events:[],edits:{},diffs:[]}}));
  await page.locator('#taskInput').fill('Создай страницу по скриншоту');await page.locator('#codeForm').evaluate(f=>f.requestSubmit());
  await page.waitForFunction(()=>document.querySelector('#taskFeed').textContent.includes('UI request checked'));
  if(!sent?.image?.startsWith('data:image/png;base64,'))throw Error('Image was not sent to coding route');
  await page.screenshot({path:path.join(folder,'candidate-code-ui.png')});
  const result=JSON.parse(fs.readFileSync(path.join(folder,'agent-result.json'),'utf8')),session=JSON.parse(fs.readFileSync(path.join(folder,'sessions',result.task_id+'.json'),'utf8'));
  const site=await ctx.newPage();site.on('pageerror',e=>errors.push(e.message));await site.goto(pathToFileURL(path.join(session.root,'index.html')).href);
  await site.locator('#taskInput').fill('Контрольная заметка');await site.getByRole('button',{name:'Добавить',exact:true}).click();
  if(await site.locator('#taskList li').count()!==1)throw Error('Add failed');
  await site.getByRole('button',{name:'Удалить',exact:true}).click();if(await site.locator('#taskList li').count()!==0)throw Error('Delete failed');
  await site.screenshot({path:path.join(folder,'generated-page.png')});
  await page.locator('[data-nav="chat"]').click();
  await page.locator('#chatFiles').setInputFiles(path.join(folder,'vision-card.png'));
  await page.waitForFunction(()=>document.querySelector('#queuedFiles').textContent.includes('Изображение'));
  await page.locator('#chatInput').fill('Прочитай надпись на изображении.');await page.locator('#chatForm').evaluate(f=>f.requestSubmit());
  await page.waitForFunction(()=>[...document.querySelectorAll('.message.assistant')].some(m=>m.textContent.includes('42')),null,{timeout:120000});
  if(errors.length)throw Error(errors.join('\n'));
  const report={coding_image_upload:true,post_contains_image:true,chat_photo_read_42:true,generated_page_add_delete:true,page_errors:errors,scope:'Isolated Desktop UI + real chat vision + browser interaction with a real model-generated page; no working profile changes'};
  fs.writeFileSync(path.join(folder,'ui-result.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e.stack);process.exit(1);});
