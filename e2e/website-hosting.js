// A website hosted by FlowQR: REAL BROWSER test of publishing and of the public page inside its sandbox, desktop and phone.
// Google and the AI are doubles (e2e/website-rig/rig_api.py). It proves the screens and the served page, not Google or a real model.
//   BASE_URL=http://localhost:3012 RIG_URL=http://127.0.0.1:18031 CHROME_PATH=<chrome.exe> SHOTS_DIR=./shots node e2e/website-hosting.js
let chromium; try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }
const fs = require('fs');
const BASE = process.env.BASE_URL || 'http://localhost:3012';
const RIG = process.env.RIG_URL || 'http://127.0.0.1:18031';
const SHOTS = process.env.SHOTS_DIR || './e2e/shots-website';
const PW = 'Str0ngPassw0rd!';
const rnd = Math.random().toString(36).slice(2, 7);
fs.mkdirSync(SHOTS, { recursive: true });
let failures = 0, passes = 0;
const check = (name, ok, extra = '') => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  ' + extra : ''}`); ok ? passes++ : failures++; };
const sql = (q, p) => fetch(RIG + '/rig/sql', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ q, p }) }).then((r) => { if (!r.ok) throw new Error('rig sql ' + r.status + ' ' + q.slice(0, 60)); return r.json(); });

(async () => {
  const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});
  const ctx = await browser.newContext({ baseURL: BASE, viewport: { width: 1440, height: 900 } });
  const email = `host-${rnd}@clinic.example`;
  await ctx.request.post('/api/v1/auth/register', { data: { email, password: PW, age_confirmed: true, full_name: 'Gomti Physio' } });
  await sql('UPDATE users SET email_verified_at = now() WHERE email = :e', { e: email });
  let r = await ctx.request.post('/api/v1/auth/login', { data: { email, password: PW } });
  const h = { 'X-CSRF-Token': (await r.json()).csrf_token };
  r = await ctx.request.post('/api/v1/tenants', { data: { name: `Gomti Physio ${rnd}`, category: 'Physiotherapy clinic', language: 'en', phone: '98765 43210' }, headers: h });
  const t = await r.json();
  await ctx.request.post('/api/v1/locations', { data: { name: 'Main branch', city: 'Lucknow', address_line: '2 Viram Khand, Gomti Nagar' }, headers: h });
  await ctx.request.put('/api/v1/agent/knowledge', { data: { description: 'Physiotherapy for back and neck pain in Lucknow.', services: ['Back care', 'Neck pain physiotherapy'], offers: [], faqs: [], prohibited_claims: [] }, headers: h });
  await ctx.request.put('/api/v1/tenant/website-interest', { data: { interest: 'wants_site' }, headers: h });
  await sql('UPDATE tenants SET onboarding_completed = true WHERE id = :t', { t: t.id });
  r = await ctx.request.post('/api/v1/google/connect', { headers: h });
  const state = new URL((await r.json()).auth_url).searchParams.get('state');
  await ctx.request.get('/api/v1/google/callback', { params: { code: 'rig-code', state }, maxRedirects: 0 });
  const conn = (await (await ctx.request.get('/api/v1/google/status')).json()).connections[0].id;
  const gl = (await (await ctx.request.get(`/api/v1/google/connections/${conn}/locations`)).json())[0];
  const mine = await (await ctx.request.get('/api/v1/locations')).json();
  const locId = (mine.locations || mine)[0].id;
  for (const [rating, text, name] of [[5, 'Wonderful care and a calm clinic. My back feels better.', 'Asha Verma'], [4, 'Helpful, patient staff.', 'Rohit Singh'], [2, 'The wait was long on a Monday.', 'Meena K']]) {
    await sql("INSERT INTO reviews (id, tenant_id, location_id, google_location_id, external_id, rating, text, reviewer_name, review_created_at, first_seen_at, google_fetched_at, update_count) VALUES (gen_random_uuid(), :t, :l, :g, :x, :r, :c, :n, now() - interval '3 days', now(), now(), 0)",
      { t: t.id, l: locId, g: gl.id, x: `r-${rnd}-${rating}`, r: rating, c: text, n: name });
  }
  r = await ctx.request.put(`/api/v1/google/connections/${conn}/selection`, { data: { selections: [{ google_location_id: gl.id, selected: true, location_id: locId }] }, headers: h });
  check('choosing the Google location is accepted (the website starts by itself)', r.status() === 200);

  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/website');
  await page.getByRole('heading', { name: 'Your website is ready for review.' }).waitFor({ timeout: 90000 });
  await page.getByRole('list', { name: 'Photos on your website' }).waitFor();
  check('the owner sees the photos copied from Google and can remove them', await page.getByRole('list', { name: 'Photos on your website' }).locator('li').count() === 5);
  await sql("UPDATE sites SET commercial_status = 'complimentary', commercial_reason = 'rig activation' WHERE tenant_id = :t", { t: t.id });
  await page.reload();
  await page.getByRole('button', { name: 'Publish website' }).click({ timeout: 30000 });
  await page.getByText('Your website is published.', { exact: false }).first().waitFor({ timeout: 30000 });
  check('after activation the owner publishes it', true);
  check('publishing prepared the Google profile link for approval', await page.getByRole('link', { name: 'Approve the Google change' }).count() === 1);
  const slug = (await sql('SELECT site_slug FROM sites WHERE tenant_id = :t', { t: t.id })).rows[0][0];

  for (const [name, vp] of [['desktop', { width: 1440, height: 900 }], ['phone', { width: 360, height: 760 }]]) {
    const v = await browser.newContext({ baseURL: BASE, viewport: vp });
    const p = await v.newPage();
    const bad = [];
    p.on('response', (res) => { if (res.status() === 403) console.log('403 from', res.url()); });
    p.on('console', (m) => { if (m.type() === 'error' && !/Report Only|report-only/i.test(m.text())) bad.push(m.text()); });
    const res = await p.goto(`/site/${slug}`);
    check(`${name}: the public website answers 200 with a sandbox policy`, res.status() === 200 && /sandbox/.test(res.headers()['content-security-policy'] || ''), String(res.status()));
    await p.waitForLoadState('networkidle');
    const styled = await p.evaluate(() => getComputedStyle(document.querySelector('.foot')).backgroundColor);
    check(`${name}: the stylesheet loads inside the sandbox`, styled === 'rgb(15, 17, 21)', styled);
    await p.evaluate(async () => { for (const i of document.images) i.loading = 'eager'; window.scrollTo(0, document.body.scrollHeight); await new Promise((r) => setTimeout(r, 800)); window.scrollTo(0, 0); });
    await p.waitForLoadState('networkidle');
    const imgs = await p.evaluate(() => [...document.images].map((i) => i.complete && i.naturalWidth > 0));
    check(`${name}: every photo loads`, imgs.length >= 4 && imgs.every(Boolean), `${imgs.filter(Boolean).length}/${imgs.length}`);
    const body = await p.locator('body').innerText();
    const need = [/3 Google reviews/, /The wait was long/, /Wonderful care/, /Back care/, /Dry needling/, /09:00/, /Viram Khand/, /98765/];
    const missing = need.filter((x) => !x.test(body)).map(String);
    check(`${name}: live reviews of every star level, services, hours, address and phone are on the page`, missing.length === 0, missing.join(' '));
    check(`${name}: no sideways scroll`, await p.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth));
    check(`${name}: the page runs in its own opaque origin (it cannot use FlowQR's)`, await p.evaluate(() => window.origin) === 'null');
    await p.screenshot({ path: `${SHOTS}/public-${name}.png`, fullPage: true });
    if (name === 'desktop') {
      await p.locator('#enquiry input[name="name"]').fill('Ravi Kumar');
      await p.locator('#enquiry input[name="phone"]').fill('9876500000');
      await p.locator('#enquiry textarea[name="message"]').fill('Do you treat knee pain?');
      await p.locator('#enquiry input[name="consent"]').check();
      await p.getByRole('button', { name: 'Send enquiry' }).click();
      await p.waitForURL(/\/thanks/, { timeout: 20000 });
      const n = (await sql('SELECT count(*) FROM site_enquiries WHERE tenant_id = :t', { t: t.id })).rows[0][0];
      check('the enquiry form works inside the sandbox and the enquiry is stored', n === 1, `stored=${n}`);
    }
    check(`${name}: nothing was blocked by the page's policy`, !bad.some((x) => /Content Security Policy|Refused to/.test(x)), bad.slice(0, 2).join(' | ').slice(0, 200));
    await v.close();
  }
  check('no uncaught errors in the app', errors.length === 0, errors.slice(0, 2).join(' | '));
  await browser.close();
  console.log(failures ? `${failures} FAILED, ${passes} passed` : `ALL ${passes} PASSED`);
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR', e.stack || e.message); process.exit(2); });
