// Real synthetic-profile Desktop UI request, not a mocked model response.
const fs=require('fs'),path=require('path');
const {chromium}=require('D:/META/Tools/node_modules/playwright');
const repo=path.resolve(__dirname,'../..'),base=path.join(repo,'build/budget-step1');
const thinking=!process.argv.includes('--chat');
(async()=>{
 const f=JSON.parse(fs.readFileSync(path.join(base,'fixture.json'),'utf8'));
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{
  const ctx=await browser.newContext({viewport:{width:1440,height:1000}});await ctx.addCookies(f.test_cookie);
  const roles=await ctx.request.post(f.url+'/studio/role-models',{headers:{Origin:f.url},data:{fast:'qwen3.5:4b',thinking:'qwen3.5:9b',code:'qwen3.5:9b',understand:'qwen3.5:4b',thinking_enabled:thinking}});
  if(!roles.ok())throw Error('Synthetic thinking configuration failed');
  const page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
   const original=window.fetch;
   window.fetch=async(...args)=>{
    const response=await original(...args);
    if(String(args[0]).endsWith('/api/message/stream'))response.clone().text().then(raw=>{window.__budgetEvents=raw.split('\n').filter(x=>x.startsWith('data:')).map(x=>JSON.parse(x.slice(5)))}).catch(e=>{window.__budgetError=e.message});
    return response;
   };
  });
  await page.goto(f.url);await page.locator('#modelSelect option[value="qwen3.5:9b"]').waitFor({state:'attached'});
  await page.locator('#newChat:not([disabled])').click();await page.locator('#chatInput').fill('привет');
  await page.locator('#sendChat').click();
  await page.waitForFunction(()=>window.__budgetEvents||window.__budgetError,{},{timeout:240000});
  const events=await page.evaluate(()=>window.__budgetEvents);if(!events)throw Error('SSE observer failed');
  await page.locator('#sendChat:not([disabled])').waitFor({timeout:240000});
  const text=await page.locator('.message.assistant').last().innerText();
  const usage=events.find(e=>e.type==='context_usage')?.data,metrics=events.find(e=>e.type==='metrics')?.data,model=events.find(e=>e.type==='model_selected')?.data;
  if(!text.trim()||errors.length||!usage||usage.output_limit!==(thinking?3500:2000)||usage.input_limit!==(thinking?4000:5500)||usage.mode!==(thinking?'thinking':'chat')||model.model!==(thinking?'qwen3.5:9b':'qwen3.5:4b')||metrics.prompt_eval_count!==usage.input_tokens)throw Error('UI/budget verification failed');
  const result={synthetic_profile_only:true,answer_visible:true,answer_characters:text.length,page_errors:errors,usage,metrics,model};
  fs.writeFileSync(path.join(repo,'build/context-budget-step1/'+(thinking?'ui':'ui-chat')+'.json'),JSON.stringify(result,null,2));
  await page.screenshot({path:path.join(repo,'build/context-budget-step1/ui.png')});console.log(JSON.stringify(result));
 }finally{await browser.close()}
})().catch(e=>{console.error(e.message);process.exit(1)});
