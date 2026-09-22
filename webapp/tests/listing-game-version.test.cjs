const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../js/app.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const context = vm.createContext({ Date });
for (const name of ['listingGameLabel', 'isListingPinned']) {
  const start = source.indexOf('  function ' + name + '(');
  const end = source.indexOf('\n  }', start) + 4;
  vm.runInContext(source.slice(start, end), context);
}

test('game labels are exact and unknown games are never silently labeled CP1', () => {
  assert.equal(context.listingGameLabel({ game_version: 'car_parking_1' }), 'Car Parking 1');
  assert.equal(context.listingGameLabel({ game_version: 'car_parking_2' }), 'Car Parking 2');
  assert.equal(context.listingGameLabel({}), 'Игра не указана');
  assert.equal(context.listingGameLabel({ game_version: 'car_parking_3' }), 'Игра не указана');
});

test('pin border requires an active backend promotion and a future deadline', () => {
  const now = Date.parse('2026-09-23T10:00:00Z');
  assert(context.isListingPinned({ pinned: true, pinned_until: '2026-09-23T10:00:01Z' }, now));
  for (const listing of [
    { pinned: false, pinned_until: '2026-09-23T10:00:01Z' },
    { pinned: true, pinned_until: '2026-09-23T10:00:00Z' },
    { pinned: true, pinned_until: '2026-09-23T09:59:59Z' },
    { pinned: true, pinned_until: null }, { pinned: true, pinned_until: 'invalid' },
  ]) assert.equal(context.isListingPinned(listing, now), false);
});

test('game is mandatory without a preselection; screenshot policy is beside upload', () => {
  const form = html.match(/<form class="car-form"[\s\S]*?<\/form>/)[0];
  const inputs = form.match(/<input[^>]+name="game_version"[^>]+>/g);
  assert.equal(inputs.length, 2);
  for (const input of inputs) { assert.match(input, /required/); assert.doesNotMatch(input, /checked/); }
  assert(form.indexOf('Выберите игру') < form.indexOf('class="photo-upload"'));
  assert.match(form, /только оригинальный скриншот автомобиля из игры/);
  assert.match(form, /созданные или изменённые нейросетью/);
});
