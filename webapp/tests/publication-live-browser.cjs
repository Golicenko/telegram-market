// Real API and PostgreSQL supplied by the isolated pytest harness, never prod.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const base=process.env.PUBLICATION_TEST_URL;
if (!base || new URL(base).hostname!=='127.0.0.1') throw new Error('Isolated localhost harness required');

(async()=>{
  const browser=await chromium.launch({...(process.env.CI?{}:{channel:'msedge'}),headless:true});
  try {
    async function context(auth,width) {
      const result=await browser.newContext({viewport:{width,height:844},isMobile:true,hasTouch:true});
      await result.route('https://telegram.org/**',route=>route.fulfill({contentType:'text/javascript',body:''}));
      await result.addInitScript(auth=>{
        window.Telegram={WebApp:{initData:auth,platform:'ios',ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}},HapticFeedback:{impactOccurred(){},notificationOccurred(){}},safeAreaInset:{top:24,bottom:34},contentSafeAreaInset:{top:12,bottom:0}}};
      },auth);
      return result;
    }
    const seller=await context(process.env.PUBLICATION_SELLER_AUTH,390);
    const page=await seller.newPage(), errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base);
    await page.locator('.catalog-add[data-open-add]').waitFor();
    const images=[];
    for(let n=0;n<10;n++) images.push(Buffer.from(await page.evaluate(n=>{
      const canvas=document.createElement('canvas');canvas.width=800;canvas.height=600;
      const ctx=canvas.getContext('2d');ctx.fillStyle=`rgb(${n*20},60,110)`;ctx.fillRect(0,0,800,600);
      ctx.fillStyle='#fff';ctx.font='30px sans-serif';ctx.fillText(`REAL TEST PHOTO ${n}`,100,250);
      return canvas.toDataURL('image/png').split(',')[1];
    },n),'base64'));
    let uploadCount=0, postCount=0;
    page.on('request',req=>{if(req.method()==='POST' && new URL(req.url()).pathname==='/api/uploads')uploadCount++;});
    // Forward the first real POST to the backend, then lose only its response.
    // A retry must recover that same persisted listing, not create another.
    await page.route('**/api/listings',async route=>{
      if(route.request().method()!=='POST')return route.continue();
      postCount++;
      if(postCount===1){const response=await route.fetch();assert.equal(response.status(),201);return route.abort('failed');}
      return route.continue();
    });
    const saved=[];
    for(const [n,game] of ['car_parking_1','car_parking_2'].entries()) {
      await page.locator('.catalog-add[data-open-add]').click();
      const form=page.locator('#carForm');
      await form.locator(`[name=game_version][value=${game}]`).check({force:true});
      await form.locator('[name=brand]').fill(`Publication ${n}`);
      await form.locator('[name=power_hp]').fill('300');await form.locator('[name=max_speed_kph]').fill('250');
      await form.locator('[name=description]').fill('Сохраняем описание и фотографии при потере ответа');
      await form.locator('[name=price_af_coins]').fill('100');
      await form.locator('[name=promote_for_24h]').uncheck({force:true});
      const files=(n===0?images.slice(0,1):images).map((buffer,i)=>({name:`photo-${i}.png`,mimeType:'application/octet-stream',buffer}));
      await form.locator('[name=photos]').setInputFiles(files);
      await page.waitForFunction(count=>[...document.querySelectorAll('.photo-preview-item img')].filter(img=>!img.hidden && img.complete && img.naturalWidth).length===count,files.length);
      assert.equal(await page.locator('.photo-preview-item img').evaluateAll(imgs=>imgs.every(img=>!img.src.startsWith('blob:') && img.naturalWidth<=480)),true);
      const button=form.locator('[type=submit]');
      await button.evaluate(el=>{el.click();el.click();});
      if(n===0){
        await page.locator('#toast').filter({hasText:'Код:'}).waitFor();
        assert.equal(await form.locator('[name=description]').inputValue(),'Сохраняем описание и фотографии при потере ответа');
        assert.equal(uploadCount,1);
        await button.click();
      }
      await page.locator('[data-view=market]').waitFor({state:'visible'});
      const card=page.locator('#marketCars [data-listing-card]').filter({hasText:`Publication ${n}`});
      await card.waitFor();saved.push(await card.getAttribute('data-listing-card'));
    }
    assert.equal(postCount,3);assert.equal(uploadCount,11);
    await page.locator('.bottom-nav [data-nav-target=profile]').click();
    await page.locator(`[data-edit-listing="${saved[1]}"]`).click();
    const form=page.locator('#carForm');
    assert.equal(await form.locator('[name=promote_for_24h]').isChecked(),false);
    await form.locator('[name=description]').fill('Отредактировано без оплаты и замены фото');
    await form.locator('[type=submit]').click();
    await page.locator('[data-view=market]').waitFor({state:'visible'});
    assert.equal(uploadCount,11);
    const buyer=await context(process.env.PUBLICATION_BUYER_AUTH,320);
    const other=await buyer.newPage();await other.goto(base);
    const card=other.locator(`#marketCars [data-listing-card="${saved[1]}"]`);
    await card.waitFor();await card.locator('h3').click();
    await other.locator('[data-view=listing-detail]').waitFor({state:'visible'});
    assert((await other.locator('[data-view=listing-detail]').innerText()).includes('Отредактировано без оплаты'));
    assert.equal(await other.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    const evidence=path.join(__dirname,'evidence');fs.mkdirSync(evidence,{recursive:true});
    await other.screenshot({path:path.join(evidence,'publication-real-api-320.png'),animations:'disabled'});
    assert.deepEqual(errors,[]);
    console.log('PASS real browser + signed API + PostgreSQL: CP1/CP2, 1/10 photos, lost POST response, double tap, edit without VIP/fee, second user detail, 320/390px');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
