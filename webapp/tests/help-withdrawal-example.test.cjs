const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../js/app.js'),'utf8');
function code(start,end){const at=source.indexOf(start);return source.slice(at,source.indexOf(end,at+1));}
function pending(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}
const example={budget_af:'30.00',gross_af:'21.43',fee_af:'6.43',unspent_af:'8.57',payout_stars:15,fee_percent:30,gift_plan:[{count:1,star_count:15}]};
test('help explanation preserves exact server example, single-flights and only sends a read request',async()=>{
  const request=pending(),calls=[],state={};let now=1000;
  const c=vm.createContext({state,Date:{now:()=>now},renderHelpWithdrawalExample(){},api:{request(url,options){calls.push({url,options});return request.promise;}}});
  vm.runInContext(code('function loadHelpWithdrawalExample','function renderHelpWithdrawalExample'),c);
  const first=c.loadHelpWithdrawalExample();assert.equal(c.loadHelpWithdrawalExample(),first);assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/help/withdrawal-example?amount=30');assert.equal(calls[0].options.method,undefined);assert.equal(calls[0].options.retries,0);
  request.resolve(example);await first;assert.equal(state.helpWithdrawalExample,example);assert.equal(state.helpWithdrawalLoading,null);
  now+=119999;await c.loadHelpWithdrawalExample();assert.equal(calls.length,1);
  now++;await c.loadHelpWithdrawalExample();assert.equal(calls.length,2);assert.equal(state.helpWithdrawalExample.fee_af,'6.43');
});
test('failed example releases loading and allows an explicit retry without changing wallet',async()=>{
  const wallet={earned_balance:50},state={me:{wallet}};let reads=0;
  const c=vm.createContext({state,Date,renderHelpWithdrawalExample(){},api:{async request(){if(++reads===1)throw Error('503');return example;}}});
  vm.runInContext(code('function loadHelpWithdrawalExample','function renderHelpWithdrawalExample'),c);
  await c.loadHelpWithdrawalExample();assert.equal(state.helpWithdrawalError,true);assert.equal(state.helpWithdrawalLoading,null);
  await c.loadHelpWithdrawalExample(true);assert.equal(state.helpWithdrawalError,false);assert.equal(reads,2);assert.deepEqual(state.me.wallet,{earned_balance:50});
});
test('withdrawal guide explains untouched remainder and never embeds the incorrect fixed fee from the prompt',()=>{
  const c=vm.createContext({window:{}});vm.runInContext(fs.readFileSync(path.join(__dirname,'../js/help.js'),'utf8'),c);
  const guide=c.window.AutoFlowHelp.articles({withdrawal_fee_percent:30,withdrawal_hours:24}).find(item=>item.id==='withdraw');
  assert.match(guide.title,/Как работает вывод средств/);assert.match(guide.steps.join(' '),/не списывается/);assert.match(guide.steps.join(' '),/внутренняя единица/);
  assert.match(guide.warning,/30%/);assert.doesNotMatch(guide.steps.join(' '),/Комиссия: 10 AF|5 AF.*возвращается/);
});
