const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(root, "js", "app.js"), "utf8");
const css = fs.readFileSync(path.join(root, "css", "style.css"), "utf8");

test("listing impressions require real visibility and a dwell time", () => {
  assert.match(app, /new IntersectionObserver/);
  assert.match(app, /entry\.isIntersecting && entry\.intersectionRatio >= 0\.5/);
  assert.match(app, /}, 750\)/);
  assert.match(app, /\/listings\/\$\{id\}\/view/);
  assert.doesNotMatch(app, /views_count\s*\+\+/);
});

test("public likes wait for the idempotent backend response", () => {
  assert.match(app, /method: listing\.liked_by_me \? "DELETE" : "POST"/);
  assert.match(app, /applyListingEngagement\(id, engagement\)/);
  assert.match(app, /Нельзя поставить лайк собственному объявлению/);
});

test("purchase and deal copy uses clear human language", () => {
  assert.match(app, /Купить за \$\{formatNumber\(effectivePrice\)\} AF Coins/);
  assert.match(app, /Подтвердить покупку/);
  assert.match(app, /Деньги будут под защитой до получения автомобиля/);
  assert.match(app, /✅ Покупка завершена/);
  assert.match(app, /✅ Продажа завершена/);
  assert.doesNotMatch(app, /Оплатить безопасно/);
});

test("compact engagement row cannot force horizontal scrolling", () => {
  assert.match(css, /\.car-engagement\{[^}]*display:flex/);
  assert.match(css, /\.car-engagement__like\{[^}]*min-width:42px/);
});
