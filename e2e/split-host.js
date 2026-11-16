// Browser test of the PRODUCTION TOPOLOGY: the site and the API are on different origins (production: https://flowqr.site -> https://api.flowqr.site; here: http://localhost:3300 -> http://localhost:8100).
// The frontend is built with NEXT_PUBLIC_API_URL pointing at the API and run on its own port; the API is the isolated demo stack with CORS_ORIGINS set to the site's origin.
//   SITE=http://localhost:3300 API=http://localhost:8100 node e2e/split-host.js
// Proves: credentialed CORS, the session and CSRF cookies across origins, cross-origin images, exposed response headers, CSRF enforcement, logout.
// Does NOT prove: Vercel, TLS, a real registrable domain (cookie Domain=.flowqr.site), or anything about Google.
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }
const SITE = process.env.SITE || 'http://localhost:3300', API = process.env.API || 'http://localhost:8100';
const TAG = Math.random().toString(36).slice(2, 8), EMAIL = `zz-split-${TAG}@example.com`, PW = 'Str0ngPassw0rd!' + TAG;
const results = [];
const expect = (c, m) => { if (!c) throw new Error(m); };

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const problems = [];
  page.on('console', (m) => { if (m.type() === 'error' && /CORS|blocked|net::ERR/i.test(m.text())) problems.push(m.text().slice(0, 200)); });
  const apiCalls = [];
  page.on('request', (r) => { if (r.url().includes('/api/v1')) apiCalls.push(r.url()); });
  async function step(name, fn) {
    try { await fn(); results.push([name, true]); console.log('PASS', name); }
    catch (e) { results.push([name, false]); console.log('FAIL', name, '\n     ', String(e.message).split('\n')[0].slice(0, 300)); await page.screenshot({ path: `split-fail-${results.length}.png` }).catch(() => {}); }
  }
  const call = (method, url, body, headers) => page.evaluate(async ([m, u, b, h]) => {
    const r = await fetch(u, { method: m, credentials: 'include', headers: { 'content-type': 'application/json', ...h }, body: b ? JSON.stringify(b) : undefined });
    const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch { /* not JSON */ }
    return { status: r.status, json: j, len: t.length };
  }, [method, url, body || null, headers || {}]);
  let csrf;

  await step('the site loads from its own origin and every API call goes to the API origin', async () => {
    await page.goto(`${SITE}/pricing`); await page.waitForLoadState('networkidle');
    expect(apiCalls.length > 0 && apiCalls.every((u) => u.startsWith(API)), `API calls went to: ${[...new Set(apiCalls)].join(', ')}`);
    const body = await page.locator('body').innerText();
    expect(/499/.test(body) && /799/.test(body), 'the plans did not load across origins: ' + body.replace(/\s+/g, ' ').slice(0, 200));
  });
  await step('sign up through the UI and reach the wizard; the session cookie works across origins', async () => {
    await page.goto(`${SITE}/register`);
    await page.locator('input[type=email]').first().fill(EMAIL);
    for (const el of await page.locator('input[type=password]').all()) await el.fill(PW);
    const name = page.getByLabel(/name/i).first(); if (await name.count()) await name.fill('Split Host');
    for (const cb of await page.getByRole('checkbox').all()) await cb.check();
    await page.getByRole('button', { name: /create|sign up|register|continue/i }).first().click();
    await page.waitForURL(/onboarding|overview/, { timeout: 30000 });
    const me = await call('GET', `${API}/api/v1/auth/me`);
    expect(me.status === 200 && me.json.user.email === EMAIL, `me ${me.status}`); csrf = me.json.csrf_token;
  });
  await step('the business, a location and a review campaign are created across origins (cookie + CSRF header)', async () => {
    let r = await call('POST', `${API}/api/v1/tenants`, { name: `ZZ Split ${TAG}`, category: 'Physiotherapy clinic', language: 'en' }, { 'X-CSRF-Token': csrf }); expect(r.status === 201, `tenant ${r.status}`);
    r = await call('POST', `${API}/api/v1/locations`, { name: 'Main', city: 'Lucknow', review_url: 'https://g.page/r/ABC123/review' }, { 'X-CSRF-Token': csrf }); expect(r.status === 201, `location ${r.status}`);
    const loc = r.json.id;
    r = await call('POST', `${API}/api/v1/review-growth/campaigns`, { name: 'Split campaign', location_id: loc }, { 'X-CSRF-Token': csrf }); expect(r.status === 201, `campaign ${r.status}`);
    await call('POST', `${API}/api/v1/tenant/complete-onboarding`, null, { 'X-CSRF-Token': csrf });
  });
  await step('the campaigns page renders from the other origin and its QR image loads cross-origin with the cookie', async () => {
    await page.goto(`${SITE}/gbp/campaigns`); await page.waitForLoadState('networkidle');
    const img = page.locator('img[src*="/qr.svg"]').first(); await img.waitFor({ timeout: 20000 });
    const src = await img.getAttribute('src'); expect(src.startsWith(API), `the QR image points at ${src}`);
    expect(await img.evaluate((i) => i.complete && i.naturalWidth > 0), 'the QR image did not load');
  });
  await step('a custom response header the frontend reads (X-FlowQR-Scannable on a QR preview) is visible to JavaScript across origins', async () => {
    const r = await page.evaluate(async ([api, csrfToken]) => {
      const st = await (await fetch(api + '/api/v1/qr/style', { credentials: 'include' })).json();
      const res = await fetch(api + '/api/v1/qr/preview.png', { method: 'POST', credentials: 'include', headers: { 'content-type': 'application/json', 'X-CSRF-Token': csrfToken }, body: JSON.stringify(st) });
      return { status: res.status, scannable: res.headers.get('x-flowqr-scannable'), type: res.headers.get('content-type') };
    }, [API, csrf]);
    expect(r.status === 200 && r.type === 'image/png', `preview ${r.status} ${r.type}`);
    expect(r.scannable !== null, 'the browser hid X-FlowQR-Scannable: the response headers are not exposed across origins');
  });
  await step('a mutating call without the CSRF header is refused across origins; with it, it works', async () => {
    const bad = await call('PATCH', `${API}/api/v1/tenant`, { review_goal: 5 }); expect(bad.status === 403, `no csrf -> ${bad.status}`);
    const ok = await call('PATCH', `${API}/api/v1/tenant`, { review_goal: 5 }, { 'X-CSRF-Token': csrf }); expect(ok.status === 200, `csrf -> ${ok.status}`);
  });
  await step('the session cookie is HttpOnly; logout ends the session', async () => {
    const cookies = await ctx.cookies(API);
    expect(cookies.some((c) => c.name === 'flowqr_session' && c.httpOnly), 'the session cookie is not HttpOnly');
    expect(!(await page.evaluate(() => document.cookie)).includes('flowqr_session'), 'JavaScript can read the session cookie');
    const out = await call('POST', `${API}/api/v1/auth/logout`, null, { 'X-CSRF-Token': csrf }); expect(out.status === 204 || out.status === 200, `logout ${out.status}`);
    expect((await call('GET', `${API}/api/v1/auth/me`)).status === 401, 'still signed in after logout');
  });
  await step('no CORS or blocked-request errors appeared in the browser console', async () => { expect(problems.length === 0, problems.join(' | ')); });

  await browser.close();
  const failed = results.filter((r) => !r[1]);
  console.log(`\n${results.length - failed.length}/${results.length} passed`);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
