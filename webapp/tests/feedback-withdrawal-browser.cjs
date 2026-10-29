// Actual frontend; isolated API/Telegram fixtures. Never sends a campaign or money.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'..'),evidence=path.join(__dirname,'evidence/feedback-20261029');fs.mkdirSync(evidence,{recursive:true});
const server=http.createServer((req,res)=>{const url=new URL(req.url,'http://fixture');const file=path.join(root,url.pathname==='/'?'index.html':url.pathname);
  try{res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2','.png':'image/png','.jpg':'image/jpeg'})[path.extname(file)]||'application/json');res.end(fs.readFileSync(file));}catch{res.writeHead(404);res.end();}});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({...process.env.CI?{}:{channel:'msedge'},headless:true});
try{for(const width of [320,390,430]){
  const page=await browser.newPage({viewport:{width,height:844},isMobile:true,hasTouch:true});const errors=[],quotes=[],reserves=[],campaignKeys=[];let seen=false,active=false;
  const pending=new Map(),user={id:'admin-fixture',telegram_id:900,first_name:'Тест администратора',role:'admin'},wallet={available_balance:100,earned_balance:100,purchased_balance:0,bonus_balance:0,frozen_balance:0};
  page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{window.Telegram={WebApp:{initData:'fixture-only',platform:'ios',ready(){},expand(){},onEvent(){},BackButton:{show(){},hide(){},onClick(){}}}};});
  await page.route(/^https:/,r=>r.abort());
  await page.route('**/api/**',async route=>{const req=route.request(),url=new URL(req.url()),endpoint=url.pathname.slice(4);let body=[];
    if(endpoint==='/me')body={user,wallet};
    else if(endpoint==='/profile')body={user,wallet,active_listings:[],sold_listings:[],wallet_transactions:[],withdrawals:[],deal_threads:[],conversations:[]};
    else if(endpoint==='/content/unseen')body={training:{unseen_count:0,marker:0},unique:{unseen_count:0,marker:0}};
    else if(endpoint==='/conversations/unread-summary')body={total_unread:0,conversations:[]};
    else if(endpoint==='/withdrawals/quote'){
      const amount=req.postDataJSON().amount;quotes.push(amount);
      if(amount==='30'||amount==='40')await new Promise(r=>pending.set(amount,r));
      body=amount==='30'?{quote_id:'quote30',gross_af:'21.43',fee_af:'6.43',payout_stars:15,unspent_af:'8.57',gift_plan:[{quantity:1,star_count:15}]}:
        amount==='40'?{quote_id:'quote40',gross_af:'35.72',fee_af:'10.72',payout_stars:25,unspent_af:'4.28',gift_plan:[{quantity:1,star_count:25}]}:
        {quote_id:'quote100',gross_af:'100.00',fee_af:'30.00',payout_stars:70,unspent_af:'0.00',gift_plan:[{quantity:1,star_count:25},{quantity:3,star_count:15}]};
    }else if(endpoint==='/withdrawals'&&req.method()==='POST'){reserves.push(req.postDataJSON());body={public_id:'#000001',status:'pending',amount:'35.72'};}
    else if(endpoint==='/admin/feedback')body={sent:7,received:1,new:seen?0:1,allowed:0,repeat_days:30,campaigns:active?[{id:'campaign-fixture',status:'running',created_at:'2026-10-29T10:00:00Z',total:10,sent:7,failed:0,received:1}]:[]};
    else if(endpoint==='/admin/feedback/reviews')body={has_more:false,items:seen||url.searchParams.get('filter')==='allowed'?[]:[{id:'review-fixture',name:'Тестовый пользователь',text:'<script>Не HTML</script>\nХороший выбор, но медленные фото.',consent:'pending',created_at:'2026-10-29T10:00:00Z',seen_at:null,forward:{status:'sent'}}]};
    else if(endpoint==='/admin/feedback/campaigns'){
      campaignKeys.push(req.postDataJSON().client_request_id);assert.equal(req.postDataJSON().confirmed,true);
      if(campaignKeys.length===1)return route.fulfill({status:503,contentType:'application/json',body:'{"detail":"Ответ потерян"}'});
      active=true;body={id:'campaign-fixture'};
    }else if(endpoint==='/admin/feedback/campaigns/campaign-fixture/stop'){active=false;body={status:'stopped'};}
    else if(endpoint==='/admin/feedback/reviews/review-fixture/seen'){seen=true;body={seen_at:'2026-10-29T10:30:00Z'};}
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);await page.waitForFunction(()=>document.getElementById('startupStatus').hidden);
  await page.locator('.bottom-nav [data-nav-target=profile]').click();await page.locator('[data-open-withdraw]').first().click();
  const input=page.locator('#withdrawForm [name=amount]'),output=page.locator('#withdrawQuote');
  await input.fill('30');while(!pending.has('30'))await sleep(20);
  await input.fill('40');while(!pending.has('40'))await sleep(20);
  pending.get('40')();await page.waitForFunction(()=>document.getElementById('withdrawQuote').textContent.includes('25 Stars'));
  pending.get('30')();await sleep(80);
  assert.match(await output.textContent(),/4[,.]28/);assert.doesNotMatch(await output.textContent(),/8[,.]57|15 Stars/);
  await page.locator('#withdrawForm [name=details]').fill('Комментарий не меняет сумму');await sleep(500);assert.equal(quotes.length,2);assert.equal(reserves.length,0);
  await page.locator('#withdrawForm button[type=submit]').click();assert.equal(reserves.length,1);assert.equal(reserves[0].quote_id,'quote40');
  await input.fill('100');await page.waitForFunction(()=>document.getElementById('withdrawQuote').textContent.includes('70 Stars'));
  assert.doesNotMatch(await output.textContent(),/Останется на балансе/);assert.equal(reserves.length,1);
  await page.screenshot({path:path.join(evidence,`withdrawal-${width}.png`)});
  await page.locator('.bottom-nav [data-nav-target=profile]').click();await page.locator('[data-open-admin]').click();await page.locator('[data-admin-tab=feedback]').click();
  await page.getByText('Отправлено запросов: 7',{exact:false}).waitFor();
  assert.match(await page.locator('#feedbackReviews').textContent(),/<script>Не HTML<\/script>/);assert.equal(await page.locator('#feedbackReviews script').count(),0);
  await page.screenshot({path:path.join(evidence,`feedback-${width}.png`)});
  await page.locator('[data-feedback-start]').click();let dialog=page.locator('dialog[open]');await dialog.getByRole('button',{name:'Отмена',exact:true}).click();assert.equal(campaignKeys.length,0);
  for(let i=0;i<2;i++){await page.locator('[data-feedback-start]').click();await dialog.getByRole('button',{name:'Да, начать сбор отзывов',exact:true}).click();if(!i)await page.waitForFunction(()=>!document.querySelector('[data-feedback-start]').disabled);else await page.locator('[data-feedback-stop]').waitFor();}
  assert.equal(await page.locator('[data-feedback-start]').isDisabled(),true,'an active campaign prevents starting another');
  assert.equal(campaignKeys.length,2);assert.equal(campaignKeys[0],campaignKeys[1]);
  await page.locator('[data-feedback-stop]').click();await dialog.getByRole('button',{name:'Да, остановить',exact:true}).click();await page.locator('[data-feedback-stop]').waitFor({state:'detached'});
  await page.locator('[data-feedback-seen]').click();await page.getByText('Отзывов по этому фильтру пока нет').waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);
  console.log(`${width}px: automatic quote race, no comment re-quote, matching reserve, zero remainder, feedback UI/counts, safe text, cancellation, same-key retry, stop and seen PASS`);
  await page.close();
}}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
