// Run explicitly with NODE_PATH pointing to an installed Playwright package.
const { chromium } = require("playwright");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "..");
const car = { id:"car-1", seller_id:"seller", listing_type:"regular", status:"active",
  brand:"Test car", model:"", price_af_coins:100, power_hp:1, max_speed_kph:1,
  description:"Test", images:[], likes_count:0, views_count:0 };
const user = { id:"buyer", telegram_id:1, first_name:"Buyer", role:"user" };
const wallet = { available_balance:100, frozen_balance:0, total_earned:0 };
const dialog = { id:"dialog-1", conversation_type:"dialog", listing:car, deal:null,
  counterparty:{ id:"seller", name:"Seller", username:null, photo_url:null }, offers:[] };
const server = http.createServer((req,res) => {
  const name = new URL(req.url,"http://test").pathname;
  const filename = path.join(root, name === "/" ? "index.html" : name);
  if (!filename.startsWith(root) || !fs.existsSync(filename)) { res.writeHead(404); return res.end(); }
  res.setHeader("Content-Type", filename.endsWith(".html") ? "text/html" : filename.endsWith(".js") ? "text/javascript" : filename.endsWith(".css") ? "text/css" : "application/json");
  res.end(fs.readFileSync(filename));
});
(async () => {
  await new Promise(resolve => server.listen(0,"127.0.0.1",resolve));
  const browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || "msedge"});
  try {
    for (const width of [320,360,390,430]) {
      const page = await browser.newPage({viewport:{width,height:844},isMobile:true,hasTouch:true});
      const errors=[];
      let unreadCount = 2;
      const receipts = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.addInitScript(() => {
        window.Telegram = {WebApp:{initData:"fixture",ready(){},expand(){},onEvent(){},
          safeAreaInset:{top:20,left:0,right:0,bottom:10},contentSafeAreaInset:{top:12},
          BackButton:{show(){},hide(){},onClick(fn){window.testTelegramBack=fn;}}}};
      });
      await page.route(/^https:/, route => route.abort());
      await page.route("**/api/**", route => {
        const url = new URL(route.request().url()); const endpoint=url.pathname.slice(4);
        let body=[];
        if(endpoint==="/me") body={user,wallet};
        else if(endpoint==="/profile") body={user,wallet,active_listings:[],sold_listings:[],purchases:[],active_deals:[],deals:[],deal_threads:[],conversations:[],wallet_transactions:[],withdrawals:[]};
        else if(endpoint==="/content/unseen") body={training:{unseen_count:0,marker:0},unique:{unseen_count:0,marker:0}};
        else if(endpoint==="/conversations/unread-summary") body={total_unread:unreadCount,conversations:unreadCount ? [{conversation_id:"dialog-1",conversation_type:"dialog",unread_count:unreadCount}] : []};
        else if(endpoint==="/conversations/dialog-1/messages") body=[1,2].map(n=>({id:"message-"+n,conversation_id:"dialog-1",sender_id:"seller",body:("Message "+n+" ").repeat(80),message_type:"text",is_read:unreadCount===0,created_at:"2026-09-07T12:00:0"+n+"Z"}));
        else if(endpoint==="/conversations/dialog-1/read") { receipts.push(url.searchParams.get("through_message_id")); unreadCount=0; }
        else if(endpoint==="/listings") body=url.searchParams.get("type")==="regular"?[car]:[];
        else if(endpoint==="/listings/car-1") body=car;
        else if(endpoint==="/conversations/listing/car-1" || endpoint==="/conversations/dialog-1") body=dialog;
        return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
      });
      await page.goto("http://127.0.0.1:"+server.address().port);
      await page.locator('[data-listing-card="car-1"]').click();
      const header=page.locator(".listing-page__header");
      await header.waitFor({state:"visible"});
      await page.waitForTimeout(500);
      const button=await header.locator("[data-back]").boundingBox();
      const title=await header.locator("span").boundingBox();
      assert(button.width>=44 && button.height>=44 && button.x>=8,JSON.stringify({button,errors}));
      assert(title.x>=button.x+button.width);
      assert(button.y>=32, JSON.stringify({button,safe:await page.evaluate(()=>({css:document.documentElement.style.cssText,telegram:window.Telegram.WebApp.safeAreaInset})),errors}));
      await page.locator("#listingPageChat").click();
      await page.locator('[data-view="deal-chat"]').waitFor({state:"visible"});
      await page.setViewportSize({width,height:420});
      await page.locator("#chatInput").fill("Mobile keyboard test");
      await page.waitForTimeout(200);
      const composer = await page.locator("#chatForm").boundingBox();
      assert(composer.y >= 0 && composer.y + composer.height <= 420, JSON.stringify(composer));
      await page.setViewportSize({width,height:844});
      await page.evaluate(() => { window.testTelegramBack(); window.testTelegramBack(); });
      await page.locator('[data-view="listing-detail"]').waitFor({state:"visible"});
      await page.waitForTimeout(500);
      await header.locator("[data-back]").click();
      await page.locator('[data-view="market"]').waitFor({state:"visible"});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),false);
      assert.deepEqual(errors,[]);
      unreadCount=2;
      await page.goto("http://127.0.0.1:"+server.address().port+"/?conversation_id=dialog-1");
      await page.locator('[data-view="deal-chat"]').waitFor({state:"visible"});
      await page.waitForFunction(()=>document.querySelector("#chatUnreadBadge").hidden);
      assert(receipts.includes("message-2"));
      const history = await page.locator("#dealMessages").evaluate(el=>({top:el.scrollTop,height:el.clientHeight,total:el.scrollHeight}));
      assert(history.top+history.height>=history.total-2,JSON.stringify(history));
      assert.deepEqual(errors,[]);
      console.log(width+"px: listing header, safe area, resized chat composer, dialog/back, double tap, overflow OK");
      console.log(width+"px: exact-chat deep link, read-through receipt, badge cleared, scroll-to-last OK");
      await page.close();
    }
  } finally { await browser.close(); server.close(); }
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
