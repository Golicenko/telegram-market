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

function sectionHarness(request) {
  const vm = require("node:vm");
  const state = { currentView: "unique", contentLoads: { unique: 0, training: 0 }, contentSyncVersion: 0, contentLoading: 0, failedOptional: new Set(), contentUnseen: {} };
  const context = { state, api: { request }, document: { hidden: false }, updateFilterOptions() {}, renderAll() { context.rendered = true; }, renderContentBadges() {}, loadOptionalData: async () => {} };
  vm.createContext(context);
  vm.runInContext(app.slice(app.indexOf("async function openContentSection"), app.indexOf("async function refreshContentBadges")), context);
  return context;
}

test("acknowledges the rendered snapshot, not a later unseen revision", async () => {
  let marker;
  const c = sectionHarness(async (url, options) => {
    if (url.endsWith("snapshot")) return { items: [{ id: "car" }], marker: 3 };
    assert.equal(c.rendered, true); marker = JSON.parse(options.body).marker;
    return { marker: 4, unseen_count: 1 };
  });
  await c.openContentSection("unique");
  assert.equal(marker, 3); assert.equal(c.state.contentUnseen.unique.unseen_count, 1);
  assert.equal(c.state.contentLoading, 0);
});

test("failed, hidden or abandoned catalogue load never marks content seen", async () => {
  for (const mode of ["error", "hidden", "left"]) {
    let calls = 0;
    const c = sectionHarness(async () => {
      calls++;
      if (mode === "error") throw new Error("offline");
      if (mode === "hidden") c.document.hidden = true;
      if (mode === "left") c.state.currentView = "market";
      return { items: [], marker: 4 };
    });
    if (mode === "error") await assert.rejects(c.openContentSection("unique"));
    else await c.openContentSection("unique");
    assert.equal(calls, 1); assert.equal(c.state.contentLoading, 0); assert.equal(c.rendered, undefined);
  }
});

test("late section response cannot acknowledge a superseded snapshot", async () => {
  let resolveFirst; const markers = []; let loads = 0;
  const c = sectionHarness(async (url, options) => {
    if (url.endsWith("snapshot")) return ++loads === 1 ? new Promise(resolve => { resolveFirst = resolve; }) : { items: [], marker: 4 };
    markers.push(JSON.parse(options.body).marker); return { unseen_count: 0, marker: 4 };
  });
  const first = c.openContentSection("unique");
  await c.openContentSection("unique");
  resolveFirst({ items: [], marker: 3 }); await first;
  assert.deepEqual(markers, [4]);
});

test("opening a training product records a backend view without blocking the page", () => {
  assert.match(html, /id="trainingDetailViews"/);
  assert.match(app, /`\/training\/\$\{product\.id\}\/view`/);
  assert.match(app, /reportClientError\("training_view", error\)/);
  assert.match(app, /просмотров \$\{Number\(product\.views_count \|\| 0\)\}/);
  assert.match(app, /product\.published_at \? `опубликовано/);
});
