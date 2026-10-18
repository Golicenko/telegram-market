const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../js/app.js'), 'utf8');
function code(start, end) {const offset=source.indexOf(start);return source.slice(offset, source.indexOf(end, offset+1));}
function deferred() {let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function loaderHarness(loaders) {
  let now=1000;
  const frames=[], renders=[];
  const c=vm.createContext({state:{serverAvailable:true,failedOptional:new Set()},optionalLoaders:loaders,
    window:{requestAnimationFrame(fn){frames.push(fn);return frames.length;},clearTimeout(){},setTimeout},
    Date:{now:()=>now},renderAll:keys=>renders.push(keys),updateFilterOptions(){c.filters=(c.filters||0)+1;},
    reportStartupStage(){},reportClientError(){},updateSyncStatus(){},optionalRecoveryTimer:null});
  vm.runInContext(code('function setOptionalValue','async function retryFailedOptional'),c);
  return {c,frames,renders,tick:ms=>now+=ms,flush(){while(frames.length)frames.shift()();}};
}

test('50 same-key reads share one in-flight request; unrelated key failure cannot block it',async()=>{
  const pending=deferred();let reads=0;
  const h=loaderHarness({regular:async()=>{reads++;await pending.promise;return true;},profile:async()=>{throw Error('503');}});
  const tasks=Array.from({length:50},()=>h.c.loadOptionalData(['regular'],{allowRecovery:false}));
  assert.equal(reads,1);
  const failed=await h.c.loadOptionalData(['profile'],{allowRecovery:false});assert.equal(failed[0].status,'rejected');
  pending.resolve();await Promise.all(tasks);h.flush();
  assert.equal(reads,1);assert.equal(h.renders.length,1);assert.deepEqual(Array.from(h.renders[0]),['regular']);
  assert.equal(h.c.state.failedOptional.has('regular'),false);assert.equal(h.c.state.failedOptional.has('profile'),true);
});

test('finite15second navigation cache and a fresh retry after errors',async()=>{
  let reads=0,fail=false;
  const h=loaderHarness({regular:async()=>{reads++;if(fail)throw Error('offline');return true;}});
  const opts={allowRecovery:false,maxAgeMs:15000};
  await h.c.loadOptionalData(['regular'],opts);h.tick(14999);await h.c.loadOptionalData(['regular'],opts);assert.equal(reads,1);
  h.tick(1);fail=true;await h.c.loadOptionalData(['regular'],opts);assert.equal(reads,2);
  fail=false;await h.c.loadOptionalData(['regular'],opts);assert.equal(reads,3);assert.equal(h.c.state.failedOptional.size,0);
});

test('explicit mutation refresh waits for older read then coalesces one fresh follow-up',async()=>{
  const old=deferred();let reads=0,visible;
  const h=loaderHarness({regular:async()=>{const n=++reads;if(n===1)await old.promise;visible=n===1?'pre-sale':'sold';return true;}});
  const initial=h.c.loadOptionalData(['regular'],{allowRecovery:false});
  const updates=Array.from({length:10},()=>h.c.loadOptionalData(['regular'],{allowRecovery:false,force:true}));
  assert.equal(reads,1);old.resolve();await Promise.all([initial,...updates]);
  assert.equal(reads,2);assert.equal(visible,'sold');
});

test('unchanged data keeps original array identity; only changed section is rendered',async()=>{
  const original=[{id:'one',price:100}];const h=loaderHarness({regular:async()=>h.c.setOptionalValue('regular',[{id:'one',price:100}])});
  h.c.state.regular=original;
  await h.c.loadOptionalData(['regular'],{allowRecovery:false});h.flush();assert.equal(h.renders.length,0);assert.equal(h.c.state.regular,original);
  h.c.optionalLoaders.regular=async()=>h.c.setOptionalValue('regular',[{id:'two',price:100}]);
  await h.c.loadOptionalData(['regular'],{allowRecovery:false});h.flush();assert.deepEqual(Array.from(h.renders[0]),['regular']);
});

test('profile and ad updates never rebuild catalogue, training or brand selector',()=>{
  const calls=[];
  const c=vm.createContext({renderListings:()=>calls.push('listings'),renderTraining:()=>calls.push('training'),
    renderProfile:()=>calls.push('profile'),renderBalance:()=>calls.push('balance'),renderAdvertisement:()=>calls.push('ad'),renderContentBadges:()=>calls.push('badges')});
  vm.runInContext(code('function renderAll','function renderContentBadges'),c);
  c.renderAll(['profile','advertisement']);assert.deepEqual(calls,['profile','balance','ad']);
});

test('primary navigation resolves immediately and later read cannot change the chosen screen',async()=>{
  const pending=deferred();const list=()=>({toggle(){},remove(){}});
  const views=['market','profile','training'].map(view=>({dataset:{view},classList:list()}));
  const state={currentView:'market',navigationStack:[],serverAvailable:true};
  const c=vm.createContext({state,primaryViews:new Set(['market','profile','training']),navigationDataMaxAge:15000,
    elements:{views,navButtons:[],shell:{classList:list()}},document:{body:{classList:list()}},window:{scrollTo(){}},
    track(){},syncReferralsPage(){},syncBackNavigation(){},updateFloatingChatVisibility(){},observeVisibleListingCards(){},switchProfileTab(){},
    loadOptionalData:async()=>pending.promise,reportClientError(){},updateSyncStatus(){}});
  vm.runInContext(code('async function navigate','async function openContentSection'),c);
  await c.navigate('profile');assert.equal(state.currentView,'profile');
  await c.navigate('market');assert.equal(state.currentView,'market');pending.resolve([]);await Promise.resolve();assert.equal(state.currentView,'market');
});

test('slow unread polling is single-flight and recovers after its first failure',async()=>{
  const pending=deferred();let reads=0;
  const c=vm.createContext({state:{serverAvailable:true,contentRefreshAt:Date.now(),currentView:'market',totalUnread:0},document:{hidden:false},
    api:{async request(){reads++;if(reads===1)await pending.promise;throw Error('offline');}},reportClientError(){},refreshContentBadges(){}});
  vm.runInContext(code('async function refreshUnreadMessages','function renderUnreadBadge'),c);
  const first=c.refreshUnreadMessages();await c.refreshUnreadMessages();assert.equal(reads,1);pending.resolve();await first;
  assert.equal(c.state.messagePollingBusy,false);await c.refreshUnreadMessages();assert.equal(reads,2);
});

test('badge sync never overlaps and its gate is released after a failed request',async()=>{
  const pending=deferred();let reads=0;
  const c=vm.createContext({state:{serverAvailable:true,contentSyncVersion:0},document:{hidden:false},renderContentBadges(){},
    api:{async request(){reads++;if(reads===1)await pending.promise;throw Error('offline');}}});
  vm.runInContext(code('async function refreshContentBadges','async function refreshUnreadMessages'),c);
  const first=c.refreshContentBadges();await c.refreshContentBadges();assert.equal(reads,1);pending.resolve();await first;
  assert.equal(c.state.contentBadgeLoading,false);await c.refreshContentBadges();assert.equal(reads,2);
});

test('confirmed payment requests a fresh profile after any pre-payment read',async()=>{
  let refresh;
  const c=vm.createContext({state:{confirmedTopupPayments:new Set(),me:{}},
    api:{async request(){return {status:'paid',wallet:{available_balance:100}};}},renderPaymentStatus(){},renderBalance(){},
    loadOptionalData:async(keys,options)=>{refresh={keys,options};}});
  vm.runInContext(code('async function checkStarPaymentStatus','function renderPaymentStatus'),c);
  await c.checkStarPaymentStatus('confirmed');
  assert.equal(refresh.options.force,true);assert.deepEqual(Array.from(refresh.keys),['profile']);
  assert.equal(c.state.confirmedTopupPayments.has('confirmed'),true);
});

test('confirmed training purchase refreshes library and profile after older reads',async()=>{
  let refresh;
  const c=vm.createContext({state:{},track(){},elements:{purchaseModalAction:{}},notify(){},renderBalance(){},renderTraining(){},renderTrainingLibrary(){},openTrainingPurchase:async()=>{},
    document:{getElementById(){return {}; }},api:{async request(p){return p==='/me'?{wallet:{available_balance:50}}:{id:'purchase',product_type:'personal'};}},
    loadOptionalData:async(keys,options)=>{refresh={keys,options};}});
  vm.runInContext(code('async function executeTrainingPurchase','async function payTrainingShortfall'),c);
  await c.executeTrainingPurchase({product:{id:'course'}});
  assert.equal(refresh.options.force,true);assert.deepEqual(Array.from(refresh.keys),['trainingPurchases','profile']);
});
