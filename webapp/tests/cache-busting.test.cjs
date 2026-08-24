const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const app = fs.readFileSync(path.join(root, "js", "app.js"), "utf8");
const css = fs.readFileSync(path.join(root, "css", "style.css"), "utf8");

test("all first-party frontend assets share a non-legacy build version", () => {
  const versions = [...html.matchAll(/(?:css\/style\.css|js\/(?:api|app)\.js)\?v=([^"&]+)/g)].map((match) => match[1]);
  assert.equal(versions.length, 3);
  assert.equal(new Set(versions).size, 1);
  assert.doesNotMatch(versions[0], /20260819-listing-validation/);
  assert.match(html, new RegExp(`<meta name="autoflow-build" content="${versions[0]}"`));
});

test("build diagnostic exposes only safe origin and pathname", () => {
  assert.match(html, /id="frontendBuildInfo"/);
  assert.match(app, /iPhone build/);
  assert.match(app, /Desktop build/);
  assert.match(app, /window\.location\.origin.*window\.location\.pathname/);
  assert.doesNotMatch(app, /frontendBuildInfo[\s\S]{0,500}location\.(?:href|search|hash)/);
  assert.match(css, /\.frontend-build-info/);
});
