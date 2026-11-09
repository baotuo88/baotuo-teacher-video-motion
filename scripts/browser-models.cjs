// UI acceptance with intercepted model-list/config responses. No real API key/cost.
const fs=require('node:fs'),path=require('node:path');
const env=Object.fromEntries(fs.readFileSync('.env','utf8').split('\n').filter(l=>l.includes('=')&&!l.startsWith('#')).map(l=>{const i=l.indexOf('=');return[l.slice(0,i),l.slice(i+1)]}));
const rid=JSON.parse(fs.readFileSync('.data/runtimes/active.json')).runtime_id;
const {chromium}=require(path.join(process.cwd(),'.data/runtimes',rid,'skill/node_modules/playwright-core'));
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'/usr/bin/chromium'),headless:true});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.env.BASE_URL||'http://127.0.0.1:'+(env.PORT||8000));await page.locator('#password').fill(process.env.ADMIN_PASSWORD||env.ADMIN_PASSWORD);await page.getByRole('button',{name:'进入工作台 →'}).click();await page.locator('#app').waitFor({state:'visible'});
 const saved={id:'a'.repeat(32),name:'已保存的演示服务',base_url:'https://mock.example/v1',model:'original-model',has_key:true,enabled:true};
 let mode='success',lastBody=null,savedBody=null;
 await page.route('**/api/providers',async route=>{
   if(route.request().method()==='GET')return route.fulfill({json:[saved]});
   savedBody=route.request().postDataJSON();return route.fulfill({json:{...saved,...savedBody,api_key:undefined}});
 });
 await page.route('**/api/providers/models/discover',async route=>{
   lastBody=route.request().postDataJSON();
   if(mode==='failure')return route.fulfill({status:400,json:{detail:'认证失败（HTTP 401），请检查 API Key'}});
   if(mode==='delay')await new Promise(r=>setTimeout(r,500));
   return route.fulfill({json:{models:[{id:'alpha-chat'},{id:'beta-chat'},{id:'image-only-not-chat'}],skipped:0,warning:'列表不保证能力'}});
 });
 await page.locator('[data-nav=providers]').click();
 await page.getByLabel('配置名称',{exact:true}).fill('自动发现演示');await page.getByLabel('Base URL',{exact:false}).fill('https://mock.example/v1');await page.getByLabel('API Key',{exact:false}).fill('not-a-real-api-key');
 await page.getByRole('button',{name:'获取模型列表',exact:true}).click();await page.getByText('已获取 3 个模型。',{exact:false}).waitFor();
 await page.getByRole('searchbox',{name:'搜索模型列表'}).fill('beta');await page.getByRole('button',{name:'beta-chat',exact:true}).click();
 if(await page.getByLabel('模型 ID',{exact:false}).inputValue()!=='beta-chat')throw Error('Selection failed');
 fs.mkdirSync('.data/e2e',{recursive:true});await page.screenshot({path:'.data/e2e/models-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'.data/e2e/models-mobile.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
 mode='failure';await page.getByRole('button',{name:'重新获取模型',exact:true}).click();await page.getByText('认证失败（HTTP 401）',{exact:false}).waitFor();
 await page.getByLabel('模型 ID',{exact:false}).fill('manual-after-failure');await page.getByRole('button',{name:'保存服务配置',exact:true}).click();await page.getByText('服务配置已保存',{exact:false}).waitFor();
 if(savedBody.model!=='manual-after-failure')throw Error('Manual fallback not saved');
 await page.getByRole('button',{name:'编辑 / 获取模型',exact:true}).click();mode='success';await page.getByRole('button',{name:'获取模型列表',exact:true}).click();await page.getByText('已获取 3 个模型。',{exact:false}).waitFor();
 if(lastBody.api_key!==null||lastBody.provider_id!==saved.id)throw Error('Stored key not referenced safely');
 if(await page.getByLabel('模型 ID',{exact:false}).inputValue()!=='original-model')throw Error('Fetched list overwrote current model');
 mode='delay';await page.getByRole('button',{name:'重新获取模型',exact:true}).click();await page.getByLabel('Base URL',{exact:false}).fill('https://changed.example/v1');await page.waitForTimeout(700);
 if(await page.locator('.model-picker').isVisible())throw Error('Stale response displayed after endpoint changed');
 if(errors.length)throw Error(errors.join(';'));
 console.log(JSON.stringify({errors,modelSelection:true,manualFallback:true,storedKeyReference:true,staleResponseIgnored:true,mobileOverflow:false,mocked:true}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
