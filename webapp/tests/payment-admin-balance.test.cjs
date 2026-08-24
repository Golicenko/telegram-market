const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "js", "app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "css", "style.css"), "utf8");

test("top-up waits for the backend payment status and never increments AF Coins locally", () => {
  const flow = app.slice(app.indexOf("async function requestStarInvoice"), app.indexOf("async function createWithdrawal"));
  assert.match(flow, /`\/wallet\/star-payments\/intents\/\$\{intentId\}`/);
  assert.match(flow, /payment\.status === "paid"/);
  assert.match(flow, /state\.me\.wallet = payment\.wallet/);
  assert.match(flow, /confirmedTopupPayments\.has\(intentId\)/);
  assert.match(flow, /confirmedTopupPayments\.add\(intentId\)/);
  assert.doesNotMatch(flow, /available_balance\s*\+=/);
  assert.doesNotMatch(flow, /available_balance\s*=\s*[^;]*\+/);
});

test("top-up exposes confirmed, pending, retry, error and cancelled states", () => {
  assert.match(app, /✅ Оплата подтверждена\s*\\nAF Coins зачислены/);
  assert.match(app, /⏳ Платёж подтверждается/);
  assert.match(app, /Не закрывайте приложение\. Обычно это занимает несколько секунд/);
  assert.match(app, /Платёж получен, но баланс пока не обновился/);
  assert.match(app, /retry\.textContent = "Проверить снова"/);
  assert.match(app, /cancelled: \["is-cancelled", "Оплата не завершена"\]/);
  assert.match(app, /loadOptionalData\(\["profile"\]/);
});

test("admin balance panel searches by normalized username before enabling adjustment", () => {
  assert.match(html, /<h2>Управление балансом пользователя<\/h2>/);
  assert.match(html, /id="adminBalanceUsername"[^>]*placeholder="@username"/);
  assert.match(app, /replace\(\/\^@\+\/, ""\)/);
  assert.match(app, /item\.user\.username[^\n]+toLowerCase\(\) === username\.toLowerCase\(\)/);
  assert.match(app, /Пользователь не найден/);
  assert.match(html, /id="balanceAdjustmentForm" hidden/);
});

test("admin adjustment uses positive mobile input, explicit direction and confirmation", () => {
  assert.match(html, /name="amount" type="number" inputmode="decimal" min="0\.01"/);
  assert.match(html, /data-balance-direction="credit">＋ Начислить/);
  assert.match(html, /data-balance-direction="debit">− Списать/);
  assert.match(app, /rawAmount <= 0/);
  assert.match(app, /state\.adminBalanceDirection === "debit" \? -rawAmount : rawAmount/);
  assert.match(app, /await confirmAction\(/);
  assert.match(app, /selected\.wallet = wallet/);
  assert.match(app, /Было: \$\{formatNumber\(before\)\} AF Coins/);
  assert.match(app, /Стало: \$\{formatNumber\(wallet\.available_balance\)\} AF Coins/);
  assert.match(app, /loadAdminFinancialHistory\(selected\.user\.id\)/);
  assert.match(css, /grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
});
