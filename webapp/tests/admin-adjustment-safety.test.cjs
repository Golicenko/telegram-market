const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../js/app.js'), 'utf8');
const body = source.slice(source.indexOf('async function createBalanceAdjustment('), source.indexOf('function renderBalance()'));

test('balance command locks immediately and retries reuse the persisted request identity', () => {
  assert.ok(body.indexOf('if (state.adminBalanceBusy) return') < body.indexOf('await confirmAction'));
  assert.ok(body.indexOf('state.adminBalanceBusy = true') < body.indexOf('await confirmAction'));
  assert.match(body, /state\.adminBalanceRequest\?\.signature !== signature/);
  assert.match(body, /id: createRequestId\(\)/);
  assert.match(body, /request_id: state\.adminBalanceRequest\.id/);
  assert.ok(body.indexOf('state.adminBalanceRequest = null') > body.indexOf('await api.request'));
  assert.match(body, /finally \{ state\.adminBalanceBusy = false/);
});
