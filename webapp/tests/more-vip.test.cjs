const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const { timeLeft } = require('../js/more.js');
test('VIP countdown clamps past expiry and shows server duration without phone wall clock', () => {
  assert.equal(timeLeft(29 * 86400 + 23 * 3600 + 45 * 60), '29 дн. 23 ч. 45 мин.');
  assert.equal(timeLeft(-100), '0 дн. 0 ч. 0 мин.'); assert.equal(timeLeft(null), '0 дн. 0 ч. 0 мин.');
});
test('More menu preserves exactly four entries and separate referral DOM without raster VIP cards', () => {
  const html = fs.readFileSync(path.resolve(__dirname, '../index.html'), 'utf8');
  const menu = html.match(/<section class="view more-menu"[\s\S]*?<\/section>/)[0];
  assert.equal((menu.match(/<button /g) || []).length, 4);
  assert(!menu.includes('data-balance')); assert(!menu.includes('referralContent'));
  assert(html.includes('data-view="referrals"')); assert(html.includes('data-view="seller-vip"')); assert(html.includes('data-view="about"'));
  const source = fs.readFileSync(path.resolve(__dirname, '../js/more.js'), 'utf8');
  assert(!/users\s*:\s*3000/.test(source)); assert(!/completed_deals\s*:\s*1500/.test(source)); assert(!source.includes('реф.jpg'));
  assert(source.includes('quote_fingerprint: retryKey.fingerprint'));
  assert(source.includes('performance.now() - activeStarted')); assert(source.includes('JSON.stringify({ id, fingerprint, quote: originalQuote })'));
});
