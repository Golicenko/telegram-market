// API/Telegram SDK fixtures in mobile Chromium, not a real-device Telegram test.
const {chromium} = require("playwright");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "..");
const server = http.createServer((req, res) => {
  const file = path.join(root, new URL(req.url, "http://test").pathname.replace(/^\/$/, "/index.html"));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) {res.writeHead(404); return res.end();}
  res.setHeader("Content-Type", file.endsWith(".html") ? "text/html" : file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "image/jpeg");
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({headless:true, channel:"msedge"});
  const base = "http://127.0.0.1:" + server.address().port;
  try {
    for (const width of [320, 360, 390, 430]) {
      let userId = "buyer", deliveryPosts = 0, adminPosts = [], failAdmin = true;
      const users = {buyer:{id:"buyer",first_name:"Покупатель",role:"user",telegram_id:1}, seller:{id:"seller",first_name:"Продавец",role:"user",telegram_id:2}, admin:{id:"admin",first_name:"Администратор",role:"admin",telegram_id:3}};
      const wallet = {available_balance:200,frozen_balance:100,total_earned:0};
      const listing = {id:"car",seller_id:"seller",brand:"BMW",model:"M5",game_version:"car_parking_1",description:"Тест",images:["/images/photo_unique.jpg"],price_af_coins:100,status:"active",listing_type:"regular",power_hp:500,max_speed_kph:250};
      const deal = {id:"deal",buyer_id:"buyer",seller_id:"seller",status:"paid",price_af_coins:100,buyer_game_id:null,seller_delivery_deadline:new Date(Date.now()+86400000).toISOString(),created_at:new Date().toISOString()};
      const messages = [];
      const page = await browser.newPage({viewport:{width,height:740},isMobile:true,hasTouch:true});
      const errors = [];
      page.on("pageerror", e => errors.push(e.message));
      await page.addInitScript(() => {
        window.Telegram = {WebApp:{initData:"fixture",ready(){},expand(){},onEvent(){},safeAreaInset:{top:20,bottom:10},contentSafeAreaInset:{top:12},BackButton:{show(){},hide(){},onClick(){}}}};
        Object.defineProperty(navigator, "clipboard", {value:{writeText:async text => {window.copiedGameId = text;}}});
      });
      await page.route(/^https:/, r => r.abort());
      await page.route("**/api/**", async route => {
        const endpoint = new URL(route.request().url()).pathname.slice(4);
        const user = users[userId];
        const conversation = {id:"thread",conversation_type:"deal",listing,deal,counterparty:{id:userId==="buyer"?"seller":"buyer",name:userId==="buyer"?"Продавец":"Покупатель",username:null,photo_url:null},offers:[]};
        let body = [];
        if (endpoint === "/me") body = {user,wallet};
        else if (endpoint === "/profile") body = {user,wallet,active_listings:[],sold_listings:[],wallet_transactions:[],withdrawals:[],deals:[deal],deal_threads:[],conversations:[]};
        else if (endpoint === "/listings") body = [listing, {...listing,id:"car2",game_version:"car_parking_2"}];
        else if (endpoint === "/content/unseen") body = {training:{unseen_count:0,marker:0},unique:{unseen_count:0,marker:0}};
        else if (endpoint === "/conversations/unread-summary") body = {total_unread:0,conversations:[]};
        else if (endpoint === "/deals/deal") body = {deal};
        else if (endpoint === "/deals/deal/conversation" || endpoint === "/conversations/thread") body = conversation;
        else if (endpoint === "/conversations/thread/messages") body = messages;
        else if (endpoint === "/deals/deal/delivery-details") {
          deliveryPosts++;
          const data = route.request().postDataJSON();
          assert.deepEqual(data, {buyer_game_id:"AB123456"});
          await new Promise(resolve => setTimeout(resolve, 100));
          deal.buyer_game_id = data.buyer_game_id; body = deal;
        } else if (endpoint === "/admin/deals/deal/control") {
          body = {deal,product:"BMW M5",buyer:users.buyer,seller:users.seller,reserved_af_coins:100,seller_payout:100,commission:0,actions:["comment"],events:[],tickets:[],transactions:[],messages,last_buyer_action_at:deal.created_at,last_seller_action_at:deal.created_at};
        } else if (endpoint === "/admin/deals/deal/messages") {
          const data = route.request().postDataJSON(); adminPosts.push(data);
          if (failAdmin) {
            failAdmin = false;
            return route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:"Временная ошибка"})});
          }
          body = {id:"admin-message",sender_id:"admin",message_type:"system",body:"🛡 Администратор\n"+data.body,created_at:new Date().toISOString()};
          messages.push(body);
        }
        return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
      });
      await page.goto(base);
      await page.locator(".listing-game-badge").first().waitFor();
      for (const badge of await page.locator(".listing-game-badge:visible").all()) {
        const metrics = await badge.evaluate(el => {
          const a=el.getBoundingClientRect(), b=el.parentElement.getBoundingClientRect(), css=getComputedStyle(el);
          return {left:a.left-b.left,top:a.top-b.top,right:a.right,bottom:a.bottom,mediaBottom:b.bottom,color:css.color,background:css.backgroundColor};
        });
        assert(metrics.left >= 6 && metrics.left <= 9 && metrics.top >= 6 && metrics.top <= 9);
        assert(metrics.right <= width && metrics.bottom < metrics.mediaBottom);
        assert(!metrics.background.startsWith("rgb(0, 0, 0"));
      }
      const colors = await page.locator(".listing-game-badge:visible").evaluateAll(nodes => nodes.map(n=>getComputedStyle(n).backgroundColor));
      assert.notEqual(colors[0], colors[1]);
      await page.goto(base + "/?deal_id=deal");
      const form = page.locator(".deal-delivery__form"); await form.waitFor();
      assert.equal(await form.locator("input").count(), 1);
      const input = form.locator("input"); assert.equal(await input.getAttribute("inputmode"), "text");
      await input.fill("AB123456");
      await page.setViewportSize({width,height:480}); // Keyboard-sized viewport, not native keyboard.
      const submit = form.locator("button");
      const box = await submit.boundingBox(); assert(box.x>=0 && box.x+box.width<=width && box.y+box.height<=480, JSON.stringify(box));
      await form.evaluate(el=>{el.requestSubmit();el.requestSubmit();});
      await form.waitFor({state:"hidden"}); assert.equal(deliveryPosts, 1);
      await page.reload(); await page.getByText("Продавец получил ваш ID:",{exact:false}).waitFor();
      userId = "seller"; await page.setViewportSize({width,height:740}); await page.reload();
      const timer = page.locator(".seller-delivery-deadline"); await timer.waitFor();
      assert.match(await timer.textContent(), /Осталось: \d+ ч \d+ мин/);
      await page.locator("[data-copy-game-id]").click(); assert.equal(await page.evaluate(()=>window.copiedGameId), "AB123456");
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth), false);
      if (width===390) await page.screenshot({path:path.join(os.tmpdir(),"autoflow-delivery-seller-390.png")});
      deal.seller_delivery_deadline = new Date(Date.now()-1000).toISOString(); await page.reload();
      await page.locator(".seller-delivery-deadline.is-expired").waitFor();
      assert(await page.locator('[data-deal-action="transfer"]').isDisabled());
      userId="admin"; await page.goto(base+"/?admin_deal_id=deal");
      const adminInput=page.locator("#adminDealMessage");
      try {await adminInput.waitFor({timeout:5000});}
      catch (error) {console.log(await page.locator("body").innerText());throw error;}
      await adminInput.fill("Пожалуйста, ответьте");
      const adminSend=page.getByRole("button",{name:"Отправить участникам",exact:true});
      await adminSend.click(); await page.waitForFunction(()=>!document.querySelector(".admin-deal-message button").disabled);
      assert.equal(await adminInput.inputValue(), "Пожалуйста, ответьте");
      await adminSend.click();
      await page.waitForFunction(()=>document.querySelector("#adminDealMessage")?.value==="");
      assert.equal(adminPosts.length,2);assert.equal(adminPosts[0].client_message_id,adminPosts[1].client_message_id);
      assert.match(await page.locator(".deal-timeline").textContent(), /Администратор: 🛡 Администратор/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      assert.deepEqual(errors,[]);
      console.log(width+"px: CP1/CP2 top-left badges, ID-only/reload/copy, seller countdown/expiry, admin retry OK");
      await page.close();
    }
  } finally {await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
