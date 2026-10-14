// Actual application DOM; isolated API/Telegram fixtures. Not real device/Stars QA.
const {chromium} = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const server = http.createServer((req,res) => {
  const file = path.resolve(root, '.' + (new URL(req.url,'http://test').pathname === '/' ? '/index.html' : new URL(req.url,'http://test').pathname));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) {res.writeHead(404);return res.end();}
  res.setHeader('Content-Type', ({'.html':'text/html','.js':'text/javascript','.css':'text/css'})[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({...(process.env.CI ? {} : {channel:'msedge'}),headless:true});
  try {
    for (const width of [320,360,390,430]) {
      const page=await browser.newPage({viewport:{width,height:760},isMobile:true,hasTouch:true});
      const errors=[],messages=[]; let idSends=0, failId=true, starts=0, cancels=0, status='awaiting_payment';
      const user={id:'buyer',role:'user',first_name:'Покупатель'},wallet={available_balance:4,frozen_balance:0};
      const listing={id:'car',seller_id:'seller',brand:'BMW M5 F90 с длинным названием',model:'',power_hp:600,max_speed_kph:300,status:'active',listing_type:'regular',images:[],price_af_coins:100,game_version:width%3?'car_parking_1':'car_parking_2',pinned:true,pinned_until:new Date(Date.now()+60000).toISOString()};
      const deal={id:'deal',buyer_id:'buyer',seller_id:'seller',status:'paid',price_af_coins:100,buyer_game_id:null};
      const conversation={id:'thread',conversation_type:'deal',listing,deal,counterparty:{id:'seller',name:'Продавец'},offers:[]};
      page.on('pageerror',error=>errors.push(error.message));
      await page.addInitScript(()=>{
        window.keyboardHeight=760;window.invoiceResult='cancelled';window.invoices=0;
        Object.defineProperty(window.visualViewport,'height',{get:()=>window.keyboardHeight});
        window.Telegram={WebApp:{initData:'fixture',viewportHeight:760,viewportStableHeight:760,safeAreaInset:{top:24,bottom:34},contentSafeAreaInset:{top:12},ready(){},expand(){},onEvent(){},
          openInvoice(_url,callback){window.invoices++;callback(window.invoiceResult);},BackButton:{show(){},hide(){},onClick(fn){window.testBack=fn;}}}};
        window.keyboard=(height)=>{window.keyboardHeight=height;window.Telegram.WebApp.viewportHeight=height;window.visualViewport.dispatchEvent(new Event('resize'));};
      });
      await page.route(/^https:/,route=>route.abort());
      await page.route('**/api/**',async route=>{
        const endpoint=new URL(route.request().url()).pathname.slice(4);let body=[];
        if(endpoint==='/me')body={user,wallet};
        else if(endpoint==='/profile')body={user,wallet,active_listings:[listing],sold_listings:[],purchases:[],active_deals:[deal],deals:[deal],deal_threads:[],conversations:[],wallet_transactions:[],withdrawals:[]};
        else if(endpoint==='/content/unseen')body={training:{unseen_count:0},unique:{unseen_count:0}};
        else if(endpoint==='/conversations/unread-summary')body={total_unread:0,conversations:[]};
        else if(endpoint==='/deals/deal')body={deal};
        else if(endpoint==='/deals/deal/conversation'||endpoint==='/conversations/thread')body=conversation;
        else if(endpoint==='/conversations/thread/messages')body=messages;
        else if(endpoint==='/deals/deal/delivery-details'){
          idSends++; await new Promise(resolve=>setTimeout(resolve,200));
          if(failId){failId=false;return route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({detail:'Ошибка тестовой сети'})});}
          deal.buyer_game_id=route.request().postDataJSON().buyer_game_id;body=deal;
        }
        else if(endpoint==='/listings')body=[listing];
        else if(endpoint==='/vip/renewals/expiry')body={listing_id:'car',renewal_id:'expiry',title:listing.brand,price_stars:10,cost_af:10,balance_af:4,stars:6,duration_hours:72,af_per_star:1};
        else if(endpoint==='/vip/orders'&&route.request().method()==='POST'){
          starts++;assert.equal(route.request().postDataJSON().renewal_id,'expiry');
          status='awaiting_payment';body={id:'order'};
        }
        else if(endpoint==='/vip/orders/order/cancel'){cancels++;status='cancelled';body={id:'order',status};}
        else if(endpoint==='/vip/orders/order')body={id:'order',status,duration_hours:72,cost_af:10,balance_af:4,stars:6,invoice_url:'https://t.me/$fixture',pinned_until:new Date(Date.now()+259200000).toISOString()};
        await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
      });
      const base='http://127.0.0.1:'+server.address().port;
      await page.goto(base+'/?deal_id=deal');
      const input=page.locator('[name=buyer_game_id]');await input.waitFor();await input.tap();
      await page.getByRole('button',{name:'Отправить продавцу',exact:true}).click();
      assert.equal(idSends,0,'empty ID does not submit');
      await input.fill('0'.repeat(128));assert.equal((await input.inputValue()).length,128);
      await input.press('End');await input.press('Backspace');assert.equal((await input.inputValue()).length,127);
      await input.fill('00AB123');
      await input.evaluate(el=>{window.originalIdInput=el;el.setSelectionRange(2,4);});
      await page.evaluate(()=>window.keyboard(350));
      assert(await input.isVisible(),'ID must not be hidden when keyboard opens');
      assert(await input.evaluate(el=>el===document.activeElement));
      messages.push({id:'one',sender_id:'seller',message_type:'text',body:'Новое сообщение во время ввода',created_at:new Date().toISOString()});
      await page.locator('.message').filter({hasText:'Новое сообщение во время ввода'}).waitFor({state:'attached',timeout:10000});
      assert(await input.evaluate(el=>el===window.originalIdInput && el===document.activeElement && el.selectionStart===2 && el.selectionEnd===4),'polling keeps real DOM node/focus/selection');
      assert.equal(await input.inputValue(),'00AB123');
      const submit=page.getByRole('button',{name:'Отправить продавцу',exact:true});
      for(const control of [input,submit]){const b=await control.boundingBox();assert(b && b.height>=44 && b.y>=0 && b.y+b.height<=350,JSON.stringify(b));}
      await submit.click();
      try { await page.getByText('Ошибка тестовой сети',{exact:true}).waitFor({timeout:4000}); }
      catch(error){console.log({idSends,errors,toast:await page.locator('#toast').textContent(),html:await input.evaluate(el=>el.form.outerHTML)});throw error;}
      await page.waitForFunction(()=>!document.querySelector('.deal-delivery__form button').disabled);
      assert.equal(await input.inputValue(),'00AB123');
      await input.fill('00ZX987654321'); // Same browser input event as paste, preserve leading zeroes.
      await submit.evaluate(el=>{el.click();el.click();});
      try { await input.waitFor({state:'detached',timeout:10000}); }
      catch(error){console.log({idSends,deal,errors,toast:await page.locator('#toast').textContent()});throw error;}
      assert.equal(idSends,2);assert.equal(deal.buyer_game_id,'00ZX987654321');
      await page.evaluate(()=>window.keyboard(760));
      const chat=page.locator('#chatInput');await chat.tap();await chat.fill('Длинный черновик '.repeat(30));
      for(const height of [340,760,360,760]){await page.evaluate(h=>window.keyboard(h),height);assert.equal(await chat.inputValue(),'Длинный черновик '.repeat(30));}
      const small=await page.locator('input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=file]):not([type=hidden]):not([type=submit]),textarea,select').evaluateAll(nodes=>nodes.filter(el=>parseFloat(getComputedStyle(el).fontSize)<16).map(el=>el.id||el.name));
      assert.deepEqual(small,[]);
      assert(!await page.locator('meta[name=viewport]').getAttribute('content').then(v=>/user-scalable=no|maximum-scale=1/.test(v)));
      await page.goto(base+'/?vip_renewal=expiry');
      await page.getByRole('heading',{name:'Продление VIP',exact:true}).waitFor();
      await page.screenshot({path:path.join(__dirname,`vip-renewal-modal-${width}.png`),animations:'disabled'});
      assert.equal(starts,0,'opening link must never create invoice');
      assert.match(await page.locator('#purchaseModalText').textContent(),/BMW M5.*\n.*\n.*10 AF.*72 ч.*4 AF.*6 ⭐/s);
      await page.locator('#purchaseModalAction').evaluate(el=>{el.click();el.click();});
      await page.getByText('Оплата не завершена. Резерв AF освобождён, VIP не активирован.',{exact:true}).waitFor();
      assert.equal(starts,1);assert.equal(cancels,1);assert.equal(await page.evaluate(()=>window.invoices),1);
      await page.evaluate(()=>window.invoiceResult='paid');
      await page.locator('#purchaseModalAction').click();
      await page.waitForFunction(()=>window.invoices===2);status='completed';
      await page.locator('#purchaseModal').waitFor({state:'hidden',timeout:12000});
      assert.equal(starts,2);
      const card=page.locator('.car-card.is-pinned').first();await card.waitFor();
      assert(await card.locator('.car-vip-badge').isVisible());
      await page.screenshot({path:path.join(__dirname,`vip-renewal-${width}.png`),animations:'disabled'});
      const vipBox=await card.locator('.car-vip-badge').boundingBox(),gameBox=await card.locator('.listing-game-badge').boundingBox();
      assert(vipBox.y+vipBox.height<=gameBox.y);
      await page.emulateMedia({reducedMotion:'reduce'});
      assert.equal(await card.evaluate(el=>getComputedStyle(el,'::after').animationName),'none');
      const expiringCard=await card.elementHandle();
      listing.pinned_until=new Date(Date.now()-1000).toISOString();
      await page.reload();await page.locator('.car-card').first().waitFor();
      assert.equal(await page.locator('.car-card.is-pinned').count(),0);
      assert.equal(await page.locator('.car-vip-badge:visible').count(),0);
      assert(await page.locator('.car-card').count()>0,'expiry keeps listing');
      await page.locator('[data-close-purchase]').first().click();
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await expiringCard.dispose();
      assert.deepEqual(errors,[]);await page.close();
      console.log(`PASS ${width}: buyer ID focus + polling + keyboard + error/retry + drafts + all field fonts + renewal cancel/success + existing VIP/expiry`);
    }
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);process.exitCode=1;server.close();});
