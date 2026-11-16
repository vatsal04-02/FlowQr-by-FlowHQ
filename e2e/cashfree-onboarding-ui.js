// FlowQR browser test: the onboarding "Plan and payment" step under Cashfree payment authorisation, in a real browser against the PRODUCTION BUILD of the frontend.
//
//   BASE_URL=http://localhost:3300 CHROME_PATH=... node e2e/cashfree-onboarding-ui.js
//
// WHAT THIS PROVES: what the screen does in each state the server can report (successful, failed, abandoned and delayed authorisation, and a server that refuses to finish onboarding), and that it
// believes only what the server says (it reads nothing from the address bar).
// WHAT THIS DOES NOT PROVE: every /api/v1 response here is a SCRIPTED STAND-IN for the server, and Cashfree's checkout SDK is replaced by a stub. It is NOT evidence about the backend or about Cashfree.
// The backend rules (no trial before a verified authorisation, direct API bypass refused, Growth access for every trial, transition to the selected plan only after a successful charge) are proved
// by backend/tests/test_cashfree_mandate_gate.py and test_cashfree_trial_entitlements.py against real PostgreSQL; real Cashfree behaviour is proved only by the sandbox runbook (docs/CASHFREE_SANDBOX_TEST.md).
const fs = require('fs');
const path = require('path');
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }

const BASE = process.env.BASE_URL || 'http://localhost:3300';
const OUT = process.env.SHOTS_DIR || path.join(__dirname, 'shots');
const results = [];
function expect(c, m) { if (!c) throw new Error(m); }

const PLANS = [
  { code: 'starter', name: 'Launch', price_paise: 49900, max_locations: 1, monthly_ai_generations: 400, review_generations: 200, review_replies: 200, max_staff: 3, features: ['review_sync', 'ai_replies', 'review_generation', 'qr_campaigns', 'review_analytics', 'gbp_connection', 'gbp_info'] },
  { code: 'growth', name: 'Growth', price_paise: 79900, max_locations: 1, monthly_ai_generations: 800, review_generations: 400, review_replies: 400, max_staff: 10, features: ['review_sync', 'ai_replies', 'review_generation', 'qr_campaigns', 'review_analytics', 'gbp_connection', 'gbp_info', 'gbp_posts', 'insights', 'autonomy'] },
  { code: 'pro', name: 'Scale', price_paise: 149900, max_locations: 10, monthly_ai_generations: 1600, review_generations: 800, review_replies: 800, max_staff: 50, features: ['review_sync', 'ai_replies', 'review_generation', 'qr_campaigns', 'review_analytics', 'gbp_connection', 'gbp_info', 'gbp_posts', 'insights', 'autonomy', 'multi_location'] },
].map((p) => ({ ...p, currency: 'INR', interval: 'monthly' }));
const NAME = { starter: 'Launch', growth: 'Growth', pro: 'Scale' };
const GROWTH = PLANS[1];

/** A scripted server. `onSync(state)` decides what Cashfree "said" when the app asked the server to look. */
function opts_unverified(st) { return !!st.unverified; }
function newServer(opts = {}) {
  const st = { unverified: !!opts.unverified, auth: null, status: 'incomplete', selected: null, checkouts: 0, syncs: 0, completeCalls: 0, completed: false, onSync: opts.onSync || (() => {}), refuseFinish: !!opts.refuseFinish, requests: [] };
  if (opts.authorised) Object.assign(st, { auth: 'authorized', status: 'trialing', selected: 'pro' });
  return st;
}
function subscription(st) {
  const trial = st.status === 'trialing';
  const lim = trial ? GROWTH : null;
  return {
    billing: { configured: true, mode: 'test', key_id: null, provider: 'cashfree', authorization_paise: 100, methods: ['upi', 'card'], mandate_required: true },
    status: st.status, active: trial, inactive_reason: trial ? null : 'authorization_required', plan: 'trial', plan_name: 'Free trial', price_paise: null,
    trial_ends_at: trial ? '2030-01-08T00:00:00Z' : null, trial_days_left: trial ? 7 : null, current_period_end: null, cancel_at_period_end: false, pending_plan: st.selected, grace_until: null, source: 'trial', has_razorpay_subscription: false,
    provider: 'cashfree', has_cashfree_subscription: !!st.auth, authorization_status: st.auth, billing_state: trial ? 'trialing' : st.auth ? 'authorization_pending' : 'authorization_required',
    first_charge_at: st.selected ? '2030-01-08' : null, next_charge_at: null, next_charge_amount_paise: st.selected ? PLANS.find((p) => p.code === st.selected).price_paise : null,
    mandate_required: true, trial_started_at: trial ? '2030-01-01T00:00:00Z' : null, payment_method: trial ? 'upi' : null,
    trial_entitlement: trial ? 'growth' : null, trial_entitlement_name: trial ? 'Growth' : null, selected_plan: st.selected, selected_plan_name: st.selected ? NAME[st.selected] : null,
    pending_plan_name: st.selected ? NAME[st.selected] : null,
    limits: trial ? { locations: lim.max_locations, ai_generations: lim.monthly_ai_generations, review_generations: lim.review_generations, review_replies: lim.review_replies, staff: lim.max_staff, features: lim.features } : { locations: 0, ai_generations: 0, review_generations: 0, review_replies: 0, staff: 0, features: [] },
    usage: { locations: 1, ai_generations: 0, review_generations: 0, review_replies: 0, staff: 1 }, promo: null,
  };
}

async function install(ctx, st) {
  // Cashfree's hosted checkout SDK: a stub that records the session it was given. Nothing leaves this machine.
  await ctx.route('https://sdk.cashfree.com/**', (r) => r.fulfill({ contentType: 'application/javascript', body: 'window.Cashfree = function () { return { subscriptionsCheckout: async function (o) { window.__cfSession = o.subsSessionId; return {}; } }; };' }));
  await ctx.route('**/api/v1/**', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname.replace(/^.*\/api\/v1/, '');
    const m = req.method();
    st.requests.push(`${m} ${p}`);
    const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    const tenant = { id: 't1', name: 'ZZ Test Cafe', slug: 'zz', category: 'cafe', email: null, phone: null, address: null, website: null, language: 'en', timezone: 'Asia/Kolkata', logo_url: null, brand_tone: null, ai_instructions: null, onboarding_completed: st.completed, suspended_at: null, suspension_reason: null, support_status: 'none' };
    if (m === 'GET' && p === '/auth/me') return json({ user: { id: 'u1', email: 'owner@example.com', full_name: 'Owner', phone: '9876543210', email_verified_at: opts_unverified(st) ? null : '2026-01-01T00:00:00Z' }, memberships: [{ tenant, role: 'owner' }], active_tenant_id: 't1', csrf_token: 'x', integrations: { google_configured: false, ai_configured: false, public_card_base_url: 'https://flowqr.site' } });
    if (m === 'GET' && p === '/locations') return json([{ id: 'l1', name: 'Main', address_line: null, city: 'Lucknow', state: null, postal_code: null, phone: null, review_url: 'https://g.page/r/abc/review', review_url_source: 'manual', is_active: true }]);
    if (m === 'GET' && p === '/billing/plans') return json({ plans: PLANS, trial_days: 7, billing: subscription(st).billing, card_price_paise: null, card_ordering_enabled: false, card_offers: [], card_offer_note: '' });
    if (m === 'GET' && p === '/billing/subscription') return json(subscription(st));
    if (m === 'GET' && p === '/billing/subscription/preview') { const pl = PLANS.find((x) => x.code === url.searchParams.get('plan')); return json({ plan_name: pl.name, amount_paise: pl.price_paise, first_charge_at: '2030-01-08T04:30:00Z', free_period_honoured: true, trial_days: 7, trial_starts_on_authorization: true, authorization_paise: 100, mandate_ceiling_paise: 149900 }); }
    if (m === 'POST' && p === '/billing/subscription/checkout' && st.unverified) return json({ detail: { code: 'email_not_verified', message: 'Please verify your email address first.' } }, 403);
    if (m === 'POST' && p === '/auth/resend-verification') { st.resent = (st.resent || 0) + 1; return json({ email_sent: true, detail: 'sent' }, 202); }
    if (m === 'POST' && p === '/billing/subscription/checkout') { const b = req.postDataJSON(); st.checkouts += 1; st.auth = 'initialized'; st.selected = b.plan; return json({ subscription_session_id: `session_${st.checkouts}`, environment: 'sandbox' }); }
    if (m === 'POST' && p === '/billing/subscription/sync') { st.syncs += 1; st.onSync(st); return json({ status: st.status, authorization_status: st.auth, billing_state: subscription(st).billing_state }); }
    if (m === 'POST' && p === '/tenant/complete-onboarding') {
      st.completeCalls += 1;
      if (st.status !== 'trialing' || st.refuseFinish) return json({ detail: { code: 'authorization_required', message: 'Authorise a payment method to start your free trial.' } }, 402);
      st.completed = true; return json({ ok: true });
    }
    if (m === 'GET' && p === '/review-growth/campaigns') return json([]);
    return json({ detail: 'not scripted' }, 404);
  });
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}), args: process.env.NO_SANDBOX ? ['--no-sandbox'] : [] });
  async function scenario(name, opts, fn) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 1000 } });
    const st = newServer(opts);
    await install(ctx, st);
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    try {
      await fn(page, st);
      expect(errors.length === 0, `page errors: ${errors.join(' | ')}`);
      results.push([name, true]); console.log('PASS', name);
    } catch (e) {
      results.push([name, false, e.message]); console.log('FAIL', name, '-', e.message);
      await page.screenshot({ path: path.join(OUT, `cf-fail-${name.slice(0, 20).replace(/\W+/g, '-')}.png`), fullPage: true }).catch(() => {});
    } finally { await ctx.close(); }
  }
  const text = (page) => page.locator('main').innerText();
  async function toPlanStep(page) {
    await page.goto(`${BASE}/onboarding`);
    await page.getByRole('heading', { name: 'How do you want to collect reviews?' }).waitFor({ timeout: 30000 });
    await page.getByText('Use my Google review link', { exact: true }).click();
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.getByRole('heading', { name: 'Start your 7-day free trial' }).waitFor({ timeout: 20000 });
  }
  async function authorise(page, plan) {
    await page.getByRole('radio', { name: new RegExp(`^${plan}`) }).check({ force: true }).catch(async () => { await page.locator('label', { hasText: plan }).first().click(); });
    await page.getByRole('button', { name: /Authorise payment and start free trial|Start again with/ }).click();
    const dlg = page.getByRole('dialog');
    await dlg.getByText(/refundable/i).first().waitFor({ timeout: 15000 });
    await dlg.getByRole('checkbox').check();
    await dlg.getByRole('button', { name: 'Continue to Cashfree' }).click();
    await page.waitForFunction(() => !!window.__cfSession, null, { timeout: 15000 });
  }

  await scenario('successful authorisation: no trial until the server confirms, then Growth access whichever plan was picked', {
    onSync: (st) => { if (st.auth === 'initialized') { st.auth = 'authorized'; st.status = 'trialing'; } },
  }, async (page, st) => {
    await toPlanStep(page);
    const t = await text(page);
    expect(PLANS.every((p) => t.includes(p.name)), 'a plan is missing');
    expect((t.match(/7 days free/g) || []).length === 3, 'every plan must show the 7-day trial: ' + t);
    expect(/Authorise payment and start free trial/.test(await page.locator('main').innerText()), 'authorisation button missing');
    expect(await page.getByRole('button', { name: 'Start my free trial' }).count() === 0, 'a way around the authorisation exists');
    await page.screenshot({ path: path.join(OUT, 'cf-ob-1-plan.png'), fullPage: true });
    await authorise(page, 'Scale');
    expect(st.checkouts === 1 && st.selected === 'pro', 'checkout was not created for Scale');
    expect(!/Your free trial has started/.test(await text(page)), 'the trial must not start when checkout merely opens');
    await page.goto(`${BASE}/onboarding?checkout=return`);  // Cashfree sends the customer back
    await page.getByRole('heading', { name: 'Your free trial has started' }).waitFor({ timeout: 20000 });
    const done = await text(page);
    expect(st.syncs >= 1, 'the page did not ask the server what happened');
    expect(/every Growth feature/.test(done) && /Your plan after the trial/.test(done) && /Scale/.test(done), 'trial/selected-plan wording missing: ' + done);
    expect(!/Scale features|Scale plan during/i.test(done), 'must not promise Scale features in the trial');
    await page.screenshot({ path: path.join(OUT, 'cf-ob-1-started.png'), fullPage: true });
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.getByRole('heading', { name: 'You are all set' }).waitFor({ timeout: 20000 });
    await page.getByRole('button', { name: /Open my dashboard/ }).click();
    await page.waitForURL(/\/overview/, { timeout: 30000 });
    expect(st.completeCalls === 1 && st.completed, 'onboarding was not finished through the server');
  });

  await scenario('failed authorisation: no trial, nothing charged, and the customer can try again', {
    onSync: (st) => { if (st.auth === 'initialized') st.auth = 'expired'; },
  }, async (page, st) => {
    await toPlanStep(page);
    await authorise(page, 'Launch');
    await page.goto(`${BASE}/onboarding?checkout=return`);
    await page.getByText("The authorisation didn't complete").waitFor({ timeout: 20000 });
    expect(st.status === 'incomplete' && !/free trial has started/i.test(await text(page)), 'a failed authorisation must not start the trial');
    await page.screenshot({ path: path.join(OUT, 'cf-ob-2-failed.png'), fullPage: true });
    const before = st.checkouts;
    st.onSync = () => {};
    await authorise(page, 'Growth');
    expect(st.checkouts === before + 1, 'retry did not create a new checkout');
  });

  await scenario('abandoned authorisation: the customer comes back without finishing; no trial and a clear way to continue', {}, async (page, st) => {
    await toPlanStep(page);
    await authorise(page, 'Growth');
    await page.goto(`${BASE}/onboarding?checkout=return`);  // the server (Cashfree) still says nothing was authorised
    await page.getByText("We haven't received your authorisation yet").waitFor({ timeout: 20000 });
    expect(st.status === 'incomplete', 'the trial must not start');
    await page.screenshot({ path: path.join(OUT, 'cf-ob-3-abandoned.png'), fullPage: true });
    expect(await page.getByRole('button', { name: 'Check again' }).count() === 1 && await page.getByRole('button', { name: /Start again with Growth/ }).count() === 1, 'check-again / start-again actions missing');
    await page.reload();  // closing and reopening the tab loses nothing: the server still says where they are
    await page.getByRole('heading', { name: 'Start your 7-day free trial' }).waitFor({ timeout: 20000 });
    await page.getByText("We haven't received your authorisation yet").waitFor({ timeout: 20000 });
  });

  await scenario('delayed authorisation: the bank approves later; the page keeps asking the server and starts the trial only then', {
    onSync: (st) => { if (st.auth === 'initialized') st.auth = 'bank_pending'; else if (st.auth === 'bank_pending' && st.syncs >= 3) { st.auth = 'authorized'; st.status = 'trialing'; } },
  }, async (page, st) => {
    await toPlanStep(page);
    await authorise(page, 'Growth');
    await page.goto(`${BASE}/onboarding?checkout=return`);
    await page.getByText('Your bank is approving the authorisation').waitFor({ timeout: 20000 });
    expect(st.status === 'incomplete' && !/free trial has started/i.test(await text(page)), 'a pending bank approval must not start the trial');
    await page.screenshot({ path: path.join(OUT, 'cf-ob-4-delayed.png'), fullPage: true });
    await page.getByRole('heading', { name: 'Your free trial has started' }).waitFor({ timeout: 40000 });  // polls every 5 seconds
    expect(st.syncs >= 3, 'the page did not keep asking');
  });

  await scenario('the server refuses to finish onboarding: the customer is sent back to the payment step with the reason', { authorised: true, refuseFinish: true }, async (page, st) => {
    await page.goto(`${BASE}/onboarding?checkout=return`);
    await page.getByRole('heading', { name: 'Your free trial has started' }).waitFor({ timeout: 30000 });
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.getByRole('heading', { name: 'You are all set' }).waitFor({ timeout: 20000 });
    await page.getByRole('button', { name: /Open my dashboard/ }).click();
    await page.getByText('Authorise a payment method to start your free trial.').waitFor({ timeout: 20000 });
    expect(!/\/overview/.test(page.url()), 'the app opened although the server refused');
    expect(st.completeCalls === 1 && !st.completed, 'the refusal was not honoured');
    await page.getByRole('heading', { name: /free trial/ }).first().waitFor({ timeout: 20000 });
  });

  await scenario('403 email_not_verified: the reason is visible next to the button in a short window, with a resend action; nothing starts', { unverified: true }, async (page, st) => {
    await page.setViewportSize({ width: 1280, height: 640 });
    await toPlanStep(page);
    expect(await page.getByText('Verify your email to authorise a payment').count() === 1, 'the plan step does not warn about the unverified email');
    await page.getByRole('button', { name: /Authorise payment and start free trial/ }).click();
    const dlg = page.getByRole('dialog'); await dlg.getByRole('checkbox').check(); await dlg.getByRole('button', { name: 'Continue to Cashfree' }).click();
    const msg = page.getByText('Please verify your email address first.');
    await msg.first().waitFor({ timeout: 15000 });
    const inView = await msg.first().evaluate((el) => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight; });
    expect(inView, 'the 403 message is not visible in the window');
    expect(await page.evaluate(() => !!window.__cfSession) === false, 'Cashfree must not open for an unverified owner');
    await dlg.getByRole('button', { name: 'Resend verification email' }).click();
    await page.waitForFunction(() => document.body.innerText.includes('Verification email sent'), null, { timeout: 10000 });
    expect(st.resent === 1 && st.status === 'incomplete', 'resend was not requested or the trial changed');
    await page.screenshot({ path: path.join(OUT, 'cf-ob-6-unverified.png') });
  });

  await browser.close();
  const bad = results.filter((r) => !r[1]);
  console.log(`\n${results.length - bad.length}/${results.length} scenarios passed`);
  if (bad.length) { for (const b of bad) console.log('FAILED:', b[0], '-', b[2]); process.exit(1); }
})().catch((e) => { console.error(e); process.exit(1); });
