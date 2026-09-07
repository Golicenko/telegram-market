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
      page.on("pageerror",e=>errors.push(e.message));
      await page.addInitScript(()=>{window.Telegram={WebApp:{initData:"fixture",ready(){},expand(){},onEvent(){},BackButton:{show(){},hide(){},onClick(){}},safeAreaInset:{top:20,bottom:15},contentSafeAreaInset:{top:12}}};});
      await page.route(/^https:/,route=>route.abort());
      await page.route("**/api/**",route=>{
        const endpoint=new URL(route.request().url()).pathname.slice(4);let body=[];
        if(endpoint==="/me"){meRequests++;body={user,wallet};}
        else if(endpoint==="/profile")body={user,wallet,active_listings:[],sold_listings:[],wallet_transactions:[],withdrawals:[],deal_threads:[],conversations:[]};
        else if(endpoint==="/conversations/unread-summary")body={total_unread:0,conversations:[]};
        else if(endpoint==="/content/unseen")body={training:{unseen_count:0,marker:0},unique:{unseen_count:0,marker:0}};
        return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
      });
      await page.goto(`http://127.0.0.1:${server.address().port}/?view=profile`);
      const profile=page.locator('[data-view="profile"]');await profile.waitFor({state:"visible"});
      await page.waitForTimeout(400);
      const menu=profile.locator(".profile-main-actions");
      assert.equal(await menu.locator("button:visible").count(),role==="admin"?6:5);
      assert.equal(await profile.locator('[data-open-support],[data-open-info],[data-nav-target="settings"]').count(),0);
      for(const button of await menu.locator("button:visible").all()){
        const b=await button.boundingBox();assert(b.width>=44&&b.height>=44&&b.x>=0&&b.x+b.width<=width&&b.y+b.height<600,JSON.stringify(b));
      }
      await menu.locator('[data-profile-tab="history"]').click();
      assert(await profile.locator('[data-profile-panel="history"]').isVisible());
      assert(await profile.locator('[data-profile-panel="deals"]').isVisible());
      await menu.locator('[data-profile-tab="chats"]').click();
      assert(await profile.locator('[data-profile-panel="chats"]').isVisible());
      await menu.locator('[data-profile-tab="listings"]').click();
      assert(await profile.locator('[data-profile-panel="listings"]').isVisible());
      const before=meRequests;await menu.locator('[data-refresh-account]').click();
      await page.waitForFunction(()=>!document.querySelector('.profile-main-actions [data-refresh-account]').disabled);
      assert(meRequests>before);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      if(role==="admin"&&width===390){const output=path.join(os.tmpdir(),"autoflow-profile-simple-390.png");await page.screenshot({path:output});console.log("Screenshot: "+output);}
      await menu.locator('[data-open-topup]').click();await page.locator('[data-view="topup"]').waitFor({state:"visible"});
      assert.deepEqual(errors,[]);console.log(`${role} ${width}px: compact menu, role visibility, history/dialogs/listings/refresh/topup OK`);
      await page.close();
    }
  }finally{await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
