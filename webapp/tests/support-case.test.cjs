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
  assert.match(flow, /let saved = await api\.request/);
  assert.match(flow, /✅ Обучение успешно изменено/);
  assert.match(flow, /training_refresh_after_save/);
  assert.ok(flow.indexOf("let saved = await api.request") < flow.indexOf("await loadAdminTraining"));
  assert.ok(flow.indexOf("await loadAdminTraining") < flow.indexOf("notify(saved.published"));
  assert.match(flow, /catch \(refreshError\) \{\s*reportClientError\("training_refresh_after_save"/);
});

test("deal support replaces the accidental dispute action and is idempotent", () => {
  assert.doesNotMatch(app, /Возникла проблема/);
  assert.match(app, /Написать в поддержку/);
  assert.match(app, /`\/deals\/\$\{dealId\}\/support`/);
  assert.match(app, /Прикрепите хотя бы один скриншот/);
  assert.match(app, /screenshot_url: screenshotUrl/);
  assert.match(app, /client_request_id: createRequestId\(\)/);
  assert.match(html, /name="deal_id"/);
});

test("admin support has filters, financial confirmation and deep-link opening", () => {
  assert.match(app, /dataset\.supportFilter|dataSupportFilter/);
  assert.match(app, /\/admin\/support\/tickets\/\$\{button\.dataset\.ticketId\}\/resolve/);
  assert.match(app, /confirmAction\(question\)/);
  assert.match(app, /support_case/);
  assert.match(app, /\?status=new/);
  assert.match(app, /new: "Новое"/);
  assert.match(app, /🛡 AutoFlow Support/);
});

test("mobile conversation owns the full viewport even with the keyboard open", () => {
  assert.match(css, /body\.chat-open \.app-shell\{width:100vw;max-width:none/);
  assert.match(css, /@media\(max-width:619px\)\{\.chat-view\{[^}]*width:var\(--chat-viewport-width,100%\);max-width:none/);
  assert.match(app, /const visualHeight = Number\(viewport\?\.height\)/);
  assert.match(app, /--chat-viewport-width/);
  assert.match(css, /\.chat-view\{display:flex;flex-direction:column;min-height:0/);
  assert.match(css, /\.messages\{flex:1 1 auto;min-height:0/);
  assert.match(css, /\.chat-compose\{margin-top:auto/);
  assert.match(app, /chatFieldFocused/);
  assert.match(app, /keyboardOpen \? visualHeight : fullHeight/);
});
