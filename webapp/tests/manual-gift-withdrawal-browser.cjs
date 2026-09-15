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
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    for(const width of [320,360,390,430]){
      const page=await browser.newPage({viewport:{width,height:844},isMobile:true,hasTouch:true});
      let quotes=0,reserves=0,failNext=true,paid=0;
      const errors=[],quoteIds=[];
      const user={id:'user-1',telegram_id:1,first_name:'Admin',role:'admin',username:null,photo_url:null};
      const wallet={available_balance:100,earned_balance:100,frozen_balance:0};
      const request={id:'request-1',user_id:user.id,amount:'21.43',fee_af:'6.43',payout_stars:15,gift_plan:[{gift_id:'gift-15',star_count:15,quantity:1}],payout_method:'manual_gift',details:'',status:'approved',user_name:'Buyer',user_telegram_id:2};
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
          quotes++;assert.equal(route.request().postDataJSON().amount,'30');
          body={quote_id:'quote-1',gross_af:'21.43',fee_af:'6.43',payout_stars:15,unspent_af:'8.57',gift_plan:request.gift_plan};
        }else if(endpoint==='/withdrawals'&&route.request().method()==='POST'){
          reserves++;quoteIds.push(route.request().postDataJSON().quote_id);
          assert.equal(route.request().postDataJSON().amount,undefined);
          if(failNext){failNext=false;return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Временно недоступно'})});}
          wallet.available_balance='78.57';wallet.earned_balance='78.57';wallet.frozen_balance='21.43';
          body={...request,status:'pending'};
        }else if(endpoint==='/admin/withdrawals')body=[request];
        else if(endpoint==='/admin/withdrawals/request-1/paid'){paid++;request.status='paid';body=request;}
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.locator('.header-balance').click();
      await page.locator('[data-view="wallet"] [data-open-withdraw]').click();
      const form=page.locator('#withdrawForm'),button=form.locator('button[type=submit]');
      await form.locator('[name=amount]').fill('30');
      await button.click();await page.waitForFunction(()=>!document.querySelector('#withdrawForm button').disabled);
      assert.equal(quotes,1);assert.equal(reserves,0);
      const quote=await page.locator('#withdrawQuote').textContent();
      assert.match(quote,/21[.,]43/);assert.match(quote,/6[.,]43/);assert.match(quote,/8[.,]57/);
      await button.click();await page.waitForFunction(()=>!document.querySelector('#withdrawForm button').disabled);
      await button.click({clickCount:2});await page.waitForFunction(()=>!document.querySelector('#withdrawForm button').disabled);
      assert.equal(reserves,2);assert.deepEqual(quoteIds,['quote-1','quote-1']);assert.equal(quotes,1);
      assert.match(await page.locator('#withdrawQuote').textContent(),/выплата ещё не завершена/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.locator('.bottom-nav [data-nav-target=profile]').click();
      await page.locator('[data-open-admin]').click();
      await page.locator('[data-admin-tab=withdrawals]').click();
      await page.locator('[data-withdrawal-action=paid]').click();
      assert.equal(paid,0);
      const dialog=page.locator('dialog[open]');await dialog.waitFor({state:'visible'});
      await dialog.getByRole('button',{name:'Отмена',exact:true}).click();assert.equal(paid,0);
      await page.locator('[data-withdrawal-action=paid]').click();
      await dialog.getByRole('button',{name:'Да, все подарки отправлены',exact:true}).click();
      await page.waitForFunction(()=>!document.querySelector('[data-withdrawal-action=paid]'));
      assert.equal(paid,1);assert.deepEqual(errors,[]);
      console.log(`${width}px: server quote, explicit reserve, retry same ID, no double tap, manual completion confirmation OK`);
      await page.close();
    }
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
