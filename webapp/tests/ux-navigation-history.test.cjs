const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const script = fs.readFileSync(path.join(root, "js", "app.js"), "utf8");

test("More and Settings are removed; Profile links to support and information", () => {
  const profile = html.match(/<section class="view profile-view"[\s\S]*?<\/section>/)?.[0] || "";
  assert.doesNotMatch(html, /data-view="(?:more|settings)"/);
  assert.match(profile, /data-open-info/);
  assert.match(profile, /data-open-support/);
  assert.doesNotMatch(profile, /data-refresh-account|data-nav-target="settings"/);
  assert.match(profile, /class="profile-admin" type="button" data-open-admin data-admin-only hidden/);
  assert.match(profile, /data-open-admin/);
});

test("Profile uses user-facing wallet and navigation labels", () => {
  assert.doesNotMatch(html, /data-open-frozen/);
  assert.doesNotMatch(html, /<span>Под защитой<\/span>/);
  for (const label of ["Мои объявления", "Сделки и чаты", "Диалоги", "Пополнение", "Профиль дорабатывается"]) {
    assert.match(html, new RegExp(label));
  }
  assert.doesNotMatch(html, /data-profile-tab="training"/);
});

test("wallet history hides ledger internals and presents understandable events", () => {
  assert.match(script, /function presentWalletTransaction/);
  assert.match(script, /"platform_commission", "purchase_completed"/);
  assert.match(script, /protection_hold: "🚗 Покупка автомобиля"/);
  assert.match(script, /sale_income: "💰 Продажа автомобиля"/);
  assert.match(script, /seller_timeout_refund: "↩️ Возврат"/);
});

test("deal chat requests are scoped by exact deal id", () => {
  assert.match(script, /messages\$\{dealId \? `\?deal_id=/);
  assert.match(script, /openConversation\(conversation\.id, conversation, null, dealId\)/);
  assert.match(script, /await markConversationRead\(id, requestedDealId\)/);
});
