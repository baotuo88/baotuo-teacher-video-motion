// Explicit smoke test: creates a real project and queues a silent render.
const fs=require('node:fs'),path=require('node:path');
const root=process.cwd();const rid=JSON.parse(fs.readFileSync(path.join(root,'.data/runtimes/active.json'))).runtime_id;
const {chromium}=require(path.join(root,'.data/runtimes',rid,'skill/node_modules/playwright-core'));
const env=Object.fromEntries(fs.readFileSync('.env','utf8').split('\n').filter(l=>l.includes('=')&&!l.startsWith('#')).map(l=>{const i=l.indexOf('=');return[l.slice(0,i),l.slice(i+1)]}));
const base=process.env.BASE_URL||'http://127.0.0.1:'+(env.PORT||8000);
fs.mkdirSync('.data/e2e',{recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'/usr/bin/chromium'),headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);await page.locator('#password').fill(process.env.ADMIN_PASSWORD||env.ADMIN_PASSWORD);await page.getByRole('button',{name:'进入工作台 →'}).click();await page.locator('#app').waitFor({state:'visible'});
 await page.screenshot({path:'.data/e2e/projects.png'});
 await page.getByRole('button',{name:'＋ 新建视频'}).click();await page.locator('[name=title]').fill('铅笔的秘密 · 多页验收');await page.locator('[name=topic]').fill('用两页给小学生解释铅笔的原料和加工。');await page.getByRole('button',{name:'创建项目',exact:true}).click();
 await page.getByRole('button',{name:'＋ 添加一页分镜'}).click();
 let scene=page.locator('.scene').nth(0);await scene.locator('.scene-heading input').fill('铅笔芯里没有铅');await scene.locator('textarea').nth(0).fill('铅笔芯是由石墨和黏土混合制成的。');await scene.locator('textarea').nth(1).fill('石墨：留下痕迹\n黏土：调节硬度');await scene.locator('input[type=number]').fill('3');
 await page.getByRole('button',{name:'＋ 添加一页分镜'}).click();scene=page.locator('.scene').nth(1);await scene.locator('.scene-heading input').fill('三步做成一支铅笔');await scene.locator('textarea').nth(0).fill('混合原料，烧制笔芯，最后用木材包裹。');await scene.locator('textarea').nth(1).fill('混合原料\n烧制笔芯\n木材包裹');await scene.locator('select').selectOption('process');await scene.locator('input[type=number]').fill('3');
 await page.getByRole('button',{name:'保存修改',exact:true}).click();await page.getByRole('button',{name:'确认分镜',exact:true}).click();await page.locator('#save-state').filter({hasText:'分镜已确认'}).waitFor();await page.screenshot({path:'.data/e2e/editor.png',fullPage:true});
 await page.getByRole('button',{name:'提交制作任务 →'}).click();await page.locator('#heading').filter({hasText:'制作任务'}).waitFor();await page.screenshot({path:'.data/e2e/jobs.png'});
 const jobs=await page.evaluate(()=>fetch('/api/jobs').then(r=>r.json()));fs.writeFileSync('.data/e2e/submitted-job.json',JSON.stringify({job:jobs[0].id,status:jobs[0].status,errors}));console.log(JSON.stringify({job:jobs[0].id,status:jobs[0].status,errors}));if(errors.length)throw Error(errors.join('; '));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
