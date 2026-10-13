// Real UI with isolated API/Telegram transport fixtures. NOT live Stars verification.
const {chromium} = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const server = http.createServer((req,res) => {
  const pathname = new URL(req.url,'http://test').pathname;
  const file = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) {res.writeHead(404);return res.end();}
  res.setHeader('Content-Type', ({'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png'})[path.extname(file)] || 'application/octet-stream');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const browser = await chromium.launch({channel:'msedge',headless:true});
  try {
    for (const width of [320,360,390,430]) {
      const page = await browser.newPage({viewport:{width,height:740},isMobile:true,hasTouch:true});
      let draft = null, invoiceCalls = 0, serverPublished = false, retryCalls = 0;
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.addInitScript(() => {
        window.Telegram={WebApp:{initData:'fixture',ready(){},expand(){},onEvent(){},BackButton:{show(){},hide(){},onClick(fn){window.testBack=fn;}},openInvoice(url,callback){window.invoiceOpenCount=(window.invoiceOpenCount||0)+1;window.invoiceCallback=callback;}}};
      });
      await page.route(/^https:/,route=>route.abort());
      await page.route('**/api/**',async route => {
        const endpoint = new URL(route.request().url()).pathname.slice(4);
        const method = route.request().method();
        const user = {id:'seller',telegram_id:1,first_name:'Seller',role:'user'};
        const wallet = {available_balance:0,frozen_balance:0,total_earned:0};
        let body = [];
        if(endpoint==='/me') body={user,wallet};
        else if(endpoint==='/profile') body={user,wallet,active_listings:[],sold_listings:[],purchases:[],active_deals:[],deals:[],deal_threads:[],conversations:[],wallet_transactions:[],withdrawals:[]};
        else if(endpoint==='/content/unseen') body={unique:{unseen_count:0},training:{unseen_count:0}};
        else if(endpoint==='/conversations/unread-summary') body={total_unread:0,conversations:[]};
        else if(endpoint==='/publication-rules') body={free_limit:5,price_stars:5,enabled:true,used:5,remaining:0,payment_required:true};
        else if(endpoint==='/uploads') body={url:'/test.png'};
        else if(endpoint==='/listings' && method==='POST') return route.fulfill({status:402,contentType:'application/json',body:JSON.stringify({detail:{code:'publication_payment_required',message:'Требуется оплата публикации'}})});
        else if(endpoint==='/publication-drafts') {
          if(method==='POST') {draft ||= {id:'draft',price_stars:5,status:'draft',payload:route.request().postDataJSON()};body=draft;}
          else body=draft && !serverPublished ? [draft] : [];
        } else if(endpoint==='/publication-drafts/draft/invoice') {invoiceCalls++;body={...draft,invoice_url:'https://t.me/$fixture'};}
        else if(endpoint==='/publication-drafts/draft/retry' || endpoint==='/publication-drafts/draft') {
          if(method==='POST') retryCalls++;
          body=serverPublished ? {...draft,status:'published',listing_id:'car'} : draft;
        } else if(endpoint==='/listings/car') body={...draft.payload,id:'car',seller_id:'seller',status:'active',images:[],pinned:false};
        await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
      });
      await page.goto('http://127.0.0.1:'+server.address().port+'/');
      await page.getByRole('button',{name:'Добавить обычную машину',exact:true}).click();
      await page.locator('#publicationNote').filter({hasText:'5 ⭐'}).waitFor();
      await page.locator('[name=game_version][value=car_parking_1]').check();
      await page.locator('#brandInput').fill('Test car');
      await page.locator('[name=power_hp]').fill('100');
      await page.locator('[name=max_speed_kph]').fill('200');
      await page.locator('#carForm [name=description]').fill('Isolated test listing');
      await page.locator('#priceInput').fill('50');
      await page.locator('[name=promote_for_24h]').uncheck();
      await page.locator('#carPhotos').setInputFiles({name:'car.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII=','base64')});
      await page.locator('#carForm button[type=submit]').click();
      const modal = page.locator('.publication-modal'); await modal.waitFor();
      const box = await modal.boundingBox(); assert(box.x>=0 && box.x+box.width<=width+1);
      assert.equal(await modal.getByRole('button',{name:'Оплатить 5 ⭐',exact:true}).count(),1);
      await modal.getByRole('button',{name:'Отмена',exact:true}).click();
      await modal.waitFor({state:'detached'});
      assert.equal(invoiceCalls,0); assert.equal(serverPublished,false);
      const resume = page.locator('#publicationDrafts button'); await resume.waitFor();
      await resume.click(); await modal.waitFor();
      await page.evaluate(()=>window.testBack()); await modal.waitFor({state:'detached'});
      assert.equal(invoiceCalls,0);
      await resume.click(); await modal.waitFor();
      await modal.getByRole('button',{name:'Оплатить 5 ⭐',exact:true}).click();
      await page.waitForFunction(()=>window.invoiceOpenCount===1);
      assert.equal(await resume.isDisabled(),true);
      await page.evaluate(()=>window.invoiceCallback('cancelled'));
      await page.waitForFunction(()=>!document.querySelector('#publicationDrafts button').disabled);
      assert.equal(serverPublished,false); assert.equal(retryCalls,0);
      await resume.click(); await modal.waitFor();
      await modal.getByRole('button',{name:'Оплатить 5 ⭐',exact:true}).click();
      await page.waitForFunction(()=>window.invoiceOpenCount===2);
      await page.evaluate(()=>window.invoiceCallback('paid'));
      await page.waitForTimeout(200);
      assert.equal(await page.locator('#successOverlay').isVisible(),false,'Client paid callback is not authority');
      assert.equal(retryCalls,1);
      serverPublished=true;
      await page.locator('#successTitle').filter({hasText:'Объявление опубликовано'}).waitFor();
      assert.equal(invoiceCalls,2,'One invoice request for each explicit checkout, no extra retry charge');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      assert.deepEqual(errors,[]);
      console.log(`${width}px: fee modal, cancel/Back, persisted resume, invoice cancel, server-only publication OK`);
      await page.close();
    }
  } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
