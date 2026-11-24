const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "js", "app.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "..", "css", "style.css"), "utf8");

for (const [kind, enabled] of [['account',false],['account',true],['car',false]]) test(`${kind} checkout checks the existing account switch (${enabled}) without affecting cars`,async()=>{
  const events=[];let checks=0;
  const listing={id:'cached-or-direct-listing',status:'active',seller_id:'seller',product_kind:kind,price_af_coins:100};
  const context={state:{regular:[listing],unique:[],me:{user:{id:'buyer'}}},
    accountSales:{async available(){checks++;return enabled?{enabled:true}:null;}},
    notify:message=>events.push(message),track:()=>events.push('track'),openDialog:()=>events.push('dialog'),
    formatNumber:String,coin:()=>({}),document:{createTextNode:value=>value},
    elements:{purchaseModalTitle:{},purchaseModalText:{},purchaseModalAmount:{replaceChildren(){}},purchaseModalNote:{},purchaseModalAction:{}}};
  vm.runInNewContext(source.slice(source.indexOf('async function buyNowFlow'),source.indexOf('async function closePurchaseFlow')),context);
  await context.buyNowFlow(listing.id);
  assert.equal(checks,kind==='account'?1:0);
  assert.deepEqual(events,kind==='account'&&!enabled?[]:['track','dialog']);
  assert.equal(Boolean(context.state.purchaseFlow),kind!=='account'||enabled);
});

for (const kind of ['car','account']) test(`${kind} purchase reuses success animation once and opens the exact chat without a timer delay`,async()=>{
  const events=[];
  const context={state:{purchaseFlow:{}},elements:{purchaseModal:{open:true,close(){events.push('close');}},successOverlay:{hidden:false}},
    refreshMarketplace:async()=>events.push('refresh'),openDealConversation:async id=>events.push(id),showPurchaseSuccess(title,text,duration){events.push({title,text,duration});}};
  vm.runInNewContext(source.slice(source.indexOf('async function finishListingPurchase'),source.indexOf('function showPurchaseSuccess')),context);
  await context.finishListingPurchase({id:'exact-paid-deal',product_kind:kind});
  assert.deepEqual(events,['close','refresh',{title:'✓ Покупка успешна!',text:'Открываем чат сделки',duration:800},'exact-paid-deal']);assert.equal(context.state.purchaseFlow,null);
  await context.finishListingPurchase({id:'exact-paid-deal',product_kind:kind});
  assert.equal(events.filter(event=>typeof event==='object').length,1,'Repeated completion must not replay success');
  await context.finishListingPurchase({id:'another-paid-deal',product_kind:kind});
  await context.finishListingPurchase({id:'exact-paid-deal',product_kind:kind});
  assert.equal(events.filter(event=>typeof event==='object').length,2,'Returning to an earlier completed request must stay deduplicated');
});

test('failed/cancelled/refunded purchase states never show success',async()=>{
  let shown=0;const context={state:{},elements:{purchaseModal:{open:false}},refreshMarketplace:async()=>{},openDealConversation:async()=>{},showPurchaseSuccess(){shown++;}};
  vm.runInNewContext(source.slice(source.indexOf('async function finishListingPurchase'),source.indexOf('function showPurchaseSuccess')),context);
  for(const status of ['cancelled','failed','refunded'])await context.finishListingPurchase({id:status,status,product_kind:'account'});
  assert.equal(shown,0);
});

test('market refresh failure cannot delay or cancel the committed purchase chat',async()=>{
  let opened=false,reported=false;const context={state:{},elements:{purchaseModal:{open:false}},refreshMarketplace:async()=>{throw Error('offline');},openDealConversation:async()=>{opened=true;},showPurchaseSuccess(){},reportClientError(){reported=true;}};
  vm.runInNewContext(source.slice(source.indexOf('async function finishListingPurchase'),source.indexOf('function showPurchaseSuccess')),context);
  await context.finishListingPurchase({id:'paid-after-network-error',status:'paid'});await Promise.resolve();
  assert.equal(opened,true);assert.equal(reported,true);
});

test("regular and unique cards expose the same server-backed purchase action", () => {
  const cardRenderer = source.slice(source.indexOf("function createListingCard"), source.indexOf("function renderTraining"));
  assert.match(cardRenderer, /buy\.dataset\.buyNow = listing\.id/);
  assert.match(cardRenderer, /buy\.disabled = listing\.status !== "active"/);
  assert.doesNotMatch(cardRenderer, /listing_type\s*===\s*"unique"[\s\S]{0,120}dataset\.buyNow/);
});

test("market has no cart UI and buyer cards expose only one primary action", () => {
  const cardRenderer = source.slice(source.indexOf("function createListingCard"), source.indexOf("function observeVisibleListingCards"));
  assert.doesNotMatch(html, /data-view="cart"|data-open-cart|data-cart-count|Корзина/);
  assert.doesNotMatch(source, /state\.cart|dataset\.cartToggle|\/cart\/items|function renderCart|function checkout/);
  assert.doesNotMatch(cardRenderer, /dataset\.chatListing|dataset\.openListing|dataset\.cartToggle/);
  assert.match(cardRenderer, /buy\.dataset\.buyNow = listing\.id/);
  assert.match(cardRenderer, /Купить за \$\{formatNumber\(effectivePrice\)\} AF/);
  assert.match(css, /\.card-actions\{display:grid;grid-template-columns:minmax\(0,1fr\)/);
});

test("listing details keep primary, secondary and negotiation actions vertically separated", () => {
  assert.match(html, /class="listing-page__buy"[^>]*>Купить</);
  assert.match(html, /class="listing-page__message"[^>]*>Написать</);
  assert.match(html, /class="listing-page__negotiate"[^>]*>Предложить цену</);
  assert.match(css, /\.listing-page__actions\{display:grid;gap:8px\}/);
});

test("purchase flow uses direct checkout and an exact listing-bound top-up intent", () => {
  const purchase = source.slice(source.indexOf("async function executeSafeListingPurchase"), source.indexOf("async function payListingPromotionShortfall"));
  assert.match(purchase, /`\/listings\/\$\{flow\.listing\.id\}\/purchase`/);
  assert.match(purchase, /error\.detail\?\.code === "insufficient_af_coins"/);
  assert.match(purchase, /error\.detail\.missing_af_coins/);
  assert.match(purchase, /`\/listings\/\$\{flow\.listing\.id\}\/purchase-topup-intent`/);
  assert.match(purchase, /`\/wallet\/star-payments\/intents\/\$\{intent\.id\}\/resume-checkout`/);
  assert.doesNotMatch(purchase, /openSecondary\("topup"\)/);
});

test("payment cancellation keeps the flow recoverable without claiming a credit", () => {
  const purchase = source.slice(source.indexOf("async function payListingShortfall"), source.indexOf("async function finishListingPurchase"));
  assert.match(purchase, /invoiceStatus === "cancelled" \|\| invoiceStatus === "failed"/);
  assert.match(purchase, /Баланс не изменён/);
  assert.match(purchase, /waitForStarPayment\(intent\.id\)/);
  assert.match(purchase, /checkout_status === "listing_unavailable"/);
});

test("mobile confirmation is a real accessible dialog", () => {
  assert.match(html, /<dialog class="modal purchase-modal" id="purchaseModal">/);
  assert.match(html, /id="purchaseModalAction"/);
  assert.match(html, /data-close-purchase/);
  assert.match(css, /\.card-actions button\{[^}]*min-height:44px/);
  assert.match(css, /\.purchase-modal \.publish-button,\.purchase-modal \.ghost-button\{width:100%;min-height:46px/);
});
