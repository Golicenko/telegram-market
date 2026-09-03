const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const app = fs.readFileSync(path.join(root, "js", "app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "css", "style.css"), "utf8");

test("successful purchase opens the exact backend deal id", () => {
  assert.match(app, /finishListingPurchase\(deal\)/);
  assert.match(app, /openDealConversation\(deal\.id\)/);
  assert.match(app, /✅ Машина куплена/);
  assert.doesNotMatch(app.slice(app.indexOf("async function checkout"), app.indexOf("async function submitListing")), /deals\[0\]/);
});

test("deal delivery form persists via the backend and has a mobile-safe layout", () => {
  assert.match(html, /id="dealDeliveryPanel"/);
  assert.match(app, /`\/deals\/\$\{dealId\}\/delivery-details`/);
  assert.match(app, /buyer_game_id: gameId/);
  assert.match(app, /buyer_server: server/);
  assert.match(app, /preferred_time: preferredTime/);
  assert.match(app, /Время указывается по МСК/);
  assert.match(app, /data-copy-game-id/);
  assert.match(app, /✅ ID скопирован/);
  assert.match(app, /activeField\?\.closest\?\.\("\.chat-view"\)/);
  assert.match(app, /\["INPUT", "TEXTAREA", "SELECT"\]\.includes\(activeField\.tagName\)/);
  assert.match(css, /\.deal-delivery__form input\[type="time"\].*font-size:16px/);
  assert.match(app, /hasDeliveryDetails && \["paid", "seller_contacted"\]/);
  assert.match(app, /✅ Машина передана/);
  assert.match(app, /✅ Да, машина у меня/);
});

test("deep link is retained through bootstrap and authorized before exact chat opens", () => {
  assert.match(app, /const launchParams = new URLSearchParams\(window\.location\.search\)/);
  assert.match(app, /pendingDealDeepLink: launchParams\.get\("deal_id"\)/);
  assert.match(app, /: `\/deals\/\$\{encodeURIComponent\(dealId\)\}`/);
  assert.match(app, /api\.request\(endpoint\)/);
  assert.match(app, /openDealConversation\(details\.deal\.id\)/);
  assert.match(app, /void openDealDeepLink\(\)/);
});

test("buyer reminder deep links open one authorized deal or its existing support flow", () => {
  assert.match(app, /pendingDealBuyerEntry: launchParams\.get\("buyer_entry"\) === "1"/);
  assert.match(app, /pendingSupportDealDeepLink: launchParams\.get\("support_deal_id"\)/);
  assert.match(app, /`\/deals\/\$\{encodeURIComponent\(dealId\)\}\/buyer-entry`/);
  assert.match(app, /openDealSupport\(dealId\)/);
  assert.match(app, /void openDealSupportDeepLink\(\)/);
});
