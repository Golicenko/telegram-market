const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
function moduleUnderTest() {
  const window = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../js/admin-operations.js"), "utf8"), { window, URLSearchParams });
  return window.AutoFlowAdmin;
}
test("older search response cannot replace newer admin results", async () => {
  const admin = moduleUnderTest(), pending = [];
  const api = { request(url) { return new Promise(resolve => pending.push({ url, resolve })); } };
  const old = admin.page(api, "users", { q: "old" });
  const fresh = admin.page(api, "users", { q: "new" });
  pending[1].resolve(["new"]); assert.deepEqual(await fresh, ["new"]);
  pending[0].resolve(["old"]); assert.equal(await old, null);
  assert.match(pending[1].url, /limit=50&offset=0/);
});
test("admin paging request preserves encoded filters and propagates network error", async () => {
  const admin = moduleUnderTest(); let captured;
  await assert.rejects(admin.page({ request(url) { captured = url; throw new Error("offline"); } }, "users", { q: "A&B" }), /offline/);
  assert.equal(new URL(captured, "http://test").searchParams.get("q"), "A&B");
});
