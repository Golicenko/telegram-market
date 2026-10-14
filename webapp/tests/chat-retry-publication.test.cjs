const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../js/app.js'),'utf8');
function fn(name,next) { return source.slice(source.indexOf(name),source.indexOf(next,source.indexOf(name)+1)); }

test('failed send retains identity; concurrent retry does not send twice; other chat stays untouched',async()=>{
  const pending={id:'client',client_message_id:'client',body:'secret test',conversation_id:'one',listing_id:'car',deal_id:'deal',created_at:'2026-01-01T00:00:00.000Z',sender_id:'buyer'};
  const calls=[]; let fail=true; let release;
  const state={currentConversation:{id:'one'},messages:[pending],chatOutbox:new Map([['client',pending]])};
  const c={state,renderConversation(){},setChatConnection(){},api:{async request(path,options){calls.push({path,data:JSON.parse(options.body)});if(fail)throw Error('offline');await new Promise(resolve=>release=resolve);return {...pending,id:'server',local_status:undefined,inFlight:undefined};}}};
  vm.createContext(c);
  vm.runInContext(fn('async function transmitChatMessage','function chatAtBottom'),c);
  await c.transmitChatMessage(pending); assert.equal(pending.local_status,'failed');assert.equal(state.chatOutbox.size,1);
  fail=false;const retry=c.transmitChatMessage(pending);await c.transmitChatMessage(pending);
  assert.equal(calls.length,2);assert.equal(calls[0].data.client_message_id,calls[1].data.client_message_id);
  state.currentConversation={id:'other'};state.messages=[{id:'unrelated'}];release();await retry;
  assert.equal(state.messages[0].id,'unrelated');assert.equal(state.chatOutbox.size,0);
});

test('server reconciliation removes optimistic duplicate without losing previous pages',()=>{
  const c={state:{chatOutbox:new Map()}};vm.createContext(c);vm.runInContext(fn('function mergeChatMessages','function chatAtBottom'),c);
  const previous=[{id:'old',created_at:'2020',body:'old'},{id:'local',client_message_id:'key',local_status:'failed',created_at:'2021'}];
  const result=c.mergeChatMessages(previous,[{id:'server',client_message_id:'key',created_at:'2021',body:'confirmed'}]);
  assert.equal(result.length,2);assert.equal(result[0].id,'old');assert.equal(result[1].id,'server');
});

test('paid publication polls server and never equates invoice paid callback with listing creation',async()=>{
  const calls=[]; let count=0;
  const c={state:{},telegram:{openInvoice(url,callback){assert.equal(url,'invoice');callback('paid');}},confirmPublication:async()=>true,
    notify(){},showPurchaseSuccess(){c.success=true;},loadPublicationOptions(){},setTimeout(fn){fn();},
    api:{async request(path,options){calls.push(path);if(path.endsWith('/invoice'))return {id:'draft',status:'draft',invoice_url:'invoice'};if(path==='/listings/listing')return{id:'listing'};count++;return count===1?{id:'draft',status:'draft'}:{id:'draft',status:'published',listing_id:'listing'};}}};
  vm.createContext(c);vm.runInContext(fn('async function payPublication','async function loadPublicationAdmin'),c);
  const result=await c.payPublication({id:'draft',status:'draft'});assert.equal(result.id,'listing');assert(c.success);
  assert.equal(calls.filter(path=>path.endsWith('/invoice')).length,1);assert(count>=2);
});

test('closing invoice leaves draft unpublished and never emits success',async()=>{
  const c={state:{},telegram:{openInvoice(url,callback){callback('cancelled');}},confirmPublication:async()=>true,notify(){},loadPublicationOptions(){},
    showPurchaseSuccess(){throw Error('false success');},api:{async request(){return{id:'draft',status:'draft',invoice_url:'invoice'};}}};
  vm.createContext(c);vm.runInContext(fn('async function payPublication','async function loadPublicationAdmin'),c);
  assert.equal(await c.payPublication({id:'draft',status:'draft'}),null);assert.equal(c.state.publicationPayBusy,false);
});

test('paid submission retains server listing identity for opening its detail after form reset',async()=>{
  const c={state:{},api:{async request(path){if(path==='/listings')throw {status:402,detail:{code:'publication_payment_required'}};return{id:'draft'};}},payPublication:async()=>({id:'published'})};
  vm.createContext(c);vm.runInContext(fn('async function publishWithQuota','function confirmPublication'),c);
  const submission={};await c.publishWithQuota({client_request_id:'request'},submission);
  assert.equal(submission.publishedPaidListingId,'published');
  const opened=[];Object.assign(c,{elements:{carForm:{reset(){}},photoPreview:{replaceChildren(){}}},state:{},refreshMarketplace:async()=>{},navigate:async()=>{},notify(){},openListingDetails:async id=>opened.push(id)});
  vm.runInContext(fn('async function finishListingSubmission','async function openListingPromotionTopup'),c);
  await c.finishListingSubmission(submission);assert.deepEqual(opened,['published']);
});
