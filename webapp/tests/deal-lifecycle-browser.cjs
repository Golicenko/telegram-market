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
      const page=await browser.newPage({viewport:{width,height:844},isMobile:true,hasTouch:true});
      let transfers=0; const errors=[];
      const user={id:"seller",telegram_id:2,first_name:"Seller",role:"user"};
      const wallet={available_balance:200,frozen_balance:0,total_earned:0};
      const listing={id:"car",seller_id:"seller",brand:"Car",model:"",description:"Test",images:[],price_af_coins:100,status:"reserved",listing_type:"regular"};
      const deal={id:"deal",buyer_id:"buyer",seller_id:"seller",status:"paid",price_af_coins:100,buyer_game_id:"AB123456",buyer_server:"Test",preferred_delivery_time:"2026-09-07T19:00:00+03:00",delivery_timezone:"Europe/Moscow"};
      const conversation={id:"thread",conversation_type:"deal",listing,deal,counterparty:{id:"buyer",name:"Buyer",username:null,photo_url:null},offers:[]};
      page.on("pageerror",error=>errors.push(error.message));
      await page.addInitScript(()=>{window.Telegram={WebApp:{initData:"fixture",ready(){},expand(){},onEvent(){},safeAreaInset:{top:20,bottom:10},contentSafeAreaInset:{top:12},BackButton:{show(){},hide(){},onClick(){}}}};});
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
          transfers++; await new Promise(resolve=>setTimeout(resolve,150));
          deal.status="transfer_in_progress";deal.transfer_started_at=new Date().toISOString();body=deal;
        }
        await route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
      });
      const base="http://127.0.0.1:"+server.address().port;
      await page.goto(base+"/?deal_id=deal");
      const transfer=page.locator('[data-deal-action="transfer"]');await transfer.waitFor();
      await page.waitForTimeout(300); // Let initial read receipts/optional rendering settle.
      // Two initial taps open only one confirmation and no mutation request.
      await transfer.click({clickCount:2});
      await page.locator("dialog.critical-confirm").waitFor();
      assert.equal(transfers,0);assert.equal(await page.locator("dialog.critical-confirm").count(),1);
      await page.locator("dialog.critical-confirm").getByRole("button",{name:"Отмена",exact:true}).click();
      assert.equal(transfers,0);
      await transfer.click();
      const confirm=page.locator("dialog.critical-confirm .publish-button");
      const box=await confirm.boundingBox();assert(box.width>=44&&box.height>=44&&box.x>=0&&box.x+box.width<=width);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await confirm.evaluate(el=>{el.click();el.click();});
      await transfer.waitFor({state:"hidden"});
      assert.equal(transfers,1);
      assert(await page.locator('[data-view="deal-chat"]').isVisible());
      await page.reload();
      await page.locator('[data-view="deal-chat"]').waitFor({state:"visible"});
      assert.equal(transfers,1);
      await page.goto(base+"/?view=profile");
      await page.locator('[data-view="profile"]').waitFor({state:"visible"});
      assert.deepEqual(errors,[]);
      console.log(width+"px: confirmation cancel/double tap/one POST, retained deal chat/reload, profile deep link OK");
      await page.close();
    }
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
