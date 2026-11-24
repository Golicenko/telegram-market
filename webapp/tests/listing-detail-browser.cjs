// Production UI, isolated HTTP fixtures only; never a production purchase or bot send.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'..'),out=path.join(__dirname,'evidence/car-detail');
const photo=colour=>`<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="504" viewBox="0 0 1200 504"><defs><linearGradient id="b" x2="1" y2="1"><stop stop-color="#202c33"/><stop offset="1" stop-color="#060c11"/></linearGradient></defs><rect width="1200" height="504" fill="url(#b)"/><path d="M0 460h1200M40 55h230l-140 90H0M990 50h190v190" fill="none" stroke="#edbd16" stroke-width="7"/><path d="m150 360 65-100 210-35 100-100h260l150 120 120 30 30 96H150" fill="${colour}" stroke="#a5aeb4" stroke-width="5"/><path d="m469 220 80-70h220l100 80Z" fill="#0a111a"/><circle cx="335" cy="356" r="64" fill="#070a0d" stroke="#777" stroke-width="15"/><circle cx="894" cy="356" r="64" fill="#070a0d" stroke="#777" stroke-width="15"/><text x="35" y="490" fill="#94a0ad" font-size="20">ISOLATED UI TEST · not a live listing</text></svg>`;
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://isolated');
 if(url.pathname.startsWith('/fixture-photo')){res.setHeader('Content-Type','image/svg+xml');return res.end(photo(url.pathname.includes('2')?'#243f50':'#39463b'));}
 const file=path.resolve(root,'.'+(url.pathname==='/'?'/index.html':url.pathname));
 if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}
 res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.html':'text/html','.jpg':'image/jpeg','.png':'image/png'})[path.extname(file)]||'application/json');res.end(fs.readFileSync(file));
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,...(process.env.CI?{}:{channel:'msedge'})});
 try{for(const width of [320,390,430]){
  const context=await browser.newContext({viewport:{width,height:844},isMobile:true,hasTouch:true,reducedMotion:'reduce'});
  await context.route(/^https:/,route=>route.fulfill({status:200,body:''}));
  const user={id:'buyer',telegram_id:77,first_name:'Тестовый покупатель',role:'user'},wallet={available_balance:500,frozen_balance:0,total_earned:0};
  const base={product_kind:'car',seller_id:'seller',model:'',power_hp:1703,max_speed_kph:420,price_af_coins:25,description:'✓ W16\n✓ Миги\n1703hp · 1977nm\nПередача происходит в самой игре.\nТорг есть, предлагайте цену ✍',delivery_time_estimate:'up_to_1h',listing_type:'regular',status:'active',views_count:3,likes_count:2,liked_by_me:false,images:['/fixture-photo.svg','/fixture-photo-2.svg','/fixture-photo-3.svg'],created_at:'2026-11-24T09:00:00Z',game_version:'car_parking_1',pinned:false,pinned_until:null};
  const listings=Array.from({length:17},(_,i)=>({...base,id:`car-${i}`,brand:['BMW M5 CS LEVEL','Toyota Supra','Nissan GTR R35','Mercedes E63'][i%4],price_af_coins:25+i,game_version:i%2?'car_parking_2':'car_parking_1'}));
  listings[14].images=['/fixture-photo.svg'];
  listings[15]={...listings[15],images:[],description:'',seller_id:'no-other',brand:'Нет фото'};
  listings[16]={...listings[16],images:['/missing-photo.jpg'],seller_id:'different-seller',brand:'Очень длинное название автомобиля для проверки маленького экрана без горизонтального переполнения'};
  const sharedId='11111111-1111-4111-8111-111111111111';
  const findListing=id=>id===sharedId?{...listings[0],id:sharedId,brand:'Объявление по ссылке'}:listings.find(i=>i.id===id);
  let saved=false,shareCalls=0,failContext=false,delayed=false,purchases=[],messages=[],offers=[];
  await context.addInitScript(()=>{window.Telegram={WebApp:{initData:'isolated-test',ready(){},expand(){},onEvent(){},BackButton:{onClick(fn){window.testBack=fn;},show(){},hide(){}},openTelegramLink(url){window.testShare=url;}}};});
  await context.route('**/api/**',async route=>{
   const req=route.request(),url=new URL(req.url()),p=url.pathname.slice(4);let body=[],status=200;
   if(p==='/me')body={user,wallet};
   else if(p==='/profile')body={user,wallet,active_listings:[],sold_listings:[],purchases:[],wallet_transactions:[],withdrawals:[],conversations:[],deal_threads:[]};
   else if(p==='/content/unseen')body={unique:{unseen_count:0,marker:0},training:{unseen_count:0,marker:0}};
   else if(p==='/conversations/unread-summary')body={total_unread:0,conversations:[]};
   else if(p==='/account-publication-rules')body={enabled:false};
   else if(p==='/listings')body=url.searchParams.get('type')==='regular'?listings:[];
   else if(p.match(/^\/listings\/[^/]+\/seller-context$/)){
    const item=findListing(p.split('/')[2]);if(failContext){status=503;body={detail:'Unavailable'};}
    else {const all=listings.filter(i=>i.seller_id===item.seller_id&&i.id!==item.id);const offset=Number(url.searchParams.get('offset')||0);body={name:'Тестовый продавец',photo_url:null,completed_sales:7,saved_by_me:saved,other_active_count:item.seller_id==='no-other'?0:all.length,items:item.seller_id==='no-other'?[]:all.slice(offset,offset+12),has_more:offset+12<all.length};}
   }else if(p.match(/^\/listings\/[^/]+\/share-link$/)){shareCalls++;body={url:`https://t.me/AutoFlowStoreBot?startapp=listing_${p.split('/')[2]}`};}
   else if(p.match(/^\/listings\/[^/]+\/purchase$/)){purchases.push(p.split('/')[2]);status=409;body={detail:'Тест завершён до списания'};}
   else if(p.match(/^\/conversations\/listing\/[^/]+$/)){messages.push(p.split('/')[3]);status=409;body={detail:'Тестовый чат'};}
   else if(p.match(/^\/conversations\/listing\/[^/]+\/offers$/)){offers.push({id:p.split('/')[3],body:req.postDataJSON()});status=409;body={detail:'Тестовое предложение'};}
   else if(p.match(/^\/listings\/[^/]+\/like$/)){body={views_count:4,likes_count:3,liked_by_me:true};}
   else if(p.endsWith('/view'))body={views_count:4,likes_count:2,liked_by_me:false};
   else if(p.startsWith('/favorites/')){saved=req.method()==='POST';body={ok:true};}
   else if(p.match(/^\/listings\/[^/]+$/)){if(delayed&&p.endsWith('/car-2'))await new Promise(r=>setTimeout(r,700));body=findListing(p.split('/')[2]);}
   await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const url=`http://127.0.0.1:${server.address().port}`;
  await page.goto(url);await page.locator('#marketCars [data-listing-card="car-0"] h3').click();
  await page.locator('#listingSellerSales').filter({hasText:'7 успешных сделок'}).waitFor();
  const detail=page.locator('.listing-page--car');await detail.waitFor();
  assert.equal(await page.locator('#listingOtherCount').innerText(),'14');
  assert.equal(await page.locator('#listingPageSpecs > span').count(),4);
  assert.equal(await page.locator('#listingGallery .listing-gallery__frame').count(),3);
  const geometry=await page.evaluate(()=>['.listing-page__media','#listingGallery','.listing-gallery__track','.listing-gallery__frame'].map(s=>{const e=document.querySelector(s),c=getComputedStyle(e),r=e.getBoundingClientRect();return {s,parent:e.parentElement.className,hidden:e.hidden,w:r.width,h:r.height,position:c.position,display:c.display,aspect:c.aspectRatio,cssWidth:c.width,cssHeight:c.height};}));
  assert((await page.locator('#listingGallery').boundingBox()).height>100,JSON.stringify(geometry));
  await page.waitForFunction(()=>[...document.querySelectorAll('#listingGallery img')].every(i=>i.complete&&i.naturalWidth>0));
  const buyBox=await page.locator('#listingPageBuy').boundingBox(),navDisc=await page.locator('.nav-market-disc').boundingBox();
  assert(buyBox.y+buyBox.height<navDisc.y,'Purchase CTA must not overlap the unchanged bottom navigation');
  await page.screenshot({path:path.join(out,`car-detail-${width}.png`),fullPage:true});
  await page.locator('#listingGallery button[aria-label="Фото 2"]').click();
  await page.waitForFunction(()=>document.querySelector('#listingGallery .listing-gallery__controls span').textContent==='2 / 3');
  await page.getByRole('button',{name:'Открыть фото на весь экран',exact:true}).click();
  const lightbox=page.getByRole('dialog',{name:'Фотографии автомобиля на весь экран'});await lightbox.waitFor();
  assert.match(await lightbox.locator('.listing-gallery__controls').innerText(),/2 \/ 3/);
  await page.evaluate(()=>testBack());await lightbox.waitFor({state:'detached'});assert.equal(await page.locator('#listingPageTitle').innerText(),listings[0].brand);
  await page.locator('#listingSave').click();await page.waitForFunction(()=>document.querySelector('#listingSave').getAttribute('aria-pressed')==='true');assert(saved);
  await page.locator('#listingShare').click();await page.waitForFunction(()=>Boolean(window.testShare));assert.equal(shareCalls,1);
  assert.match(await page.evaluate(()=>testShare),/startapp%3Dlisting_car-0/);
  await page.locator('#listingPageLike').click();assert.match(await page.locator('#listingPageLike').innerText(),/3/);
  const horizontal=page.locator('#listingOtherTrack');await horizontal.evaluate(el=>el.scrollLeft=el.scrollWidth);
  await page.waitForFunction(()=>document.querySelectorAll('#listingOtherTrack button').length===14);
  assert.equal(await horizontal.evaluate(el=>getComputedStyle(el).flexWrap),'nowrap');
  const firstState=await page.evaluate(()=>{window.scrollTo(0,110);const el=document.querySelector('#listingOtherTrack');el.scrollLeft=90;return {scrollY:window.scrollY,left:el.scrollLeft};});
  await page.locator('#listingOtherTrack [data-open-listing="car-2"]').click();
  await page.waitForFunction(()=>document.querySelector('#listingPageTitle').textContent==='Nissan GTR R35');
  assert.equal(await page.evaluate(()=>scrollY),0);
  // All existing actions must follow the selected car, not the previous page.
  await page.locator('#listingPageChat').click();await page.waitForFunction(()=>document.querySelector('#toast').textContent==='Тестовый чат');assert.deepEqual(messages,['car-2']);
  await page.locator('#listingPageOfferButton').click();await page.locator('#listingOfferAmount').fill('19');await page.locator('#listingOfferForm button[type=submit]').click();
  await page.waitForFunction(()=>document.querySelector('#toast').textContent==='Тестовое предложение');assert.equal(offers[0].id,'car-2');assert.equal(offers[0].body.amount_af_coins,19);
  await page.locator('[data-close-listing-offer]').click();
  await page.locator('#listingPageBuy').click();assert.match(await page.locator('#purchaseModalText').innerText(),/27/);
  await page.locator('#purchaseModalAction').click();await page.waitForFunction(()=>document.querySelector('#purchaseModalText').textContent==='Тест завершён до списания');assert.deepEqual(purchases,['car-2']);
  await page.locator('[data-close-purchase]').first().click();
  await page.locator('#listingOtherTrack [data-open-listing="car-3"]').click();
  await page.waitForFunction(()=>document.querySelector('#listingPageTitle').textContent==='Mercedes E63');
  await page.evaluate(()=>testBack());await page.waitForFunction(()=>document.querySelector('#listingPageTitle').textContent==='Nissan GTR R35');
  await page.waitForTimeout(480);await page.evaluate(()=>testBack());await page.waitForFunction(()=>document.querySelector('#listingPageTitle').textContent==='BMW M5 CS LEVEL');
  await page.waitForFunction(y=>Math.abs(scrollY-y)<3,firstState.scrollY);
  assert(Math.abs(await horizontal.evaluate(el=>el.scrollLeft)-firstState.left)<3,`restored=${await horizontal.evaluate(el=>el.scrollLeft)} expected=${firstState.left}`);
  await page.waitForTimeout(480);await page.evaluate(()=>testBack());await page.locator('[data-view="market"]').waitFor({state:'visible'});
  // Single/no/broken photos, long names, no other vehicles, and retry are not blank screens.
  failContext=true;await page.locator('#marketCars [data-listing-card="car-15"] h3').click();await page.locator('#listingSellerRetry').waitFor({state:'visible'});
  failContext=false;await page.locator('#listingSellerRetry').click();await page.locator('#listingSellerSales').filter({hasText:'7 успешных сделок'}).waitFor();
  assert(await page.locator('#listingOtherCars').isHidden());assert.match(await page.locator('#listingGallery').innerText(),/Фотографий пока нет/);
  await page.locator('.bottom-nav [data-nav-target="market"]').click();await page.locator('#marketCars [data-listing-card="car-14"] h3').click();
  assert(await page.locator('#listingGallery .listing-gallery__dots').isHidden());assert.match(await page.locator('#listingGallery .listing-gallery__controls').innerText(),/1 \/ 1/);
  await page.locator('.bottom-nav [data-nav-target="market"]').click();await page.locator('#marketCars [data-listing-card="car-16"] h3').click();
  await page.locator('.listing-gallery__missing').filter({hasText:'Фото недоступно'}).waitFor();
  assert(await page.locator('#listingGallery .listing-gallery__dots').isHidden());
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  // Stale listing response must not reopen detail after a tab navigation.
  await page.locator('.bottom-nav [data-nav-target="market"]').click();delayed=true;await page.locator('#marketCars [data-listing-card="car-2"] h3').click();
  await page.locator('.bottom-nav [data-nav-target="profile"]').click();await page.waitForTimeout(850);await page.locator('[data-view="profile"]').waitFor({state:'visible'});delayed=false;
  if(width===390){
   const shared=await context.newPage();shared.on('pageerror',e=>errors.push(e.message));
   await shared.goto(url+'/?startapp=listing_'+sharedId);await shared.locator('#listingPageTitle').filter({hasText:'Объявление по ссылке'}).waitFor();
   assert.equal(await shared.locator('#listingPageBuy').innerText(),'Купить за 25 AF');await shared.evaluate(()=>testBack());await shared.locator('[data-view="market"]').waitFor({state:'visible'});await shared.close();
  }
  assert.deepEqual(errors,[]);await context.close();console.log(`PASS car detail ${width}px: gallery/fullscreen, real server context, favorite/share/likes, pagination, A→B→C→B→A→catalog, scroll restore, missing media, retry and stale response`);
 }}finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
