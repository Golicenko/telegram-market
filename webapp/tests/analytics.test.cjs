const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const crypto = require("node:crypto");
function setup(reject = false) {
  const window = { crypto }, document = { visibilityState: "visible" }, calls = [];
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../js/analytics.js"), "utf8"), { window, document });
  const context = { ready: true, staff: false, platform: "ios" };
  const track = window.AutoFlowAnalytics.create({ request(url, options) { calls.push({ url, ...options, data: JSON.parse(options.body) }); return reject ? Promise.reject(new Error("offline")) : Promise.resolve(); } }, () => context);
  return { track, context, document, calls };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
test("view telemetry is deduplicated and never includes money or personal text", async () => {
  const { track, calls } = setup(); track("miniapp_opened"); track("miniapp_opened"); track("market_viewed"); track("market_viewed");
  await tick(); assert.equal(calls.length, 2);
  assert.equal(calls[0].data.session_id, calls[1].data.session_id);
  assert.deepEqual(Object.keys(calls[0].data).sort(), ["entity_id", "event_id", "event_name", "platform", "reason", "session_id", "source"].sort());
  assert.equal(calls[0].retries, 0); assert.equal(calls[0].timeoutMs, 3000);
});
test("cannot send success events and hidden/unauthenticated/staff pages do not count", async () => {
  const { track, context, document, calls } = setup();
  track("topup_success"); track("order_paid");
  context.ready = false; track("market_viewed");
  context.ready = true; context.staff = true; track("miniapp_opened");
  context.staff = false; document.visibilityState = "hidden"; track("topup_screen_opened");
  await tick(); assert.equal(calls.length, 0);
});
test("analytics failure pauses collection without throwing into checkout", async () => {
  const { track, calls } = setup(true);
  assert.equal(track("miniapp_opened"), undefined); await tick(); track("market_viewed"); await tick();
  assert.equal(calls.length, 1);
});
