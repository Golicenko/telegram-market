// Existing production frontend, isolated API/Telegram transport, no financial writes.
// NAV_BASELINE_REF=9ea3e78 measures the frozen commit and records violated invariants.
// Default mode is a strict regression gate against the current worktree.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const revision = process.env.NAV_BASELINE_REF || '';
const baseline = Boolean(revision);
const evidence = path.join(__dirname, 'evidence/perf-20261028', baseline ? 'before' : 'after');
const selected = new Set((process.env.NAV_CASES || 'chains,details,stalls,resume,fragments,help').split(','));
const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const files = new Map();
const picture = '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="240"><rect width="400" height="240" fill="#112638"/><path d="M70 150l40-55h145l55 55v35H70z" fill="#819bab"/><circle cx="125" cy="183" r="24" fill="#09131c"/><circle cx="270" cy="183" r="24" fill="#09131c"/></svg>';
const server = http.createServer((request, response) => {
  const pathname = new URL(request.url, 'http://fixture').pathname;
  const relative = pathname === '/' ? 'index.html' : pathname.slice(1);
  if (relative.includes('..') || pathname.startsWith('/api/')) { response.writeHead(404); return response.end(); }
  try {
    const mime = { '.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.png':'image/png', '.jpg':'image/jpeg', '.svg':'image/svg+xml', '.woff2':'font/woff2' };
    response.setHeader('Content-Type', mime[path.extname(relative)] || 'application/json');
    if (baseline && !files.has(relative)) files.set(relative, execFileSync('git', ['show', `${revision}:webapp/${relative}`], { cwd:root, maxBuffer:12*1024*1024 }));
    response.end(baseline ? files.get(relative) : fs.readFileSync(path.join(root, relative)));
  } catch { response.writeHead(404); response.end(); }
});
const report = { mode:baseline ? 'baseline' : 'after', revision:revision || 'worktree', checks:[], timings:[], cases:[], notes:'Desktop mobile Chromium390x844 with isolated populated transport. No physical Telegram client, production backend or financial operation. Held responses are deliberate fixtures, not measured production latency.' };
function check(name, condition, details = {}) {
  report.checks.push({ name, passed:Boolean(condition), ...details });
  if (!baseline) assert(condition, `${name}: ${JSON.stringify(details)}`);
}

function instrumentation() {
  const metrics = window.__navFixture = { hidden:false, listeners:0, ownedAdded:0, ownedRemoved:0, trainingAdded:0, trainingRemoved:0, longTasks:[], transitions:[] };
  const nativeAdd = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function(...args) { metrics.listeners++; return nativeAdd.apply(this, args); };
  Object.defineProperty(document, 'hidden', { configurable:true, get:() => metrics.hidden });
  Object.defineProperty(document, 'visibilityState', { configurable:true, get:() => metrics.hidden ? 'hidden' : 'visible' });
  new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'attributes' && record.target.matches?.('.view') && !record.target.hidden) metrics.transitions.push({ view:record.target.dataset.view, at:performance.now() });
      if (record.target.id === 'profileActiveCars') { metrics.ownedAdded += record.addedNodes.length; metrics.ownedRemoved += record.removedNodes.length; }
      if (record.target.id === 'trainingCards') { metrics.trainingAdded += record.addedNodes.length; metrics.trainingRemoved += record.removedNodes.length; }
    }
  }).observe(document, { subtree:true, childList:true, attributes:true, attributeFilter:['hidden'] });
  try { new PerformanceObserver(list => metrics.longTasks.push(...list.getEntries().map(entry => entry.duration))).observe({ type:'longtask', buffered:true }); } catch {}
  window.Telegram = { WebApp:{ initData:'isolated-navigation-resilience', platform:'ios', ready(){}, expand(){}, onEvent(){}, offEvent(){},
    BackButton:{ show(){}, hide(){}, onClick(handler){ metrics.back = handler; }, offClick(){} }, HapticFeedback:{ impactOccurred(){}, notificationOccurred(){} },
    safeAreaInset:{ top:24, bottom:34 }, contentSafeAreaInset:{ top:12, bottom:0 } } };
}

async function fixture(browser, name) {
  const context = await browser.newContext({ viewport:{ width:390, height:844 }, isMobile:true, hasTouch:true });
  context.setDefaultTimeout(5000);
  context.setDefaultNavigationTimeout(15000);
  await context.route(/^https:/, route => route.fulfill({ status:200, body:'' }));
  await context.addInitScript(instrumentation);
  const page = await context.newPage();
  await page.clock.install(); // Install before application timers, not after the first real polling interval.
  const requests = [], errors = [], forbidden = [], controls = new Map(), gates = [];
  page.on('pageerror', error => errors.push(error.message));
  const user = { id:'resilience-user', telegram_id:77, first_name:'Проверка', last_name:'Навигации', username:null, photo_url:null, role:'user' };
  let balance = 123.45;
  const wallet = () => ({ available_balance:balance, earned_balance:balance, purchased_balance:0, bonus_balance:0, frozen_balance:0 });
  const listing = (id, seller = 'other') => ({ id, seller_id:seller, brand:'BMW', model:`Fixture ${id}`, description:'Изолированные тестовые данные', power_hp:500, max_speed_kph:300, price_af_coins:100, game_version:id.endsWith('1') ? 'car_parking_1' : 'car_parking_2', listing_type:'regular', status:'active', images:['/api/media/fixture'], pinned:false, created_at:'2026-10-28T10:00:00Z' });
  const regular = Array.from({ length:100 }, (_, index) => listing(`regular-${index}`));
  const unique = Array.from({ length:40 }, (_, index) => ({ ...listing(`unique-${index}`), listing_type:'unique' }));
  const active = Array.from({ length:40 }, (_, index) => listing(`owned-${index}`, user.id));
  const sold = Array.from({ length:10 }, (_, index) => ({ ...listing(`sold-${index}`, user.id), status:'sold' }));
  const training = Array.from({ length:12 }, (_, index) => ({ id:`training-${index}`, admin_id:'trainer', title:`Обучение ${index}`, short_description:'Описание тестовой услуги', full_description:'Полное описание из изолированного API', price_af_coins:25, product_type:index%2 ? 'personal' : 'automatic', published:true, availability:'available', cover_url:'/api/media/fixture', promo_video_url:null, pinned:false, views_count:0 }));
  const purchase = { id:'purchase-1', product_id:'training-1', product_type:'personal', title_snapshot:'Купленное обучение', cover_url_snapshot:'/api/media/fixture', status:'completed', delivery_status:'delivered', created_at:'2026-10-28T10:00:00Z', materials:[] };
  const purchases = [purchase];
  const profile = () => ({ user, wallet:wallet(), active_listings:active, sold_listings:sold, purchases:[], deals:[], active_deals:[], deal_threads:[], conversations:[], wallet_transactions:[{ id:'history-1', type:'sale_income', amount:10, created_at:'2026-10-28T10:00:00Z' }], withdrawals:[] });
  const summary = { referralCode:'NAV062', referralUrl:'https://t.me/FixtureBot?startapp=NAV062', referralCount:1, referralLimit:20, commissionPercent:5, canInvite:true, milestones:[{ count:3, reward:10, completed:false },{ count:10, reward:15, completed:false },{ count:20, reward:50, completed:false }] };
  function hold(endpoint, status = 200) {
    let release;
    const gate = { endpoint, status, arrived:0, promise:new Promise(resolve => { release = resolve; }) };
    gate.release = () => { if (controls.get(endpoint) === gate) controls.delete(endpoint); release(); };
    controls.set(endpoint, gate); gates.push(gate); return gate;
  }
  async function arrived(gate) {
    const until = Date.now()+2500;
    while (!gate.arrived && Date.now()<until) await wait(10);
    assert(gate.arrived, `Fixture request reached ${gate.endpoint}`);
  }
  await context.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), endpoint = url.pathname.slice(4), method = request.method();
    requests.push({ endpoint, query:url.search, method, at:Date.now() });
    if (endpoint === '/media/fixture') return route.fulfill({ status:200, contentType:'image/svg+xml', body:picture });
    const allowed = ['/analytics/events','/diagnostics/client','/content/training/mark-seen','/content/unique/mark-seen'].includes(endpoint) || /^\/(listings|training)\/[^/]+\/view$/.test(endpoint);
    if (!['GET','HEAD'].includes(method) && !allowed) { forbidden.push({ endpoint, method }); return route.fulfill({ status:409, contentType:'application/json', body:'{"detail":"Unexpected mutation in navigation fixture"}' }); }
    const gate = controls.get(endpoint);
    if (gate) { gate.arrived++; await gate.promise; }
    let body = [], status = gate?.status || 200;
    if (status !== 200) body = { detail:'Isolated API failure' };
    else if (endpoint === '/me') body = { user, wallet:wallet() };
    else if (endpoint === '/profile') body = profile();
    else if (endpoint === '/listings') body = url.searchParams.get('type') === 'unique' ? unique : regular;
    else if (endpoint === '/training') body = training;
    else if (endpoint === '/training/mine') body = purchases;
    else if (endpoint === '/training/purchases/purchase-1/access') body = { purchase, access_allowed:true, description:'Доступ из тестового API', contact_url:null };
    else if (/^\/training\/training-\d+$/.test(endpoint)) body = training.find(item => endpoint.endsWith('/'+item.id));
    else if (/^\/(listings|training)\/[^/]+\/view$/.test(endpoint)) body = { views_count:1, likes_count:0, liked_by_me:false };
    else if (endpoint === '/content/training/snapshot') body = { items:training, marker:1 };
    else if (endpoint === '/content/unique/snapshot') body = { items:unique, marker:1 };
    else if (endpoint.endsWith('/mark-seen')) body = { unseen_count:0, marker:1 };
    else if (endpoint === '/content/unseen') body = { training:{ unseen_count:0, marker:1 }, unique:{ unseen_count:0, marker:1 } };
    else if (endpoint === '/conversations/unread-summary') body = { total_unread:0, conversations:[] };
    else if (endpoint === '/referrals') body = summary;
    else if (endpoint === '/help/rules') body = { publication:{ enabled:true, free_limit:5, remaining:5, price_stars:7 }, af_per_star:1, withdrawal_fee_percent:30, withdrawal_hours:24, seller_response_hours:24, vip_cost_af:15, vip_hours:24 };
    else if (endpoint === '/help/withdrawal-example') body = { budget_af:'30.00', gross_af:'21.43', fee_af:'6.43', payout_stars:15, unspent_af:'8.57', fee_percent:30, gift_plan:[{ count:1, star_count:15 }] };
    else if (endpoint === '/advertisement') body = { is_active:false };
    await route.fulfill({ status, contentType:'application/json', body:JSON.stringify(body) }).catch(error => { if (!request.failure()) throw error; });
  });
  const visible = () => page.evaluate(() => [...document.querySelectorAll('.view')].filter(node => !node.hidden).map(node => node.dataset.view));
  async function click(view, label = name) {
    const wallStarted = performance.now();
    const result = await page.evaluate(async view => {
      const start = performance.now(); document.querySelector(`.bottom-nav [data-nav-target="${view}"]`).click();
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      return { view, paintMs:performance.now()-start, visible:!document.querySelector(`[data-view="${view}"]`).hidden };
    }, view);
    result.wallMs = performance.now()-wallStarted;
    report.timings.push({ case:name, label, ...result });
    check(`${name}: ${label} shows ${view} without waiting for API`, result.visible, result);
    // Host elapsed time also catches a blocked main thread when the test clock is installed.
    check(`${name}: ${label} paint budget`, result.paintMs<1000 && result.wallMs<2000, result);
    return result;
  }
  async function start() {
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.waitForFunction(() => document.querySelectorAll('#marketCars [data-listing-card]').length === 100 && document.getElementById('startupStatus').hidden);
    await page.evaluate(() => document.fonts.ready);
  }
  async function close() {
    gates.forEach(gate => gate.release());
    report.cases.push({ name, requests, errors, forbidden, metrics:await page.evaluate(() => ({ ...window.__navFixture, back:undefined, nodes:document.querySelectorAll('*').length })).catch(() => null) });
    assert.deepEqual(forbidden, [], 'No financial or other unexpected mutation');
    assert.deepEqual(errors, [], 'No uncaught browser error');
    await context.close();
  }
  return { page, requests, hold, arrived, visible, click, start, close, setBalance:value => { balance = value; }, releaseAll:() => gates.forEach(gate => gate.release()) };
}

async function runCase(browser, name, task) {
  const app = await fixture(browser, name);
  try { await app.start(); await task(app); }
  catch (error) { await app.page.screenshot({ path:path.join(evidence, `${name}-failure.png`), fullPage:true }).catch(() => {}); throw error; }
  finally { await app.close(); }
}

async function chains(browser) {
  await runCase(browser, 'requested-chains', async app => {
    for (const view of ['profile','training','unique','more','market']) await app.click(view, 'warmup');
    await app.page.waitForFunction(() => document.querySelectorAll('#trainingCards .training-card').length === 12 && document.getElementById('profileActiveCars').children.length === 40);
    await wait(60);
    await app.page.evaluate(() => { window.__ownedCard=document.getElementById('profileActiveCars').firstElementChild; window.__trainingCard=document.getElementById('trainingCards').firstElementChild; window.__beforeMetrics={ ...window.__navFixture }; });
    const sequences = [['market','profile','market'],['market','training','market'],['market','unique','market'],['market','more','market'],['profile','more','profile'],['more','more','market'],['training','profile','market'],['market','training','unique','market']];
    for (let index=0;index<sequences.length;index++) for (const view of sequences[index]) await app.click(view, `sequence-${index+1}`);
    await app.page.evaluate(() => { for (let index=0;index<150;index++) document.querySelector(`.bottom-nav [data-nav-target="${['profile','training','unique','more','market'][index%5]}"]`).click(); });
    await wait(100); check('sequence-9: rapid switching preserves final Market', (await app.visible()).join() === 'market');
    for (const view of ['market','training','profile','more','market']) for (let index=0;index<5;index++) await app.click(view, 'sequence-10');
    const identity = await app.page.evaluate(() => ({ owned:window.__ownedCard===document.getElementById('profileActiveCars').firstElementChild, training:window.__trainingCard===document.getElementById('trainingCards').firstElementChild, ownedAdded:window.__navFixture.ownedAdded-window.__beforeMetrics.ownedAdded, ownedRemoved:window.__navFixture.ownedRemoved-window.__beforeMetrics.ownedRemoved }));
    check('unchanged populated profile keeps its card DOM', identity.owned, identity);
    check('unchanged populated training keeps its card DOM', identity.training, identity);
  });
}

async function details(browser) {
  for (const kind of ['success','404','owned']) await runCase(browser, `late-training-${kind}`, async app => {
    await app.click('training');
    await app.page.waitForFunction(() => document.querySelectorAll('#trainingCards .training-card').length === 12);
    const endpoint = kind === 'owned' ? '/training/purchases/purchase-1/access' : '/training/training-0';
    const gate = app.hold(endpoint, kind === '404' ? 404 : 200);
    const selector = kind === 'owned' ? '#trainingCards [data-open-training-purchase="purchase-1"]' : '#trainingCards [data-open-training-product="training-0"]';
    await app.page.locator(selector).first().evaluate(button => button.click()); await app.arrived(gate);
    await app.click('market', 'leave pending detail'); gate.release(); await wait(100);
    await app.page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const actual = await app.visible(); check(`late ${kind} response cannot navigate away from Market`, actual.join() === 'market', { actual });
    await app.page.screenshot({ path:path.join(evidence, `late-training-${kind}.png`), animations:'disabled' });
  });
}

async function fragments(browser) {
  await runCase(browser, 'unchanged-fragment-refresh', async app => {
    await app.click('profile'); await app.click('training');
    await app.page.waitForFunction(() => document.getElementById('profileActiveCars').children.length === 40 && document.getElementById('profileSoldCars').children.length === 10 && document.querySelectorAll('#trainingCards .training-card').length === 12);
    await app.page.waitForFunction(() => document.querySelectorAll('#personalTrainingPurchases .training-library-card').length === 1);
    await wait(60);
    await app.page.evaluate(() => {
      window.__refreshCards = { owned:document.getElementById('profileActiveCars').firstElementChild, sold:document.getElementById('profileSoldCars').firstElementChild, training:document.getElementById('trainingCards').firstElementChild };
      window.__refreshMetrics = { ownedAdded:window.__navFixture.ownedAdded, trainingAdded:window.__navFixture.trainingAdded };
    });
    await app.click('market'); await app.page.clock.fastForward(16000);
    const profileReads = app.requests.filter(request => request.endpoint === '/profile').length;
    app.setBalance(432.10); await app.click('profile', 'wallet-only fresh profile');
    await app.page.waitForFunction(() => document.querySelector('.header-balance [data-balance]').textContent === '432.10');
    const profile = await app.page.evaluate(() => ({ owned:window.__refreshCards.owned===document.getElementById('profileActiveCars').firstElementChild, sold:window.__refreshCards.sold===document.getElementById('profileSoldCars').firstElementChild, training:window.__refreshCards.training===document.getElementById('trainingCards').firstElementChild, ownedAdded:window.__navFixture.ownedAdded-window.__refreshMetrics.ownedAdded, trainingAdded:window.__navFixture.trainingAdded-window.__refreshMetrics.trainingAdded }));
    check('wallet-only profile comparison used an actual fresh server read', app.requests.filter(request => request.endpoint === '/profile').length > profileReads);
    check('wallet-only profile refresh retains all unchanged owned/sold card DOM', profile.owned && profile.sold && profile.ownedAdded === 0, profile);
    check('wallet-only profile refresh does not rebuild unrelated training products', profile.training && profile.trainingAdded === 0, profile);
    const purchaseReads = app.requests.filter(request => request.endpoint === '/training/mine').length;
    await app.click('training', 'fresh unchanged training purchases');
    const until = Date.now()+2500;
    while (app.requests.filter(request => request.endpoint === '/training/mine').length === purchaseReads && Date.now()<until) await wait(10);
    check('training comparison used an actual fresh purchases read', app.requests.filter(request => request.endpoint === '/training/mine').length > purchaseReads);
    await wait(80);
    const training = await app.page.evaluate(() => ({ retained:window.__refreshCards.training===document.getElementById('trainingCards').firstElementChild, added:window.__navFixture.trainingAdded-window.__refreshMetrics.trainingAdded }));
    check('fresh unchanged purchases and catalogue retain training product DOM', training.retained && training.added === 0, training);
    await app.click('market');
  });
}

async function stalls(browser) {
  await runCase(browser, 'stalled-training-snapshot', async app => {
    const gate = app.hold('/content/training/snapshot'); await app.click('training'); await app.arrived(gate);
    await app.click('market', 'leave stalled training');
    for (const milliseconds of [13000,1000,13000]) { await app.page.clock.fastForward(milliseconds); await wait(30); }
    check('training timeout does not replace Market', (await app.visible()).join() === 'market');
    check('training timeout retains cached Market cards', await app.page.locator('#marketCars [data-listing-card]').count() === 100);
    gate.release(); await wait(60);
    const previousReads = app.requests.filter(request => request.endpoint === '/content/training/snapshot').length;
    await app.click('training', 'retry after timeout');
    const until = Date.now()+2500;
    while (app.requests.filter(request => request.endpoint === '/content/training/snapshot').length === previousReads && Date.now()<until) await wait(10);
    check('training retry actually issues a fresh snapshot read', app.requests.filter(request => request.endpoint === '/content/training/snapshot').length > previousReads);
    await app.page.waitForFunction(() => document.querySelectorAll('#trainingCards .training-card').length === 12);
    await app.click('market');
  });
  await runCase(browser, 'cold-referral-wallet', async app => {
    const referral = app.hold('/referrals'), me = app.hold('/me');
    await app.click('more'); await app.arrived(referral); referral.release(); await app.arrived(me);
    await app.page.locator('#referralContent').waitFor({ state:'visible', timeout:2000 });
    check('first referral summary renders before authoritative wallet refresh', await app.page.locator('#referralContent').isVisible());
    check('pending wallet does not invent a local balance', await app.page.locator('.header-balance [data-balance]').textContent() === '123.45');
    await app.click('market'); app.setBalance(654.32); me.release();
    await app.page.waitForFunction(() => document.querySelector('.header-balance [data-balance]').textContent === '654.32');
    check('late authoritative wallet refresh retains Market', (await app.visible()).join() === 'market');
  });
  await runCase(browser, 'stalled-referral-wallet', async app => {
    const referral = app.hold('/referrals'), me = app.hold('/me');
    await app.click('more'); await app.arrived(referral); await app.click('market', 'leave pending referrals');
    referral.release(); await wait(60); check('late summary leaves Market selected', (await app.visible()).join() === 'market');
    await app.click('more', 'reopen known referrals');
    await app.page.locator('#referralContent').waitFor({ state:'visible' }); await app.arrived(me);
    const reads = app.requests.filter(request => request.endpoint === '/me').length;
    for (let index=0;index<8;index++) { await app.click('market'); await app.click('more'); }
    check('pending wallet refresh remains singleflight', app.requests.filter(request => request.endpoint === '/me').length === reads);
    check('referral content is visible before wallet refresh', await app.page.locator('#referralContent').isVisible());
    app.setBalance(654.32); me.release();
    await app.page.waitForFunction(() => document.querySelector('.header-balance [data-balance]').textContent === '654.32');
    await app.click('market');
  });
}

async function withdrawalHelp(browser) {
  // This is new functionality, not a claim that the old commit already had it.
  if (baseline) { report.helpBaseline='New readonly withdrawal example is tested after implementation only.'; return; }
  await runCase(browser, 'withdrawal-help-readonly', async app => {
    const reads = () => app.requests.filter(request => request.endpoint === '/help/withdrawal-example');
    const balanceBefore = await app.page.locator('.header-balance [data-balance]').textContent();
    await app.page.locator('#infoButton').click();
    await app.page.locator('[data-view="help"]').waitFor({ state:'visible' });
    await app.page.waitForFunction(() => document.getElementById('helpRulesStatus').textContent.includes('получены'));
    check('withdrawal help has a clear heading', /Как работает вывод средств/.test(await app.page.locator('#help-withdraw > summary').textContent()));
    check('withdrawal example is not requested before opening its article', reads().length === 0);
    const gate = app.hold('/help/withdrawal-example', 503);
    await app.page.locator('#help-withdraw > summary').click(); await app.arrived(gate);
    check('readonly example has an explicit loading state', /Получаем пример/.test(await app.page.locator('#helpWithdrawalExample [role="status"]').textContent()));
    gate.release();
    await app.page.locator('[data-retry-withdrawal-example]').waitFor({ state:'visible' });
    const errorState = await app.page.locator('#helpWithdrawalExample [role="status"]').textContent();
    check('readonly example error is visible and sanitized', /Не удалось обновить пример/.test(errorState) && !/Isolated|RAW/.test(errorState));
    check('failed readonly example leaves other help content available', await app.page.locator('#help-withdraw .help-article__content > ol').isVisible());
    await app.page.locator('[data-retry-withdrawal-example]').click();
    await app.page.locator('#helpWithdrawalExample dl').waitFor({ state:'visible' });
    const amounts = await app.page.locator('#helpWithdrawalExample dd').allTextContents();
    check('help displays server reserve, commission, unspent budget and Stars', amounts.length === 5 && /30/.test(amounts[0]) && /21[,.]43/.test(amounts[1]) && /6[,.]43/.test(amounts[2]) && /8[,.]57/.test(amounts[3]) && /15/.test(amounts[4]), { amounts });
    check('example uses readonly GET with the requested budget', reads().length === 2 && reads().every(request => request.method === 'GET' && request.query === '?amount=30'), { reads:reads() });
    check('reading the example never changes balance', await app.page.locator('.header-balance [data-balance]').textContent() === balanceBefore);
    await app.page.locator('#help-withdraw > summary').click(); await wait(20); await app.page.locator('#help-withdraw > summary').click(); await wait(30);
    check('reopening the example uses its bounded cache', reads().length === 2);
    check('help never calls withdrawal quote/create endpoints', !app.requests.some(request => request.endpoint.startsWith('/withdrawals')));
    await app.page.screenshot({ path:path.join(evidence, 'withdrawal-help-readonly.png'), fullPage:true, animations:'disabled' });
    await app.click('market', 'leave help');
  });
}

async function resume(browser) {
  await runCase(browser, 'hidden-resume', async app => {
    await app.click('training');
    await app.page.evaluate(() => { window.__navFixture.hidden=true; document.dispatchEvent(new Event('visibilitychange')); });
    await app.page.clock.fastForward(61000);
    const me = app.hold('/me'); app.setBalance(777.77);
    await app.page.evaluate(() => { window.__navFixture.hidden=false; document.dispatchEvent(new Event('visibilitychange')); });
    await app.arrived(me); await app.click('unique', 'navigate during resume authentication'); me.release(); await wait(100);
    check('resume response retains latest selected section', (await app.visible()).join() === 'unique');
    await app.page.waitForFunction(() => document.querySelector('.header-balance [data-balance]').textContent === '777.77');
    const again = app.hold('/me');
    await app.page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted:true })));
    await app.arrived(again); await app.click('market', 'navigate during bfcache restoration'); again.release(); await wait(100);
    check('bfcache restoration retains final Market', (await app.visible()).join() === 'market');
    check('resume does not lose catalogue cards', await app.page.locator('#marketCars [data-listing-card]').count() === 100);
  });
}

(async () => {
  fs.mkdirSync(evidence, { recursive:true });
  if (baseline) report.commit = execFileSync('git', ['rev-parse', revision], { cwd:root, encoding:'utf8' }).trim();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ ...(process.env.CI ? {} : { channel:'msedge' }), headless:true });
    for (const [name, task] of [['chains',chains],['details',details],['stalls',stalls],['resume',resume],['fragments',fragments],['help',withdrawalHelp]]) if (selected.has(name)) await task(browser);
    console.log(JSON.stringify({ mode:report.mode, checks:report.checks.length, violations:report.checks.filter(check => !check.passed) }));
  } finally {
    fs.writeFileSync(path.join(evidence, 'navigation-resilience.json'), JSON.stringify(report, null, 2));
    await browser?.close(); await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); server.close(); process.exitCode=1; });
