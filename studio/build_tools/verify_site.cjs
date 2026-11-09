const fs=require('fs'),path=require('path'),http=require('http');
const {chromium}=require('C:/Users/user/Documents/GitHub/META-AI/local/tools/node_modules/playwright');
const repo=path.resolve(__dirname,'../..'),base=path.join(repo,'build','verification');
(async()=>{
 const result=JSON.parse(fs.readFileSync(path.join(base,'real-agent-result.json'),'utf8'));if(!result.passed)throw Error('Agent did not finish');
 const root=path.join(base,'projects',result.project),errors=[];
 const server=http.createServer((req,res)=>{const file=path.resolve(root,'.'+decodeURIComponent(req.url==='/'?'/index.html':req.url.split('?')[0]));if(!file.startsWith(root+path.sep)){res.writeHead(403);res.end();return;}try{res.setHeader('Content-Type',({'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript'})[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));}catch{res.writeHead(404);res.end();}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1360,height:900}});page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:'+server.address().port);await page.waitForSelector('#theme-toggle');
 const before=await page.locator('body').getAttribute('data-theme');await page.locator('#theme-toggle').click();const after=await page.locator('body').getAttribute('data-theme');if(before===after)throw Error('Theme toggle broken');
 await page.setViewportSize({width:390,height:844});await page.waitForTimeout(300);const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);if(overflow)throw Error('Mobile horizontal overflow');if(errors.length)throw Error(errors.join('\n'));
 fs.writeFileSync(path.join(base,'site-browser-result.json'),JSON.stringify({passed:true,theme_toggle:true,mobile_horizontal_overflow:false,page_errors:errors},null,2));
 await browser.close();await new Promise(resolve=>server.close(resolve));process.stdout.write('Generated website browser test passed\n');
})().catch(e=>{process.stderr.write(e.stack+'\n');process.exit(1);});
