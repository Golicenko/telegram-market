// Real application, signed HTTP and isolated PostgreSQL. No live Stars/Bot API.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const base=process.env.PUBLICATION_TEST_URL;
if (!base || new URL(base).hostname!=='127.0.0.1') throw Error('Isolated localhost required');
(async()=>{
  const browser=await chromium.launch({...(process.env.CI?{}:{channel:'msedge'}),headless:true});
  try {
    async function pageFor(auth,width=390) {
      const page=await browser.newPage({viewport:{width,height:844},isMobile:true,hasTouch:true});
      await page.route('https://telegram.org/**',r=>r.fulfill({contentType:'text/javascript',body:''}));
      await page.addInitScript(auth=>{window.Telegram={WebApp:{initData:auth,platform:'ios',ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}}}};},auth);
      return page;
    }
    const evidence=path.join(__dirname,'evidence');fs.mkdirSync(evidence,{recursive:true});
    const page=await pageFor(process.env.PUBLICATION_SELLER_AUTH);
    let published=false, posts=0;
    await page.route('**/api/listings',async route=>{
      if(route.request().method()!=='POST')return route.continue();
      posts++;const response=await route.fetch();assert.equal(response.status(),201);
      const row=await response.json();assert.equal(row.pinned,true);published=true;
      await route.fulfill({response});
    });
    await page.route('**/api/profile',route=>published?route.fulfill({status:503,json:{detail:'isolated refresh failure'}}):route.continue());
    await page.goto(base);
    await page.locator('.catalog-add[data-open-add]').click();
    const form=page.locator('#carForm');
    await form.locator('[name=game_version][value=car_parking_1]').check({force:true});
    await form.locator('[name=brand]').fill('VIP regression test');
    await form.locator('[name=power_hp]').fill('600');await form.locator('[name=max_speed_kph]').fill('300');
    await form.locator('[name=description]').fill('Тест публикации с VIP');await form.locator('[name=price_af_coins]').fill('100');
    await form.locator('[name=photos]').setInputFiles({name:'test.jpg',mimeType:'image/jpeg',buffer:Buffer.from(process.env.PUBLICATION_EXIF_JPEG,'base64')});
    await page.waitForFunction(()=>!!document.querySelector('.photo-preview-item img')?.naturalWidth);
    await form.locator('[name=promote_for_24h]').check({force:true});
    await form.locator('[type=submit]').evaluate(el=>{el.click();el.click();});
    await page.locator('#promotionChoicePaid').click();
    await page.locator('#toast').filter({hasText:'Объявление сохранено, но данные не удалось обновить'}).waitFor();
    assert.equal(posts,1);
    await page.screenshot({path:path.join(evidence,'vip-publication-refresh-390.png'),animations:'disabled'});
    await page.close();

    const admin=await pageFor(process.env.CRITICAL_ADMIN_AUTH,430);
    admin.on('dialog',dialog=>dialog.accept('Проверено обеими сторонами'));
    let controls=0;
    await admin.route(`**/api/admin/deals/${process.env.CRITICAL_CONTROL_DEAL}/control`,async route=>{
      if(route.request().method()!=='POST')return route.continue();
      controls++;const response=await route.fetch();assert.equal(response.status(),200);
      assert.equal((await response.json()).status,'completed');await route.abort('failed');
    });
    await admin.goto(base+'/?admin_deal_id='+process.env.CRITICAL_CONTROL_DEAL);
    await admin.locator('#adminDealReason').fill('Проверено обеими сторонами');
    await admin.locator('[data-admin-deal-action=complete]').click();
    await admin.locator('.critical-confirm .publish-button').click();
    await admin.locator('#toast').filter({hasText:'Сделка успешно завершена'}).waitFor();
    assert.equal(controls,1);assert.equal(await admin.locator('[data-admin-deal-action=complete]').count(),0);
    await admin.screenshot({path:path.join(evidence,'admin-lost-response-430.png'),animations:'disabled'});
    let resolved=false, resolutions=0;
    await admin.route(`**/api/admin/support/tickets/${process.env.CRITICAL_SUPPORT_TICKET}/resolve`,async route=>{
      resolutions++;const response=await route.fetch();assert.equal(response.status(),200);
      assert.equal((await response.json()).status,'resolved');resolved=true;await route.fulfill({response});
    });
    await admin.route('**/api/admin/support/tickets?*',route=>resolved?route.fulfill({status:503,json:{detail:'isolated refresh failure'}}):route.continue());
    await admin.goto(base+'/?support_case='+process.env.CRITICAL_SUPPORT_TICKET);
    await admin.locator(`[data-support-resolution=complete][data-ticket-id="${process.env.CRITICAL_SUPPORT_TICKET}"]`).click();
    await admin.locator('.critical-confirm .publish-button').click();
    await admin.locator('#toast').filter({hasText:'Средства начислены продавцу. Данные не удалось обновить'}).waitFor();
    assert.equal(resolutions,1);
    await admin.screenshot({path:path.join(evidence,'support-resolution-refresh-430.png'),animations:'disabled'});
    console.log('PASS real VIP/admin browser: initial VIP; refresh failure after publication; lost admin POST response reconciled; support settlement + failed refresh; no duplicate writes');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
