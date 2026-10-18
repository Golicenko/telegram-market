const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'js/app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

function setup() {
  const controls = ['marketGameFilter', 'uniqueGameFilter', 'brandFilter', 'priceMinFilter', 'priceMaxFilter', 'powerFilter', 'speedFilter'];
  const elements = Object.fromEntries(controls.map(key => [key, { value: '', setAttribute(name, value) { this[name] = value; } }]));
  const base = { brand: 'BMW', power_hp: 500, max_speed_kph: 350, price_af_coins: 100 };
  const state = {
    regular: [
      { ...base, id: 'cp2-vip', game_version: 'car_parking_2', pinned: true },
      { ...base, id: 'cp1', game_version: 'car_parking_1' },
      { ...base, id: 'cp2', game_version: 'car_parking_2', price_af_coins: 50 },
      { ...base, id: 'unknown', game_version: null },
      { ...base, id: 'cp2-audi', game_version: 'car_parking_2', brand: 'Audi', price_af_coins: 150, power_hp: 300 },
    ],
    unique: [
      { ...base, id: 'unique-cp2', game_version: 'car_parking_2', pinned: true },
      { ...base, id: 'unique-cp1', game_version: 'car_parking_1' },
      { ...base, id: 'unique-unknown', game_version: 'unrecognized' },
    ],
  };
  const context = { elements, state, renders: 0, renderListings() { this.renders++; } };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function getFilteredRegular()'), source.indexOf('function listingGameLabel(')), context);
  vm.runInContext(source.slice(source.indexOf('function resetFilters()'), source.indexOf('function renderProfile()')), context);
  return context;
}

const ids = items => Array.from(items, item => item.id);

test('default КП includes both games and unknown legacy values without reordering VIP', () => {
  const context = setup();
  assert.deepEqual(ids(context.getFilteredRegular()), ids(context.state.regular));
  assert.deepEqual(ids(context.getFilteredUnique()), ids(context.state.unique));
});

test('each section filters the exact game_version and preserves its own selection', () => {
  const context = setup();
  context.elements.marketGameFilter.value = 'car_parking_1';
  context.elements.uniqueGameFilter.value = 'car_parking_2';
  assert.deepEqual(ids(context.getFilteredRegular()), ['cp1']);
  assert.deepEqual(ids(context.getFilteredUnique()), ['unique-cp2']);
  context.elements.marketGameFilter.value = 'car_parking_2';
  assert.deepEqual(ids(context.getFilteredRegular()), ['cp2-vip', 'cp2', 'cp2-audi']);
  assert.equal(context.elements.uniqueGameFilter.value, 'car_parking_2');
  context.elements.uniqueGameFilter.value = 'car_parking_1';
  assert.deepEqual(ids(context.getFilteredUnique()), ['unique-cp1']);
  assert.equal(context.elements.marketGameFilter.value, 'car_parking_2');
});

test('game filtering combines brand, inclusive price range, power and speed', () => {
  const context = setup();
  Object.assign(context.elements.marketGameFilter, { value: 'car_parking_2' });
  context.elements.brandFilter.value = 'BMW';
  context.elements.priceMinFilter.value = '50';
  context.elements.priceMaxFilter.value = '100';
  context.elements.powerFilter.value = '500';
  context.elements.speedFilter.value = '350';
  assert.deepEqual(ids(context.getFilteredRegular()), ['cp2-vip', 'cp2']);
  context.elements.priceMinFilter.value = '51';
  assert.deepEqual(ids(context.getFilteredRegular()), ['cp2-vip']);
  assert.equal(context.elements.marketGameFilter.value, 'car_parking_2');
});

test('reset restores Market to КП and clears existing filters without touching Unique', () => {
  const context = setup();
  for (const control of Object.values(context.elements)) control.value = '100';
  context.elements.uniqueGameFilter.value = 'car_parking_2';
  context.resetFilters();
  for (const [name, control] of Object.entries(context.elements)) {
    assert.equal(control.value, name === 'uniqueGameFilter' ? 'car_parking_2' : '');
  }
  assert.deepEqual(ids(context.getFilteredRegular()), ids(context.state.regular));
});

test('catalog refresh retains both chosen games and empty results are finite arrays', () => {
  const context = setup();
  context.elements.marketGameFilter.value = 'car_parking_1';
  context.elements.uniqueGameFilter.value = 'car_parking_2';
  context.state.regular = context.state.regular.filter(item => item.id !== 'cp1');
  context.state.unique = [];
  assert.deepEqual(ids(context.getFilteredRegular()), []);
  assert.deepEqual(ids(context.getFilteredUnique()), []);
  assert.equal(context.elements.marketGameFilter.value, 'car_parking_1');
  assert.equal(context.elements.uniqueGameFilter.value, 'car_parking_2');
});

test('each compact dropdown has КП, КП 1, КП 2; Market places it before brand', () => {
  for (const id of ['marketGameFilter', 'uniqueGameFilter']) {
    const select = html.match(new RegExp(`<select id="${id}"[^>]*>([\\s\\S]*?)</select>`))?.[1];
    assert(select);
    assert.deepEqual(Array.from(select.matchAll(/<option value="([^"]*)">([^<]*)<\/option>/g), match => [match[1], match[2]]), [
      ['', 'КП'], ['car_parking_1', 'КП 1'], ['car_parking_2', 'КП 2'],
    ]);
  }
  assert(html.indexOf('id="marketGameFilter"') < html.indexOf('id="brandFilter"'));
});

test('brand remains selected after last matching listing leaves catalog; same options keep DOM', () => {
  const context = setup();
  context.Option = function Option(text, value) { return { text, value }; };
  vm.runInContext(source.slice(source.indexOf('function setSelectOptions('), source.indexOf('function toggleExtraFilters(')), context);
  const select = {
    value: 'BMW', options: [], replacements: 0,
    replaceChildren(...options) { this.options = options; this.value = ''; this.replacements++; },
  };
  context.setSelectOptions(select, 'Автомобиль', ['Audi']);
  assert.equal(select.value, 'BMW');
  assert.deepEqual(Array.from(select.options, option => option.value), ['', 'BMW', 'Audi']);
  context.setSelectOptions(select, 'Автомобиль', ['Audi']);
  assert.equal(select.replacements, 1);
  select.value = '';
  context.setSelectOptions(select, 'Автомобиль', ['Audi']);
  assert.deepEqual(Array.from(select.options, option => option.value), ['', 'Audi']);
});

test('delayed mobile price focus uses captured input after DOM event currentTarget is cleared', () => {
  let callback, scrolls = 0;
  const control = { isConnected: true, scrollIntoView() { scrolls++; } };
  const context = { document: { body: { classList: { add() {} } }, activeElement: control }, window: { setTimeout(handler) { callback = handler; } } };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function beginPriceFilterInput('), source.indexOf('function endPriceFilterInput(')), context);
  const event = { currentTarget: control };
  context.beginPriceFilterInput(event);
  event.currentTarget = null; // Browser clears this after its dispatch finishes.
  callback();
  assert.equal(scrolls, 1);
  context.beginPriceFilterInput({ currentTarget: control });
  context.document.activeElement = null;
  callback();
  assert.equal(scrolls, 1, 'moving to another field/section must not scroll the old input');
});
