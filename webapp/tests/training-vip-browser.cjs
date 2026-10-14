// Actual application DOM, isolated API/Telegram fixtures. Not a live payment.
const {chromium} = require('playwright');
const http = require('node:http'), fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.resolve(__dirname,'..');
const server = http.createServer((req,res)=>{
  const pathname = new URL(req.url,'http://test').pathname;
  const file = path.resolve(root,'.'+(pathname==='/'?'/index.html':pathname));
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}
  res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css'})[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    for(const width of [320,360,390,430]){
      const page=await browser.newPage({viewport:{width,height:780},isMobile:true,hasTouch:true});
      const errors=[], queries=[]; let order=null, posts=0, cancelled=0, backendPaid=false, edits=0, legacyPins=0;
      const user={id:'seller',telegram_id:1,first_name:'Длинное имя '.repeat(6),role:'admin'};
      const wallet={available_balance:2,frozen_balance:0,total_earned:0};
      const listing={id:'car',seller_id:'seller',seller:{...user},brand:'BMW',model:'M5',listing_type:'regular',game_version:'car_parking_2',status:'active',price_af_coins:100,power_hp:600,max_speed_kph:300,images:[],pinned:false,description:'Описание',created_at:new Date().toISOString()};
      page.on('pageerror',error=>errors.push(error.message));
      await page.addInitScript(()=>{window.Telegram={WebApp:{initData:'isolated-fixture',ready(){},expand(){},onEvent(){},BackButton:{show(){},hide(){},onClick(){}},openInvoice(_url,callback){window.invoiceCallback=callback;window.invoiceOpened=(window.invoiceOpened||0)+1;}}};});
      await page.route(/^https:/,route=>route.abort());
      await page.route('**/api/**',async route=>{
        const url=new URL(route.request().url()), endpoint=url.pathname.slice(4), method=route.request().method();let body=[];
        if(endpoint==='/me')body={user,wallet};
        else if(endpoint==='/profile')body={user,wallet,active_listings:[listing],sold_listings:[],purchases:[],active_deals:[],deals:[],deal_threads:[],conversations:[],wallet_transactions:[],withdrawals:[]};
        else if(endpoint==='/content/unseen')body={unique:{unseen_count:0},training:{unseen_count:0}};
        else if(endpoint==='/conversations/unread-summary')body={total_unread:0,conversations:[]};
        else if(endpoint==='/listings')body=url.searchParams.get('listing_type')==='unique'?[]:[listing];
        else if(endpoint==='/listings/car'){if(method==='PATCH')edits++;body=listing;}
        else if(endpoint==='/listings/car/promote'){legacyPins++;body=listing;}
        else if(endpoint==='/vip/quote')body={cost_af:5,balance_af:2,stars:3,duration_hours:24,af_per_star:1,rounding_credit_af:0};
        else if(endpoint==='/vip/orders'&&method==='POST'){posts++;order={id:'vip-one',status:'awaiting_payment',cost_af:5,balance_af:2,stars:3,duration_hours:24,invoice_url:'https://t.me/$fixture',pinned_until:'2026-10-15T10:00:00Z'};body=order;}
        else if(endpoint==='/vip/orders/vip-one')body={...order,status:backendPaid?'completed':order.status};
        else if(endpoint==='/vip/orders/vip-one/cancel'){cancelled++;order.status='cancelled';body=order;}
        else if(endpoint==='/admin/training-analytics'){
          queries.push(url.search);
          const item={id:'00000000-0000-0000-0000-000000000001',number:'00000000-0000-0000-0000-000000000001',title:'GameGuardian Android',buyer_name:'<img src=x onerror=alert(1)> Длинное имя '.repeat(5),buyer_id:'00000000-0000-0000-0000-000000000002',buyer_username:null,profile_url:'tg://user?id=1',purchased_at:'2026-10-13T22:15:23Z',amount_af:98,payment_method:'af_balance',payment_status:'paid',fulfillment_status:'completed',delivery_status:'delivered'};
          body={items:[item],total:1,has_more:false,timezone:'Europe/Bratislava',counts:{today:1,week:1,month:1,all_time:1},summary:{paid_count:1,gross_af:98,refund_af:0,net_af:98,unique_buyers:1,unverified_count:0},products:[{product_id:'p',title:'GameGuardian Android',today:1,week:1,month:1,all_time:1,gross_af:98,refund_af:0}],definitions:['Только подтверждённые покупки.']};
        }else if(endpoint==='/publication-rules')body={free_limit:5,price_stars:5,enabled:true,active_count:1,used:1,remaining:4,payment_required:false};
        await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.locator('[data-promote-listing="car"]').first().click();
      await page.locator('#purchaseModal').waitFor();
      assert.match(await page.locator('#purchaseModal').innerText(),/С баланса: 2 AF.*Доплатить: 3 ⭐/);
      await page.locator('#purchaseModalAction').dblclick();
      await page.waitForFunction(()=>window.invoiceOpened===1);
      assert.equal(posts,1);
      await page.evaluate(()=>window.invoiceCallback('cancelled'));
      await page.waitForFunction(()=>document.querySelector('#purchaseModalNote').textContent.includes('Резерв AF освобождён'));
      assert.equal(cancelled,1);
      await page.locator('#purchaseModalAction').click();
      await page.waitForFunction(()=>window.invoiceOpened===2);
      await page.evaluate(()=>window.invoiceCallback('paid'));
      assert.equal(await page.locator('#purchaseModal').isVisible(),true); // UI callback alone is not success.
      backendPaid=true;
      await page.locator('#purchaseModal').waitFor({state:'hidden'});
      await page.locator('[data-edit-listing="car"]').first().click();
      await page.locator('#carForm button[type=submit]').click();
      await page.locator('#purchaseModal').waitFor();
      assert.equal(edits,1); assert.equal(legacyPins,0); assert.equal(posts,2);
      assert.match(await page.locator('#purchaseModal').innerText(),/Доплатить: 3 ⭐/);
      await page.evaluate(()=>document.querySelector('#purchaseModal').dispatchEvent(new Event('cancel',{cancelable:true})));
      await page.locator('#purchaseModal').waitFor({state:'hidden'});
      await page.locator('[data-nav-target="profile"]').click();
      await page.locator('[data-open-admin]').click();
      await page.locator('[data-admin-tab="training"]').click();
      await page.locator('#trainingSales').getByText('Username отсутствует',{exact:true}).waitFor();
      assert.match(await page.locator('#trainingSales').innerText(),/14\.10\.2026.*00:15:23|14\.10\.26.*00:15:23/s);
      assert.equal(await page.locator('#trainingSales img').count(),0);
      const search=page.locator('#trainingSales input[name=search]'); await search.fill('@example');
      await page.waitForFunction(()=>document.querySelector('#trainingSales button[type=submit]').disabled===false);
      await page.waitForTimeout(450);
      assert(queries.some(q=>q.includes('search=%40example')));
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      const fonts=await page.locator('#trainingSales input').evaluateAll(inputs=>inputs.map(input=>parseFloat(getComputedStyle(input).fontSize)));
      assert(fonts.every(size=>size>=16));
      await page.waitForFunction(()=>!document.querySelector('#toast').classList.contains('is-visible'));
      await page.screenshot({path:path.join(__dirname,`training-sales-${width}.png`),fullPage:false});
      if(width===390){
        await page.locator('.training-sales__card').first().scrollIntoViewIfNeeded();
        await page.screenshot({path:path.join(__dirname,'training-sale-detail-390.png'),fullPage:false});
      }
      assert.deepEqual(errors,[]);
      console.log(`${width}px: VIP split/cancel/server confirmation, training snapshots/time/search/XSS/no overflow OK`);
      await page.close();
    }
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
