const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../js/app.js'),'utf8');
function code(start,end){const at=source.indexOf(start);return source.slice(at,source.indexOf(end,at+1));}
function pending(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}
for(const [name,start,end,response] of [
  ['public product','async function openTrainingProduct(id)','function normalizedTrainingDeepLink',{id:'course',published:true}],
  ['owned purchase','async function openTrainingPurchase(id)','async function openPurchasedMaterials',{purchase:{id:'purchase'}}],
])for(const fail of [false,true])test(`late ${name} ${fail?'failure':'success'} cannot navigate, notify or render after the user leaves`,async()=>{
  const request=pending(),state={navigationVersion:1,trainingPurchases:[],training:[],currentView:'training'};
  const c=vm.createContext({state,api:{request:()=>request.promise},document:{getElementById(){assert.fail('late response must not touch the DOM');}},
    navigate(){assert.fail('late response must not change the destination');},notify(){assert.fail('late errors must not interrupt the new screen');},reportClientError(){assert.fail('abandoned read is not a current screen error');}});
  vm.runInContext(code(start,end),c);
  const result=(name==='public product'?c.openTrainingProduct:c.openTrainingPurchase)('course');
  state.currentView='market';state.navigationVersion++;
  if(fail)request.reject(Object.assign(Error('no longer available'),{status:404}));else request.resolve(response);
  assert.equal(await result,false);assert.equal(state.currentView,'market');
});

test('an earlier product read cannot replace a later selection on the same section',async()=>{
  const first=pending(),second=pending(),state={navigationVersion:1,trainingPurchases:[],training:[]};let reads=0;
  const c=vm.createContext({state,api:{request:()=>++reads===1?first.promise:second.promise},document:{getElementById(){assert.fail('abandoned result must not render');}},notify(){assert.fail('abandoned result must not notify');}});
  vm.runInContext(code('async function openTrainingProduct(id)','function normalizedTrainingDeepLink'),c);
  const a=c.openTrainingProduct('a'),b=c.openTrainingProduct('b');
  first.resolve({id:'a'});assert.equal(await a,false);
  state.navigationVersion++;second.resolve({id:'b'});assert.equal(await b,false);
});
