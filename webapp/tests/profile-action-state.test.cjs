const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const app = fs.readFileSync(path.join(root, 'js/app.js'), 'utf8');

function setup() {
  const buttons = Array.from({ length: 6 }, () => {
    const classes = new Set();
    return { attributes: {}, classList: { toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); }, contains: name => classes.has(name) }, setAttribute(name, value) { this.attributes[name] = value; } };
  });
  const document = { querySelectorAll(selector) { assert.match(selector, /profile-main-actions/); return buttons; } };
  const start = app.indexOf('  function selectProfileAction('), end = app.indexOf('  function switchProfileTab(', start);
  assert(start >= 0 && end > start, 'profile action state is handled by a small existing-navigation helper');
  const select = vm.runInNewContext(`(${app.slice(start, end).trim()})`, { document });
  return { buttons, select };
}

test('profile menu has no permanently selected or golden My Listings/Withdraw markup', () => {
  const menu = html.match(/<div class="profile-actions profile-main-actions"[\s\S]*?<\/div>/)?.[0];
  assert(menu); assert.doesNotMatch(menu, /profile-action--gold|class="[^"]*\bis-active\b/);
  assert.match(menu, /data-profile-tab="listings"/); assert.match(menu, /data-open-withdraw/);
});

test('clicking a profile action selects exactly that action and updates accessibility state immediately', () => {
  const { buttons, select } = setup();
  select(buttons[1]);
  assert.deepEqual(buttons.map(button => button.classList.contains('is-active')), [false, true, false, false, false, false]);
  assert.deepEqual(buttons.map(button => button.attributes['aria-pressed']), ['false', 'true', 'false', 'false', 'false', 'false']);
});

test('switching profile action clears the previous highlight instead of accumulating active buttons', () => {
  const { buttons, select } = setup();
  select(buttons[2]); select(buttons[3]); select(buttons[0]);
  assert.deepEqual(buttons.map(button => button.classList.contains('is-active')), [true, false, false, false, false, false]);
  assert.equal(buttons.filter(button => button.attributes['aria-pressed'] === 'true').length, 1);
});

test('implicit entry or leaving the profile clears all selection without a default gold action', () => {
  const { buttons, select } = setup();
  select(buttons[2]); select();
  assert(buttons.every(button => !button.classList.contains('is-active')));
  assert(buttons.every(button => button.attributes['aria-pressed'] === 'false'));
  select(); assert(buttons.every(button => !button.classList.contains('is-active')));
});
