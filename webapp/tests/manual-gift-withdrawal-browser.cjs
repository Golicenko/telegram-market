// Real frontend; isolated HTTP/Telegram fixtures, never real gift delivery.
const {chromium}=require('playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const server=http.createServer((req,res)=>{
  const name=new URL(req.url,'http://fixture').pathname;
  const file=path.resolve(root,'.'+(name==='/'?'/index.html':name));
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||fs.statSync(file).isDirectory()){res.writeHead(404);return res.end();}
  res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.jpg':'image/jpeg'})[path.extname(file)]||'application/json');res.end(fs.readFileSync(file));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({...(process.env.CI?{}:{channel:'msedge'}),headless:true});
  try{
    for(const width of [320,360,390,430]){
      const page=await browser.newPage({viewport:{width,height:844},isMobile:true,hasTouch:true});
      let quotes=0,reserves=0,failNext=true,paid=0,loseDeliveryResponse=true;
      const deliveryCommands=[];
      const errors=[],quoteIds=[];
      const user={id:'user-1',telegram_id:1,first_name:'Admin',role:'admin',username:null,photo_url:null};
      const wallet={available_balance:100,earned_balance:100,frozen_balance:0};
      const request={id:'request-1',public_number:57,public_id:'#000057',created_at:'2026-10-12T12:00:00Z',profile_url:'tg://user?id=2',user_id:user.id,amount:'42.86',fee_af:'12.86',payout_stars:30,gift_plan:[{gift_id:'gift-15',star_count:15,quantity:2}],gift_deliveries:[],gift_delivered_stars:0,gift_remaining_stars:30,payout_method:'manual_gift',details:'',status:'approved',user_name:'Buyer',user_telegram_id:2};
      page.on('pageerror',error=>errors.push(error.message));
      await page.addInitScript(()=>{window.Telegram={WebApp:{initData:'fixture',ready(){},expand(){},onEvent(){},BackButton:{show(){},hide(){},onClick(){}}}};});
      await page.route(/^https:/,route=>route.abort());
      await page.route('**/api/**',async route=>{
        const endpoint=new URL(route.request().url()).pathname.slice(4);let body=[];
        if(endpoint==='/me')body={user,wallet};
        else if(endpoint==='/profile')body={user,wallet,active_listings:[],sold_listings:[],wallet_transactions:[],withdrawals:[],deal_threads:[],conversations:[]};
        else if(endpoint==='/content/unseen')body={training:{unseen_count:0,marker:0},unique:{unseen_count:0,marker:0}};
        else if(endpoint==='/conversations/unread-summary')body={total_unread:0,conversations:[]};
        else if(endpoint==='/withdrawals/quote'){
          quotes++;assert.equal(route.request().postDataJSON().amount,'43');
          body={quote_id:'quote-1',gross_af:'42.86',fee_af:'12.86',payout_stars:30,unspent_af:'0.14',gift_plan:request.gift_plan};
        }else if(endpoint==='/withdrawals'&&route.request().method()==='POST'){
          reserves++;quoteIds.push(route.request().postDataJSON().quote_id);
          assert.equal(route.request().postDataJSON().amount,undefined);
          if(failNext){failNext=false;return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Временно недоступно'})});}
          wallet.available_balance='57.14';wallet.earned_balance='57.14';wallet.frozen_balance='42.86';
          body={...request,status:'pending'};
        }else if(endpoint==='/admin/withdrawals')body=[request];
        else if(endpoint==='/admin/withdrawals/request-1/gifts/delivered'){
          const command=route.request().postDataJSON();deliveryCommands.push(command);
          if(!request.gift_deliveries.some(row=>row.request_id===command.request_id)){
            request.gift_deliveries.push({...command,star_count:15});request.gift_delivered_stars+=15;request.gift_remaining_stars-=15;
          }
          if(loseDeliveryResponse){loseDeliveryResponse=false;return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Ответ потерян после записи'})});}
          body=request;
        }
        else if(endpoint==='/admin/withdrawals/request-1/paid'){assert.equal(request.gift_remaining_stars,0);paid++;request.status='paid';body=request;}
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.locator('.header-balance').click();
      await page.locator('[data-view="wallet"] [data-open-withdraw]').click();
      const form=page.locator('#withdrawForm'),button=form.locator('button[type=submit]');
      await form.locator('[name=amount]').fill('43');
      await button.click();await page.waitForFunction(()=>!document.querySelector('#withdrawForm button').disabled);
      assert.equal(quotes,1);assert.equal(reserves,0);
      const quote=await page.locator('#withdrawQuote').textContent();
      assert.match(quote,/42[.,]86/);assert.match(quote,/12[.,]86/);assert.match(quote,/0[.,]14/);
      await button.click();await page.waitForFunction(()=>!document.querySelector('#withdrawForm button').disabled);
      await button.click({clickCount:2});await page.waitForFunction(()=>!document.querySelector('#withdrawForm button').disabled);
      assert.equal(reserves,2);assert.deepEqual(quoteIds,['quote-1','quote-1']);assert.equal(quotes,1);
      assert.match(await page.locator('#withdrawQuote').textContent(),/выплата ещё не завершена/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.locator('.bottom-nav [data-nav-target=profile]').click();
      await page.locator('[data-open-admin]').click();
      await page.locator('[data-admin-tab=withdrawals]').click();
      await page.getByText('Вывод #000057', {exact:false}).first().waitFor();
      assert.equal(await page.locator('.admin-withdrawal a').getAttribute('href'),'tg://user?id=2');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      if(process.env.AUTOFLOW_SCREENSHOT_DIR){fs.mkdirSync(process.env.AUTOFLOW_SCREENSHOT_DIR,{recursive:true});await page.screenshot({path:path.join(process.env.AUTOFLOW_SCREENSHOT_DIR,`withdrawals-${width}.png`),fullPage:true});}
      await page.locator('[data-withdrawal-action=paid]').click();
      assert.equal(paid,0);
      const dialog=page.locator('dialog[open]');await dialog.waitFor({state:'visible'});
      await dialog.getByRole('button',{name:'Отмена',exact:true}).click();assert.equal(paid,0);
      await page.locator('.admin-withdrawal summary').click();
      let delivery=page.locator('.gift-delivery-form');
      await delivery.locator('input').nth(1).fill('receipt-first');
      await delivery.locator('button').click();
      await dialog.getByRole('button',{name:'Да, отправлены',exact:true}).click();
      await page.waitForFunction(()=>!document.querySelector('.gift-delivery-form button').disabled);
      assert.equal(deliveryCommands.length,1);assert(await delivery.locator('input').first().isDisabled());
      await delivery.locator('button').evaluate(el=>{el.click();el.click();});
      await page.waitForFunction(()=>document.querySelector('[data-withdrawal-action=paid]')?.disabled === true);
      assert.equal(deliveryCommands.length,2);assert.deepEqual(deliveryCommands[0],deliveryCommands[1]);
      assert.equal(await page.locator('[data-withdrawal-action=reject]').count(),0);
      await page.locator('.admin-withdrawal summary').click();
      delivery=page.locator('.gift-delivery-form');
      await delivery.locator('input').nth(1).fill('receipt-second');
      await delivery.locator('button').click();
      await dialog.getByRole('button',{name:'Да, отправлены',exact:true}).click();
      await page.waitForFunction(()=>document.querySelector('[data-withdrawal-action=paid]')?.disabled === false);
      assert.equal(deliveryCommands.length,3);assert.notEqual(deliveryCommands[1].request_id,deliveryCommands[2].request_id);
      await page.locator('[data-withdrawal-action=paid]').click();
      await dialog.getByRole('button',{name:'Да, все подарки отправлены',exact:true}).click();
      await page.waitForFunction(()=>!document.querySelector('[data-withdrawal-action=paid]'));
      await page.locator('.admin-withdrawal').waitFor({state:'visible'});
      assert.equal(paid,1);assert.deepEqual(errors,[]);
      console.log(`${width}px: server quote, reserve retry, partial gift records, lost-response retry same ID, final confirmation OK`);
      await page.close();
    }
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
