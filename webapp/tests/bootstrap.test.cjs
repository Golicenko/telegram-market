const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "js", "app.js"), "utf8");

test("critical bootstrap only authenticates and loads the current user", () => {
  const critical = source.slice(source.indexOf("async function runBootstrap"), source.indexOf("const optionalLoaders"));
  assert.match(critical, /api\.request\("\/me"/);
  assert.doesNotMatch(critical, /\/listings|\/cart|\/profile|\/advertisement|Promise\.all\(/);
  assert.match(critical, /authenticateCurrentUser/);
  assert.match(critical, /timeoutMs: 18000/);
});

test("secondary endpoints are isolated with allSettled", () => {
  const optional = source.slice(source.indexOf("const optionalLoaders"), source.indexOf("function handleClick"));
  for (const endpoint of ["/listings?type=regular", "/listings?type=unique", "/training", "/cart", "/profile", "/advertisement", "/notifications"]) {
    assert.match(optional, new RegExp(endpoint.replace(/[?]/g, "\\?")));
  }
  assert.match(optional, /Promise\.allSettled/);
});

test("browser launch and global JavaScript failures have explicit handling", () => {
  assert.match(source, /Откройте AutoFlow Market через Telegram/);
  assert.match(source, /unhandledrejection/);
  assert.match(source, /window\.addEventListener\("online"/);
  assert.doesNotMatch(source, /Запустите PostgreSQL|localhost|Сервер API не подключён/);
});

test("intro cannot permanently cover a rendered shell", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
  assert.match(html, /window\.setTimeout\(dismiss, 4500\)/);
  assert.match(html, /video\.addEventListener\("error", dismiss/);
  assert.match(source, /dismissIntro\(\)/);
});

test("optional requests render independently before allSettled completes", () => {
  const optional = source.slice(source.indexOf("async function loadOptionalData"), source.indexOf("async function retryFailedOptional"));
  assert.match(optional, /renderAll\(\)/);
  assert.match(optional, /Promise\.allSettled\(tasks\)/);
});
