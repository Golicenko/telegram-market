const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../js/app.js'), 'utf8');
function load(start, end, values) {
  const c = vm.createContext(values);
  vm.runInContext(source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start) + 1)), c);
  return c;
}

for (const failure of ['timeout', 'network', 'invalid_json', 'http']) {
  test(`admin ${failure}: read persisted request event after lost response, never second POST`, async () => {
    const calls = [], notices = [];
    const command = {outcome: 'complete', reason: 'Проверено', request_id: 'stable'};
    const c = load('async function sendAdminDecision', 'async function executeAdminDealControl', {
      state: {me: {user: {id: 'admin'}}}, notify: s => notices.push(s), reportClientError() {},
      api: {async request(p, opts) {
        calls.push([p, opts]);
        if (opts) throw Object.assign(new Error('lost'), {errorType: failure, status: failure === 'http' ? 500 : 0});
        return {deal: {id: 'deal', status: 'completed'}, events: [{request_id: 'stable', actor_id: 'admin', type: 'admin_complete', details: {reason: 'Проверено'}}]};
      }},
    });
    assert.equal((await c.sendAdminDecision('/admin/support/tickets/t/resolve', command, 'deal')).status, 'completed');
    assert.equal(calls.filter(x => x[1]).length, 1);
    assert.equal(calls[1][0], '/admin/deals/deal/control');
    assert.match(notices[0], /Проверяем/);
  });
}

for (const wrong of ['missing', 'actor', 'reason', 'request']) {
  test(`unknown admin result (${wrong}) stays an error, unrelated completed status is not proof`, async () => {
    const event = {request_id: 'request', actor_id: 'admin', type: 'admin_complete', details: {reason: 'reason'}};
    if (wrong === 'actor') event.actor_id = 'other';
    if (wrong === 'reason') event.details.reason = 'other';
    if (wrong === 'request') event.request_id = 'other';
    const c = load('async function sendAdminDecision', 'async function executeAdminDealControl', {
      state: {me: {user: {id: 'admin'}}}, notify() {}, reportClientError() {},
      api: {async request(p, opts) { if (opts) throw {errorType: 'timeout'}; return {deal: {status: 'completed'}, events: wrong === 'missing' ? [] : [event]}; }},
    });
    await assert.rejects(c.sendAdminDecision('/control', {action: 'complete', request_id: 'request', reason: 'reason'}, 'deal'), e => /не подтверждён/.test(e.message));
  });
}

test('known rejection is not converted to a success by reconciliation', async () => {
  let calls = 0;
  const c = load('async function sendAdminDecision', 'async function executeAdminDealControl', {
    api: {async request() { calls++; throw {status: 403, message: 'Forbidden'}; }},
  });
  await assert.rejects(c.sendAdminDecision('/control', {}, 'deal'), e => e.status === 403);
  assert.equal(calls, 1);
});

test('post-commit admin refresh failure retains explicit settlement success', async () => {
  const notices = [];
  const c = load('async function sendAdminDecision', 'async function executeAdminDealControl', {notify: x => notices.push(x), reportClientError() {}});
  await c.showAdminDecisionResult('complete', async () => { throw Error('refresh'); });
  assert.match(notices[0], /Сделка успешно завершена.*Средства начислены продавцу.*не удалось обновить/);
  assert.doesNotMatch(notices[0], /Не удалось завершить/);
});

test('publication refresh failure does not escape as a failed POST and clears submitted form once', async () => {
  const notices = []; let resets = 0;
  const c = load('async function finishListingSubmission', 'async function openListingPromotionTopup', {
    state: {pendingListingRequestId: 'saved'}, elements: {carForm: {reset() {resets++;}}},
    renderPhotoPreviews() {}, refreshMarketplace: async () => [{status: 'rejected'}], navigate: async () => {},
    notify: s => notices.push(s), reportClientError() {},
  });
  await c.finishListingSubmission({targetView: 'market'});
  assert.equal(resets, 1); assert.equal(c.state.pendingListingRequestId, null);
  assert.match(notices[0], /Объявление сохранено.*не удалось обновить/);
});

test('pending VIP after paid publication keeps form and does not throw a technical error', async () => {
  const c = load('async function publishWithQuota', 'function confirmPublication', {
    state: {}, payPublication: async () => null,
    api: {async request(p) {if (p === '/listings') throw {status: 402, detail: {code: 'publication_payment_required'}}; return {id: 'draft'};}},
  });
  assert.equal(await c.publishWithQuota({client_request_id: 'saved'}, {}), null);
});

test('VIP shortfall 402 reaches existing top-up; invoice cancellation releases reserve and preserves form', async () => {
  const submit = source.slice(source.indexOf('async function submitListing'), source.indexOf('async function finishListingSubmission'));
  assert.match(submit, /error\.detail\?\.purpose === "listing_promotion"/);
  assert.match(submit, /openListingPromotionTopup\(listingSubmission, error\)/);
  const calls = [];
  const flow = {vipOrderId: 'order', requestId: 'saved', submission: {payload: {brand: 'Car'}}};
  const c = load('async function payListingPromotionShortfall', 'async function finishListingPurchase', {
    state: {}, elements: {purchaseModalAction: {}, purchaseModalText: {}, purchaseModalNote: {}},
    telegram: {initData: 'signed', openInvoice(url, cb) {cb('cancelled');}}, formatNumber: String,
    api: {async request(p, opts) {calls.push(p);return opts ? {id: 'order', status: 'cancelled'} : {id: 'order', status: 'awaiting_payment', invoice_url: 'invoice', stars: 3, balance_af: 2, cost_af: 5};}},
  });
  await c.payListingPromotionShortfall(flow);
  assert.deepEqual(calls, ['/vip/orders/order', '/vip/orders/order/cancel']);
  assert.equal(flow.submission.payload.brand, 'Car'); assert.equal(flow.vipOrderId, null);
  assert.match(c.elements.purchaseModalNote.textContent, /Резерв AF освобождён/);
});

test('admin double tap runs one POST and retains request identity after unknown response', async () => {
  let calls = 0, release;
  const button = {disabled: false, dataset: {adminDealAction: 'complete'}};
  const state = {adminDealControl: {deal: {id: 'deal'}, seller: {first_name: 'Seller', telegram_id: 2}, buyer: {}, seller_payout: 100}};
  const c = load('async function executeAdminDealControl', 'async function loadAdminTraining', {
    state, document: {getElementById() {return {value: 'Проверено'};}}, createRequestId: () => 'stable', formatNumber: String,
    confirmCriticalAction: async () => true, notify() {}, showAdminDecisionResult: async () => {},
    sendAdminDecision: async () => {calls++; await new Promise(r => release = r); throw Error('unknown');},
  });
  const first = c.executeAdminDealControl(button);
  await Promise.resolve();
  await c.executeAdminDealControl(button);
  release(); await first;
  assert.equal(calls, 1); assert.equal(state.adminDealRequest.id, 'stable'); assert.equal(button.disabled, false);
});
