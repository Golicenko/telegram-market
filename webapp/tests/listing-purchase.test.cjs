const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "js", "app.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "..", "css", "style.css"), "utf8");

test("regular and unique cards expose the same server-backed purchase action", () => {
  const cardRenderer = source.slice(source.indexOf("function createListingCard"), source.indexOf("function renderTraining"));
  assert.match(cardRenderer, /buy\.dataset\.buyNow = listing\.id/);
  assert.match(cardRenderer, /buy\.disabled = listing\.status !== "active"/);
  assert.doesNotMatch(cardRenderer, /listing_type\s*===\s*"unique"[\s\S]{0,120}dataset\.buyNow/);
});

test("purchase flow uses direct checkout and an exact listing-bound top-up intent", () => {
  const purchase = source.slice(source.indexOf("async function executeSafeListingPurchase"), source.indexOf("async function payListingPromotionShortfall"));
  assert.match(purchase, /`\/listings\/\$\{flow\.listing\.id\}\/purchase`/);
  assert.match(purchase, /error\.detail\?\.code === "insufficient_af_coins"/);
  assert.match(purchase, /error\.detail\.missing_af_coins/);
  assert.match(purchase, /`\/listings\/\$\{flow\.listing\.id\}\/purchase-topup-intent`/);
  assert.match(purchase, /`\/wallet\/star-payments\/intents\/\$\{intent\.id\}\/resume-checkout`/);
  assert.doesNotMatch(purchase, /openSecondary\("topup"\)/);
});

test("payment cancellation keeps the flow recoverable without claiming a credit", () => {
  const purchase = source.slice(source.indexOf("async function payListingShortfall"), source.indexOf("async function finishListingPurchase"));
  assert.match(purchase, /invoiceStatus === "cancelled" \|\| invoiceStatus === "failed"/);
  assert.match(purchase, /Баланс не изменён/);
  assert.match(purchase, /waitForStarPayment\(intent\.id\)/);
  assert.match(purchase, /checkout_status === "listing_unavailable"/);
});

test("mobile confirmation is a real accessible dialog", () => {
  assert.match(html, /<dialog class="modal purchase-modal" id="purchaseModal">/);
  assert.match(html, /id="purchaseModalAction"/);
  assert.match(html, /data-close-purchase/);
  assert.match(css, /\.card-actions button\{[^}]*min-height:44px/);
  assert.match(css, /\.purchase-modal \.publish-button,\.purchase-modal \.ghost-button\{width:100%;min-height:46px/);
});
