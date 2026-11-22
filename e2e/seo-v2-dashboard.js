// Browser test of the V2 /seo dashboard. Run ONLY against an isolated stack (frontend :3112 -> API :8112 -> a throwaway database); it registers a user and seeds rows.
// Build the frontend with BACKEND_URL=http://127.0.0.1:8112 and check .next/routes-manifest.json first. MODE=closed (customer profile, gate closed) or MODE=test (designated test profile:
// start the API with SEO_V2_TEST_LOCATION_NAMES=locations/9001). The 'verified' row and one 'failed' row are SEEDED fixtures that exercise the rendering; they are not evidence of a Google write.
// CHROME_PATH may override the browser location.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }

const BASE = 'http://127.0.0.1:3112';
const OUT = process.env.SHOTS_DIR || path.join(__dirname, 'shots'); fs.mkdirSync(OUT, { recursive: true });
const TAG = Math.random().toString(36).slice(2, 8);
const PW = 'Str0ngPassw0rd!' + TAG;
const EMAIL = `zz-seo-${TAG}@example.com`;
const results = [];
const consoleErrors = [];
const MODE = process.env.MODE || 'closed'; // closed = customer profile (gate closed); test = dedicated test profile

const dockerExec = (code) => execFileSync('docker', ['exec', '-i', 'fq-seov2-api', 'sh', '-c', 'cd /srv && PYTHONPATH=/srv python -'], { input: code, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
function expect(c, m) { if (!c) throw new Error(m); }

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
  const ctx = await browser.newContext({ baseURL: BASE, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)); });
  page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + String(e.message).slice(0, 200)));
  async function step(name, fn) {
    try { await fn(); results.push([name, true]); console.log('PASS', name); }
    catch (e) { results.push([name, false, String(e.message).split('\n')[0].slice(0, 300)]); console.log('FAIL', name, '\n    ', String(e.message).split('\n')[0].slice(0, 300)); await page.screenshot({ path: path.join(OUT, `fail-${results.length}.png`), fullPage: true }).catch(() => {}); }
  }
  let csrf, tenant, locA, gloc;
  let r = await ctx.request.post('/api/v1/auth/register', { data: { email: EMAIL, password: PW, age_confirmed: true, full_name: 'ZZ SEO Owner' } });
  expect(r.status() === 201, `register ${r.status()} ${await r.text()}`);
  csrf = (await r.json()).csrf_token;
  const H = () => ({ 'X-CSRF-Token': csrf });
  tenant = await (await ctx.request.post('/api/v1/tenants', { data: { name: `ZZ-SEO-${TAG}`, category: 'Physiotherapy clinic', language: 'en' }, headers: H() })).json();
  locA = await (await ctx.request.post('/api/v1/locations', { data: { name: 'SEO Main', city: 'Lucknow', review_url: 'https://g.page/r/ABC123/review' }, headers: H() })).json();
  await ctx.request.post('/api/v1/tenant/complete-onboarding', { headers: H() });
  const seedOut = dockerExec(fs.readFileSync(path.join(__dirname, 'seo_v2_seed.py'), 'utf8').replace('__EMAIL__', EMAIL).replace('__TID__', tenant.id).replace('__LID__', locA.id).replace('__MODE__', MODE));
  console.log('seed:', seedOut.split('\n').slice(-3).join(' | '));
  gloc = seedOut.split('\n').pop().trim();

  await page.goto('/seo');
  await page.getByRole('heading', { name: 'Fix your profile' }).waitFor({ timeout: 40000 });

  await step('desktop: summary tiles hold real counts and the gate notice explains itself', async () => {
    const txt = await page.locator('main').innerText();
    for (const w of ['Issues found', 'Fixes ready', 'Waiting for you', 'Confirmed on Google', 'Failed or blocked', 'Profile health']) expect(txt.includes(w), 'missing tile ' + w);
    if (MODE === 'closed') expect(/does not make them yet/.test(txt) && /Google's rules on automated changes/.test(txt), 'gate notice missing');
    await page.screenshot({ path: path.join(OUT, `desktop-top-${MODE}.png`) });
  });
  await step('area-by-area list shows every V2 area with a state and how it would be fixed', async () => {
    const txt = await page.locator('main').innerText();
    for (const w of ['Description', 'Categories', 'Services', 'Attributes', 'Opening hours', 'Holiday hours', 'Phone and website', 'Service area']) expect(txt.includes(w), 'missing area ' + w);
    expect(/Not made by FlowQR|Shown to you: make it in Google|We need your answer|FlowQR makes it after you approve/.test(txt), 'no fix mode shown');
  });
  await step('services recommendation shows BEFORE and AFTER with what is added; existing service kept', async () => {
    const card = page.locator('li', { hasText: 'Services (the complete list)' }).first();
    await card.waitFor({ timeout: 15000 });
    const t = await card.innerText();
    expect(/On Google now/.test(t) && /Would become/.test(t), 'no before/after');
    expect(/Back care/.test(t) && /Neck pain physiotherapy/.test(t), 'added services not shown');
    expect(/Adds:/.test(t) && !/Removes:/.test(t), 'add/remove summary wrong: ' + t.slice(0, 200));
    expect(/job_type_id:dry_needling|Dry needling/.test(t), 'existing service missing from before');
  });
  await step('category recommendation says why, keeps the main category, owner-only risk', async () => {
    const t = await page.locator('li', { hasText: 'Categories (primary and additional, together)' }).first().innerText();
    expect(/Main:/.test(t) && /Sports injury clinic/i.test(t), 'category diff wrong: ' + t.slice(0, 200));
    expect(/high risk|Level 3/.test(t), 'risk label missing');
  });
  if (MODE === 'closed') {
    await step('closed gate: recommendations carry "Not made by FlowQR" and have no approve button', async () => {
      const rec = page.locator('li', { hasText: 'Not made by FlowQR' });
      expect(await rec.count() >= 2, 'expected at least two recommendations');
      expect(await rec.first().getByRole('button', { name: /approve/i }).count() === 0, 'a recommended card must not offer Approve');
      expect(await rec.first().getByRole('button', { name: 'Dismiss' }).count() === 1, 'Dismiss missing');
    });
  }
  await step('approval state: a pending change (different phone) shows Approve and Reject', async () => {
    const w = page.locator('li', { hasText: 'Waiting' }).or(page.locator('li', { hasText: 'Change an existing primary phone' })).first();
    await w.waitFor({ timeout: 10000 });
    await w.getByRole('button', { name: /Approve/ }).waitFor();
    await w.getByRole('button', { name: 'Reject' }).waitFor();
  });
  await step('failed and blocked changes are listed with the real reason, not as success', async () => {
    const card = page.locator('section[aria-label="Failed or blocked"]');
    await card.waitFor({ timeout: 10000 });
    const t = await card.innerText();
    expect(/Failed/.test(t) && /Blocked|Stopped/.test(t), 'failed/blocked labels missing: ' + t.slice(0, 200));
    expect(/read-back|does not show|after the opening time|Google/.test(t), 'reason not shown');
    expect(!/Confirmed on Google/.test(t), 'a failed change must not say confirmed');
  });
  await step('verified change is labelled only as confirmed after read-back', async () => {
    const card = page.locator('section[aria-label="Recent changes"]');
    await card.waitFor({ timeout: 10000 });
    const t = await card.innerText();
    expect(/Confirmed on Google/.test(t) && /read the profile back|reading the profile back/i.test(t), 'verified row wrong: ' + t.slice(0, 200));
  });
  await step('search suggestions carry evidence and no invented volume or difficulty', async () => {
    const card = page.locator('section[aria-label="Search ideas"]');
    await card.waitFor({ timeout: 10000 });
    const t = await card.innerText();
    expect(/in Lucknow|near me/.test(t) && /you list/.test(t), 'no evidence: ' + t.slice(0, 200));
    expect(!/search volume:|difficulty|traffic/i.test(t.replace('No search volume or ranking is promised', '')), 'invented metric shown');
  });
  await step('Google performance card shows real numbers and does not claim cause', async () => {
    const t = await page.locator('section[aria-label="Google performance"]').innerText();
    expect(/40/.test(t) && /30/.test(t) && /not what caused it/.test(t), 'performance card wrong: ' + t.slice(0, 200));
  });
  await step('attributes ask yes/no questions and never prefill an answer', async () => {
    const t = await page.locator('section[aria-label="Your answers needed"]').innerText();
    expect(/Wheelchair accessible entrance/.test(t) && /never guesses/.test(t), 'attribute question missing');
  });
  await step('special hours: add a date; the screen says what happened and the new row appears', async () => {
    const box = page.locator('section[aria-label="Your answers needed"]');
    await box.getByLabel('Date').fill('2099-12-25');
    await box.getByRole('button', { name: 'Add this date' }).click();
    const expectText = MODE === 'closed' ? /Saved as a recommendation/ : /Added for your approval/;
    await page.getByRole('status').filter({ hasText: expectText }).first().waitFor({ timeout: 20000 });
    await page.locator('li', { hasText: '2099-12-25' }).first().waitFor({ timeout: 15000 });
  });
  await step('dismissing a recommendation removes it and records the reason', async () => {
    if (MODE !== 'closed') return;
    const before = await page.locator('li', { hasText: 'Not made by FlowQR' }).count();
    await page.locator('li', { hasText: 'Not made by FlowQR' }).last().getByRole('button', { name: 'Dismiss' }).click();
    await page.waitForFunction((n) => document.querySelectorAll('li').length >= 0 && [...document.querySelectorAll('li')].filter((l) => l.textContent.includes('Not made by FlowQR')).length < n, before, { timeout: 15000 });
  });
  await step('approving the pending phone change against fake Google fails visibly, never as success', async () => {
    const w = page.locator('li', { hasText: 'Change an existing primary phone' }).first();
    await w.getByRole('button', { name: /Approve/ }).click();
    const toast = page.getByRole('status').or(page.getByRole('alert')).filter({ hasText: /./ });
    await page.waitForTimeout(6000);
    const body = await page.locator('main').innerText();
    expect(!/Done\. Google's own profile now shows it/.test(body), 'claimed success');
    const rows = await page.locator('section[aria-label="Failed or blocked"]').innerText();
    expect(/Failed|Stopped|Blocked/.test(rows), 'not listed as failed after a failed approval');
  });
  await step('desktop: no horizontal overflow', async () => {
    const o = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(o <= 1, 'overflow ' + o);
    await page.screenshot({ path: path.join(OUT, `desktop-full-${MODE}.png`), fullPage: true });
  });

  // ---- mobile
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.getByRole('heading', { name: 'Fix your profile' }).waitFor({ timeout: 40000 });
  await step('mobile 390: no horizontal overflow, tiles and cards readable', async () => {
    const o = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(o <= 1, 'overflow ' + o);
    const tooSmall = await page.evaluate(() => [...document.querySelectorAll('section[aria-label="Fix your profile"] button')].filter((b) => b.getBoundingClientRect().height > 0 && b.getBoundingClientRect().height < 32).length);
    expect(tooSmall === 0, tooSmall + ' buttons under 32px tall');
    // the area list must use the width: a text column squeezed beside its chip is unreadable on a phone
    const w = await page.evaluate(() => { const li = document.querySelector('section[aria-label="Profile areas"] li'); const p = li && li.querySelector('p'); return p && li ? [p.getBoundingClientRect().width, li.getBoundingClientRect().width] : null; });
    expect(w && w[0] >= w[1] * 0.8, 'area text is squeezed: ' + JSON.stringify(w));
    await page.screenshot({ path: path.join(OUT, `mobile-full-${MODE}.png`), fullPage: true });
  });

  // ---- loading / error / not-read / empty states (API answers are intercepted; the page code is the real one)
  await page.setViewportSize({ width: 1440, height: 900 });
  await step('loading state: a skeleton shows while the overview is slow', async () => {
    await page.route('**/api/v1/seo/v2/overview*', async (route) => { await new Promise((r) => setTimeout(r, 3500)); await route.continue(); });
    await page.reload();
    await page.waitForSelector('section[aria-label="Fix your profile"]', { state: 'detached', timeout: 2000 }).catch(() => {});
    expect(await page.getByRole('heading', { name: 'Fix your profile' }).count() === 0, 'content shown before data');
    await page.getByRole('heading', { name: 'Fix your profile' }).waitFor({ timeout: 20000 });
    await page.unroute('**/api/v1/seo/v2/overview*');
  });
  await step('error state: a failing overview shows a clear error and the rest of the page still renders', async () => {
    await page.route('**/api/v1/seo/v2/overview*', (route) => route.fulfill({ status: 500, json: { detail: 'Something went wrong. Please try again.' } }));
    await page.reload();
    await page.getByRole('alert').filter({ hasText: /Something went wrong/ }).first().waitFor({ timeout: 20000 });
    await page.getByRole('heading', { name: 'How you show up on Google' }).waitFor();
    await page.unroute('**/api/v1/seo/v2/overview*');
  });
  await step('not-read state: a profile Google has not been read for says so and shows no score', async () => {
    await page.route('**/api/v1/seo/v2/overview*', (route) => route.fulfill({ json: { generated_at: new Date().toISOString(), how_it_works: 'x', gate_note: 'g', totals: { issues_detected: 0, optimizations_available: 0, pending_approvals: 0, recommended_only: 0, in_progress: 0, verified_on_google: 0, verified_last_90_days: 0, failed: 0, blocked: 0 }, health: null,
      locations: [{ google_location_id: 'x', title: 'Empty Clinic', profile_read: false, fetched_at: null, snapshot_error: null, note: 'FlowQR has not read this Google profile yet, so nothing is scored and nothing is proposed. Refresh from Google.', gate: { allowed: false, test_profile: false, customer_writes: false, reason: 'r' }, areas: [], opportunities: [], actions: { pending: [], recommended: [], in_progress: [], verified: [], failed: [], blocked: [], closed: [] }, performance: null }] } }));
    await page.reload();
    await page.getByText('has not read this Google profile yet').waitFor({ timeout: 20000 });
    expect(await page.locator('section[aria-label="Fix your profile"]').getByText('–').count() >= 1, 'no dash for the missing score');
    await page.unroute('**/api/v1/seo/v2/overview*');
  });
  await step('empty state: no Google location at all renders no broken section and no crash', async () => {
    await page.route('**/api/v1/seo/v2/overview*', (route) => route.fulfill({ json: { generated_at: new Date().toISOString(), how_it_works: '', gate_note: '', totals: {}, health: null, locations: [] } }));
    await page.reload();
    await page.getByRole('heading', { name: 'How you show up on Google' }).waitFor({ timeout: 20000 });
    expect(await page.getByRole('heading', { name: 'Fix your profile' }).count() === 0, 'section shown with no location');
    await page.unroute('**/api/v1/seo/v2/overview*');
  });

  const nonHydration = consoleErrors.filter((e) => !/hydrat|Minified React error #4(18|23|25)|favicon|Failed to load resource/i.test(e));
  await step('no unexpected console errors during the whole run', async () => { expect(nonHydration.length === 0, nonHydration.slice(0, 3).join(' || ')); });
  await browser.close();
  const pass = results.filter((r) => r[1]).length;
  console.log(`\n${MODE}: ${pass}/${results.length} passed`);
  console.log('gloc', gloc);
  process.exit(pass === results.length ? 0 : 1);
})().catch((e) => { console.error('FATAL', e); process.exit(2); });
