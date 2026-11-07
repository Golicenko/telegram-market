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
