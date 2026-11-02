// Production finance renderer/CSS with labelled fixtures; no real payment API.
const {chromium,webkit}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'..'),out=path.join(__dirname,'evidence/owner-finance-20261102');fs.mkdirSync(out,{recursive:true});
const server=http.createServer((req,res)=>{const p=new URL(req.url,'http://fixture').pathname;if(p!=='/'&&!fs.existsSync(path.join(root,p))){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',(p.endsWith('.css')?'text/css':p.endsWith('.js')?'text/javascript':'text/html')+'; charset=utf-8');res.end(p==='/'?'<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><link rel="stylesheet" href="/css/style.css"><body><main class="app-shell"><div class="admin-panel"><div class="admin-tabs"></div></div></main><script src="/js/admin-operations.js"></script><script src="/js/owner-finance.js"></script>':fs.readFileSync(path.join(root,p)));});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const engine=process.env.TEST_ENGINE==='webkit'?webkit:chromium;const browser=await engine.launch({headless:true,...(engine===chromium&&!process.env.CI?{channel:'msedge'}:{})});
try{for(const width of [320,390,430,1000]){const page=await browser.newPage({viewport:{width,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:'+server.address().port);
await page.evaluate(async()=>{
  const data={from_utc:'2026-11-01T23:00:00Z',until_utc_exclusive:'2026-11-02T23:00:00Z',summary:{turnover_af:'150.00',platform_income_af:'34.00',publication_income_stars:'5.00',owner_income_af:'121.00',recorded_payout_stars:'15.00',bonus_issued_af:'10.00',net_profit:null,net_label:'Недостаточно данных о внешних расходах',stars_received:'105.00',stars_returned_from_receipts_cohort:'0.00',refund_af:'0.00'},chart:{grain:'day',items:[{day:'2026-11-01',unit:'AF',amount:'10.00'},{day:'2026-11-02',unit:'AF',amount:'34.00'}]},sources:[{label:'VIP и продления',count:1,amount:'10.00',unit:'AF',category:'platform_income'}],liabilities_now:{wallets_af:{purchased_balance:'100.00',earned_balance:'200.00',bonus_balance:'10.00',purchased_frozen_balance:'30.00',earned_frozen_balance:'0.00',bonus_frozen_balance:'0.00'},withdrawals:{count:1,reserved_af:'30.00',expected_stars:15,expected_fee_af:'9.00'},unfulfilled_publications_stars:0},data_quality:{paid_withdrawals_without_fee:0,unverified_training_purchases:0},definitions:['AF и Stars не суммируются. Пополнение не прибыль.'],operations:[{at:'2026-11-02T10:00:00Z',label:'VIP',amount:'10.00',unit:'AF',reference:'test-operation'}],has_more:true};
  const refs={definition:'Только квалифицированные новые аккаунты, бонусы не выводятся.',items:[{rank:1,name:'Тестовый пользователь с очень длинным именем',username:null,invited:3,qualified:3,accrued_af:'10.00',credited_bonus_af:'10.00',profile_url:'tg://user?id=12345',contact_note:'Открытие зависит от приватности Telegram.'}]};
  data.liabilities_now.non_bonus_af='330.00';data.liabilities_now.bonus_credits_af='10.00';
  data.data_quality.unverified_car_orders=0;
  window.calls=[];window.fail=false;window.fixtureApi={request:async url=>{calls.push(url);if(fail)throw Error('Тестовый сбой сети');return url.includes('/referrals')?refs:{...data,has_more:!url.includes('offset=25')};}};
  AutoFlowAdmin.mount();document.querySelector('[data-admin-panel=finance]').hidden=false;await AutoFlowFinance.render(fixtureApi);
});
assert.equal(await page.locator('.finance-summary>.admin-metric').count(),4);
assert.equal(await page.locator('.finance-chart svg circle').count(),1);
assert(!(await page.locator('#adminFinance').innerText()).includes('undefined'));
assert.match(await page.locator('.finance-summary').textContent(),/Не рассчитан/);
assert.equal(await page.getByRole('link',{name:'Написать'}).getAttribute('href'),'tg://user?id=12345');
assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
await page.getByRole('button',{name:'Далее',exact:true}).click();assert(await page.getByText('Страница 2',{exact:true}).isVisible());
assert((await page.evaluate(()=>calls)).some(x=>x.includes('offset=25')));
await page.getByRole('button',{name:'Всё время',exact:true}).click();assert((await page.evaluate(()=>calls)).some(x=>x.includes('all_time=true')));
await page.screenshot({path:path.join(out,'finance-'+width+'.png'),fullPage:true});
await page.evaluate(()=>{window.fail=true;});await page.getByRole('button',{name:'Сегодня',exact:true}).click();await page.getByRole('alert').waitFor();assert.equal(await page.locator('table').count(),0);
await page.evaluate(()=>{window.fail=false;});await page.getByRole('button',{name:'Повторить',exact:true}).click();assert(await page.getByText('Топ-10 по приглашённым друзьям',{exact:true}).isVisible());assert.deepEqual(errors,[]);await page.close();console.log(width+'px: finance summary/units, referral contact, period/pagination, network retry and no overflow PASS');}
}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
