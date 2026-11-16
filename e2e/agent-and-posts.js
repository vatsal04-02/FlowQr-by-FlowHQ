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
// Playwright rejects a pending navigation promise when the browser closes at the end of the run; that must not skip cleanup and the summary.
process.on('unhandledRejection', (e) => { if (!/Target page, context or browser has been closed/.test(String(e && e.message))) { console.error(e); process.exitCode = 1; } });

const docker = (args, input) => execFileSync('docker', ['compose', 'exec', '-T', ...args], { cwd: ROOT, input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
const seed = (code) => docker(['api', 'sh', '-c', 'cd /srv && PYTHONPATH=/srv python -'], code).trim();
const sql = (q) => docker(['db', 'psql', '-U', 'flowqr', '-d', 'flowqr', '-At', '-v', 'ON_ERROR_STOP=1'], `BEGIN; SELECT set_config('app.bypass_rls','on',true); SELECT set_config('app.history_purge','on',true); ${q} COMMIT;`).trim();
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
  // the left rail: the current section's pages as icon links named by aria-label (desktop viewport)
  const rail = (sec) => page.getByRole('navigation', { name: sec + ' pages', exact: true });
  const railOf = async (sec) => { await rail(sec).waitFor({ timeout: 20000 }); return (await rail(sec).getByRole('link').evaluateAll((els) => els.map((e) => e.getAttribute('aria-label')))).join('|'); };
  const railCurrent = async (sec, name) => { await rail(sec).waitFor({ timeout: 20000 }); return rail(sec).getByRole('link', { name, exact: true }).getAttribute('aria-current'); };

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
    await step('nav: four sections in one pill, the rail lists the section pages, old URLs redirect', async () => {
      await page.goto('/dashboard');
      await page.waitForURL('**/overview');
      await nav().getByRole('link', { name: 'Overview', exact: true }).waitFor({ timeout: 30000 });
      const names = await nav().getByRole('link').allInnerTexts();
      expect(JSON.stringify(names.map((n) => n.trim())) === JSON.stringify(['Overview', 'GBP Manager', 'AI', 'Settings']), 'section links: ' + names.join(' | '));
      expect(await nav().getByRole('link', { name: 'Overview', exact: true }).getAttribute('aria-current') === 'page', 'Overview is not marked current on /overview');
      expect(await railOf('Overview') === 'Summary|Reviews|Search & Maps|Customer funnel|Locations|Reports', 'overview pages: ' + await railOf('Overview'));
      expect(await railCurrent('Overview', 'Summary') === 'page', 'Summary is not the current page on /overview');
      // PRD §8: old URLs land on the new ones and keep their query string
      await page.goto('/reviews?state=none');
      await page.waitForURL('**/gbp/reviews?state=none');
    });
    await step('nav: the rail and the sibling-page pills follow the page', async () => {
      await page.goto('/gbp/posts');
      expect(await railOf('GBP Manager') === 'Overview|Reviews & replies|Business info|Posts|Photos|Local ranking|Locations & Google|QR/NFC cards|Review campaigns|Inbox & leads', 'gbp pages: ' + await railOf('GBP Manager'));
      expect(await nav().getByRole('link', { name: 'GBP Manager' }).getAttribute('aria-current') === 'page', 'GBP Manager is not marked current');
      expect(await railCurrent('GBP Manager', 'Posts') === 'page', 'Posts is not current');
      // Opening hours reads the live profile from Google; the seeded token would be refused and the connection marked revoked,
      // which would change every later step. This step only checks navigation, so answer that one read locally.
      await page.route('**/api/v1/gbp/*/info', (route) => route.fulfill({ json: { title: 'E2E Main', description: 'Old', phone: null, website: null, primary_category: null, additional_categories: [], hours: [] } }));
      await page.goto('/gbp/hours');
      expect(await railCurrent('GBP Manager', 'Business info') === 'page', 'opening hours are not under Business info');
      await page.waitForLoadState('networkidle');  // the profile is fetched after the rail renders: keep the stub until that request is answered
      await page.waitForTimeout(500);
      await page.unroute('**/api/v1/gbp/*/info');
      await page.goto('/cards/analytics');
      await page.waitForURL('**/analytics/funnel');
      expect(await railCurrent('Overview', 'Customer funnel') === 'page', 'card analytics are not under Customer funnel');
      await page.goto('/ai/approvals');
      expect(await railOf('AI') === 'Reply assistant|AI assistant|Autonomy|Brand voice|Review-writing assistant|Insights|Content studio|Business brain|Usage & limits', 'ai pages: ' + await railOf('AI'));
      expect(await railCurrent('AI', 'AI assistant') === 'page', 'approvals do not sit under AI assistant');
      expect(await page.getByRole('navigation', { name: 'AI assistant pages', exact: true }).getByRole('link', { name: 'Waiting for approval' }).getAttribute('aria-current') === 'page', 'sub page not marked');
      // Local ranking lives under GBP Manager now (the old /overview/visibility URL redirects there).
      await page.goto('/overview/visibility');
      await page.waitForURL('**/seo/rank');
      expect(await railCurrent('GBP Manager', 'Local ranking') === 'page', 'local ranking is not under GBP Manager');
      // The Performance page calls Google live. With Google configured, Google rejects this suite's SEEDED fake token and the backend rightly marks the
      // connection revoked, which would change every later step. This step only checks navigation, so answer those calls locally (no real Google call).
      await page.route('**/api/v1/gbp/*/performance**', (route) => route.fulfill({ json: { from: '', to: '', totals: {}, series: {}, note: 'stub' } }));
      await page.route('**/api/v1/gbp/*/keywords**', (route) => route.fulfill({ json: { from_month: '', to_month: '', keywords: [], note: 'stub' } }));
      await page.goto('/analytics/performance');
      expect(await railCurrent('Overview', 'Search & Maps') === 'page', 'performance is not under Search & Maps');
      await page.waitForTimeout(1500);
      await page.unroute('**/api/v1/gbp/*/performance**');
      await page.unroute('**/api/v1/gbp/*/keywords**');
      await page.goto('/ai/studio/calendar');
      expect(await railCurrent('AI', 'Content studio') === 'page', 'studio is not under AI');
      expect(await page.getByRole('navigation', { name: 'Content studio pages', exact: true }).getByRole('link', { name: 'Calendar' }).getAttribute('aria-current') === 'page', 'studio calendar is not a Content studio page');
      await page.goto('/gbp/inbox/campaigns');
      expect(await railCurrent('GBP Manager', 'Inbox & leads') === 'page', 'inbox campaigns are not under Inbox & leads');
      await page.goto('/payments');
      await page.waitForURL('**/settings/billing/payments');
      expect(await nav().getByRole('link', { name: 'Settings' }).getAttribute('aria-current') === 'page', 'payments do not sit under Settings');
      expect(await railOf('Settings') === 'Business|Team|Plan & billing|Account|Connections|Appearance|Notifications|Audit log', 'settings pages: ' + await railOf('Settings'));
      expect(await railCurrent('Settings', 'Plan & billing') === 'page', 'payments are not under Plan & billing');
    });
    await step('nav: location picker appears once there is more than one location and filters by the choice', async () => {
      sql(`UPDATE subscriptions SET max_locations = 10 WHERE tenant_id = '${tenant.id}';`);  // Growth includes ONE location (Phase 2); this step needs a second
      await ctx.request.post('/api/v1/locations', { data: { name: 'E2E Branch', city: 'Kanpur', review_url: 'https://g.page/r/XYZ/review' }, headers: H() });
      await page.goto('/reports');
      const pick = page.getByLabel('Show data for location', { exact: true });
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
    const next = () => page.getByRole('button', { name: /^Next/ }).click();
    await step('knowledge base: a guided wizard with the health rules pre-filled; it saves, persists and checks text', async () => {
      await page.goto('/agent/knowledge');
      await page.getByRole('heading', { name: 'About you' }).waitFor({ timeout: 30000 });
      expect(await page.getByRole('navigation', { name: 'Setup steps' }).getByRole('listitem').count() === 5, 'five wizard steps');
      await page.getByLabel('What do you do, and where?').fill('Physiotherapy for back and neck pain in Lucknow.');
      await page.getByLabel('Services (one per line)').fill('Back pain physiotherapy\nSports injury rehab');
      await page.getByLabel('How should replies sound?').fill('warm and calm');
      await next();
      await page.getByRole('button', { name: 'Add a price or offer' }).click();
      await page.getByLabel('Name', { exact: true }).fill('First visit assessment');
      await page.getByLabel('Price (₹)').fill('500');
      await next(); await next();
      await page.getByText('Health business rules are on').waitFor();
      expect((await page.getByLabel('Never say (one phrase per line)').inputValue()).includes('guaranteed cure'), 'health defaults not pre-filled');
      await page.getByRole('button', { name: 'Save Business Brain' }).click();
      await toast('Business Brain saved');
      await page.reload();
      await page.getByLabel('What do you do, and where?').waitFor({ timeout: 20000 });
      expect((await page.getByLabel('Services (one per line)').inputValue()).includes('Sports injury rehab'), 'services did not persist');
      await next();
      expect((await page.getByLabel('Price (₹)').inputValue()) === '500', 'price did not persist');
      await next(); await next(); await next();
      await page.getByLabel('Try a reply, post or description').fill('Painless treatment, 100% cure, only ₹999');
      await page.getByRole('button', { name: 'Check it against my rules' }).click();
      await page.getByText('This text breaks a rule from your knowledge base').waitFor();
      expect(await page.getByText(/Not allowed for a health business/).count() >= 1 && await page.getByText(/not in your verified prices/).count() >= 1, 'violations not explained');
      await page.getByLabel('Try a reply, post or description').fill('The first visit assessment is ₹500. We are open Monday to Saturday.');
      await page.getByRole('button', { name: 'Check it against my rules' }).click();
      await page.getByText('Passes your rules').waitFor();
    });
    await step('knowledge base: a claim in the description is refused with a reason', async () => {
      await page.goto('/agent/knowledge');
      await page.getByLabel('What do you do, and where?').fill('We are the best and guaranteed cheapest clinic in town');
      await page.getByRole('button', { name: 'Save Business Brain' }).click();
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
      await page.getByRole('heading', { name: 'How your business is doing' }).waitFor();
      // The rule: a score only when at least 4 of the 6 measures have real data; otherwise the honest "Getting started" line.
      const measures = page.getByRole('list', { name: 'Business measures' });
      await measures.waitFor();
      const available = await measures.getByText('(available)').count();
      const score = await page.getByLabel(/Score \d+ out of 100/).count();
      if (available >= 4) expect(score === 1, `${available} of 6 measures have data but no score is shown`);
      else {
        expect(score === 0, `a score is shown with only ${available} of 6 measures`);
        await page.getByText(new RegExp(`Getting started\\s*·\\s*${available} of 6 business measures available`)).waitFor();
      }
      const list = page.getByRole('list', { name: 'How the score is made' });
      await list.getByText('Review reply coverage').waitFor();
      await list.getByText('1 of 3 reviews from the last 90 days have a reply').waitFor();
      await list.getByText('Profile completeness').waitFor();
      await list.getByText(/Google has not told us about your photos|newest photo|no photos/).first().waitFor();
      await page.getByText('How this is worked out').click();
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
    await step('agent: automations lay out the six jobs as one workflow with what needs approval', async () => {
      await page.goto('/ai/automations');
      await page.getByRole('list', { name: 'Agent workflow' }).waitFor({ timeout: 20000 });
      for (const stage of ['Data collection', 'Analysis', 'Approval', 'Publishing', 'Verification', 'Activity report']) await page.getByRole('list', { name: 'Agent workflow' }).getByText(stage, { exact: true }).waitFor();
      for (const name of ['SEO profile optimization', 'Review growth', 'AI review replies', 'Daily Google Posts', 'Photo management', 'Performance analytics']) await page.getByText(name, { exact: true }).first().waitFor();
      await page.getByText('Review replies, Google Posts and photos always need a person').waitFor();
      await page.getByText('AI review replies', { exact: true }).first().click();
      await page.getByText('Publishing every reply, including 5-star ones').waitFor();
    });
    await step('ai quality: the acceptance table shows all four kinds and never a made-up rate', async () => {
      await page.goto('/settings/ai/usage');
      await page.getByText('How much of what the AI writes you keep').waitFor({ timeout: 20000 });
      for (const k of ['Review replies', 'Google Posts', 'Profile descriptions', 'Customer review drafts']) await page.getByRole('cell', { name: k, exact: true }).waitFor();
      const rows = await page.getByRole('row').filter({ hasText: 'Google Posts' }).first().innerText();
      expect(/–|%/.test(rows), 'no acceptance cell');
      await page.getByText(/Kept as is = approved with at most 25% of the words changed/).waitFor();
    });
    await step('posts: "Suggest 3 ideas" shows different concepts with a real photo to take, and one can be used as the text', async () => {
      await page.route('**/api/v1/posts/ideas', (route) => route.fulfill({ json: { ideas: [
        { type: 'educational', title: 'Desk posture', text: 'Sitting at a desk all day? Check how your screen and chair line up before strain turns into pain. Call the clinic to book.', image: 'The reception desk', why: 'Reaches desk workers' },
        { type: 'faq', title: 'Referral?', text: 'Do I need a doctor referral? No referral is needed for a first assessment, so you can simply call and book.', image: 'The front door with timings', why: 'Answers a real question' },
        { type: 'service', title: 'First visit', text: 'A first visit lasts about 45 minutes: we listen, examine, explain and agree a plan with you.', image: 'A treatment room as it really looks', why: 'Shows what to expect' }], missing: [], note: 'x' } }));
      await page.goto('/gbp/posts');
      await page.getByRole('button', { name: 'Suggest 3 ideas' }).click();
      await page.getByLabel('Post ideas').waitFor({ timeout: 20000 });
      expect(await page.getByLabel('Post ideas').getByRole('listitem').count() === 3, 'not three ideas');
      await page.getByLabel('Post ideas').getByText('Photo to take:').first().waitFor();
      await page.getByLabel('Post ideas').getByRole('button', { name: 'Use this text' }).nth(1).click();
      expect((await page.getByLabel(/What's new/).inputValue()).startsWith('Do I need a doctor referral'), 'idea text was not used');
      await page.unroute('**/api/v1/posts/ideas');
    });
    await step('agent: activity shows the plan run and what is queued', async () => {
      await page.goto('/agent/activity');
      await page.getByRole('heading', { name: 'Activity' }).waitFor({ timeout: 20000 });
      await page.getByRole('cell', { name: 'Daily plan' }).first().waitFor();
      await page.getByText('Task history').waitFor();
    });
    await step('overview: the summary grid in plain language, a fair health check and what needs attention', async () => {
      const googleCalls = [];
      const spy = (req) => { if (/\/api\/v1\/gbp\//.test(req.url())) googleCalls.push(req.url()); };
      page.on('request', spy);
      await page.goto('/dashboard');
      for (const h of ['Average Google rating', 'Review trend', 'Recent activity', 'Customer funnel', 'Your business growth', 'What customers mention', 'Needs your attention'])
        await page.getByRole('heading', { name: h }).waitFor({ timeout: 20000 });
      await page.getByText(/AI assistant has \d+ things? to help with today|all caught up|hasn't made today's plan/i).waitFor({ timeout: 20000 });
      await page.getByRole('heading', { name: 'How your business is doing' }).waitFor();
      // never a score without enough real data behind it: either the honest "getting started" line or a score from at least 4 measures
      const txt = await page.locator('main').innerText();
      const m = txt.match(/Getting started\s*·\s*(\d+) of (\d+) business measures available/);
      expect(m || /\/100/.test(txt), 'neither a "Getting started" line nor a score is shown');
      if (m) expect(!/\b100\s*\/\s*100\b/.test(txt), 'a perfect score is shown with too little data');
      // the old jargon is gone from the main page
      for (const bad of ['Reply coverage', 'Business health', 'AI Execution History', 'Pending Approvals']) expect(!txt.includes(bad), `jargon still on the dashboard: ${bad}`);
      // scans and reviews are never combined: the funnel says so in words
      await page.getByText(/Clicks are not reviews|No card on a counter yet/).first().waitFor({ timeout: 20000 });  // the heading shows before the funnel's data does
      const txt2 = await page.locator('main').innerText();
      // with cards, the funnel says clicks are not reviews; without any card it says so instead of drawing an empty funnel
      expect(txt2.includes('Clicks are not reviews') || txt2.includes('No card on a counter yet'), 'the funnel no longer separates clicks from reviews');
      await page.waitForTimeout(1500);
      page.off('request', spy);
      // loading the dashboard must never call Google (it would spend quota and can change the connection's state)
      expect(googleCalls.length === 0, 'the dashboard called Google on load: ' + googleCalls.join(', '));
    });
    await step('overview: growth chart tabs and the 7/30/90-day filter work from keyboard and mouse', async () => {
      // the two Google tabs fetch live from Google when opened; stub that one call so this suite stays free of real Google requests
      await page.route('**/api/v1/gbp/*/performance**', (route) => route.fulfill({ json: { from: '', to: '', totals: {}, series: { CALL_CLICKS: [{ date: '2026-11-01', value: 2 }], BUSINESS_IMPRESSIONS_DESKTOP_MAPS: [{ date: '2026-11-01', value: 9 }] }, note: 'stub' } }));
      await page.goto('/dashboard');
      const tabs = page.getByRole('tab');
      await tabs.first().waitFor({ timeout: 20000 });
      expect(await tabs.count() === 4, 'four growth tabs');
      expect(await page.getByRole('tab', { name: 'Reviews' }).getAttribute('aria-selected') === 'true', 'Reviews tab starts selected');
      await page.getByRole('tab', { name: 'Reviews' }).focus();
      await page.keyboard.press('ArrowRight');
      expect(await page.getByRole('tab', { name: 'Google profile use' }).getAttribute('aria-selected') === 'true', 'ArrowRight moves to the next tab');
      expect(await page.getByRole('radiogroup', { name: 'Show the last' }).count() === 1, 'one range control on the page');
      await page.getByRole('radio', { name: '90 days' }).click();
      await page.getByText('Last 90 days', { exact: true }).waitFor({ timeout: 20000 });
      await page.getByRole('radio', { name: '7 days' }).click();
      await page.getByText('Last 7 days', { exact: true }).waitFor({ timeout: 20000 });
      await page.unroute('**/api/v1/gbp/*/performance**');
    });
    await step('overview: a tooltip opens on focus and closes on Escape', async () => {
      await page.goto('/dashboard');
      const hint = page.getByRole('button', { name: /What does .Your business growth. mean/ });
      await hint.waitFor({ timeout: 20000 });
      await hint.focus();
      await page.getByRole('tooltip').waitFor();
      await page.keyboard.press('Escape');
      expect(await page.getByRole('tooltip').count() === 0, 'tooltip did not close on Escape');
    });
    await step('shell: Ctrl+K jumps to a page; the theme toggle switches to dark and back', async () => {
      await page.goto('/dashboard');
      await page.getByRole('heading', { name: 'Review trend' }).waitFor({ timeout: 20000 });
      await page.keyboard.press('Control+k');
      await page.getByRole('combobox', { name: 'Search pages and reviews' }).fill('posts');
      await page.keyboard.press('Enter');
      await page.waitForURL('**/posts');
      await page.getByRole('button', { name: 'Dark mode' }).click();
      await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark', null, { timeout: 5000 }).catch(() => { throw new Error('dark mode did not apply'); });
      await page.waitForTimeout(800);  // let the 600 ms circular reveal finish
      await page.getByRole('button', { name: 'Light mode' }).click();
      await page.waitForFunction(() => document.documentElement.dataset.theme === 'light', null, { timeout: 5000 }).catch(() => { throw new Error('light mode did not come back'); });
      await page.waitForTimeout(800);
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
      await page.getByText('New reviews').first().waitFor();
      const dl = page.getByLabel('Downloads');
      const pdf = await download(() => dl.getByRole('button', { name: 'PDF report' }).click());
      expect(pdf.bytes.subarray(0, 8).toString() === '%PDF-1.4' && /^flowqr-report-\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.pdf$/.test(pdf.name), 'PDF is not a PDF');
      const csv = await download(() => dl.getByRole('button', { name: 'Reviews (CSV)' }).click());
      expect(csv.bytes.toString().includes('review_date,location,reviewer,rating') && csv.bytes.toString().includes('Waited a long time'), 'CSV content wrong: ' + csv.name + ' ' + JSON.stringify(csv.bytes.toString().slice(0, 160)));
      for (const n of ['Posts (CSV)', 'Agent tasks (CSV)', 'AI activity (CSV)']) { const d = await download(() => dl.getByRole('button', { name: n }).click()); expect(d.bytes.length > 20, n + ' empty'); }
    });
    await step('settings: connections never say "Connected" for what is not, AI usage and the audit log load', async () => {
      await page.goto('/settings/connections');
      await page.getByRole('heading', { name: 'Connections' }).waitFor({ timeout: 20000 });
      for (const label of ['Facebook & Instagram (Meta)', 'WhatsApp Business Platform']) {
        const panel = page.locator('section, div').filter({ has: page.getByText(label, { exact: true }) }).filter({ hasText: /Setup required/ }).first();
        await panel.waitFor();
      }
      expect(await page.getByText('Connected', { exact: true }).count() === await (async () => { const j = await (await ctx.request.get('/api/v1/workspace/integrations')).json(); return j.integrations.filter((i) => i.status === 'connected').length; })(), 'the page shows "Connected" for something the server did not call connected');
      await page.goto('/settings/ai');  // moved to AI › Usage & limits; the old URL redirects
      await page.waitForURL('**/settings/ai/usage');
      await page.getByRole('heading', { name: 'Usage & limits' }).waitFor({ timeout: 20000 });
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
      for (const [u, h] of [['/inbox', 'WhatsApp inbox'], ['/inbox/leads', 'Leads'], ['/studio/social', 'Social publishing'], ['/studio', 'AI Creator']]) {
        await page.goto(u);
        await page.getByRole('heading', { name: h, exact: true }).waitFor({ timeout: 20000 });
        await page.getByText('Setup required', { exact: true }).first().waitFor();
        await page.getByText(/Nothing on this page is simulated/).waitFor();
        expect(!(await page.getByText('Connected', { exact: true }).count()), `${u} claims Connected`);
      }
    });
    // Last, on purpose: Media and Insights call Google with the seeded (fake) token, which marks the seeded connection as lost.
    await step('nav: every existing URL still opens a real page and sits under exactly one workspace', async () => {
      const urls = ['/dashboard', '/reports', '/analytics', '/cards/analytics', '/profile', '/reviews', '/posts', '/media', '/performance', '/local-visibility', '/google',
        '/agent', '/agent/recommendations', '/agent/approvals', '/agent/activity', '/agent/knowledge', '/agent/automations',
        '/studio', '/studio/calendar', '/studio/brand', '/studio/assets', '/studio/social',
        '/review-growth', '/review-growth/campaigns', '/review-growth/customize', '/review-growth/generator', '/review-growth/settings', '/review-growth/analytics', '/cards', '/qr',
        '/inbox', '/inbox/leads', '/inbox/appointments', '/inbox/followups', '/inbox/campaigns',
        '/settings', '/settings/connections', '/settings/ai', '/settings/audit', '/locations', '/staff', '/subscription', '/payments'];
      await page.route('**/api/v1/gbp/**', (route) => {
        const u = new URL(route.request().url()).pathname;
        if (u.includes('/library') && !u.endsWith('/coverage')) return route.continue();
        if (u.endsWith('/performance')) return route.fulfill({ json: { from: '', to: '', totals: {}, series: {}, note: 'stub' } });
        if (u.endsWith('/keywords')) return route.fulfill({ json: { from_month: '', to_month: '', keywords: [], note: 'stub' } });
        if (u.endsWith('/coverage')) return route.fulfill({ json: { on_google: {}, total_on_google: 0, suggestions: [], note: 'stub' } });
        if (u.endsWith('/info')) return route.fulfill({ json: { title: 'E2E Main', description: 'Old', phone: null, website: null, primary_category: null, additional_categories: [], hours: [] } });
        return route.fulfill({ json: [] });
      });
      for (const u of urls) {
        const r = await page.goto(u);
        expect(r && r.status() < 400, `${u} -> ${r && r.status()}`);
        await page.locator('h1').first().waitFor({ timeout: 20000 });
        expect(!(await page.getByText('This page could not be found').count()), `${u} is a 404`);
        expect(await nav().locator('a[aria-current="page"]').count() === 1, `${u} is not under exactly one workspace`);
      }
      await page.unroute('**/api/v1/gbp/**');
    });
    await step('no page crashed and no request returned a server error', async () => {
      expect(pageErrors.length === 0, 'page errors: ' + pageErrors.slice(0, 3).join(' | '));
      expect(httpErrors.length === 0, 'HTTP 5xx: ' + httpErrors.slice(0, 3).join(' | '));
    });
  }

  await page.unrouteAll({ behavior: 'ignoreErrors' }).catch(() => {});
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
