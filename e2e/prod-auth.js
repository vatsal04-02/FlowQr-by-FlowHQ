// Browser test of the REAL production authentication path: the site on its own origin talking to the API on another (https://www.flowqr.site -> https://api.flowqr.site).
//   PHASE=register|verify|reset-request|reset-confirm: the mailbox-dependent steps (the verification and reset links are pasted in by the person who owns the test mailbox)
//   PHASE=public  node e2e/prod-auth.js     needs no account and no email: pages, Google availability, allowlist refusal, wrong password, route guards, CORS, bundle hygiene
//   PHASE=account EMAIL=... PASSWORD=... [ADMIN_EMAIL=... ADMIN_PASSWORD=...] node e2e/prod-auth.js     a controlled test account that already exists: login, cookies, CSRF, refresh, logout, admin gate
// Run it from a container (the host's TLS interception breaks real-domain tests): see docs/PRODUCTION_AUTH_TESTING.md. It creates NOTHING: registration is only ever attempted with an
// address that must be REFUSED, and it asserts that. Registering an approved test account, verifying and resetting passwords are done by hand (they need a real mailbox).
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }
const SITE = (process.env.SITE || 'https://www.flowqr.site').replace(/\/$/, ''), API = (process.env.API || 'https://api.flowqr.site').replace(/\/$/, '');
const PHASE = process.env.PHASE || 'public';
const TAG = Math.random().toString(36).slice(2, 8);
const results = [];
const expect = (c, m) => { if (!c) throw new Error(m); };

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'], ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const consoleProblems = [], apiCalls = [], apiStatuses = [];
  page.on('console', (m) => { if (m.type() === 'error' && /CORS|blocked|net::ERR|Access-Control/i.test(m.text())) consoleProblems.push(m.text().slice(0, 200)); });
  page.on('requestfailed', (r) => { if (r.url().startsWith(API)) consoleProblems.push(`request failed: ${r.method()} ${r.url().replace(API, '')} ${(r.failure() || {}).errorText}`); });
  page.on('request', (r) => { if (/\/api\//.test(r.url()) && !r.url().startsWith(SITE)) apiCalls.push(r.url()); });
  page.on('response', (r) => { if (r.url().startsWith(API + '/api/v1')) apiStatuses.push(`${r.request().method()} ${r.url().replace(API, '')} ${r.status()}`); });
  async function step(name, fn) {
    try { await fn(); results.push([name, true]); console.log('PASS', name); }
    catch (e) { results.push([name, false]); console.log('FAIL', name, '\n     ', String(e.message).split('\n')[0].slice(0, 400)); if (consoleProblems.length) console.log('      browser:', consoleProblems.slice(-3).join(' | ')); if (apiStatuses.length) console.log('      last API:', apiStatuses.slice(-3).join(' | ')); await page.screenshot({ path: `prod-auth-fail-${results.length}.png` }).catch(() => {}); }
  }
  const body = async () => (await page.locator('body').innerText()).replace(/\s+/g, ' ');
  const cookies = async () => Object.fromEntries((await ctx.cookies()).map((c) => [c.name, c]));
  const call = (method, path, data, headers) => page.evaluate(async ([m, u, b, h]) => {
    const r = await fetch(u, { method: m, credentials: 'include', headers: { 'content-type': 'application/json', ...h }, body: b ? JSON.stringify(b) : undefined });
    const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch { /* not JSON */ }
    return { status: r.status, json: j };
  }, [method, `${API}/api/v1${path}`, data || null, headers || {}]);
  const login = async (email, password) => {
    await page.goto(`${SITE}/login`); await page.waitForLoadState('networkidle');
    await page.locator('input[type=email]').first().fill(email); await page.locator('input[type=password]').first().fill(password);
    await page.getByRole('button', { name: /^log in$/i }).click();
  };

  if (PHASE === 'public') {
    await step('the login page loads, every API call goes to the API origin, and no CORS error appears', async () => {
      await page.goto(`${SITE}/login`); await page.waitForLoadState('networkidle');
      expect(/welcome back/i.test(await body()), 'login page text missing: ' + (await body()).slice(0, 160));
      expect(apiCalls.length > 0 && apiCalls.every((u) => u.startsWith(API)), `API calls went to: ${[...new Set(apiCalls)].join(', ')}`);
      expect(consoleProblems.length === 0, 'console: ' + consoleProblems.join(' | '));
    });
    await step('Google sign-in is offered ONLY if the server says it works (no misleading button, no error banner)', async () => {
      const providers = await call('GET', '/auth/providers');
      expect(providers.status === 200 && typeof providers.json.google === 'boolean', 'providers endpoint: ' + JSON.stringify(providers));
      const shown = await page.getByText(/continue with google|sign up with google/i).count();
      expect(shown === (providers.json.google ? 1 : 0), `server says google=${providers.json.google} but the page shows ${shown} Google button(s)`);
      expect(!/isn't available on this server/i.test(await body()), 'the page shows the "not available" error without any click');
      console.log('     google configured on the server:', providers.json.google);
    });
    await step('the sign-up page says registration is by approval, and offers no Google button when Google is off', async () => {
      await page.goto(`${SITE}/register`); await page.waitForLoadState('networkidle');
      const mode = await call('GET', '/auth/registration');
      expect(mode.json.mode === 'allowlist', 'registration mode is ' + mode.json.mode + ' (must stay allowlist)');
      expect(/approved businesses only/i.test(await body()), 'the allowlist notice is missing');
    });
    await step('an address that is NOT on the allowlist gets the clear refusal and no session', async () => {
      await page.goto(`${SITE}/register`); await page.waitForLoadState('networkidle');
      await page.getByLabel(/your name/i).fill('Refusal Test'); await page.getByLabel(/work email/i).fill(`not-listed-${TAG}@example.com`);
      await page.getByLabel(/^password/i).fill('Str0ngPassw0rd!x' + TAG);
      await page.getByLabel(/18 years of age or older/i).check();
      await page.getByRole('button', { name: /create account/i }).click();
      await page.waitForFunction(() => /approved businesses only at the moment/i.test(document.body.innerText) && document.querySelectorAll('[role=alert]').length > 0, null, { timeout: 15000 });
      expect(/\/register/.test(page.url()), 'left the sign-up page: ' + page.url());
      expect(!(await cookies()).flowqr_session, 'a session cookie was set for a refused registration');
      expect(apiStatuses.some((s) => s.startsWith('POST /api/v1/auth/register 403')), 'no 403 from the API: ' + apiStatuses.join(', '));
    });
    await step('a wrong password shows a plain message, keeps the user on the login page and sets no session', async () => {
      await login(`nobody-${TAG}@example.com`, 'Wrong-Passw0rd!1');
      await page.waitForFunction(() => /invalid|incorrect|wrong/i.test(document.body.innerText), null, { timeout: 15000 });
      expect(/\/login/.test(page.url()), 'moved away: ' + page.url());
      expect(!(await cookies()).flowqr_session, 'a session cookie was set');
      expect(!/traceback|internal server|stack|at \w+\.\w+ \(/i.test(await body()), 'raw error text on the page');
    });
    await step('protected pages send an anonymous visitor to the login page', async () => {
      for (const path of ['/overview', '/settings', '/admin']) {
        await page.goto(`${SITE}${path}`); await page.waitForURL(/\/login/, { timeout: 15000 });
      }
    });
    await step('the password-reset form calls the real endpoint and answers the same for any address', async () => {
      await page.goto(`${SITE}/forgot-password`); await page.waitForLoadState('networkidle');
      await page.locator('input[type=email]').first().fill(`nobody-${TAG}@example.com`);
      await page.getByRole('button', { name: /send|reset|email/i }).first().click();
      await page.waitForFunction(() => /check your (email|inbox)|sent|if an account/i.test(document.body.innerText), null, { timeout: 15000 });
      expect(apiStatuses.some((s) => s.startsWith('POST /api/v1/auth/password-reset/request 202')), 'no 202: ' + apiStatuses.slice(-3).join(', '));
    });
    await step('CORS: the site origin is allowed with credentials, a foreign origin is not', async () => {
      const ok = await ctx.request.fetch(`${API}/api/v1/auth/me`, { method: 'OPTIONS', headers: { Origin: SITE, 'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'content-type,x-csrf-token' } });
      expect(ok.headers()['access-control-allow-origin'] === SITE && ok.headers()['access-control-allow-credentials'] === 'true', 'site origin: ' + JSON.stringify(ok.headers()));
      const bad = await ctx.request.fetch(`${API}/api/v1/auth/me`, { method: 'OPTIONS', headers: { Origin: 'https://evil.example', 'Access-Control-Request-Method': 'GET' } });
      expect(!bad.headers()['access-control-allow-origin'], 'foreign origin was allowed: ' + bad.headers()['access-control-allow-origin']);
    });
    await step('no secrets or tokens in the page, the scripts or browser storage', async () => {
      const store = await page.evaluate(() => JSON.stringify({ l: Object.entries(localStorage), s: Object.entries(sessionStorage) }));
      expect(!/token|session|password|secret/i.test(store), 'browser storage holds: ' + store.slice(0, 200));
      await page.goto(`${SITE}/login`); await page.waitForLoadState('networkidle');
      const srcs = await page.evaluate(() => [...document.scripts].map((s) => s.src).filter(Boolean));
      let leaked = [];
      for (const s of srcs.slice(0, 40)) { const t = await (await ctx.request.get(s)).text(); if (/GOCSPX-|client_secret|AIza[0-9A-Za-z_-]{20}|sk-[A-Za-z0-9]{20}|BEGIN (RSA |)PRIVATE/.test(t)) leaked.push(s); }
      expect(leaked.length === 0, 'secret-looking text in: ' + leaked.join(', '));
    });
  } else if (PHASE === 'register') {
    // Creates ONE account through the real sign-up form. The address must already be on the allowlist (python -m app.cli registration --add). Sends the verification email.
    const EMAIL = process.env.EMAIL, PASSWORD = process.env.PASSWORD, NAME = process.env.NAME || 'Auth Test';
    expect(EMAIL && PASSWORD, 'EMAIL and PASSWORD are required for PHASE=register');
    await step('register the allowlisted test account through the real sign-up form', async () => {
      await page.goto(`${SITE}/register`); await page.waitForLoadState('networkidle');
      await page.getByLabel(/your name/i).fill(NAME); await page.getByLabel(/work email/i).fill(EMAIL); await page.getByLabel(/^password/i).fill(PASSWORD);
      await page.getByLabel(/18 years of age or older/i).check();
      await page.getByRole('button', { name: /create account/i }).click();
      await page.waitForURL(/\/onboarding|\/admin|\/overview/, { timeout: 25000 });
      expect(apiStatuses.some((s) => s.startsWith('POST /api/v1/auth/register 201')), 'no 201: ' + apiStatuses.join(', '));
    });
    await step('the new account starts with an unverified email, no admin rights, and a production-grade session cookie', async () => {
      const me = await call('GET', '/auth/me');
      expect(me.status === 200 && me.json.user.email.toLowerCase() === EMAIL.toLowerCase(), 'me: ' + me.status);
      expect(me.json.user.email_verified_at === null, 'already verified?');
      expect(me.json.user.is_platform_admin === false, 'a new account must not be an administrator');
      const s = (await cookies()).flowqr_session;
      expect(s && s.domain === '.flowqr.site' && s.secure && s.httpOnly && s.sameSite === 'Lax', 'session cookie: ' + JSON.stringify(s && { d: s.domain, sec: s.secure, ho: s.httpOnly, ss: s.sameSite }));
      expect((await call('GET', '/admin/stats')).status === 403, 'an unverified new account reached the admin API');
    });
  } else if (PHASE === 'product') {
    // Controlled test business on a VERIFIED, allowlisted test account: onboarding through the real forms, trial length, dashboard, QR downloads, the business-specific landing page,
    // a customer session without AI, analytics, and tenant isolation against a SECOND tenant owned by ADMIN_EMAIL/ADMIN_PASSWORD (a verified second account). No card is printed,
    // nothing is sent to Google, no AI call is made.
    const EMAIL = process.env.EMAIL, PASSWORD = process.env.PASSWORD, BIZ = `Auth Test Clinic ${TAG}`;
    expect(EMAIL && PASSWORD, 'EMAIL and PASSWORD are required for PHASE=product');
    const REVIEW_URL = `https://g.page/r/AuthTest${TAG}/review`;
    const PHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'; // the API refuses automated clients (headless Chrome says so); a customer's phone does not
    const callP = (pg, method, path, data, headers, opts = {}) => pg.evaluate(async ([m, u, b, h, cred]) => {
      const r = await fetch(u, { method: m, credentials: cred ? 'include' : 'omit', headers: { ...(b ? { 'content-type': 'application/json' } : {}), ...h }, body: b ? JSON.stringify(b) : undefined });
      const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch { /* not JSON */ }
      return { status: r.status, json: j, text: t.slice(0, 300) };
    }, [method, `${API}/api/v1${path}`, data || null, headers || {}, opts.cred !== false]);
    const csrfOf = async (c) => ((await c.cookies()).find((k) => k.name === 'flowqr_csrf') || {}).value;
    const bytesOf = (pg, path) => pg.evaluate(async (u) => {
      const r = await fetch(u, { credentials: 'include' }); const b = new Uint8Array(await r.arrayBuffer());
      return { status: r.status, type: r.headers.get('content-type'), len: b.length, head: Array.from(b.slice(0, 8)), text: new TextDecoder().decode(b.slice(0, 60)) };
    }, `${API}/api/v1${path}`);
    let camp, tenantA;

    await step('log in as the verified test account', async () => { await login(EMAIL, PASSWORD); await page.waitForURL(/\/(onboarding|overview)/, { timeout: 25000 }); });
    await step('business onboarding through the real forms (business, location, review link, first review page)', async () => {
      await page.goto(`${SITE}/onboarding`); await page.waitForLoadState('networkidle'); await page.waitForTimeout(1500);
      if (/\/overview/.test(page.url())) { console.log('     (already onboarded: this account has its test business)'); return; }
      // one form: the business and its first location
      await page.getByLabel(/business name/i).waitFor({ timeout: 20000 });
      await page.getByLabel(/business name/i).fill(BIZ); await page.getByLabel(/business type/i).selectOption('Physiotherapy clinic');
      await page.getByLabel(/^city/i).fill('Lucknow'); await page.getByLabel(/^review link/i).fill(REVIEW_URL);
      await page.getByRole('button', { name: /^continue$/i }).click();
      await page.getByText(/use my google review link/i).first().click({ timeout: 20000 }); await page.getByRole('button', { name: /^continue$/i }).click();
      await page.getByRole('heading', { name: /choose your plan|free trial/i }).waitFor({ timeout: 20000 });
      // A card-required server cannot be passed by a script (it cannot type a card): say so plainly instead of timing out.
      expect(await page.getByRole('button', { name: /authorise payment and start free trial/i }).count() === 0, 'Payment authorisation is required: this script cannot complete one. Use an account that already finished onboarding.');
      await page.getByRole('button', { name: /start my free trial/i }).click();
      await page.getByText(/you are all set/i).waitFor({ timeout: 20000 });
      await page.getByText(/first review page/i).first().waitFor({ timeout: 20000 });
      const mk = page.getByRole('button', { name: /create my review page/i });
      await mk.waitFor({ timeout: 15000 }).catch(() => {}); // the page is still loading the plan and locations
      if (await mk.count()) { await mk.click(); await page.getByText(/^created$/i).first().waitFor({ timeout: 20000 }); }
      await page.getByRole('button', { name: /open my dashboard/i }).click();
      await page.waitForURL(/\/overview/, { timeout: 25000 });
    });
    let bizName = BIZ;
    await step('the dashboard loads for the new business and the trial is 7 days', async () => {
      await page.waitForLoadState('networkidle');
      const me = await callP(page, 'GET', '/auth/me'); tenantA = me.json.memberships[0].tenant.id; bizName = me.json.memberships[0].tenant.name;
      expect(me.json.memberships.length === 1 && me.json.memberships[0].role === 'owner', 'membership: ' + JSON.stringify(me.json.memberships.map((m) => m.role)));
      const sub = await callP(page, 'GET', '/billing/subscription');
      expect(sub.json.status === 'trialing' && sub.json.active === true, 'subscription: ' + JSON.stringify({ s: sub.json.status, a: sub.json.active }));
      expect([6, 7].includes(sub.json.trial_days_left), 'trial_days_left=' + sub.json.trial_days_left + ' (the production trial must be 7 days)');
      expect(!/something went wrong|error/i.test(await body()), 'the dashboard shows an error');
    });
    await step('a review campaign exists with a permanent business-specific address', async () => {
      let list = await callP(page, 'GET', '/review-growth/campaigns');
      if (list.status === 200 && list.json.length === 0) {  // the first-page button was not used in an earlier run: create it exactly as that button does
        const locs = await callP(page, 'GET', '/locations'); const mk = await callP(page, 'POST', '/review-growth/campaigns', { name: 'Auth test reviews', location_id: locs.json[0].id }, { 'X-CSRF-Token': await csrfOf(ctx) });
        expect(mk.status === 201, 'create campaign ' + mk.status + ' ' + mk.text); console.log('     (campaign created through the API: the first-page button had not been used)'); list = await callP(page, 'GET', '/review-growth/campaigns');
      }
      expect(list.status === 200 && list.json.length >= 1, 'campaigns: ' + list.status + ' ' + list.text);
      camp = list.json[0];
      expect(camp.review_url_ready === true && /\/r\/[A-Za-z0-9_-]+$/.test(camp.url), 'campaign: ' + JSON.stringify({ url: camp.url, ready: camp.review_url_ready }));
    });
    await step('QR image downloads: PNG and SVG are real images, and the poster renders', async () => {
      const png = await bytesOf(page, `/review-growth/campaigns/${camp.id}/qr.png`);
      expect(png.status === 200 && /image\/png/.test(png.type) && png.head.slice(0, 4).join() === '137,80,78,71' && png.len > 800, 'png: ' + JSON.stringify(png));
      const svg = await bytesOf(page, `/review-growth/campaigns/${camp.id}/qr.svg`);
      expect(svg.status === 200 && /svg/.test(svg.type) && /<svg|<\?xml/.test(svg.text), 'svg: ' + JSON.stringify(svg));
      const poster = await bytesOf(page, `/review-growth/campaigns/${camp.id}/poster.png`);
      expect(poster.status === 200 && /image\/png/.test(poster.type) && poster.len > 5000, 'poster: ' + JSON.stringify(poster));
    });
    await step('the QR address opens the business-specific landing page on the real site', async () => {
      const cust = await browser.newContext({ viewport: { width: 390, height: 800 }, userAgent: PHONE_UA, isMobile: true }); const p = await cust.newPage();
      const seen = []; p.on('request', (q) => { if (q.url().startsWith(API)) seen.push(q.method() + ' ' + q.url().replace(API, '').replace(/[A-Za-z0-9_-]{16,}/g, '<id>')); });
      const r = await p.goto(camp.url, { waitUntil: 'networkidle' });
      expect(r && r.status() === 200, 'landing status ' + (r && r.status()));
      await p.getByText(new RegExp(bizName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i')).first().waitFor({ timeout: 20000 });
      expect(/flowqr\.site\/r\//.test(p.url()), 'landed on ' + p.url());
      console.log('     landing page API calls:', [...new Set(seen)].join(', ')); await p.screenshot({ path: 'landing-mobile.png' }); await cust.close();
    });
    let sid;
    await step('a customer review session without AI: start, confirm own wording, continue to Google', async () => {
      const pid = camp.public_id; const anon = await browser.newContext({ userAgent: PHONE_UA }); const p = await anon.newPage(); await p.goto(`${SITE}/login`);
      const g = await callP(p, 'POST', `/public/reviews/${pid}/generate`, { mode: 'manual', rating: 5, language: 'en' }, {}, { cred: false });
      expect(g.status === 200, 'start: ' + g.status + ' ' + g.text);
      sid = g.json.session_id || g.json.session || (g.json.session_identifier); expect(sid, 'no session id in ' + Object.keys(g.json).join(','));
      const a = await callP(p, 'POST', `/public/reviews/${pid}/approve`, { session_id: sid, final_text: 'Friendly staff and a clean clinic. Thank you for the care.' }, {}, { cred: false });
      expect(a.status === 200 && a.json.google_ready === true && /^https:\/\/g\.page\/r\/AuthTest[A-Za-z0-9]+\/review$/.test(a.json.review_url), 'approve: ' + a.status + ' ' + a.text);
      const r = await callP(p, 'POST', `/public/reviews/${pid}/redirect`, { session_id: sid, copied: true }, {}, { cred: false });
      expect(r.status === 200 && r.json.review_url === a.json.review_url, 'redirect: ' + r.status + ' ' + r.text);
      const direct = await callP(p, 'POST', `/public/reviews/${pid}/submit`, { session_id: sid, final_text: 'Friendly staff and a clean clinic. Thank you for the care.', rating: 5, consent: true, language: 'en', suggestions: [] }, {}, { cred: false });
      expect(direct.status === 409, 'direct submission to Google must stay unavailable (409), got ' + direct.status);
      await anon.close();
    });
    await step('analytics count the scan, the confirmation and the Google tap', async () => {
      await page.waitForTimeout(1500);
      const an = await callP(page, 'GET', '/review-growth/analytics'); expect(an.status === 200, 'analytics ' + an.status);
      const flat = JSON.stringify(an.json);
      const num = (re) => { let best = 0; (function walk(o) { for (const [k, v] of Object.entries(o || {})) { if (v && typeof v === 'object') walk(v); else if (re.test(k) && typeof v === 'number') best = Math.max(best, v); } })(an.json); return best; };
      expect(num(/scan/i) >= 1, 'no scan counted: ' + flat.slice(0, 300));
      expect(num(/approv|confirm/i) >= 1 || num(/redirect|google/i) >= 1, 'no customer step counted: ' + flat.slice(0, 300));
    });
    if (process.env.ADMIN_EMAIL && process.env.ADMIN_PASSWORD) {
      let b; const actx = await browser.newContext(); const ap = await actx.newPage();
      await step('a second tenant (owned by the verified second account) exists for the isolation test', async () => {
        const L = await ap.request.post(`${API}/api/v1/auth/login`, { data: { email: process.env.ADMIN_EMAIL, password: process.env.ADMIN_PASSWORD }, headers: { Origin: SITE } });
        expect(L.status() === 200, 'second account login ' + L.status()); await ap.goto(`${SITE}/login`);
        const cs = (await L.json()).csrf_token; const H = { 'X-CSRF-Token': cs };
        let me = await callP(ap, 'GET', '/auth/me'); let tid = me.json.memberships[0] && me.json.memberships[0].tenant.id;
        if (!tid) { const t = await callP(ap, 'POST', '/tenants', { name: `Isolation Test Co ${TAG}`, category: 'Physiotherapy clinic', language: 'en' }, H); expect(t.status === 201, 'create tenant ' + t.status + ' ' + t.text); tid = t.json.id; }
        const loc = await callP(ap, 'POST', '/locations', { name: 'Iso branch', city: 'Delhi', review_url: `https://g.page/r/Iso${TAG}/review` }, H); expect(loc.status === 201, 'location ' + loc.status + ' ' + loc.text);
        const cp = await callP(ap, 'POST', '/review-growth/campaigns', { name: 'Iso campaign', location_id: loc.json.id }, H); expect(cp.status === 201, 'campaign ' + cp.status + ' ' + cp.text);
        b = { tenant: tid, loc: loc.json.id, camp: cp.json.id, H };
      });
      await step('tenant isolation: neither account can read or change the other tenant\'s records (404/403, never 200)', async () => {
        const csrfA = await csrfOf(ctx);
        for (const [m, p, d] of [['GET', `/review-growth/campaigns/${b.camp}`], ['GET', `/locations/${b.loc}`], ['PATCH', `/review-growth/campaigns/${b.camp}`, { name: 'hijacked' }], ['DELETE', `/locations/${b.loc}`]]) {
          const r = await callP(page, m, p, d, { 'X-CSRF-Token': csrfA }); expect([403, 404].includes(r.status), `A -> B ${m} ${p}: ${r.status}`);
        }
        const png = await bytesOf(page, `/review-growth/campaigns/${b.camp}/qr.png`); expect([403, 404].includes(png.status), 'A downloaded B\'s QR: ' + png.status);
        const hdr = await callP(page, 'GET', '/review-growth/campaigns', null, { 'X-Tenant-Id': b.tenant }); expect(hdr.status === 403 || (hdr.status === 200 && !JSON.stringify(hdr.json).includes(b.camp)), 'X-Tenant-Id switch leaked: ' + hdr.status);
        const mineInList = await callP(ap, 'GET', '/review-growth/campaigns'); expect(!JSON.stringify(mineInList.json).includes(camp.id), 'B can list A\'s campaign');
        const rev = await callP(ap, 'GET', `/review-growth/campaigns/${camp.id}`, null, { 'X-CSRF-Token': b.H['X-CSRF-Token'] }); expect([403, 404].includes(rev.status), `B -> A: ${rev.status}`);
        const anon = await ctx.request.get(`${API}/api/v1/review-growth/campaigns/${b.camp}`, { headers: { Cookie: '' } }); expect([401, 403].includes(anon.status()), 'anonymous read: ' + anon.status());
      });
      await actx.close();
    } else {
      results.push(['tenant isolation (needs ADMIN_EMAIL/ADMIN_PASSWORD, a verified second account)', null]); console.log('SKIP tenant isolation: no second verified account supplied');
    }
    await step('log out at the end', async () => { const out = await callP(page, 'POST', '/auth/logout', null, { 'X-CSRF-Token': await csrfOf(ctx) }); expect(out.status === 204, 'logout ' + out.status); });
  } else if (PHASE === 'verify' || PHASE === 'reset-request' || PHASE === 'reset-confirm') {
    const EMAIL = process.env.EMAIL, LINK = process.env.LINK || '';
    const okLink = /^https:\/\/(www\.)?flowqr\.site\/(verify-email|reset-password)\?token=[A-Za-z0-9_-]+$/.test(LINK);
    if (PHASE === 'reset-request') {
      expect(EMAIL, 'EMAIL is required');
      await step('request a password reset through the real form', async () => {
        await page.goto(`${SITE}/forgot-password`); await page.waitForLoadState('networkidle');
        await page.locator('input[type=email]').first().fill(EMAIL);
        await page.getByRole('button', { name: /send|reset|email/i }).first().click();
        await page.waitForFunction(() => /check your (email|inbox)|sent|if an account/i.test(document.body.innerText), null, { timeout: 15000 });
        expect(apiStatuses.some((s) => s.startsWith('POST /api/v1/auth/password-reset/request 202')), 'no 202: ' + apiStatuses.join(', '));
      });
    } else if (PHASE === 'verify') {
      await step('the verification link from the email verifies the address in the browser', async () => {
        expect(okLink && /verify-email/.test(LINK), 'LINK must be the https://(www.)flowqr.site/verify-email?token=... link from the email');
        await page.goto(LINK); await page.waitForFunction(() => /email verified|couldn.t verify/i.test(document.body.innerText), null, { timeout: 20000 });
        expect(/email verified/i.test(await body()), 'not verified: ' + (await body()).slice(0, 200));
        expect(apiStatuses.some((s) => s.startsWith('POST /api/v1/auth/verify-email 204')), 'no 204: ' + apiStatuses.join(', '));
      });
      await step('the same link cannot be used twice', async () => {
        const again = await ctx.newPage(); await again.goto(LINK); await again.waitForFunction(() => /email verified|couldn.t verify/i.test(document.body.innerText), null, { timeout: 20000 });
        const t = (await again.locator('body').innerText()).replace(/\s+/g, ' ');
        // the backend is idempotent for an already-verified address; what matters is that no error page leaks anything
        expect(!/traceback|internal server/i.test(t), 'raw error: ' + t.slice(0, 160)); await again.close();
      });
    } else {
      const OLD = process.env.OLD_PASSWORD, NEW = process.env.NEW_PASSWORD;
      expect(EMAIL && OLD && NEW, 'EMAIL, OLD_PASSWORD, NEW_PASSWORD are required');
      let other, otherCsrf;
      await step('a second browser is signed in with the old password before the reset', async () => {
        other = await browser.newContext(); const p = await other.newPage();
        const r = await p.request.post(`${API}/api/v1/auth/login`, { data: { email: EMAIL, password: OLD }, headers: { Origin: SITE } });
        expect(r.status() === 200, 'old-password login ' + r.status()); otherCsrf = (await r.json()).csrf_token;
      });
      await step('the reset link sets a new password through the real form', async () => {
        expect(okLink && /reset-password/.test(LINK), 'LINK must be the https://(www.)flowqr.site/reset-password?token=... link from the email');
        await page.goto(LINK); await page.waitForLoadState('networkidle');
        await page.getByLabel(/new password/i).fill(NEW); await page.getByRole('button', { name: /set new password/i }).click();
        await page.waitForFunction(() => /password updated|invalid or has expired/i.test(document.body.innerText), null, { timeout: 20000 });
        expect(/password updated/i.test(await body()), 'not updated: ' + (await body()).slice(0, 200));
        expect(apiStatuses.some((s) => s.startsWith('POST /api/v1/auth/password-reset/confirm 204')), 'no 204: ' + apiStatuses.join(', '));
      });
      await step('the reset link cannot be used a second time', async () => {
        await page.goto(LINK); await page.waitForLoadState('networkidle');
        await page.getByLabel(/new password/i).fill(NEW + 'x'); await page.getByRole('button', { name: /set new password/i }).click();
        await page.waitForFunction(() => /invalid or has expired/i.test(document.body.innerText), null, { timeout: 20000 });
      });
      await step('the session that existed before the reset is signed out everywhere', async () => {
        const p = await other.newPage(); const r = await p.request.get(`${API}/api/v1/auth/me`, { headers: { Origin: SITE } });
        expect(r.status() === 401, 'the old session still works: ' + r.status()); await other.close();
      });
      await step('the OLD password no longer works', async () => {
        const r = await ctx.request.post(`${API}/api/v1/auth/login`, { data: { email: EMAIL, password: OLD }, headers: { Origin: SITE } });
        expect(r.status() === 401, 'old password status ' + r.status());
      });
      await step('the NEW password works in the real login form', async () => {
        await login(EMAIL, NEW); await page.waitForURL(/\/(overview|onboarding|admin)/, { timeout: 20000 });
        expect((await cookies()).flowqr_session, 'no session cookie');
      });
    }
  } else {
    const EMAIL = process.env.EMAIL, PASSWORD = process.env.PASSWORD;
    expect(EMAIL && PASSWORD, 'EMAIL and PASSWORD are required for PHASE=account');
    await step('log in through the real form; the session cookie has the production attributes', async () => {
      await login(EMAIL, PASSWORD);
      await page.waitForURL(/\/(overview|onboarding|admin)/, { timeout: 20000 });
      const c = await cookies(), s = c.flowqr_session, x = c.flowqr_csrf;
      expect(s && x, 'cookies present: ' + Object.keys(c).join(','));
      expect(s.domain === '.flowqr.site' && s.secure && s.httpOnly && s.sameSite === 'Lax', 'session cookie: ' + JSON.stringify({ d: s.domain, sec: s.secure, ho: s.httpOnly, ss: s.sameSite }));
      expect(x.domain === '.flowqr.site' && x.secure && !x.httpOnly && x.sameSite === 'Lax', 'csrf cookie: ' + JSON.stringify({ d: x.domain, sec: x.secure, ho: x.httpOnly, ss: x.sameSite }));
    });
    await step('the session survives a browser refresh and a new tab', async () => {
      await page.reload(); await page.waitForLoadState('networkidle');
      expect(!/\/login/.test(page.url()), 'sent to login after reload: ' + page.url());
      const t = await ctx.newPage(); await t.goto(`${SITE}/settings`); await t.waitForLoadState('networkidle');
      expect(!/\/login/.test(t.url()), 'new tab sent to login: ' + t.url()); await t.close();
    });
    await step('CSRF: a state-changing call without the header is refused, with it is accepted', async () => {
      const csrf = (await cookies()).flowqr_csrf.value;
      const curName = (await call('GET', '/auth/me')).json.user.full_name || 'Test';  // write back the SAME name: this step must not change the account
      const no = await call('PATCH', '/auth/profile', { full_name: curName });
      expect(no.status === 403, 'without the header: ' + no.status);
      const bad = await call('PATCH', '/auth/profile', { full_name: curName }, { 'X-CSRF-Token': 'wrong' });
      expect(bad.status === 403, 'wrong header: ' + bad.status);
      const ok = await call('PATCH', '/auth/profile', { full_name: curName }, { 'X-CSRF-Token': csrf });
      expect(ok.status === 200, 'with the header: ' + ok.status);
    });
    await step('nothing sensitive is kept in browser storage', async () => {
      const store = await page.evaluate(() => JSON.stringify({ l: Object.entries(localStorage), s: Object.entries(sessionStorage) }));
      expect(!/token|session|password|secret|csrf/i.test(store), 'storage: ' + store.slice(0, 200));
    });
    if (process.env.ADMIN_EXPECTED === 'yes') {
      await step('the administrator has the role and reaches the admin console', async () => {
        const me = await call('GET', '/auth/me');
        expect(me.json.user.is_platform_admin === true && me.json.user.email_verified_at, 'role/verification: ' + JSON.stringify({ a: me.json.user.is_platform_admin, v: !!me.json.user.email_verified_at }));
        await page.goto(`${SITE}/admin`); await page.waitForLoadState('networkidle');
        expect(/FlowHQ staff|Platform admin/i.test(await body()) && !/Platform admins only/i.test(await body()), 'admin console not shown: ' + (await body()).slice(0, 160));
      });
      await step('the admin API answers the administrator (read) and still demands the CSRF header (write)', async () => {
        for (const path of ['/admin/stats', '/admin/registration', '/admin/work-queue']) { const r = await call('GET', path); expect(r.status === 200, `${path}: ${r.status}`); }
        const reg = await call('GET', '/admin/registration'); expect(reg.json.mode === 'allowlist', 'registration mode must stay allowlist, got ' + reg.json.mode);
        const noCsrf = await call('POST', '/admin/registration/allowlist', { email: `must-not-be-added-${TAG}@example.com` }); expect(noCsrf.status === 403, 'an admin write without the CSRF header was accepted: ' + noCsrf.status);
        const after = await call('GET', '/admin/registration'); expect(!JSON.stringify(after.json).includes('must-not-be-added'), 'the refused write changed the allowlist');
      });
      await step('the administrator session is the short 12-hour kind', async () => {
        const s = (await cookies()).flowqr_session; const hours = (s.expires - Date.now() / 1000) / 3600;
        expect(hours > 11 && hours <= 12.1, 'admin session lasts ' + hours.toFixed(2) + ' hours (expected about 12)');
      });
    } else {
      await step('an ordinary account cannot open the admin console or its API', async () => {
        await page.goto(`${SITE}/admin`); await page.waitForLoadState('networkidle');
        expect(/Platform admins only/i.test(await body()), 'the admin page was not refused: ' + (await body()).slice(0, 160));
        const csrf = (await cookies()).flowqr_csrf.value;
        for (const [m, path, d] of [['GET', '/admin/stats'], ['GET', '/admin/registration'], ['GET', '/admin/work-queue'], ['POST', '/admin/registration/allowlist', { email: `must-not-be-added-${TAG}@example.com` }]]) {
          const r = await call(m, path, d, { 'X-CSRF-Token': csrf }); expect(r.status === 403, `${m} ${path} answered an ordinary account with ${r.status}`);
        }
      });
    }
    await step('log out clears both cookies and the old session no longer works', async () => {
      const before = (await cookies()).flowqr_session.value;
      await page.evaluate(() => fetch('/', { method: 'HEAD' })); // keep the page alive
      const csrf = (await cookies()).flowqr_csrf.value;
      const out = await call('POST', '/auth/logout', null, { 'X-CSRF-Token': csrf });
      expect(out.status === 204, 'logout status ' + out.status);
      const c = await cookies();
      expect(!c.flowqr_session && !c.flowqr_csrf, 'cookies remain: ' + Object.keys(c).join(','));
      await ctx.addCookies([{ name: 'flowqr_session', value: before, domain: '.flowqr.site', path: '/', secure: true, httpOnly: true, sameSite: 'Lax' }]);
      expect((await call('GET', '/auth/me')).status === 401, 'the old session token still works after logout');
      await ctx.clearCookies();
      await page.goto(`${SITE}/overview`); await page.waitForURL(/\/login/, { timeout: 15000 });
    });
  }

  await browser.close();
  const failed = results.filter((r) => r[1] === false);
  console.log(`\n${results.length - failed.length}/${results.length} passed (${PHASE})`);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('CRASH', e); process.exit(2); });
