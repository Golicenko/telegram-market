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
test('late full-message fallback is also discarded after switching deal scope',async()=>{
  let release,ready;const reached=new Promise(resolve=>ready=resolve);
  const state={currentView:'deal-chat',currentConversation:{id:'thread',deal:{id:'old'}},messages:[{id:'m'}]};
  let rendered=0;
  const run=vm.runInNewContext('('+implementation+')',{URLSearchParams,state,safeArray:x=>x,setChatConnection(){},
    api:{request:path=>path.includes('/messages')?(path.includes('after=')?Promise.resolve([]):new Promise(resolve=>{release=resolve;ready();})):Promise.resolve({id:'thread',deal:{id:'old'}})},
    renderConversation:()=>rendered++,markConversationRead(){throw Error('must not mark another scope');}});
  const pending=run();await reached;state.currentConversation={id:'thread',deal:{id:'new'}};release([]);await pending;
  assert.equal(state.currentConversation.deal.id,'new');assert.equal(rendered,0);
});
