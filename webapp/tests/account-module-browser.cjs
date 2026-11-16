// Real production account component; only API/invoice transport is a fixture.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'..'),out=path.join(__dirname,'evidence/account-autodelivery');
const server=http.createServer((req,res)=>{
 if(req.url==='/isolated-account-fixture'){res.setHeader('Content-Type','text/html; charset=utf-8');return res.end('<!doctype html><meta charset="utf-8"><title>Isolated UI test</title>');}
 const file=path.resolve(root,'.'+new URL(req.url,'http://test').pathname);
 if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}
 res.setHeader('Content-Type',(file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/plain')+'; charset=utf-8');res.end(fs.readFileSync(file));
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));fs.mkdirSync(out,{recursive:true});
 const base='http://127.0.0.1:'+server.address().port,browser=await chromium.launch({headless:true,...(process.env.CI?{}:{channel:'msedge'})});
 try{for(const width of [320,390,430]){
  const context=await browser.newContext({viewport:{width,height:width===320?700:844},isMobile:true,hasTouch:true});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/isolated-account-fixture');
  await page.setContent(`<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="${base}/css/style.css"><link rel="stylesheet" href="${base}/css/account-sales.css"><button id="launch">Продать</button><section id="editor-view" class="view form-view" hidden style="padding:12px"><header><button id="back">Назад</button><h1 id="editor-title"></h1></header><div id="editor-body"></div></section><main id="card"></main>`);
  await page.addScriptTag({url:base+'/js/account-sales.js'});
  await page.evaluate(width=>{
   const fixture=window.testAccount={car:0,refresh:0,reveals:0,submissions:[],copies:0,support:0,uploads:0,pinStarts:0,invoices:0,notices:[],activeCount:width===320?0:width===390?3:4,retentionDays:width===430?3:1};
   Object.defineProperty(navigator,'clipboard',{configurable:true,value:{async writeText(){fixture.copies++;}}});
   window.Telegram={WebApp:{openInvoice(_url,callback){fixture.invoices++;callback(width===430?'paid':'cancelled');}}};
   const api={async request(path,options={}){
    if(path==='/account-publication-rules')return {enabled:true,active_count:fixture.activeCount,free_limit:3,price_af:15,vip_stars:5,vip_hours:24,video_max_bytes:104857600,secret_retention_days:fixture.retentionDays};
    if(path==='/account-videos')return {id:'00000000-0000-4000-a000-000000000005',upload_url:width===390?'/account-videos/00000000-0000-4000-a000-000000000005/content':'https://isolated-storage.example/upload',upload_transport:width===390?'miniapp':'s3',content_type:'video/mp4'};
    if(path.endsWith('/cancel')){fixture.cancelled=true;return {status:'cancelled'};}
    if(path.endsWith('/status'))return {id:'video-fixture',ready:false,status:'uploading'};
    if(path.endsWith('/complete'))return {id:'video-fixture',ready:true};
    if(path==='/account-products'){
     const data=JSON.parse(options.body);fixture.submissions.push(data);
     if(fixture.activeCount>=3&&!data.publication_fee_confirmed)throw Object.assign(new Error('Публикация дополнительного аккаунта стоит 15 AF'),{detail:{code:'account_publication_confirmation',price_af:'15'}});
     fixture.published=true;return {id:'test-account'};
    }
    if(path==='/account-products/test-account/pin'){if(!fixture.published)throw Error('VIP before publication');fixture.pinStarts++;return {id:'pin-fixture',invoice_url:'https://t.me/$isolated-invoice',status:'pending'};}
    if(path==='/account-pins/pin-fixture')return {id:'pin-fixture',status:width===430?'completed':'pending'};
    if(path.endsWith('/credentials')){fixture.reveals++;return {login:'test-account-login',password:'test-password-DO-NOT-LOG'};}
    throw Error('Unexpected fixture request '+path);
   },async upload(){return {url:'/api/media/00000000-0000-4000-a000-000000000001'};},async uploadAccountVideo(upload,file,options){
    if(!(file instanceof File)||upload.content_type!=='video/mp4')throw Error('Invalid video upload');fixture.uploads++;options.onProgress(25);
    if(fixture.holdUpload)await new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Error('Cancelled')),{once:true}));
    options.onProgress(100);
   }};
   window.accountModule=AutoFlowAccountSales.create({api,notify:message=>fixture.notices.push(message),refresh:async()=>fixture.refresh++,openCar:()=>fixture.car++,support(){fixture.support++;},userId:()=> 'buyer',reloadDeal:async()=>{},topup(){},
    showEditor(page,listing){document.querySelector('#editor-title').textContent=listing?'Изменить аккаунт':'Продать аккаунт';document.querySelector('#editor-body').replaceChildren(page);document.querySelector('#editor-view').hidden=false;},
    closeEditor(saved){fixture.closedTo=saved?.id;document.querySelector('#editor-view').hidden=true;}});
   document.querySelector('#launch').onclick=()=>accountModule.choose();document.querySelector('#back').onclick=()=>{document.querySelector('#editor-view').hidden=true;};
  },width);
  await page.locator('#launch').click();
  const choices=page.locator('dialog.account-modal .account-sale-choice');assert.equal(await choices.count(),2);
  for(const choice of await choices.all()){
   const appearance=await choice.evaluate(el=>{const s=getComputedStyle(el);return {background:s.backgroundImage,color:s.color,weight:Number(s.fontWeight),font:parseFloat(s.fontSize),height:el.getBoundingClientRect().height};});
   assert.match(appearance.background,/255, 229, 139/);assert.equal(appearance.color,'rgb(32, 22, 6)');assert(appearance.weight<=500&&appearance.font>=14&&appearance.height>=44&&appearance.height<70);
  }
  await page.locator('dialog.account-modal').evaluate(el=>Promise.all(el.getAnimations().map(a=>a.finished)));
  await page.screenshot({path:path.join(out,`sale-choice-${width}.png`)});
  await page.getByRole('button',{name:/🚗 Автомобиль/}).click();assert.equal(await page.evaluate(()=>testAccount.car),1);
  await page.locator('#launch').click();await page.getByRole('button',{name:/👤 Аккаунт/}).click();
  const form=page.locator('#editor-body form.account-form');await form.waitFor();
  assert.equal(await form.evaluate(el=>el.closest('dialog')===null),true,'Full app page, not a modal');
  assert.equal(await page.getByRole('heading',{name:'Как работает автовыдача?',exact:true}).count(),0);
  assert.equal(await form.locator('[name=no_personal_mail_required]').count(),0);
  const quota=form.locator('.account-quota');assert.match(await quota.innerText(),width===320?/0 из 3 использовано/:width===390?/3 из 3 использовано/:/4 активных объявления/);
  assert.equal(await form.locator('[name=vip]').isChecked(),true,'VIP defaults on, but creates no invoice before publication');
  assert.equal(await page.evaluate(()=>testAccount.pinStarts),0);
  await form.locator('[name=game_version]').selectOption('car_parking_2');await form.locator('[name=title]').fill('Аккаунт CP2 — тестовая коллекция');
  await page.locator('#back').click();await page.locator('#launch').click();await page.getByRole('button',{name:/👤 Аккаунт/}).click();
  assert.equal(await form.locator('[name=title]').inputValue(),'Аккаунт CP2 — тестовая коллекция','Back preserves in-memory draft');
  await page.evaluate(()=>{testAccount.activeCount=1;document.querySelector('#back').click();});
  await page.locator('#launch').click();await page.getByRole('button',{name:/👤 Аккаунт/}).click();
  assert.match(await quota.innerText(),/1 из 3 использовано/);assert.match(await quota.innerText(),/Осталось бесплатно: 2/);
  await page.evaluate(count=>{testAccount.activeCount=count;document.querySelector('#back').click();},width===320?0:width===390?3:4);
  await page.locator('#launch').click();await page.getByRole('button',{name:/👤 Аккаунт/}).click();
  const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jDrsAAAAASUVORK5CYII=','base64');
  await form.locator('[name=cover]').setInputFiles({name:'cover.png',mimeType:'image/png',buffer:png});
  if(width===390){
    await page.evaluate(()=>{testAccount.holdUpload=true;});
    await form.locator('[name=video]').setInputFiles({name:'cancelled.mp4',mimeType:'video/mp4',buffer:Buffer.from('cancelled fixture')});
    await form.getByRole('button',{name:'Отменить загрузку видео',exact:true}).click();
    await form.getByText(/Загрузка отменена/).waitFor();
    assert.equal(await form.locator('[name=title]').inputValue(),'Аккаунт CP2 — тестовая коллекция');assert.equal(await page.evaluate(()=>testAccount.submissions.length),0);
    await page.evaluate(()=>{testAccount.holdUpload=false;});
  }
  await form.locator('[name=video]').setInputFiles({name:'review.mp4',mimeType:'video/mp4',buffer:Buffer.from('isolated test fixture')});
  await form.getByText('Видео готово ✓',{exact:true}).waitFor();assert.equal(await page.evaluate(()=>testAccount.uploads),width===390?2:1,'Upload starts at selection, not publication');
  const pausedDraft=await form.locator('video').evaluate(media=>{let calls=0;const nativePause=media.pause;media.pause=function(){calls++;nativePause.call(this);};accountModule.pauseVideos();media.pause=nativePause;return calls;});
  assert.equal(pausedDraft,1,'Leaving/hiding the app pauses the in-memory draft preview, not only listing players');
  await form.locator('[name=description]').fill('Реальные значения тестовой коллекции. Изолированная проверка интерфейса.');await form.locator('[name=price_af_coins]').fill('100');await form.locator('[name=owns_account]').check();
  if(width===320)await form.locator('[name=vip]').uncheck();
  await form.getByRole('button',{name:'Как работает автовыдача?',exact:true}).click();
  const help=page.getByRole('dialog',{name:'Как работает автовыдача?',exact:true});await help.waitFor();
  assert.match(await help.innerText(),/хранит их в зашифрованном виде/);assert.match(await help.innerText(),new RegExp('Через '+(width===430?3:1)+' сут\\. после завершения сделки'));
  await help.evaluate(el=>Promise.all(el.getAnimations().map(a=>a.finished)));await page.screenshot({path:path.join(out,`autodelivery-help-${width}.png`)});
  await page.evaluate(()=>accountModule.dismiss());await help.waitFor({state:'detached'});
  assert.equal(await form.locator('[name=title]').inputValue(),'Аккаунт CP2 — тестовая коллекция');assert.equal(await page.evaluate(()=>document.body.style.overflow),'','Help restores normal page scroll');
  assert.equal(await page.evaluate(()=>testAccount.submissions.length),0);assert.equal(await form.locator('[name=password]').evaluate(el=>getComputedStyle(el).fontSize),'16px');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:path.join(out,`form-${width}.png`),fullPage:true});
  await form.locator('[name=login]').fill('test@example.test');await form.locator('[name=password]').fill('test-password-DO-NOT-LOG');
  const uploadsBefore=await page.evaluate(()=>testAccount.uploads);
  await form.getByRole('button',{name:'Опубликовать аккаунт',exact:true}).click();
  if(width!==320){await page.getByRole('heading',{name:'Лимит бесплатных объявлений',exact:true}).waitFor();await page.waitForTimeout(500);await page.getByRole('button',{name:'Опубликовать за 15 AF',exact:true}).click();}
  await form.waitFor({state:'detached'});await page.waitForFunction(()=>testAccount.refresh>=1);
  if(width!==320)await page.waitForFunction(()=>testAccount.invoices===1&&testAccount.notices.some(m=>m.includes('без VIP')||m==='Аккаунт закреплён'));
  const state=await page.evaluate(()=>({count:testAccount.submissions.length,paid:testAccount.submissions.at(-1).publication_fee_confirmed||false,game:testAccount.submissions.at(-1).game_version,mail:testAccount.submissions.some(d=>Object.hasOwn(d,'no_personal_mail_required')),pin:testAccount.pinStarts,invoices:testAccount.invoices,closed:testAccount.closedTo,uploads:testAccount.uploads}));
  assert.deepEqual(state,{count:width===320?1:2,paid:width!==320,game:'car_parking_2',mail:false,pin:width===320?0:1,invoices:width===320?0:1,closed:'test-account',uploads:uploadsBefore});
  await page.evaluate(()=>accountModule.panel(document.querySelector('#card'),{id:'deal-fixture',buyer_id:'buyer',status:'transfer_in_progress'}));
  assert.equal(await page.evaluate(()=>testAccount.reveals),0);await page.getByRole('button',{name:'🔐 Открыть аккаунт',exact:true}).click();await page.locator('[name=password]').waitFor();
  assert.equal(await page.locator('[name=password]').getAttribute('type'),'password');await page.getByRole('button',{name:'Показать / скрыть',exact:true}).click();await page.getByRole('button',{name:'Скопировать',exact:true}).last().click();
  assert.equal(await page.evaluate(()=>testAccount.copies),1);await page.evaluate(()=>accountModule.dismiss());await page.locator('dialog.account-modal').waitFor({state:'detached'});assert.equal(await page.locator('[name=password]').count(),0);
  assert.equal(await page.evaluate(()=>JSON.stringify(localStorage).includes('DO-NOT-LOG')),false);assert.deepEqual(errors,[]);
  await context.close();console.log(`PASS full account page, quotas 0/1/3/4, early upload, default VIP/off/cancelled/paid, protected credentials ${width}px`);
 }}finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
