// Actual frontend, explicit isolated API/Telegram fixtures; NOT live payment/device E2E.
const {chromium} = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const server = http.createServer((req,res) => {
  const file = path.resolve(root, '.' + (new URL(req.url,'http://test').pathname === '/' ? '/index.html' : new URL(req.url,'http://test').pathname));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) {res.writeHead(404);return res.end();}
  res.setHeader('Content-Type', ({'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png'})[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const browser = await chromium.launch({channel:'msedge',headless:true});
  try {
    for (const width of [320,360,390,430,960]) {
      const errors=[]; let failSend=true; const attempts=[];
      const messages=Array.from({length:1000},(_,n)=>({id:String(n+1).padStart(5,'0'),conversation_id:'thread',deal_id:null,sender_id:'seller',body:`Message ${n} <script>window.injected=true</script>`,message_type:'text',created_at:new Date(1700000000000+n*1000).toISOString(),is_read:false}));
      const pages=[];
      for (const who of ['buyer','seller']) {
        const page=await browser.newPage({viewport:{width,height:740},isMobile:width<600,hasTouch:width<600}); pages.push(page);
        page.on('pageerror',e=>errors.push(e.message));
        await page.addInitScript(()=>{
          window.Telegram={WebApp:{initData:'fixture',ready(){},expand(){},onEvent(){},BackButton:{show(){},hide(){},onClick(fn){window.testBack=fn;}}}};
          Object.defineProperty(navigator,'clipboard',{value:{async writeText(text){window.copiedMessage=text;}}});
        });
        await page.route(/^https:/,route=>route.abort());
        await page.route('**/api/**',async route=>{
          const url=new URL(route.request().url()), endpoint=url.pathname.slice(4);let body=[];
          const user={id:who,telegram_id:who==='buyer'?1:2,first_name:who,role:'user'};
          const wallet={available_balance:0,frozen_balance:0,total_earned:0};
          if(endpoint==='/me')body={user,wallet};
          else if(endpoint==='/profile')body={user,wallet,active_listings:[],sold_listings:[],purchases:[],active_deals:[],deals:[],deal_threads:[],conversations:[],wallet_transactions:[],withdrawals:[]};
          else if(endpoint==='/content/unseen')body={unique:{unseen_count:0},training:{unseen_count:0}};
          else if(endpoint==='/conversations/unread-summary')body={total_unread:0,conversations:[]};
          else if(endpoint==='/conversations/thread')body={id:'thread',conversation_type:'dialog',listing:{id:'car',seller_id:'seller',brand:'Car',price_af_coins:100,images:[]},counterparty:{id:who==='buyer'?'seller':'buyer',name:'Другой участник'},offers:[]};
          else if(endpoint==='/conversations/thread/messages'){
            if(route.request().method()==='POST'){
              const data=route.request().postDataJSON(); attempts.push(data.client_message_id);
              if(failSend){failSend=false;return route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({detail:'network fixture'})});}
              body=messages.find(m=>m.client_message_id===data.client_message_id);
              if(!body){body={...data,id:String(messages.length+1).padStart(5,'0'),sender_id:who,conversation_id:'thread',message_type:'text',created_at:new Date().toISOString(),is_read:false};messages.push(body);}
            }else{
              const before=url.searchParams.get('before'),after=url.searchParams.get('after');
              const rows=messages.filter(m=>(!before||m.id<before)&&(!after||m.id>after));
              body=after?rows.slice(0,100):rows.slice(-100);
            }
          }
          await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
        });
        await page.goto('http://127.0.0.1:'+server.address().port+'/?conversation_id=thread');
        await page.locator('.message').first().waitFor();
        assert.equal(await page.locator('.message').count(),100);
        assert.equal(await page.evaluate(()=>window.injected),undefined);
      }
      const [buyer,seller]=pages;
      await buyer.bringToFront();
      await buyer.locator('#dealMessages').evaluate(el=>el.scrollTop=120);
      const before=await buyer.locator('#dealMessages').evaluate(el=>el.scrollTop);
      messages.push({id:'01001',conversation_id:'thread',sender_id:'seller',body:'New while reading',message_type:'text',created_at:new Date().toISOString()});
      await buyer.locator('.message').filter({hasText:'New while reading'}).waitFor({state:'attached'});
      assert(Math.abs(await buyer.locator('#dealMessages').evaluate(el=>el.scrollTop)-before)<5);
      await buyer.locator('#chatJumpLatest').waitFor({state:'visible'});
      await buyer.locator('#dealMessages').evaluate(el=>el.scrollTop=0);
      await buyer.getByRole('button',{name:'Предыдущие сообщения',exact:true}).click();
      await buyer.waitForFunction(()=>document.querySelectorAll('.message').length===201);
      assert(await buyer.locator('#dealMessages').evaluate(el=>el.scrollTop)>100);
      await buyer.locator('#chatJumpLatest').click();
      const input=buyer.locator('#chatInput'); await input.fill('Long message '.repeat(70));
      assert(Number(await input.evaluate(el=>getComputedStyle(el).fontSize.replace('px','')))>=16);
      assert((await input.boundingBox()).height<=114);
      await buyer.setViewportSize({width,height:360}); await input.focus();
      await buyer.waitForTimeout(150);
      const box=await input.boundingBox(); assert(box.y>=0 && box.y+box.height<=360,JSON.stringify(box));
      assert.equal(await buyer.evaluate(()=>visualViewport.scale),1);
      await input.blur(); await buyer.setViewportSize({width,height:740});
      assert((await input.inputValue()).startsWith('Long message'));
      await input.fill('Retry exactly once'); await buyer.locator('#chatForm button').click();
      await buyer.getByRole('button',{name:'Повторить',exact:true}).waitFor();
      await buyer.getByRole('button',{name:'Повторить',exact:true}).click();
      await seller.bringToFront();
      await seller.locator('.message').filter({hasText:'Retry exactly once'}).waitFor({state:'attached'});
      await buyer.bringToFront();
      assert.equal(attempts.length,2); assert.equal(attempts[0],attempts[1]);
      assert.equal(messages.filter(m=>m.body==='Retry exactly once').length,1);
      const bubble=buyer.locator('.message').filter({hasText:'Retry exactly once'});
      await bubble.dispatchEvent('pointerdown',{pointerType:'touch',clientX:40,clientY:200});
      await buyer.locator('#chatCopyMenu').waitFor(); await bubble.dispatchEvent('pointerup',{pointerType:'touch'});
      await buyer.locator('#chatCopyMenu').click();
      assert.equal(await buyer.evaluate(()=>window.copiedMessage),'Retry exactly once');
      assert.equal(await buyer.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      assert.deepEqual(errors,[]);
      console.log(`${width}px: 2 accounts, 1000-message pagination, scroll preservation, keyboard resize, retry ID, XSS, copy OK`);
      for(const page of pages)await page.close();
    }
  } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
