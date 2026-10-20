const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const app = fs.readFileSync(path.join(__dirname, '../js/app.js'), 'utf8');

function loadFunction(name, next, environment) {
  const source = app.slice(app.indexOf(`  function ${name}(`), app.indexOf(`  function ${next}(`));
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
