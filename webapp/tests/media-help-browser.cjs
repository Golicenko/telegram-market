// Real frontend; isolated HTTP/Telegram fixtures only. No production operations.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const root = path.resolve(__dirname, '..');
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://fixture').pathname;
  const file = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.setHeader('Content-Type', ({'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png','.jpg':'image/jpeg'})[path.extname(file)] || 'application/json');
  res.end(fs.readFileSync(file));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ ...(process.env.CI ? {} : {channel:'msedge'}), headless:true });
  try {
    for (const width of [320,360,390,430]) {
      const context = await browser.newContext({viewport:{width,height:844},isMobile:true,hasTouch:true});
      const page = await context.newPage();
      const errors=[]; page.on('pageerror', error => errors.push(error.message));
      const png = Buffer.from(await page.evaluate(() => {
        const canvas=document.createElement('canvas'); canvas.width=640; canvas.height=480;
        const ctx=canvas.getContext('2d');ctx.fillStyle='#284960';ctx.fillRect(0,0,640,480);
        ctx.fillStyle='#f5b83e';ctx.fillRect(50,150,540,160);ctx.fillStyle='#101a28';ctx.font='32px sans-serif';ctx.fillText('TEST PHOTO · CP1 / CP2',95,240);
        return canvas.toDataURL('image/png').split(',')[1];
      }), 'base64');
      await context.route(/^https:/, route => route.fulfill({status:200,body:''}));
      const user={id:'seller',telegram_id:77,first_name:'Тестовый пользователь с длинным именем',role:'user'};
      const wallet={available_balance:100,earned_balance:100,purchased_balance:0,bonus_balance:0,frozen_balance:0};
      const profile={user,wallet,active_listings:[],sold_listings:[],deals:[],conversations:[],wallet_transactions:[],withdrawals:[]};
      const rules={publication:{enabled:true,free_limit:5,remaining:5,price_stars:7},af_per_star:1,car_seller_percent:100,withdrawal_fee_percent:30,withdrawal_hours:24,seller_response_hours:24,vip_cost_af:15,vip_hours:24,renewal_stars:10,renewal_hours:72};
      const listings=[1,2].map((game)=>({id:`car${game}`,seller_id:'other',brand:`Тестовая машина CP${game}`,model:'',description:'Тестовое объявление',power_hp:300,max_speed_kph:240,price_af_coins:100,game_version:`car_parking_${game}`,listing_type:'regular',status:'active',images:['/api/media/photo'],pinned:game===2,pinned_until:game===2?new Date(Date.now()+86400000).toISOString():null,created_at:new Date().toISOString()}));
      let uploads=0,publishes=0,failPhoto=true,lastPayload;
      await context.route('**/api/**',async route=>{
        const req=route.request(),url=new URL(req.url()),endpoint=url.pathname.slice(4);
        let body=[],status=200;
        if(endpoint==='/media/photo')return route.fulfill({status:200,contentType:'image/png',body:png});
        if(endpoint==='/me')body={user,wallet};
        else if(endpoint==='/profile')body=profile;
        else if(endpoint==='/help/rules')body=rules;
        else if(endpoint==='/uploads/policy')body={max_bytes:31457280,max_pixels:64000000,max_files:10};
        else if(endpoint==='/content/unseen')body={unique:{unseen_count:0,marker:0},training:{unseen_count:0,marker:0}};
        else if(endpoint==='/conversations/unread')body={total_unread:0,conversations:[]};
        else if(endpoint==='/publication-rules')body={...rules.publication,payment_required:false};
        else if(endpoint==='/vip/quote')body={cost_af:15,duration_hours:24};
        else if(endpoint==='/uploads'){
          uploads++; const bytes=req.postDataBuffer();
          assert(bytes.includes(Buffer.from('image/jpeg')),'small PNG with wrong MIME is normalized to JPEG');
          if(uploads===2 && failPhoto){status=503;body={detail:'Temporary upload error'};}
          else body={url:'/api/media/photo'};
        }
        else if(endpoint==='/listings' && req.method()==='POST'){
          publishes++;lastPayload=req.postDataJSON();assert.equal(lastPayload.image_urls.length,2);
          await new Promise(resolve=>setTimeout(resolve,150));body={...lastPayload,id:'saved',pinned:false};status=201;
        }
        else if(endpoint==='/listings')body=url.searchParams.get('type')==='regular'?listings:[];
        else if(endpoint.startsWith('/listings/car'))body=listings.find(l=>endpoint.includes(l.id));
        await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
      });
      await context.addInitScript(()=>{
        window.Telegram={WebApp:{initData:'isolated-browser-fixture',platform:'ios',ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}},HapticFeedback:{impactOccurred(){},notificationOccurred(){}},safeAreaInset:{top:24,bottom:34},contentSafeAreaInset:{top:12,bottom:0}}};
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      await page.locator('#marketCars .is-pinned').first().waitFor();
      await page.locator('#marketCars img').first().evaluate(img=>img.decode());
      const media=page.locator('#marketCars .car-card__media').first();
      assert.equal(await media.evaluate(el=>getComputedStyle(el,'::after').content),'none');
      assert.equal(new URL(await media.locator('img').getAttribute('src')).pathname,'/api/media/photo','real photo URL is not replaced by frame');
      await page.screenshot({path:path.join(__dirname,`media-help-market-${width}.png`),animations:'disabled'});
      await page.locator('.catalog-add[data-open-add]').click();
      const form=page.locator('#carForm');
      await form.locator('[name=game_version][value=car_parking_2]').check({force:true});
      await form.locator('[name=brand]').fill('Test');await form.locator('[name=power_hp]').fill('300');await form.locator('[name=max_speed_kph]').fill('250');
      await form.locator('[name=description]').fill('Описание не должно пропасть при сетевой ошибке');await form.locator('[name=price_af_coins]').fill('100');
      await form.locator('[name=promote_for_24h]').uncheck({force:true});
      await form.locator('[name=photos]').setInputFiles([{name:'one.png',mimeType:'application/octet-stream',buffer:png},{name:'two.png',mimeType:'image/png',buffer:png}]);
      const submit=form.locator('[type=submit]');
      await page.getByRole('button',{name:'Повторить загрузку',exact:true}).waitFor();
      assert.equal(publishes,0,'failed photo cannot initiate publication/payment');
      assert.equal(await form.locator('[name=description]').inputValue(),'Описание не должно пропасть при сетевой ошибке');
      assert.equal(await page.locator('.photo-preview-item').count(),2);
      // Cancelling the picker must preserve the two original photos.
      await form.locator('[name=photos]').setInputFiles([]);
      assert.equal(await page.locator('.photo-preview-item').count(),2);
      failPhoto=false;await page.getByRole('button',{name:'Повторить загрузку',exact:true}).click();
      await page.getByRole('button',{name:'Повторить загрузку',exact:true}).waitFor({state:'detached'});
      await submit.evaluate(el=>{el.click();el.click();});
      await page.locator('[data-view=market]').waitFor({state:'visible'});
      assert.equal(publishes,1);assert.equal(uploads,3,'already saved image is reused on retry');
      assert.equal(lastPayload.game_version,'car_parking_2');
      await page.locator('.bottom-nav [data-nav-target=profile]').click();
      await page.locator('.profile-main-actions [data-open-withdraw]').click();
      await page.locator('#withdrawForm').waitFor({state:'visible'});
      await page.locator('.bottom-nav [data-nav-target=profile]').click();
      await page.locator('.profile-main-actions [data-open-info]').click();
      await page.waitForFunction(()=>document.getElementById('helpRulesStatus').textContent.includes('получены с сервера'));
      assert.equal(await page.locator('#helpArticles details').count(),14);
      await page.locator('#help-withdraw summary').click();
      assert((await page.locator('#help-withdraw').innerText()).includes('30%'));
      await page.waitForFunction(()=>!document.getElementById('toast').classList.contains('is-visible'));
      await page.locator('#help-withdraw').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(__dirname,`media-help-guide-${width}.png`),animations:'disabled'});
      await page.locator('#help-unique summary').click();await page.getByRole('button',{name:'Перейти в Уникальные',exact:true}).click();
      await page.locator('[data-view=unique]').waitFor({state:'visible'});
      await page.locator('#infoButton').click();await page.locator('#help-training summary').click();
      await page.getByRole('button',{name:'Перейти в Обучение',exact:true}).click();await page.locator('[data-view=training]').waitFor({state:'visible'});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      assert.deepEqual(errors,[]); console.log(`PASS ${width}: frame, multi-upload, retained draft/retry, no duplicate publication, withdrawal entry, help links`);
      await context.close();
    }
  } finally { await browser.close();await new Promise(resolve=>server.close(resolve)); }
})().catch(error=>{console.error(error);process.exitCode=1;});
