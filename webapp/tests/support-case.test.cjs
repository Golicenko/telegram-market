const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "js", "app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "css", "style.css"), "utf8");

test("training save is successful before optional refresh", () => {
  const flow = app.slice(app.indexOf("async function submitTrainingProduct"), app.indexOf("async function deleteTrainingProduct"));
  assert.match(flow, /const saved = await api\.request/);
  assert.match(flow, /notify\("Сохранено"\)/);
  assert.match(flow, /training_refresh_after_save/);
  assert.ok(flow.indexOf('notify("Сохранено")') < flow.indexOf("await loadAdminTraining"));
});

test("deal support replaces the accidental dispute action and is idempotent", () => {
  assert.doesNotMatch(app, /Возникла проблема/);
  assert.match(app, /🛟 Написать в поддержку/);
  assert.match(app, /`\/deals\/\$\{dealId\}\/support`/);
  assert.match(app, /client_request_id: crypto\.randomUUID\(\)/);
  assert.match(html, /name="deal_id"/);
});

test("admin support has filters, financial confirmation and deep-link opening", () => {
  assert.match(app, /dataset\.supportFilter|dataSupportFilter/);
  assert.match(app, /\/admin\/support\/tickets\/\$\{button\.dataset\.ticketId\}\/resolve/);
  assert.match(app, /confirmAction\(question\)/);
  assert.match(app, /support_case/);
  assert.match(app, /🛡 AutoFlow Support/);
});

test("mobile conversation owns the full viewport even with the keyboard open", () => {
  assert.match(css, /body\.chat-open \.app-shell\{width:100vw;max-width:none/);
  assert.match(css, /@media\(max-width:619px\)\{\.chat-view\{[^}]*width:100vw;max-width:100vw/);
  assert.match(app, /const visualHeight = Number\(viewport\?\.height\)/);
});
