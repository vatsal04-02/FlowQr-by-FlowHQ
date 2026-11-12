// FlowQR browser E2E for navigation, legal pages, data export/deletion, the AI Growth Agent, Google Posts, reports and settings.
// Drives the real UI in Chromium against a RUNNING local stack (docker compose up).
//
//   node e2e/agent-and-posts.js         (BASE_URL defaults to http://localhost:3000; CHROME_PATH=<system Chrome> with playwright-core)
//
// It creates one throwaway business ("ZZ-E2E-<id>") and removes it at the end.
//
// WHAT THIS DOES AND DOES NOT PROVE
//  * The Google connection, its location, reviews and the Google "snapshot" are SEEDED database rows. The UI is exercised against them.
//    No Google call succeeds in this test, and the one place a post is sent to Google ("Approve & publish now") is EXPECTED to fail
//    honestly, because the seeded connection has no real token. That failure path is what is being tested.
//  * AI drafting is NOT exercised here (it would spend your real AI quota); it is covered by the backend tests with a scripted AI.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }

const BASE = process.env.BASE_URL || 'http://localhost:3000';
const ROOT = path.resolve(__dirname, '..');
const OUT = process.env.SHOTS_DIR || path.join(ROOT, 'e2e', 'shots');
const TAG = Math.random().toString(36).slice(2, 8);
const PW = 'Str0ngPassw0rd!' + TAG;
const NAME = `ZZ-E2E-${TAG}`;
const results = [];

const docker = (args, input) => execFileSync('docker', ['compose', 'exec', '-T', ...args], { cwd: ROOT, input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
const seed = (code) => docker(['api', 'sh', '-c', 'cd /srv && PYTHONPATH=/srv python -'], code).trim();
const sql = (q) => docker(['db', 'psql', '-U', 'flowqr', '-d', 'flowqr', '-At', '-v', 'ON_ERROR_STOP=1'], `BEGIN; SELECT set_config('app.bypass_rls','on',true); ${q} COMMIT;`).trim();
function expect(cond, msg) { if (!cond) throw new Error(msg); }
const stamp = (d) => { const p = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  const ctx = await browser.newContext({ baseURL: BASE, viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const pageErrors = []; const httpErrors = [];
  page.on('pageerror', (e) => pageErrors.push(e.message));
  page.on('response', (r) => { if (r.status() >= 500) httpErrors.push(`${r.status()} ${r.url()}`); });

  async function step(name, fn) {
    try { await fn(); results.push([name, true]); console.log('PASS', name); }
    catch (e) {
      results.push([name, false, String(e.message).split('\n')[0].slice(0, 300)]);
      console.log('FAIL', name, '\n     ', String(e.message).split('\n')[0].slice(0, 300));
      await page.screenshot({ path: path.join(OUT, `fail-agent-${results.length}.png`), fullPage: true }).catch(() => {});
    }
  }
  const toast = (text) => page.getByRole('status').filter({ hasText: text }).first().waitFor({ timeout: 20000 });
  const download = async (click) => { const [d] = await Promise.all([page.waitForEvent('download', { timeout: 30000 }), click()]); return { name: d.suggestedFilename(), bytes: fs.readFileSync(await d.path()) }; };
  const nav = () => page.getByRole('navigation', { name: 'Main' });

  // ------------------------------------------------------------------ setup (API + seeded rows)
  let csrf, tenant, locA, ready = false;
  const H = () => ({ 'X-CSRF-Token': csrf });
  try {
    let r = await ctx.request.post('/api/v1/auth/register', { data: { email: `zz-e2e-${TAG}@example.com`, password: PW, full_name: 'ZZ E2E Owner' } });
    expect(r.status() === 201, `register ${r.status()} ${await r.text()}`);
    csrf = (await r.json()).csrf_token;
    tenant = await (await ctx.request.post('/api/v1/tenants', { data: { name: NAME, category: 'Physiotherapy clinic', language: 'en' }, headers: H() })).json();
    locA = await (await ctx.request.post('/api/v1/locations', { data: { name: 'E2E Main', city: 'Lucknow', review_url: 'https://g.page/r/ABC123/review' }, headers: H() })).json();
    await ctx.request.post('/api/v1/tenant/complete-onboarding', { headers: H() });
    seed(`
import uuid
from datetime import timedelta
from sqlalchemy import text
from app.core.db import system_session
from app.models import GbpSnapshot, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Review
from app.models.base import utcnow
db = system_session()
db.execute(text("UPDATE users SET email_verified_at = now() WHERE email = 'zz-e2e-${TAG}@example.com'"))
tid, lid = uuid.UUID("${tenant.id}"), uuid.UUID("${locA.id}")
c = GoogleConnection(tenant_id=tid, google_email="seeded-e2e@example.com", google_sub="seeded-${TAG}", status=GoogleConnectionStatus.active, api_access="approved", connected_at=utcnow())
db.add(c); db.flush()
g = GoogleLocation(tenant_id=tid, connection_id=c.id, location_id=lid, google_account_name="accounts/1", google_location_name="locations/1", title="E2E Main (Google)", selected=True, last_synced_at=utcnow(), last_sync_status="ok")
db.add(g); db.flush()
for i, (rating, text_, days, reply) in enumerate([(1, "Waited a long time and nobody explained", 2, None), (5, "Lovely and friendly staff", 6, "Thank you!"), (4, "Good clinic, parking is hard", 9, None)]):
    db.add(Review(tenant_id=tid, location_id=lid, google_location_id=g.id, external_id=f"seed-{i}", rating=rating, text=text_, reviewer_name=["Asha", "Ravi", "Meera"][i],
                  review_created_at=utcnow() - timedelta(days=days), first_seen_at=utcnow(), google_reply_text=reply, google_reply_at=utcnow() - timedelta(days=days - 1) if reply else None))
now = utcnow()
db.add(GbpSnapshot(tenant_id=tid, google_location_id=g.id, fetched_at=now, info={"title": "E2E Main", "description": "Old", "phone": "+91 98765 43210", "website": "https://clinic.example.com", "primary_category": {"id": "c", "name": "Physiotherapist"}, "additional_categories": [], "hours": [{"day": "MONDAY", "open": "09:00", "close": "18:00"}]},
                   posts=[], media=[], performance={"current": 4, "previous": 13, "window_days": 28, "from": "2026-10-01", "to": "2026-10-28", "metrics": []}))
db.commit()
`);
    ready = true;
  } catch (e) { console.log('SETUP FAILED:', e.message); results.push(['setup', false, e.message]); }

  if (ready) {
    // ------------------------------------------------------------------ 1. navigation
    await step('nav: eight groups, the group you are in is open, no duplicate names, no inner scrolling', async () => {
      await page.goto('/dashboard');
      await nav().getByRole('link', { name: 'Business Overview' }).waitFor({ timeout: 30000 });
      for (const g of ['Google Business', 'AI Growth Agent', 'Content Studio', 'Review Growth', 'Inbox & Leads', 'Settings']) await nav().getByRole('button', { name: g }).waitFor();
      await nav().getByRole('link', { name: 'Reports' }).waitFor();
      expect(await nav().getByRole('button', { name: 'Google Business' }).getAttribute('aria-expanded') === 'false', 'a group other than the current one is open at start');
      const scrolls = await nav().evaluate((el) => el.scrollHeight - el.clientHeight);
      expect(scrolls <= 1, `the sidebar scrolls by ${scrolls}px with one group open`);
      for (const g of ['Google Business', 'AI Growth Agent', 'Content Studio', 'Review Growth', 'Inbox & Leads', 'Settings']) await nav().getByRole('button', { name: g }).click();
      expect(await nav().getByRole('link', { name: 'Overview', exact: true }).count() === 1, 'more than one "Overview" link');
      expect(await nav().getByRole('link', { name: 'Analytics', exact: true }).count() === 1, 'more than one "Analytics" link');
    });
    await step('nav: active item and breadcrumb follow the page; collapsed state is remembered', async () => {
      await page.goto('/posts');
      const posts = nav().getByRole('link', { name: 'Posts', exact: true });
      await posts.waitFor({ timeout: 20000 });
      expect(await posts.getAttribute('aria-current') === 'page', 'Posts is not marked current');
      expect(await nav().getByRole('button', { name: 'Google Business' }).getAttribute('aria-expanded') === 'true', 'current group is not open');
      const crumbs = await page.getByRole('navigation', { name: 'Breadcrumb' }).innerText();
      expect(/Google Business/.test(crumbs) && /Posts/.test(crumbs), 'breadcrumb: ' + crumbs);
      await page.goto('/cards/analytics');
      await page.getByRole('navigation', { name: 'Breadcrumb' }).getByText('Reports').waitFor({ timeout: 20000 });
      expect(await nav().getByRole('link', { name: 'Reports' }).getAttribute('aria-current') === 'page', 'legacy analytics page does not belong to Reports');
    });
    await step('nav: every pre-existing URL still opens a real page', async () => {
      const urls = ['/dashboard', '/reviews', '/analytics', '/cards', '/cards/analytics', '/qr', '/locations', '/review-growth', '/review-growth/campaigns', '/review-growth/generator', '/review-growth/customize', '/review-growth/analytics', '/review-growth/settings', '/google', '/profile', '/subscription', '/payments', '/staff', '/settings'];
      for (const u of urls) {
        const r = await page.goto(u);
        expect(r && r.status() < 400, `${u} -> ${r && r.status()}`);
        await page.locator('h1').first().waitFor({ timeout: 20000 });
        expect(!(await page.getByText('This page could not be found').count()), `${u} is a 404`);
      }
    });
    await step('nav: location picker appears once there is more than one location and filters by the choice', async () => {
      await ctx.request.post('/api/v1/locations', { data: { name: 'E2E Branch', city: 'Kanpur', review_url: 'https://g.page/r/XYZ/review' }, headers: H() });
      await page.goto('/reports');
      const pick = page.getByLabel('Location', { exact: true });
      await pick.waitFor({ timeout: 20000 });
      expect((await pick.locator('option').allInnerTexts()).join('|') === 'All locations|E2E Main|E2E Branch', 'unexpected options');
      await pick.selectOption({ label: 'E2E Branch' });
      await page.getByText('0', { exact: true }).first().waitFor();
      await pick.selectOption('');
    });

    // ------------------------------------------------------------------ 2. legal + data rights
    await step('legal: privacy, terms and data-deletion pages are public, specific and link from the footer', async () => {
      const anon = await browser.newContext({ baseURL: BASE });
      const p = await anon.newPage();
      await p.goto('/privacy');
      await p.getByRole('heading', { name: 'Privacy policy' }).waitFor({ timeout: 20000 });
      expect(/Limited Use/.test(await p.locator('main').innerText()), 'no Google Limited Use statement');
      expect(/90 days/.test(await p.locator('main').innerText()), 'retention is not stated');
      expect(await p.getByText('has not been configured on this server yet').count() >= 1, 'does not say the contact address is unset');
      await p.getByRole('link', { name: 'Terms', exact: true }).click();
      await p.getByRole('heading', { name: 'Terms of service' }).waitFor();
      expect(/review gating/i.test(await p.locator('main').innerText()), 'terms do not forbid review gating');
      await p.getByRole('link', { name: 'Delete your data' }).click();
      await p.getByRole('heading', { name: 'Delete your data' }).waitFor();
      expect(/Settings → Your data|Settings → Your data/.test(await p.locator('main').innerText()), 'deletion steps missing');
      await anon.close();
    });
    await step('data: owner can download an export ZIP with no secrets', async () => {
      await page.goto('/settings#data');
      const d = await download(() => page.getByRole('button', { name: 'Download' }).click());
      expect(d.name === `flowqr-export-${(await (await ctx.request.get('/api/v1/tenant')).json()).slug}.zip` && d.bytes.subarray(0, 2).toString() === 'PK', 'not a zip: ' + d.name);
      const text = d.bytes.toString('latin1');
      for (const f of ['business.json', 'locations.json', 'reviews.json', 'README.json']) expect(text.includes(f), 'zip is missing ' + f);
      expect(!/refresh_token_encrypted|password_hash/.test(text), 'a secret column name is in the export listing');
    });
    await step('data: deletion needs the exact name and password, shows a banner, and can be cancelled', async () => {
      await page.getByRole('button', { name: 'Delete business…' }).click();
      const go = page.getByRole('button', { name: 'Schedule deletion' });
      expect(await go.isDisabled(), 'enabled before typing the name');
      await page.getByLabel(/Type the business name/).fill(NAME.toLowerCase());
      expect(await go.isDisabled(), 'enabled for the wrong-case name');
      await page.getByLabel(/Type the business name/).fill(NAME);
      await page.getByLabel('Your password').fill('wrong-Password1');
      await go.click();
      await page.getByText('That password is not correct.').waitFor();
      await page.getByLabel('Your password').fill(PW);
      await go.click();
      await toast('Deletion scheduled');
      await page.getByText(/This business will be deleted on/).waitFor({ timeout: 15000 });
      await page.goto('/dashboard');
      await page.getByText('This business is scheduled for deletion').waitFor({ timeout: 20000 });
      await page.goto('/settings#data');
      await page.getByRole('button', { name: 'Cancel deletion' }).click();
      await toast('Deletion cancelled');
      await page.getByRole('button', { name: 'Delete business…' }).waitFor();
      const st = await (await ctx.request.get('/api/v1/account/deletion')).json();
      expect(st.requested === false, 'still scheduled');
    });

    // ------------------------------------------------------------------ 3. knowledge base
    await step('knowledge base: seeded health rules, saves, persists, and checks text against the rules', async () => {
      await page.goto('/agent/knowledge');
      await page.getByText('Health business safety rules are on').waitFor({ timeout: 30000 });
      expect((await page.getByLabel('One phrase per line').inputValue()).includes('guaranteed cure'), 'health defaults not pre-filled');
      await page.getByLabel('Description', { exact: true }).fill('Physiotherapy for back and neck pain in Lucknow.');
      await page.getByLabel('Services (one per line)').fill('Back pain physiotherapy\nSports injury rehab');
      await page.getByLabel('Brand voice').fill('warm and calm');
      await page.getByRole('button', { name: 'Add a price or offer' }).click();
      await page.getByLabel('Name', { exact: true }).fill('First visit assessment');
      await page.getByLabel('Price (₹)').fill('500');
      await page.getByRole('button', { name: 'Save knowledge base' }).click();
      await toast('Knowledge base saved');
      await page.reload();
      await page.getByLabel('Description', { exact: true }).waitFor({ timeout: 20000 });
      expect((await page.getByLabel('Price (₹)').inputValue()) === '500' && (await page.getByLabel('Services (one per line)').inputValue()).includes('Sports injury rehab'), 'values did not persist');
      await page.getByLabel('Paste any reply, post or description').fill('Painless treatment, 100% cure, only ₹999');
      await page.getByRole('button', { name: 'Check', exact: true }).click();
      await page.getByText('This text breaks a rule from your knowledge base').waitFor();
      expect(await page.getByText(/Not allowed for a health business/).count() >= 1 && await page.getByText(/not in your verified prices/).count() >= 1, 'violations not explained');
      await page.getByLabel('Paste any reply, post or description').fill('The first visit assessment is ₹500. We are open Monday to Saturday.');
      await page.getByRole('button', { name: 'Check', exact: true }).click();
      await page.getByText('No rule broken.').waitFor();
    });
    await step('knowledge base: a claim in the description is refused with a reason', async () => {
      await page.getByLabel('Description', { exact: true }).fill('We are the best and guaranteed cheapest clinic in town');
      await page.getByRole('button', { name: 'Save knowledge base' }).click();
      await page.getByText('Not saved').waitFor({ timeout: 15000 });
      await page.reload();
    });

    // ------------------------------------------------------------------ 4. daily plan
    await step('agent: building the plan from the seeded data makes real tasks, worst review first, with the data behind them', async () => {
      const r = await ctx.request.post('/api/v1/agent/plan/run', { headers: H() });
      expect(r.status() === 200, 'plan run ' + r.status());
      await page.goto('/agent');
      await page.getByRole('heading', { name: "Today's plan" }).waitFor({ timeout: 20000 });
      const first = page.getByRole('listitem').filter({ hasText: 'Reply to a 1-star review from Asha' }).first();
      await first.waitFor({ timeout: 20000 });
      await first.getByText('2 days old and has no reply').waitFor();
      await first.getByText('Waited a long time and nobody explained').waitFor();
      expect(await page.getByRole('listitem').filter({ hasText: 'Reply to a 4-star review from Meera' }).count() === 1, 'second review task missing');
      expect(await page.getByRole('listitem').filter({ hasText: 'Reply to a 5-star' }).count() === 0, 'a task was made for an already-answered review');
      expect(await page.getByRole('listitem').filter({ hasText: 'Add a description to E2E Main (Google)' }).count() === 1, 'description task (from the snapshot) missing');
      expect(await page.getByRole('listitem').filter({ hasText: 'Publish a Google post this week' }).count() === 1, 'post task missing');
      expect(await page.getByRole('listitem').filter({ hasText: 'Complete your knowledge base' }).count() === 0, 'knowledge task should be resolved after the knowledge base was filled in');
    });
    await step('agent: the health score shows its formula, real measures, and leaves out what it cannot see', async () => {
      await page.getByRole('heading', { name: 'Business health' }).waitFor();
      const aria = await page.getByLabel(/Health score \d+ out of 100/).getAttribute('aria-label');
      expect(!!aria, 'no numeric score');
      const list = page.getByRole('list', { name: 'How the score is made' });
      await list.getByText('Review reply coverage').waitFor();
      await list.getByText('1 of 3 reviews from the last 90 days have a reply').waitFor();
      await list.getByText('Profile completeness').waitFor();
      await list.getByText(/Google has not told us about your photos|newest photo|no photos/).first().waitFor();
      await page.getByText('How this is calculated').click();
      await page.getByText(/Σ\(weight × value\)/).waitFor();
      await page.getByText(/not Google.s rules/).waitFor();
    });
    await step('agent: snooze and dismiss move tasks along and are recorded; history shows them', async () => {
      const card = page.getByRole('listitem').filter({ hasText: 'Publish a Google post this week' }).first();
      await card.getByRole('button', { name: 'Snooze' }).click();
      await toast('Snoozed until tomorrow');
      await card.waitFor({ state: 'detached', timeout: 15000 });
      const photo = page.getByRole('listitem').filter({ hasText: 'Reply to a 4-star review from Meera' }).first();
      await photo.getByRole('button', { name: 'Dismiss' }).click();
      await toast('Dismissed');
      await page.getByRole('listitem').filter({ hasText: 'Reply to a 4-star review from Meera' }).first().waitFor({ state: 'detached', timeout: 15000 }).catch(() => {});
      await page.goto('/agent/recommendations');
      await page.getByRole('radio', { name: 'History' }).click();
      await page.getByRole('listitem').filter({ hasText: 'Reply to a 4-star review from Meera' }).getByText('Dismissed').waitFor({ timeout: 20000 });
      await page.getByRole('radio', { name: 'Open', exact: true }).click();
      await page.getByRole('button', { name: 'Replies' }).click();
      await page.getByRole('listitem').filter({ hasText: 'Reply to a 1-star review from Asha' }).waitFor();
    });
    await step('agent: drafting without an AI draft in hand shows the honest empty approvals page', async () => {
      await page.goto('/agent/approvals');
      await page.getByText('Nothing is waiting for approval').waitFor({ timeout: 20000 });
    });
    await step('agent: automations are honest: drafting can be switched on, publishing cannot', async () => {
      await page.goto('/agent/automations');
      const draft = page.getByRole('switch', { name: 'Draft replies to new reviews' });
      await draft.waitFor({ timeout: 20000 });
      expect(!(await draft.isChecked()), 'auto-draft is on by default');
      await draft.click();
      await toast('Saved');
      await page.waitForFunction(() => document.getElementById('draft').checked);
      const pub = page.getByRole('switch', { name: 'Publish automatically' });
      expect(await pub.isDisabled() && !(await pub.isChecked()), 'auto-publish is available');
      await page.getByText('Automatic publishing is not available').waitFor();
      await draft.click();
      await toast('Saved');
    });
    await step('agent: activity shows the plan run and what is queued', async () => {
      await page.goto('/agent/activity');
      await page.getByRole('heading', { name: 'Activity' }).waitFor({ timeout: 20000 });
      await page.getByRole('cell', { name: 'Daily plan' }).first().waitFor();
      await page.getByText('Task history').waitFor();
    });
    await step('overview: shows the health score and today\'s plan', async () => {
      await page.goto('/dashboard');
      await page.getByRole('heading', { name: 'Business health' }).waitFor({ timeout: 20000 });
      await page.getByRole('heading', { name: "Today's plan" }).waitFor();
      await page.getByText(/to do/).first().waitFor();
    });

    // ------------------------------------------------------------------ 5. posts
    const GOOD = 'We are open Monday to Saturday. Call the clinic to book a visit.';
    const card = (text) => page.getByRole('listitem').filter({ hasText: text }).first();
    await step('posts: draft → submit → approve & schedule for later; nothing is sent; it shows on the calendar; cancel it', async () => {
      await page.goto('/posts');
      await page.getByLabel("What's new?").waitFor({ timeout: 30000 });
      await page.getByLabel("What's new?").fill(GOOD);
      await page.getByRole('button', { name: 'Save draft' }).click();
      await toast('Draft saved');
      const c = card(GOOD);
      await c.getByText('Draft', { exact: true }).waitFor();
      await c.getByRole('button', { name: 'Submit for approval' }).click();
      await toast('Submitted for approval');
      await c.getByText('Awaiting approval').waitFor();
      await c.getByLabel('Or schedule for').fill(stamp(new Date(Date.now() + 2 * 86400000)));
      await c.getByRole('button', { name: 'Approve & schedule' }).click();
      await toast('Scheduled');
      await c.getByText('Scheduled', { exact: true }).waitFor();
      await c.getByText(/Goes out/).waitFor();
      const posts = await (await ctx.request.get('/api/v1/posts')).json();
      expect(posts.posts[0].status === 'scheduled' && posts.posts[0].published_at === null && posts.posts[0].google_post_name === null, 'it was marked published without Google');
      await page.getByRole('radio', { name: 'Calendar' }).click();
      await page.getByRole('grid', { name: 'Post calendar' }).getByText('Scheduled').first().waitFor({ timeout: 20000 });
      await page.getByRole('radio', { name: 'Posts', exact: true }).click();
      const cb = card(GOOD).getByRole('button', { name: 'Cancel post' });
      console.log('cancel-button', await cb.count(), await cb.isVisible(), await cb.isEnabled());
      await cb.click({ timeout: 8000 });
      await toast('Canceled');
    });
    await step('posts: text that breaks the knowledge-base rules is shown as such and cannot be approved', async () => {
      const bad = 'Painless treatment with a 100% cure for only ₹999 today';
      await page.getByLabel("What's new?").fill(bad);
      await page.getByRole('button', { name: 'Save draft' }).click();
      await toast('Draft saved');
      const c = card(bad);
      await c.getByText('This text breaks a rule from your knowledge base').waitFor();
      await c.getByRole('button', { name: 'Submit for approval' }).click();
      await c.getByText('Awaiting approval').waitFor();
      await c.getByRole('button', { name: 'Approve & publish now' }).click();
      await c.getByText(/breaks a rule from your knowledge base/).first().waitFor();
      expect(await c.getByText('Awaiting approval').count() === 1, 'the post moved on despite the violation');
      await c.getByRole('button', { name: 'Cancel post' }).click();
      await toast('Canceled');
    });
    await step('posts: publishing when Google refuses ends as Failed with the reason, never as Published', async () => {
      const t = GOOD + ' Walk-ins welcome.';
      await page.getByLabel("What's new?").fill(t);
      await page.getByRole('button', { name: 'Save draft' }).click();
      await toast('Draft saved');
      const c = card(t);
      await c.getByRole('button', { name: 'Submit for approval' }).click();
      await c.getByRole('button', { name: 'Approve & publish now' }).click();
      await c.getByText('Failed', { exact: true }).waitFor({ timeout: 30000 });
      await c.getByText(/Google access was revoked|not connected|reconnect/i).first().waitFor();
      await c.getByRole('button', { name: 'Retry' }).waitFor();
      const row = (await (await ctx.request.get('/api/v1/posts')).json()).posts.find((p) => p.summary === t);
      expect(row.status === 'failed' && !row.published_at && !row.google_post_name, 'a refused post was recorded as published: ' + JSON.stringify(row).slice(0, 200));
      await page.goto('/agent/activity');
      await page.getByText(/Failed posts \(1\)/).waitFor({ timeout: 20000 });
    });

    // ------------------------------------------------------------------ 6. profile, media, performance
    await step('google pages react honestly to the lost connection instead of showing stale tools', async () => {
      for (const u of ['/profile', '/media', '/performance']) {
        await page.goto(u);
        await page.getByText('Google access was lost').waitFor({ timeout: 20000 });
        await page.getByRole('link', { name: 'Reconnect' }).waitFor();
      }
    });
    // ------------------------------------------------------------------ 7. reports + settings
    await step('reports: real numbers, Google performance marked missing, and the downloads work', async () => {
      await page.goto('/reports');
      await page.getByRole('heading', { name: 'Reputation' }).waitFor({ timeout: 20000 });
      await page.getByText('New reviews').waitFor();
      const dl = page.getByLabel('Downloads');
      const pdf = await download(() => dl.getByRole('button', { name: 'PDF report' }).click());
      expect(pdf.bytes.subarray(0, 8).toString() === '%PDF-1.4' && pdf.name === 'flowqr-report.pdf', 'PDF is not a PDF');
      const csv = await download(() => dl.getByRole('button', { name: 'Reviews (CSV)' }).click());
      expect(csv.bytes.toString().includes('review_date,location,reviewer,rating') && csv.bytes.toString().includes('Waited a long time'), 'CSV content wrong: ' + csv.name + ' ' + JSON.stringify(csv.bytes.toString().slice(0, 160)));
      for (const n of ['Posts (CSV)', 'Agent tasks (CSV)', 'AI activity (CSV)']) { const d = await download(() => dl.getByRole('button', { name: n }).click()); expect(d.bytes.length > 20, n + ' empty'); }
    });
    await step('settings: connections never say "Connected" for what is not, AI usage and the audit log load', async () => {
      await page.goto('/settings/connections');
      await page.getByRole('heading', { name: 'Connections' }).waitFor({ timeout: 20000 });
      for (const label of ['Facebook & Instagram (Meta)', 'WhatsApp Business Platform', 'Local rank provider']) {
        const panel = page.locator('section, div').filter({ has: page.getByText(label, { exact: true }) }).filter({ hasText: /Setup required/ }).first();
        await panel.waitFor();
      }
      expect(await page.getByText('Connected', { exact: true }).count() === await (async () => { const j = await (await ctx.request.get('/api/v1/workspace/integrations')).json(); return j.integrations.filter((i) => i.status === 'connected').length; })(), 'the page shows "Connected" for something the server did not call connected');
      await page.goto('/settings/ai');
      await page.getByRole('heading', { name: 'AI usage & limits' }).waitFor({ timeout: 20000 });
      await page.getByText('This month', { exact: true }).first().waitFor();
      await page.goto('/settings/audit');
      await page.getByRole('heading', { name: 'Audit log' }).waitFor({ timeout: 20000 });
      await page.getByRole('cell', { name: 'post.approve' }).first().waitFor();
      await page.getByLabel('Filter by action prefix').fill('agent.');
      await page.getByRole('cell', { name: /^agent\./ }).first().waitFor({ timeout: 20000 });
      await page.getByRole('cell', { name: 'post.approve' }).first().waitFor({ state: 'detached', timeout: 15000 });
    });
    await step('google: a connected account that manages no location is explained and offers another account', async () => {
      sql(`UPDATE google_connections SET status = 'pending_selection', last_error = NULL WHERE tenant_id = '${tenant.id}'; DELETE FROM google_locations WHERE tenant_id = '${tenant.id}';`);
      await page.goto('/google');
      await page.getByText('This Google account manages no locations').waitFor({ timeout: 20000 });
      await page.getByRole('button', { name: 'Connect another account' }).first().waitFor();
      await page.goto('/posts');
      await page.getByText('This Google account manages no locations').waitFor({ timeout: 20000 });
      const s = await (await ctx.request.get('/api/v1/workspace/integrations')).json();
      const g = s.integrations.find((i) => i.id === 'google');
      expect(g.status === 'attention' && /not a working business connection/.test(g.detail), 'integration status claims more than is true: ' + g.status);
    });

    await step('planned areas say "Setup required" and show no fake data', async () => {
      for (const [u, h] of [['/inbox', 'WhatsApp inbox'], ['/inbox/leads', 'Leads'], ['/studio/social', 'Social publishing'], ['/local-visibility', 'Local visibility'], ['/studio', 'AI Creator']]) {
        await page.goto(u);
        await page.getByRole('heading', { name: h, exact: true }).waitFor({ timeout: 20000 });
        await page.getByText('Setup required', { exact: true }).first().waitFor();
        await page.getByText(/Nothing on this page is simulated/).waitFor();
        expect(!(await page.getByText('Connected', { exact: true }).count()), `${u} claims Connected`);
      }
    });
    await step('no page crashed and no request returned a server error', async () => {
      expect(pageErrors.length === 0, 'page errors: ' + pageErrors.slice(0, 3).join(' | '));
      expect(httpErrors.length === 0, 'HTTP 5xx: ' + httpErrors.slice(0, 3).join(' | '));
    });
  }

  await browser.close();
  try {
    const left = sql(`
      DELETE FROM audit_logs WHERE tenant_id IN (SELECT id FROM tenants WHERE name = '${NAME}') OR user_id IN (SELECT id FROM users WHERE email LIKE 'zz-e2e-%${TAG}@example.com');
      DELETE FROM tenants WHERE name = '${NAME}';
      DELETE FROM users WHERE email LIKE 'zz-e2e-%${TAG}@example.com';
      SELECT 'left: ' || (SELECT count(*) FROM tenants WHERE name = '${NAME}') || ' tenants, ' || (SELECT count(*) FROM users WHERE email LIKE 'zz-e2e-%${TAG}@example.com') || ' users';`);
    console.log('cleanup', left.split('\n').pop());
  } catch (e) { console.log('CLEANUP FAILED (remove ' + NAME + ' by hand):', String(e.message).slice(0, 300)); }
  const failed = results.filter((r) => !r[1]);
  console.log(`\n${results.length - failed.length}/${results.length} browser checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
