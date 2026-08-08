const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const app = fs.readFileSync(path.join(root, "js", "app.js"), "utf8");

test("user navigation replaces accounts with training and uses the supplied GG asset", () => {
  const nav = html.match(/<nav class="bottom-nav"[\s\S]*?<\/nav>/)?.[0] || "";
  assert.match(nav, /data-nav-target="training"/);
  assert.match(nav, /images\/gg-training-icon\.jpg/);
  assert.equal(fs.existsSync(path.join(root, "images", "gg-training-icon.jpg")), true);
  assert.match(nav, />Обучение</);
  assert.doesNotMatch(nav, />Аккаунты</);
});

test("training has list, details and an admin-only editor", () => {
  assert.match(html, /data-view="training"/);
  assert.match(html, /data-view="training-detail"/);
  assert.match(html, /data-open-training data-admin-only/);
  assert.match(app, /\/admin\/training/);
  assert.match(app, /\/training\/\$\{id\}/);
});

test("training purchase is deliberately deferred", () => {
  assert.match(html, /Покупка и выдача материалов будут подключены на следующем этапе/);
  assert.match(app, /Покупка обучения будет подключена на следующем этапе/);
});
