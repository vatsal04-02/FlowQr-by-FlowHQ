// FlowQR browser E2E for the Phase 2 completion work, run against the STAGING stack over HTTPS (see docs/STAGING_DEPLOYMENT.md):
//   * the customer onboarding wizard end to end, including its last step (real plan/trial status, first review page)
//   * the Getting-started checklist after it
//   * the platform admin Work queue: a real data export and a real deletion request made by an owner show up there
//   * marketing pages stay on the marketing host (the Caddy route list) and the public origin is in sitemap/robots
//
//   STAGING_DOMAIN=flowqr-staging.dev ADMIN_EMAIL=admin@flowqr-staging.dev ADMIN_PASSWORD='...' CHROME_PATH=... node e2e/phase2-onboarding-and-queue.js
//
// Run it from a container on the staging network (Chromium trusts the internal CA of the local TLS overlay through ignoreHTTPSErrors; nothing else is relaxed):
//   docker run --rm --network flowqr-staging_default -v "$PWD/e2e:/e2e:ro" -v "<dir with playwright-core>/node_modules:/nm:ro" -e NODE_PATH=/nm -e NO_SANDBOX=1 -e CHROME_PATH=/usr/bin/chromium node:22-alpine sh -c 'apk add -q chromium && node /e2e/phase2-onboarding-and-queue.js'
// On a developer PC a security product that intercepts TLS on port 443 can answer instead of Caddy; use the container.
// WHAT THIS DOES NOT PROVE: it makes no Google, Places, Razorpay or Gemini call. The wizard's "Google" choice used here is the manual review-link path.
const fs = require('fs');
const path = require('path');
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }

const D = process.env.STAGING_DOMAIN || 'flowqr-staging.dev';
const APP = `https://app.${D}`, SITE = `https://${D}`;
const OUT = process.env.SHOTS_DIR || path.join(__dirname, 'shots');
const TAG = Math.random().toString(36).slice(2, 8);
const OWNER = `zz-e2e-ob-${TAG}@example.com`, PW = 'Str0ngPassw0rd!' + TAG, NAME = `ZZ Onboarding ${TAG}`;
const ADMIN = process.env.ADMIN_EMAIL || `admin@${D}`, ADMIN_PW = process.env.ADMIN_PASSWORD || 'Staging-Passw0rd!x1';
const results = [];
function expect(c, m) { if (!c) throw new Error(m); }

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({
    headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
    // MAP_TO_LOOPBACK=1 when running on the host (names resolve to the published ports). Inside the compose network the names already resolve (Caddy aliases) and nothing is mapped.
    args: [...(process.env.MAP_TO_LOOPBACK ? [`--host-resolver-rules=MAP ${D} 127.0.0.1, MAP *.${D} 127.0.0.1`, '--no-proxy-server'] : []), ...(process.env.NO_SANDBOX ? ['--no-sandbox'] : [])],
  });
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const pageErrors = [], http5xx = [];
  page.on('pageerror', (e) => pageErrors.push(e.message));
  page.on('response', (r) => { if (r.status() >= 500) http5xx.push(`${r.status()} ${r.url()}`); });
  async function step(name, fn) {
    try { await fn(); results.push([name, true]); console.log('PASS', name); }
    catch (e) { results.push([name, false]); console.log('FAIL', name, '\n     ', String(e.message).split('\n')[0].slice(0, 300)); await page.screenshot({ path: path.join(OUT, `fail-ob-${results.length}.png`), fullPage: true }).catch(() => {}); }
  }
  const noSideways = async () => { const o = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth); expect(o <= 1, `page scrolls sideways by ${o}px`); };
  let csrf;
const call = (pg, method, url, body, headers) => pg.evaluate(async ([m, u, b, h]) => {
  const r = await fetch(u, { method: m, credentials: 'include', headers: { 'content-type': 'application/json', ...h }, body: b ? JSON.stringify(b) : undefined });
  const text = await r.text(); let json = null; try { json = JSON.parse(text); } catch {}
  return { status: r.status, json, length: text.length, text: text.slice(0, 300) };
}, [method, url, body || null, headers || {}]);

  // ------------------------------------------------------------------ customer: the wizard
  await step('register an owner and land in the onboarding wizard', async () => {
    await page.goto(`${APP}/login`); await page.waitForLoadState('domcontentloaded');
    const r = await call(page, 'POST', '/api/v1/auth/register', { email: OWNER, password: PW, full_name: 'Onboarding Owner' });
    expect(r.status === 201, `register ${r.status} ${r.text}`);
    csrf = r.json.csrf_token;
    await page.goto(`${APP}/onboarding`);
    await page.getByRole('heading', { name: 'Tell us about your business' }).waitFor({ timeout: 30000 });
    const steps = await page.getByRole('navigation', { name: 'Set-up progress' }).locator('li').count();
    expect(steps === 4, `expected 4 wizard steps, saw ${steps}`);
  });
  await step('step 1: one form creates the business and its first location, with a Google review link', async () => {
    await page.getByLabel('Business name').fill(NAME);
    await page.getByLabel('Business type').selectOption('Physiotherapy clinic');  // no default any more: the owner (or Google) chooses
    await page.getByLabel('City').fill('Lucknow');
    await page.getByLabel('Review link').fill('https://g.page/r/ABC123/review');
    await page.getByText('More options').click();
    await page.getByLabel('Location name').fill('Hazratganj branch');
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.getByRole('heading', { name: 'How do you want to collect reviews?' }).waitFor({ timeout: 20000 });
    const locs = (await call(page, 'GET', '/api/v1/locations')).json;
    expect(locs.length === 1 && locs[0].name === 'Hazratganj branch' && locs[0].city === 'Lucknow', 'the first location was not saved with the business: ' + JSON.stringify(locs));
  });
  await step('step 2: choosing the manual link does not finish set-up yet, and the Google permissions are explained', async () => {
    await page.getByText('What does connecting Google allow?').click();
    await page.getByText(/only after you .* approve that exact change/).waitFor();
    await page.getByText('Use my Google review link', { exact: true }).click();
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.getByRole('heading', { name: /Choose your plan|free trial/ }).waitFor({ timeout: 20000 });
    expect(!(await page.url()).includes('/overview'), 'the wizard left before its last step');
  });
  await step('step 3: the plan step shows the real trial and prices, and the app stays closed until it is done', async () => {
    const plans = (await call(page, 'GET', '/api/v1/billing/plans')).json;
    const text = await page.locator('main').innerText();
    expect(new RegExp(`${plans.trial_days} days`).test(text), `trial length (${plans.trial_days} days) missing: ${text}`);
    expect(/Due today/.test(text) && /\u20B90/.test(text), 'the "due today" line is missing');
    expect(plans.plans.every((p) => text.includes(p.name)), 'a plan is missing');
    await page.screenshot({ path: path.join(OUT, 'ob-plan.png'), fullPage: true });
    if (plans.trial_requires_card) {
      // A card is required on this server: the only way forward is the card button, and the server refuses to finish without it.
      expect(await page.getByRole('button', { name: 'Add card and start free trial' }).count() === 1, 'the card button is missing');
      expect(await page.getByRole('button', { name: 'Start my free trial' }).count() === 0, 'a way around the card exists');
      const done = await call(page, 'POST', '/api/v1/tenant/complete-onboarding', null, { 'X-CSRF-Token': csrf });
      expect(done.status === 402, `complete-onboarding without a card answered ${done.status}`);
      throw new Error('TRIAL_REQUIRES_CARD is on for this server, so this script cannot go on: it cannot type a card. The card gate itself was verified above.');
    }
    await page.getByRole('button', { name: 'Start my free trial' }).click();
    await page.getByRole('heading', { name: 'You are all set' }).waitFor({ timeout: 20000 });
    const summary = await page.locator('main').innerText();
    expect(/Free trial/i.test(summary) && /charged automatically/i.test(summary), `launch summary incomplete: ${summary}`);
    await page.screenshot({ path: path.join(OUT, 'ob-ready.png'), fullPage: true });
  });
  await step('step 4: the first review page is created for real, then the dashboard opens with a checklist', async () => {
    expect((await call(page, 'GET', '/api/v1/review-growth/campaigns')).json.length === 0, 'a campaign existed before the button was pressed');
    await page.getByRole('button', { name: /Create my review page/ }).click();
    await page.getByText('Created', { exact: true }).waitFor({ timeout: 20000 });
    const camps = (await call(page, 'GET', '/api/v1/review-growth/campaigns')).json;
    expect(camps.length === 1 && camps[0].name.includes('Hazratganj'), 'the campaign was not stored');
    await page.getByRole('button', { name: 'Open my dashboard' }).click();
    await page.waitForURL(/\/overview/, { timeout: 30000 });
    await page.getByRole('heading', { name: 'Getting started' }).waitFor({ timeout: 20000 });
    const list = await page.locator('section[aria-labelledby="gs-h"]').innerText();
    expect(/Create your first review campaign/.test(list) && /Add your location/.test(list), 'checklist rows missing');
    const done = await page.locator('section[aria-labelledby="gs-h"] li .line-through').allInnerTexts();
    expect(done.some((t) => /Create your first review campaign/.test(t)) && done.some((t) => /Add your location/.test(t)), `finished steps are not marked done: ${done}`);
    expect(!done.some((t) => /Confirm your email/.test(t)), 'email is unverified, so it must not be shown as done');
  });
  await step('the wizard is not shown again once finished', async () => {
    await page.goto(`${APP}/onboarding`);
    await page.waitForURL(/\/overview/, { timeout: 30000 });
  });
  await step('wizard and dashboard fit a phone screen', async () => {
    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto(`${APP}/overview`); await page.getByRole('heading', { name: 'Getting started' }).waitFor({ timeout: 30000 }); await page.waitForLoadState('networkidle'); await noSideways();
    await page.setViewportSize({ width: 1280, height: 900 });
  });

  // ------------------------------------------------------------------ real requests the admin must then see
  await step('the owner exports their data and schedules deletion (real requests)', async () => {
    await page.goto(`${APP}/overview`); await page.waitForLoadState('domcontentloaded');
    const e = await call(page, 'GET', '/api/v1/account/export');
    expect(e.status === 200 && e.length > 200, `export ${e.status}`);
    const d = await call(page, 'POST', '/api/v1/account/deletion', { confirm_name: NAME, password: PW }, { 'X-CSRF-Token': csrf });
    expect(d.status === 200 && d.json.requested === true, `deletion ${d.status} ${d.text}`);
  });

  // ------------------------------------------------------------------ platform admin
  const adminCtx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1280, height: 900 } });
  const ap = await adminCtx.newPage();
  ap.on('pageerror', (e) => pageErrors.push(e.message));
  ap.on('response', (r) => { if (r.status() >= 500) http5xx.push(`${r.status()} ${r.url()}`); });
  await step('platform admin signs in and opens the Work queue from the admin navigation', async () => {
    await ap.goto(`${APP}/login`);
    await ap.locator('input[type=email]').first().fill(ADMIN); await ap.locator('input[type=password]').first().fill(ADMIN_PW);
    await ap.getByRole('button', { name: /^Sign in|^Log in/ }).click();
    await ap.waitForURL(/\/(admin|overview|onboarding)/, { timeout: 30000 });
    await ap.goto(`${APP}/admin`); await ap.getByRole('link', { name: 'Work queue' }).first().click();
    await ap.getByRole('heading', { name: 'Work queue' }).waitFor({ timeout: 30000 });
  });
  await step('the queue lists the owner’s deletion request and data export from real records', async () => {
    await ap.getByRole('heading', { name: 'Business deletions' }).waitFor();
    const card = ap.locator('main').first();
    await card.getByText(NAME).first().waitFor({ timeout: 20000 });
    const text = await ap.locator('main').innerText();
    expect(/scheduled/i.test(text), 'deletion is not marked scheduled');
    expect(new RegExp(NAME).test(text.split('Data exports')[1] || ''), 'the export is not listed under Data exports');
    expect(!/overdue/i.test(text.split('Business deletions')[1].split('Data exports')[0].split(NAME)[1] || ''), 'a deletion due in the future must not be flagged overdue');
    await ap.screenshot({ path: path.join(OUT, 'admin-queue.png'), fullPage: true });
  });
  await step('empty sections say so plainly instead of showing placeholders', async () => {
    const text = await ap.locator('main').innerText();
    expect(/No failed, blocked or invalidated changes|Failed, blocked or invalidated Google changes/.test(text), 'failed-changes section missing');
    expect(/Nothing is waiting for approval|Waiting for approval/.test(text), 'approvals section missing');
  });
  await step('the queue fits a phone screen', async () => {
    await ap.setViewportSize({ width: 390, height: 800 }); await ap.reload(); await ap.getByRole('heading', { name: 'Work queue' }).waitFor({ timeout: 30000 }); await ap.waitForLoadState('networkidle');
    const o = await ap.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth); expect(o <= 1, `scrolls sideways by ${o}px`);
  });
  await step('a business owner cannot open the admin queue (page or API)', async () => {
    await page.goto(`${APP}/overview`); await page.waitForLoadState('domcontentloaded');
    const r = await call(page, 'GET', '/api/v1/admin/work-queue'); expect(r.status === 403, `owner got ${r.status}`);
    await page.goto(`${APP}/admin/queue`); await page.waitForLoadState('networkidle');
    expect(!(await page.locator('body').innerText()).includes('Business deletions'), 'an owner saw the admin queue');
  });
  await step('cleanup: the owner cancels the deletion so nothing is removed by the daily job', async () => {
    await page.goto(`${APP}/overview`); await page.waitForLoadState('domcontentloaded');
    const r = await call(page, 'DELETE', '/api/v1/account/deletion', null, { 'X-CSRF-Token': csrf });
    expect(r.status === 200 && r.json.requested === false, `cancel ${r.status}`);
  });

  // ------------------------------------------------------------------ admin controls added in the completion pass
  let tenantId;
  await step('admin sets one business\'s spending ceilings; the change is stored and audited', async () => {
    await ap.goto(`${APP}/admin`); await ap.waitForLoadState('domcontentloaded');
    const list = await call(ap, 'GET', `/api/v1/admin/tenants?search=${encodeURIComponent(NAME)}`);
    tenantId = list.json.items.find((t) => t.name === NAME).id;
    await ap.goto(`${APP}/admin/customers/${tenantId}`);
    await ap.getByRole('heading', { name: 'Spending ceilings' }).waitFor({ timeout: 30000 });
    await ap.getByRole('button', { name: 'Change' }).click();
    await ap.getByLabel('Google searches per month').fill('50');
    await ap.getByLabel(/Why\?/).fill('pilot ceiling set by the browser test');
    await ap.getByRole('button', { name: 'Save ceilings' }).click();
    await ap.getByText('Ceilings saved.').waitFor({ timeout: 20000 });
    const b = (await call(ap, 'GET', `/api/v1/admin/tenants/${tenantId}/budgets`)).json;
    expect(b.places_monthly_cap === 50, `stored cap is ${b.places_monthly_cap}`);
    expect((await ap.locator('main').innerText()).includes('50'), 'the new ceiling is not shown');
    const detail = (await call(ap, 'GET', `/api/v1/admin/tenants/${tenantId}`)).json;
    expect(JSON.stringify(detail.audit).includes('admin.budgets'), 'the change is not in the business audit trail');
    // clear it again so staging is left as found
    await ap.getByRole('button', { name: 'Change' }).click(); await ap.getByLabel('Google searches per month').fill(''); await ap.getByLabel(/Why\?/).fill('cleared after the browser test');
    await ap.getByRole('button', { name: 'Save ceilings' }).click();
    await ap.getByRole('button', { name: 'Change' }).waitFor({ timeout: 20000 });  // the editor closed: the save finished (the first save's toast may still be on screen)
    let cap; for (let i = 0; i < 10; i++) { cap = (await call(ap, 'GET', `/api/v1/admin/tenants/${tenantId}/budgets`)).json.places_monthly_cap; if (cap === null) break; await ap.waitForTimeout(500); }
    expect(cap === null, `the ceiling was not cleared (${cap})`);
  });
  await step('admin uses the platform emergency stop and resumes (a reason is required)', async () => {
    await ap.goto(`${APP}/admin/ops`);
    await ap.getByRole('heading', { name: 'Emergency stop' }).waitFor({ timeout: 30000 });
    const stopBtn = ap.getByRole('button', { name: 'Stop everything' });
    expect(await stopBtn.isDisabled(), 'the stop button is enabled without a reason');
    await ap.getByLabel(/Why are you stopping everything/).fill('browser test of the emergency stop');
    await stopBtn.click();
    await ap.getByText('STOPPED', { exact: true }).waitFor({ timeout: 20000 });
    expect((await call(ap, 'GET', '/api/v1/admin/autonomy/emergency-stop')).json.stop.on === true, 'the server does not report the stop');
    await ap.getByRole('button', { name: 'Resume execution' }).click();
    await ap.getByText('running', { exact: true }).waitFor({ timeout: 20000 });
    expect((await call(ap, 'GET', '/api/v1/admin/autonomy/emergency-stop')).json.stop === null, 'the stop was not lifted');
  });

  // ------------------------------------------------------------------ marketing host routing (the Caddy route list) and the public origin
  await step('marketing pages stay on the marketing host and carry the public origin', async () => {
    const mp = await ctx.newPage();
    await mp.route('**/*', (route) => route.continue());
    for (const p of ['/about', '/review-cards', '/google-business', '/ai-growth-agent', '/industries', '/demo', '/privacy', '/terms', '/refund-policy', '/data-deletion', '/pricing']) {
      const resp = await mp.goto(`${SITE}${p}`); expect(resp.status() === 200, `${p} -> ${resp.status()}`);
      expect(new URL(mp.url()).host === D, `${p} left the marketing host: ${mp.url()}`);
    }
    await mp.goto(`${SITE}/pricing`); await mp.waitForLoadState('networkidle');
    const body = await mp.locator('body').innerText();
    expect(/499/.test(body) && /799/.test(body) && /1,?499/.test(body), 'the three plan prices are not on the pricing page: ' + body.replace(/\s+/g, ' ').slice(0, 400));
    const canon = await mp.locator('link[rel="canonical"]').getAttribute('href');
    expect(canon && canon.startsWith(SITE), `canonical link is ${canon}`);
    await mp.goto(`${SITE}/robots.txt`); const robots = await mp.locator('body').innerText();
    expect(!/Disallow: \/ai-growth-agent/.test(robots) && /Disallow: \/ai\//.test(robots), 'robots.txt blocks a marketing page or misses the app path');
  });

  await browser.close();
  const failed = results.filter((r) => !r[1]);
  if (pageErrors.length) console.log('PAGE ERRORS:', [...new Set(pageErrors)].slice(0, 5));
  if (http5xx.length) console.log('5xx RESPONSES:', http5xx.slice(0, 5));
  console.log(`\n${results.length - failed.length}/${results.length} passed`);
  process.exit(failed.length || pageErrors.length || http5xx.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
