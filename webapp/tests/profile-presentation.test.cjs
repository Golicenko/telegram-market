const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const app = fs.readFileSync(path.join(__dirname, '../js/app.js'), 'utf8');

function loadFunction(name, next, environment) {
  let end = app.indexOf(`  function ${next}(`);
  if (end < 0) end = app.indexOf(`  async function ${next}(`);
  const source = app.slice(app.indexOf(`  function ${name}(`), end);
  return vm.runInNewContext(`(${source.trim()})`, environment);
}

function thumbnail(apiBase = 'https://market.example/api') {
  return loadFunction('profileThumbnailUrl', 'renderHistory', {
    URL, window: { location: { origin: 'https://market.example' } }, api: { baseUrl: apiBase },
    absoluteMediaUrl: url => url.startsWith('/') ? apiBase.replace(/\/api$/, '') + url : url,
  });
}

test('profile thumbnails use the existing media endpoint, not a new image service', () => {
  assert.equal(thumbnail()('/api/media/photo-1'), 'https://market.example/api/media/photo-1?preview=true');
  assert.equal(thumbnail()('/api/media/photo-1?v=2'), 'https://market.example/api/media/photo-1?v=2&preview=true');
});

test('relative API base remains supported by profile image rendering', () => {
  assert.equal(thumbnail('/api')('/api/media/photo-1'), 'https://market.example/api/media/photo-1?preview=true');
});

test('legacy images, signed external URLs and malformed historical URLs are not rewritten', () => {
  assert.equal(thumbnail()('/uploads/photo.jpg'), 'https://market.example/uploads/photo.jpg');
  const signed = 'https://cdn.example/car.jpg?signature=Ab%2B12&size=1000';
  assert.equal(thumbnail()(signed), signed);
  assert.equal(thumbnail()('https://cdn.example/api/media/photo-1'), 'https://cdn.example/api/media/photo-1');
  assert.equal(thumbnail()('http://['), 'http://[');
});

function userPresentation(user) {
  const nodes = new Map();
  for (const id of ['profileName','profileUsername','profileTelegramId','copyProfileTelegramId','headerAvatarFallback','profileAvatarFallback','headerAvatarImage','profileAvatarImage']) {
    nodes.set(id, { textContent:'', hidden:false, getAttribute(name){return this[name] ?? null;}, removeAttribute(name){ delete this[name]; } });
  }
  nodes.get('headerAvatarImage').previousElementSibling = nodes.get('headerAvatarFallback');
  nodes.get('profileAvatarImage').previousElementSibling = nodes.get('profileAvatarFallback');
  const state = { me:{ user } };
  const render = loadFunction('renderUser','bind',{state, document:{getElementById:id=>nodes.get(id)}});
  return {nodes,state,render};
}

test('profile identity uses server values; avatar failure and removal restore initials', () => {
  const {nodes,state,render} = userPresentation({telegram_id:9876543210,first_name:'Анна',last_name:'Иванова',username:'anna',photo_url:'https://example/photo.jpg'});
  render();
  assert.equal(nodes.get('profileName').textContent,'Анна Иванова');
  assert.equal(nodes.get('profileUsername').textContent,'@anna');
  assert.equal(nodes.get('profileTelegramId').textContent,'Telegram ID:\n9876543210');
  assert.equal(nodes.get('copyProfileTelegramId').disabled,false);
  const image = nodes.get('profileAvatarImage'), fallback = nodes.get('profileAvatarFallback');
  assert.equal(image.hidden,true); assert.equal(fallback.textContent,'А');
  image.onload(); assert.equal(image.hidden,false); assert.equal(fallback.hidden,true);
  const loaded = image.onload; render(); assert.equal(image.onload,loaded); assert.equal(image.hidden,false);
  image.onerror(); assert.equal(image.hidden,true); assert.equal(fallback.hidden,false);
  state.me.user.photo_url = null; render();
  assert.equal(image.src,undefined); assert.equal(fallback.hidden,false);
});

test('missing Telegram fields produce an honest neutral identity, not reference data', () => {
  const {nodes,render} = userPresentation({telegram_id:null,first_name:'',last_name:null,username:null,photo_url:null});
  render();
  assert.equal(nodes.get('profileName').textContent,'Пользователь');
  assert.equal(nodes.get('profileUsername').textContent,'Username не указан');
  assert.equal(nodes.get('copyProfileTelegramId').disabled,true);
});

test('balance formatting still uses the existing available balance and only adapts its visual size', () => {
  const state={me:{wallet:{available_balance:'1324.74'}}}, nodes=[{},{}], flags=new Map();
  const render=loadFunction('renderBalance','renderUser',{state,document:{
    querySelectorAll:()=>nodes,querySelector:()=>({classList:{toggle:(name,on)=>flags.set(name,on)}}),
  }});
  render(); assert(nodes.every(node=>node.textContent==='1324.74')); assert.equal(flags.get('is-large-balance'),false);
  state.me.wallet.available_balance='1234567890.12'; render();
  assert(nodes.every(node=>node.textContent==='1234567890.12')); assert.equal(flags.get('is-large-balance'),true);
});

function miniListingsPresentation() {
  function node(tagName) {
    return {tagName,children:[],dataset:{},className:'',textContent:'',replacements:0,listeners:new Map(),
      classList:{toggle(){}},setAttribute(){},
      addEventListener(type,listener){this.listeners.set(type,listener);},
      emit(type){this.listeners.get(type)?.();this[`on${type}`]?.();},
      querySelectorAll(selector){return this.children.flatMap(child=>[...(child.tagName===selector?[child]:[]),...child.querySelectorAll(selector)]);},
      remove(){if(this.parent)this.parent.children=this.parent.children.filter(child=>child!==this);},
      append(...children){children.forEach(child=>{child.parent=this;this.children.push(child);});},
      replaceChildren(...children){this.children=children;this.replacements++;}};
  }
  const render=loadFunction('renderMiniListings','profileActionButton',{
    state:{},document:{createElement:node},safeArray:value=>Array.isArray(value)?value:[],
    listingTitle:listing=>listing.title,listingGameLabel:listing=>listing.game_version,
    statusLabel:status=>status,formatDate:value=>value,formatNumber:value=>String(value),
    coin:()=>node('coin'),profileThumbnailUrl:url=>url,profileActionButton:(_icon,label)=>Object.assign(node('button'),{textContent:label}),
  });
  return {render,container:node('section'),node};
}

test('unchanged owned-listing data preserves row identity, while real price/VIP changes update controls', () => {
  const {render,container}=miniListingsPresentation();
  const listing={id:'owned-one',title:'BMW M5',game_version:'car_parking_1',status:'active',images:[],price_af_coins:100,pinned:false};
  render(container,[listing],'No listings',true);
  const originalRow=container.children[0];
  render(container,[JSON.parse(JSON.stringify(listing))],'No listings',true);
  assert.equal(container.children[0],originalRow,'an equal server response must not rebuild existing image/action DOM');
  assert.equal(container.replacements,1);
  listing.price_af_coins=150;listing.pinned=true;listing.pinned_until='2026-10-29T12:00:00Z';
  render(container,[listing],'No listings',true);
  const changedRow=container.children[0];
  assert.notEqual(changedRow,originalRow);
  assert.equal(changedRow.children[2].children[0].textContent,'150');
  assert.equal(changedRow.children[3].children[1].disabled,true);
  assert.equal(changedRow.children[3].children[1].textContent,'Закреплено');
});

test('profile listing memoization is per container and reacts to permissions and empty states', () => {
  const {render,container,node}=miniListingsPresentation(),other=node('section');
  const listings=[{id:'one',title:'Car',game_version:'car_parking_2',status:'active',images:[],price_af_coins:25}];
  render(container,listings,'Empty',true);render(other,listings,'Empty',true);
  assert.equal(container.replacements,1);assert.equal(other.replacements,1);
  render(container,listings,'Empty',false);
  assert.equal(container.children[0].children.length,3,'removing owner controls invalidates the snapshot');
  render(container,[],'No active listings',false);
  assert.equal(container.children[0].textContent,'No active listings');
  render(container,[],'No active listings',false);assert.equal(container.replacements,3);
  render(container,[],'Nothing sold yet',false);
  assert.equal(container.children[0].textContent,'Nothing sold yet');assert.equal(container.replacements,4);
});

test('a failed DOM replacement is not cached as a successful profile render', () => {
  const {render,container}=miniListingsPresentation();
  const listings=[{id:'one',title:'Car',game_version:'car_parking_2',status:'active',images:[],price_af_coins:25}];
  const replace=container.replaceChildren;container.replaceChildren=()=>{throw Error('temporary rendering failure');};
  assert.throws(()=>render(container,listings,'Empty',true),/temporary rendering failure/);
  container.replaceChildren=replace;render(container,listings,'Empty',true);
  assert.equal(container.children.length,1);assert.equal(container.replacements,1);
});

test('a failed profile photo is retried on the next equal server render, without rebuilding successful photos repeatedly', () => {
  const {render,container}=miniListingsPresentation();
  const listings=[{id:'one',title:'Car',game_version:'car_parking_2',status:'active',images:['/car.jpg'],price_af_coins:25}];
  render(container,listings,'Empty',true);
  const row=container.children[0],media=row.children[0],image=media.children[0];
  render(container,listings,'Empty',true);
  assert.equal(container.children[0],row,'healthy image DOM is memoized');
  image.emit('error');
  assert.equal(media.querySelectorAll('img').length,0);assert.equal(media.textContent,'AF');
  render(container,JSON.parse(JSON.stringify(listings)),'Empty',true);
  const recoveredRow=container.children[0],recoveredImage=recoveredRow.children[0].children[0];
  assert.notEqual(recoveredRow,row,'a temporary media failure must invalidate only this container snapshot');
  assert.equal(recoveredImage.src,'/car.jpg');
  render(container,listings,'Empty',true);assert.equal(container.children[0],recoveredRow,'the retry does not disable memoization permanently');
});

test('either image in a profile pair can fail without removing the healthy photo or invalidating other containers', () => {
  for (const failedIndex of [0,1]) {
    const {render,container,node}=miniListingsPresentation(),other=node('section');
    const listings=[{id:'paired',title:'Car',game_version:'car_parking_1',status:'active',images:['/first.jpg','/second.jpg'],price_af_coins:25}];
    render(container,listings,'Empty',true);render(other,listings,'Empty',true);
    const row=container.children[0],otherRow=other.children[0],media=row.children[0];
    const healthy=media.children[1-failedIndex];
    media.children[failedIndex].emit('error');
    assert.deepEqual(media.querySelectorAll('img'),[healthy],'the successful half of the photo pair remains visible');
    assert.notEqual(media.textContent,'AF');
    render(other,listings,'Empty',true);assert.equal(other.children[0],otherRow,'an unrelated healthy container remains memoized');
    render(container,listings,'Empty',true);
    assert.notEqual(container.children[0],row);assert.equal(container.children[0].children[0].children.length,2,'the next equal payload retries the failed pair member');
  }
});

test('a failed training cover is retried on the next equal render while healthy covers preserve DOM identity', () => {
  const {node}=miniListingsPresentation(),cards=node('section');
  const state={me:{user:{id:'buyer',role:'user'}},trainingPurchases:[],training:[{id:'training-one',title:'Урок',cover_url:'/cover.jpg',
    product_type:'automatic',published:true,admin_id:'owner',availability:'available',price_af_coins:25,short_description:'Описание'}]};
  const render=loadFunction('renderTraining','buyNowFlow',{state,
    document:{createElement:node,createTextNode:text=>Object.assign(node('#text'),{textContent:text})},
    elements:{trainingCards:cards,trainingEmpty:{}},absoluteMediaUrl:url=>url,
    trainingTypeLabel:value=>value,trainingAvailabilityLabel:value=>value,formatNumber:value=>String(value),coin:()=>node('coin'),renderTrainingLibrary(){},
  });
  render();
  const originalCard=cards.children[0],cover=originalCard.children[0].children[0].children[0];
  render();assert.equal(cards.children[0],originalCard,'a healthy cover must remain memoized');
  cover.emit('error');render();
  assert.notEqual(cards.children[0],originalCard,'a temporary cover failure must invalidate the training render snapshot');
  assert.equal(cards.children[0].children[0].children[0].children[0].src,'/cover.jpg');
  const recoveredCard=cards.children[0];render();assert.equal(cards.children[0],recoveredCard);
});
