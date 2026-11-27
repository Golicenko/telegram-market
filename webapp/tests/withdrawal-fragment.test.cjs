const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../js/app.js'), 'utf8');
class Element {
  constructor() { this.children = []; this.textContent = ''; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  text() { return this.textContent + this.children.map(node => typeof node === 'string' ? node : node.text()).join(' '); }
}
function quoteRenderer() {
  const output = new Element();
  const document = {getElementById: () => output, createElement: () => new Element()};
  const code = source.slice(source.indexOf('  function renderWithdrawalQuote('), source.indexOf('  function loadWithdrawalQuote('));
  const render = vm.runInNewContext(`${code};renderWithdrawalQuote`, {document, formatNumber: value => value});
  return {render, output};
}
test('Fragment quote displays exact server net, method, one included fee and no fake gifts', () => {
  const {render, output} = quoteRenderer();
  render({payout_method:'manual_fragment',gross_af:'75.72',fee_af:'22.72',payout_stars:53,unspent_af:'0',gift_plan:[]}, '75.72');
  const text = output.text();
  assert.match(text, /Fragment/); assert.match(text, /53 Stars/); assert.match(text, /22.72 AF/);
  assert.match(text, /Создание заявки ещё не означает выплату/);
  assert.doesNotMatch(text, /подарки стоимостью|Останется на балансе|×/);
});
test('gift quote preserves denominations, truthful remainder and gift distinction', () => {
  const {render, output} = quoteRenderer();
  render({payout_method:'manual_gift',gross_af:'21.43',fee_af:'6.43',payout_stars:15,unspent_af:'8.57',gift_plan:[{star_count:15,quantity:1}]}, '30');
  const text = output.text();
  assert.match(text, /Telegram-подарок/); assert.match(text, /1 × 15 Stars/);
  assert.match(text, /Останется на балансе/); assert.doesNotMatch(text, /Fragment/);
});
test('pending Fragment request is not reported as gift delivery or completed payment', () => {
  const code=source.slice(source.indexOf('  function withdrawalSubmissionText('),source.indexOf('  function renderTopupSelection('));
  const render=vm.runInNewContext(`${code};withdrawalSubmissionText`,{withdrawalStatusLabel:value=>value,formatNumber:value=>value});
  const result=render({public_id:'#000058',amount:'75.72',payout_method:'manual_fragment',status:'pending'});
  assert.match(result, /#000058/); assert.match(result, /ручной выплаты через Fragment/);
  assert.match(result, /выплата ещё не завершена/); assert.doesNotMatch(result, /отправки подарков/);
});
