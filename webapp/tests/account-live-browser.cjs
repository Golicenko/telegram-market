// Real signed API and disposable PG supplied by pytest; never production.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.env.ACCOUNT_TEST_URL,width=Number(process.env.ACCOUNT_TEST_WIDTH||390),listing=process.env.ACCOUNT_TEST_LISTING;
if(!base||new URL(base).hostname!=='127.0.0.1')throw Error('Local isolated backend required');
const out=path.join(__dirname,'evidence/account-autodelivery');fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CI?{}:{channel:'msedge'})});const errors=[];
  async function open(auth,query=''){
    const context=await browser.newContext({viewport:{width,height:width===320?700:844},hasTouch:true,isMobile:true});
    await context.route('https://telegram.org/**',r=>r.fulfill({body:''}));
    await context.addInitScript(auth=>{
      window.Telegram={WebApp:{initData:auth,platform:'ios',ready(){},expand(){},onEvent(){},offEvent(){},safeAreaInset:{top:20,bottom:10},BackButton:{show(){},hide(){},onClick(fn){window.testBack=fn;}}}};
      Object.defineProperty(navigator,'clipboard',{value:{async writeText(){window.testCopyCount=(window.testCopyCount||0)+1;}}});
    },auth);
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+'/'+query);return page;
  }
  try{
    const buyer=await open(process.env.ACCOUNT_BUYER_AUTH);
    let reveals=0;buyer.on('request',r=>{if(r.url().endsWith('/credentials'))reveals++;});
    await buyer.locator(`[data-listing-card="${listing}"]`).waitFor();
    await buyer.getByRole('button',{name:'Аккаунты',exact:true}).click();
    assert.equal(await buyer.locator('#marketCars [data-listing-card]').count(),1);
    assert(!/null л\.с\.|null км/.test(await buyer.locator('#marketCars').innerText()));
    await buyer.locator(`[data-buy-now="${listing}"]`).click();
    await buyer.locator('#purchaseModalAction').click();
    await buyer.locator('[data-view=deal-chat]').waitFor({state:'visible'});
    await buyer.locator('#successOverlay').waitFor({state:'hidden'});
    assert.equal(reveals,0,'Secret must not be prefetched');
    assert.equal(await buyer.locator('[name=buyer_game_id]').count(),0);
    const details=await buyer.evaluate(async()=>{const profile=await window.AutoFlowApi.request('/profile');return profile.deals[0];});
    const seller=await open(process.env.ACCOUNT_SELLER_AUTH,'?deal_id='+details.id);
    await seller.locator('[data-view=deal-chat]').waitFor({state:'visible'});
    assert.equal(await seller.getByRole('button',{name:'Машина передана',exact:false}).count(),0);
    assert.equal(await seller.getByRole('button',{name:'🔐 Открыть аккаунт',exact:true}).count(),0);
    assert.match(await seller.locator('#dealDeliveryPanel').innerText(),/Автовыдача выполнена/);
    await seller.screenshot({path:path.join(out,'seller-'+width+'.png')});
    await buyer.getByRole('button',{name:'🔐 Открыть аккаунт',exact:true}).first().click();
    const popup=buyer.locator('dialog.account-modal[open]');
    await popup.locator('input[name=login]').waitFor();
    assert.equal(await popup.locator('input[name=password]').getAttribute('type'),'password');
    await popup.getByRole('button',{name:'Показать / скрыть',exact:true}).click();
    assert.equal(await popup.locator('input[name=password]').getAttribute('type'),'text');
    await popup.getByRole('button',{name:'Скопировать',exact:true}).first().click();
    assert.equal(await buyer.evaluate(()=>window.testCopyCount),1);
    // Never save a screenshot with plaintext credentials.
    await popup.getByRole('button',{name:'Показать / скрыть',exact:true}).click();
    const geometry=await popup.boundingBox();assert(geometry.x>=0&&geometry.x+geometry.width<=width+1);
    await buyer.evaluate(()=>window.testBack());await popup.waitFor({state:'detached'});
    assert.equal(await buyer.locator('input[name=password]').count(),0);
    assert.equal(await buyer.evaluate(()=>JSON.stringify(localStorage).includes('DO-NOT-LOG')),false);
    await buyer.waitForTimeout(1100);await buyer.getByRole('button',{name:'🔐 Открыть аккаунт',exact:true}).first().click();
    await buyer.locator('dialog.account-modal input[name=password]').waitFor();
    assert.equal(await buyer.locator('dialog.account-modal input[name=password]').getAttribute('type'),'password');
    await buyer.getByRole('button',{name:'Закрыть',exact:true}).last().click();
    await buyer.getByRole('button',{name:'Аккаунт получен',exact:true}).click();
    const confirm=buyer.locator('dialog.account-modal[open]');
    assert(await confirm.getByRole('button',{name:'Подтвердить получение',exact:true}).isDisabled());
    await confirm.locator('input[name=checked_access]').check();
    await buyer.screenshot({path:path.join(out,'confirmation-'+width+'.png')});
    await confirm.getByRole('button',{name:'Подтвердить получение',exact:true}).click();
    await buyer.getByText('✅ Сделка завершена',{exact:true}).waitFor();
    const retained=await buyer.evaluate(async()=>{const p=await window.AutoFlowApi.request('/profile');return p.deal_threads.map(t=>t.deal.id);});
    assert(retained.includes(details.id),'Receipt must remain reachable after restart/completion');
    assert.equal(reveals,2);
    assert.deepEqual(errors,[]);
    console.log('Verified account purchase, private card, copy/mask/Back, consent and shared settlement at '+width+'px');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
