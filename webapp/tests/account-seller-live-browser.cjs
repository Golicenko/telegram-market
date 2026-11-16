// Real production form, HTTP API, volume, queued FFmpeg, and isolated PostgreSQL.
// Only the Telegram native host bridge is supplied; no application/API mocks.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const base=process.env.ACCOUNT_TEST_URL;
if(!base||new URL(base).hostname!=='127.0.0.1')throw Error('Local isolated backend required');
const evidence=path.join(__dirname,'evidence/account-autodelivery');fs.mkdirSync(evidence,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CI?{}:{channel:'msedge'})}),errors=[];
 async function open(auth){
  const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  await context.route('https://telegram.org/**',route=>route.fulfill({body:''}));
  await context.addInitScript(auth=>{window.Telegram={WebApp:{initData:auth,platform:'ios',ready(){},expand(){},onEvent(){},offEvent(){},safeAreaInset:{top:20,bottom:10},BackButton:{show(){},hide(){},onClick(){}},openInvoice(){throw Error('Unexpected Stars checkout in a VIP-disabled test');}}};},auth);
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));await page.goto(base+'/');
  await page.locator('#startupStatus').waitFor({state:'hidden'});return page;
 }
 try{
  const seller=await open(process.env.ACCOUNT_SELLER_AUTH),transport={uploads:0,publishes:0,pins:0};
  seller.on('request',request=>{const url=new URL(request.url());if(request.method()==='PUT'&&/\/api\/account-videos\/[^/]+\/content$/.test(url.pathname))transport.uploads++;if(request.method()==='POST'&&url.pathname==='/api/account-products')transport.publishes++;if(/\/pin$/.test(url.pathname))transport.pins++;});
  await seller.getByRole('button',{name:'Добавить автомобиль или аккаунт',exact:true}).click();
  await seller.getByRole('button',{name:/👤 Аккаунт/}).click();
  const editor=seller.locator('[data-view=account-editor]'),form=editor.locator('form.account-form');await form.waitFor();
  assert.equal(await form.evaluate(element=>element.closest('dialog')===null),true);
  assert.match(await form.locator('.account-quota').innerText(),/0 из 3 использовано/);
  assert.equal(await form.locator('[name=vip]').isChecked(),true);await form.locator('[name=vip]').uncheck();
  await form.locator('[name=game_version]').selectOption('car_parking_2');
  await form.locator('[name=cover]').setInputFiles(process.env.ACCOUNT_TEST_COVER);
  const started=seller.waitForResponse(response=>new URL(response.url()).pathname==='/api/account-videos'&&response.request().method()==='POST');
  await form.locator('[name=video]').setInputFiles(process.env.ACCOUNT_TEST_VIDEO);
  const videoResponse=await started;assert.equal(videoResponse.status(),201);
  const asset=await videoResponse.json();assert.equal(asset.upload_transport,'miniapp');
  await form.getByText('Видео готово ✓',{exact:true}).waitFor({timeout:90000});
  assert.deepEqual(transport,{uploads:1,publishes:0,pins:0},'Video completes before any publication or Stars invoice');
  await form.locator('[name=title]').fill('Аккаунт CP2 — сквозная проверка');
  await form.locator('[name=description]').fill('Изолированный тест реальной формы, фото и обработанного видео.');
  await form.locator('[name=price_af_coins]').fill('100');await form.locator('[name=owns_account]').check();
  assert.equal(await seller.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await seller.screenshot({path:path.join(evidence,'seller-real-form-390.png'),fullPage:true});
  // Test credentials are entered only after screenshot capture, never logged.
  await form.locator('[name=login]').fill('seller-ui@example.test');
  await form.locator('[name=password]').fill('seller-ui-private-password');
  const published=seller.waitForResponse(response=>new URL(response.url()).pathname==='/api/account-products'&&response.request().method()==='POST');
  await form.getByRole('button',{name:'Опубликовать аккаунт',exact:true}).click();
  const response=await published;assert.equal(response.status(),201,'Real form publication must succeed');
  const item=await response.json();assert.equal(item.video_asset_id,asset.id);assert.equal(item.product_kind,'account');assert.equal(item.game_version,'car_parking_2');
  assert(!JSON.stringify(item).includes('seller-ui-private-password'),'Public API must never disclose credentials');
  await seller.locator('[data-view=listing-detail]').waitFor({state:'visible'});
  await seller.locator('#listingPageImage').waitFor({state:'visible'});
  await seller.waitForFunction(()=>document.querySelector('#listingPageImage').naturalWidth>0);
  assert.equal(await seller.locator('[name=password]').count(),0,'Committed publication clears credential inputs');
  assert.deepEqual(transport,{uploads:1,publishes:1,pins:0},'Publishing reuses uploaded asset and disabled VIP makes no API call');

  const buyer=await open(process.env.ACCOUNT_BUYER_AUTH);
  const card=buyer.locator(`[data-listing-card="${item.id}"]`);await card.waitFor();await card.locator('img').first().click();
  await buyer.locator('[data-view=listing-detail]').waitFor({state:'visible'});
  assert.equal(await buyer.locator('#listingPageTitle').innerText(),'Аккаунт CP2 — сквозная проверка');
  assert.equal(await buyer.locator('#listingPageImage').isVisible(),true,'Photo remains the first gallery slide');
  assert.equal(await buyer.locator('#accountListingVideo video').count(),0);
  await buyer.getByRole('button',{name:'Видео',exact:true}).click();await buyer.getByRole('button',{name:'Смотреть видео аккаунта',exact:true}).click();
  await buyer.waitForFunction(()=>{const video=document.querySelector('#accountListingVideo video');return video&&video.readyState>=2&&video.duration>=29;});
  await buyer.evaluate(()=>document.querySelector('#accountListingVideo video').pause());
  await buyer.screenshot({path:path.join(evidence,'seller-published-buyer-video-390.png'),fullPage:true});
  await buyer.evaluate(()=>{window.testSuccess=false;new MutationObserver(()=>{if(!document.querySelector('#successOverlay').hidden)window.testSuccess=true;}).observe(document.querySelector('#successOverlay'),{attributes:true,attributeFilter:['hidden']});});
  await buyer.locator('#listingPageBuy').click();await buyer.locator('#purchaseModalAction').click();
  await buyer.locator('[data-view=deal-chat]').waitFor({state:'visible'});await buyer.locator('#successOverlay').waitFor({state:'hidden'});
  assert.equal(await buyer.evaluate(()=>testSuccess),true,'Only the successful server purchase opens success animation');
  assert.equal(await buyer.getByRole('button',{name:'🔐 Открыть аккаунт',exact:true}).count(),1);
  assert.equal(await buyer.locator('#dealMessages .account-delivery-card').count(),0);
  assert.equal(await buyer.locator('#chatForm').isVisible(),true);
  const message='Здравствуйте! Проверяю полученный аккаунт.';
  await buyer.locator('#chatInput').fill(message);await buyer.locator('#chatForm').getByRole('button',{name:'Отправить',exact:true}).click();
  await buyer.locator('#dealMessages .message').filter({hasText:message}).waitFor();
  assert.deepEqual(errors,[]);console.log('PASS seller real form -> eager upload -> queued FFmpeg H264 -> free publication/VIP off -> buyer photo/video -> one escrow purchase -> clean chat 390px');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
