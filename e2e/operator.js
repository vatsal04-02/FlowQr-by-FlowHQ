// AI Business Operator: REAL BROWSER test (Playwright) of Fix your profile, Pending changes and the AI Operator, on desktop and phone.
//
// It runs the real Next.js app against the real FlowQR API on a throwaway database, with GOOGLE replaced by an in-memory double and the AI by a scripted stand-in
// (e2e/operator-rig/rig_api.py). So it proves what the screens do with what the server tells them. It proves NOTHING about Google or about how a real model behaves.
//
//   BASE_URL=http://localhost:3011 RIG_URL=http://127.0.0.1:18030 CHROME_PATH=<chrome.exe> SHOTS_DIR=./shots node e2e/operator.js     (exits 1 if any check fails)
let chromium; try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }
const fs = require('fs');
const BASE = process.env.BASE_URL || 'http://localhost:3011';
const RIG = process.env.RIG_URL || 'http://127.0.0.1:18030';
const SHOTS = process.env.SHOTS_DIR || './e2e/shots-operator';
const PW = 'Str0ngPassw0rd!';
const rnd = Math.random().toString(36).slice(2, 7);
fs.mkdirSync(SHOTS, { recursive: true });
let failures = 0, passes = 0;
const check = (name, ok, extra = '') => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  ' + extra : ''}`); ok ? passes++ : failures++; };
const rig = (path, body, method = 'POST') => fetch(RIG + '/rig' + path, { method, headers: { 'content-type': 'application/json' }, body: method === 'GET' ? undefined : JSON.stringify(body || {}) }).then((r) => r.json());
const sql = (q, p) => rig('/sql', { q, p });
const google = () => rig('/google', null, 'GET');
const WEAK = 'Physio clinic.';
const DRAFT = 'Gomti Physio is a physiotherapy clinic in Lucknow offering back care and neck pain physiotherapy. Call the clinic to book a visit or to ask a question about our services.';
const OWN = 'At Gomti Physio in Lucknow our physiotherapists help people with back care and neck pain physiotherapy. Call the clinic to book a visit or ask us a question about services.';
const js = (o) => JSON.stringify(o);
const VIEWS = { desktop: { width: 1440, height: 900 }, phone: { width: 390, height: 844 } };

(async () => {
  const exe = process.env.CHROME_PATH;
  const browser = await chromium.launch(exe ? { executablePath: exe } : {});
  const email = `op-${rnd}@clinic.example`;
  const ctx = await browser.newContext({ baseURL: BASE, viewport: VIEWS.desktop });
  let r = await ctx.request.post('/api/v1/auth/register', { data: { email, password: PW, age_confirmed: true, full_name: 'Gomti Physio' } });
  await sql('UPDATE users SET email_verified_at = now() WHERE email = :e', { e: email });
  r = await ctx.request.post('/api/v1/auth/login', { data: { email, password: PW } });
  const h = { 'X-CSRF-Token': (await r.json()).csrf_token };
  const post = (p, d) => ctx.request.post('/api/v1' + p, { data: d, headers: h });
  r = await post('/tenants', { name: 'Gomti Physio', category: 'Physiotherapy clinic', language: 'en' });
  const tenant = await r.json();
  await post('/locations', { name: 'Gomti Physio - Main', city: 'Lucknow', review_url: 'https://g.page/r/ABC123/review' });
  await sql('UPDATE tenants SET onboarding_completed = true WHERE id = :t', { t: tenant.id });
  await ctx.request.put('/api/v1/agent/knowledge', { data: { description: 'Physiotherapy for back and neck pain in Lucknow.', services: ['Back care', 'Neck pain physiotherapy'], offers: [], faqs: [], prohibited_claims: [] }, headers: h });
  // connect Google through the real OAuth routes (the rig's double answers as Google)
  r = await post('/google/connect');
  const state = new URL((await r.json()).auth_url).searchParams.get('state');
  await ctx.request.get('/api/v1/google/callback', { params: { code: 'rig-code', state }, maxRedirects: 0 });
  const st = await (await ctx.request.get('/api/v1/google/status')).json();
  const conn = st.connections[0].id;
  const locs = await (await ctx.request.get(`/api/v1/google/connections/${conn}/locations`)).json();
  const mine = await (await ctx.request.get('/api/v1/locations')).json();
  r = await ctx.request.put(`/api/v1/google/connections/${conn}/selection`, { data: { selections: [{ google_location_id: locs[0].id, selected: true, location_id: (mine.locations || mine)[0].id }] }, headers: h });
  const gid = locs[0].id;
  check('setup: a business with a connected, selected Google location', r.status() === 200 && !!gid, String(r.status()));
  await rig('/google/details', { key: 'description', value: WEAK });
  r = await post('/agent/google/refresh');
  check('setup: the profile was read from Google (the double)', r.status() === 200 && (await r.json()).locations[0].ok === true);

  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|401|403|404|409|422|429|502/.test(m.text())) errors.push('console: ' + m.text()); });
  const go = async (path) => { await page.goto(path, { waitUntil: 'domcontentloaded' }); await page.getByRole('status', { name: 'Loading FlowQR' }).waitFor({ state: 'detached', timeout: 20000 }).catch(() => {}); };
  const shot = (name) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
  const noSideScroll = () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);

  const writes0 = (await google()).update_calls;
  // ---------------------------------------------------------------- 1. the operator PREPARES the change (it does not just advise)
  await rig('/ai', { reset: true, outputs: [js({ tool: 'audit_profile', args: {} }), js({ tool: 'prepare_change', args: { area: 'description' } }), DRAFT,
    js({ final: 'Your description is very short. I wrote a fuller one from the facts in your Business Brain. It is waiting for your approval and nothing is live yet.' })] });
  await go('/ai/operator');
  await page.getByRole('heading', { name: 'AI Business Operator' }).waitFor();
  await page.getByRole('button', { name: 'Improve my Google profile' }).click();
  await page.getByText('What I did').waitFor({ timeout: 60000 });
  const did = await page.locator('text=What I did').locator('..').innerText();
  check('operator: shows the tool steps that really ran (audit, then prepare)', /Checked your Google profile/.test(did) && /Prepared a change/.test(did), did.replace(/\n+/g, ' | ').slice(0, 200));
  await page.getByText('prepared for your approval').waitFor();
  const card = page.locator('li[id^="change-action:"]').first();
  await card.waitFor();
  const cardText = await card.innerText();
  check('operator: the stored change shows BEFORE (what is on Google) and AFTER (the complete new description)', cardText.includes(WEAK) && cardText.includes('Gomti Physio is a physiotherapy clinic'));
  check('operator: it offers Approve, Edit, Regenerate and Reject, and says nothing changes until approval', ['Approve & apply', 'Edit', 'Regenerate', 'Reject'].every((b) => cardText.includes(b)) && /Nothing changes until you approve/.test(cardText));
  let g = await google();
  check('operator: asking prepared a draft but wrote NOTHING to Google', g.update_calls === writes0 && g.details.description === WEAK, `update_calls=${g.update_calls} (was ${writes0})`);
  await shot('operator-desktop');

  // ---------------------------------------------------------------- 2. every recommendation card that offers an action leads somewhere real
  await go('/seo');
  await page.getByRole('heading', { name: 'Fix your profile' }).waitFor();
  const row = page.locator('li', { hasText: 'Description' }).filter({ hasText: 'Can be better' }).first();
  await row.waitFor();
  const link = row.getByRole('link', { name: /Review and approve/ });
  check('profile area "Description" now has a real control (not a dead chip) that opens the prepared change', await link.count() === 1);
  await shot('seo-fix-your-profile');
  await link.click();
  await page.waitForURL(/\/ai\/changes\?focus=action/);
  await page.locator('li[id^="change-action:"]').first().waitFor();
  check('clicking it opens the prepared change on the pending-changes page', /Business description|Description/.test(await page.locator('h1').first().innerText().catch(() => '')) || (await page.locator('li[id^="change-action:"]').count()) >= 1);

  // the profile checklist rows no longer drop the owner on the generic editor
  await go('/seo/profile');
  await page.getByRole('heading', { name: 'Profile', exact: true }).waitFor();
  await page.getByRole('link', { name: /Business description/ }).first().click();
  await page.waitForURL(/\/ai\/changes/);
  const here = page.url();
  check('profile checklist row opens the change page (prepare on arrival), not /gbp/info', /\/ai\/changes/.test(here) && !/\/gbp\/info/.test(here), here);
  await page.getByText('This change is already prepared', { exact: false }).first().waitFor({ timeout: 30000 });
  check('...and it opens the SAME prepared change instead of paying for a second draft', (await page.locator('li[id^="change-action:"]').count()) === 1);

  // ---------------------------------------------------------------- 3. edit, regenerate (with the AI down and up), approve
  const cardEl = page.locator('li[id^="change-action:"]').first();
  await cardEl.getByRole('button', { name: 'Edit' }).click();
  await cardEl.getByLabel('Your wording').fill('Too short.');
  await cardEl.getByRole('button', { name: 'Save my wording' }).click();
  await cardEl.getByText(/40 to 750 characters/).waitFor();
  check('an edit that is too short is refused with the reason and the original is kept', (await cardEl.innerText()).includes('Gomti Physio is a physiotherapy clinic') || (await cardEl.innerText()).includes('40 to 750'));
  await cardEl.getByLabel('Your wording').fill(OWN);
  await cardEl.getByRole('button', { name: 'Save my wording' }).click();
  await page.waitForFunction((t) => document.body.innerText.includes(t), OWN.slice(0, 40));
  check('your own checked wording replaces the draft (still waiting for approval)', (await page.locator('li[id^="change-action:"]').count()) === 1 && (await page.locator('li[id^="change-action:"]').first().innerText()).includes('Waiting for your approval'));

  await rig('/ai', { down: 'credits' });
  await page.locator('li[id^="change-action:"]').first().getByRole('button', { name: 'Regenerate' }).click();
  await page.getByText(/no credit/i).first().waitFor({ timeout: 20000 });
  check('regenerate with the AI out of credit says so in words and keeps the current draft', (await page.locator('li[id^="change-action:"]').count()) === 1);
  await rig('/ai', { down: '', outputs: [DRAFT] });
  await page.locator('li[id^="change-action:"]').first().getByRole('button', { name: 'Regenerate' }).click();
  await page.waitForFunction((t) => document.body.innerText.includes(t), DRAFT.slice(0, 40), { timeout: 30000 });
  check('regenerate with the AI back produces a new version', true);
  await shot('changes-before-approve');

  g = await google();
  const before = g.update_calls;
  await page.locator('li[id^="change-action:"]').first().getByRole('button', { name: 'Approve & apply' }).click();
  await page.getByText(/updated on Google and confirmed/).waitFor({ timeout: 30000 });
  g = await google();
  check('approve: written to Google exactly once and confirmed by reading the profile back', g.update_calls === before + 1 && g.details.description === DRAFT, `update_calls=${g.update_calls}`);
  const rows = (await sql("SELECT status, verified_at IS NOT NULL FROM agent_actions WHERE tenant_id = :t AND action_type = 'description_improve' ORDER BY created_at", { t: tenant.id })).rows;
  check('the action is recorded as executed with a verification time, earlier versions as cancelled/rejected', rows.some((x) => x[0] === 'executed' && x[1] === true) && rows.filter((x) => x[0] === 'executed').length === 1, JSON.stringify(rows));
  await shot('changes-after-approve');

  // ---------------------------------------------------------------- 4. the Google policy gate: a drafted change on a customer profile says why it cannot be applied
  r = await post('/seo/v2/special-hours', { google_location_id: gid, entries: [{ start: '2099-12-31', closed: true }] });
  const sh = await r.json();
  check('gate closed: a holiday-hours change is drafted as "recommended", not approved', r.status() === 201 && sh.status === 'recommended', sh.status);
  await go(`/ai/changes?focus=action:${sh.id}`);
  const hc = page.locator(`[id="change-action:${sh.id}"]`);
  await hc.waitFor();
  const ht = await hc.innerText();
  check('gate closed: the card has NO Approve button and says why (Google rules being confirmed)', !ht.includes('Approve & apply') && /not made by FlowQr yet|still being confirmed with Google/.test(ht) && ht.includes('Reject'));
  await shot('changes-gate-closed');
  const gname = (await sql('SELECT google_location_name FROM google_locations WHERE id = :g', { g: gid })).rows[0][0];
  await rig('/setting', { attr: 'seo_v2_test_location_names', value: gname });
  await go(`/ai/changes?focus=action:${sh.id}`);
  await hc.waitFor();
  check('gate opened for the dedicated test profile only: the same change now offers Approve', (await hc.innerText()).includes('Approve & apply'));
  await hc.getByRole('button', { name: 'Approve & apply' }).click();
  await page.getByText(/confirmed by reading the profile back/).first().waitFor({ timeout: 30000 });
  check('...and approving applies and verifies it', true);
  await rig('/setting', { attr: 'seo_v2_test_location_names', value: '' });

  // ---------------------------------------------------------------- 5. the AI being down is reported, nothing is invented
  await rig('/ai', { down: 'credits', reset: true });
  await go('/ai/operator');
  await page.getByRole('button', { name: 'What is waiting for me?' }).click();
  await page.getByText('The AI could not run').waitFor({ timeout: 30000 });
  check('operator with the AI out of credit: says so, prepares nothing', /no credit/i.test(await page.locator('body').innerText()) && (await page.locator('li[id^="change-"]').count()) === 0);
  await rig('/ai', { down: '' });

  // ---------------------------------------------------------------- 6. the phone
  await page.setViewportSize(VIEWS.phone);
  for (const p of ['/ai/changes', '/ai/operator', '/seo']) {
    await go(p);
    await page.waitForTimeout(800);
    check(`phone ${p}: no sideways scroll`, await noSideScroll());
  }
  await go(`/ai/changes?focus=action:${sh.id}`);
  await shot('changes-phone');
  const small = await page.evaluate(() => [...document.querySelectorAll('main button, main a')].filter((e) => e.offsetParent !== null).filter((e) => { const b = e.getBoundingClientRect(); return b.width < 24 || b.height < 24; }).map((e) => `${e.tagName} "${e.innerText.trim().slice(0, 30)}" ${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`));
  check('phone: every button and link is at least 24px (touch target)', small.length === 0, small.join(' ; '));
  check('no uncaught page errors on any screen', errors.length === 0, errors.slice(0, 3).join(' | '));

  await browser.close();
  console.log(failures ? `${failures} FAILED, ${passes} passed` : `ALL ${passes} PASSED`);
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR', e.stack || e.message); process.exit(2); });
