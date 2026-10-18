// Existing frontend in a real mobile browser, with isolated HTTP/Telegram fixtures.
// Opening existing flows is verified; no purchase, payout, pin or delete is submitted.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const root = path.resolve(__dirname, '..');
const evidence = path.join(__dirname, 'evidence/profile-reference');
const carSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400"><rect width="640" height="400" fill="#14283c"/><path fill="#8aa5bd" d="M45 258l85-37 62-12 63-63h146l67 65 85 27 30 64H45z"/><path fill="#07131f" d="M219 205l48-48h54v48zm115-48h55l48 48H334z"/><g fill="#06101c" stroke="#35516b" stroke-width="9"><circle cx="157" cy="302" r="36"/><circle cx="477" cy="302" r="36"/></g><text x="320" y="370" text-anchor="middle" font-family="sans-serif" font-size="17" fill="#aac2d6">ТЕСТОВАЯ ФОТОГРАФИЯ</text></svg>`;
const avatarSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><rect width="160" height="160" fill="#153b58"/><circle cx="80" cy="58" r="30" fill="#9fc4dd"/><path d="M23 156c1-68 113-68 114 0" fill="#9fc4dd"/></svg>`;
const server = http.createServer((request, response) => {
  const pathname = new URL(request.url, 'http://fixture').pathname;
  if (pathname === '/profile-test-car.svg' || pathname === '/profile-test-avatar.svg') {
    response.setHeader('Content-Type', 'image/svg+xml');
    return response.end(pathname.includes('avatar') ? avatarSvg : carSvg);
  }
  if (pathname === '/profile-test-broken-avatar') { response.writeHead(404); return response.end(); }
  const file = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { response.writeHead(404); return response.end(); }
  response.setHeader('Content-Type', ({ '.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.jpg':'image/jpeg', '.png':'image/png' })[path.extname(file)] || 'application/json');
  response.end(fs.readFileSync(file));
});
const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const widths = (process.env.PROFILE_WIDTHS || '320,360,375,390,414,430').split(',').map(Number);
const roles = (process.env.PROFILE_ROLES || 'user,admin').split(',');

async function profileScenario(browser, { width, role, slow = false }) {
  const context = await browser.newContext({ viewport:{ width, height:844 }, isMobile:true, hasTouch:true });
  await context.route(/^https:/, route => route.fulfill({ status:200, body:'' }));
  await context.addInitScript(({ platform, fallbackCopy, relativeApi }) => {
    if(relativeApi)window.AUTO_FLOW_API_BASE='/api';
    const metrics = window.__profileFixture = { copies:[], confirms:[], listeners:0 };
    const nativeAdd = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function(...args) { metrics.listeners++; return nativeAdd.apply(this, args); };
    Object.defineProperty(navigator, 'clipboard', { configurable:true, value:{ async writeText(value) {
      if (fallbackCopy) throw Error('Isolated WebView clipboard denial');
      metrics.copies.push(String(value));
    } } });
    const nativeCommand = document.execCommand.bind(document);
    document.execCommand = function(command, ...args) {
      if (command === 'copy') { metrics.copies.push(document.activeElement.value); return true; }
      return nativeCommand(command, ...args);
    };
    window.Telegram = { WebApp:{ initData:'isolated-profile-reference-fixture', platform,
      ready(){}, expand(){}, onEvent(){}, offEvent(){},
      showConfirm(message, callback){ metrics.confirms.push(message); callback(false); },
      BackButton:{ show(){}, hide(){}, onClick(){}, offClick(){} },
      HapticFeedback:{ impactOccurred(){}, notificationOccurred(){} },
      safeAreaInset:{ top:24, bottom:34 }, contentSafeAreaInset:{ top:12, bottom:0 } } };
  }, { platform:width%2 ? 'android' : 'ios', fallbackCopy:width===320, relativeApi:slow });
  const page = await context.newPage();
  const errors = [], requests = [], forbiddenWrites = [];
  page.on('pageerror', error => errors.push(error.message));
  const long = width===320 || width===414;
  const missing = width===320;
  const broken = width===360;
  const user = { id:'profile-owner', telegram_id:1234567890123,
    first_name:long ? 'Александр-Константин' : 'Александр', last_name:long ? 'ПроверкаОченьДлиннойФамилии' : 'Петров',
    username:missing ? null : width===414 ? 'long_username_for_profile_layout' : 'autoflow_fixture',
    photo_url:missing ? null : broken ? '/profile-test-broken-avatar' : '/profile-test-avatar.svg', role };
  const available = width===414 ? 1234567890.12 : 1324.74;
  const wallet = { available_balance:available, earned_balance:available, purchased_balance:0, bonus_balance:0, frozen_balance:25, total_earned:available };
  const created = '2026-10-19T10:00:00Z';
  const base = { seller_id:user.id, description:'Настоящие тестовые данные существующего API', power_hp:700, max_speed_kph:390, price_af_coins:123.45,
    listing_type:'regular', status:'active', images:['/profile-test-car.svg'], created_at:created, pinned:false, delivery_time_estimate:'up_to_1h' };
  const active = Array.from({ length:17 }, (_, index) => ({ ...base, id:`owned-${index}`, brand:index%2 ? 'Mercedes-Benz' : 'BMW',
    model:index===0 ? 'M5 F90 Competition Edition с длинным названием автомобиля' : index%2 ? 'AMG GT63 S' : 'M5 F90',
    game_version:index%2 ? 'car_parking_2' : 'car_parking_1', pinned:index===1, pinned_until:index===1 ? '2099-10-19T10:00:00Z' : null }));
  active[0].images=['/api/media/00000000-0000-4000-8000-000000000001','/api/media/00000000-0000-4000-8000-000000000002'];
  if(slow)active.at(-1).images=['http://[invalid'];
  const sold = [0,1].map(index => ({ ...active[index], id:`sold-${index}`, status:'sold' }));
  const thread = { id:'profile-thread', buyer_id:user.id, seller_id:'counterparty', listing:{ ...active[0], seller_id:'counterparty' },
    deal:{ id:'profile-deal', status:'paid', price_af_coins:50 }, counterparty:{ name:'Продавец', username:null }, created_at:created, unread_count:2 };
  const conversation = { id:'profile-dialog', counterparty:{name:'Обычный диалог',username:null,photo_url:null}, last_message:'Сообщение для проверки', last_message_at:created };
  const profile = { user, wallet, active_listings:active, sold_listings:sold, purchases:[], active_deals:[], deals:[], deal_threads:[thread], conversations:[conversation],
    wallet_transactions:[{ id:'history-1', type:'sale_income', amount:50, created_at:created }], withdrawals:[] };
  const rules={ publication:{enabled:true,free_limit:5,remaining:0,price_stars:7},af_per_star:1,car_seller_percent:100,withdrawal_fee_percent:30,withdrawal_hours:24,seller_response_hours:24,vip_cost_af:15,vip_hours:24,renewal_stars:10,renewal_hours:72 };
  let profileRequests=0, quotes=0;
  await context.route('**/api/**', async route => {
    const request=route.request(), url=new URL(request.url()), endpoint=url.pathname.slice(4), method=request.method();
    requests.push({endpoint,method});
    if(endpoint.startsWith('/media/'))return route.fulfill({status:200,contentType:'image/svg+xml',body:carSvg});
    if (!['GET','HEAD'].includes(method) && !['/analytics/events','/diagnostics/client','/content/unique/mark-seen','/content/training/mark-seen'].includes(endpoint) && !/^\/listings\/[^/]+\/view$/.test(endpoint)) {
      forbiddenWrites.push({endpoint,method});
      return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'This isolated test must not mutate money or listings'})});
    }
    let body=[], status=200;
    if(endpoint==='/me')body={user,wallet};
    else if(endpoint==='/profile'){profileRequests++;if(slow)await wait(500);body=profile;}
    else if(endpoint==='/listings')body=url.searchParams.get('type')==='unique'?[]:active;
    else if(endpoint.endsWith('/view'))body={views_count:1,likes_count:0,liked_by_me:false};
    else if(endpoint.startsWith('/listings/'))body=[...active,...sold].find(item=>endpoint.endsWith('/'+item.id));
    else if(endpoint==='/vip/quote'){quotes++;body={cost_af:15,duration_hours:24,balance_af:15,stars:0,af_per_star:1,rounding_credit_af:0};}
    else if(endpoint==='/publication-rules')body={...rules.publication,payment_required:true};
    else if(endpoint==='/uploads/policy')body={max_bytes:67108864,source_max_bytes:67108864,max_pixels:64000000,max_files:10};
    else if(endpoint==='/help/rules')body=rules;
    else if(endpoint==='/content/unseen')body={unique:{unseen_count:0,marker:1},training:{unseen_count:0,marker:1}};
    else if(endpoint.endsWith('/snapshot'))body={items:[],marker:1};
    else if(endpoint.endsWith('/mark-seen'))body={unseen_count:0,marker:1};
    else if(endpoint==='/conversations/unread-summary')body={total_unread:2,conversations:[{conversation_id:thread.id,conversation_type:'deal',unread_count:2}]};
    else if(endpoint==='/support/categories')body=[{key:'other',label:'Другой вопрос',icon:'💬',deal_related:false}];
    else if(endpoint==='/admin/overview')body={from_utc:created,until_utc_exclusive:'2026-10-20T10:00:00Z',timezone:'Europe/Bratislava',metrics:{new_users:1},pending_now:{withdrawals:0},definitions:{new_users:'Тестовая метрика'}};
    else if(endpoint==='/advertisement')body={is_active:false};
    else if(endpoint.startsWith('/admin/') && role!=='admin'){status=403;body={detail:'Forbidden'};}
    await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  });
  const profileView=page.locator('[data-view="profile"]');
  const returnProfile=async()=>{await page.locator('.bottom-nav [data-nav-target="profile"]').click();await profileView.waitFor({state:'visible'});};
  const view=async name=>page.locator(`[data-view="${name}"]`).waitFor({state:'visible'});
  const noOverflow=async()=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${role} ${width}px has horizontal overflow`);
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}/?view=profile`);
    await profileView.waitFor({state:'visible'});
    if(slow){
      await page.evaluate(()=>{for(let index=0;index<40;index++)document.querySelector(`.bottom-nav [data-nav-target="${['market','unique','training','profile'][index%4]}"]`).click();});
      assert.equal(await profileView.isVisible(),true,'slow profile cannot block the intended final screen');
    }
    await page.waitForFunction(()=>document.getElementById('activeCount').textContent==='17');
    assert.equal(await profileView.locator('#profileName').textContent(),[user.first_name,user.last_name].join(' '));
    assert.equal(await profileView.locator('#profileName').getAttribute('title'),[user.first_name,user.last_name].join(' '),'full name stays available when visually clamped');
    assert(await profileView.locator('#profileName').evaluate(node=>node.getBoundingClientRect().height<=parseFloat(getComputedStyle(node).lineHeight)*3+1),'long identity uses at most three visible lines');
    assert.equal(await profileView.locator('#profileUsername').textContent(),user.username?'@'+user.username:'Username не указан');
    assert.equal(await profileView.locator('#profileUsername').getAttribute('title'),user.username?'@'+user.username:'Username не указан');
    assert((await profileView.locator('#profileTelegramId').textContent()).includes(String(user.telegram_id)));
    const idRange=await profileView.locator('#profileTelegramId').evaluate(node=>{
      const text=node.firstChild, start=text.textContent.indexOf('\n')+1, range=document.createRange();
      range.setStart(text,start);range.setEnd(text,text.textContent.length);
      return [...range.getClientRects()].filter(rect=>rect.width>0).map(rect=>({x:rect.x,y:rect.y,width:rect.width,height:rect.height}));
    });
    assert.equal(new Set(idRange.map(rect=>Math.round(rect.y))).size,1,'Telegram ID value stays on one physical line');
    assert.equal(await profileView.locator('[data-balance]').textContent(),available.toFixed(2));
    if(available<1000000)assert(await profileView.locator('[data-balance]').evaluate(node=>node.getBoundingClientRect().height<=parseFloat(getComputedStyle(node).lineHeight)+1),'ordinary balance must remain on one line');
    assert.equal(await profileView.locator('#activeCount').textContent(),'17');
    assert.equal(await profileView.locator('#soldCount').textContent(),'2');
    assert.equal(await page.locator('#profileActiveCars .profile-mini-card').count(),17,'all owned listings stay accessible');
    assert.equal(await page.locator('#profileSoldCars .profile-mini-card').count(),2);
    await noOverflow();
    if(missing || broken){
      await page.waitForFunction(()=>!document.getElementById('profileAvatarFallback').hidden && document.getElementById('profileAvatarImage').hidden);
      assert.equal(await profileView.locator('#profileAvatarImage').isVisible(),false);
    }else{
      await profileView.locator('#profileAvatarImage').evaluate(image=>image.decode());
      assert.equal(await profileView.locator('#profileAvatarImage').isVisible(),true);
    }
    await profileView.locator('#copyProfileTelegramId').click();
    await page.waitForFunction(()=>window.__profileFixture.copies.length===1);
    assert.deepEqual(await page.evaluate(()=>window.__profileFixture.copies),[String(user.telegram_id)],'copy contains complete Telegram ID only');
    assert.equal(await profileView.locator('[data-open-admin]').isVisible(),role==='admin');
    assert.equal(await profileView.locator('.profile-work-note').count(),0);
    assert.deepEqual(await page.locator('.bottom-nav button').evaluateAll(nodes=>nodes.map(node=>node.dataset.navTarget)),['unique','training','market','profile','more']);
    assert.equal(await page.locator('.bottom-nav .is-active').getAttribute('data-nav-target'),'profile');
    assert.equal(await page.locator('#floatingChatButton').isVisible(),false,'Profile chat menu keeps its duplicate floating button from covering Delete');
    const topup=profileView.locator('[data-open-topup]'),withdraw=profileView.locator('[data-open-withdraw]');
    const topupBox=await topup.boundingBox(),withdrawBox=await withdraw.boundingBox();
    assert(Math.abs(topupBox.y-withdrawBox.y)<=1,'funding and withdrawal occupy one row');
    assert(Math.abs(topupBox.height-withdrawBox.height)<=1,'financial CTAs have equal height');
    for(const control of [topup,withdraw,profileView.locator('[data-profile-tab="listings"]'),profileView.locator('[data-profile-tab="deals"]'),profileView.locator('[data-open-support]'),profileView.locator('[data-open-info]')]){
      const box=await control.boundingBox();assert(box.height>=44 && box.width>=44,`small tap target ${JSON.stringify(box)}`);assert(box.x>=0 && box.x+box.width<=width+1);
    }
    const cards=profileView.locator('#profileActiveCars .profile-mini-card');
    const first=cards.first();
    assert.match(await first.innerText(),/BMW M5 F90/);
    assert.match(await first.innerText(),/Car Parking 1/);
    assert.match(await cards.nth(1).innerText(),/Car Parking 2/);
    for(const button of await first.locator('.profile-card-actions button').all()){
      const box=await button.boundingBox();assert(box.height>=44 && box.width>=44,`owner control too small ${JSON.stringify(box)}`);
    }
    const photo=first.locator('img').first();await photo.evaluate(image=>image.decode());
    const photoUrl=new URL(await photo.getAttribute('src'),'http://fixture');
    assert.equal(photoUrl.pathname,active[0].images[0]);assert.equal(photoUrl.searchParams.get('preview'),'true','profile uses existing persisted media thumbnail route');
    assert.equal(await first.locator('img').count(),2,'existing secondary photo stays available');
    assert.equal(await cards.nth(1).locator('[data-promote-listing]').isDisabled(),true,'active VIP is not repurchased from the row');
    await profileView.locator('[data-profile-tab="listings"]').click();assert.equal(await profileView.locator('[data-profile-panel="listings"]').isVisible(),true);
    await first.locator('.profile-listing-media').click();await view('listing-detail');assert.match(await page.locator('#listingPageTitle').innerText(),/BMW M5 F90/);await returnProfile();
    await topup.click();await view('topup');assert.equal(await page.locator('#topupForm').isVisible(),true);await noOverflow();await returnProfile();
    await withdraw.click();await view('withdraw');assert.equal(await page.locator('#withdrawForm').isVisible(),true);
    assert(await page.locator('#withdrawForm input').evaluate(input=>parseFloat(getComputedStyle(input).fontSize)>=16));await returnProfile();
    await profileView.locator('.profile-wallet[data-nav-target="wallet"]').click();await view('wallet');await returnProfile();
    await profileView.locator('[data-profile-tab="deals"]').click();await view('activity');
    assert.match(await page.locator('#activeDeals').innerText(),/BMW M5 F90/);
    await page.locator('[data-activity-tab="history"]').click();assert.match(await page.locator('#operationHistory').innerText(),/Продажа автомобиля/);
    await page.locator('[data-activity-tab="chats"]').click();assert.match(await page.locator('#conversationList').innerText(),/Обычный диалог/);await returnProfile();
    await profileView.locator('[data-open-support]').click();await view('support');await page.locator('#supportCategoryPicker button').click();assert.equal(await page.locator('#supportForm').isVisible(),true);await returnProfile();
    await profileView.locator('[data-open-info]').click();await view('help');await page.waitForFunction(()=>document.querySelectorAll('#helpArticles details').length>0);await returnProfile();
    if(role==='admin'){await profileView.locator('[data-open-admin]').click();await view('admin');await page.locator('#adminOverview').getByText('Операционный обзор',{exact:true}).waitFor();await returnProfile();}
    else {
      await profileView.locator('[data-open-admin]').evaluate(button=>{button.hidden=false;button.click();button.hidden=true;});
      assert.equal(await page.locator('[data-view="admin"]').isVisible(),false,'revealing an admin button does not grant client access');
      assert.equal(requests.filter(request=>request.endpoint.startsWith('/admin/')).length,0);
    }
    await first.locator('[data-edit-listing="owned-0"]').click();await view('add');
    assert.equal(await page.locator('#carForm [name=brand]').inputValue(),'BMW');
    assert.equal(await page.locator('#carForm [name=game_version]:checked').inputValue(),'car_parking_1');
    assert.equal(await page.locator('#carForm [name=description]').inputValue(),base.description);await returnProfile();
    await first.locator('[data-promote-listing="owned-0"]').click();await page.locator('#purchaseModal').waitFor({state:'visible'});
    assert.match(await page.locator('#purchaseModalTitle').innerText(),/VIP/);assert(quotes>0);
    await page.locator('#purchaseModal [data-close-purchase]').last().click();await page.locator('#purchaseModal').waitFor({state:'hidden'});
    const deleteButton=first.locator('[data-delete-listing="owned-0"]');
    await deleteButton.scrollIntoViewIfNeeded();
    assert(await deleteButton.evaluate(button=>{
      const rect=button.getBoundingClientRect(),target=document.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2);
      return target===button || button.contains(target);
    }),'Delete center is clickable without floating chat/navigation occlusion');
    await deleteButton.click();
    assert.equal(await page.evaluate(()=>window.__profileFixture.confirms.length),1);
    assert.equal(await page.locator('#profileActiveCars .profile-mini-card').count(),17,'cancelled delete keeps the listing');
    await profileView.locator('[data-profile-section="sold"]').click();assert.equal(await page.locator('#profileSoldCars').isVisible(),true);await noOverflow();
    await profileView.locator('[data-profile-section="active"]').click();
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.waitForTimeout(80);
    const listeners=await page.evaluate(()=>window.__profileFixture.listeners),profileReadsBefore=profileRequests;
    await page.locator('.bottom-nav [data-nav-target="market"]').click();await view('market');
    assert.equal(await page.locator('#floatingChatButton').isVisible(),true,'other sections keep their floating chat entry');
    await returnProfile();
    await page.evaluate(()=>{for(let index=0;index<40;index++)document.querySelector(`.bottom-nav [data-nav-target="${['market','unique','training','profile'][index%4]}"]`).click();});
    await profileView.waitFor({state:'visible'});await page.waitForTimeout(80);
    assert(await page.evaluate(()=>window.__profileFixture.listeners)<=listeners+3,'repeated opens do not accumulate handlers');
    assert(profileRequests<=profileReadsBefore+1,'profile layout does not create request multiplication');
    assert.equal(await page.locator('#profileActiveCars .profile-mini-card').count(),17);
    assert.equal(await page.locator('.bottom-nav').count(),1);
    await noOverflow();
    const last=cards.last();await last.scrollIntoViewIfNeeded();
    const lastBox=await last.boundingBox(),navBox=await page.locator('.bottom-nav').boundingBox();
    assert(lastBox.y+lastBox.height<=navBox.y+1,'bottom navigation does not cover the last listing');
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.waitForFunction(()=>!document.getElementById('toast').classList.contains('is-visible'));
    const suffix=`${role}-${width}${slow?'-slow':''}`;
    await page.screenshot({path:path.join(evidence,`profile-${suffix}.png`),animations:'disabled'});
    if(width===320 || width===390)await page.screenshot({path:path.join(evidence,`profile-${suffix}-full.png`),fullPage:true,animations:'disabled'});
    assert.deepEqual(forbiddenWrites,[],'opening flows must not submit financial/listing mutations');
    assert.deepEqual(errors,[]);
    const result={role,width,slow,relativeApi:slow,malformedHistoricalImage:slow,idRange,profileRequests,quotes,listenerCount:await page.evaluate(()=>window.__profileFixture.listeners),activeListings:17,soldListings:2,
      fallbackAvatar:missing||broken,missingUsername:missing,largeBalance:available,topupBox,withdrawBox,unverified:'Physical iPhone/Android Telegram clients and production data are not exercised.'};
    fs.writeFileSync(path.join(evidence,`profile-${suffix}.json`),JSON.stringify(result,null,2));
    console.log(`PASS ${suffix}: API identity/balance, ID copy, 17 owned +2 sold, all existing flows, role visibility, layout/safe areas, repeated navigation; no money/listing writes`);
  } catch(error) {
    console.error(JSON.stringify({role,width,slow,errors,forbiddenWrites,lastRequests:requests.slice(-10)}));
    await page.screenshot({path:path.join(evidence,`profile-failure-${role}-${width}.png`),fullPage:true}).catch(()=>{});
    throw error;
  } finally {await context.close();}
}

(async()=>{
  fs.mkdirSync(evidence,{recursive:true});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({...(process.env.CI?{}:{channel:'msedge'}),headless:true});
  try {
    for(const role of roles)for(const width of widths)await profileScenario(browser,{role,width});
    if(process.env.PROFILE_SKIP_SLOW!=='1')await profileScenario(browser,{role:'user',width:390,slow:true});
  } finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
