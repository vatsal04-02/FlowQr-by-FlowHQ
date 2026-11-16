// FlowQR browser E2E for Phase 2: the commercial plans, separate allowances, the free card month, plan gating, the getting-started checklist, the Google-permission explanation,
// and the platform admin's Plans and limits, Release status and Finance pages. Drives the real UI in Chromium against a RUNNING stack.
//
//   PLATFORM_ADMIN_EMAILS=zz-p2-admin@example.com docker compose -p flowqr-demo -f docker-compose.yml -f e2e/compose.demo.yml --project-directory . up -d --build
//   COMPOSE_PROJECT_NAME=flowqr-demo BASE_URL=http://localhost:3100 ADMIN_EMAIL=zz-p2-admin@example.com node e2e/phase2-commercial.js
//
// WHAT THIS DOES AND DOES NOT PROVE
//  * It exercises the screens and the server rules (plan gating, which numbers are shown, what is marked missing). The Google connection, the review, the free card month and the
//    plan changes are SEEDED database rows. No Razorpay, Google or Places call is made, so this proves nothing about those services, and no payment is taken.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }

const BASE = process.env.BASE_URL || 'http://localhost:3000';
const ROOT = path.resolve(__dirname, '..');
const OUT = process.env.SHOTS_DIR || path.join(ROOT, 'e2e', 'shots');
const TAG = Math.random().toString(36).slice(2, 8);
const ADMIN = process.env.ADMIN_EMAIL || 'zz-p2-admin@example.com';
const OWNER = `zz-e2e-p2-${TAG}@example.com`, OWNER2 = `zz-e2e-p2b-${TAG}@example.com`;
const PW = 'Str0ngPassw0rd!' + TAG;
const ADMIN_PW = process.env.ADMIN_PASSWORD || 'Str0ngPassw0rd!P2admin';  // fixed, so a second run can sign the same admin in
const NAME = `ZZ-E2E-P2-${TAG}`, NAME2 = `ZZ-E2E-P2B-${TAG}`;
const results = [];
process.on('unhandledRejection', (e) => { if (!/Target page, context or browser has been closed/.test(String(e && e.message))) { console.error(e); process.exitCode = 1; } });

const docker = (args, input) => execFileSync('docker', ['compose', 'exec', '-T', ...args], { cwd: ROOT, input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
const seed = (code) => docker(['api', 'sh', '-c', 'cd /srv && PYTHONPATH=/srv python -'], code).trim();
const sql = (q) => docker(['db', 'psql', '-U', 'flowqr', '-d', 'flowqr', '-At', '-v', 'ON_ERROR_STOP=1'], `BEGIN; SELECT set_config('app.bypass_rls','on',true); SELECT set_config('app.history_purge','on',true); ${q} COMMIT;`).trim();
function expect(cond, msg) { if (!cond) throw new Error(msg); }

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  const ctx = await browser.newContext({ baseURL: BASE, viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const pageErrors = []; const httpErrors = [];
  page.on('pageerror', (e) => pageErrors.push(e.message));
  page.on('response', (r) => { if (r.status() >= 500) httpErrors.push(`${r.status()} ${r.url()}`); });
  async function step(name, fn) {
    try { await fn(); results.push([name, true]); console.log('PASS', name); }
    catch (e) {
      results.push([name, false, String(e.message).split('\n')[0].slice(0, 300)]);
      console.log('FAIL', name, '\n     ', String(e.message).split('\n')[0].slice(0, 300));
      await page.screenshot({ path: path.join(OUT, `fail-p2-${results.length}.png`), fullPage: true }).catch(() => {});
    }
  }
  const toast = (text) => page.getByRole('status').filter({ hasText: text }).first().waitFor({ timeout: 20000 });
  const noSideways = async (u) => { await page.goto(u); await page.locator('h1').first().waitFor({ timeout: 30000 }); await page.waitForLoadState('networkidle'); const o = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth); expect(o <= 1, `${u} scrolls sideways by ${o}px`); };

  // ------------------------------------------------------------------ setup: two businesses, seeded rows
  let csrf, tenant, ready = false;
  const H = () => ({ 'X-CSRF-Token': csrf });
  try {
    let r = await ctx.request.post('/api/v1/auth/register', { data: { email: OWNER, password: PW, full_name: 'ZZ P2 Owner' } });
    expect(r.status() === 201, `register ${r.status()} ${await r.text()}`);
    csrf = (await r.json()).csrf_token;
    tenant = await (await ctx.request.post('/api/v1/tenants', { data: { name: NAME, category: 'Physiotherapy clinic', language: 'en' }, headers: H() })).json();
    const loc = await (await ctx.request.post('/api/v1/locations', { data: { name: 'P2 Main', city: 'Lucknow', review_url: 'https://g.page/r/ABC123/review' }, headers: H() })).json();
    await ctx.request.post('/api/v1/tenant/complete-onboarding', { headers: H() });
    seed(`
import uuid
from datetime import timedelta
from sqlalchemy import text
from app.core.db import system_session
from app.models import GoogleConnection, GoogleConnectionStatus, GoogleLocation, Review
from app.models.base import utcnow
db = system_session()
db.execute(text("UPDATE users SET email_verified_at = now() WHERE email IN ('${OWNER}', '${OWNER2}')"))
tid, lid = uuid.UUID("${tenant.id}"), uuid.UUID("${loc.id}")
c = GoogleConnection(tenant_id=tid, google_email="seeded-p2@example.com", google_sub="seeded-p2-${TAG}", status=GoogleConnectionStatus.active, api_access="approved", connected_at=utcnow())
db.add(c); db.flush()
g = GoogleLocation(tenant_id=tid, connection_id=c.id, location_id=lid, google_account_name="accounts/1", google_location_name="locations/1", title="P2 Main (Google)", selected=True, last_synced_at=utcnow(), last_sync_status="ok")
db.add(g); db.flush()
db.add(Review(tenant_id=tid, location_id=lid, google_location_id=g.id, external_id="seed-p2-1", rating=5, text="Lovely and friendly staff", reviewer_name="Asha", review_created_at=utcnow() - timedelta(days=3), first_seen_at=utcnow()))
db.commit()
`);
    ready = true;
  } catch (e) { console.log('SETUP FAILED:', e.message); results.push(['setup', false, e.message]); }

  if (ready) {
    await step('the plans are the confirmed ones, with the two allowances as separate rows', async () => {
      await page.goto('/settings/billing');
      await page.getByRole('heading', { level: 1, name: 'Subscription' }).waitFor({ timeout: 30000 });
      const table = page.locator('table').first();
      await table.waitFor({ timeout: 20000 });
      const head = await table.locator('thead').innerText();
      for (const t of ['Starter', 'Growth', 'Pro', '₹499', '₹799', '₹1,499']) expect(head.includes(t), `plan table is missing ${t}: ${head.slice(0, 200)}`);
      expect(!/Essential|Multi-location\s*₹/.test(head), 'a retired plan is still offered');
      const body = await table.locator('tbody').innerText();
      expect(/AI review generations \/ month\s*200\s*400\s*800/.test(body.replace(/\n/g, ' ').replace(/\t/g, ' ')) || (body.includes('AI review generations / month') && body.includes('AI review replies / month')), 'the two separate allowance rows are missing');
      await page.getByText('AI review generations this month').waitFor();
      await page.getByText('AI review replies this month').waitFor();
      await page.screenshot({ path: path.join(OUT, 'p2-1-billing.png'), fullPage: true });
    });

    await step('a free Growth month from a card purchase is shown as free, with the day it ends, and says nothing is charged', async () => {
      sql(`INSERT INTO promotional_grants (id, tenant_id, kind, plan, status, starts_at, ends_at, created_at, note) VALUES (gen_random_uuid(), '${tenant.id}', 'card_purchase', 'growth', 'active', now(), now() + interval '30 days', now(), 'e2e seeded');`);
      await page.reload();
      const a = page.getByText(/Free Growth until/);
      await a.waitFor({ timeout: 20000 });
      const t = await page.locator('main').innerText();
      expect(/nothing is charged/i.test(t) && /only charged for a plan you pick yourself/i.test(t), 'the free month does not say that nothing is charged');
    });

    await step('subscription history lists what happened, in plain words', async () => {
      await page.getByRole('heading', { name: 'Subscription history' }).waitFor({ timeout: 20000 });
      const t = await page.locator('main').innerText();
      expect(t.includes('Free trial started'), 'trial start is not in the history');
    });

    await step('Starter: the autonomy area is closed with a message that names what to upgrade for', async () => {
      sql(`UPDATE subscriptions SET plan = 'starter', status = 'active', source = 'manual', features = (SELECT features FROM billing_plans WHERE code = 'starter') WHERE tenant_id = '${tenant.id}'; UPDATE promotional_grants SET status = 'ended' WHERE tenant_id = '${tenant.id}';`);
      await page.goto('/settings/ai/autonomy');
      await page.getByText(/Autonomous SEO maintenance isn't included in your current plan/).waitFor({ timeout: 30000 });
      await page.screenshot({ path: path.join(OUT, 'p2-2-starter-gate.png'), fullPage: true });
      await page.goto('/seo/rank');
      await page.getByText(/Keyword tracking isn't included|Google connection|isn't included in your current plan/).first().waitFor({ timeout: 30000 });
      sql(`UPDATE subscriptions SET plan = 'growth', features = (SELECT features FROM billing_plans WHERE code = 'growth') WHERE tenant_id = '${tenant.id}';`);
    });

    await step('getting started lists what is really left, marks optional steps, and is readable on a phone', async () => {
      await page.goto('/overview');
      const panel = page.getByRole('region', { name: 'Getting started' });
      await panel.waitFor({ timeout: 30000 });
      const t = await panel.innerText();
      expect(/essential steps done/.test(t) && /Create your first review campaign/.test(t), 'the checklist is missing steps: ' + t.slice(0, 200));
      expect(/Assign a physical card\s*optional/.test(t.replace(/\n/g, ' ')), 'an open optional step is not marked optional');
      expect(/Connect your Google Business Profile/.test(t), 'the connected Google step is missing');  // seeded as connected, so it is shown as done (struck through), not as optional
      await page.setViewportSize({ width: 390, height: 844 });
      await noSideways('/overview');
      await page.screenshot({ path: path.join(OUT, 'p2-3-getting-started-mobile.png'), fullPage: true });
      await page.setViewportSize({ width: 1280, height: 900 });
    });

    await step('onboarding explains in plain language what connecting Google allows, and offers a path without a profile', async () => {
      const ctx2 = await browser.newContext({ baseURL: BASE });
      let r = await ctx2.request.post('/api/v1/auth/register', { data: { email: OWNER2, password: PW, full_name: 'ZZ P2 Owner B' } });
      expect(r.status() === 201, 'register 2 ' + r.status());
      const c2 = (await r.json()).csrf_token;
      await ctx2.request.post('/api/v1/tenants', { data: { name: NAME2, category: 'Dental clinic', language: 'en' }, headers: { 'X-CSRF-Token': c2 } });
      await ctx2.request.post('/api/v1/locations', { data: { name: 'B Main', city: 'Lucknow' }, headers: { 'X-CSRF-Token': c2 } });
      const p2 = await ctx2.newPage();
      await p2.goto('/onboarding');
      await p2.getByRole('heading', { name: 'How do you want to collect reviews?' }).waitFor({ timeout: 30000 });
      await p2.getByText('What does connecting Google allow?').click();
      const t = await p2.locator('main').innerText();
      expect(/only after you .* approve that exact change/.test(t.replace(/\n/g, ' ')) && /Signing in with Google is separate/.test(t) && /No Google Business Profile yet\?/.test(t), 'the permission explanation is incomplete');
      await p2.screenshot({ path: path.join(OUT, 'p2-4-onboarding-google.png'), fullPage: true });
      await ctx2.close();
    });

    await step('a business owner cannot open the platform admin pages', async () => {
      for (const u of ['/admin/finance', '/admin/plans']) { await page.goto(u); await page.getByText('Platform admins only').waitFor({ timeout: 30000 }); }
    });

    // ------------------------------------------------------------------ platform admin
    const actx = await browser.newContext({ baseURL: BASE, viewport: { width: 1280, height: 900 } });
    const ap = await actx.newPage();
    let adminOk = false;
    try {
      let r = await actx.request.post('/api/v1/auth/register', { data: { email: ADMIN, password: ADMIN_PW, full_name: 'ZZ P2 Admin' } });
      if (r.status() === 409) r = await actx.request.post('/api/v1/auth/login', { data: { email: ADMIN, password: ADMIN_PW } });
      if (r.status() === 201 || r.status() === 200) {
        // Administrator rights are granted only when the mailbox is verified (Phase 2 security fix). This stack has no mail, so the verification is seeded here, then the admin signs in again.
        sql(`UPDATE users SET email_verified_at = now(), is_platform_admin = true WHERE email = '${ADMIN}';`);
        r = await actx.request.post('/api/v1/auth/login', { data: { email: ADMIN, password: ADMIN_PW } });
      }
      adminOk = r.ok() && (await (await actx.request.get('/api/v1/auth/me')).json()).user?.is_platform_admin === true;
    } catch { adminOk = false; }
    if (!adminOk) {
      results.push(['platform admin sign-in (the stack must be started with PLATFORM_ADMIN_EMAILS including ADMIN_EMAIL)', false, 'not a platform admin']);
      console.log('FAIL platform admin sign-in: ADMIN_EMAIL is not a platform admin on this stack; the admin steps were not run');
    } else {
      const astep = async (name, fn) => { try { await fn(); results.push([name, true]); console.log('PASS', name); } catch (e) { results.push([name, false, String(e.message).split('\n')[0]]); console.log('FAIL', name, '\n     ', String(e.message).split('\n')[0].slice(0, 300)); await ap.screenshot({ path: path.join(OUT, `fail-p2-admin-${results.length}.png`), fullPage: true }).catch(() => {}); } };
      await astep('admin: Plans and limits shows the confirmed plans, the unapproved map allowances as pending, and the release ladder with nothing live passed', async () => {
        await ap.goto('/admin/plans');
        await ap.getByRole('heading', { level: 1, name: 'Plans and limits' }).waitFor({ timeout: 30000 });
        await ap.getByText(/Waiting for an owner decision/).waitFor();
        const t = (await ap.locator('main').innerText()).replace(/\n/g, ' ');
        for (const s of ['Starter', 'Growth', 'Pro', '₹499', '₹799', '₹1,499', 'Growth includes one location']) expect(t.includes(s), `missing ${s}`);
        const gates = await ap.getByText('Release status').locator('xpath=ancestor::*[contains(@class,"panel") or contains(@class,"card")][1]').innerText().catch(() => t);
        expect(/Development Complete - External Validation Pending/.test(t), 'overall status is not the honest one');
        expect((t.match(/not done/g) || []).length >= 4, 'the live rungs are not all shown as not done');
        await ap.screenshot({ path: path.join(OUT, 'p2-5-admin-plans.png'), fullPage: true });
      });
      await astep('admin: approving map allowances needs all three numbers and a reason, then clears the warning; clearing them turns maps off again', async () => {
        const growth = ap.locator('section, div').filter({ hasText: /Growth · ₹799/ }).locator('form').first();
        await growth.waitFor({ timeout: 20000 });
        const inputs = growth.getByRole('textbox');
        await inputs.nth(0).fill('3'); await inputs.nth(1).fill('25'); await inputs.nth(2).fill('');
        await growth.getByLabel(/Why/).fill('e2e: partial');
        await growth.getByRole('button', { name: 'Save' }).click();
        await toastIn(ap, /three together|Set max_grids/i);
        await inputs.nth(2).fill('400');
        await growth.getByLabel(/Why/).fill('e2e: approved for the test');
        await growth.getByRole('button', { name: 'Save' }).click();
        await toastIn(ap, /Saved/);
        await ap.reload();
        await ap.getByRole('heading', { level: 1, name: 'Plans and limits' }).waitFor();
        const g2 = ap.locator('section, div').filter({ hasText: /Growth · ₹799/ }).locator('form').first();
        const v = await g2.getByRole('textbox').nth(2).inputValue();
        expect(v === '400', 'the saved allowance did not persist');
        const i2 = g2.getByRole('textbox');
        await i2.nth(0).fill(''); await i2.nth(1).fill(''); await i2.nth(2).fill('');
        await g2.getByLabel(/Why/).fill('e2e: reset');
        await g2.getByRole('button', { name: 'Save' }).click();
        await toastIn(ap, /Saved/);
      });
      await astep('admin: Finance and usage labels every figure actual, estimated or missing, never treats a missing cost as zero, and keeps card revenue out of MRR', async () => {
        await ap.goto('/admin/finance');
        await ap.getByRole('heading', { level: 1, name: 'Finance and usage' }).waitFor({ timeout: 30000 });
        await ap.getByText('MRR (paid subscriptions)').waitFor({ timeout: 20000 });
        const t = (await ap.locator('main').innerText()).replace(/\n/g, ' ');
        expect(/Card revenue \(one-time\)/.test(t) && /Never part of MRR or ARR/.test(t), 'card revenue is not separated from MRR');
        expect(/missing/.test(t) && /Needs: /.test(t), 'nothing is marked missing although no cost inputs are configured');
        expect(/No margin can be shown yet/.test(t), 'a margin is shown without every cost input');
        expect(!/Contribution margin\s*₹\s*0\b/.test(t), 'a missing margin is shown as zero');
        await ap.screenshot({ path: path.join(OUT, 'p2-6-admin-finance.png'), fullPage: true });
        await ap.setViewportSize({ width: 390, height: 844 });
        await ap.goto('/admin/finance');
        await ap.locator('h1').first().waitFor();
        await ap.waitForLoadState('networkidle');
        const o = await ap.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(o <= 1, `/admin/finance scrolls sideways by ${o}px on a phone`);
        await ap.setViewportSize({ width: 1280, height: 900 });
      });
    }
    await step('no page crashed and no request returned a server error', async () => {
      expect(pageErrors.length === 0, 'page errors: ' + pageErrors.slice(0, 3).join(' | '));
      expect(httpErrors.length === 0, 'HTTP 5xx: ' + httpErrors.slice(0, 3).join(' | '));
    });
  }

  await browser.close();
  try {
    const left = sql(`
      DELETE FROM audit_logs WHERE tenant_id IN (SELECT id FROM tenants WHERE name IN ('${NAME}', '${NAME2}')) OR user_id IN (SELECT id FROM users WHERE email LIKE 'zz-e2e-p2%${TAG}@example.com');
      DELETE FROM tenants WHERE name IN ('${NAME}', '${NAME2}');
      DELETE FROM users WHERE email LIKE 'zz-e2e-p2%${TAG}@example.com';
      SELECT 'left: ' || (SELECT count(*) FROM tenants WHERE name IN ('${NAME}', '${NAME2}')) || ' tenants, ' || (SELECT count(*) FROM users WHERE email LIKE 'zz-e2e-p2%${TAG}@example.com') || ' users';`);
    console.log('cleanup', left.split('\n').pop());
  } catch (e) { console.log('CLEANUP FAILED (remove ' + NAME + ' by hand):', String(e.message).slice(0, 300)); }
  const failed = results.filter((r) => !r[1]);
  console.log(`\n${results.length - failed.length}/${results.length} browser checks passed`);
  process.exit(failed.length ? 1 : 0);
})();

async function toastIn(p, re) { await p.getByRole('status').filter({ hasText: re }).first().waitFor({ timeout: 20000 }); }
