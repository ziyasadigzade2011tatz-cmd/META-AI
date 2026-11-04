const fs=require('fs'),path=require('path');
(async()=>{
const [library,edge,url,out]=process.argv.slice(2);
const {chromium}=require(library);
console.log('META_BROWSER_START');
const browser=await chromium.launch({executablePath:edge,headless:true,args:['--disable-gpu','--renderer-process-limit=2']});
console.log('META_BROWSER_LAUNCHED');
try{const page=await browser.newPage({viewport:{width:1365,height:900}});const errors=[];
page.on('pageerror',e=>errors.push(String(e.message).slice(0,800)));
page.on('console',m=>{if(m.type()==='error')errors.push(m.text().slice(0,800));});
const response=await page.goto(url,{waitUntil:'networkidle',timeout:20000});
console.log('META_BROWSER_NAVIGATED');
await page.screenshot({path:path.join(out,'screenshot.png'),fullPage:true,timeout:10000});
fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify({url,title:await page.title(),status:response?.status(),errors:errors.slice(0,30),text:(await page.locator('body').innerText()).slice(0,6000)}));
console.log('META_BROWSER_SAVED');
}finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exit(1)});
