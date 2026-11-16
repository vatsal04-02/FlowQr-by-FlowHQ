// FlowQR browser E2E for the Autonomy control centre and the geo-grid map. Drives the real UI in Chromium against a RUNNING stack.
//
//   COMPOSE_PROJECT_NAME=flowqr-demo BASE_URL=http://localhost:3100 node e2e/autonomy-control-centre.js
//   (use the isolated demo stack: docker compose -p flowqr-demo -f docker-compose.yml -f e2e/compose.demo.yml --project-directory . up -d --build)
//
// It creates one throwaway business ("ZZ-E2E-<id>") and removes it at the end.
//
// WHAT THIS DOES AND DOES NOT PROVE
//  * The Google connection, location, profile snapshot, the three autonomy actions (waiting, failed, executed) and the map scans are SEEDED database rows.
//    The UI, the API, the role rules, the database and the policy are real. NO Google call is made and none succeeds: the "executed" action is a seeded
//    record, so this test proves the screens and the owner's controls, NOT that FlowQR can change a real Google profile.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }

const BASE = process.env.BASE_URL || 'http://localhost:3000';
const ROOT = path.resolve(__dirname, '..');
const OUT = process.env.SHOTS_DIR || path.join(ROOT, 'e2e', 'shots');
const TAG = Math.random().toString(36).slice(2, 8);
const EMAIL = `zz-e2e-${TAG}@example.com`;
const PW = 'Str0ngPassw0rd!' + TAG;
const NAME = `ZZ-E2E-${TAG}`;
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
      await page.screenshot({ path: path.join(OUT, `fail-autonomy-${results.length}.png`), fullPage: true }).catch(() => {});
    }
  }
  const toast = (text) => page.getByRole('status').filter({ hasText: text }).first().waitFor({ timeout: 20000 });
  const tab = (name) => page.getByRole('radio', { name });

  // ------------------------------------------------------------------ setup (API + seeded rows)
  let csrf, tenant, ready = false;
  const H = () => ({ 'X-CSRF-Token': csrf });
  try {
    let r = await ctx.request.post('/api/v1/auth/register', { data: { email: EMAIL, password: PW, full_name: 'ZZ E2E Owner' } });
    expect(r.status() === 201, `register ${r.status()} ${await r.text()}`);
    csrf = (await r.json()).csrf_token;
    tenant = await (await ctx.request.post('/api/v1/tenants', { data: { name: NAME, category: 'Physiotherapy clinic', language: 'en' }, headers: H() })).json();
    const locA = await (await ctx.request.post('/api/v1/locations', { data: { name: 'E2E Main', city: 'Lucknow', review_url: 'https://g.page/r/ABC123/review' }, headers: H() })).json();
    await ctx.request.post('/api/v1/tenant/complete-onboarding', { headers: H() });
    console.log(seed(`
import uuid
from datetime import timedelta
from sqlalchemy import select, text
from app.core.db import system_session
from app.models import AgentAction, GbpSnapshot, GoogleConnection, GoogleConnectionStatus, GoogleLocation, RankGrid, RankGridPoint, RankGridScan, RankKeyword, Tenant, User
from app.models.base import utcnow
from app.services import rank_grid as rg
from app.services.agent import executor, history
db = system_session()
db.execute(text("UPDATE users SET email_verified_at = now() WHERE email = '${EMAIL}'"))
tid, lid = uuid.UUID("${tenant.id}"), uuid.UUID("${locA.id}")
uid = db.scalar(select(User.id).where(User.email == "${EMAIL}"))
c = GoogleConnection(tenant_id=tid, google_email="seeded-e2e@example.com", google_sub="seeded-${TAG}", status=GoogleConnectionStatus.active, api_access="approved", connected_at=utcnow())
db.add(c); db.flush()
g = GoogleLocation(tenant_id=tid, connection_id=c.id, location_id=lid, google_account_name="accounts/1", google_location_name="locations/1", title="E2E Main (Google)", selected=True,
                   last_synced_at=utcnow(), last_sync_status="ok", lat=26.85, lng=80.95, place_id="PID-E2E")
db.add(g); db.flush()
info = {"title": "E2E Main", "description": "Old description of the clinic.", "phone": "+91 98765 43210", "website": "https://clinic.example.com",
        "primary_category": {"id": "categories/gcid:physiotherapist", "name": "Physiotherapist"}, "additional_categories": [], "hours": [{"day": "MONDAY", "open": "09:00", "close": "18:00"}]}
db.add(GbpSnapshot(tenant_id=tid, google_location_id=g.id, fetched_at=utcnow(), info=info, posts=[], media=[], performance={"current": 4, "previous": 13, "window_days": 28, "from": "2026-10-01", "to": "2026-10-28", "metrics": []}))
db.flush()
tenant = db.get(Tenant, tid)
# 1) waiting: Level 2 hours (a person decides), 2) waiting: Level 3 main category (owner only), 3) failed, 4) executed (a SEEDED record)
hours = executor.propose(db, tenant, g, "hours_update", proposed=[{"day": "MONDAY", "open": "09:00", "close": "18:00"}, {"day": "TUESDAY", "open": "10:00", "close": "17:30"}],
                         source={"kind": "owner_input", "user_id": str(uid)}, trigger="owner_request", problem="Tuesday hours are missing.", reason="You told us the Tuesday hours.", proposed_by="user", user_id=uid)
cat = executor.propose(db, tenant, g, "primary_category_change", proposed="categories/gcid:chiropractor", source={"kind": "owner_input", "user_id": str(uid)}, trigger="owner_request",
                       problem="The main category looks wrong.", reason="You asked for it to be Chiropractor.", proposed_by="user", user_id=uid)
bad = executor.propose(db, tenant, g, "contact_update", field_key="website", proposed="https://other.example.com", source={"kind": "owner_input", "user_id": str(uid)}, trigger="owner_request",
                       problem="Change the website.", reason="New site.", proposed_by="user", user_id=uid)
bad.status, bad.last_error = "failed", "Google denied the request: the connected account may not manage this location."
history.record(db, bad, "failed", actor="google", data={"stage": "write", "reason": bad.last_error})
done = executor.propose(db, tenant, g, "description_improve", proposed="Gomti Physio is a physiotherapy clinic in Lucknow for back care and neck pain. Call us to book a visit or ask a question about our services.",
                        source={"kind": "owner_input", "user_id": str(uid)}, trigger="owner_request", problem="The description is weak.", reason="Seeded demo record.", proposed_by="user", user_id=uid)
for ev, data in (("approved", {"basis": "owner"}), ("executing", {"attempt": 1}), ("google_write", {"seeded": True}), ("read_back", {"matched": True}), ("verified", {"matched": True})):
    history.record(db, done, ev, actor="system", data=data)
done.status, done.executed_at, done.verified_at = "executed", utcnow(), utcnow()
done.verification = {"matched": True, "detail": "Seeded demo record: no Google call was made."}
# the map: two scans of one 3x3 grid, the second much better, so the change panel has something real to say
kw = RankKeyword(tenant_id=tid, google_location_id=g.id, keyword="physiotherapist near me")
db.add(kw); db.flush()
pts = rg.square_points(26.85, 80.95, 3, 1000)
grid = RankGrid(tenant_id=tid, google_location_id=g.id, name="Around the clinic", mode="square", size=3, spacing_m=1000, points=pts, points_hash=rg.hash_points(pts))
db.add(grid); db.flush()
for days, ranks in ((8, [12, None, None, 15, 9, None, None, 18, 14]), (1, [2, 1, 4, 3, 1, 8, 2, 5, 11])):
    sc = RankGridScan(tenant_id=tid, google_location_id=g.id, grid_id=grid.id, keyword_id=kw.id, points_hash=grid.points_hash, source="manual", status="running", started_at=utcnow() - timedelta(days=days))
    db.add(sc); db.flush()
    rows = [RankGridPoint(tenant_id=tid, scan_id=sc.id, point_index=i, lat=p["lat"], lng=p["lng"], status="ok", rank=ranks[i], results_seen=20, checked_at=sc.started_at) for i, p in enumerate(pts)]
    db.add_all(rows); db.flush()
    sc.calls = 9; rg._aggregate(sc, rows); sc.status, sc.finished_at = "done", sc.started_at; sc.change = rg.change_for(db, sc)
db.commit()
print("seeded", hours.status, cat.status)
`));
    sql(`UPDATE subscriptions SET limits = '{"geo": {"max_grids": 2, "max_points": 9, "monthly_points": 150}}'::jsonb WHERE tenant_id = '${tenant.id}';`);  // the shipped plans have NO map allowance until the owner approves one; this test business has been given one
    ready = true;
  } catch (e) { console.log('SETUP FAILED:', e.message); results.push(['setup', false, e.message]); }

  if (ready) {
    await step('the owner finds Autonomy in the AI section and the page opens off, asking for nothing', async () => {
      await page.goto('/settings/ai/autonomy');
      await page.getByRole('heading', { level: 1, name: 'Autonomy' }).waitFor({ timeout: 30000 });
      const rail = page.getByRole('navigation', { name: 'AI pages', exact: true });
      await rail.waitFor({ timeout: 20000 });
      expect((await rail.getByRole('link', { name: 'Autonomy', exact: true }).getAttribute('aria-current')) === 'page', 'Autonomy is not marked current in the AI rail');
      await page.getByText('Off', { exact: true }).first().waitFor();
      await page.getByText('FlowQR will suggest changes but never make one without a person approving it.').waitFor();
      await page.screenshot({ path: path.join(OUT, 'autonomy-1-overview.png'), fullPage: true });
    });
    await step('the map shows every measured point with its position, a legend and what changed since last time', async () => {
      await page.goto('/seo/rank');
      await page.getByText('Map view').waitFor({ timeout: 30000 });
      const map = page.getByRole('img', { name: /Map of 9 measured points/ });
      await map.waitFor({ timeout: 20000 });
      expect((await map.getAttribute('aria-label')).includes('7 are in the top 3') || /\d are in the top 3/.test(await map.getAttribute('aria-label')), 'map label does not say how many are in the top 3');
      expect(await map.locator('div').count() === 9, 'the map does not draw 9 points');
      await page.getByText('In the top 3').first().waitFor();
      await page.getByText(/Significant change: improved/).waitFor({ timeout: 20000 });
      await page.getByText(/not proof of why it changed/).waitFor();
      expect(await page.getByText(/map searches left this month/).count() === 1, 'the allowance is not shown');
      await page.screenshot({ path: path.join(OUT, 'autonomy-6-map.png'), fullPage: true });
    });
    await step('what is waiting shows what is on Google now, what it would become, the level, and who decides', async () => {
      await page.goto('/settings/ai/autonomy');
      await tab(/^Needs you/).waitFor();
      const card = page.locator('li', { hasText: 'Regular opening hours' }).first();
      await card.waitFor({ timeout: 20000 });
      const text = await card.innerText();
      expect(/Level 2/.test(text) && /On Google now/.test(text) && /Would become/.test(text) && /Tue 10:00-17:30/.test(text), 'level-2 card is incomplete: ' + text.slice(0, 200));
      const l3 = page.locator('li', { hasText: 'Primary category' }).first();
      expect(/Level 3: owner only/.test(await l3.innerText()), 'the main-category card is not marked Level 3');
      expect(await l3.getByRole('button', { name: /Approve/ }).isEnabled(), 'the owner cannot approve a level-3 change');
    });
    await step('rejecting needs a reason, and the rejection is recorded', async () => {
      const card = page.locator('li', { hasText: 'Primary category' }).first();
      await card.getByRole('button', { name: 'Reject' }).click();
      const confirm = card.getByRole('button', { name: 'Confirm rejection' });
      expect(await confirm.isDisabled(), 'rejection can be confirmed without a reason');
      await card.getByLabel(/Why are you rejecting/).fill('We are physiotherapists, not chiropractors.');
      await confirm.click();
      await toast('Rejected');
      await page.getByText('Primary category').first().waitFor({ state: 'detached', timeout: 20000 }).catch(() => {});
    });
    await step('approving shows the honest result when Google cannot be reached (nothing is claimed as done)', async () => {
      const card = page.locator('li', { hasText: 'Regular opening hours' }).first();
      await card.getByRole('button', { name: /Approve/ }).click();
      // the seeded connection has no real token: the engine must report that it could not confirm the change, not a success
      await page.getByRole('status').filter({ hasText: /./ }).first().waitFor({ timeout: 30000 });
      const msg = (await page.getByRole('status').allInnerTexts()).join(' ');
      expect(!/Done\. Google's own profile now shows it/.test(msg), 'the page claimed success without Google confirming: ' + msg.slice(0, 200));
    });
    await step('the activity tab lists a confirmed change and its record shows every step and an intact history', async () => {
      await tab('Activity').click();
      const line = page.getByRole('button', { name: /Description improvement from verified facts.*Confirmed on Google/ }).first();
      await line.waitFor({ timeout: 20000 });
      await line.click();
      const dlg = page.getByRole('dialog');
      await dlg.waitFor();
      await dlg.getByText(/Record intact|Record problem/).waitFor({ timeout: 20000 });
      const t = await dlg.innerText();
      expect(/Confirmed: Google shows the change/.test(t) && /Read the profile back from Google/.test(t) && /Record intact/.test(t), 'record is missing steps: ' + t.slice(0, 300));
      await page.screenshot({ path: path.join(OUT, 'autonomy-2-record.png'), fullPage: true });
      await dlg.getByRole('button', { name: 'Close' }).first().click();
    });
    await step('the problems tab says what failed and why in plain words', async () => {
      await tab(/^Problems/).click();
      await page.getByText(/Google denied the request/).first().waitFor({ timeout: 20000 });
      await page.screenshot({ path: path.join(OUT, 'autonomy-3-problems.png'), fullPage: true });
    });
    await step('permissions: public content can never be set to run on its own; a safe kind can, and it persists', async () => {
      await tab('Permissions').click();
      const posts = page.locator('li', { hasText: 'Publish an approved Google Post' }).first();
      await posts.waitFor({ timeout: 20000 });
      expect(/Always asks a person/.test(await posts.innerText()), 'a post can be set to run on its own');
      const hours = page.locator('li', { hasText: 'Regular opening hours' }).first();
      await hours.getByRole('radio', { name: 'Do it' }).click();
      await page.getByRole('button', { name: 'Save permissions' }).click();
      await toast('Permissions saved');
      await page.reload();
      await tab('Permissions').click();
      expect(await page.locator('li', { hasText: 'Regular opening hours' }).first().getByRole('radio', { name: 'Do it' }).getAttribute('aria-checked') === 'true', 'the permission did not persist');
      const cat = page.locator('li', { hasText: 'Primary category' }).first();
      expect(/Always asks a person/.test(await cat.innerText()), 'a level-3 type can be pre-authorised');
      await page.screenshot({ path: path.join(OUT, 'autonomy-4-permissions.png'), fullPage: true });
    });
    await step('turning autonomy on explains what it allows first; the emergency stop stops it and nothing runs until it is resumed', async () => {
      await page.getByRole('button', { name: 'Turn on' }).click();
      const dlg = page.getByRole('dialog');
      expect(/never sent without a person approving each one/.test(await dlg.innerText()), 'the confirmation does not say posts, photos and replies always need a person');
      await dlg.getByRole('button', { name: 'Turn on' }).click();
      await toast('Autonomy is on');
      await page.getByText('On', { exact: true }).first().waitFor();
      await page.getByRole('button', { name: 'Emergency stop' }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Stop autonomy' }).click();
      await toast('Stopped');
      await page.getByText('Stopped', { exact: true }).first().waitFor();
      expect(await page.getByRole('button', { name: 'Turn on' }).count() === 0, 'a stopped business can be switched straight back on without Resume');
      await page.getByRole('button', { name: 'Resume' }).click();
      await toast('Resumed');
    });
    await step('usage shows this month against the limits', async () => {
      await tab('Usage').click();
      await page.getByText('AI review generations', { exact: true }).waitFor({ timeout: 20000 });
      await page.getByText('AI review replies', { exact: true }).waitFor();
      await page.getByText('Ranking checks (Google)').waitFor();
      expect(await page.getByRole('progressbar').count() >= 3, 'no usage meters');
      await page.screenshot({ path: path.join(OUT, 'autonomy-5-usage.png'), fullPage: true });
    });
    await step('phone width: no horizontal scroll, tabs reachable, the cards stay readable', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      for (const u of ['/settings/ai/autonomy', '/seo/rank']) {
        await page.goto(u);
        await page.locator('h1').first().waitFor({ timeout: 30000 });
        await page.waitForLoadState('networkidle');
        const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(over <= 1, `${u} scrolls sideways by ${over}px`);
      }
      await page.goto('/settings/ai/autonomy');
      await tab(/^Needs you/).waitFor();
      await tab('Usage').click();
      await page.getByText('AI review generations', { exact: true }).waitFor();
      await page.screenshot({ path: path.join(OUT, 'autonomy-7-mobile.png'), fullPage: true });
      await page.setViewportSize({ width: 1280, height: 900 });
    });
    await step('the settings endpoint refuses a policy level and reports the owner flags (the staff-role rules are covered by the backend tests)', async () => {
      const cc = await (await ctx.request.get('/api/v1/agent/control-centre')).json();
      expect(cc.is_owner === true && cc.can_decide === true, 'owner flags are wrong');
      const put = await ctx.request.put('/api/v1/agent/autonomy-settings', { data: { level: 1 }, headers: H() });
      expect(put.status() === 422, 'a level can be sent to the settings endpoint: ' + put.status());
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
