const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "css", "style.css"), "utf8");
const app = fs.readFileSync(path.join(root, "js", "app.js"), "utf8");

test("training and unique navigation icons have overlapping iPhone-style badges", () => {
  assert.match(html, /id="uniqueContentBadge" hidden/);
  assert.match(html, /id="trainingContentBadge" hidden/);
  assert.match(css, /\.nav-icon-wrap\{[^}]*position:relative[^}]*overflow:visible/);
  assert.match(css, /\.content-badge\{[^}]*position:absolute[^}]*z-index:3[^}]*top:-7px[^}]*right:-10px/);
  assert.match(css, /background:#f1252e/);
  assert.match(css, /color:#fff/);
});

test("badges are server-backed, disappear at zero and cap their label at 99+", () => {
  assert.match(app, /api\.request\("\/content\/unseen"\)/);
  assert.match(app, /`\/content\/\$\{section\}\/mark-seen`/);
  assert.match(app, /badge\.hidden = count === 0/);
  assert.match(app, /count > 99 \? "99\+" : String\(count\)/);
});

test("section opening marks only the server marker loaded before the refreshed list", () => {
  const flow = app.slice(app.indexOf("async function openContentSection"), app.indexOf("async function refreshUnreadMessages"));
  assert.ok(flow.indexOf('api.request("/content/unseen")') < flow.indexOf("await refreshMarketplace()"));
  assert.ok(flow.indexOf("await refreshMarketplace()") < flow.indexOf("mark-seen"));
  assert.match(flow, /snapshot\?\.\[section\]\?\.marker/);
});

test("opening a training product records a backend view without blocking the page", () => {
  assert.match(html, /id="trainingDetailViews"/);
  assert.match(app, /`\/training\/\$\{product\.id\}\/view`/);
  assert.match(app, /reportClientError\("training_view", error\)/);
  assert.match(app, /просмотров \$\{Number\(product\.views_count \|\| 0\)\}/);
  assert.match(app, /product\.published_at \? `опубликовано/);
});
