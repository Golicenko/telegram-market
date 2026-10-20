const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../js/referrals.js'), 'utf8');
const helpers = vm.runInNewContext(`(() => { ${source.slice(source.indexOf('  const number'), source.indexOf('  async function copyFullUrl'))} return { friends, inviteFriends, rewardPresentation }; })()`);
const presentation = (count, required, completed = false) => helpers.rewardPresentation({ count: required, reward: 10, completed }, count);

test('all requested counts retain exact remaining/progress without claiming unconfirmed rewards', () => {
  for (const count of [0, 1, 2, 3, 8, 10, 17, 20, 25]) for (const required of [3, 10, 20]) {
    const view = presentation(count, required);
    assert.equal(view.remaining, Math.max(0, required - count));
    assert.equal(view.progress, Math.min(count, required));
    assert.equal(view.maximum, required); assert.equal(view.completed, false);
    assert.doesNotMatch(view.description, /уже начислены/);
    if (count >= required) assert.match(view.description, /Ожидаем подтверждения/);
  }
  assert.equal(presentation(8, 10).progress / 10, .8);
  assert.equal(presentation(17, 20).progress / 20, .85);
});

test('Russian card labels and invitation phrases use grammatical word forms', () => {
  for (const [count, expected] of [[1, 'друг'], [2, 'друга'], [3, 'друга'], [4, 'друга'], [5, 'друзей'], [11, 'друзей'], [14, 'друзей'], [21, 'друг'], [22, 'друга'], [25, 'друзей'], [111, 'друзей']]) assert.equal(helpers.friends(count), expected);
  assert.equal(helpers.inviteFriends(1), 'друга'); assert.equal(helpers.inviteFriends(2), 'друзей');
  assert.match(presentation(2, 3).description, /ещё 1 друга/);
  assert.match(presentation(1, 3).description, /ещё 2 друзей/);
});

test('only strict persisted completion can produce received text', () => {
  assert.equal(presentation(25, 3, 'true').completed, false);
  assert.equal(presentation(25, 3, 1).completed, false);
  const confirmed = presentation(3, 3, true);
  assert.equal(confirmed.title, 'Награда получена'); assert.match(confirmed.description, /10 AF уже начислены/);
});

class Node {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.parentElement = null; this.dataset = {}; this.attributes = {};
    this.listeners = new Map(); this.style = { overflow: '', position: '', top: '', width: '' };
    this._text = ''; this.value = ''; this.hidden = false; this.disabled = false; this.inert = false; this.open = false; this.replacements = 0;
    const classes = new Set();
    this.classList = { add: (...names) => names.forEach(name => classes.add(name)), remove: (...names) => names.forEach(name => classes.delete(name)), contains: name => classes.has(name), toggle: (name, enabled) => { if (enabled ?? !classes.has(name)) classes.add(name); else classes.delete(name); } };
    Object.defineProperty(this, 'className', { get: () => [...classes].join(' '), set: value => { classes.clear(); String(value).split(/\s+/).filter(Boolean).forEach(name => classes.add(name)); } });
  }
  get textContent() { return this._text + this.children.map(node => node.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  get isConnected() { return true; }
  append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } }
  replaceChildren(...nodes) { this.children = []; this.replacements++; this.append(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); if (name === 'open') this.open = true; }
  removeAttribute(name) { delete this.attributes[name]; if (name === 'open') this.open = false; }
  addEventListener(name, handler) { if (!this.listeners.has(name)) this.listeners.set(name, []); this.listeners.get(name).push(handler); }
  emit(name, event = {}) { return Promise.all((this.listeners.get(name) || []).map(handler => handler({ target: this, preventDefault() {}, ...event }))); }
  matches(selector) {
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    if (selector === 'button:not([disabled])') return this.tagName === 'button' && !this.disabled;
    if (selector.startsWith('[data-')) return this.attributes[selector.slice(1, -1)] !== undefined || selector === '[data-referral-milestone]' && this.dataset.referralMilestone !== undefined;
    return false;
  }
  querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector); }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  focus() { this.document.activeElement = this; }
  select() {}
  setSelectionRange() {}
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(node => node !== this); }
  showModal() { this.open = true; }
  close() { this.open = false; void this.emit('close'); }
  getBoundingClientRect() { return { left: 100, right: 300, top: 100, bottom: 300 }; }
}

function summary(count = 1, completed = [false, false, false]) {
  return { referralCode: 'Ab123x', referralUrl: 'https://t.me/TestBot?startapp=Ab123x', referralCount: count, referralLimit: 20, commissionPercent: 5, canInvite: count < 20,
    milestones: [3, 10, 20].map((required, index) => ({ count: required, reward: [10, 15, 50][index], completed: completed[index] })) };
}

function fixture(initial = summary(), options = {}) {
  const nodes = new Map(), timers = new Map(), intervals = new Map(), frames = new Map(), requests = [], notices = [], scrolls = [];
  let clock = 1000, timerId = 0, walletReads = 0, response = initial, pending = null;
  const document = { hidden: false, activeElement: null, listeners: new Map() };
  const createNode = tag => { const node = new Node(tag); node.document = document; return node; };
  document.body = createNode('body');
  document.createElement = createNode; document.createElementNS = (_ns, tag) => createNode(tag);
  document.execCommand = () => false;
  document.getElementById = id => nodes.get(id);
  document.addEventListener = (name, handler) => { if (!document.listeners.has(name)) document.listeners.set(name, []); document.listeners.get(name).push(handler); };
  const root = createNode('section'), dialog = createNode('dialog'); document.body.append(root, dialog);
  document.querySelector = () => root;
  for (const id of ['referralShare', 'referralShareLabel', 'referralContent', 'referralStatus', 'referralRetry', 'referralPercent', 'referralCount', 'referralMilestones', 'referralLimit', 'referralUrl', 'referralRewardTitle', 'referralRewardDescription', 'referralRewardProgressLabel', 'referralRewardProgress', 'referralRewardStatus']) {
    const node = createNode(id === 'referralShare' || id === 'referralRetry' ? 'button' : 'span'); nodes.set(id, node);
    (id.startsWith('referralReward') ? dialog : root).append(node);
  }
  nodes.set('referralRewardModal', dialog);
  nodes.get('referralShare').append(nodes.get('referralShareLabel'));
  const shareIcon = createNode('svg'); nodes.get('referralShare').append(shareIcon);
  const copies = [createNode('button'), createNode('button')]; copies.forEach(node => { node.setAttribute('data-copy-referral', ''); root.append(node); });
  const close = createNode('button'); close.setAttribute('data-close-referral-reward', ''); dialog.append(close);
  const window = { scrollY: 120, scrollTo(options) { scrolls.push(options.top); window.scrollY = options.top; }, matchMedia: () => ({ matches: Boolean(options.reducedMotion) }),
    setTimeout(callback) { const id = ++timerId; timers.set(id, callback); return id; }, clearTimeout: id => timers.delete(id),
    setInterval(callback) { const id = ++timerId; intervals.set(id, callback); return id; }, clearInterval: id => intervals.delete(id),
    requestAnimationFrame(callback) { const id = ++timerId; frames.set(id, callback); return id; }, cancelAnimationFrame: id => frames.delete(id),
  };
  const api = { async request(endpoint, requestOptions) { requests.push([endpoint, requestOptions]); if (endpoint === '/referrals') return pending ? pending.promise : JSON.parse(JSON.stringify(response)); return { preparedMessageId: 'prepared' }; } };
  class ClockDate extends Date { static now() { return clock; } }
  const clipboard = { async writeText() {} };
  const context = { window, document, navigator: { clipboard }, HTMLElement: Node, Intl, Date: ClockDate, console };
  vm.runInNewContext(source, context);
  const controller = window.AutoFlowReferrals.create({ api, notify: text => notices.push(text), async refreshWallet() { walletReads++; } });
  const flush = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); };
  return { controller, nodes, root, dialog, timers, intervals, frames, requests, copies, clipboard, shareIcon, notices, scrolls, document, window, flush,
    walletReads: () => walletReads, advance: value => { clock += value; }, respond: value => { response = value; },
    deferred() { let resolve; const promise = new Promise(complete => { resolve = complete; }); pending = { promise, resolve }; return value => { pending = null; resolve(value); }; },
  };
}

test('persistent buttons reuse DOM, respect backend completed=false at thresholds, and never clamp main count', async () => {
  const env = fixture(summary(25)); env.controller.setActive(true); await env.flush();
  const milestones = env.nodes.get('referralMilestones'), initialCards = [...milestones.children];
  assert.equal(env.nodes.get('referralCount').textContent, '25');
  assert(initialCards.every(card => card.tagName === 'button' && !card.classList.contains('is-complete')));
  assert.equal(env.nodes.get('referralShare').disabled, true);
  env.controller.setActive(false); env.controller.setActive(true); await env.flush();
  assert.equal(milestones.replacements, 1); assert.equal(env.requests.length, 1);
  assert(initialCards.every((card, index) => milestones.children[index] === card));
  assert.equal(env.intervals.size, 1);
});

test('only newly confirmed backend rewards animate; cards open informational progress and release scroll lock', async () => {
  const env = fixture(summary(3)); env.controller.setActive(true); await env.flush();
  const milestones = env.nodes.get('referralMilestones'), card = milestones.children[0];
  await milestones.emit('click', { target: card });
  assert.equal(env.dialog.open, true); assert.match(env.nodes.get('referralRewardDescription').textContent, /Ожидаем подтверждения/);
  assert.equal(env.document.body.style.position, 'fixed'); assert.equal(env.root.inert, true);
  await env.dialog.emit('close'); // A queued close from the prior opening must not unlock a newly open dialog.
  assert.equal(env.document.body.style.position, 'fixed'); assert.equal(env.root.inert, true);
  env.controller.setActive(false);
  assert.equal(env.dialog.open, false); assert.equal(env.document.body.style.position, ''); assert.equal(env.root.inert, false);
  env.respond(summary(3, [true, false, false])); env.advance(16000); env.controller.setActive(true); await env.flush();
  assert.equal(card.classList.contains('is-complete'), true); assert.equal(card.classList.contains('is-newly-complete'), true);
  assert.equal(milestones.children[0], card); assert.equal(env.walletReads(), 2);
  await milestones.emit('click', { target: card }); assert.match(env.nodes.get('referralRewardDescription').textContent, /10 AF уже начислены/);
  assert.equal(env.controller.dismiss(), true);
  [...env.timers.values()].forEach(callback => callback());
  assert.equal(env.dialog.open, false); assert.equal(env.controller.dismiss(), false);
  assert(env.requests.every(([endpoint]) => endpoint === '/referrals'));
});

test('single flight and cache prevent duplicate requests; hidden response never opens UI and wallet refreshes on return', async () => {
  const env = fixture(); const resolve = env.deferred();
  env.controller.setActive(true); env.controller.setActive(false); env.controller.setActive(true); env.controller.setActive(false);
  assert.equal(env.requests.length, 1); assert.equal(env.intervals.size, 0);
  resolve(summary(8, [true, false, false])); await env.flush();
  assert.equal(env.nodes.get('referralMilestones').children.length, 0); assert.equal(env.walletReads(), 0);
  env.controller.setActive(true); await env.flush();
  assert.equal(env.nodes.get('referralCount').textContent, '8'); assert.equal(env.requests.length, 1); assert.equal(env.walletReads(), 1);
  assert.equal(env.intervals.size, 1);
});

test('initial completed cards and reduced motion do not run completion animations', async () => {
  const env = fixture(summary(3, [true, false, false]), { reducedMotion: true }); env.controller.setActive(true); await env.flush();
  const cards = env.nodes.get('referralMilestones').children;
  assert.equal(cards[0].classList.contains('is-complete'), true); assert.equal(cards[0].classList.contains('is-newly-complete'), false);
  env.respond(summary(10, [true, true, false]));
  for (const callback of env.intervals.values()) callback(); await env.flush();
  assert.equal(cards[1].classList.contains('is-complete'), true); assert.equal(cards[1].classList.contains('is-newly-complete'), false);
});

test('sharing uses one native prepared message, preserves icon children and treats cancelled callback as cancellation', async () => {
  const env = fixture(); const shared = [];
  env.window.Telegram = { WebApp: { isVersionAtLeast: () => true, shareMessage(id, callback) { shared.push(id); env.callback = callback; } } };
  env.controller.setActive(true); await env.flush();
  void env.nodes.get('referralShare').emit('click'); void env.nodes.get('referralShare').emit('click'); await env.flush();
  assert.equal(env.requests.filter(([endpoint]) => endpoint === '/referrals/share-message').length, 1); assert.deepEqual(shared, ['prepared']);
  assert.equal(env.nodes.get('referralShare').disabled, true); assert(env.nodes.get('referralShare').children.includes(env.shareIcon));
  env.callback(false); await env.flush(); assert.equal(env.nodes.get('referralShare').disabled, false); assert.deepEqual(env.notices, []);
});

test('same-count polling refreshes server wallet for commissions while cached reopens do not', async () => {
  const env = fixture(); env.controller.setActive(true); await env.flush();
  assert.equal(env.walletReads(), 1);
  for (const callback of env.intervals.values()) callback(); await env.flush();
  assert.equal(env.walletReads(), 2); assert.equal(env.requests.length, 2);
  env.controller.setActive(false); env.controller.setActive(true); await env.flush();
  assert.equal(env.walletReads(), 2); assert.equal(env.requests.length, 2);
});

test('a new failed copy removes the previous success check without a false-success notice', async () => {
  const env = fixture(); env.controller.setActive(true); await env.flush();
  await env.copies[0].emit('click');
  assert(env.copies.every(node => node.classList.contains('is-copied')));
  env.clipboard.writeText = async () => { throw Error('clipboard denied'); };
  await env.copies[0].emit('click');
  assert(env.copies.every(node => !node.classList.contains('is-copied')));
  assert.match(env.notices.at(-1), /Не удалось скопировать/);
});

test('reward dialog shows existing Telegram BackButton and first-open decoration never repeats', async () => {
  const env = fixture(), calls = [];
  env.window.Telegram = { WebApp: { BackButton: { show() { calls.push('show'); }, hide() { calls.push('hide'); } } } };
  env.controller.setActive(true); await env.flush(); assert(env.root.classList.contains('is-first-open'));
  await env.nodes.get('referralMilestones').emit('click', { target: env.nodes.get('referralMilestones').children[0] });
  assert.deepEqual(calls, ['show']);
  env.controller.setActive(false); assert.deepEqual(calls, ['show', 'hide']);
  assert.equal(env.root.classList.contains('is-first-open'), false);
  env.controller.setActive(true); await env.flush();
  assert.equal(env.root.classList.contains('is-first-open'), false);
});

test('captured wheel cannot queue background scroll from body/backdrop; long modal stays scrollable', async () => {
  const env = fixture(summary(), { reducedMotion: true }); env.controller.setActive(true); await env.flush();
  await env.nodes.get('referralMilestones').emit('click', { target: env.nodes.get('referralMilestones').children[0] });
  Object.assign(env.dialog, { scrollHeight: 300, clientHeight: 300, scrollTop: 0 });
  let prevented = false;
  const wheel = async (x = 150, target = env.dialog, ctrlKey = false) => {
    for (const handler of env.document.listeners.get('wheel')) handler({ target, clientX: x, clientY: 150, deltaY: 200, ctrlKey, preventDefault() { prevented = true; } });
  };
  await wheel(); assert.equal(prevented, true);
  Object.assign(env.dialog, { scrollHeight: 600, clientHeight: 300, scrollTop: 100 });
  prevented = false; await wheel(); assert.equal(prevented, false, 'scrollable content can still be read');
  env.dialog.scrollTop = 300; prevented = false; await wheel(); assert.equal(prevented, true);
  env.dialog.scrollTop = 100; prevented = false; await wheel(3); assert.equal(prevented, true, 'backdrop never scrolls content or background');
  prevented = false; await wheel(150, env.document.body); assert.equal(prevented, true, 'native backdrop retargeted to body is blocked before default scrolling');
  prevented = false; await wheel(150, env.document.body, true); assert.equal(prevented, false, 'pinch/Control-wheel zoom remains accessible');
  env.controller.setActive(false); prevented = false; await wheel(150, env.document.body); assert.equal(prevented, false, 'outside the reward modal normal page scrolling is untouched');
});

test('touch guard blocks only outside single-finger gestures while modal is open, preserving pinch zoom', async () => {
  const env = fixture(summary(), { reducedMotion: true }); env.controller.setActive(true); await env.flush();
  await env.nodes.get('referralMilestones').emit('click', { target: env.nodes.get('referralMilestones').children[0] });
  let prevented = false;
  const move = (target, count, x = 150) => { prevented = false; for (const handler of env.document.listeners.get('touchmove')) handler({ target, touches: Array(count).fill({ clientX: x, clientY: 150 }), preventDefault() { prevented = true; } }); return prevented; };
  assert.equal(move(env.document.body, 1), true); assert.equal(move(env.document.body, 2), false);
  assert.equal(move(env.dialog, 1), false);
  assert.equal(move(env.dialog, 1, 3), true, 'a native backdrop touch retargeted to dialog is still outside its rectangle');
  env.controller.setActive(false); assert.equal(move(env.document.body, 1), false);
});
