const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');
class Element extends EventTarget {
  constructor(tag) { super(); this.tagName = tag; this.children = []; this.open = false; }
  append(...items) { this.children.push(...items); }
  setAttribute() {} focus() {} remove() {} close() { this.open = false; }
}
function harness(request) {
  const body = new Element('body'), calls = [], notices = []; let ids = 0, refreshes = 0;
  const window = {}, document = { body, createElement: tag => new Element(tag) };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../js/seller-vip-pinning.js'), 'utf8'), { window, document, Event });
  const module = window.AutoFlowVipPinning.create({ api: { request: async (url, options) => { calls.push({ url, options }); return request(url, options); } }, openDialog: modal => { modal.open = true; }, notify: text => notices.push(text), requestId: () => `key-${++ids}`, formatDate: value => value, refresh: async () => refreshes++ });
  return { module, calls, notices, body, modal: () => body.children.at(-1), refreshes: () => refreshes };
}
const quote = { options: [{ duration_hours: 72, remaining: 1, total: 10, cost_af: 0 }], already_pinned: false };
const flush = () => new Promise(resolve => setImmediate(resolve));
test('exhausted VIP falls back to the existing paid flow without consuming money or privileges', async () => {
  const h = harness(async () => ({ options: [] })); assert.equal(await h.module.existing('car'), false); assert.equal(h.calls.length, 1);
});
test('cancel and Back make no mutation', async () => {
  const h = harness(async () => quote); const waiting = h.module.existing('car'); await flush();
  assert.equal(h.module.dismiss(), true); assert.equal(await waiting, true); assert.equal(h.calls.length, 1);
});
test('last allowance uses a single zero-AF request even with two concurrent taps', async () => {
  let finish; const h = harness(async url => url.includes('/quote') ? quote : new Promise(resolve => { finish = resolve; }));
  const waiting = h.module.existing('car'); await flush(); assert.equal(await h.module.existing('car'), true);
  h.modal().children.find(el => el.textContent?.startsWith('Использовать VIP')).onclick(); await flush();
  assert.equal(h.calls.filter(call => call.options?.method === 'POST').length, 1);
  const payload = JSON.parse(h.calls.at(-1).options.body); assert.deepEqual(payload, { listing_id: 'car', duration_hours: 72, request_id: 'key-1' });
  finish({ pinned_until: 'future' }); assert.equal(await waiting, true); assert.equal(h.refreshes(), 1);
});
test('ambiguous network failure retains request identity on retry', async () => {
  let posts = 0; const h = harness(async (url) => { if (url.includes('/quote')) return quote; if (++posts === 1) throw Error('network'); return { pinned_until: 'future' }; });
  for (let attempt = 0; attempt < 2; attempt++) { const pending = h.module.existing('car'); await flush(); h.modal().children.find(el => el.textContent?.startsWith('Использовать VIP')).onclick(); await pending; }
  const keys = h.calls.filter(call => call.options?.method === 'POST').map(call => JSON.parse(call.options.body).request_id);
  assert.deepEqual(keys, ['key-1', 'key-1']); assert.equal(h.refreshes(), 1);
});
test('initial publication choice only chooses duration; the server activation is separate', async () => {
  const h = harness(async () => ({ active_subscription: { pins_72h_remaining: 8, pins_72h_total: 10, pins_24h_remaining: 0, pins_24h_total: 0 } }));
  const pending = h.module.chooseInitial(); await flush(); h.modal().children.find(el => el.textContent?.startsWith('Использовать VIP')).onclick();
  assert.equal(await pending, 72); assert.equal(h.calls.length, 1); assert.equal(h.calls[0].url, '/seller-vip');
});
