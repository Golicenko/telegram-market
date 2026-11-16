// Production account form/viewer in a real browser. Only transport is a fixture.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'..'),out=path.join(__dirname,'evidence/account-autodelivery');
const server=http.createServer((req,res)=>{if(req.url==='/isolated-account-fixture'){res.setHeader('Content-Type','text/html; charset=utf-8');return res.end('<!doctype html><meta charset="utf-8"><title>Isolated UI test</title>');}const file=path.resolve(root,'.'+new URL(req.url,'http://test').pathname);if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}res.setHeader('Content-Type',(file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/plain')+'; charset=utf-8');res.end(fs.readFileSync(file));});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));fs.mkdirSync(out,{recursive:true});
 const base='http://127.0.0.1:'+server.address().port,browser=await chromium.launch({headless:true,...(process.env.CI?{}:{channel:'msedge'})});
 try{for(const width of [320,390,430]){
  const context=await browser.newContext({viewport:{width,height:width===320?700:844},isMobile:true,hasTouch:true});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/isolated-account-fixture'); // Blank same-origin document; no old app timers.
  await page.setContent(`<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="${base}/css/style.css"><link rel="stylesheet" href="${base}/css/account-sales.css"><button id="launch">Продать</button><main id="card"></main>`);
  await page.addScriptTag({url:base+'/js/account-sales.js'});
  await page.route('**/fixture-video',r=>r.fulfill({status:200,body:''}));
  await page.evaluate(width=>{
   const fixture=window.testAccount={car:0,refresh:0,reveals:0,submissions:[],copies:0,support:0,volumeUploads:0};
   Object.defineProperty(navigator,'clipboard',{configurable:true,value:{async writeText(){fixture.copies++;}}});
   const api={async request(path,options={}){
    if(path==='/account-publication-rules')return {enabled:true,free_limit:3,price_af:15,vip_stars:5,vip_hours:24,video_max_bytes:104857600,secret_retention_days:1};
    if(path==='/account-videos')return {id:'00000000-0000-4000-a000-000000000005',upload_url:width===390?'/account-videos/00000000-0000-4000-a000-000000000005/content':location.origin+'/fixture-video',upload_transport:width===390?'miniapp':'s3',content_type:'video/mp4'};
    if(path.endsWith('/content')){if(options.headers['Content-Type']!=='video/mp4'||!(options.body instanceof File)||options.method!=='PUT')throw Error('Invalid binary video request');fixture.volumeUploads++;return {ready:true};}
    if(path.endsWith('/complete'))return {id:'video-fixture',ready:true};
    if(path==='/account-products'){
     const data=JSON.parse(options.body);fixture.submissions.push(data);
     if(!data.publication_fee_confirmed)throw Object.assign(new Error('Публикация дополнительного аккаунта стоит 15 AF'),{detail:{code:'account_publication_confirmation',price_af:'15'}});
     return {id:'test-account'};
    }
    if(path.endsWith('/credentials')){fixture.reveals++;return {login:'test-account-login',password:'test-password-DO-NOT-LOG'};}
    throw Error('Unexpected fixture request '+path);
   },async upload(){return {url:'/api/media/00000000-0000-4000-a000-000000000001'};}};
   window.accountModule=window.AutoFlowAccountSales.create({api,notify(){},refresh:async()=>fixture.refresh++,openCar:()=>fixture.car++,support(){fixture.support++;},userId:()=> 'buyer',reloadDeal:async()=>{},topup(){}});
   document.querySelector('#launch').onclick=()=>window.accountModule.choose();
  },width);
  await page.locator('#launch').click();
  await page.getByRole('button',{name:/🚗 Автомобиль/}).click();
  assert.equal(await page.evaluate(()=>window.testAccount.car),1);
  await page.locator('#launch').click();await page.getByRole('button',{name:/👤 Аккаунт/}).click();
  await page.waitForTimeout(500);await page.getByRole('button',{name:'Понятно, продолжить',exact:true}).click();
  const form=page.locator('form.account-form');await form.waitFor();
  await form.locator('[name=game_version]').selectOption('car_parking_2');
  const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jDrsAAAAASUVORK5CYII=','base64');
  await form.locator('[name=cover]').setInputFiles({name:'cover.png',mimeType:'image/png',buffer:png});
  await form.locator('[name=video]').setInputFiles({name:'review.mp4',mimeType:'video/mp4',buffer:Buffer.from('isolated test fixture')});
  await form.locator('[name=title]').fill('Аккаунт CP2 — тестовая коллекция');
  await form.locator('[name=description]').fill('Реальные значения тестовой коллекции. Изолированная проверка интерфейса.');
  await form.locator('[name=price_af_coins]').fill('100');
  await form.locator('[name=owns_account]').check();await form.locator('[name=no_personal_mail_required]').check();
  const geometry=await page.locator('dialog[open]').boundingBox();assert(geometry.x>=0&&geometry.x+geometry.width<=width+1);
  assert.equal(await form.locator('[name=password]').evaluate(el=>getComputedStyle(el).fontSize),'16px');
  // Screenshot is taken before filling either credential.
  await page.screenshot({path:path.join(out,'form-'+width+'.png')});
  await form.locator('[name=login]').fill('test@example.test');await form.locator('[name=password]').fill('test-password-DO-NOT-LOG');
  await form.getByRole('button',{name:'Опубликовать аккаунт',exact:true}).click();
  await page.getByRole('heading',{name:'Лимит бесплатных объявлений',exact:true}).waitFor();
  await page.waitForTimeout(500);await page.getByRole('button',{name:'Опубликовать за 15 AF',exact:true}).click();
  await page.locator('dialog[open]').waitFor({state:'detached'});
  assert.equal(await page.evaluate(()=>window.testAccount.refresh),1);
  const state=await page.evaluate(()=>({count:window.testAccount.submissions.length,paid:window.testAccount.submissions[1].publication_fee_confirmed,game:window.testAccount.submissions[1].game_version}));
  assert.deepEqual(state,{count:2,paid:true,game:'car_parking_2'});
  await page.evaluate(()=>document.querySelector('#card').append(window.accountModule.card({id:'deal-fixture',buyer_id:'buyer'},true)));
  assert.equal(await page.evaluate(()=>window.testAccount.reveals),0);
  await page.getByRole('button',{name:'🔐 Открыть аккаунт',exact:true}).click();await page.locator('[name=password]').waitFor();
  assert.equal(await page.locator('[name=password]').getAttribute('type'),'password');
  await page.getByRole('button',{name:'Показать / скрыть',exact:true}).click();
  assert.equal(await page.locator('[name=password]').getAttribute('type'),'text');
  await page.getByRole('button',{name:'Скопировать',exact:true}).last().click();
  assert.equal(await page.evaluate(()=>window.testAccount.copies),1);
  await page.evaluate(()=>window.accountModule.dismiss());await page.locator('dialog.account-modal').waitFor({state:'detached'});assert.equal(await page.locator('[name=password]').count(),0);
  assert.equal(await page.evaluate(()=>JSON.stringify(localStorage).includes('DO-NOT-LOG')),false);
  await page.evaluate(()=>window.accountModule.controls(document.querySelector('#card'),{id:'closed-account',buyer_id:'buyer',status:'completed'}));
  await page.getByRole('button',{name:'Обратиться в поддержку',exact:true}).click();assert.equal(await page.evaluate(()=>window.testAccount.support),1);
  assert.equal(await page.evaluate(()=>testAccount.volumeUploads),width===390?1:0);
  assert.deepEqual(errors,[]);await context.close();console.log('PASS account form, video PUT, 15 AF consent, protected popup and cleanup '+width+'px');
 }}finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
