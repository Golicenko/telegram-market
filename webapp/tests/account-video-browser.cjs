// Actual decoded WebM -> private Range endpoint -> production player. No media mocks.
const {chromium,webkit}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.env.ACCOUNT_VIDEO_TEST_URL,videoId=process.env.ACCOUNT_VIDEO_TEST_ID;
const out=path.join(__dirname,'evidence/account-video');
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const useWebKit=process.env.ACCOUNT_VIDEO_TEST_ENGINE==='webkit';
 const browser=await (useWebKit?webkit:chromium).launch({headless:true,...(process.env.CI||useWebKit?{}:{channel:'msedge'})});
 try{for(const width of [320,390,430]){
  const context=await browser.newContext({viewport:{width,height:844},isMobile:true,hasTouch:true});
  const page=await context.newPage(),errors=[],ranges=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('response',r=>{if(r.url().includes('/stream'))ranges.push(r.status());});
  await page.goto(base+'/account-video-test');
  await page.addStyleTag({path:path.resolve(__dirname,'../css/style.css')});
  await page.addStyleTag({path:path.resolve(__dirname,'../css/account-sales.css')});
  await page.addScriptTag({path:path.resolve(__dirname,'../js/account-sales.js')});
  await page.evaluate(({videoId,auth})=>{
   window.videoRequests=0;
   window.api={async request(path,options={}){
    window.videoRequests++;const response=await fetch('/api'+path,{...options,headers:{'X-Telegram-Init-Data':auth},credentials:'same-origin'});
    const data=await response.json();if(!response.ok)throw Error(data.detail);return data;
   }};
   window.accountModule=AutoFlowAccountSales.create({api,notify(){},refresh(){},userId:()=> 'test-buyer',reloadDeal(){},support(){}});
   document.body.innerHTML='<main style="padding:12px;max-width:600px;margin:auto"><div id="video" class="account-video"></div><div id="receipt"></div></main>';
   window.item={id:'test-account',product_kind:'account',video_asset_id:videoId,images:[]};
   accountModule.video(document.querySelector('#video'),item);
  },{videoId,auth:process.env.ACCOUNT_VIDEO_TEST_AUTH||''});
  assert.equal(await page.evaluate(()=>videoRequests),0,'No media prefetch before tap');
  await page.getByRole('button',{name:'Смотреть видео аккаунта',exact:true}).click();
  try { await page.waitForFunction(()=>{const v=document.querySelector('video');return v&&Number.isFinite(v.duration)&&v.duration>20;}); }
  catch (_) { throw Error('Video metadata unavailable: '+JSON.stringify(await page.evaluate(()=>{const v=document.querySelector('video');return {error:v?.error?.code,networkState:v?.networkState,webm:v?.canPlayType('video/webm; codecs="vp8"'),mp4:v?.canPlayType('video/mp4; codecs="avc1.42E01E"'),message:document.querySelector('.account-video__status')?.textContent};}))); }
  await page.evaluate(()=>document.querySelector('video').pause());
  const seek=page.getByRole('slider',{name:'Позиция видео'});
  await seek.evaluate(el=>{el.value='12';el.dispatchEvent(new Event('input'));});
  await page.waitForFunction(()=>Math.abs(document.querySelector('video').currentTime-12)<.5);
  await page.getByRole('combobox',{name:'Скорость видео'}).selectOption('2');
  assert.equal(await page.locator('video').evaluate(v=>v.playbackRate),2);
  await page.getByRole('combobox',{name:'Скорость видео'}).selectOption('5');
  assert.equal(await page.locator('video').evaluate(v=>v.playbackRate),5);
  await page.getByRole('button',{name:'Воспроизвести видео',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('video').currentTime>14);
  await page.getByRole('button',{name:'Пауза',exact:true}).click();
  const position=await page.locator('video').evaluate(v=>v.currentTime);
  await page.evaluate(()=>accountModule.video(document.querySelector('#video'),{...item}));
  assert.equal(await page.locator('video').count(),1);
  assert.equal(await page.locator('video').evaluate(v=>v.currentTime),position,'Refresh must preserve position');
  assert.equal(await page.evaluate(()=>videoRequests),1,'Re-render must not request a second playback URL');
  await page.getByRole('button',{name:'Воспроизвести видео',exact:true}).click();
  await page.evaluate(()=>accountModule.pauseVideos());
  assert.equal(await page.locator('video').evaluate(v=>v.paused),true);
  assert.ok(ranges.includes(206),'Browser must receive a real byte-range response');
  assert.equal((await context.cookies()).length,0,'Playback must work without cookies');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:path.join(out,`player-${width}.png`),fullPage:true});
  await page.evaluate(()=>accountModule.controls(document.querySelector('#receipt'),{id:'receipt-test',buyer_id:'test-buyer',status:'transfer_in_progress',transfer_started_at:new Date(Date.now()-61000).toISOString()}));
  await page.getByRole('button',{name:'Аккаунт получен',exact:true}).click();
  assert.match(await page.locator('dialog').innerText(),/действительно соответствует описанию и видео/);
  assert.match(await page.locator('dialog').innerText(),/смените привязанную электронную почту/);
  assert.match(await page.locator('dialog').innerText(),/продавец может попытаться вернуть доступ/);
  assert.equal(await page.getByRole('button',{name:'Подтвердить получение',exact:true}).isDisabled(),true);
  await page.locator('dialog').evaluate(el=>Promise.all(el.getAnimations().map(animation=>animation.finished)));
  await page.screenshot({path:path.join(out,`receipt-warning-${width}.png`),fullPage:true});
  await page.getByRole('button',{name:'Вернуться к проверке',exact:true}).click();
  assert.equal(await page.evaluate(()=>videoRequests),1,'Cancel must not confirm or change money');
  assert.equal(await page.locator('dialog').count(),0);
  assert.deepEqual(errors,[]);await context.close();
  console.log(`PASS ${useWebKit?'WebKit':'Chromium'} real volume video, Range/seek/pause/2x/5x, refresh, receipt warning ${width}px`);
 }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
