// Signed API and real isolated PG supplied by pytest. Never a production URL.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.env.CHAT_TEST_URL,width=Number(process.env.CHAT_TEST_WIDTH||390),deal=process.env.CHAT_TEST_DEAL;
if(!base||new URL(base).hostname!=='127.0.0.1')throw Error('Local isolated backend required');
const out=path.join(__dirname,'evidence/chat-20261107');fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CI?{}:{channel:'msedge'})});const errors=[];
  async function open(auth){
    const context=await browser.newContext({viewport:{width,height:width===320?640:844},hasTouch:true,isMobile:true});
    await context.route('https://telegram.org/**',r=>r.fulfill({body:''}));
    await context.addInitScript(auth=>{window.Telegram={WebApp:{initData:auth,platform:'ios',ready(){},expand(){},onEvent(){},offEvent(){},safeAreaInset:{top:20,bottom:10},BackButton:{show(){},hide(){},onClick(fn){window.testBack=fn;}}}};},auth);
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+'/?deal_id='+deal);await page.locator('[data-view=deal-chat]').waitFor({state:'visible'});return page;
  }
  try{
    const seller=await open(process.env.CHAT_SELLER_AUTH);
    const box=await seller.locator('.seller-deal__card').boundingBox();assert(box.height<seller.viewportSize().height/4);
    await seller.screenshot({path:path.join(out,'compact-accept-'+width+'.png')});
    await seller.getByRole('button',{name:'Принять сделку',exact:true}).click();
    await seller.locator('[data-deal-reminder=id]').waitFor();
    const buyer=await open(process.env.CHAT_BUYER_AUTH);
    await buyer.locator('[name=buyer_game_id]').fill('AB12345');await buyer.getByRole('button',{name:'Отправить продавцу',exact:true}).click();
    await seller.locator('[data-deal-action=transfer]').waitFor({timeout:20000});
    const file={name:'isolated-test.png',mimeType:'image/png',buffer:Buffer.from(process.env.CHAT_TEST_PHOTO,'base64')};
    await seller.locator('#chatPhotoInput').setInputFiles(file);assert.equal(await seller.locator('#chatPhotoSelection img').count(),1);
    await seller.getByRole('button',{name:'Убрать фотографию',exact:true}).click();assert.equal(await seller.locator('#chatPhotoSelection img').count(),0);
    await seller.locator('#chatPhotoInput').setInputFiles([file,{...file,name:'test2.png'},{...file,name:'test3.png'}]);
    assert.equal(await seller.locator('#chatPhotoSelection img').count(),3);
    let uploads=0,lost=false,nonce=null;const ids=[];
    await seller.route('**/api/conversations/*/photos',async route=>{
      if(route.request().method()!=='POST')return route.continue();
      uploads++;const response=await route.fetch();const message=await response.json();ids.push(message.id);
      if(!lost){lost=true;nonce=message.client_message_id;return route.abort('failed');}
      await route.fulfill({response});
    });
    await seller.locator('#chatForm button[type=submit]').evaluate(button=>{button.click();button.click();});
    const retry=seller.locator('.message').getByRole('button',{name:'Повторить',exact:true});
    // A server-committed lost response may recover either through explicit
    // retry or the next authenticated incremental poll.
    try{await retry.first().waitFor({timeout:1800});await retry.first().click();}catch{}
    await buyer.waitForFunction(()=>document.querySelectorAll('.message .chat-photo').length===3,null,{timeout:25000});
    await seller.waitForFunction(()=>document.querySelectorAll('.message .chat-photo').length===3,null,{timeout:25000});
    assert.equal(new Set(ids).size,3);assert(uploads>=3&&uploads<=4);assert(nonce);
    await buyer.locator('.chat-photo').first().scrollIntoViewIfNeeded();
    await buyer.locator('.chat-photo img').first().waitFor();
    await buyer.waitForFunction(()=>document.querySelector('.chat-photo img')?.src.startsWith('blob:'));
    await buyer.locator('.chat-photo').first().click();
    const viewer=buyer.locator('dialog.chat-photo-viewer');await viewer.waitFor();
    await buyer.waitForFunction(()=>document.querySelector('.chat-photo-canvas img')?.naturalWidth>0);
    await viewer.getByRole('button',{name:'Увеличить фото',exact:true}).click();
    assert.match(await viewer.locator('img').getAttribute('style'),/scale\(1\.3\)/);
    await buyer.evaluate(()=>window.testBack());await viewer.waitFor({state:'detached'});assert(await buyer.locator('[data-view=deal-chat]').isVisible());
    await buyer.evaluate(()=>{window.firstPhoto=document.querySelector('.message .chat-photo').parentElement;});
    await seller.locator('#chatInput').fill('Новое сообщение после фото');await seller.locator('#chatForm button[type=submit]').click();
    await buyer.locator('.message').filter({hasText:'Новое сообщение после фото'}).waitFor({timeout:20000});
    assert(await buyer.evaluate(()=>window.firstPhoto.isConnected),'unchanged photo bubble kept in DOM');
    for(let reopen=0;reopen<2;reopen++){
      await buyer.locator('[data-view=deal-chat] [data-back]').click();
      await buyer.locator('.bottom-nav [data-nav-target=profile]').click();
      await buyer.locator('[data-profile-tab=deals]').click();
      await buyer.locator('[data-open-deal-thread][data-deal-id="'+deal+'"]').click();
      await buyer.locator('[data-view=deal-chat]').waitFor({state:'visible'});
      await buyer.locator('.chat-photo').last().evaluate(el=>el.scrollIntoView({block:'center'}));
      await buyer.waitForFunction(()=>{const img=[...document.querySelectorAll('.chat-photo img')].at(-1);return img?.src.startsWith('blob:')&&img.naturalWidth>0;});
    }
    await seller.locator('[data-deal-action=transfer]').click();const confirm=seller.locator('dialog.deal-confirmation');await confirm.waitFor();
    await seller.waitForFunction(()=>!document.querySelector('.deal-confirmation .publish-button')?.disabled);
    await confirm.getByRole('button',{name:'Да, передал',exact:true}).click();await confirm.waitFor({state:'detached'});
    assert.equal(await seller.locator('.seller-deal__progress i.is-done').count(),3);
    assert.equal(await seller.locator('#dealControls').isVisible(),false,'no empty footer frame after seller actions');
    assert.match(await seller.locator('.seller-deal').textContent(),/Ожидаем подтверждения покупателя/);
    await seller.screenshot({path:path.join(out,'compact-transferred-'+width+'.png')});
    for(const page of [seller,buyer])assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)));
    assert.deepEqual(errors,[]);
    console.log(width+'px: signed seller/buyer, compact states, private photos x3, lost-response replay, viewer/zoom/Back, DOM reuse, reopen twice, escrow held PASS');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
