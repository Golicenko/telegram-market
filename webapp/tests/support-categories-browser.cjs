// Real UI with isolated API fixtures, not a live Telegram/device test.
const {chromium} = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const server = http.createServer((req,res) => {
  const file = path.resolve(root, '.' + (new URL(req.url,'http://test').pathname === '/' ? '/index.html' : new URL(req.url,'http://test').pathname));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.setHeader('Content-Type', ({'.html':'text/html','.js':'text/javascript','.css':'text/css'})[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});
const categories = [['payment','💳','Оплата и баланс'],['purchase','🚗','Покупка автомобиля'],['deal','🤝','Проблема со сделкой'],['listing','📢','Объявления'],['withdrawal','⭐','Вывод средств'],['deal_details','🔄','Изменение данных сделки'],['transfer','🎮','Передача автомобиля'],['training','🎓','Обучение'],['referral','🎁','Реферальная программа'],['technical','⚙️','Техническая проблема'],['other','💬','Другое']].map(([key,icon,label])=>({key,icon,label,deal_related:['purchase','deal','deal_details','transfer'].includes(key)}));
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    for(const width of [320,360,390,430]){
      const page=await browser.newPage({viewport:{width,height:740},isMobile:true,hasTouch:true});
      let tickets=[], submitted=[]; const errors=[];
      const user={id:'buyer',telegram_id:1,first_name:'Длинное имя '.repeat(8),role:'user'};
      const wallet={available_balance:100,frozen_balance:0,total_earned:0};
      page.on('pageerror',error=>errors.push(error.message));
      await page.addInitScript(()=>{window.Telegram={WebApp:{initData:'fixture',ready(){},expand(){},onEvent(){},BackButton:{show(){},hide(){},onClick(){}}}};});
      await page.route(/^https:/,route=>route.abort());
      await page.route('**/api/**',async route=>{
        const endpoint=new URL(route.request().url()).pathname.slice(4); let body=[];
        if(endpoint==='/me')body={user,wallet};
        else if(endpoint==='/profile')body={user,wallet,active_listings:[],sold_listings:[],purchases:[],active_deals:[],deals:[],deal_threads:[],conversations:[],wallet_transactions:[],withdrawals:[]};
        else if(endpoint==='/content/unseen')body={unique:{unseen_count:0},training:{unseen_count:0}};
        else if(endpoint==='/conversations/unread-summary')body={total_unread:0,conversations:[]};
        else if(endpoint==='/support/categories')body=categories;
        else if(endpoint==='/deals')body=[{id:'12345678-test-order',price_af_coins:100}];
        else if(endpoint==='/support/tickets'){
          if(route.request().method()==='POST'){
            const data=route.request().postDataJSON(); submitted.push(data);
            body={id:'abcdefgh-ticket',public_number:'ABCDEFGH',case_type:'general',topic_label:categories.find(c=>c.key===data.topic).label,
              author:user,author_id:user.id,status:'open',created_at:new Date().toISOString(),messages:[{sender_id:user.id,body:data.message}],deal_id:data.deal_id};
            tickets=[body]; await new Promise(resolve=>setTimeout(resolve,150));
          }else body=tickets;
        }
        await route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.locator('[data-nav-target="profile"]').click();
      await page.locator('[data-view="profile"] [data-open-support]').click();
      const picker=page.locator('#supportCategoryPicker'); await picker.waitFor();
      assert.equal(await picker.locator('button').count(),11);
      assert.equal(await page.locator('#supportForm').isVisible(),false);
      await page.waitForFunction(()=>[...document.querySelectorAll('#supportCategoryPicker button')].every(button=>button.getBoundingClientRect().height>=43.99));
      for(const button of await picker.locator('button').all()) assert((await button.boundingBox()).height>=43.99);
      await picker.getByRole('button',{name:'🤝 Проблема со сделкой',exact:true}).click();
      await page.locator('#supportOrderChoice option[value="12345678-test-order"]').waitFor({state:'attached'});
      await page.locator('[name=linked_deal_id]').selectOption('12345678-test-order');
      const textarea=page.locator('#supportForm textarea');
      await textarea.fill('<img src=x onerror=alert(1)> Помогите разобраться');
      assert(Number(await textarea.evaluate(el=>parseFloat(getComputedStyle(el).fontSize)))>=16);
      await page.locator('#supportForm button[type=submit]').dblclick();
      await page.locator('#supportTickets').getByText('<img src=x onerror=alert(1)> Помогите разобраться',{exact:true}).waitFor();
      assert.equal(submitted.length,1); assert(submitted[0].client_request_id); assert.equal(submitted[0].deal_id,'12345678-test-order');
      assert.equal(await page.locator('#supportTickets img').count(),0);
      assert.match(await page.locator('#supportTickets').innerText(),/Username отсутствует/);
      await page.locator('#supportCategoryPicker').getByRole('button',{name:'⭐ Вывод средств',exact:true}).click();
      assert.equal(await page.locator('#supportOrderChoice').isVisible(),false);
      assert.equal(await page.locator('[name=linked_deal_id]').inputValue(),'');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      assert.deepEqual(errors,[]);
      console.log(`${width}px: 11 categories, optional order, submit guard, safe text, 44px targets, no overflow OK`);
      await page.close();
    }
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
