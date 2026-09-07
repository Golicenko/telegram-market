// Real static frontend, no fake users, balances, Telegram SDK or successful API responses.
// Layout/public navigation only: this is NOT an authenticated Telegram E2E test.
const { chromium } = require("playwright");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "..");
const server = http.createServer((req, res) => {
  const name = new URL(req.url, "http://test").pathname;
  const filename = path.resolve(root, "." + (name === "/" ? "/index.html" : name));
  if (!filename.startsWith(root + path.sep) || !fs.existsSync(filename) || fs.statSync(filename).isDirectory()) { res.writeHead(404); return res.end(); }
  const types={".html":"text/html", ".js":"text/javascript", ".css":"text/css", ".jpg":"image/jpeg", ".png":"image/png", ".json":"application/json"};
  res.setHeader("Content-Type", types[path.extname(filename)] || "application/octet-stream");
  res.end(fs.readFileSync(filename));
});
(async () => {
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({channel:"msedge", headless:true});
  try {
    for (const width of [320,360,390,430]) {
      const page = await browser.newPage({viewport:{width,height:844},isMobile:true,hasTouch:true});
      const errors=[];
      page.on("pageerror", e => errors.push(e.message));
      await page.goto(`http://127.0.0.1:${server.address().port}`);
      await page.waitForTimeout(7000);
      const overflow = async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`);
      for (const view of ["profile","training","more"]) {
        await page.locator(`.bottom-nav [data-nav-target="${view}"]`).click();
        await overflow();
        if (width === 390) await page.screenshot({path:path.join(root,"../docs",`ux-after-${view}.png`),fullPage:true});
      }
      await page.locator('[data-view="more"] [data-open-info]').click();
      assert.equal(await page.locator(".help-article").count(), 11);
      await page.locator('[data-help-anchor="help-support"]').click();
      await page.waitForTimeout(900);
      const anchor = await page.locator("#help-support").boundingBox();
      assert(anchor.y >= 0 && anchor.y < 844, JSON.stringify(anchor));
      await overflow();
      if (width === 390) await page.screenshot({path:path.join(root,"../docs/ux-after-help.png"),fullPage:true});
      await page.locator('.bottom-nav [data-nav-target="profile"]').click();
      assert.equal(await page.locator('[data-view="profile"] [data-profile-tab="training"]').count(), 0);
      assert(await page.locator(".profile-admin").isHidden());
      await page.locator('[data-view="profile"] [data-open-topup]').click();
      assert.equal(await page.locator("[data-topup-amount]").count(), 7);
      for (const amount of [10,15,25,50,75,90,100]) {
        const button=page.locator(`[data-topup-amount="${amount}"]`);
        await button.click();
        assert.equal(await page.locator("#topupAmount").inputValue(), String(amount));
        assert.equal(await button.getAttribute("aria-pressed"),"true");
        assert.equal(await page.locator(".topup-packages .is-selected").count(),1);
        const box=await button.boundingBox(); assert(box.height>=44);
      }
      await page.locator("#topupAmount").fill("55");
      assert.equal(await page.locator(".topup-packages .is-selected").count(),0);
      assert.match(await page.locator("#topupForm .pay-button").textContent(),/55/);
      await overflow();
      if (width===390) await page.screenshot({path:path.join(root,"../docs/ux-after-topup.png"),fullPage:true});
      await page.locator("#topupForm .pay-button").click();
      assert.match(await page.locator("#paymentResult").textContent(), /внутри Telegram/);
      assert.doesNotMatch(await page.locator("#paymentResult").textContent(), /зачислены/);
      assert.deepEqual(errors,[]);
      await page.close();
      console.log(`public navigation/layout ${width}px: OK (no Telegram E2E claim)`);
    }
  } finally { await browser.close(); server.close(); }
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
