// Real frontend + isolated API fixtures. No live Telegram/payment calls.
const {chromium}=require("playwright");
const http=require("node:http"),fs=require("node:fs"),path=require("node:path"),os=require("node:os"),assert=require("node:assert/strict");
const root=path.resolve(__dirname,"..");
const server=http.createServer((req,res)=>{
  const name=new URL(req.url,"http://test").pathname;
  const file=path.resolve(root,"."+(name==="/"?"/index.html":name));
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}
  res.setHeader("Content-Type",file.endsWith(".html")?"text/html":file.endsWith(".js")?"text/javascript":file.endsWith(".css")?"text/css":"application/json");res.end(fs.readFileSync(file));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
  const browser=await chromium.launch({channel:"msedge",headless:true});
  try{
    for(const role of ["user","admin"])for(const width of [320,360,390,430]){
      const page=await browser.newPage({viewport:{width,height:740},isMobile:true,hasTouch:true});
      const errors=[];let meRequests=0;
      const user={id:"fixture-user",telegram_id:1,first_name:"Пользователь",username:null,photo_url:null,role};
      const wallet={available_balance:100,frozen_balance:0,total_earned:0};
      const thread={id:'thread-1',buyer_id:user.id,seller_id:'seller-1',listing:{brand:'BMW',model:'M5',price_af_coins:100,images:['/images/photo_unique.jpg']},deal:{id:'deal-1',status:'paid',price_af_coins:50},counterparty:{name:'Продавец',username:null},created_at:'2026-09-15T10:00:00Z',unread_count:2};
      page.on("pageerror",e=>errors.push(e.message));
      await page.addInitScript(()=>{window.Telegram={WebApp:{initData:"fixture",ready(){},expand(){},onEvent(){},BackButton:{show(){},hide(){},onClick(){}},safeAreaInset:{top:20,bottom:15},contentSafeAreaInset:{top:12}}};});
      await page.route(/^https:/,route=>route.abort());
      await page.route("**/api/**",route=>{
        const endpoint=new URL(route.request().url()).pathname.slice(4);let body=[];
        if(endpoint==="/me"){meRequests++;body={user,wallet};}
        else if(endpoint==="/profile")body={user,wallet,active_listings:[],sold_listings:[],wallet_transactions:[],withdrawals:[],deal_threads:[thread],conversations:[]};
        else if(endpoint==="/conversations/unread-summary")body={total_unread:2,conversations:[{conversation_id:thread.id,conversation_type:'deal',unread_count:2}]};
        else if(endpoint==="/content/unseen")body={training:{unseen_count:0,marker:0},unique:{unseen_count:0,marker:0}};
        return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/?view=profile`);
      const profile=page.locator('[data-view="profile"]');await profile.waitFor({state:"visible"});
      await page.waitForTimeout(400);
      const menu=profile.locator(".profile-main-actions");
      assert.equal(await menu.locator('[data-profile-tab="deals"] .conversation-unread').textContent(),'2');
      assert.equal(await menu.locator("button:visible").count(),role==="admin"?6:5);
      assert.equal(await profile.locator('[data-open-support],[data-open-info]').count(),2);
      assert.equal(await page.locator('[data-view="more"],[data-view="settings"],[data-refresh-account]').count(),0);
      assert.deepEqual(await page.locator('.bottom-nav button').evaluateAll(nodes=>nodes.map(n=>n.dataset.navTarget)),['unique','training','market','profile']);
      for(const icon of await page.locator('.bottom-nav img').all()){
        assert(await icon.evaluate(img=>img.complete&&img.naturalWidth>0));
        assert.equal(await icon.evaluate(img=>getComputedStyle(img).objectFit),'contain');
        const box=await icon.boundingBox();assert.equal(box.width,28);assert.equal(box.height,28);
      }
      for(const button of await menu.locator("button:visible").all()){
        const b=await button.boundingBox();assert(b.width>=44&&b.height>=44&&b.x>=0&&b.x+b.width<=width&&b.y+b.height<600,JSON.stringify(b));
      }
      await menu.locator('[data-profile-tab="deals"]').click();
      const activity=page.locator('[data-view="activity"]');await activity.waitFor({state:'visible'});
      assert(await activity.locator('[data-profile-panel="deals"]').isVisible());
      const card=activity.locator('.activity-deal-row');
      assert.match(await card.textContent(),/BMW M5/);assert.match(await card.textContent(),/Вы — покупатель/);assert.match(await card.textContent(),/50 AF Coins/);
      assert.equal(await card.locator('[data-open-deal-thread]').getAttribute('data-deal-id'),'deal-1');
      assert.equal(await card.locator('.conversation-unread').textContent(),'2');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await activity.locator('[data-activity-tab="history"]').click();
      assert(await activity.locator('[data-profile-panel="history"]').isVisible());
      assert(await activity.locator('[data-profile-panel="deals"]').isHidden());
      await activity.locator('[data-activity-tab="chats"]').click();
      assert(await activity.locator('[data-profile-panel="chats"]').isVisible());
      await activity.locator('[data-back]').click();await profile.waitFor({state:'visible'});
      await menu.locator('[data-profile-tab="listings"]').click();
      assert(await profile.locator('[data-profile-panel="listings"]').isVisible());
      await menu.locator('[data-open-info]').click();await page.locator('[data-view="help"]').waitFor({state:'visible'});
      await page.locator('.bottom-nav [data-nav-target="profile"]').click();
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      if(role==="admin"&&width===390){await page.waitForTimeout(350);const output=path.join(os.tmpdir(),"autoflow-profile-simple-390.png");await page.screenshot({path:output});console.log("Screenshot: "+output);}
      await menu.locator('[data-open-topup]').click();await page.locator('[data-view="topup"]').waitFor({state:"visible"});
      assert.deepEqual(errors,[]);console.log(`${role} ${width}px: four icons, compact menu, role visibility, activity/history/dialogs/back/information/topup OK`);
      await page.close();
    }
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
