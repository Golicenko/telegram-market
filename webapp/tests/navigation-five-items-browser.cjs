// Real frontend, isolated API/Telegram fixtures. Not a real-device Telegram test.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://test').pathname;
  const file = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg' })[path.extname(file)] || 'application/json');
  res.end(fs.readFileSync(file));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const width of [320, 360, 390, 430]) {
      const context = await browser.newContext({ viewport: { width, height: 740 }, isMobile: true, hasTouch: true });
      await context.route(/^https:/, route => route.fulfill({ status: 200, contentType: 'text/html', body: '' }));
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.addInitScript(() => {
        window.__channelLinks = [];
        window.__backVisible = false;
        window.Telegram = { WebApp: {
          initData: 'isolated-navigation-fixture', ready() {}, expand() {}, onEvent() {},
          safeAreaInset: { top: 20, bottom: 34 }, contentSafeAreaInset: { top: 12 },
          BackButton: { show() { window.__backVisible = true; }, hide() { window.__backVisible = false; }, onClick(fn) { window.__back = fn; } },
          openTelegramLink(url) { window.__channelLinks.push(url); },
        } };
      });
      const user = { id: 'navigation-test-user', telegram_id: 1, first_name: 'Покупатель', username: null, photo_url: null, role: 'user' };
      const wallet = { available_balance: 100, frozen_balance: 0, total_earned: 0 };
      await page.route('**/api/**', route => {
        const endpoint = new URL(route.request().url()).pathname.slice(4);
        let body = [];
        if (endpoint === '/me') body = { user, wallet };
        else if (endpoint === '/profile') body = { user, wallet, active_listings: [], sold_listings: [], wallet_transactions: [], withdrawals: [], conversations: [], deal_threads: [] };
        else if (endpoint === '/conversations/unread-summary') body = { total_unread: 0, conversations: [] };
        else if (endpoint === '/content/unseen') body = { unique: { unseen_count: 3, marker: 3 }, training: { unseen_count: 1, marker: 1 } };
        else if (endpoint.endsWith('/mark-seen')) body = { unseen_count: 0, marker: 3 };
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
      });
      const url = `http://127.0.0.1:${server.address().port}/`;
      await page.goto(url);
      await page.locator('#startupStatus').waitFor({ state: 'hidden' });
      await page.waitForTimeout(350);
      const nav = page.locator('.bottom-nav');
      const referralPage = page.locator('[data-view="more"]');
      const more = nav.locator('[data-nav-target="more"]');
      assert.deepEqual(await nav.locator('button').evaluateAll(nodes => nodes.map(n => n.dataset.navTarget)), ['unique', 'training', 'market', 'profile', 'more']);
      const geometry = await nav.evaluate(node => ({
        panel: node.getBoundingClientRect().toJSON(),
        padding: parseFloat(getComputedStyle(node).paddingBottom),
        cells: [...node.children].map(n => n.getBoundingClientRect().toJSON()),
        market: node.querySelector('.nav-market-disc').getBoundingClientRect().toJSON(),
      }));
      assert.equal(geometry.padding, 34, 'Telegram bottom safe area retained');
      assert.equal(geometry.panel.height, 102, 'Original 68px panel plus safe area; no extra height');
      assert(Math.abs(geometry.market.x + geometry.market.width / 2 - width / 2) < 0.1, 'Market at viewport center');
      for (const cell of geometry.cells) {
        assert(Math.abs(cell.width - geometry.cells[0].width) < 0.1, 'Equal-width cells');
        assert(cell.width >= 44 && cell.height >= 44, '44px touch targets');
        assert(cell.x >= 0 && cell.x + cell.width <= width, 'No overflow');
      }
      for (const icon of await nav.locator('img').all()) {
        assert(await icon.evaluate(img => img.complete && img.naturalWidth > 0));
        assert.equal(await icon.evaluate(img => getComputedStyle(img).objectFit), 'contain');
        const source = await icon.evaluate(img => ({ w: img.naturalWidth, h: img.naturalHeight }));
        const box = await icon.boundingBox();
        assert(Math.abs(box.width / box.height - source.w / source.h) < 0.002, 'Original aspect ratio');
      }
      for (const label of await nav.locator('.nav-item > span:last-child').all()) {
        const box = await label.boundingBox();
        assert(box.width <= geometry.cells[0].width && box.height < 16, 'Single-line label fits');
      }
      assert.equal(await nav.locator('#trainingContentBadge').textContent(), '1');
      assert.equal(await nav.locator('.nav-icon-wrap').first().evaluate(n => getComputedStyle(n).overflow), 'visible');
      if (width === 390) {
        const output = path.join(os.tmpdir(), 'autoflow-navigation-390.png');
        await page.screenshot({ path: output });
        console.log('Screenshot: ' + output);
      }
      for (const view of ['unique', 'training', 'market', 'profile']) {
        await nav.locator(`[data-nav-target="${view}"]`).click();
        await page.locator(`[data-view="${view}"]`).waitFor({ state: 'visible' });
        assert.equal(await nav.locator('[aria-current="page"]').getAttribute('data-nav-target'), view);
        await more.click();
        assert(await referralPage.isVisible());
        assert.equal(await page.evaluate(() => window.__backVisible), false);
        assert.equal(await nav.locator('[aria-current="page"]').getAttribute('data-nav-target'), 'more');
        assert(!await page.locator(`[data-view="${view}"]`).isVisible(), 'More is a full page');
        assert(await page.locator('.app-header').isVisible(), 'Shared header preserved');
      }
      // Rapid opening keeps one page, with no modal or overlay.
      await more.evaluate(button => { button.click(); button.click(); });
      assert.equal(await page.locator('#moreUpdatesModal').count(), 0);
      await page.evaluate(async () => { await window.__back(); await window.__back(); });
      assert(await referralPage.isVisible());
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      // Legacy ?view=more now opens the referral screen.
      await page.goto(url + '?view=more');
      await referralPage.waitFor({ state: 'visible' });
      assert(!await page.locator('[data-view="market"]').isVisible());
      assert.equal(await page.locator('[data-view="more"]').count(), 1);
      assert.deepEqual(errors, []);
      console.log(`${width}px OK: equal cells, centered Market, 4 PNGs, safe area, routes, badges, referral page/header`);
      await context.close();
    }
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
