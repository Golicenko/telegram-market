const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const app=fs.readFileSync(path.join(__dirname,'../js/app.js'),'utf8'),start=app.indexOf('async function refreshOpenConversation()'),end=app.indexOf('async function markConversationRead',start);
const implementation=app.slice(start,end).trim();
test('late response of another deal in the same conversation cannot replace selected deal',async()=>{
  const waiting=[],paths=[],state={currentView:'deal-chat',currentConversation:{id:'thread',deal:{id:'old'}},messages:[]};
  let rendered=0,read=0;
  const run=vm.runInNewContext('('+implementation+')',{URLSearchParams,state,safeArray:x=>x,api:{request:path=>{paths.push(path);return new Promise(resolve=>waiting.push(resolve));}},renderConversation:()=>rendered++,markConversationRead:()=>read++});
  const pending=run();state.currentConversation={id:'thread',deal:{id:'new'}};
  waiting[0]([]);waiting[1]({id:'thread',deal:{id:'old',status:'cancelled'}});await pending;
  assert(paths.every(p=>p.includes('deal_id=old')));
  assert.equal(state.currentConversation.deal.id,'new');assert.equal(rendered,0);assert.equal(read,0);
});
test('empty incremental poll does not reload history; read receipts still update',async()=>{
  const state={currentView:'deal-chat',currentConversation:{id:'thread',deal:{id:'old',status:'paid'}},messages:[{id:'m',is_read:false}]},paths=[];
  let rendered=0;
  const run=vm.runInNewContext('('+implementation+')',{URLSearchParams,state,safeArray:x=>x,setChatConnection(){},mergeChatMessages:existing=>existing,
    api:{request:async(path,options)=>{paths.push(path);options?.onResponse?.({headers:{get:()=> '["m"]'}});return path.includes('/messages')?[]:{id:'thread',deal:{id:'old',status:'paid'}};}},
    renderConversation:()=>rendered++,markConversationRead:async()=>{}});
  await run();assert.equal(paths.length,2);assert(paths[0].includes('after=m'));assert(state.messages[0].is_read);assert.equal(rendered,1);
});

test('concurrent incremental polls coalesce; reopening the same deal rejects an old response',async()=>{
  const state={currentView:'deal-chat',currentConversation:{id:'thread',deal:{id:'d'}},messages:[],chatOpening:1},waiting=[];
  let renders=0;
  const run=vm.runInNewContext('('+implementation+')',{URLSearchParams,state,safeArray:x=>x,api:{request:()=>new Promise(resolve=>waiting.push(resolve))},renderConversation:()=>renders++});
  const first=run();await run();assert.equal(waiting.length,2);
  state.chatOpening=2;waiting[0]([]);waiting[1]({id:'thread',deal:{id:'d',status:'cancelled'}});await first;
  assert.equal(renders,0);assert.equal(state.chatSyncBusy,null);
});

test('late old-history failure does not overwrite another chat or its loading flag',async()=>{
  const first=app.indexOf('async function loadOlderChatMessages()'),last=app.indexOf('function installMessageCopy',first);
  const state={currentView:'deal-chat',chatOpening:1,currentConversation:{id:'old',deal:{id:'deal-old'}},messages:[{id:'first'}]};
  let reject,errors=0;
  const run=vm.runInNewContext('('+app.slice(first,last).trim()+')',{URLSearchParams,state,api:{request:()=>new Promise((_resolve,r)=>reject=r)},setChatConnection:()=>errors++});
  const pending=run();state.chatOpening=2;state.currentConversation={id:'new',deal:{id:'deal-new'}};state.chatOlderScope='new-scope';
  reject(Error('old request failed'));await pending;
  assert.equal(errors,0);assert.equal(state.chatOlderScope,'new-scope');assert.equal(state.chatLoadingOlder,true);
});

test('older history and reopening preserve unconfirmed outbox photos until a server acknowledgement',()=>{
  const first=app.indexOf('function mergeChatMessages('),last=app.indexOf('function chatAtBottom(',first);
  const pending={id:'nonce',client_message_id:'nonce',local_status:'failed',local_photo_url:'blob:local',created_at:'2026-11-07T10:00:00Z'};
  const state={chatOutbox:new Map([['nonce',pending]])},revoked=[];
  const merge=vm.runInNewContext('('+app.slice(first,last).trim()+')',{state,URL:{revokeObjectURL:url=>revoked.push(url)}});
  let messages=merge([{id:'old',created_at:'2026-11-07T09:00:00Z'}],[pending]);
  assert.equal(state.chatOutbox.get('nonce'),pending);assert.deepEqual(revoked,[]);assert.equal(messages.length,2);
  messages=merge(messages,[{id:'server-id',client_message_id:'nonce',created_at:pending.created_at}]);
  assert.equal(state.chatOutbox.size,0);assert.deepEqual(revoked,['blob:local']);assert.equal(messages.length,2);assert.equal(messages[1].id,'server-id');
});
