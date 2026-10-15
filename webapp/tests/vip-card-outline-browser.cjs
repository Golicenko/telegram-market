// Real card renderer/CSS, isolated API and a clearly labelled test illustration.
// This is viewport/Telegram-platform emulation, not a physical iOS/Android test.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), http = require('node:http');
const root = path.resolve(__dirname, '..');
const photo = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">
  <defs><linearGradient id="sky" x2="0" y2="1"><stop stop-color="#385c75"/><stop offset="1" stop-color="#132636"/></linearGradient>
  <linearGradient id="paint" x2="0" y2="1"><stop stop-color="#ecf3f8"/><stop offset=".5" stop-color="#8bafc7"/><stop offset="1" stop-color="#456078"/></linearGradient></defs>
  <path fill="url(#sky)" d="M0 0h640v480H0z"/><path fill="#15202b" d="M0 310h640v170H0z"/>
  <path stroke="#51616b" stroke-width="3" d="M0 420h640"/>
  <ellipse fill="#060e17" cx="326" cy="371" rx="273" ry="29"/>
  <path fill="url(#paint)" d="M60 297l48-36 89-8 64-68h140l82 79 80 21 20 57-19 16H69l-17-17z"/>
  <path fill="#102734" d="M222 249l52-53h48v53zm111-53h61l57 53H333z"/>
  <path fill="#d1e9f3" d="M66 295h48v17H61zm473-4 29 7 6 20h-28z"/>
  <path stroke="#314555" stroke-width="3" fill="none" d="M319 262v75m139-72 10 66M97 328h433"/>
  <g fill="#09111b" stroke="#32404a" stroke-width="5"><circle cx="166" cy="347" r="44"/><circle cx="477" cy="347" r="44"/></g>
  <g fill="#90a5b4" stroke="#445867" stroke-width="9"><circle cx="166" cy="347" r="24"/><circle cx="477" cy="347" r="24"/></g>
  <text x="320" y="452" fill="#aebfcd" text-anchor="middle" font-family="sans-serif" font-size="17">ТЕСТОВАЯ ИЛЛЮСТРАЦИЯ · НЕ ОБЪЯВЛЕНИЕ</text>
</svg>`;
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://fixture').pathname;
  const file = path.resolve(root, '.' + (pathname === '/' ? '/index.html' : pathname));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) { res.writeHead(404); return res.end(); }
  res.setHeader('Content-Type', ({'.html':'text/html','.js':'text/javascript','.css':'text/css','.png':'image/png','.jpg':'image/jpeg'})[path.extname(file)] || 'application/json');
  res.end(fs.readFileSync(file));
});

async function appearance(card) {
  const id=await card.getAttribute('data-listing-card');
  // Catalogue refresh can replace a locator's resolved node before evaluation.
  // Resolve and measure the current node atomically in the same JS task.
  return card.page().evaluate(id => {
    const el=document.querySelector(`[data-listing-card="${id}"]`);
    const media = el.querySelector('.car-card__media'), img = media.querySelector('img');
    const cardStyle = getComputedStyle(el), imgStyle = getComputedStyle(img);
    const box = el.getBoundingClientRect(), imageBox = img.getBoundingClientRect();
    return {
      width:box.width, height:box.height,
      photo:{src:img.getAttribute('src'),x:imageBox.x-box.x,y:imageBox.y-box.y,width:imageBox.width,height:imageBox.height,fit:imgStyle.objectFit,transform:imgStyle.transform},
      borders:[cardStyle.borderTopWidth,cardStyle.borderRightWidth,cardStyle.borderBottomWidth,cardStyle.borderLeftWidth],
      backgroundClip:cardStyle.backgroundClip, shadow:cardStyle.boxShadow,
      imageBorder:imgStyle.borderWidth, mediaBorder:getComputedStyle(media).borderWidth,
      overlays:[el,media,img].flatMap(node => ['::before','::after'].map(pseudo => getComputedStyle(node,pseudo).content)),
    };
  },id);
}

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ ...(process.env.CI ? {} : {channel:'msedge'}), headless:true });
  try {
    for (const platform of ['ios','android']) for (const width of [320,360,390,430]) {
      const game = [320,390].includes(width) ? 1 : 2;
      const context = await browser.newContext({viewport:{width,height:844},isMobile:true,hasTouch:true});
      const page = await context.newPage(), errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const png=Buffer.from(await page.evaluate(async svg=>{
        const img=new Image(); img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg); await img.decode();
        const canvas=document.createElement('canvas'); canvas.width=640;canvas.height=480;
        canvas.getContext('2d').drawImage(img,0,0);
        return canvas.toDataURL('image/png').split(',')[1];
      },photo),'base64');
      await context.route('**/test-car.png',route=>route.fulfill({contentType:'image/png',body:png}));
      await page.clock.install({time:new Date('2026-10-15T12:00:00Z')});
      await context.route(/^https:/, route => route.fulfill({status:200,body:''}));
      await context.addInitScript(platform => {
        window.Telegram={WebApp:{initData:'isolated-fixture',platform,ready(){},expand(){},onEvent(){},offEvent(){},BackButton:{show(){},hide(){},onClick(){},offClick(){}},safeAreaInset:{top:24,bottom:34},contentSafeAreaInset:{top:12,bottom:0}}};
      }, platform);
      const user={id:'viewer',first_name:'Визуальная проверка',role:'user'};
      const wallet={available_balance:100,frozen_balance:0};
      const base={seller_id:'seller',brand:'BMW',model:'M5 F90',description:'Тестовый пример для сравнения оформления',power_hp:1695,max_speed_kph:920,price_af_coins:150,game_version:`car_parking_${game}`,listing_type:'regular',status:'active',images:['/test-car.png'],created_at:'2026-10-15T12:00:00Z'};
      const listings=[{...base,id:'ordinary',pinned:false},{...base,id:'vip',pinned:true,pinned_until:'2026-10-15T12:01:00Z'}];
      await context.route('**/api/**', async route => {
        const url=new URL(route.request().url()), endpoint=url.pathname.slice(4);
        let body=[];
        if(endpoint==='/me')body={user,wallet};
        else if(endpoint==='/profile')body={user,wallet,active_listings:[],sold_listings:[],deals:[],conversations:[],wallet_transactions:[],withdrawals:[]};
        else if(endpoint==='/content/unseen')body={unique:{unseen_count:0,marker:0},training:{unseen_count:0,marker:0}};
        else if(endpoint==='/listings')body=url.searchParams.get('type')==='regular'?listings:[{...listings[1],id:'unique-vip',listing_type:'unique'}];
        else if(endpoint.endsWith('/view'))body={views_count:0,likes_count:0,liked_by_me:false};
        else if(endpoint.startsWith('/listings/'))body=listings.find(l=>endpoint===`/listings/${l.id}`);
        await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/`);
      const ordinary=page.locator('#marketCars [data-listing-card=ordinary]');
      const vip=page.locator('#marketCars [data-listing-card=vip]');
      await vip.waitFor(); await page.locator('#marketCars img').evaluateAll(imgs=>Promise.all(imgs.map(img=>img.decode())));
      // Finish the screen entrance before measuring screenshot clip coordinates.
      await page.screenshot({animations:'disabled'});
      const normal=await appearance(ordinary), premium=await appearance(vip);
      assert.deepEqual(premium.photo,normal.photo,'VIP must keep the same source, crop, position and size');
      assert.equal(premium.width,normal.width); assert.equal(premium.height,normal.height);
      assert.deepEqual(premium.borders,['1px','1px','1px','1px']);
      assert.equal(premium.backgroundClip,'padding-box, border-box');
      assert.equal(premium.imageBorder,'0px'); assert.equal(premium.mediaBorder,'0px');
      assert(premium.overlays.every(content=>content==='none'),'no decorative card/photo pseudo-elements');
      assert(!premium.shadow.includes('inset'),'no extra inset outline');
      assert.equal(await vip.locator('.car-vip-badge').textContent(),'👑 VIP');
      assert.equal(await ordinary.locator('.car-vip-badge').isVisible(),false);
      const vipBadge=await vip.locator('.car-vip-badge').boundingBox(), gameBadge=await vip.locator('.listing-game-badge').boundingBox();
      assert(vipBadge.y+vipBadge.height<=gameBadge.y,'VIP and CP labels cannot overlap');
      // Compare the same viewport pixels below the metadata labels. Comparing two
      // different screen positions introduces Chromium rasterisation differences.
      const photoPixels=async card=>{
        const box=await card.locator('img').boundingBox();
        return page.screenshot({clip:{x:box.x,y:box.y+60,width:box.width,height:box.height-62},animations:'disabled'});
      };
      await page.screenshot({path:path.join(__dirname,`vip-outline-${platform}-${width}.png`),animations:'disabled'});
      const vipPixels=await photoPixels(vip);
      await vip.evaluate(el=>el.classList.remove('is-pinned'));
      const ordinaryPixels=await photoPixels(vip);
      await vip.evaluate(el=>el.classList.add('is-pinned'));
      assert(vipPixels.equals(ordinaryPixels),'VIP class must not alter the rendered image pixels');
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await vip.locator('img').click();
      await page.locator('[data-view=listing-detail]').waitFor({state:'visible'});
      assert.equal(await page.locator('#listingPageGame').textContent(),`Car Parking ${game}`);
      await page.locator('.bottom-nav [data-nav-target=market]').click();
      await page.locator('[data-view=market]').waitFor({state:'visible'});
      await page.emulateMedia({reducedMotion:'reduce'});
      await page.waitForFunction(()=>{
        const el=document.querySelector('#marketCars .is-pinned');
        return el && getComputedStyle(el).animationName==='none';
      });
      // Unique cards share the renderer: the VIP rule must also replace their old shadow ring.
      const unique=page.locator('#uniqueCars .car-card.is-pinned');
      assert.equal((await appearance(unique)).shadow,premium.shadow);
      await page.clock.fastForward(61000);
      await page.waitForFunction(()=>!document.querySelector('#marketCars .is-pinned'));
      await vip.waitFor();
      const expired=await appearance(vip);
      assert.deepEqual(expired.photo,premium.photo);
      assert.equal(expired.width,premium.width); assert.equal(expired.height,premium.height);
      assert.equal(expired.backgroundClip,normal.backgroundClip);
      assert.equal(await vip.locator('.car-vip-badge').isVisible(),false);
      assert.deepEqual(errors,[]);
      console.log(`PASS ${platform} ${width} CP${game}: one outer contour, identical photo pixels, clicks, unique, reduced motion, expiry without layout shift`);
      await context.close();
    }
  } finally { await browser.close();await new Promise(resolve=>server.close(resolve)); }
})().catch(error=>{console.error(error);process.exitCode=1;});
