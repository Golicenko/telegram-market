// Real frontend with isolated API/SDK fixtures; NOT a real-device Telegram test.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, "http://test").pathname;
  const file = path.resolve(root, "." + (pathname === "/" ? "/index.html" : pathname));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.setHeader("Content-Type", ({ ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png" })[path.extname(file)] || "application/json");
  res.end(fs.readFileSync(file));
});

(async () => {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    for (const width of [320, 360, 390, 430, 768]) {
      const context = await browser.newContext({ viewport: { width, height: 844 }, isMobile: true, hasTouch: true });
      await context.route(/^https:/, route => route.fulfill({ status: 200, body: "" }));
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.addInitScript(() => {
        window.__shared = []; window.__links = []; window.__copied = [];
        Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async text => { window.__copied.push(text); } } });
        window.Telegram = { WebApp: {
          initData: "isolated-referral-fixture", ready() {}, expand() {}, onEvent() {},
          safeAreaInset: { top: 20, bottom: 34 }, contentSafeAreaInset: { top: 12 },
          BackButton: { show() {}, hide() {}, onClick() {} }, isVersionAtLeast: () => true,
          shareMessage(id, callback) { window.__shared.push(id); window.__shareCallback = callback; },
          openTelegramLink(url) { window.__links.push(url); },
        } };
      });
      let invited = 7, shareCalls = 0, errorStatus = 0, summaryError = false;
      let balance = 123.45;
      const referralUrl = "https://t.me/ActualProductionBot?startapp=aB123XYZ";
      const shareText = "Длинное настоящее имя приглашает тебя в AutoFlow Market 🚗";
      const user = { id: "fixture-user", telegram_id: 1, role: "user", first_name: "Очень длинное имя покупателя без username", photo_url: null };
      await page.route("**/api/**", async route => {
        const endpoint = new URL(route.request().url()).pathname.slice(4);
        let body = [], status = 200;
        const wallet = { available_balance: balance, frozen_balance: 0, total_earned: 0 };
        if (endpoint === "/me") body = { user, wallet };
        else if (endpoint === "/profile") body = { user, wallet, active_listings: [], sold_listings: [], wallet_transactions: [], withdrawals: [], conversations: [], deal_threads: [] };
        else if (endpoint === "/conversations/unread-summary") body = { total_unread: 0, conversations: [] };
        else if (endpoint === "/content/unseen") body = { unique: { unseen_count: 0, marker: 0 }, training: { unseen_count: 0, marker: 0 } };
        else if (endpoint === "/referrals") {
          status = summaryError ? 503 : 200;
          body = summaryError ? { detail: "RAW SERVER ERROR" } : {
            referralCode: "aB123XYZ", referralUrl, shareText, referralCount: invited, referralLimit: 20,
            commissionPercent: 5, canInvite: invited < 20,
            milestones: [{ count: 3, reward: 10, completed: invited >= 3 }, { count: 10, reward: 15, completed: invited >= 10 }, { count: 20, reward: 50, completed: invited >= 20 }],
          };
        } else if (endpoint === "/referrals/share-message") {
          shareCalls++; status = errorStatus || 200;
          body = errorStatus ? { detail: "RAW SERVER ERROR" } : { preparedMessageId: "prepared-123" };
        }
        await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      });
      const url = `http://127.0.0.1:${server.address().port}/?view=more`;
      await page.goto(url);
      await page.locator("#referralContent").waitFor({ state: "visible" });
      assert.equal(await page.locator("#referralCount").textContent(), "7");
      assert.equal(await page.locator("#referralPercent").textContent(), "5%");
      assert.equal(await page.locator(".referral-milestone.is-complete").count(), 1);
      assert(!await page.locator("#referralLimit").isVisible());
      assert.equal(await page.locator('.bottom-nav [aria-current="page"]').getAttribute("data-nav-target"), "more");
      assert(await page.locator(".app-header").isVisible());
      assert.equal(await page.locator("#referralUrl").inputValue(), referralUrl);
      assert(!/7\s*(\/|из)\s*20/.test(await page.locator(".referral-view").textContent()));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      for (const button of await page.locator(".referral-view button:visible").all()) {
        const rect = await button.boundingBox();
        assert(rect.height >= 44 && rect.width >= 44);
        assert(rect.x >= 0 && rect.x + rect.width <= width);
      }
      await page.locator(".referral-actions [data-copy-referral]").click();
      assert.deepEqual(await page.evaluate(() => window.__copied), [referralUrl]);
      assert.match(await page.locator("#toast").textContent(), /Ссылка скопирована/);
      // Clipboard permission denied: the selection fallback copies the SAME full URL.
      await page.evaluate(() => {
        navigator.clipboard.writeText = async () => { throw new Error("permission denied"); };
        document.execCommand = command => {
          if (command !== "copy") return false;
          window.__copied.push(document.activeElement.value); return true;
        };
      });
      await page.locator(".referral-link-row [data-copy-referral]").click();
      assert.deepEqual(await page.evaluate(() => window.__copied), [referralUrl, referralUrl]);
      if (width === 390) {
        await page.waitForTimeout(3200); // Let the real toast finish before the review screenshot.
        const output = path.join(os.tmpdir(), "autoflow-referrals-390.png");
        await page.screenshot({ path: output, fullPage: true });
        console.log("Screenshot: " + output);
      }
      // Double tap sends one backend request, not two native dialogs.
      await page.locator("#referralShare").evaluate(button => { button.click(); button.click(); });
      await page.waitForFunction(() => window.__shared.length === 1);
      assert.equal(shareCalls, 1);
      assert(await page.locator("#referralShare").isDisabled());
      await page.evaluate(() => window.__shareCallback(false)); // Cancel is not a success or fallback.
      await page.waitForFunction(() => !document.getElementById("referralShare").disabled);
      assert.deepEqual(await page.evaluate(() => window.__links), []);
      errorStatus = 502;
      await page.locator("#referralShare").click();
      await page.waitForFunction(() => !document.getElementById("referralShare").disabled);
      assert.match(await page.locator("#toast").textContent(), /Не удалось открыть пересылку/);
      assert.doesNotMatch(await page.locator("#toast").textContent(), /RAW|JSON|trace/);
      errorStatus = 0;
      // Older SDK can expose the method but reject its version; use fallback without POST.
      await page.evaluate(() => { window.Telegram.WebApp.isVersionAtLeast = () => false; });
      const callsBeforeFallback = shareCalls;
      await page.locator("#referralShare").click();
      const fallback = new URL(await page.evaluate(() => window.__links[0]));
      assert.equal(fallback.searchParams.get("url"), referralUrl);
      assert.equal(fallback.searchParams.get("text"), shareText);
      assert.equal(shareCalls, callsBeforeFallback);
      // Server update (not local reward math) refreshes count, badges and wallet.
      invited = 20; balance = 188.45;
      await page.locator('.bottom-nav [data-nav-target="market"]').click();
      await page.locator('[data-nav-target="more"]').click();
      await page.waitForFunction(() => document.getElementById("referralCount").textContent === "20");
      await page.waitForFunction(() => document.querySelector(".app-header [data-balance]").textContent === "188.45");
      assert.equal(await page.locator(".referral-milestone.is-complete").count(), 3);
      for (const card of await page.locator(".referral-milestone").all()) {
        assert(await card.evaluate(node => node.querySelector("span").getBoundingClientRect().right <= node.getBoundingClientRect().right - 4),
          "Completed milestone label stays inside its card");
      }
      assert(await page.locator("#referralLimit").isVisible());
      assert(await page.locator("#referralShare").isDisabled());
      for (const button of await page.locator("[data-copy-referral]").all()) assert(await button.isDisabled());
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      // Reload retains server state, no local-only counter.
      await page.reload();
      await page.waitForFunction(() => document.getElementById("referralCount").textContent === "20");
      summaryError = true;
      await page.reload();
      await page.locator("#referralRetry").waitFor({ state: "visible" });
      assert(!await page.locator("#referralContent").isVisible());
      assert.doesNotMatch(await page.locator("#referralStatus").textContent(), /RAW/);
      summaryError = false;
      await page.locator("#referralRetry").click();
      await page.locator("#referralContent").waitFor({ state: "visible" });
      assert.deepEqual(errors, []);
      console.log(`${width}px: OK — layout, safe areas, native share/cancel, double tap, copy, fallback, cap, reload, retry`);
      await context.close();
    }
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
