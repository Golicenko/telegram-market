const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "js", "app.js"), "utf8");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "css", "style.css"), "utf8");

test("chat uses visual viewport and Telegram viewport events", () => {
  assert.match(app, /visualViewport/);
  assert.match(app, /viewportChanged/);
  assert.match(css, /--chat-viewport-height/);
  assert.match(html, /viewport-fit=cover/);
  assert.match(app, /telegram\?\.viewportHeight/);
  assert.doesNotMatch(app, /telegram\?\.viewportStableHeight/);
});

test("mobile conversation is edge anchored without the half-screen transform", () => {
  assert.match(css, /\.chat-view\{top:var\(--chat-viewport-top,0px\);right:0;bottom:auto;left:0;inset-inline:0;width:100%;max-width:none;transform:none/);
  assert.doesNotMatch(css, /\.chat-view\{inset:auto auto auto 50%/);
  assert.match(css, /overflow-wrap:anywhere/);
});

test("composer preserves text on errors and prevents double submit", () => {
  assert.match(app, /client_message_id: clientMessageId/);
  assert.match(app, /button\.disabled = true/);
  assert.match(app, /input\.value = body/);
  assert.match(html, /<textarea id="chatInput"/);
});

test("read receipts depend on backend is_read", () => {
  assert.match(app, /message\.is_read \? "✓✓" : "✓"/);
  assert.match(app, /markConversationRead/);
});

test("avatars and usernames have optional fallbacks", () => {
  assert.match(app, /other\.name \|\| "Пользователь"/);
  assert.match(app, /other\.username \?/);
  assert.match(app, /other\.photo_url/);
});
