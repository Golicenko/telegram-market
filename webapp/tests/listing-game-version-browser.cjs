// Real frontend with an isolated API fixture; HTTP/database checks live in pytest.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os'), http = require('node:http');
const root = path.resolve(__dirname, '..');
const photo = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aK1sAAAAASUVORK5CYII=', 'base64');
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://test').pathname;
  if (pathname === '/test-photo.png') { res.setHeader('Content-Type', 'image/png'); return res.end(photo); }
  const filename = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
  if (!filename.startsWith(root + path.sep) || !fs.existsSync(filename)) { res.writeHead(404); return res.end(); }
  res.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg' })[path.extname(filename)] || 'application/json');
  res.end(fs.readFileSync(filename));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    await context.route(/^https:/, route => route.fulfill({ status: 200, body: '' }));
    const user = { id: 'seller-fixture', telegram_id: 77, first_name: 'Продавец', username: null, photo_url: null, role: 'user' };
    const wallet = { available_balance: 100, frozen_balance: 0, total_earned: 0 };
    const base = { seller_id: 'another-seller', brand: 'Тестовый автомобиль', model: '', power_hp: 250, max_speed_kph: 300, price_af_coins: 100, description: 'Описание машины', delivery_time_estimate: 'up_to_1h', listing_type: 'regular', status: 'active', views_count: 2, likes_count: 0, images: ['/test-photo.png'], created_at: '2026-09-23T09:00:00Z', game_version: 'car_parking_1', pinned: false, pinned_until: null };
    const listings = [
      { ...base, id: 'old-cp1', pinned: true, pinned_until: '2026-09-23T09:01:00Z' },
      { ...base, id: 'regular-cp2', game_version: 'car_parking_2' },
    ];
    let posts = 0, uploads = 0;
    await context.addInitScript(() => { window.Telegram = { WebApp: { initData: 'isolated-fixture', ready() {}, expand() {}, onEvent() {}, BackButton: { onClick() {}, show() {}, hide() {} } } }; });
    await context.route('**/api/**', async route => {
      const req = route.request(), url = new URL(req.url()), endpoint = url.pathname.slice(4);
      let body = [], status = 200;
      if (endpoint === '/me') body = { user, wallet };
      else if (endpoint === '/profile') body = { user, wallet, active_listings: listings.filter(item => item.seller_id === user.id), sold_listings: [], wallet_transactions: [], withdrawals: [], conversations: [], deal_threads: [] };
      else if (endpoint === '/content/unseen') body = { unique: { unseen_count: 0, marker: 0 }, training: { unseen_count: 0, marker: 0 } };
      else if (endpoint === '/conversations/unread-summary') body = { total_unread: 0, conversations: [] };
      else if (endpoint === '/uploads') { uploads++; body = { url: '/test-photo.png' }; }
      else if (endpoint === '/listings' && req.method() === 'POST') {
        const values = req.postDataJSON(); posts++;
        assert(['car_parking_1', 'car_parking_2'].includes(values.game_version));
        body = { ...base, ...values, id: 'new-' + posts, seller_id: user.id, images: values.image_urls };
        listings.push(body); status = 201;
      } else if (endpoint === '/listings') body = url.searchParams.get('type') === 'unique' ? [] : listings;
      else if (/^\/listings\/[^/]+$/.test(endpoint)) {
        body = listings.find(item => item.id === endpoint.split('/')[2]);
        if (req.method() === 'PATCH') Object.assign(body, req.postDataJSON());
      } else if (endpoint.endsWith('/view')) body = { views_count: 3, likes_count: 0, liked_by_me: false };
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    });
    const page = await context.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.clock.install({ time: new Date('2026-09-23T09:00:00Z') });
    const url = `http://127.0.0.1:${server.address().port}/`;
    await page.goto(url);
    await page.locator('#marketCars [data-listing-card="old-cp1"]').waitFor();
    const pinned = page.locator('#marketCars [data-listing-card="old-cp1"]');
    const ordinary = page.locator('#marketCars [data-listing-card="regular-cp2"]');
    assert.equal(await pinned.locator('.listing-game-badge').textContent(), 'Car Parking 1');
    assert.equal(await ordinary.locator('.listing-game-badge').textContent(), 'Car Parking 2');
    assert(await pinned.evaluate(n => n.classList.contains('is-pinned')));
    assert.equal(await ordinary.evaluate(n => n.classList.contains('is-pinned')), false);
    assert.equal(await pinned.locator('.pin-label').count(), 0);
    const before = await pinned.boundingBox();
    await page.screenshot({ path: path.join(os.tmpdir(), 'autoflow-game-market-390.png') });
    await page.clock.fastForward(61000);
    assert.equal(await pinned.evaluate(n => n.classList.contains('is-pinned')), false, 'Frame expires without backend refresh');
    const after = await pinned.boundingBox();
    assert.equal(after.width, before.width, 'Frame does not resize card width');
    assert.equal(after.height, before.height, 'Frame does not resize card height');
    await ordinary.locator('h3').click();
    await page.locator('[data-view="listing-detail"]').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#listingPageGame').textContent(), 'Car Parking 2');
    assert.equal(await page.locator('#listingPageGameNote').textContent(), 'Машина из Car Parking 2');
    for (const game of ['car_parking_1', 'car_parking_2']) {
      await page.locator('.bottom-nav [data-nav-target="market"]').click();
      await page.locator('.catalog-add[data-open-add]').click();
      const form = page.locator('#carForm');
      assert.equal(await form.locator('[name="game_version"]:checked').count(), 0);
      assert((await form.locator('.listing-game-choice').boundingBox()).y < (await form.locator('.photo-upload').boundingBox()).y);
      assert.match(await form.locator('.listing-photo-rules').textContent(), /созданные или изменённые нейросетью/);
      await form.locator('[name="brand"]').fill('Мой автомобиль');
      await form.locator('[name="power_hp"]').fill('1000000');
      await form.locator('[name="max_speed_kph"]').fill('1000000');
      await form.locator('[name="description"]').fill('Оригинальный скриншот из игры');
      await form.locator('[name="price_af_coins"]').fill('10');
      await form.locator('#promoteRow').click();
      assert.equal(await form.locator('[name="promote_for_24h"]').isChecked(), false);
      await form.locator('#carPhotos').setInputFiles({ name: 'game-screenshot.png', mimeType: 'image/png', buffer: photo });
      assert.equal(await form.evaluate(n => n.checkValidity()), false);
      const requestCount = posts, uploadCount = uploads;
      await form.locator('button[type="submit"]').click();
      assert.equal(posts, requestCount); assert.equal(uploads, uploadCount);
      // Even bypassing browser validity must stop before an upload/request.
      await form.evaluate(n => n.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
      await page.locator('#toast').filter({ hasText: 'Выберите Car Parking' }).waitFor();
      assert.equal(posts, requestCount); assert.equal(uploads, uploadCount);
      await form.locator(`label:has([value="${game}"])`).click();
      assert.equal(await form.evaluate(n => n.checkValidity()), true);
      assert.match(await form.locator('#listingGameSelection').textContent(), /Выбрано: Car Parking/);
      if (game === 'car_parking_2') {
        await page.clock.fastForward(3500);
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
        await page.screenshot({ path: path.join(os.tmpdir(), 'autoflow-game-form-390.png'), animations: 'disabled' });
      }
      await form.locator('button[type="submit"]').click();
      await page.locator('[data-view="market"]').waitFor({ state: 'visible' });
      assert.equal(listings.at(-1).game_version, game);
      assert.equal(uploads, uploadCount + 1);
    }
    await page.reload();
    await page.locator('#marketCars [data-listing-card="new-2"]').waitFor();
    assert.equal(await page.locator('#marketCars [data-listing-card="new-2"] .listing-game-badge').textContent(), 'Car Parking 2');
    await page.locator('.bottom-nav [data-nav-target="profile"]').click();
    const own = page.locator('.profile-mini-card').filter({ has: page.locator('[data-edit-listing="new-2"]') });
    await own.waitFor(); assert.match(await own.textContent(), /Car Parking 2/);
    await own.locator('[data-edit-listing]').click();
    assert.equal(await page.locator('#carForm [name="game_version"]:checked').inputValue(), 'car_parking_2');
    await page.locator('#carForm #promoteRow').click();
    assert.equal(await page.locator('#carForm [name="promote_for_24h"]').isChecked(), false);
    await page.locator('#carForm [name="description"]').fill('Сохранение без потери игры');
    await page.locator('#carForm button[type="submit"]').click();
    await page.locator('[data-view="market"]').waitFor({ state: 'visible' });
    assert.equal(listings.at(-1).game_version, 'car_parking_2');
    assert.equal(listings.at(-1).description, 'Сохранение без потери игры');
    assert.equal(uploads, 2, 'Editing without new photos does not upload again');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);
    console.log('390px: CP1/CP2 publish + upload, required choice, no request on invalid choice, edit/reopen/profile/detail, pin expiry/no resizing OK');
    await context.close();
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
