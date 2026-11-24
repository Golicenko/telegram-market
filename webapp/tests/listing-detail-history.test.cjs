const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../js/app.js'),'utf8');
function harness(){
 let now=1000,modal=false;const requests=[],restores=[];
 const state={currentView:'listing-detail',previousView:'market',selectedListing:{id:'A'},navigationVersion:1,navigationStack:[{view:'market',scrollY:40}]};
 const window={scrollY:120,setTimeout(){},scrollTo(value){window.scrollY=value.top;},AutoFlowDealConfirmation:{dismiss:()=>false}};
 const c={state,window,Date:{now:()=>now},primaryViews:new Set(['market','profile']),referralsPage:null,
  document:{querySelector:()=>null},elements:{purchaseModal:{open:false}},accountSales:{dismiss:()=>false},
  listingDetail:{dismiss:()=>modal,snapshot:()=>({photoIndex:1,otherScrollLeft:90}),restore:value=>restores.push(value)},
  renderListingPage(){},recordListingView(){},track(){},notify(){},requestAnimationFrame:fn=>fn(),
  api:{async request(url){requests.push(url);return {id:url.split('/').at(-1)};}},
  async navigate(view,options={}){if(['market','profile'].includes(view)&&!options.back)state.navigationStack=[];state.currentView=view;state.navigationVersion++;window.scrollY=0;},
 };
 vm.runInNewContext(source.slice(source.indexOf('function listingNavigationEntry'),source.indexOf('function renderListingPage')),c);
 vm.runInNewContext(source.slice(source.indexOf('async function goBack'),source.indexOf('function syncBackNavigation')),c);
 return {c,state,requests,restores,tick:()=>now+=500,modal:value=>modal=value};
}
test('A → B → C → Back → B → Back → A → catalogue, preserving each prior ID and scroll',async()=>{
 const h=harness();await h.c.openListingDetails('B');h.c.window.scrollY=230;await h.c.openListingDetails('C');
 assert.deepEqual(h.state.navigationStack.map(e=>e.view==='listing-detail'?e.listingId:e.view),['market','A','B']);
 await h.c.goBack();assert.equal(h.state.selectedListing.id,'B');assert.equal(h.c.window.scrollY,230);h.tick();
 await h.c.goBack();assert.equal(h.state.selectedListing.id,'A');assert.equal(h.c.window.scrollY,120);h.tick();
 await h.c.goBack();assert.equal(h.state.currentView,'market');assert.equal(h.state.navigationStack.length,0);
 assert.equal(h.restores[0].photoIndex,1);assert.equal(h.restores[1].otherScrollLeft,90);
});
test('a failed Back read retains the target in history and never changes the selected listing',async()=>{
 const h=harness();await h.c.openListingDetails('B');h.c.api.request=async()=>{throw Error('offline');};
 await h.c.goBack();assert.equal(h.state.selectedListing.id,'B');assert.equal(h.state.navigationStack.at(-1).listingId,'A');
});
test('a late response cannot reopen a listing after navigating to another tab',async()=>{
 const h=harness();let resolve;h.c.api.request=()=>new Promise(r=>resolve=r);
 const opening=h.c.openListingDetails('B');await h.c.navigate('profile');resolve({id:'B'});
 assert.equal(await opening,false);assert.equal(h.state.currentView,'profile');assert.equal(h.state.selectedListing.id,'A');
});
test('the latest requested listing wins even when responses arrive out of order',async()=>{
 const h=harness();let resolve;h.c.api.request=url=>url.endsWith('/B')?new Promise(r=>resolve=r):Promise.resolve({id:'C'});
 const old=h.c.openListingDetails('B');await h.c.openListingDetails('C');resolve({id:'B'});await old;
 assert.equal(h.state.selectedListing.id,'C');assert.equal(h.state.navigationStack.at(-1).listingId,'A');
});
test('Telegram Back closes fullscreen first without consuming listing history',async()=>{
 const h=harness();h.modal(true);await h.c.goBack();assert.equal(h.state.navigationStack.length,1);assert.equal(h.state.currentView,'listing-detail');
});
test('abandoned Back cannot put stale listing history back into a newly selected primary tab',async()=>{
 const h=harness();await h.c.openListingDetails('B');let resolve;h.c.api.request=()=>new Promise(r=>resolve=r);
 const back=h.c.goBack();await h.c.navigate('profile');resolve({id:'A'});await back;
 assert.equal(h.state.currentView,'profile');assert.equal(h.state.navigationStack.length,0);
});
