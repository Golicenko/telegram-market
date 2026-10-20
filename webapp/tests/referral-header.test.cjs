const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../js/app.js'),'utf8');
function header(resizeObserver=true){
  const name={offsetLeft:77,style:{maxWidth:'',removeProperty(){this.maxWidth='';}}},balance={offsetLeft:201},appHeader={};
  let observers=0,bindings=0;const observed=[];
  class Observer{constructor(callback){observers++;this.callback=callback;}observe(node){observed.push(node);}disconnect(){}}
  const state={currentView:'more'},window={ResizeObserver:resizeObserver?Observer:undefined,addEventListener(name,callback){assert.equal(name,'resize');bindings++;this.resize=callback;}};
  const env={state,window,ResizeObserver:Observer,document:{getElementById:id=>id==='headerAvatarName'?name:appHeader,querySelector:()=>balance}};
  const start=source.indexOf('  function syncReferralHeader('),end=source.indexOf('  function renderHelpCenter(',start);
  const sync=vm.runInNewContext(`(${source.slice(start,end).trim()})`,env);
  return{sync,state,name,balance,window,get observers(){return observers;},get bindings(){return bindings;},observed};
}
test('referral name reserves the actual wallet width for long names and large balances',()=>{
  const h=header();h.sync(true);assert.equal(h.name.style.maxWidth,'116px');
  h.balance.offsetLeft=155;h.state.layoutReferralHeader();assert.equal(h.name.style.maxWidth,'70px');
  h.balance.offsetLeft=60;h.state.layoutReferralHeader();assert.equal(h.name.style.maxWidth,'0px');
});
test('repeated More navigation reuses one observer and restores other headers',()=>{
  const h=header();for(let n=0;n<40;n++){h.sync(true);h.sync(false);}assert.equal(h.observers,1);assert.equal(h.name.style.maxWidth,'');
  h.state.currentView='market';h.state.layoutReferralHeader();assert.equal(h.name.style.maxWidth,'');
});
test('older WebViews install one passive resize fallback, not one per visit',()=>{
  const h=header(false);for(let n=0;n<40;n++){h.sync(true);h.sync(false);}assert.equal(h.observers,0);assert.equal(h.bindings,1);
  h.balance.offsetLeft=200;h.window.resize();assert.equal(h.name.style.maxWidth,'115px');
});
