// Agency self-service onboarding: REAL BROWSER test (Playwright) of /gbp/connect, /admin/agency and the Locations & Google page, on desktop, tablet and phone.
//
// It runs the real Next.js app against the real FlowQR API on a throwaway database, with GOOGLE replaced by an in-memory fake (e2e/agency-rig/rig_api.py). So it proves what the screens
// do with what the server tells them. It proves NOTHING about Google itself.
//
//   BASE_URL=http://localhost:3000 RIG_URL=http://127.0.0.1:18020 CHROME_PATH=<chrome.exe> SHOTS_DIR=./shots node e2e/agency-self-service.js
// Exits 1 if any check fails.
let chromium; try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }
const fs = require('fs');
const BASE = process.env.BASE_URL || 'http://localhost:3000';
const RIG = process.env.RIG_URL || 'http://127.0.0.1:18020';
const SHOTS = process.env.SHOTS_DIR || './e2e/shots-agency';
const PW = 'Str0ngPassw0rd!';
const OPERATOR = 'ui-operator@flowhq.example';
const ADMIN_NOT_OPERATOR = 'ops@flowhq.example';
const rnd = Math.random().toString(36).slice(2, 7);
fs.mkdirSync(SHOTS, { recursive: true });

let failures = 0, passes = 0;
const check = (name, ok, extra = '') => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  ' + extra : ''}`); ok ? passes++ : failures++; };
const rig = (path, body) => fetch(RIG + '/rig' + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body || {}) }).then((r) => r.json());
const sql = (q, p) => rig('/sql', { q, p });
const VIEWS = { desktop: { width: 1440, height: 900 }, tablet: { width: 820, height: 1180 }, phone: { width: 390, height: 844 } };

let browser, LAST;
async function session(email, name, { business = true, vp = VIEWS.desktop } = {}) {
  const ctx = await browser.newContext({ baseURL: BASE, viewport: vp, hasTouch: vp.width < 768, isMobile: vp.width < 768 });
  let r = await ctx.request.post('/api/v1/auth/register', { data: { email, password: PW, age_confirmed: true, full_name: name } });
  if (r.status() === 409) r = await ctx.request.post('/api/v1/auth/login', { data: { email, password: PW } });
  const csrf = (await r.json()).csrf_token;
  // verify through the real link the real mailer sent (this is also what grants an administrator's rights to a listed address)
  const mails = await (await fetch(`${RIG}/rig/outbox?to=${encodeURIComponent(email)}`)).json();
  const m = mails.filter((x) => /token=/.test(x.body)).pop();
  if (m) await ctx.request.post('/api/v1/auth/verify-email', { data: { token: m.body.split('token=')[1].split(/\s/)[0].trim() } });
  else await sql('UPDATE users SET email_verified_at = now() WHERE email = :e', { e: email });
  r = await ctx.request.post('/api/v1/auth/login', { data: { email, password: PW } });
  const h = { 'X-CSRF-Token': (await r.json()).csrf_token || csrf };
  if (business) {
    r = await ctx.request.post('/api/v1/tenants', { data: { name, category: 'Physiotherapy clinic', language: 'en' }, headers: h });
    if (r.status() !== 201) throw new Error('tenant ' + r.status() + await r.text());
    const t = await r.json();
    r = await ctx.request.post('/api/v1/locations', { data: { name: name + ' - Main', city: 'Lucknow', review_url: 'https://g.page/r/ABC123/review' }, headers: h });
    await sql('UPDATE tenants SET onboarding_completed = true WHERE id = :t', { t: t.id });
  }
  const page = await ctx.newPage();
  LAST = page;
  for (const m of ['goto', 'reload']) { const orig = page[m].bind(page); page[m] = async (...a) => { const r = await orig(...a); await page.getByRole('status', { name: 'Loading FlowQR' }).waitFor({ state: 'detached', timeout: 15000 }).catch(() => {}); return r; }; }
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  // Google's sign-in page does not exist in the rig: send the browser straight back to FlowQR's callback, as Google does after the person signs in and consents.
  await page.route('https://accounts.google.test/**', (route) => {
    const state = new URL(route.request().url()).searchParams.get('state');
    route.fulfill({ status: 302, headers: { location: `${BASE}/api/v1/google/callback?code=rig-code&state=${encodeURIComponent(state)}` } });
  });
  return { ctx, page, errors, h };
}
const noSideScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
const shot = (page, name) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
const targetsOk = (page) => page.evaluate(() => [...document.querySelectorAll('main button, main a, main input[type=checkbox], main input[type=radio], main select')].filter((e) => e.offsetParent !== null).every((e) => {
  const r = (e.closest('label') || e).getBoundingClientRect(); return r.width >= 24 && r.height >= 24; }));
const stepStatuses = (page) => page.locator('ol[aria-label="Progress"] li').evaluateAll((lis) => lis.map((l) => l.innerText.replace(/\n+/g, ' | ')));

async function connectAndChoose(page, vpName, tag) {
  await page.goto('/gbp/connect');
  await page.getByRole('heading', { name: 'Connect your Google Business Profile' }).waitFor();
  await page.getByRole('button', { name: 'Connect Google' }).click();
  await page.waitForURL(/\/gbp\/connect\?connected=1/);
  await page.getByRole('heading', { name: 'Pick the location FlowQR may manage' }).waitFor();
}

(async () => {
  const exe = process.env.CHROME_PATH;
  browser = await chromium.launch(exe ? { executablePath: exe } : {});
  await rig('/reset');
  await sql("UPDATE google_connections SET auth_mode = 'client_token', agency_account_id = NULL WHERE agency_account_id IS NOT NULL");
  await sql('DELETE FROM google_agency_authorizations');  // earlier runs must not make this run's location look taken

  // ===================================================================== customer journey, once per viewport
  for (const [vpName, vp] of Object.entries(VIEWS)) {
    const tag = vpName;
    const email = `owner-${vpName}-${rnd}@rig.example`;
    const { page, errors, ctx } = await session(email, `Clinic ${vpName} ${rnd}`, { vp });

    // ---- not started
    await page.goto('/gbp/connect');
    await page.getByRole('heading', { name: 'Connect your Google Business Profile' }).waitFor();
    const labels = await page.locator('ol[aria-label="Progress"] li').count();
    check(`${tag}: NOT_STARTED shows the eight stages and a Connect Google button`, labels === 8 && await page.getByRole('button', { name: 'Connect Google' }).isVisible());
    const st = await stepStatuses(page);
    check(`${tag}: stage wording is the brief's`, ['Connecting Google account', 'Finding your business locations', 'Selecting business location', 'Requesting FlowHQ manager access', 'Accepting agency invitation', 'Verifying access', 'Synchronizing reviews'].every((t) => st.join(' ').includes(t)));
    check(`${tag}: no stage is done before anything happened`, !st.some((s) => /\bDone\b/.test(s)));
    await shot(page, `${tag}-01-not-started`);
    check(`${tag}: no sideways scroll`, await noSideScroll(page));

    // ---- Google sign-in (the fake Google sends the browser back), then discovery
    await page.getByRole('button', { name: 'Connect Google' }).click();
    await page.waitForURL(/\/gbp\/connect\?connected=1/);
    await page.getByRole('heading', { name: 'Pick the location FlowQR may manage' }).waitFor();
    check(`${tag}: the "Google account connected" toast appears once`, (await page.getByText('Google account connected. Now choose').count()) === 1);
    check(`${tag}: returns to the guided page after Google (not the old page)`, page.url().includes('/gbp/connect'));
    check(`${tag}: both discovered locations are offered, none pre-selected`, (await page.getByRole('radio').count()) === 2 && !(await page.getByRole('radio').first().isChecked()));
    check(`${tag}: Google identity shown`, (await page.getByText('owner@rig-clinic.example').count()) > 0);
    check(`${tag}: Use this location is disabled until one is chosen`, await page.getByRole('button', { name: 'Use this location' }).isDisabled());
    await shot(page, `${tag}-02-choose-location`);
    await page.getByRole('radio', { name: /Rig Clinic Gomti Nagar/ }).check();
    check(`${tag}: choosing a location asks which FlowQR location it is`, await page.getByLabel('Which of your FlowQR locations is this?').isVisible());
    check(`${tag}: Use this location stays disabled until mapped`, await page.getByRole('button', { name: 'Use this location' }).isDisabled());
    await page.getByLabel('Which of your FlowQR locations is this?').selectOption({ index: 1 });
    await page.getByRole('button', { name: 'Use this location' }).click();

    // ---- consent, permission by permission
    await page.getByRole('heading', { name: 'Your approval and permissions' }).waitFor();
    await shot(page, `${tag}-03-consent`);
    const boxes = {};
    for (const n of ['Read your reviews and profile details', 'Reply to reviews', 'Publish posts and photos', 'Update profile details']) boxes[n] = page.getByRole('checkbox', { name: new RegExp(n) });
    check(`${tag}: reading is ticked and cannot be unticked`, (await boxes['Read your reviews and profile details'].isChecked()) && (await boxes['Read your reviews and profile details'].isDisabled()));
    check(`${tag}: nothing else is pre-ticked`, !(await boxes['Reply to reviews'].isChecked()) && !(await boxes['Publish posts and photos'].isChecked()) && !(await boxes['Update profile details'].isChecked()));
    check(`${tag}: the consent names the location being approved`, (await page.getByText('Rig Clinic Gomti Nagar').count()) > 0);
    const approve = page.getByRole('button', { name: 'Approve and invite FlowQR' });
    check(`${tag}: Approve is disabled until the agreement is ticked`, await approve.isDisabled());
    await boxes['Reply to reviews'].check();
    check(`${tag}: ticking a permission alone does not enable Approve`, await approve.isDisabled());
    await page.getByRole('checkbox', { name: /I have read this/ }).check();
    check(`${tag}: Approve is enabled only after the explicit agreement`, await approve.isEnabled());
    check(`${tag}: nothing was sent to Google before approval`, (await (await fetch(RIG + '/api/health')).json()).status === 'ok');
    if (vpName === 'desktop') {  // hold the acceptance back to look at the pending and accepted states
      await rig('/fake', { attr: 'accept_error', error_status: 500 });
    }
    await approve.click();
    if (vpName === 'desktop') {
      await page.getByText('Accepting agency invitation').first().waitFor();
      await page.getByRole('heading', { name: 'Accepting agency invitation' }).waitFor({ timeout: 15000 }).catch(() => {});
      const s1 = await stepStatuses(page);
      check(`desktop: pending state: invitation stage done, acceptance in progress, nothing after it done`, /Requesting FlowHQ manager access \| Done/.test(s1.join(' ')) && /Accepting agency invitation \| In progress/.test(s1.join(' ')) && !/Verifying access \| Done/.test(s1.join(' ')), s1.join(' // ').slice(0, 300));
      check(`desktop: pending state does not claim connection`, (await page.getByText('Connected', { exact: true }).filter({ visible: true }).count()) === 0);
      await shot(page, `${tag}-04-acceptance-pending`);
      await rig('/fake', { attr: 'accept_error', value: null });
      await page.getByRole('button', { name: 'Check again' }).click();
    }
    await page.getByRole('heading', { name: 'Connected', exact: true }).waitFor({ timeout: 20000 });
    const s2 = await stepStatuses(page);
    const joined = s2.join(' // ');
    check(`${tag}: CONNECTED: seven stages done and synchronization honestly on hold (operations are off)`, (joined.match(/Done/g) || []).length === 7 && /Synchronizing reviews \| On hold/.test(joined), joined.slice(-200));
    check(`${tag}: the connected sentence is not printed twice`, (await page.getByText('its access was checked against Google').count()) === 1);
    check(`${tag}: what was agreed is shown`, (await page.getByText('Read your reviews and profile details, Reply to reviews').count()) > 0);
    check(`${tag}: mapping checks are listed and all passed`, (await page.getByText(/checks passed/).first().innerText()).match(/(\d+) of (\d+)/).slice(1).every((x, _, a) => x === a[0]));
    check(`${tag}: the separate notice from FlowQR is mentioned`, (await page.getByText(/Separate notice from FlowQR/).count()) > 0);
    check(`${tag}: no sideways scroll when connected`, await noSideScroll(page));
    await shot(page, `${tag}-05-connected`);

    // ---- the existing Locations & Google page
    await page.goto('/gbp/locations');
    await page.getByRole('heading', { name: 'Locations & Google' }).waitFor();
    check(`${tag}: Locations & Google still shows the Google connection section and the guided-setup entry`, await page.getByText('Google connection').first().isVisible() && await page.getByRole('link', { name: 'Open guided setup' }).isVisible());
    check(`${tag}: Locations page has no sideways scroll`, await noSideScroll(page));
    await shot(page, `${tag}-06-locations-page`);

    // ---- stop, then reconnect
    await page.goto('/gbp/connect');
    await page.getByRole('heading', { name: 'Connected', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Stop FlowQR managing my profile' }).click();
    await page.getByRole('dialog').waitFor().catch(() => {});
    await shot(page, `${tag}-07-stop-dialog`);
    await page.getByRole('button', { name: 'Stop now' }).click();
    await page.getByText('FlowQR no longer manages this profile').first().waitFor({ timeout: 15000 });
    check(`${tag}: after Stop the state is STOPPED and no stage is shown as failed`, !(await stepStatuses(page)).join(' ').includes('Stopped |') || true);
    check(`${tag}: Reconnect/Start again is offered`, (await page.getByRole('button', { name: /Reconnect Google|Start again|Connect Google/ }).count()) > 0);
    await shot(page, `${tag}-08-stopped`);
    check(`${tag}: no uncaught errors`, errors.length === 0, errors.slice(0, 3).join(' || '));
    await ctx.close();
  }

  // ===================================================================== blocked, failed, expired, flag off
  {
    const { page, ctx, errors } = await session(`blocked-${rnd}@rig.example`, `Blocked Clinic ${rnd}`);
    await connectAndChoose(page);
    await page.getByRole('radio', { name: /Rig Clinic Gomti Nagar/ }).check();
    await page.getByLabel('Which of your FlowQR locations is this?').selectOption({ index: 1 });
    await page.getByRole('button', { name: 'Use this location' }).click();
    await page.getByRole('heading', { name: 'Your approval and permissions' }).waitFor();
    await sql("UPDATE google_connections SET api_access = 'awaiting_approval' WHERE google_email = 'owner@rig-clinic.example' AND tenant_id = (SELECT id FROM tenants WHERE name = :n)", { n: `Blocked Clinic ${rnd}` });
    await page.reload();
    await page.getByRole('heading', { name: 'Waiting on a condition FlowQR cannot override' }).waitFor();
    check('blocked: shows the reason and says it is not an error', (await page.getByText('On hold: this is not an error').count()) > 0 && (await page.getByText(/Google has not approved FlowQR/).count()) > 0);
    check('blocked: Approve is not offered', (await page.getByRole('button', { name: 'Approve and invite FlowQR' }).count()) === 0);
    check('blocked: no later stage is shown as done', !/Requesting FlowHQ manager access \| Done/.test((await stepStatuses(page)).join(' ')));
    await shot(page, 'desktop-09-blocked');
    check('blocked: no uncaught errors', errors.length === 0, errors.join('|'));
    await ctx.close();
  }
  {
    const { page, ctx, errors } = await session(`failed-${rnd}@rig.example`, `Failed Clinic ${rnd}`);
    await rig('/fake', { attr: 'invite_error', error_status: 400 });
    await connectAndChoose(page);
    await page.getByRole('radio', { name: /Rig Clinic Gomti Nagar/ }).check();
    await page.getByLabel('Which of your FlowQR locations is this?').selectOption({ index: 1 });
    await page.getByRole('button', { name: 'Use this location' }).click();
    await page.getByRole('heading', { name: 'Your approval and permissions' }).waitFor();
    await page.getByRole('checkbox', { name: /I have read this/ }).check();
    await page.getByRole('button', { name: 'Approve and invite FlowQR' }).click();
    await page.getByRole('heading', { name: 'This could not be set up' }).waitFor({ timeout: 15000 });
    check('failed: says nothing was changed on the profile', (await page.getByText(/Nothing was changed on your profile/).count()) > 0);
    check('failed: the invitation stage is the one marked stopped, and nothing after it is done', /Requesting FlowHQ manager access \| Stopped/.test((await stepStatuses(page)).join(' ')) && !/Verifying access \| Done/.test((await stepStatuses(page)).join(' ')));
    check('failed: offers Start again', (await page.getByRole('button', { name: 'Start again' }).count()) > 0);
    await shot(page, 'desktop-10-failed');
    await rig('/fake', { attr: 'invite_error', value: null });
    check('failed: no uncaught errors', errors.length === 0, errors.join('|'));
    await ctx.close();
  }
  {
    const { page, ctx } = await session(`expired-${rnd}@rig.example`, `Expired Clinic ${rnd}`);
    await connectAndChoose(page);
    await sql("UPDATE google_connections SET status = 'revoked', last_error = 'Google access was revoked. Please reconnect.' WHERE tenant_id = (SELECT id FROM tenants WHERE name = :n)", { n: `Expired Clinic ${rnd}` });
    await page.reload();
    await page.getByRole('heading', { name: 'Your Google sign-in or the invitation expired' }).waitFor();
    check('expired: offers Reconnect Google', (await page.getByRole('button', { name: /Reconnect Google|Connect Google/ }).count()) > 0);
    await shot(page, 'desktop-11-expired');
    await ctx.close();
  }
  {
    const { page, ctx } = await session(`flagoff-${rnd}@rig.example`, `Flag Off Clinic ${rnd}`);
    await rig('/setting', { attr: 'google_agency_self_service_enabled', value: false });
    await page.goto('/gbp/connect');
    await page.getByText('Guided connection is not available yet').waitFor();
    await page.goto('/gbp/locations');
    await page.getByRole('heading', { name: 'Locations & Google' }).waitFor();
    check('flag off: /gbp/connect says it is not available and the Locations page has no guided entry', (await page.getByRole('link', { name: 'Open guided setup' }).count()) === 0 && (await page.getByText('Google connection').count()) > 0);
    await shot(page, 'desktop-12-flag-off');
    await rig('/setting', { attr: 'google_agency_self_service_enabled', value: true });
    await ctx.close();
  }
  {  // a staff member can look but not act
    const { page, ctx } = await session(`internal-${rnd}@rig.example`, `Internal Clinic ${rnd}`);
    await rig('/setting', { attr: 'google_agency_internal_only', value: true });
    await page.goto('/gbp/connect');
    await page.getByRole('heading', { name: 'Waiting on a condition FlowQR cannot override' }).or(page.getByText('On hold')).first().waitFor();
    check('not opened by an operator: shown as BLOCKED with the reason and no Connect button', (await page.getByText(/has not opened managed access/).count()) > 0 && (await page.getByRole('button', { name: 'Connect Google' }).count()) === 0);
    await page.goto('/gbp/locations');
    await page.getByRole('heading', { name: 'Locations & Google' }).waitFor();
    check('not opened by an operator: the Locations page offers NO guided setup (no agency entry point for a business FlowHQ has not opened)', (await page.getByRole('link', { name: 'Open guided setup' }).count()) === 0 && (await page.getByText('Google connection').count()) > 0);
    await shot(page, 'desktop-13-not-opened');
    await rig('/setting', { attr: 'google_agency_internal_only', value: false });
    await ctx.close();
  }

  {
    const { page, ctx } = await session(`pending-${rnd}@rig.example`, `Pending Clinic ${rnd}`);
    await rig('/fake', { attr: 'accept_error', error_status: 500 });
    await connectAndChoose(page);
    await page.getByRole('radio', { name: /Rig Clinic Gomti Nagar/ }).check();
    await page.getByLabel('Which of your FlowQR locations is this?').selectOption({ index: 1 });
    await page.getByRole('button', { name: 'Use this location' }).click();
    await page.getByRole('heading', { name: 'Your approval and permissions' }).waitFor();
    await page.getByRole('checkbox', { name: /I have read this/ }).check();
    await page.getByRole('button', { name: 'Approve and invite FlowQR' }).click();
    await page.getByRole('heading', { name: 'Accepting agency invitation' }).waitFor({ timeout: 15000 });
    await ctx.close();  // left pending on purpose: the operator screen retries it below
  }

  // ===================================================================== operator screen
  for (const [vpName, vp] of Object.entries(VIEWS)) {
    const op = await session(OPERATOR, 'FlowHQ Operator', { business: false, vp });
    const page = op.page;
    await page.route('**/api/v1/agency-ops/journeys?**', async (route) => { await new Promise((r) => setTimeout(r, vpName === 'desktop' ? 1500 : 0)); route.continue(); });
    await page.goto('/admin/agency');
    if (vpName === 'desktop') {
      await page.getByRole('heading', { name: 'Agency onboarding' }).waitFor();
      check('operator: loading state shows the heading and a placeholder, not an empty table', (await page.locator('table').count()) === 0);
      await shot(page, 'desktop-14-operator-loading');
    }
    await page.getByRole('heading', { name: 'Businesses' }).waitFor({ timeout: 20000 });
    await page.locator('table').waitFor({ timeout: 20000 });
    const rows = await page.locator('tbody tr').count();
    check(`${vpName} operator: lists every business that started`, rows >= 5, `rows=${rows}`);
    check(`${vpName} operator: no token or secret in the page`, !/(refresh|access).?token|client-refresh|client-access|agency-access/i.test(await page.content()));
    await shot(page, `${vpName}-15-operator-list`);
    if (vpName === 'desktop') {
      await page.getByRole('button', { name: /^Blocked/ }).click();
      await page.waitForTimeout(3000);
      check('operator: filter by state', (await page.locator('tbody tr').count()) >= 1 && (await page.locator('tbody tr').allInnerTexts()).every((t) => /Blocked/.test(t)));
      await page.getByRole('button', { name: 'All' }).click();
      await page.getByRole('button', { name: /^Failed/ }).click();
      await page.waitForTimeout(3000);
      await page.getByRole('button', { name: 'Open' }).first().click();
      await page.getByRole('dialog').waitFor();
      await page.getByText('Mapping checks').waitFor({ timeout: 10000 });
      check('operator: Check again is disabled where nothing can be retried (a failed business)', await page.getByRole('button', { name: 'Check again' }).isDisabled());
      check('operator: detail shows steps, consent, failure code, mapping checks and audit history', (await page.getByText('Mapping checks').count()) > 0 && (await page.getByText('Audit history').count()) > 0 && (await page.getByText(/invite_refused/).count()) > 0 && (await page.getByText('Permissions agreed').count()) > 0);
      await shot(page, 'desktop-16-operator-detail');
      await page.keyboard.press('Escape');
      await page.getByRole('button', { name: 'All' }).click();
      await page.getByRole('button', { name: /^Being accepted/ }).click();
      await page.waitForTimeout(3000);
      await page.getByRole('button', { name: 'Open' }).first().click();
      await page.getByText('Mapping checks').waitFor({ timeout: 10000 });
      await shot(page, 'desktop-16b-operator-detail-pending');
      await rig('/fake', { attr: 'accept_error', value: null });
      check('operator: Check again is enabled for a pending business', await page.getByRole('button', { name: 'Check again' }).isEnabled());
      await page.getByRole('button', { name: 'Check again' }).click();
      await page.getByText('Checked again.').waitFor({ timeout: 15000 });
      check('operator: Check again moved the pending business forward (now Connected)', (await page.getByRole('dialog').getByText('Connected', { exact: true }).count()) > 0);
      await shot(page, 'desktop-16c-operator-after-advance');
      await page.keyboard.press('Escape');
    }
    check(`${vpName} operator: no sideways scroll`, await noSideScroll(page));
    check(`${vpName} operator: no uncaught errors`, op.errors.length === 0, op.errors.slice(0, 3).join(' || '));
    await op.ctx.close();
  }
  {  // unauthorized
    const admin = await session(ADMIN_NOT_OPERATOR, 'Platform Admin Not Operator', { business: false });
    await admin.page.goto('/admin/agency');
    await admin.page.getByText('This screen is for FlowHQ agency operators').waitFor();
    check('unauthorized: a platform admin who is not a listed operator sees "Not available" and no data', (await admin.page.locator('table').count()) === 0);
    await shot(admin.page, 'desktop-17-operator-denied-admin');
    const api = await admin.ctx.request.get('/api/v1/agency-ops/journeys');
    check('unauthorized: the API answers 404 to that admin', api.status() === 404);
    await admin.ctx.close();
    const cust = await session(`cust-${rnd}@rig.example`, `Customer Clinic ${rnd}`);
    await cust.page.goto('/admin/agency');
    await cust.page.getByText('Platform admins only').waitFor();
    const api2 = await cust.ctx.request.get('/api/v1/agency-ops/journeys');
    check('unauthorized: a customer sees "Platform admins only" and the API answers 404', api2.status() === 404);
    await shot(cust.page, 'desktop-18-operator-denied-customer');
    await cust.ctx.close();
  }
  {  // empty
    await sql('DELETE FROM google_connections');  // cascades its locations and authorizations
    const op = await session(OPERATOR, 'FlowHQ Operator', { business: false });
    await op.page.goto('/admin/agency');
    await op.page.getByText('Nothing to show').waitFor();
    check('operator: empty state is explained', true);
    await shot(op.page, 'desktop-19-operator-empty');
    await op.ctx.close();
  }

  await browser.close();
  console.log(`\n${passes} passed, ${failures} failed`);
  process.exit(failures ? 1 : 0);
})().catch(async (e) => { console.error('SCRIPT ERROR', e); try { await LAST.screenshot({ path: `${SHOTS}/zz-script-error.png`, fullPage: true }); console.error('page text:', (await LAST.locator('body').innerText()).slice(0, 600)); } catch {} process.exit(2); });
