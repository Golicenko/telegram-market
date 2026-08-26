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
  assert.match(app, /✅ Покупка оплачена/);
  assert.doesNotMatch(app.slice(app.indexOf("async function checkout"), app.indexOf("async function submitListing")), /deals\[0\]/);
});

test("deal delivery form persists via the backend and has a mobile-safe layout", () => {
  assert.match(html, /id="dealDeliveryPanel"/);
  assert.match(app, /`\/deals\/\$\{dealId\}\/delivery-details`/);
  assert.match(app, /buyer_game_id: gameId/);
  assert.match(app, /preferred_time: form\.elements\.preferred_time\.value/);
  assert.match(css, /\.deal-delivery__form input\[type="time"\].*font-size:16px/);
});

test("deep link is retained through bootstrap and authorized before exact chat opens", () => {
  assert.match(app, /pendingDealDeepLink: new URLSearchParams\(window\.location\.search\)\.get\("deal_id"\)/);
  assert.match(app, /api\.request\(`\/deals\/\$\{encodeURIComponent\(dealId\)\}`\)/);
  assert.match(app, /openDealConversation\(details\.deal\.id\)/);
  assert.match(app, /void openDealDeepLink\(\)/);
});
