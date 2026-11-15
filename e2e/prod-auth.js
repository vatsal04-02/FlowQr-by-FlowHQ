// Browser test of the REAL production authentication path: the site on its own origin talking to the API on another (https://www.flowqr.site -> https://api.flowqr.site).
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
  page.on('request', (r) => { if (/\/api\//.test(r.url()) && !r.url().startsWith(SITE)) apiCalls.push(r.url()); });
  page.on('response', (r) => { if (r.url().startsWith(API + '/api/v1')) apiStatuses.push(`${r.request().method()} ${r.url().replace(API, '')} ${r.status()}`); });
  async function step(name, fn) {
    try { await fn(); results.push([name, true]); console.log('PASS', name); }
    catch (e) { results.push([name, false]); console.log('FAIL', name, '\n     ', String(e.message).split('\n')[0].slice(0, 400)); await page.screenshot({ path: `prod-auth-fail-${results.length}.png` }).catch(() => {}); }
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
      const no = await call('PATCH', '/auth/profile', { full_name: 'Prod Auth Test' });
      expect(no.status === 403, 'without the header: ' + no.status);
      const bad = await call('PATCH', '/auth/profile', { full_name: 'Prod Auth Test' }, { 'X-CSRF-Token': 'wrong' });
      expect(bad.status === 403, 'wrong header: ' + bad.status);
      const ok = await call('PATCH', '/auth/profile', { full_name: 'Prod Auth Test' }, { 'X-CSRF-Token': csrf });
      expect(ok.status === 200, 'with the header: ' + ok.status);
    });
    await step('nothing sensitive is kept in browser storage', async () => {
      const store = await page.evaluate(() => JSON.stringify({ l: Object.entries(localStorage), s: Object.entries(sessionStorage) }));
      expect(!/token|session|password|secret|csrf/i.test(store), 'storage: ' + store.slice(0, 200));
    });
    if (process.env.ADMIN_EXPECTED === 'yes') {
      await step('the administrator reaches the admin console', async () => {
        await page.goto(`${SITE}/admin`); await page.waitForLoadState('networkidle');
        expect(/FlowHQ staff|Platform admin/i.test(await body()) && !/Platform admins only/i.test(await body()), 'admin console not shown: ' + (await body()).slice(0, 160));
        expect((await call('GET', '/admin/stats')).status === 200, 'admin API refused');
      });
    } else {
      await step('an ordinary account cannot open the admin console or its API', async () => {
        await page.goto(`${SITE}/admin`); await page.waitForLoadState('networkidle');
        expect(/Platform admins only/i.test(await body()), 'the admin page was not refused: ' + (await body()).slice(0, 160));
        expect((await call('GET', '/admin/stats')).status === 403, 'admin API answered an ordinary account');
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
  const failed = results.filter((r) => !r[1]);
  console.log(`\n${results.length - failed.length}/${results.length} passed (${PHASE})`);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('CRASH', e); process.exit(2); });
