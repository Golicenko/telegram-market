const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname,"..");
const html=fs.readFileSync(path.join(root,"index.html"),"utf8");
const app=fs.readFileSync(path.join(root,"js/app.js"),"utf8");

test("profile contains only the requested primary actions",()=>{
  const profile=html.slice(html.indexOf('<section class="view profile-view"'),html.indexOf('<section class="view" data-view="more"'));
  assert.doesNotMatch(profile,/data-open-info|data-open-support|data-nav-target="settings"|data-open-frozen|data-open-withdraw/);
  const menu=profile.slice(profile.indexOf('class="profile-actions'),profile.indexOf('class="profile-panel'));
  assert.equal((menu.match(/<button /g)||[]).length,6);
  for(const label of ["Пополнение","Мои объявления","История сделок","Диалоги","Обновить данные профиля","Администратор"])assert(menu.includes(label));
  assert.match(menu,/data-open-admin data-admin-only hidden/);
});

test("help has eleven articles, matching shortcuts and no old information modal",()=>{
  const help=app.slice(app.indexOf("function renderHelpCenter()"),app.indexOf("async function openTrainingProduct(id)"));
  assert.equal((help.match(/id: "/g)||[]).length,11);
  for(const anchor of html.matchAll(/data-help-anchor="help-([^"]+)"/g)) assert(help.includes(`id: "${anchor[1]}"`));
  assert.doesNotMatch(html,/id="infoModal"/);
  assert.match(help,/loading: "lazy", decoding: "async"/);
});
test("topup presets keep custom amount and real server confirmation",()=>{
  assert.deepEqual([...html.matchAll(/data-topup-amount="(\d+)"/g)].map(x=>Number(x[1])),[10,15,25,50,75,90,100]);
  assert.match(html,/id="topupAmount"/);
  assert.match(app,/state\.me\.wallet = payment\.wallet/);
  assert.match(app,/kind === "confirmed"/);
  assert.match(app,/dataset\.paymentHistory/);
  assert.doesNotMatch(app,/available_balance\s*\+=/);
});
test("library cards open authorized purchases rather than public product endpoint",()=>{
  const library=app.slice(app.indexOf("function createTrainingLibraryCard"),app.indexOf("function renderMiniListings"));
  assert.match(library,/dataset\.openTrainingPurchase = purchase\.id/);
  assert.match(app,/`\/training\/purchases\/\$\{id\}\/access`/);
  const access=app.slice(app.indexOf("async function openTrainingPurchase"),app.indexOf("function renderHelpCenter"));
  assert.doesNotMatch(access,/\/conversations|\/deals|delivery_reference/);
  assert.match(access,/access\.access_allowed/);
  assert.match(access,/Связаться через поддержку/);
});
test("optional render coalesces same-frame responses but permits later fresh data",()=>{
  const code=app.slice(app.indexOf("let optionalRenderFrame = null;"),app.indexOf("async function loadOptionalData"));
  const frames=[];let renders=0,filters=0;
  const context=vm.createContext({window:{requestAnimationFrame(fn){frames.push(fn);return frames.length;}},renderAll(){renders++;},updateFilterOptions(){filters++;}});
  vm.runInContext(code+"scheduleOptionalRender();scheduleOptionalRender();",context);
  assert.equal(frames.length,1); assert.equal(renders,0);
  frames.shift()(); assert.equal(renders,1);assert.equal(filters,1);
  vm.runInContext("scheduleOptionalRender()",context); frames.shift()();assert.equal(renders,2);
});
