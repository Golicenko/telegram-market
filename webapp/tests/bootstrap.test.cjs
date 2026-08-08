const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "..", "js", "app.js"), "utf8");

test("critical bootstrap only authenticates and loads the current user", () => {
  const critical = source.slice(source.indexOf("async function runBootstrap"), source.indexOf("const optionalLoaders"));
  assert.match(critical, /api\.request\("\/me"/);
  assert.doesNotMatch(critical, /\/listings|\/cart|\/profile|\/advertisement|Promise\.all\(/);
});

test("secondary endpoints are isolated with allSettled", () => {
  const optional = source.slice(source.indexOf("const optionalLoaders"), source.indexOf("function handleClick"));
  for (const endpoint of ["/listings?type=regular", "/listings?type=unique", "/accounts", "/cart", "/profile", "/advertisement", "/notifications"]) {
    assert.match(optional, new RegExp(endpoint.replace(/[?]/g, "\\?")));
  }
  assert.match(optional, /Promise\.allSettled/);
});

test("browser launch and global JavaScript failures have explicit handling", () => {
  assert.match(source, /Откройте AutoFlow Market через Telegram/);
  assert.match(source, /unhandledrejection/);
  assert.match(source, /window\.addEventListener\("online"/);
});
