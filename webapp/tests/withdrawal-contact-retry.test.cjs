const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../js/app.js'), 'utf8');
const code = source.slice(source.indexOf('  async function replySupportTicket('), source.indexOf('  async function setSupportTicketStatus('));
test('support lost-response retry retains identity and blocks concurrent sends', async () => {
  const state = {}, requests = []; let release, ids = 0;
  const first = new Promise(resolve => { release = resolve; });
  const api = {request: async (url, options) => { requests.push(JSON.parse(options.body)); if(requests.length === 1){await first;throw Error('Lost response');} }};
  const reply = new Function('state','window','api','createRequestId','loadAdminSupport','notify', `${code}; return replySupportTicket;`)(state, {prompt:()=> 'Message'}, api, ()=>`id-${++ids}`, async()=>{}, ()=>{});
  const sending = reply('ticket', true);
  await reply('ticket', true); assert.equal(requests.length,1);
  release(); await sending;
  await reply('ticket', true);
  assert.equal(requests.length,2); assert.deepEqual(requests[0],requests[1]);
  assert.equal(state.supportReplyRequests['true:ticket'],undefined);
});
