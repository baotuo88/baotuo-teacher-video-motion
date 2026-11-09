// Read-only authenticated UI / artifact inspection. Requires scripts/dev.py running.
const fs=require('node:fs'),path=require('node:path');
const env=Object.fromEntries(fs.readFileSync('.env','utf8').split('\n').filter(l=>l.includes('=')&&!l.startsWith('#')).map(l=>{const i=l.indexOf('=');return[l.slice(0,i),l.slice(i+1)]}));
const rid=JSON.parse(fs.readFileSync('.data/runtimes/active.json')).runtime_id;
const {chromium}=require(path.join(process.cwd(),'.data/runtimes',rid,'skill/node_modules/playwright-core'));
(async()=>{const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'/usr/bin/chromium'),headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(process.env.BASE_URL||'http://127.0.0.1:'+(env.PORT||8000));await page.locator('#password').fill(process.env.ADMIN_PASSWORD||env.ADMIN_PASSWORD);await page.getByRole('button',{name:'进入工作台 →'}).click();await page.locator('#app').waitFor({state:'visible'});
fs.mkdirSync('.data/e2e',{recursive:true});
await page.locator('[data-nav=system]').click();
await page.getByRole('heading',{name:'基础环境已就绪'}).waitFor();
for (const width of [1440, 768, 390]) {
 await page.setViewportSize({width,height:1000});
 await page.screenshot({path:'.data/e2e/system-'+width+'.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('System page overflow '+width);
}
await page.getByRole('button',{name:'重新检查',exact:true}).click();
await page.getByRole('heading',{name:'基础环境已就绪'}).waitFor();
if(errors.length)throw Error(errors.join(';'));
console.log(JSON.stringify({errors,systemReady:true,widths:[1440,768,390],overflow:false}));
await browser.close();})().catch(e=>{console.error(e);process.exit(1)});
