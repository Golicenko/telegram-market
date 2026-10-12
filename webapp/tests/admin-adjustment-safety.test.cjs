const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../js/app.js'), 'utf8');
const body = source.slice(source.indexOf('async function createBalanceAdjustment('), source.indexOf('function renderBalance()'));

test('balance command locks immediately and retries reuse the persisted request identity', () => {
  assert.ok(body.indexOf('if (state.adminBalanceBusy) return') < body.indexOf('await confirmAction'));
  assert.ok(body.indexOf('state.adminBalanceBusy = true') < body.indexOf('await confirmAction'));
  assert.match(body, /state\.adminBalanceRequest\?\.signature !== signature/);
  assert.match(body, /id: createRequestId\(\)/);
  assert.match(body, /request_id: state\.adminBalanceRequest\.id/);
  assert.ok(body.indexOf('state.adminBalanceRequest = null') > body.indexOf('await api.request'));
  assert.match(body, /finally \{ state\.adminBalanceBusy = false/);
});

function harness(confirmAction, request) {
  const state = {adminBalanceUser:{user:{id:'user-1',username:'test'},wallet:{available_balance:100}},adminBalanceDirection:'credit'};
  const button={disabled:false};
  const form={querySelector:()=>button,reset(){}};
  const result={textContent:'',classList:{add(){},remove(){}},replaceChildren(){}};
  let nextId=0;
  const build=new Function('state','api','FormData','elements','confirmAction','createRequestId','formatNumber','setAdminBalanceLookupMessage','renderAdminBalanceUser','document','setAdminBalanceDirection','loadAdminFinancialHistory',`return (${body.trim()});`);
  const handler=build(state,{request},class {get(name){return name==='amount'?'10':'Test adjustment';}},
    {adminBalanceResult:result},confirmAction,()=>`request-${++nextId}`,String,()=>{},()=>{},
    {createElement:()=>({})},()=>{},async()=>{});
  return {state,button,submit:()=>handler({preventDefault(){},currentTarget:form})};
}

test('double submit while confirmation is open cannot send two commands', async()=>{
  let confirm;
  const confirmation=new Promise(resolve=>{confirm=resolve;});
  const sent=[];
  const ui=harness(()=>confirmation,async(_url,options)=>{sent.push(JSON.parse(options.body));return {available_balance:110};});
  const first=ui.submit();
  await ui.submit();
  assert.equal(sent.length,0);
  assert.equal(ui.button.disabled,true);
  confirm(true);
  await first;
  assert.equal(sent.length,1);
  assert.equal(ui.button.disabled,false);
});

test('lost response reuses the same key; cancelled confirmation sends no command', async()=>{
  const sent=[];
  const ui=harness(async()=>true,async(_url,options)=>{
    sent.push(JSON.parse(options.body));
    if(sent.length===1)throw new Error('Network response lost');
    return {available_balance:110};
  });
  await ui.submit();
  await ui.submit();
  assert.equal(sent.length,2);
  assert.equal(sent[0].request_id,sent[1].request_id);
  assert.equal(ui.state.adminBalanceRequest,null);
  const cancelled=harness(async()=>false,async()=>{throw new Error('Must not send');});
  await cancelled.submit();
  assert.equal(cancelled.button.disabled,false);
  assert.equal(cancelled.state.adminBalanceBusy,false);
});
