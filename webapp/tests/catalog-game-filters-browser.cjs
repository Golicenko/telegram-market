// Real frontend/CSS and isolated API data. Mobile Telegram shell emulation;
// this does not claim testing on physical iPhone/Android Telegram clients.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const root = path.resolve(__dirname, '..');
const evidence = path.join(__dirname, 'evidence/catalog-game-filters');
const illustration = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#1c3348"/><path fill="#91b5ce" d="M60 290l65-35 70-8 67-67h141l76 75 83 25 18 70H60z"/><path fill="#102336" d="M222 244l52-53h48v53zm111-53h62l53 53H333z"/><g fill="#08131e" stroke="#4a6376" stroke-width="9"><circle cx="165" cy="350" r="38"/><circle cx="475" cy="350" r="38"/></g><text x="320" y="445" text-anchor="middle" font-family="sans-serif" font-size="20" fill="#bdcddb">ТЕСТОВАЯ ИЛЛЮСТРАЦИЯ</text></svg>`;
const server = http.createServer((request, response) => {
  const pathname = new URL(request.url, 'http://fixture').pathname;
  if (pathname === '/test-car.svg') { response.setHeader('Content-Type', 'image/svg+xml'); return response.end(illustration); }
  const file = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) { response.writeHead(404); return response.end(); }
  response.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg' })[path.extname(file)] || 'application/json');
  response.end(fs.readFileSync(file));
});

async function listingIds(page, section) {
  return page.locator(`#${section}Cars [data-listing-card]`).evaluateAll(cards => cards.map(card => card.dataset.listingCard));
}

async function cardStyle(card) {
  return card.evaluate(element => {
    const css = getComputedStyle(element), image = element.querySelector('img');
    const media = element.querySelector('.car-card__media'), game = element.querySelector('.listing-game-badge'), vip = element.querySelector('.car-vip-badge');
    const gameCss = getComputedStyle(game), vipCss = getComputedStyle(vip);
    return { clip: css.backgroundClip, border: css.borderTopWidth, shadow: css.boxShadow,
      photo: { src: image.getAttribute('src'), border: getComputedStyle(image).borderWidth, fit: getComputedStyle(image).objectFit, ratio: getComputedStyle(media).aspectRatio },
      game: { top: gameCss.top, left: gameCss.left, fontSize: gameCss.fontSize, background: gameCss.backgroundColor },
      vip: { top: vipCss.top, left: vipCss.left, right: vipCss.right, fontSize: vipCss.fontSize },
    };
  });
}

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ ...(process.env.CI ? {} : { channel: 'msedge' }), headless: true });
  fs.mkdirSync(evidence, { recursive: true });
  try {
    for (const platform of ['ios', 'android']) for (const width of [320, 390, 430]) {
      const context = await browser.newContext({ viewport: { width, height: 844 }, isMobile: true, hasTouch: true });
      await context.route(/^https:/, route => route.fulfill({ status: 200, body: '' }));
      await context.addInitScript(platform => {
        window.Telegram = { WebApp: { initData: 'isolated-filter-fixture', platform, ready() {}, expand() {}, onEvent() {}, offEvent() {}, BackButton: { onClick() {}, offClick() {}, show() {}, hide() {} }, safeAreaInset: { top: 24, bottom: 34 }, contentSafeAreaInset: { top: 12, bottom: 0 } } };
      }, platform);
      const user = { id: 'viewer', first_name: 'Проверка фильтров', role: 'user' };
      const wallet = { available_balance: 100, frozen_balance: 0 };
      const base = { seller_id: 'seller', brand: 'BMW', model: 'M5', description: 'Тестовое объявление', power_hp: 500, max_speed_kph: 350, price_af_coins: 100, game_version: 'car_parking_1', listing_type: 'regular', status: 'active', images: ['/test-car.svg'], created_at: '2026-10-18T12:00:00Z', pinned: false };
      const vip = { pinned: true, pinned_until: '2099-10-18T12:00:00Z' };
      const regular = [
        { ...base, ...vip, id: 'cp2-vip', game_version: 'car_parking_2', power_hp: 700, max_speed_kph: 450 },
        { ...base, ...vip, id: 'cp1-vip' },
        { ...base, id: 'cp1-regular', price_af_coins: 50 },
        { ...base, id: 'cp2-bmw', game_version: 'car_parking_2', price_af_coins: 150 },
        { ...base, id: 'cp2-audi', game_version: 'car_parking_2', brand: 'Audi' },
        { ...base, id: 'unknown', game_version: null },
      ];
      const unique = [
        { ...base, ...vip, id: 'unique-cp1-vip', listing_type: 'unique' },
        { ...base, id: 'unique-cp1', listing_type: 'unique' },
        { ...base, ...vip, id: 'unique-cp2-vip', listing_type: 'unique', game_version: 'car_parking_2' },
        { ...base, id: 'unique-cp2', listing_type: 'unique', game_version: 'car_parking_2' },
        { ...base, id: 'unique-unknown', listing_type: 'unique', game_version: null },
      ];
      let financialRequests = 0;
      const clientDiagnostics = [];
      await context.route('**/api/**', async route => {
        const request = route.request(), url = new URL(request.url()), endpoint = url.pathname.slice(4);
        if (['/wallet/', '/vip/', '/purchase', '/withdraw'].some(part => endpoint.includes(part))) financialRequests++;
        let body = [];
        if (endpoint === '/me') body = { user, wallet };
        else if (endpoint === '/profile') body = { user, wallet, active_listings: [], sold_listings: [], deals: [], conversations: [], deal_threads: [], wallet_transactions: [], withdrawals: [] };
        else if (endpoint === '/listings') body = url.searchParams.get('type') === 'unique' ? unique : regular;
        else if (endpoint === '/content/unseen') body = { unique: { unseen_count: 0, marker: 0 }, training: { unseen_count: 0, marker: 0 } };
        else if (endpoint === '/content/unique/snapshot') body = { items: unique, marker: 0 };
        else if (endpoint === '/content/training/snapshot') body = { items: [], marker: 0 };
        else if (endpoint.endsWith('/mark-seen')) body = { unseen_count: 0, marker: 0 };
        else if (endpoint === '/conversations/unread-summary') body = { total_unread: 0, conversations: [] };
        else if (endpoint.endsWith('/view')) body = { views_count: 0, likes_count: 0, liked_by_me: false };
        else if (endpoint === '/diagnostics/client') clientDiagnostics.push(request.postDataJSON());
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      });
      const page = await context.newPage(), errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      try { await page.locator('#marketCars [data-listing-card=cp2-vip]').waitFor(); }
      catch (error) { console.error('Startup state:', { errors, status: await page.locator('#startupStatus').textContent(), sync: await page.locator('#syncStatus').textContent() }); throw error; }
      const nav = async section => { await page.locator(`.bottom-nav [data-nav-target=${section}]`).click(); await page.locator(`[data-view=${section}]`).waitFor({ state: 'visible' }); };
      assert.equal(await page.locator('#marketGameFilter').inputValue(), '');
      assert.equal(await page.locator('#uniqueGameFilter').inputValue(), '');
      assert.deepEqual(await listingIds(page, 'market'), regular.map(row => row.id));
      assert(await page.locator('#marketGameFilter').evaluate(select => select.closest('.filters').firstElementChild.contains(select)));
      const normalStyle = await cardStyle(page.locator('#marketCars [data-listing-card=cp1-regular]'));
      const marketVipStyle = await cardStyle(page.locator('#marketCars [data-listing-card=cp1-vip]'));
      assert.equal(marketVipStyle.game.top, '36px'); assert.equal(marketVipStyle.vip.left, '8px');
      await page.locator('#marketGameFilter').selectOption('car_parking_1');
      assert.deepEqual(await listingIds(page, 'market'), ['cp1-vip', 'cp1-regular']);
      await page.locator('#marketGameFilter').selectOption('car_parking_2');
      assert.deepEqual(await listingIds(page, 'market'), ['cp2-vip', 'cp2-bmw', 'cp2-audi']);
      await page.locator('#brandFilter').selectOption('BMW');
      await page.locator('#priceMinFilter').fill('100'); await page.locator('#priceMaxFilter').fill('150');
      await page.locator('#extraFiltersButton').click();
      await page.locator('#powerFilter').fill('600'); await page.locator('#speedFilter').fill('400');
      await page.locator('#applyFiltersButton').click();
      assert.deepEqual(await listingIds(page, 'market'), ['cp2-vip']);
      await page.locator('#priceMinFilter').fill('151'); await page.locator('#priceMinFilter').blur();
      assert.deepEqual(await listingIds(page, 'market'), []);
      assert.match(await page.locator('#marketEmptyState').textContent(), /По выбранным фильтрам объявлений пока нет/);
      await page.locator('#resetFiltersButton').click();
      assert.equal(await page.locator('#marketGameFilter').inputValue(), '');
      assert.deepEqual(await listingIds(page, 'market'), regular.map(row => row.id));
      await page.locator('#marketGameFilter').selectOption('car_parking_1');
      await nav('unique');
      await page.locator('#uniqueCars [data-listing-card=unique-cp1-vip]').waitFor();
      assert.deepEqual(await listingIds(page, 'unique'), unique.map(row => row.id));
      assert.equal(await page.locator('#uniqueCars .unique-label').count(), 0);
      await page.locator('#uniqueGameFilter').selectOption('car_parking_1');
      assert.deepEqual(await listingIds(page, 'unique'), ['unique-cp1-vip', 'unique-cp1']);
      await page.locator('#uniqueGameFilter').selectOption('car_parking_2');
      assert.deepEqual(await listingIds(page, 'unique'), ['unique-cp2-vip', 'unique-cp2']);
      const uniqueVip = page.locator('#uniqueCars [data-listing-card=unique-cp2-vip]');
      const uniquePlain = page.locator('#uniqueCars [data-listing-card=unique-cp2]');
      const uniqueStyle = await cardStyle(uniqueVip), uniquePlainStyle = await cardStyle(uniquePlain);
      assert.equal(uniqueStyle.clip, marketVipStyle.clip); assert.equal(uniqueStyle.shadow, marketVipStyle.shadow);
      assert.equal(uniqueStyle.border, '1px'); assert.deepEqual(uniqueStyle.photo, uniquePlainStyle.photo);
      assert.equal(uniqueStyle.game.top, '7px'); assert.equal(uniqueStyle.vip.top, '7px'); assert.equal(uniqueStyle.vip.right, '7px');
      for (const card of [uniqueVip, uniquePlain]) {
        const media = await card.locator('.car-card__media').boundingBox(), game = await card.locator('.listing-game-badge').boundingBox();
        assert(game.y >= media.y && game.y + game.height <= media.y + media.height);
        assert.equal(await card.locator('.listing-game-badge').textContent(), 'Car Parking 2');
      }
      const gameBox = await uniqueVip.locator('.listing-game-badge').boundingBox(), vipBox = await uniqueVip.locator('.car-vip-badge').boundingBox();
      assert(gameBox.x + gameBox.width <= vipBox.x, `${platform} ${width}: game and VIP must not overlap`);
      assert.equal(await uniquePlain.locator('.car-vip-badge').isVisible(), false);
      await page.screenshot({ path: path.join(evidence, `unique-${platform}-${width}.png`), animations: 'disabled' });
      await nav('profile'); await nav('market');
      assert.equal(await page.locator('#marketGameFilter').inputValue(), 'car_parking_1');
      assert.deepEqual(await listingIds(page, 'market'), ['cp1-vip', 'cp1-regular']);
      assert.deepEqual(await cardStyle(page.locator('#marketCars [data-listing-card=cp1-regular]')), normalStyle);
      assert.deepEqual(await cardStyle(page.locator('#marketCars [data-listing-card=cp1-vip]')), marketVipStyle);
      await page.locator('#marketGameFilter').selectOption('');
      await page.locator('#extraFiltersButton').click();
      await page.locator('.filters').evaluate(element => { element.scrollLeft = 0; });
      await page.screenshot({ path: path.join(evidence, `market-${platform}-${width}.png`), animations: 'disabled' });
      await nav('unique');
      assert.equal(await page.locator('#uniqueGameFilter').inputValue(), 'car_parking_2');
      await page.locator('#uniqueGameFilter').selectOption('');
      assert.deepEqual(await listingIds(page, 'unique'), unique.map(row => row.id));
      await page.locator('#uniqueGameFilter').selectOption('car_parking_2');
      await nav('market'); await page.locator('#extraFiltersButton').click(); await page.locator('#resetFiltersButton').click(); await nav('unique');
      assert.equal(await page.locator('#uniqueGameFilter').inputValue(), 'car_parking_2');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      assert.equal(financialRequests, 0); assert.deepEqual(errors, []); assert.deepEqual(clientDiagnostics, []);
      console.log(`PASS ${platform} ${width}: independent КП filters/all/CP1/CP2, price/brand/stats/reset, profile persistence, unchanged Market cards, Unique top badges/no overlap, outer VIP border`);
      await context.close();
    }
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
