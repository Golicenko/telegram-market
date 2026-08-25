const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const app = fs.readFileSync(path.join(root, "js", "app.js"), "utf8");
const css = fs.readFileSync(path.join(root, "css", "style.css"), "utf8");

test("admin panel creates one unified text or photo broadcast", () => {
  assert.match(app, /ensureBroadcastAdminUi\(\)/);
  assert.match(app, /Каждое сообщение автоматически содержит кнопку/);
  assert.match(app, /api\.upload\(photo\)/);
  assert.match(app, /api\.request\("\/admin\/broadcasts"/);
  assert.match(app, /client_request_id: state\.pendingBroadcastRequestId/);
});

test("admin panel renders real backend progress and polls only active jobs", () => {
  assert.match(app, /Отправлено: \$\{item\.sent_count\}/);
  assert.match(app, /Ошибок: \$\{item\.failed_count\}/);
  assert.match(app, /Всего: \$\{item\.total_recipients\}/);
  assert.match(app, /\["queued", "running"\]\.includes\(item\.status\)/);
  assert.match(app, /✅ Рассылка завершена/);
  assert.match(css, /\.broadcast-admin/);
  assert.match(css, /max-width:100%;min-width:0;font-size:16px/);
});

test("failed backend launch never produces a false success message", () => {
  const submit = app.slice(app.indexOf("async function submitAdminBroadcast"), app.indexOf("async function loadAdminBroadcasts"));
  assert.match(submit, /❌ Не удалось запустить рассылку/);
  assert.match(submit, /Другая рассылка ещё отправляется/);
  assert.doesNotMatch(submit, /state\.adminBroadcasts\.push/);
});
