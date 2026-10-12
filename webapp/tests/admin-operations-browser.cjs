// Browser fixtures verify UI only; production/Telegram/payment APIs are blocked.
const { chromium } = require("playwright");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "..");
const server = http.createServer((req, res) => {
  const filename = path.join(root, new URL(req.url, "http://test").pathname.replace(/^\/$/, "/index.html"));
  if (!filename.startsWith(root + path.sep) || !fs.existsSync(filename)) { res.writeHead(404); return res.end(); }
  res.setHeader("Content-Type", filename.endsWith(".html") ? "text/html" : filename.endsWith(".js") ? "text/javascript" : filename.endsWith(".css") ? "text/css" : "application/json");
  res.end(fs.readFileSync(filename));
});
(async () => {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({ headless: true, channel: "msedge" });
  try {
    for (const width of [320, 360, 390, 430]) for (const role of ["admin", "support"]) {
      const page = await browser.newPage({ viewport: { width, height: 844 }, isMobile: true, hasTouch: true });
      const calls = [], errors = [];
      const user = { id: "admin", telegram_id: 1, first_name: "Длинное имя администратора", role: role === "admin" ? "admin" : "user" };
      const wallet = { available_balance: 0, frozen_balance: 0, total_earned: 0 };
      const tabs = role === "admin" ? ["overview", "users", "listings", "deals", "support", "withdrawals", "training", "audit", "advertisement", "broadcasts"] : ["support"];
      page.on("pageerror", error => errors.push(error.message));
      await page.addInitScript(() => { window.Telegram = { WebApp: { initData: "fixture", ready() {}, expand() {}, onEvent() {}, BackButton: { show() {}, hide() {}, onClick() {} } } }; });
      await page.route(/^https:/, route => route.abort());
      await page.route("**/api/**", async route => {
        const url = new URL(route.request().url()); const endpoint = url.pathname.slice(4); let body = [];
        if (endpoint.startsWith("/admin/")) calls.push(endpoint + url.search);
        if (endpoint === "/me") body = { user, wallet, admin_access: { role, tabs } };
        else if (endpoint === "/profile") body = { user, wallet, active_listings: [], sold_listings: [], purchases: [], active_deals: [], deals: [], conversations: [], wallet_transactions: [], withdrawals: [] };
        else if (endpoint === "/content/unseen") body = { training: { unseen_count: 0 }, unique: { unseen_count: 0 } };
        else if (endpoint === "/conversations/unread-summary") body = { total_unread: 0, conversations: [] };
        else if (endpoint === "/admin/overview") body = { timezone: "Europe/Bratislava", from_utc: "2026-10-12T22:00:00Z", until_utc_exclusive: "2026-10-13T22:00:00Z", metrics: { new_users: 7, credited_payments: 2, credited_stars: 25 }, pending_now: { withdrawals: 3, support: 1 }, definitions: { payments: "Подтверждённые оплаты" } };
        else if (endpoint === "/admin/platform-financial-summary") body = { completed_deals: 0, platform_commission_af_coins: 0 };
        else if (endpoint === "/admin/users") body = Number(url.searchParams.get("offset")) ? [] : Array.from({ length: 50 }, (_, i) => ({ user: { ...user, id: String(i) }, wallet, listings_count: 0, deals_count: 0 }));
        else if (endpoint === "/admin/audit") body = { items: [], has_more: false };
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.locator('[data-nav-target="profile"]').click();
      calls.length = 0; // Ignore the existing catalogue bootstrap, measure panel entry.
      await page.locator('[data-open-admin]').first().click();
      if (role === "admin") {
        await page.locator("#adminOverview .admin-metric").first().waitFor();
        assert.deepEqual(calls.map(value => value.split("?")[0]), ["/admin/overview"]);
        await page.screenshot({ path: path.join(__dirname, `admin-overview-${width}.png`), fullPage: true });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
        await page.locator('[data-admin-tab="users"]').click();
        await page.locator("#adminUsers .admin-record").first().waitFor();
        await page.locator("#adminUsers").getByRole("button", { name: "Далее", exact: true }).click();
        await page.locator("#adminUsers").getByText("Записей нет", { exact: true }).waitFor();
        assert(calls.some(value => value.includes("offset=50")));
        await page.locator('[data-admin-tab="audit"]').click();
        await page.locator("#adminAudit").getByText("Записей нет", { exact: true }).waitFor();
      } else {
        await page.locator("#adminSupportTickets").getByText("Обращений пока нет", { exact: true }).waitFor();
        assert.deepEqual(calls, ["/admin/support/tickets?status=new"]);
        for (const tab of ["overview", "users", "withdrawals", "audit"]) assert.equal(await page.locator(`[data-admin-tab="${tab}"]`).isVisible(), false);
      }
      assert.deepEqual(errors, []); await page.close(); console.log(`${role} ${width}px PASS`);
    }
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
