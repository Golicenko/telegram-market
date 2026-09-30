// Mobile browser regression test with explicit API fixtures; NOT real Telegram E2E.
const {chromium} = require("playwright");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname,"..");
const server = http.createServer((req,res)=>{
  const name = new URL(req.url,"http://test").pathname;
  const filename = path.join(root,name === "/" ? "index.html" : name);
  if(!filename.startsWith(root) || !fs.existsSync(filename)){res.writeHead(404);return res.end();}
  res.setHeader("Content-Type",filename.endsWith(".html")?"text/html":filename.endsWith(".js")?"text/javascript":filename.endsWith(".css")?"text/css":"application/json");
  res.end(fs.readFileSync(filename));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  const browser = await chromium.launch({headless:true,channel:"msedge"});
  try{
    for(const width of [320,360,390,430]){
      const page=await browser.newPage({viewport:{width,height:width===320?568:844},isMobile:true,hasTouch:true});
      let transfers=0, receipts=0, failTransfer=true; const errors=[];
      let user={id:"seller",telegram_id:2,first_name:"Seller",role:"user"};
      const wallet={available_balance:200,frozen_balance:0,total_earned:0};
      const listing={id:"car",seller_id:"seller",brand:"Car",model:"",description:"Test",images:[],price_af_coins:100,status:"reserved",listing_type:"regular"};
      const deal={id:"deal",buyer_id:"buyer",seller_id:"seller",status:"paid",price_af_coins:100,buyer_game_id:"AB123456",buyer_server:"Test",preferred_delivery_time:"2026-09-07T19:00:00+03:00",delivery_timezone:"Europe/Moscow"};
      const conversation={id:"thread",conversation_type:"deal",listing,deal,counterparty:{id:"buyer",name:"Buyer",username:null,photo_url:null},offers:[]};
      page.on("pageerror",error=>errors.push(error.message));
      await page.addInitScript(()=>{
        window.testHaptics=[];
        window.Telegram={WebApp:{initData:"fixture",ready(){},expand(){},onEvent(){},safeAreaInset:{top:20,bottom:10},contentSafeAreaInset:{top:12},
          HapticFeedback:{impactOccurred(v){window.testHaptics.push(v);},notificationOccurred(v){window.testHaptics.push(v);}},
          BackButton:{show(){},hide(){},onClick(fn){window.testBack=fn;}}}};
        Object.defineProperty(navigator,"clipboard",{value:{async writeText(value){window.copiedId=value;}}});
      });
      await page.route(/^https:/,route=>route.abort());
      await page.route("**/api/**",async route=>{
        const endpoint=new URL(route.request().url()).pathname.slice(4);let body=[];
        if(endpoint==="/me")body={user,wallet};
        else if(endpoint==="/profile")body={user,wallet,active_listings:[],sold_listings:[],purchases:[],active_deals:[deal],deals:[deal],deal_threads:[],conversations:[],wallet_transactions:[],withdrawals:[]};
        else if(endpoint==="/content/unseen")body={training:{unseen_count:0,marker:0},unique:{unseen_count:0,marker:0}};
        else if(endpoint==="/conversations/unread-summary")body={total_unread:0,conversations:[]};
        else if(endpoint==="/deals/deal")body={deal};
        else if(endpoint==="/deals/deal/conversation" || endpoint==="/conversations/thread")body=conversation;
        else if(endpoint==="/deals/deal/transfer"){
          transfers++; await new Promise(resolve=>setTimeout(resolve,400));
          if(failTransfer){failTransfer=false;return route.fulfill({status:500,contentType:"application/json",body:JSON.stringify({detail:"RAW_STACK_TRACE"})});}
          deal.status="transfer_in_progress";deal.transfer_started_at=new Date().toISOString();body=deal;
        }
        else if(endpoint==="/deals/deal/confirm"){
          receipts++; await new Promise(resolve=>setTimeout(resolve,400));
          deal.status="completed";body=deal;
        }
        await route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
      });
      const base="http://127.0.0.1:"+server.address().port;
      await page.goto(base+"/?deal_id=deal");
      const transfer=page.locator('[data-deal-action="transfer"]');await transfer.waitFor();
      await page.waitForTimeout(300); // Let initial read receipts/optional rendering settle.
      // Two initial taps open only one confirmation and no mutation request.
      await transfer.click({clickCount:2});
      const modal=page.locator("dialog.deal-confirmation");
      await modal.waitFor();
      assert.equal(transfers,0);assert.equal(await modal.count(),1);
      assert.equal(await page.evaluate(()=>document.body.style.position),"fixed");
      assert.equal(await modal.getAttribute("aria-modal"),"true");
      await modal.getByRole("button",{name:"Скопировать",exact:true}).click();
      assert.equal(await page.evaluate(()=>window.copiedId),"AB123456");
      await modal.getByRole("button",{name:"Нет, вернуться",exact:true}).click();
      await modal.waitFor({state:"detached"});
      assert.equal(transfers,0);
      for (const cancelWith of ["escape","telegram","backdrop"]) {
        await transfer.click(); await modal.waitFor();
        if(cancelWith==="escape")await page.keyboard.press("Escape");
        else if(cancelWith==="telegram")await page.evaluate(()=>window.testBack());
        else { await page.waitForTimeout(500); await page.mouse.click(2,2); }
        await modal.waitFor({state:"detached"});assert.equal(transfers,0);
        assert(await page.locator('[data-view="deal-chat"]').isVisible());
      }
      await transfer.click();
      const confirm=modal.locator(".publish-button");
      await page.waitForFunction(()=>!document.querySelector(".deal-confirmation .publish-button")?.disabled);
      if(process.env.TRANSFER_SCREENSHOT_DIR)await page.screenshot({path:path.join(process.env.TRANSFER_SCREENSHOT_DIR,"transfer-"+width+".png")});
      const box=await confirm.boundingBox();assert(box.width>=44&&box.height>=44&&box.x>=0&&box.x+box.width<=width);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await confirm.evaluate(el=>{el.click();el.click();});
      assert(await confirm.isDisabled());
      await modal.getByText("Не удалось подтвердить передачу. Попробуйте ещё раз.",{exact:true}).waitFor();
      assert.equal(transfers,1);assert.equal(deal.status,"paid");
      assert(!(await modal.innerText()).includes("RAW_STACK_TRACE"));assert(!(await confirm.isDisabled()));
      await confirm.evaluate(el=>{el.click();el.click();});
      await page.evaluate(()=>window.testBack()); // Pending request cannot navigate or resubmit.
      await modal.getByText("Передача отмечена",{exact:true}).waitFor();
      assert(await modal.isVisible());assert(await confirm.isDisabled());
      await modal.waitFor({state:"detached"});
      await transfer.waitFor({state:"hidden"});
      assert.equal(transfers,2); // One failed request + one successful retry.
      assert.equal(await page.evaluate(()=>document.body.style.position),"");
      assert.deepEqual(await page.evaluate(()=>window.testHaptics.filter(v=>v!=="light")),["error","success"]);
      await page.getByText("⏳ Ожидаем подтверждения покупателя",{exact:true}).waitFor();
      assert(await page.locator('[data-view="deal-chat"]').isVisible());
      await page.reload();
      await page.locator('[data-view="deal-chat"]').waitFor({state:"visible"});
      assert.equal(transfers,2);
      user={id:"buyer",telegram_id:1,first_name:"Buyer",role:"user"};
      deal.transfer_started_at=new Date(Date.now()-61000).toISOString();
      await page.reload();
      const receipt=page.locator('[data-deal-action="confirm"]');await receipt.waitFor({state:"visible"});
      await receipt.click();await modal.waitFor();
      await modal.getByRole("heading",{name:"Автомобиль получен?"}).waitFor();
      assert.equal(receipts,0);
      await modal.getByRole("button",{name:"Нет, вернуться",exact:true}).click();await modal.waitFor({state:"detached"});
      assert.equal(receipts,0);
      await receipt.click();await modal.waitFor();
      await page.waitForFunction(()=>!document.querySelector(".deal-confirmation .publish-button")?.disabled);
      await modal.getByRole("button",{name:"Да, получил",exact:true}).evaluate(el=>{el.click();el.click();});
      await modal.getByText("Сделка завершена",{exact:true}).waitFor();
      await modal.waitFor({state:"detached"});
      assert.equal(receipts,1);assert.equal(deal.status,"completed");
      await page.goto(base+"/?view=profile");
      await page.locator('[data-view="profile"]').waitFor({state:"visible"});
      assert.deepEqual(errors,[]);
      console.log(width+"px: seller/buyer cancel, Back/Escape/backdrop, copy ID, error/retry, loading/success, double tap, reload, no overflow OK");
      await page.close();
    }
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
