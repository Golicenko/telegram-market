// Real existing frontend in mobile Chromium, isolated API and Telegram transport.
// No production accounts, bot messages, reward claims or financial commands.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const root = path.resolve(__dirname, '..');
const evidence = path.join(__dirname, 'evidence/referral-reference');
const avatar = `<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><rect width="160" height="160" fill="#332944"/><circle cx="80" cy="57" r="29" fill="#c3b2dc"/><path d="M20 160c0-74 120-74 120 0" fill="#c3b2dc"/></svg>`;
const server = http.createServer((request, response) => {
  const pathname = new URL(request.url, 'http://fixture').pathname;
  if(pathname==='/referral-test-avatar.svg'){response.setHeader('Content-Type','image/svg+xml');return response.end(avatar);}
  if(pathname==='/referral-test-broken-avatar'){response.writeHead(404);return response.end();}
  const file=path.resolve(root,'.'+(pathname==='/'?'/index.html':pathname));
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||fs.statSync(file).isDirectory()){response.writeHead(404);return response.end();}
  response.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png','.jpg':'image/jpeg','.svg':'image/svg+xml','.webp':'image/webp','.woff2':'font/woff2'})[path.extname(file)]||'application/json');
  response.end(fs.readFileSync(file));
});
const wait=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));
const widths=(process.env.REFERRAL_WIDTHS||'320,360,375,390,414,430').split(',').map(Number);
const targets=[3,10,20], rewards=[10,15,50];

function installFixtures({width,reducedMotion}) {
  const state=window.__referralFixture={copies:[],shares:[],links:[],alerts:[],newCompletions:[],listeners:0,events:[],reducedMotion,copyMode:'api'};
  const add=EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener=function(...args){state.listeners++;return add.apply(this,args);};
  state.resizeObservers=0;
  if(window.ResizeObserver){const NativeResizeObserver=window.ResizeObserver;window.ResizeObserver=class extends NativeResizeObserver{constructor(callback){super(callback);state.resizeObservers++;}};}
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{async writeText(value){
    if(state.copyMode!=='api')throw Error('Isolated clipboard permission denial');
    state.copies.push(String(value));
  }}});
  document.execCommand=command=>{
    if(command!=='copy'||state.copyMode==='failed')return false;
    state.copies.push(document.activeElement.value);return true;
  };
  const position=()=>({y:scrollY,height:document.documentElement.scrollHeight,innerHeight,body:document.body?.style.cssText,fonts:document.fonts?.status,open:Boolean(document.getElementById('referralRewardModal')?.open)});
  state.scrollTrace=[];
  const trace=entry=>{state.scrollTrace.push({time:performance.now(),...entry,...position()});if(state.scrollTrace.length>80)state.scrollTrace.shift();};
  const scrollTo=window.scrollTo.bind(window);window.scrollTo=(...args)=>{trace({kind:'scrollTo',args});return scrollTo(...args);};
  window.addEventListener('scroll',()=>trace({kind:'scroll'}));
  document.addEventListener('wheel',event=>{const target=event.target?.tagName;setTimeout(()=>trace({kind:'wheel',target,clientX:event.clientX,clientY:event.clientY,cancelable:event.cancelable,prevented:event.defaultPrevented,delta:event.deltaY}),0);},{capture:true,passive:true});
  document.addEventListener('click',event=>{if(event.target.closest?.('[data-referral-milestone]')){state.beforeOpenScroll=scrollY;trace({kind:'activate'});}},true);
  window.Telegram={WebApp:{initData:'isolated-referral-reference-fixture',platform:width===375||width===414?'android':'ios',
    ready(){},expand(){},onEvent(name,handler){state.events.push({name,handler});},offEvent(){},
    BackButton:{show(){state.backVisible=true;},hide(){state.backVisible=false;},onClick(handler){state.backRegistrations=(state.backRegistrations||0)+1;state.back=handler;},offClick(){}},
    HapticFeedback:{impactOccurred(){},notificationOccurred(){}},
    isVersionAtLeast:()=>true,
    shareMessage(id,callback){state.shares.push(id);state.shareCallback=callback;},
    openTelegramLink(url){state.links.push(url);},
    safeAreaInset:{top:24,bottom:34},contentSafeAreaInset:{top:12,bottom:0}}};
  const animationStates=new WeakMap();
  new MutationObserver(records=>{
    for(const card of new Set(records.map(record=>record.target))){
      if(!card.matches?.('[data-referral-milestone]'))continue;
      const animated=card.classList.contains('is-newly-complete');
      if(animated&&animationStates.get(card)!==true)state.newCompletions.push(Number(card.dataset.referralMilestone));
      animationStates.set(card,animated);
    }
  }).observe(document,{subtree:true,attributes:true,attributeFilter:['class'],attributeOldValue:true});
}

async function scenario(browser,width,{failure=false}={}) {
  const reducedMotion=width===430;
  const context=await browser.newContext({viewport:{width,height:844},isMobile:true,hasTouch:true,reducedMotion:reducedMotion?'reduce':'no-preference'});
  await context.route(/^https:/,route=>route.fulfill({status:200,body:''}));
  await context.addInitScript(installFixtures,{width,reducedMotion});
  const page=await context.newPage();
  const errors=[],requests=[],financialWrites=[],imageRequests=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(request.resourceType()==='image')imageRequests.push(request.url());});
  const user={id:'referral-viewer',telegram_id:725123456,role:'user',first_name:'Александр',last_name:width===414?'ОченьДлиннаяФамилияДляПроверки':'Петров',username:width===320?null:'referral_fixture',photo_url:width===320?null:width===360?'/referral-test-broken-avatar':'/referral-test-avatar.svg'};
  let invited=0, completed=[false,false,false], balance=width===414?987654321.99:123.45;
  let summaryError=failure, summaryDelay=failure?450:0, shareError=0, summaryRequests=0, shareRequests=0, meRequests=0, navigationMetrics=null;
  const referralUrl='https://t.me/FixtureAutoFlowBot?startapp=Zz9pQ62A';
  const makeWallet=()=>({available_balance:balance,earned_balance:balance,purchased_balance:0,bonus_balance:0,frozen_balance:0});
  const summary=()=>({referralCode:'Zz9pQ62A',referralUrl,shareText:'Александр приглашает тебя в AutoFlow Market',referralCount:invited,referralLimit:20,commissionPercent:5,canInvite:invited<20,
    milestones:targets.map((count,index)=>({count,reward:rewards[index],completed:completed[index]}))});
  await context.route('**/api/**',async route=>{
    const request=route.request(),url=new URL(request.url()),endpoint=url.pathname.slice(4),method=request.method();
    requests.push({endpoint,method});
    const allowedWrites=['/analytics/events','/diagnostics/client','/referrals/share-message','/content/unique/mark-seen','/content/training/mark-seen'];
    if(!['GET','HEAD'].includes(method)&&!allowedWrites.includes(endpoint)){
      financialWrites.push({endpoint,method});return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Unexpected mutation in read-only referral fixture'})});
    }
    let body=[],status=200;
    if(endpoint==='/me'){meRequests++;body={user,wallet:makeWallet()};}
    else if(endpoint==='/profile')body={user,wallet:makeWallet(),active_listings:[],sold_listings:[],purchases:[],wallet_transactions:[],withdrawals:[],conversations:[],deal_threads:[]};
    else if(endpoint==='/referrals'){
      summaryRequests++;const payload=summary();if(summaryDelay)await wait(summaryDelay);
      status=summaryError?503:200;body=summaryError?{detail:'RAW INTERNAL ERROR NOT FOR USER'}:payload;
    }
    else if(endpoint==='/referrals/share-message'){shareRequests++;if(summaryDelay)await wait(summaryDelay);status=shareError||200;body=shareError?{detail:'RAW INTERNAL SHARE ERROR'}:{preparedMessageId:'prepared-referral-fixture'};}
    else if(endpoint==='/conversations/unread-summary')body={total_unread:0,conversations:[]};
    else if(endpoint==='/content/unseen')body={unique:{unseen_count:0,marker:1},training:{unseen_count:0,marker:1}};
    else if(endpoint.endsWith('/snapshot'))body={items:[],marker:1};
    else if(endpoint.endsWith('/mark-seen'))body={unseen_count:0,marker:1};
    else if(endpoint==='/advertisement')body={is_active:false};
    else if(endpoint==='/help/rules')body={publication:{enabled:true,free_limit:5,remaining:5,price_stars:7},af_per_star:1,car_seller_percent:100,withdrawal_fee_percent:30,withdrawal_hours:24,seller_response_hours:24,vip_cost_af:15,vip_hours:24,renewal_stars:10,renewal_hours:72};
    await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  });
  const more=page.locator('[data-view="more"]'),modal=page.locator('#referralRewardModal');
  const card=target=>more.locator(`[data-referral-milestone="${target}"]`);
  const backMore=async()=>{await page.locator('.bottom-nav [data-nav-target="more"]').click();await more.waitFor({state:'visible'});};
  const noOverflow=async()=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${width}px referral horizontal overflow`);
  const stableCards=async()=>assert(await page.evaluate(()=>window.__originalMilestoneCards.every((node,index)=>node===document.querySelectorAll('#referralMilestones [data-referral-milestone]')[index])),'backend updates preserve milestone DOM identity');
  const next=async(count,flags,serverBalance=balance)=>{
    invited=count;completed=[...flags];balance=serverBalance;
    await page.clock.fastForward(31000);
    await page.waitForFunction(({count,completed})=>document.getElementById('referralCount').textContent===String(count)&&[...document.querySelectorAll('#referralMilestones [data-referral-milestone]')].every((node,index)=>node.classList.contains('is-complete')===completed[index]),{count,completed});
    await page.waitForFunction(expected=>document.querySelector('.header-balance [data-balance]').textContent===expected,balance.toFixed(2));
    await stableCards();await noOverflow();
  };
  const assertClosed=async(source,beforeScroll)=>{
    await modal.waitFor({state:'hidden'});
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert.equal(await page.evaluate(()=>document.body.classList.contains('referral-reward-open')),false);
    assert.notEqual(await page.evaluate(()=>document.body.style.overflow),'hidden','body scrolling restored');
    assert.equal(await page.locator('dialog[open]').count(),0);
    assert.equal(await page.evaluate(()=>Boolean(window.__referralFixture.backVisible)),false,'native Back does not stay visible after the reward closes');
    if(source)assert(await source.evaluate(node=>document.activeElement===node),'focus returns to the opening card');
    if(beforeScroll!=null){
      const afterScroll=await page.evaluate(()=>scrollY),drift=Math.abs(afterScroll-beforeScroll);
      assert(drift<=2,'modal close restores page scroll');
    }
  };
  const openReward=async(target,close='understood',takeScreenshot=false)=>{
    const source=card(target),index=targets.indexOf(target),reward=rewards[index];
    await source.scrollIntoViewIfNeeded();await source.focus();
    const beforeScroll=await page.evaluate(()=>scrollY),readsBefore=summaryRequests;
    if(invited===1&&target===10&&close==='understood')await source.locator('.referral-milestone__arrow').click();
    else await source.click();
    await modal.waitFor({state:'visible'});
    const activationScroll=await page.evaluate(()=>window.__referralFixture.beforeOpenScroll);
    const rect=await modal.boundingBox();assert(rect.x>=0&&rect.x+rect.width<=width+1&&rect.y>=0&&rect.y+rect.height<=844,'reward modal fits viewport');
    assert.match(await page.locator('#referralRewardTitle').textContent(),completed[index]?/Награда получена/:new RegExp(`Награда\\s+${reward}\\s+AF`));
    const description=await page.locator('#referralRewardDescription').textContent();
    const remaining=Math.max(0,target-invited);
    if(completed[index])assert.match(description,new RegExp(`${reward}\\s+AF.*начислен`));
    else if(remaining===0){assert.match(description,/ожидаем|подтвержден/iu);assert.doesNotMatch(description,/уже начислены/iu);}
    else assert.match(description,new RegExp(`ещё\\s+${remaining}\\s+${remaining===1?'друга':'друзей'}`),'remaining invitation count uses the accusative friend form');
    assert.match(await page.locator('#referralRewardProgressLabel').textContent(),new RegExp(`${Math.min(invited,target)}\\s+из\\s+${target}`));
    await page.waitForFunction(expected=>document.getElementById('referralRewardProgress').value===expected,Math.min(invited,target));
    assert.equal(await page.locator('#referralRewardProgress').evaluate(node=>node.max),target);
    assert.equal(await page.locator('#referralRewardProgress').evaluate(node=>node.value),Math.min(invited,target));
    assert.equal(summaryRequests,readsBefore,'viewing reward details never calls a reward claim API');
    assert.equal(await page.evaluate(()=>getComputedStyle(document.body).overflow),'hidden');
    const scroll=await page.evaluate(()=>scrollY);await page.mouse.wheel(0,200);await wait(30);assert.equal(await page.evaluate(()=>scrollY),scroll,'modal locks background scroll');
    if(invited===1&&target===3){
      const backdrop=await modal.evaluate(node=>{const css=getComputedStyle(node,'::backdrop');return{background:css.backgroundColor,blur:css.backdropFilter,supported:CSS.supports('backdrop-filter','blur(2px)')};});
      assert(!['transparent','rgba(0, 0, 0, 0)'].includes(backdrop.background),'reward backdrop visibly dims the app');
      if(backdrop.supported)assert.match(backdrop.blur,/blur\(/,'supported WebViews blur the modal backdrop');
    }
    if(invited===1&&target===3&&close==='x'){
      await page.keyboard.press('Shift+Tab');assert(await modal.locator('[data-close-referral-reward]').last().evaluate(node=>node===document.activeElement));
      await page.keyboard.press('Tab');assert(await modal.locator('[data-close-referral-reward]').first().evaluate(node=>node===document.activeElement));
    }
    if(takeScreenshot){
      await page.waitForFunction(()=>{const dialog=document.getElementById('referralRewardModal');return Number(getComputedStyle(dialog).opacity)===1&&Number(getComputedStyle(dialog,'::backdrop').opacity)===1;});
      await page.screenshot({path:path.join(evidence,`referral-modal-${invited}-of-${target}-${width}.png`),animations:'disabled'});
    }
    if(close==='x')await modal.locator('[data-close-referral-reward]').first().click();
    else if(close==='backdrop')await page.mouse.click(3,40);
    else if(close==='escape')await page.keyboard.press('Escape');
    else if(close==='native')await page.evaluate(()=>window.__referralFixture.back());
    else await modal.locator('[data-close-referral-reward]').last().click();
    try{await assertClosed(source,activationScroll??beforeScroll);}catch(error){console.error(JSON.stringify({modalScrollFailure:{count:invited,target,close,beforeClick:beforeScroll,activation:activationScroll,after:await page.evaluate(()=>scrollY)},trace:await page.evaluate(()=>window.__referralFixture.scrollTrace.slice(-20))}));throw error;}
  };
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}/?view=more`);
    await more.waitFor({state:'visible'});
    if(failure){
      await page.locator('#referralRetry').waitFor({state:'visible'});
      assert.equal(await page.locator('#referralContent').isVisible(),false);
      assert.doesNotMatch(await page.locator('#referralStatus').textContent(),/RAW|INTERNAL/);
      summaryError=false;
      await page.locator('#referralRetry').click();await page.locator('#referralContent').waitFor({state:'visible'});
      const reads=summaryRequests;
      await page.evaluate(()=>{for(let index=0;index<80;index++)document.querySelector(`.bottom-nav [data-nav-target="${['market','more','profile','more'][index%4]}"]`).click();});
      await more.waitFor({state:'visible'});await wait(600);
      assert(summaryRequests<=reads+1,'slow loads remain single-flight across rapid tabs');
      assert.equal(await page.locator('#referralCount').textContent(),'0');
      assert.deepEqual(errors,[]);assert.deepEqual(financialWrites,[]);
      console.log(`PASS ${width}px: referral slow/error/retry and rapid navigation recovery`);return;
    }
    await page.locator('#referralContent').waitFor({state:'visible'});
    await page.evaluate(()=>document.fonts.ready);
    await page.waitForFunction(()=>document.querySelectorAll('#referralMilestones [data-referral-milestone]').length===3);
    await page.evaluate(()=>{window.__originalMilestoneCards=[...document.querySelectorAll('#referralMilestones [data-referral-milestone]')];});
    assert.equal(await page.locator('.referral-milestone.is-newly-complete').count(),0,'initial render never replays a paid reward animation');
    assert.equal(await page.locator('#referralCount').textContent(),'0');
    assert.deepEqual(await more.locator('.referral-milestone__title').allTextContents(),['3 друга','10 друзей','20 друзей']);
    assert.equal(await page.locator('#referralPercent').textContent(),'5%');
    assert.equal(await page.locator('#referralUrl').inputValue(),referralUrl);
    assert.equal(await page.locator('.bottom-nav').count(),1);
    assert.deepEqual(await page.locator('.bottom-nav button').evaluateAll(nodes=>nodes.map(node=>node.dataset.navTarget)),['unique','training','market','profile','more']);
    assert.equal(await page.locator('.bottom-nav [aria-current="page"]').getAttribute('data-nav-target'),'more');
    assert.equal(await page.locator('#headerAvatarName').textContent(),[user.first_name,user.last_name].join(' '));
    assert.equal(await page.locator('#headerAvatarName').isVisible(),true);
    for(const selector of ['#appHeader','#infoButton','.header-balance','#referralHeaderTopup']){
      const box=await page.locator(selector).boundingBox();
      assert(box.x>=0&&box.x+box.width<=width+1,`${width}px ${selector} is not clipped beyond the screen`);
    }
    assert(await page.evaluate(()=>{
      const name=document.getElementById('headerAvatarName').getBoundingClientRect(),wallet=document.querySelector('.header-balance').getBoundingClientRect();
      return name.bottom<=wallet.top||name.top>=wallet.bottom||name.right<=wallet.left-2;
    }),'long header identity never extends behind the wallet');
    const banner=page.locator('#referralBannerImage');await banner.evaluate(image=>image.decode());
    assert.equal(await banner.isVisible(),true,'dedicated banner asset is visible in More');
    assert(['cover','contain'].includes(await banner.evaluate(image=>getComputedStyle(image).objectFit)),'banner preserves image proportions');
    const bannerUrl=await banner.evaluate(image=>image.currentSrc),bannerReads=imageRequests.filter(url=>url===bannerUrl).length;
    if(width===320||width===360)await page.waitForFunction(()=>document.getElementById('headerAvatarImage').hidden&&!document.getElementById('headerAvatarFallback').hidden);
    else {await page.locator('#headerAvatarImage').evaluate(image=>image.decode());assert.equal(await page.locator('#headerAvatarImage').isVisible(),true);}
    const milestoneBoxes=await more.locator('[data-referral-milestone]').evaluateAll(nodes=>nodes.map(node=>{const rect=node.getBoundingClientRect();return{x:rect.x,y:rect.y,width:rect.width,height:rect.height};}));
    assert(Math.max(...milestoneBoxes.map(rect=>rect.height))-Math.min(...milestoneBoxes.map(rect=>rect.height))<=1,'milestones have equal height');
    assert(Math.max(...milestoneBoxes.map(rect=>rect.y))-Math.min(...milestoneBoxes.map(rect=>rect.y))<=1,'three milestone cards stay on one row');
    milestoneBoxes.forEach(rect=>assert(rect.width>=44&&rect.height>=44&&rect.x>=0&&rect.x+rect.width<=width+1));
    await noOverflow();
    await page.clock.install();
    for(const target of targets)await openReward(target);
    await next(1,[false,false,false]);
    await page.evaluate(()=>window.scrollTo(0,0));await wait(400);
    await page.screenshot({path:path.join(evidence,`referral-count-1-${width}.png`),animations:'disabled'});
    await page.screenshot({path:path.join(evidence,`referral-count-1-${width}-full.png`),fullPage:true,animations:'disabled'});
    await openReward(3,'x');await openReward(10,'understood');await openReward(20,'backdrop');await openReward(3,'escape');await openReward(10,'native');
    if(width===414)for(let index=0;index<6;index++)await openReward(targets[index%3],index%2?'escape':'backdrop');
    const copy=more.locator('.referral-actions [data-copy-referral]');
    await copy.click();await page.waitForFunction(()=>window.__referralFixture.copies.length===1);
    assert.deepEqual(await page.evaluate(()=>window.__referralFixture.copies),[referralUrl]);assert.match(await page.locator('#toast').textContent(),/Ссылка скопирована/);
    await page.waitForFunction(()=>document.querySelector('[data-copy-referral].is-copied'));
    await page.clock.fastForward(1700);assert.equal(await more.locator('[data-copy-referral].is-copied').count(),0,'copy success state clears after its short timeout');
    await page.evaluate(()=>window.__referralFixture.copyMode='fallback');
    await more.locator('.referral-link-row [data-copy-referral]').click();await page.waitForFunction(()=>window.__referralFixture.copies.length===2);
    assert.deepEqual(await page.evaluate(()=>window.__referralFixture.copies),[referralUrl,referralUrl]);
    await page.evaluate(()=>window.__referralFixture.copyMode='failed');await copy.click();
    await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('Не удалось скопировать'));
    assert.doesNotMatch(await page.locator('#toast').textContent(),/Ссылка скопирована/);assert.equal(await page.evaluate(()=>window.__referralFixture.copies.length),2);
    assert.equal(await more.locator('[data-copy-referral].is-copied').count(),0,'a failed copy must not keep a stale success check');
    await page.locator('#referralShare').evaluate(button=>{button.click();button.click();});
    await page.waitForFunction(()=>window.__referralFixture.shares.length===1);assert.equal(shareRequests,1);
    assert.equal(await page.locator('#referralShare').isDisabled(),true);
    await page.evaluate(()=>window.__referralFixture.shareCallback(false));await page.waitForFunction(()=>!document.getElementById('referralShare').disabled);
    assert.deepEqual(await page.evaluate(()=>window.__referralFixture.links),[]);
    await page.locator('#referralShare').click();await page.waitForFunction(()=>window.__referralFixture.shares.length===2);
    assert.deepEqual(await page.evaluate(()=>window.__referralFixture.shares),['prepared-referral-fixture','prepared-referral-fixture']);
    await page.evaluate(()=>window.__referralFixture.shareCallback(true));await page.waitForFunction(()=>!document.getElementById('referralShare').disabled);
    shareError=502;await page.locator('#referralShare').click();await page.waitForFunction(()=>!document.getElementById('referralShare').disabled);
    assert.match(await page.locator('#toast').textContent(),/Не удалось открыть пересылку/);assert.doesNotMatch(await page.locator('#toast').textContent(),/RAW|INTERNAL/);shareError=0;
    const beforeOld=shareRequests;await page.evaluate(()=>window.Telegram.WebApp.isVersionAtLeast=()=>false);await page.locator('#referralShare').click();
    assert.match(await page.locator('#toast').textContent(),/Обновите Telegram/);assert.equal(shareRequests,beforeOld);
    await page.evaluate(()=>{window.Telegram.WebApp.isVersionAtLeast=()=>true;delete window.Telegram.WebApp.shareMessage;});await page.locator('#referralShare').click();
    assert.match(await page.locator('#toast').textContent(),/Обновите Telegram/);assert.equal(shareRequests,beforeOld);
    assert.deepEqual(await page.evaluate(()=>window.__referralFixture.links),[]);
    await next(1,[false,false,false],width===414?987654876.54:321.09); // Commission/other server wallet changes can happen without a new friend.
    const headerTopup=page.locator('#referralHeaderTopup');
    await headerTopup.scrollIntoViewIfNeeded();
    assert.equal(await headerTopup.evaluate(button=>button.tagName),'BUTTON','More topup is a real keyboard-focusable button');
    assert.equal(await headerTopup.evaluate(button=>Boolean(button.parentElement.closest('button'))),false,'topup never nests a button in the wallet button');
    assert(await headerTopup.evaluate(button=>{const box=button.getBoundingClientRect();return box.width>=44&&box.height>=44&&button===document.elementFromPoint(box.x+box.width/2,box.y+box.height/2);}),'+ is a visible unobstructed44px touch target');
    await headerTopup.focus();await page.keyboard.press('Enter');await page.locator('[data-view="topup"]').waitFor({state:'visible'});
    await page.locator('[data-view="topup"] [data-back]').click();await more.waitFor({state:'visible'});
    await page.locator('.header-balance [data-balance]').click();await page.locator('[data-view="wallet"]').waitFor({state:'visible'});
    await page.clock.fastForward(500); // Respect the existing double-Back guard between distinct user flows.
    await page.locator('[data-view="wallet"] [data-back]').click();await more.waitFor({state:'visible'});
    await page.locator('#infoButton').click();await page.locator('[data-view="help"]').waitFor({state:'visible'});
    await page.waitForFunction(()=>document.getElementById('help-referrals').open);
    assert.equal(await page.locator('#help-referrals').evaluate(node=>node.open),true,'Information opens existing referral help article');
    await page.clock.fastForward(500);
    await page.evaluate(()=>window.__referralFixture.back());await more.waitFor({state:'visible'});
    const beforeNav=summaryRequests,listeners=await page.evaluate(()=>window.__referralFixture.listeners),nativeBackRegistrations=await page.evaluate(()=>window.__referralFixture.backRegistrations),resizeObservers=await page.evaluate(()=>window.__referralFixture.resizeObservers);
    await page.evaluate(()=>{for(let index=0;index<80;index++)document.querySelector(`.bottom-nav [data-nav-target="${['market','more','profile','more'][index%4]}"]`).click();});
    await more.waitFor({state:'visible'});await wait(100);await stableCards();
    assert(summaryRequests<=beforeNav+1,'cached repeated tabs do not multiply summary reads');
    assert(await page.evaluate(()=>window.__referralFixture.listeners)<=listeners+5,'handlers do not accumulate on repeated tab visits');
    assert.equal(await page.evaluate(()=>window.__referralFixture.backRegistrations),nativeBackRegistrations,'native Back handler is not registered on repeated tab visits');
    assert.equal(await page.evaluate(()=>window.__referralFixture.resizeObservers),resizeObservers,'header ResizeObserver is reused instead of created on each tab visit');
    assert.equal(await more.evaluate(node=>node.classList.contains('is-first-open')),false,'returning to More does not replay the initial entrance animation');
    navigationMetrics={switches:80,summaryReads:summaryRequests-beforeNav,addedListeners:(await page.evaluate(()=>window.__referralFixture.listeners))-listeners,addedNativeBackHandlers:(await page.evaluate(()=>window.__referralFixture.backRegistrations))-nativeBackRegistrations,addedResizeObservers:(await page.evaluate(()=>window.__referralFixture.resizeObservers))-resizeObservers};
    assert.equal(imageRequests.filter(url=>url===bannerUrl).length,bannerReads,'tab navigation reuses the existing banner image');
    await openReward(3);
    await card(3).click();await modal.waitFor({state:'visible'});
    await page.evaluate(()=>document.querySelector('.bottom-nav [data-nav-target="profile"]').click());await page.locator('[data-view="profile"]').waitFor({state:'visible'});await assertClosed();await backMore();
    const states=[{count:2,flags:[false,false,false]},{count:3,flags:[false,false,false]},{count:3,flags:[true,false,false],earned:3},
      {count:8,flags:[true,false,false]},{count:10,flags:[true,false,false]},{count:10,flags:[true,true,false],earned:10},
      {count:17,flags:[true,true,false]},{count:20,flags:[true,true,false]},{count:20,flags:[true,true,true],earned:20},{count:25,flags:[true,true,true]}];
    for(const state of states){
      const animationsBefore=await page.evaluate(()=>window.__referralFixture.newCompletions.length);
      if(width===390&&state.earned){await card(state.earned).click();await modal.waitFor({state:'visible'});assert.match(await page.locator('#referralRewardDescription').textContent(),/Ожидаем подтверждения/);}
      await next(state.count,state.flags,state.earned?432.10+state.earned:balance);
      if(width===390&&state.earned){assert.match(await page.locator('#referralRewardDescription').textContent(),/уже начислены/);await modal.locator('[data-close-referral-reward]').last().click();await assertClosed(card(state.earned));}
      const animations=await page.evaluate(start=>window.__referralFixture.newCompletions.slice(start),animationsBefore);
      assert.deepEqual(animations,reducedMotion||!state.earned?[]:[state.earned],'only a new backend-confirmed reward animates');
      assert.equal(await more.locator('.referral-milestone.is-complete').count(),state.flags.filter(Boolean).length);
      for(const target of targets)await openReward(target,'understood',width===390&&state.count===8&&target===10);
      const filters=await more.locator('.referral-milestone__content').evaluateAll(nodes=>nodes.map(node=>getComputedStyle(node).filter));
      state.flags.forEach((received,index)=>assert.equal(/blur\((?!0px)/.test(filters[index]),received,'only backend-confirmed card content is blurred'));
      if(state.count===3&&state.earned){
        await wait(550);await page.evaluate(()=>window.scrollTo(0,0));
        await page.screenshot({path:path.join(evidence,`referral-confirmed-3-${width}.png`),animations:'disabled'});
        await page.screenshot({path:path.join(evidence,`referral-confirmed-3-${width}-full.png`),fullPage:true,animations:'disabled'});
      }
    }
    assert.equal(await page.locator('#referralCount').textContent(),'25','main counter is never clamped to20');
    assert.equal(await page.locator('#referralShare').isDisabled(),true,'backend invitation limit remains authoritative');
    for(const button of await more.locator('[data-copy-referral]').all())assert.equal(await button.isDisabled(),true);
    assert.equal(await page.locator('#referralPercent').textContent(),'5%','commission display remains present after invitation cap');
    if(reducedMotion)assert(await more.locator('.referral-milestone__check').evaluateAll(nodes=>nodes.every(node=>getComputedStyle(node).animationName==='none'||getComputedStyle(node).animationDuration.split(',').every(duration=>parseFloat(duration)===0))),'reduced motion suppresses reward check animation');
    summaryError=true;await page.clock.fastForward(31000);await page.locator('#referralRetry').waitFor({state:'visible'});
    assert.equal(await page.locator('#referralContent').isVisible(),true,'later network failures retain rendered server data');
    assert.equal(await page.locator('#referralCount').textContent(),'25');
    assert.doesNotMatch(await page.locator('#referralStatus').textContent(),/RAW|INTERNAL/);
    summaryError=false;await page.locator('#referralRetry').click();await page.locator('#referralRetry').waitFor({state:'hidden'});
    await page.reload();await page.waitForFunction(()=>document.getElementById('referralCount').textContent==='25');
    assert.equal(await more.locator('.referral-milestone.is-complete').count(),3);assert.equal(await more.locator('.is-newly-complete').count(),0,'reload never replays earned rewards');
    await noOverflow();assert.deepEqual(errors,[]);assert.deepEqual(financialWrites,[]);
    fs.writeFileSync(path.join(evidence,`referral-${width}.json`),JSON.stringify({width,reducedMotion,summaryRequests,shareRequests,meRequests,navigationMetrics,counts:[0,1,2,3,8,10,17,20,25],milestoneBoxes,
      notes:'Mobile Chromium and Telegram shell fixture only. Real Telegram clients, actual native share delivery and financial operations are not exercised.'},null,2));
    console.log(`PASS ${width}px:0/1/2/3/8/10/17/20/25, backendpending/completed, progress/grammar, five modal close paths, copy/native share, real header, stable navigation, reduced motion=${reducedMotion}`);
  }catch(error){console.error(JSON.stringify({width,failure,errors,financialWrites,lastRequests:requests.slice(-12)}));await page.screenshot({path:path.join(evidence,`referral-failure-${width}.png`),fullPage:true}).catch(()=>{});throw error;}
  finally{await context.close();}
}

(async()=>{
  fs.mkdirSync(evidence,{recursive:true});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({...(process.env.CI?{}:{channel:'msedge'}),headless:true});
  try{
    // Each width owns its context, routes, SDK state and evidence filenames.
    // Settle both before closing the browser, including when one width fails.
    for(let index=0;index<widths.length;index+=2){
      const results=await Promise.allSettled(widths.slice(index,index+2).map(width=>scenario(browser,width)));
      const failure=results.find(result=>result.status==='rejected');
      if(failure)throw failure.reason;
    }
    if(process.env.REFERRAL_SKIP_FAILURE!=='1')await scenario(browser,390,{failure:true});
  }
  finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
