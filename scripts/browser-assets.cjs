// Explicit acceptance test: uploads generated media fixtures and renders a project.
const fs=require('node:fs'),path=require('node:path');
const env=Object.fromEntries(fs.readFileSync('.env','utf8').split('\n').filter(l=>l.includes('=')&&!l.startsWith('#')).map(l=>{const i=l.indexOf('=');return[l.slice(0,i),l.slice(i+1)]}));
const rid=JSON.parse(fs.readFileSync('.data/runtimes/active.json')).runtime_id;
const {chromium}=require(path.join(process.cwd(),'.data/runtimes',rid,'skill/node_modules/playwright-core'));
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||(process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':'/usr/bin/chromium'),headless:true});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.env.BASE_URL||'http://127.0.0.1:'+(env.PORT||8000));await page.locator('#password').fill(process.env.ADMIN_PASSWORD||env.ADMIN_PASSWORD);await page.getByRole('button',{name:'进入工作台 →'}).click();await page.locator('#app').waitFor({state:'visible'});
 await page.locator('[data-nav=assets]').click();
 await page.locator('input[type=file]').setInputFiles('.data/e2e/assets/workflow.png');await page.getByRole('button',{name:'上传素材',exact:true}).click();await page.getByRole('heading',{name:'workflow.png',exact:true}).first().waitFor();
 await page.locator('.upload-controls select').selectOption('audio');await page.locator('input[type=file]').setInputFiles('.data/e2e/assets/narration-tone.wav');await page.getByRole('button',{name:'上传素材',exact:true}).click();await page.getByRole('heading',{name:'narration-tone.wav',exact:true}).first().waitFor();
 await page.screenshot({path:'.data/e2e/assets-library.png'});
 await page.locator('[data-nav=projects]').click();await page.getByRole('button',{name:'＋ 新建视频'}).click();await page.locator('[name=title]').fill('素材驱动的视频 · 验收');await page.locator('[name=topic]').fill('绑定上传的流程图片与测试音轨，验证图文布局和导出。');await page.getByRole('button',{name:'创建项目',exact:true}).click();await page.locator('[data-stage-link=storyboard]').click();await page.getByRole('button',{name:'＋ 添加一页分镜'}).click();
 const scene=page.locator('.scene').first();await scene.locator('.scene-heading input').fill('从想法到清晰的讲解');await scene.locator('textarea').nth(0).fill('先组织想法，再编写分镜，最后完成讲解。');await scene.locator('textarea').nth(1).fill('组织想法\n编写分镜\n完成讲解');
 await page.locator('[data-stage-link=media]').click();await scene.locator('.scene-asset.image').getByRole('button',{name:'选择素材'}).click();await page.locator('.asset-dialog').getByRole('button',{name:'使用此素材'}).first().click();
 await scene.locator('.scene-asset.audio').getByRole('button',{name:'选择素材'}).click();await page.locator('.asset-dialog').getByRole('button',{name:'使用此素材'}).first().click();
 await page.locator('[data-stage-link=export]').click();await page.locator('.export-group select').first().selectOption('uploaded');
 // Editing the scene must not reset chosen audio mode.
 await page.getByRole('button',{name:'保存修改',exact:true}).click();if(await page.locator('.export-group select').first().inputValue()!=='uploaded')throw Error('Audio selection reset');
 await page.getByRole('button',{name:'确认分镜',exact:true}).click();await page.locator('#save-state').filter({hasText:'分镜已确认'}).waitFor();
 const layouts=[];
 for(const width of [1440,1100,768,390]){
   await page.setViewportSize({width,height:1000});await page.screenshot({path:'.data/e2e/assets-editor-'+width+'.png',fullPage:true});
   const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);layouts.push({width,overflow});if(overflow)throw Error('Overflow at '+width);
 }
 await page.locator('[data-stage-link=media]').click();await scene.locator('.scene-asset.image').getByRole('button',{name:'更换素材'}).click();await page.screenshot({path:'.data/e2e/assets-picker-mobile.png'});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Dialog overflow');await page.locator('.asset-dialog').getByRole('button',{name:'关闭',exact:true}).click();
 await page.setViewportSize({width:1440,height:1000});await page.locator('[data-stage-link=export]').click();await page.getByRole('button',{name:'提交制作任务 →'}).click();await page.getByText('任务已提交',{exact:true}).waitFor();await page.getByRole('button',{name:'日志与结果',exact:true}).click();
 const jobs=await page.evaluate(()=>fetch('/api/jobs').then(r=>r.json()));const id=jobs[0].id;
 fs.writeFileSync('.data/e2e/assets-job.json',JSON.stringify({job:id,errors,layouts}));
 for(let attempt=0;attempt<180;attempt++){
   const job=await page.evaluate(id=>fetch('/api/jobs/'+id).then(r=>r.json()),id);
   if(['failed','interrupted','cancelled'].includes(job.status))throw Error(JSON.stringify(job));
   if(job.status==='succeeded'){
     const artifact=job.result.artifacts.find(a=>a.kind==='video');console.log(JSON.stringify({job:id,status:job.status,duration:artifact.duration,errors,layouts}));
     await page.screenshot({path:'.data/e2e/assets-job-finished.png'});if(errors.length)throw Error(errors.join(';'));return;
   }
   await page.waitForTimeout(1000);
 }
 throw Error('Rendering timeout');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
