// Real frontend DOM and browser; HTTP/Telegram fixtures are isolated from production.
// CATALOG_BASELINE=1 serves the committed baseline instead of concurrently edited files.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const baseline = process.env.CATALOG_BASELINE === '1';
const revision = process.env.CATALOG_BASELINE_REF || 'a9eef21';
const cache = new Map();
const evidence = path.join(__dirname, 'evidence');
fs.mkdirSync(evidence, { recursive: true });
const mime = { '.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.png':'image/png', '.jpg':'image/jpeg', '.svg':'image/svg+xml' };
function fixtureFile(relative) {
  if (!baseline) return fs.readFileSync(path.join(root, relative));
  if (!cache.has(relative)) cache.set(relative, execFileSync('git', ['show', `${revision}:webapp/${relative.replaceAll('\\', '/')}`], { cwd: root, maxBuffer: 12 * 1024 * 1024 }));
  return cache.get(relative);
}
const server = http.createServer((request, response) => {
  const pathname = new URL(request.url, 'http://fixture').pathname;
  if (pathname.startsWith('/api/')) { response.writeHead(404); return response.end(); }
  const relative = pathname === '/' ? 'index.html' : pathname.slice(1);
  if (relative.includes('..')) { response.writeHead(404); return response.end(); }
  try {
    response.setHeader('Content-Type', mime[path.extname(relative)] || 'application/json');
    response.end(fixtureFile(relative));
  } catch { response.writeHead(404); response.end(); }
});
const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

function instrumentation() {
  const metrics = window.__catalogMetrics = { listenersAdded:0, listenersRemoved:0, observersCreated:0, observersActive:0, cardsAdded:0, cardsRemoved:0, longTasks:[], mutations:0 };
  const nativeAdd = EventTarget.prototype.addEventListener;
  const nativeRemove = EventTarget.prototype.removeEventListener;
  EventTarget.prototype.addEventListener = function(...args) { metrics.listenersAdded++; return nativeAdd.apply(this, args); };
  EventTarget.prototype.removeEventListener = function(...args) { metrics.listenersRemoved++; return nativeRemove.apply(this, args); };
  const NativeIntersectionObserver = window.IntersectionObserver;
  if (NativeIntersectionObserver) window.IntersectionObserver = class extends NativeIntersectionObserver {
    constructor(...args) { super(...args); metrics.observersCreated++; this.__metricActive = false; }
    observe(target) { if (!this.__metricActive) { this.__metricActive=true; metrics.observersActive++; } return super.observe(target); }
    disconnect() { if (this.__metricActive) { this.__metricActive=false; metrics.observersActive--; } return super.disconnect(); }
  };
  if (window.PerformanceObserver) {
    try { new PerformanceObserver(list => metrics.longTasks.push(...list.getEntries().map(entry => entry.duration))).observe({ type:'longtask', buffered:true }); } catch {}
  }
  const countCards = node => node.nodeType === 1 ? Number(node.matches('[data-listing-card]')) + node.querySelectorAll('[data-listing-card]').length : 0;
  const mutation = new MutationObserver(entries => {
    for (const entry of entries) {
      metrics.mutations++;
      for (const node of entry.addedNodes) metrics.cardsAdded += countCards(node);
      for (const node of entry.removedNodes) metrics.cardsRemoved += countCards(node);
    }
  });
  mutation.observe(document, { childList:true, subtree:true });
  window.Telegram={WebApp:{initData:'isolated-navigation-fixture',platform:'ios',ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}},HapticFeedback:{impactOccurred(){},notificationOccurred(){}},safeAreaInset:{top:24,bottom:34},contentSafeAreaInset:{top:12,bottom:0}}};
}

async function scenario(browser, count) {
  const context = await browser.newContext({ viewport:{width:390,height:844}, isMobile:true, hasTouch:true });
  await context.addInitScript(instrumentation);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await context.route(/^https:/, route => route.fulfill({status:200, body:''}));
  const user={id:'navigation-user',telegram_id:77,first_name:'Проверка навигации',role:'user'};
  const wallet={available_balance:100,earned_balance:100,purchased_balance:0,bonus_balance:0,frozen_balance:0};
  const profile={user,wallet,active_listings:[],sold_listings:[],deals:[],deal_threads:[],conversations:[],wallet_transactions:[],withdrawals:[]};
  const timestamp = new Date().toISOString();
  const listings = kind => Array.from({length:count},(_,index)=>({id:`${kind}-${index}`,seller_id:'other',brand:index%2?'BMW':'Audi',model:`${kind} ${index}`,description:'Тестовые данные для измерения навигации',power_hp:300,max_speed_kph:240,price_af_coins:50+index,game_version:index%2?'car_parking_2':'car_parking_1',listing_type:kind,status:'active',images:['/api/media/navigation-photo'],pinned:index<2,pinned_until:index<2?new Date(Date.now()+86400000).toISOString():null,created_at:timestamp}));
  let regular=listings('regular'), unique=listings('unique');
  const requests=[];
  let delay=0, profileFailure=false, regularFailure=false, holdRegular=false;
  const heldRegular=[];
  let activeReads=0, maxActiveReads=0;
  const readPaths = endpoint => endpoint==='/profile' || endpoint==='/listings' || endpoint==='/training' || endpoint==='/training/mine' || endpoint==='/referrals' || endpoint.endsWith('/snapshot') || endpoint.endsWith('/mark-seen');
  const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==','base64');
  await context.route('**/api/**', async route => {
    const request=route.request(), url=new URL(request.url()), endpoint=url.pathname.slice(4);
    requests.push({endpoint,query:url.search,method:request.method(),at:Date.now()});
    if(endpoint==='/media/navigation-photo') return route.fulfill({status:200,contentType:'image/png',body:pixel});
    const isRead=readPaths(endpoint);
    if(isRead) {activeReads++;maxActiveReads=Math.max(maxActiveReads,activeReads);}
    try {
      if(delay && isRead) await wait(delay);
      if(holdRegular && endpoint==='/listings' && url.searchParams.get('type')==='regular')await new Promise(resolve=>heldRegular.push(resolve));
      let body=[], status=200;
      if(endpoint==='/me')body={user,wallet};
      else if(endpoint==='/profile') {body=profile; if(profileFailure){status=503;body={detail:'Isolated profile outage'};}}
      else if(endpoint==='/listings') {body=url.searchParams.get('type')==='unique'?unique:regular;if(regularFailure && url.searchParams.get('type')==='regular'){status=503;body={detail:'Isolated catalogue outage'};}}
      else if(endpoint==='/content/unique/snapshot')body={items:unique,marker:1};
      else if(endpoint==='/content/training/snapshot')body={items:[],marker:1};
      else if(endpoint.endsWith('/mark-seen'))body={unseen_count:0,marker:1};
      else if(endpoint==='/content/unseen')body={unique:{unseen_count:0,marker:1},training:{unseen_count:0,marker:1}};
      else if(endpoint==='/conversations/unread-summary')body={total_unread:0,conversations:[]};
      else if(endpoint==='/referrals')body={referralCode:'TEST62',referralUrl:'https://t.me/FixtureBot?startapp=TEST62',referralCount:0,referralLimit:20,commissionPercent:5,canInvite:true,milestones:[]};
      else if(endpoint==='/advertisement')body={is_active:false};
      else if(endpoint.match(/^\/listings\/[^/]+\/view$/))body={views_count:1,likes_count:0,liked_by_me:false};
      else if(endpoint.match(/^\/listings\/[^/]+$/))body=[...regular,...unique].find(item=>endpoint.endsWith('/'+item.id));
      await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)}).catch(error=>{
        if(!request.failure())throw error;
      });
    } finally {if(isRead)activeReads--;}
  });
  const dataCount=()=>requests.filter(item=>readPaths(item.endpoint)).length;
  const snapshot=async label=>({label,dataRequests:dataCount(),requests:requests.reduce((result,item)=>{if(readPaths(item.endpoint)){const key=item.endpoint+item.query;result[key]=(result[key]||0)+1;}return result;},{}),...await page.evaluate(()=>({...window.__catalogMetrics,nodes:document.querySelectorAll('*').length,cards:document.querySelectorAll('[data-listing-card]').length,heapBytes:performance.memory?.usedJSHeapSize||null,stableMarketCard:window.__firstMarketCard===document.querySelector('#marketCars [data-listing-card]')}))});
  const click=async view=>page.evaluate(view=>document.querySelector(`.bottom-nav [data-nav-target="${view}"]`).click(),view);
  const painted=async view=>{
    await page.waitForFunction(view=>!document.querySelector(`[data-view="${view}"]`).hidden,view);
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  };
  const settle=async()=>{await page.waitForFunction(()=>!document.querySelector('#startupStatus') || document.querySelector('#startupStatus').hidden);for(let attempt=0;attempt<40;attempt++){if(activeReads===0){await wait(50);if(activeReads===0)break;}await wait(30);}await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));};
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.waitForFunction(expected=>document.querySelectorAll('#marketCars [data-listing-card]').length===expected,count);
    await settle();
    await page.evaluate(()=>{window.__firstMarketCard=document.querySelector('#marketCars [data-listing-card]');});
    const checkpoints=[await snapshot('initial')], timings=[];
    const sequence=['profile','training','unique','more','market'];
    for(let index=0;index<50;index++){
      const view=sequence[index%sequence.length];
      const start=performance.now();await click(view);await painted(view);timings.push({view,paintMs:performance.now()-start});
      await settle();
      if([5,10,50].includes(index+1))checkpoints.push(await snapshot(`after${index+1}`));
    }
    assert.deepEqual(errors,[],'normal navigation has no uncaught JavaScript errors');
    assert.equal(await page.locator('.bottom-nav .is-active').getAttribute('data-nav-target'),'market');
    assert.equal(await page.locator('#marketCars [data-listing-card]').count(),count);
    // A fresh cached catalogue must survive slow profile data and a storm of clicks.
    delay=350;profileFailure=true;const beforeRapid=dataCount();
    await page.evaluate(()=>{for(let index=0;index<100;index++)document.querySelector(`.bottom-nav [data-nav-target="${['profile','training','unique','market'][index%4]}"]`).click();});
    await painted('market');
    await wait(500);await settle();
    const rapid={...await snapshot('rapid100'),dataRequests:dataCount()-beforeRapid,maxActiveReads};
    assert.equal(await page.locator('.bottom-nav .is-active').getAttribute('data-nav-target'),'market','late responses cannot change intended destination');
    assert.equal(await page.locator('[data-view=market]').isVisible(),true);
    assert.equal(await page.locator('#marketCars [data-listing-card]').count(),count,'outage retains cached catalogue');
    profileFailure=false;delay=0;
    const after=checkpoints.at(-1), initial=checkpoints[0];
    if(!baseline){
      assert(after.dataRequests-initial.dataRequests<=16,'50 cached switches must not repeat every catalogue/profile request');
      assert.equal(after.stableMarketCard,true,'unchanged listings keep the same DOM nodes across unrelated navigation');
      assert(after.cardsAdded-initial.cardsAdded<=count,'unrelated profile/content results must not recreate both catalogues');
      assert(after.listenersAdded-initial.listenersAdded<=12,'listeners must not grow per navigation');
      assert(after.observersActive<=2,'listing observers do not accumulate');
      assert(after.nodes<=initial.nodes+100,'DOM size remains bounded after navigation');
      assert(rapid.dataRequests<=6,'rapid delayed loads are deduplicated per data source');
    }
    const advanced=[];
    if(!baseline && count===100){
      // Run the real 12-second timeout/retry code using virtual time after measuring.
      await page.clock.install();
      regularFailure=true;profileFailure=true;
      await page.clock.fastForward(16000);
      await click('profile');await painted('profile');await click('market');await painted('market');
      await page.locator('#syncRetry').waitFor({state:'visible'});
      assert.equal(await page.locator('#marketCars [data-listing-card]').count(),count,'failed refresh retains cached listings');
      assert.equal(await page.locator('.bottom-nav .is-active').getAttribute('data-nav-target'),'market','profile failure does not block Market');
      regularFailure=false;profileFailure=false;
      await page.locator('#syncRetry').click();await page.locator('#syncStatus').waitFor({state:'hidden'});await settle();
      advanced.push('503 profile/catalogue outage -> retained cards -> retry recovery');
      holdRegular=true;
      await page.clock.fastForward(16000);
      await click('profile');await click('market');await painted('market');
      for(let attempt=0;attempt<40 && heldRegular.length<1;attempt++)await wait(20);
      assert(heldRegular.length>0,'stale catalogue request actually reached fixture');
      await click('training');await painted('training');await click('market');await painted('market');
      await page.clock.fastForward(13000);await wait(50);
      await page.clock.fastForward(700);await wait(50);
      await page.clock.fastForward(13000);await wait(100);
      await page.locator('#syncRetry').waitFor({state:'visible'});
      assert.equal(await page.locator('[data-view=market]').isVisible(),true,'timed-out request does not lock navigation');
      assert.equal(await page.locator('#marketCars [data-listing-card]').count(),count);
      holdRegular=false;heldRegular.splice(0).forEach(resolve=>resolve());await wait(100);
      await page.locator('#syncRetry').click();await page.locator('#syncStatus').waitFor({state:'hidden'});await settle();
      advanced.push('real request timeout + retry via virtual clock -> navigation/recovery');
      await page.locator('#marketGameFilter').selectOption('car_parking_1');
      await click('unique');await painted('unique');await page.locator('#uniqueGameFilter').selectOption('car_parking_2');
      regular=regular.filter(item=>item.id!=='regular-0');
      unique=unique.filter(item=>item.id!=='unique-1');
      await page.clock.fastForward(16000);
      await click('market');await painted('market');
      await page.waitForFunction(expected=>document.querySelectorAll('#marketCars [data-listing-card]').length===expected,count/2-1);
      await click('unique');await painted('unique');
      await page.waitForFunction(expected=>document.querySelectorAll('#uniqueCars [data-listing-card]').length===expected,count/2-1);
      assert.equal(await page.locator('#marketGameFilter').inputValue(),'car_parking_1');
      assert.equal(await page.locator('#uniqueGameFilter').inputValue(),'car_parking_2');
      await page.locator('#uniqueGameFilter').selectOption('');
      await click('market');await painted('market');await page.locator('#marketGameFilter').selectOption('');
      advanced.push('expired cache refresh removes sold listings and preserves independent game filters');
    }
    assert.equal(await page.locator('[data-view=market]').isVisible(),true);
    assert.equal(await page.locator('#marketCars [data-listing-card]').count(),regular.length);
    await page.locator('#marketCars [data-listing-card]').first().click();
    await page.locator('[data-view=listing-detail]').waitFor({state:'visible'});
    await click('market');await painted('market');
    assert.deepEqual(errors,[]);
    const report={mode:baseline?'baseline':'after',revision:baseline?revision:'worktree',perCatalogListings:count,totalCatalogueListings:count*2,checkpoints,rapid,advanced,marketPaintMs:timings.filter(item=>item.view==='market').map(item=>Math.round(item.paintMs*10)/10),allPaintMs:timings.map(item=>Math.round(item.paintMs*10)/10),fixtureNotes:'Real HTML/CSS/JavaScript in mobile Chromium. Isolated deterministic transport and Telegram shell. Read counts include listings/profile/training/referrals/content snapshot and mark-seen; exclude analytics,diagnostics,unread polling,images. No production/device/Telegram claim.'};
    fs.writeFileSync(path.join(evidence,`catalog-navigation-${baseline?'baseline':'after'}-${count}.json`),JSON.stringify(report,null,2));
    if(count===100)await page.screenshot({path:path.join(evidence,`catalog-navigation-${baseline?'baseline':'after'}-390.png`),animations:'disabled'});
    console.log(JSON.stringify({mode:report.mode,listingsPerCatalog:count,checkpoints:checkpoints.map(point=>({label:point.label,dataRequests:point.dataRequests,cardsAdded:point.cardsAdded,cardsRemoved:point.cardsRemoved,stableMarketCard:point.stableMarketCard,observersCreated:point.observersCreated,observersActive:point.observersActive,listenersAdded:point.listenersAdded,nodes:point.nodes})),rapidRequests:rapid.dataRequests,rapidMaxConcurrentReads:maxActiveReads,marketPaintMs:report.marketPaintMs,longTasks:after.longTasks.length}));
    return report;
  } catch(error) {
    console.error(JSON.stringify({browserErrors:errors,lastRequests:requests.slice(-12),startup:await page.locator('#startupStatus').innerText().catch(()=>''),marketCards:await page.locator('#marketCars [data-listing-card]').count()}));
    throw error;
  } finally {heldRegular.splice(0).forEach(resolve=>resolve());await context.close();}
}

(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({...process.env.CI?{}:{channel:'msedge'},headless:true});
  try {for(const count of (process.env.CATALOG_SIZES||'50,100,300,500').split(',').map(Number))await scenario(browser,count);}
  finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
