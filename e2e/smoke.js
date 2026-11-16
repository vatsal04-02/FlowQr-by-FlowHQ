// FlowQR browser smoke test (Playwright). See README "End-to-end smoke test". Not a substitute for unit tests.
const { chromium } = require('playwright');
const OUT = process.env.SHOTS_DIR || './e2e/shots';
const BASE = process.env.BASE_URL || 'http://localhost:3000';
const rnd = Math.random().toString(36).slice(2, 8);
const log = (...a) => console.log(...a);

async function apiCtx(browser, email, name) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: !!process.env.IGNORE_HTTPS_ERRORS, baseURL: BASE });
  const r = await ctx.request.post('/api/v1/auth/register', { data: { email, password: process.env.ADMIN_PASSWORD || 'Str0ngPassw0rd!', full_name: name } });
  if (r.status() === 409) {
    const l = await ctx.request.post('/api/v1/auth/login', { data: { email, password: process.env.ADMIN_PASSWORD || 'Str0ngPassw0rd!' } });
    return { ctx, csrf: (await l.json()).csrf_token };
  }
  return { ctx, csrf: (await r.json()).csrf_token };
}

(async () => {
  const HOST_RULES = process.env.HOST_RULES; // e.g. 'MAP *.flowqr-staging.dev 127.0.0.1' (staging with local TLS)
  const browser = await chromium.launch(HOST_RULES ? { args: [`--host-resolver-rules=${HOST_RULES}`] } : {});
  const errors = [];

  // ---- Platform admin creates a batch ----
  const admin = await apiCtx(browser, process.env.ADMIN_EMAIL || 'admin@flowhq-dev.example.com', 'FlowHQ Admin');
  const H = (c) => ({ 'X-CSRF-Token': c });
  let r = await admin.ctx.request.post('/api/v1/admin/batches', { data: { name: `E2E batch ${rnd}`, quantity: 3 }, headers: H(admin.csrf) });
  log('batch', r.status());
  const batch = await r.json();

  // ---- Business owner goes through the real UI ----
  const ctx = await browser.newContext({ ignoreHTTPSErrors: !!process.env.IGNORE_HTTPS_ERRORS, baseURL: BASE, viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('response', (r) => { if (r.status() >= 400 && r.status() !== 401) console.log('HTTP', r.status(), r.url()); });
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto('/'); await page.screenshot({ path: `${OUT}/01-landing.png`, fullPage: true });
  await page.goto('/register');
  await page.getByLabel('Your name').fill('E2E Demo Owner');
  await page.getByLabel('Work email').fill(`owner-${rnd}@example.com`);
  await page.getByLabel('Password').fill('weak');
  await page.getByLabel('Password').blur();
  await page.screenshot({ path: `${OUT}/02-register-inline-error.png` });
  await page.getByLabel('Password').fill('Str0ngPassw0rd!');
  await page.getByRole('button', { name: 'Create account' }).click();
  await page.waitForURL('**/onboarding');

  await page.getByLabel('Business name').fill('E2E Demo Physiotherapy');
  await page.getByLabel('Phone').fill('98765 43210');
  await page.screenshot({ path: `${OUT}/03-onboarding-business.png`, fullPage: true });
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByLabel('Location name').fill('Gomti Nagar branch');
  await page.getByLabel('City').fill('Lucknow');
  await page.getByLabel('Google review link (optional)').fill('https://evil.example.com/x');
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.screenshot({ path: `${OUT}/04-onboarding-location-error.png`, fullPage: true });
  await page.getByLabel('Google review link (optional)').fill('https://g.page/r/CdemoABC123/review');
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByText('How do you want to collect reviews?').waitFor();
  await page.screenshot({ path: `${OUT}/05-onboarding-google.png`, fullPage: true });
  await page.getByRole('button', { name: /Use my Google review link/ }).click();
  await page.waitForURL('**/overview');
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/06-dashboard-desktop.png`, fullPage: true });

  // ---- Admin assigns a card to this business ----
  const tenant = await (await ctx.request.get('/api/v1/tenant')).json();
  const locs = await (await ctx.request.get('/api/v1/locations')).json();
  const cards = (await (await admin.ctx.request.get(`/api/v1/admin/cards?batch_id=${batch.id}`)).json()).items;
  r = await admin.ctx.request.post(`/api/v1/admin/cards/${cards[0].id}/assign`, { data: { tenant_id: tenant.id, location_id: locs[0].id, label: 'Reception desk' }, headers: H(admin.csrf) });
  log('assign', r.status());
  const token = cards[0].public_token; log('card url', cards[0].url);

  // ---- Customer on a phone ----
  const phone = await browser.newContext({ ignoreHTTPSErrors: !!process.env.IGNORE_HTTPS_ERRORS, baseURL: BASE, viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1' });
  const m = await phone.newPage();
  m.on('pageerror', (e) => errors.push('mobile pageerror: ' + e.message));
  await m.goto(`/c/${token}`);
  await m.getByText('Share your experience').waitFor();
  await m.screenshot({ path: `${OUT}/07-public-mobile-initial.png`, fullPage: true });
  await m.getByLabel('Your experience').fill('doctor was very kind, my back pain is much better after 3 sessions');
  await m.route('**/assist', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ suggestion: 'The doctor was very kind, and my back pain is much better after three sessions.', language: 'en', ai_assisted: true, disclaimer: 'AI-assisted suggestion based on what you wrote. Edit it so it\'s truly your own words before posting.' }) }));
  await m.screenshot({ path: `${OUT}/08-public-mobile-typed.png`, fullPage: true });
  // AI isn't configured on this server => honest message is shown (no Improve button)
  const aiBtn = await m.getByRole('button', { name: 'Improve my wording' }).count();
  log('AI button present (expected 0 without GEMINI_API_KEY):', aiBtn);
  await m.getByRole('button', { name: 'Copy review' }).click();
  await m.getByText('Copied!').waitFor();
  const [popup] = await Promise.all([m.waitForEvent('popup'), m.getByRole('link', { name: /Continue to Google/ }).click()]);
  log('opened:', popup.url());
  await m.screenshot({ path: `${OUT}/09-public-mobile-copied.png`, fullPage: true });
  const bad = await phone.newPage(); await bad.goto('/c/' + 'x'.repeat(30)); await bad.getByText('Card not found').waitFor();
  await bad.screenshot({ path: `${OUT}/10-public-notfound.png` });

  // ---- Signed-in pages ----
  for (const [name, path] of [['cards', '/cards'], ['analytics', '/cards/analytics'], ['locations', '/locations'], ['google', '/google'], ['reviews', '/reviews'], ['settings', '/settings'], ['staff', '/staff']]) {
    await page.goto(path); await page.waitForTimeout(900);
    await page.screenshot({ path: `${OUT}/20-${name}.png`, fullPage: true });
  }
  await page.goto('/cards'); await page.getByRole('button', { name: /QR & NFC/ }).click(); await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/21-cards-qr-modal.png` });
  await page.keyboard.press('Escape');

  // mobile dashboard
  const mctx = await browser.newContext({ ignoreHTTPSErrors: !!process.env.IGNORE_HTTPS_ERRORS, baseURL: BASE, viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  await mctx.addCookies(await ctx.cookies());
  const md = await mctx.newPage(); await md.goto('/dashboard'); await md.waitForTimeout(1000);
  await md.screenshot({ path: `${OUT}/22-dashboard-mobile.png`, fullPage: false });
  await md.getByRole('button', { name: 'Account menu' }).click(); await md.waitForTimeout(400);
  await md.screenshot({ path: `${OUT}/23-mobile-menu.png` });

  // admin UI
  const actx = await browser.newContext({ ignoreHTTPSErrors: !!process.env.IGNORE_HTTPS_ERRORS, baseURL: BASE, viewport: { width: 1280, height: 800 } });
  await actx.addCookies(await admin.ctx.cookies());
  const ap = await actx.newPage(); ap.on('pageerror', (e) => errors.push('admin pageerror: ' + e.message));
  await ap.goto('/admin/cards'); await ap.waitForTimeout(1200);
  await ap.screenshot({ path: `${OUT}/30-admin-cards.png`, fullPage: true });
  await ap.goto('/admin'); await ap.waitForTimeout(1000);
  await ap.screenshot({ path: `${OUT}/31-admin-home.png`, fullPage: true });


  // ================= v2: verification, billing, analytics, profile, suspension, admin console =================
  const fs = require('fs');
  const ownerEmail = `owner-${rnd}@example.com`;
  const logTxt = fs.existsSync(process.env.API_LOG || '/tmp/uvicorn.log') ? fs.readFileSync(process.env.API_LOG || '/tmp/uvicorn.log', 'utf8') : '';
  let mailTok = null;
  if (process.env.MAILPIT_URL) {
    const list = await (await fetch(`${process.env.MAILPIT_URL}/api/v1/messages?limit=200`)).json();
    const hit = list.messages.find((m) => m.To.some((t) => t.Address === ownerEmail) && m.Subject.includes('Verify'));
    if (hit) { const body = (await (await fetch(`${process.env.MAILPIT_URL}/api/v1/message/${hit.ID}`)).json()).Text; mailTok = body.match(/token=([\w-]+)/)[1]; }
  }
  const m1 = mailTok ? [null, mailTok] : [...logTxt.matchAll(new RegExp(`to=${ownerEmail.replace('.', '\\.')}[\\s\\S]*?verify-email\\?token=([\\w-]+)`, 'g'))].pop();
  if (m1) {
    await page.goto('/dashboard'); await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/40-unverified-banner.png` });
    await page.goto(`/verify-email?token=${m1[1]}`); await page.getByText('Email verified').waitFor();
    log('email verified via UI link');
  } else log('SKIP verification step: no dev email found in API_LOG');

  await page.goto('/pricing'); await page.getByText('Simple pricing in rupees').waitFor();
  await page.getByText('₹399').first().waitFor(); await page.getByText('₹799').first().waitFor(); await page.getByText('₹1,499').first().waitFor();
  await page.screenshot({ path: `${OUT}/41-pricing.png`, fullPage: true });

  await page.goto('/subscription'); await page.getByText('Configuration pending').first().waitFor().catch(() => {});
  await page.waitForTimeout(800); await page.screenshot({ path: `${OUT}/42-subscription.png`, fullPage: true });
  await page.goto('/payments'); await page.waitForTimeout(800); await page.screenshot({ path: `${OUT}/43-payments.png`, fullPage: true });
  await page.goto('/analytics'); await page.waitForTimeout(1200); await page.screenshot({ path: `${OUT}/44-analytics.png`, fullPage: true });
  await page.goto('/profile'); await page.waitForTimeout(800); await page.screenshot({ path: `${OUT}/45-profile-not-connected.png`, fullPage: true });

  // mobile pricing + subscription
  const mp = await mctx.newPage(); await mp.goto('/subscription'); await mp.waitForTimeout(1000);
  const sw = await mp.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
  log('mobile /subscription scrollWidth vs viewport:', sw.join(' / ')); if (sw[0] > sw[1]) errors.push('horizontal overflow on mobile /subscription');
  await mp.screenshot({ path: `${OUT}/46-subscription-mobile.png`, fullPage: true });

  // suspension: admin suspends the business, owner sees the suspended screen, then restore
  r = await admin.ctx.request.post(`/api/v1/admin/tenants/${tenant.id}/suspend`, { data: { reason: 'E2E suspension test' }, headers: H(admin.csrf) }); log('suspend', r.status());
  await page.goto('/dashboard'); await page.getByText('This account is suspended').waitFor();
  await page.screenshot({ path: `${OUT}/47-suspended.png` });
  const pub = await phone.newPage(); await pub.goto(`/c/${token}`); await pub.getByText('This card is no longer active').waitFor(); log('public card shows inactive while suspended');
  r = await admin.ctx.request.post(`/api/v1/admin/tenants/${tenant.id}/unsuspend`, { headers: H(admin.csrf) }); log('unsuspend', r.status());
  await page.goto('/dashboard'); await page.getByText(/^Good (morning|afternoon|evening)/).waitFor();

  // admin console (separate shell)
  await ap.goto('/admin/customers'); await ap.getByText('Customers').first().waitFor(); await ap.waitForTimeout(800);
  await ap.screenshot({ path: `${OUT}/50-admin-customers.png`, fullPage: true });
  await ap.goto(`/admin/customers/${tenant.id}`); await ap.getByText('Subscription').first().waitFor(); await ap.waitForTimeout(600);
  await ap.screenshot({ path: `${OUT}/51-admin-customer-detail.png`, fullPage: true });
  await ap.goto('/admin/billing'); await ap.waitForTimeout(900); await ap.screenshot({ path: `${OUT}/52-admin-billing.png`, fullPage: true });
  await ap.goto('/admin/audit'); await ap.waitForTimeout(900); await ap.screenshot({ path: `${OUT}/53-admin-audit.png`, fullPage: true });
  // an ordinary business user must not get admin data
  const denied = await ctx.request.get('/api/v1/admin/stats'); log('business user -> /admin/stats status', denied.status()); if (denied.status() !== 403) errors.push('business user reached admin API');
  const dp = await ctx.newPage(); await dp.goto('/admin'); await dp.getByText('Platform admins only').waitFor(); log('business user sees admin denial page');

  log('ERRORS:', JSON.stringify(errors, null, 1));
  await browser.close();
})().catch((e) => { console.error('E2E FAILED', e); process.exit(1); });
