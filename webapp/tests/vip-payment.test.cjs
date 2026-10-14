const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../js/app.js'), 'utf8');
const code = source.slice(source.indexOf('async function payListingPromotionShortfall'), source.indexOf('async function finishListingPurchase'));
function setup(status = 'completed') {
  const requests = [], notes = [];
  const action = {disabled:false,textContent:''};
  const order = {id:'one',status,cost_af:5,balance_af:2,stars:3,invoice_url:'https://t.me/$test',pinned_until:'2026-10-15T00:00:00Z'};
  const context = {api:{async request(url,options){requests.push([url,options?.method]);if(url.endsWith('/cancel')) return {...order,status:'cancelled'};return {...order};}},
    state:{},elements:{purchaseModalAction:action,purchaseModalNote:{},purchaseModalTitle:{},purchaseModalText:{},purchaseModal:{open:true,close(){this.open=false;}}},
    telegram:{initData:'signed',openInvoice(_url, callback){callback('cancelled');}},createRequestId:()=> 'stable',
    refreshMarketplace:async()=>{},finishListingSubmission:async()=>{},notify:text=>notes.push(text),formatDate:value=>value,formatNumber:value=>String(value),
    setTimeout:callback=>callback(),Promise};
  vm.createContext(context);vm.runInContext(code,context);return{context,requests,action,notes,order};
}
test('VIP activation is backend-authoritative, never a second frontend promote call',async()=>{
  const {context,requests,notes} = setup(); const flow={listingId:'car'};
  await context.payListingPromotionShortfall(flow);
  assert.deepEqual(requests.map(r=>r[0]),['/vip/orders','/vip/orders/one']);
  assert.equal(notes.length,1); assert.equal(flow.busy,false);
});
test('cancelled Stars flow releases reservation and does not activate or report success',async()=>{
  const {context,requests,notes} = setup('awaiting_payment'); const flow={listingId:'car'};
  await context.payListingPromotionShortfall(flow);
  assert(requests.some(r=>r[0]==='/vip/orders/one/cancel'));
  assert.equal(notes.length,0); assert.equal(flow.vipOrderId,null);assert.equal(flow.requestId,null);
});
test('lost start response keeps request key for retry, pending status never means success',async()=>{
  const {context,requests,notes} = setup('paid'); const flow={listingId:'car'};
  const original=context.api.request; let fail=true;
  context.api.request=async(...args)=>{if(fail){fail=false;throw new Error('Network');}return original(...args);};
  await context.payListingPromotionShortfall(flow);assert.equal(flow.requestId,'stable');
  await context.payListingPromotionShortfall(flow);assert.equal(flow.requestId,'stable');assert.equal(notes.length,0);
  assert.equal(requests.filter(r=>r[1]==='POST').length,1);
});
