// Read-only authenticated UI / artifact inspection. Requires scripts/dev.py running.
const fs=require('node:fs'),path=require('node:path');
const env=Object.fromEntries(fs.readFileSync('.env','utf8').split('\n').filter(l=>l.includes('=')&&!l.startsWith('#')).map(l=>{const i=l.indexOf('=');return[l.slice(0,i),l.slice(i+1)]}));
const rid=JSON.parse(fs.readFileSync('.data/runtimes/active.json')).runtime_id;
const {chromium}=require(path.join(process.cwd(),'.data/runtimes',rid,'skill/node_modules/playwright-core'));
(async()=>{const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'/usr/bin/chromium'),headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(process.env.BASE_URL||'http://127.0.0.1:'+(env.PORT||8000));await page.locator('#password').fill(process.env.ADMIN_PASSWORD||env.ADMIN_PASSWORD);await page.getByRole('button',{name:'进入工作台 →'}).click();await page.locator('#app').waitFor({state:'visible'});
fs.mkdirSync('.data/e2e',{recursive:true});
for(const name of ['projects','assets','providers','runtimes','jobs']){await page.locator('[data-nav='+name+']').click();await page.waitForTimeout(350);await page.screenshot({path:'.data/e2e/'+name+'-final.png'});}
const result=await page.evaluate(async()=>{const jobs=await fetch('/api/jobs').then(r=>r.json());const j=jobs.find(j=>j.status==='succeeded'&&j.kind==='render');if(!j)return {artifact:'no finished job'};const a=j.result.artifacts.find(a=>a.kind==='video');const r=await fetch('/api/jobs/'+j.id+'/artifacts/'+encodeURIComponent(a.name),{headers:{Range:'bytes=0-1023'}});return{job:j.id,rangeStatus:r.status,contentType:r.headers.get('content-type'),bytes:(await r.arrayBuffer()).byteLength};});
await page.setViewportSize({width:390,height:844});await page.locator('[data-nav=projects]').click();await page.waitForTimeout(250);await page.screenshot({path:'.data/e2e/mobile.png',fullPage:true});const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
console.log(JSON.stringify({errors,overflow,...result}));if(errors.length||overflow||result.rangeStatus!==206)throw Error('UI/artifact checks failed');await browser.close();})().catch(e=>{console.error(e);process.exit(1)});
