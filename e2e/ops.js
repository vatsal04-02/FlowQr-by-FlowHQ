// FlowQR browser E2E for the FlowHQ Operations page (/admin/ops). Needs a RUNNING stack whose PLATFORM_ADMIN_EMAILS includes ADMIN_EMAIL.
//   BASE_URL=http://localhost:3100 ADMIN_EMAIL=admin@flowhq-dev.example.com node e2e/ops.js
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }
const BASE = process.env.BASE_URL || 'http://localhost:3000';
const EMAIL = process.env.ADMIN_EMAIL || 'admin@flowhq-dev.example.com';
const PASSWORD = process.env.ADMIN_PASSWORD || 'Str0ngPassw0rd!';
const results = [];
const expect = (c, m) => { if (!c) throw new Error(m); };

async function signedIn(browser, email, name) {
  const ctx = await browser.newContext({ baseURL: BASE });
  let r = await ctx.request.post('/api/v1/auth/register', { data: { email, password: PASSWORD, full_name: name } });
  if (r.status() === 409) r = await ctx.request.post('/api/v1/auth/login', { data: { email, password: PASSWORD } });
  expect(r.ok(), 'could not sign in ' + email + ' (' + r.status() + ')');
  return ctx;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  async function step(name, fn) {
    try { await fn(); results.push([name, true]); console.log('PASS', name); } catch (e) { results.push([name, false]); console.log('FAIL', name, '\n     ', String(e.message).split('\n')[0].slice(0, 300)); }
  }
  const admin = await signedIn(browser, EMAIL, 'Ops Admin');
  const page = await admin.newPage();
  const owner = await signedIn(browser, `zz-ops-owner-${Math.random().toString(36).slice(2, 8)}@example.com`, 'Plain Owner');

  await step('ops: the page lists every platform check with a plain status and what to do', async () => {
    await page.goto('/admin/ops');
    await page.getByRole('heading', { name: 'Operations' }).waitFor({ timeout: 20000 });
    await page.getByRole('list', { name: 'Platform checks' }).waitFor({ timeout: 20000 });
    for (const label of ['Database', 'Database migrations', 'Worker and scheduler', 'Database backup', 'Error reporting', 'Email (SMTP)', 'Production configuration']) await page.getByText(label, { exact: true }).first().waitFor({ timeout: 10000 });
    expect(await page.getByText(/Healthy|Needs attention|Critical|Not measured/).count() > 5, 'checks have no status words');
  });
  await step('ops: it never shows a key, DSN or password', async () => {
    const t = await page.locator('main').innerText();
    expect(!/AIza[0-9A-Za-z_-]{10}|rzp_(live|test)_[A-Za-z0-9]{6}|sk-[A-Za-z0-9]{10}|ingest\.sentry\.io|BEGIN [A-Z ]*PRIVATE/.test(t), 'a secret-looking value is on the page');
  });
  await step('ops: it is in the admin navigation and loads on a phone-width screen without sideways scroll', async () => {
    await page.getByRole('link', { name: 'Operations' }).first().waitFor();
    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto('/admin/ops');
    await page.getByRole('list', { name: 'Platform checks' }).waitFor({ timeout: 20000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'horizontal overflow at 390px');
  });
  await step('ops: an ordinary business owner is refused by the API and the page', async () => {
    expect((await owner.request.get('/api/v1/admin/ops')).status() === 403, 'owner reached /admin/ops');
    const p = await owner.newPage();
    await p.goto('/admin/ops');
    await p.getByText('Platform admins only').waitFor({ timeout: 20000 });
  });
  await step('ops: anonymous callers get 401', async () => {
    const anon = await browser.newContext({ baseURL: BASE });
    expect((await anon.request.get('/api/v1/admin/ops')).status() === 401, 'anonymous reached /admin/ops');
  });

  const passed = results.filter((r) => r[1]).length;
  console.log(`\n${passed}/${results.length} browser checks passed`);
  await browser.close();
  process.exit(passed === results.length ? 0 : 1);
})().catch((e) => { console.error('E2E FAILED', e); process.exit(1); });
