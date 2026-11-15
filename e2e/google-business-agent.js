// FlowQR browser E2E for the Google Business AI agent: the GBP overview, photo library + scheduler, offer/event posts, search keywords,
// the profile optimizer, reply tone/language, review request templates and the reply assistant's batch approval.
//
//   node e2e/google-business-agent.js      (BASE_URL defaults to http://localhost:3000; CHROME_PATH=<system Chrome/Edge> with playwright-core)
//
// It creates one throwaway business ("ZZ-GBA-<id>") and removes it at the end.
//
// WHAT THIS DOES AND DOES NOT PROVE (MOCKED, not live)
//  * The Google connection, location, reviews and snapshot are SEEDED rows. Every browser request to a Google-backed endpoint that would
//    reach Google (/gbp/*/library/coverage, /gbp/*/keywords, /gbp/*/performance, /gbp/*/media) is answered locally with page.route, so
//    the UI is checked against Google-shaped data without calling Google. Live Google reads are verified separately by `google-smoke`.
//  * Nothing here is published to Google. The photo is uploaded into FlowQR's library and approved; the scheduler is not run.
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
const NAME = `ZZ-GBA-${TAG}`;
const results = [];
// Playwright rejects a pending navigation promise when the browser closes at the end of the run; that must not skip cleanup and the summary.
process.on('unhandledRejection', (e) => { if (!/Target page, context or browser has been closed/.test(String(e && e.message))) { console.error(e); process.exitCode = 1; } });

const docker = (args, input) => execFileSync('docker', ['compose', 'exec', '-T', ...args], { cwd: ROOT, input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
const seed = (code) => docker(['api', 'sh', '-c', 'cd /srv && PYTHONPATH=/srv python -'], code).trim();
const sql = (q) => docker(['db', 'psql', '-U', 'flowqr', '-d', 'flowqr', '-At', '-v', 'ON_ERROR_STOP=1'], `BEGIN; SELECT set_config('app.bypass_rls','on',true); ${q} COMMIT;`).trim();
function expect(cond, msg) { if (!cond) throw new Error(msg); }

/** A small but valid JPEG made in the browser (900x700 noise, well above Google's 10 KB / 250 px minimum). */
async function makeJpeg(page) {
  const b64 = await page.evaluate(async () => {
    const c = document.createElement('canvas'); c.width = 900; c.height = 700;
    const x = c.getContext('2d'); const d = x.createImageData(900, 700);
    for (let i = 0; i < d.data.length; i++) d.data[i] = (i % 4 === 3) ? 255 : Math.floor(Math.random() * 255);
    x.putImageData(d, 0, 0);
    const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.9));
    const buf = new Uint8Array(await blob.arrayBuffer()); let s = ''; for (const v of buf) s += String.fromCharCode(v); return btoa(s);
  });
  return Buffer.from(b64, 'base64');
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  const ctx = await browser.newContext({ baseURL: BASE, viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const pageErrors = []; const httpErrors = [];
  page.on('pageerror', (e) => pageErrors.push(e.message));
  page.on('response', (r) => { if (r.status() >= 500) httpErrors.push(`${r.status()} ${r.url()}`); });
  // Every /gbp/... call that would reach Google is answered locally with Google-shaped data (see header). FlowQR's own photo library
  // (/gbp/<id>/library, but not /library/coverage) goes to the real API. Without this the seeded fake token would be sent to Google,
  // Google would refuse it, and FlowQR would (correctly) mark the connection revoked for every later step.
  const STUB = {
    coverage: { on_google: { EXTERIOR: 2 }, total_on_google: 2, note: 'stub',
      suggestions: [['COVER', 'Cover photo'], ['EXTERIOR', 'Exterior'], ['INTERIOR', 'Interior'], ['TEAMS', 'Team']].map(([category, label]) => ({ category, label, on_google: category === 'EXTERIOR', pending: false })) },
    keywords: { from_month: '2026-08', to_month: '2026-10', note: 'stub', keywords: [{ keyword: 'physiotherapist near me', value: 120, below: null }, { keyword: 'back pain clinic', value: null, below: 15 }] },
    performance: { from: '', to: '', note: 'stub', totals: { CALL_CLICKS: 5 }, series: { CALL_CLICKS: [{ date: '2026-10-01', value: 5 }] } },
    info: { title: 'GBA Main', description: 'Physio.', phone: '+91 98765 43210', website: 'https://clinic.example.com', primary_category: { id: 'c', name: 'Physiotherapist' }, additional_categories: [], hours: [] },
  };
  await page.route('**/api/v1/gbp/**', (route) => {
    const u = new URL(route.request().url()).pathname;
    if (u.includes('/library') && !u.endsWith('/coverage')) return route.continue();
    if (u.includes('/rank')) return route.continue();  // FlowQR's own rank API (the check itself makes ONE real Places search with the server's key)
    if (u.endsWith('/coverage')) return route.fulfill({ json: STUB.coverage });
    if (u.endsWith('/keywords')) return route.fulfill({ json: STUB.keywords });
    if (u.endsWith('/performance')) return route.fulfill({ json: STUB.performance });
    if (u.endsWith('/info')) return route.fulfill({ json: STUB.info });
    if (u.endsWith('/categories')) return route.fulfill({ json: [] });
    return route.fulfill({ json: [] });  // media, posts lists
  });

  async function step(name, fn) {
    try { await fn(); results.push([name, true]); console.log('PASS', name); if (process.env.SHOOT) await page.screenshot({ path: path.join(OUT, `gba-${results.length}-desktop.png`), fullPage: true }).catch(() => {}); }
    catch (e) {
      results.push([name, false, String(e.message).split('\n')[0].slice(0, 300)]);
      console.log('FAIL', name, '\n     ', String(e.message).split('\n')[0].slice(0, 300));
      await page.screenshot({ path: path.join(OUT, `fail-gba-${results.length}.png`), fullPage: true }).catch(() => {});
    }
  }
  const toast = (text) => page.getByRole('status').filter({ hasText: text }).first().waitFor({ timeout: 20000 });

  let csrf, tenant, locA, gid, ready = false;
  const H = () => ({ 'X-CSRF-Token': csrf });
  try {
    let r = await ctx.request.post('/api/v1/auth/register', { data: { email: `zz-gba-${TAG}@example.com`, password: PW, full_name: 'ZZ GBA Owner' } });
    expect(r.status() === 201, `register ${r.status()} ${await r.text()}`);
    csrf = (await r.json()).csrf_token;
    tenant = await (await ctx.request.post('/api/v1/tenants', { data: { name: NAME, category: 'Physiotherapy clinic', language: 'en' }, headers: H() })).json();
    locA = await (await ctx.request.post('/api/v1/locations', { data: { name: 'GBA Main', city: 'Lucknow', review_url: 'https://g.page/r/ABC123/review' }, headers: H() })).json();
    await ctx.request.post('/api/v1/tenant/complete-onboarding', { headers: H() });
    gid = seed(`
import uuid
from datetime import timedelta
from sqlalchemy import text
from app.core.db import system_session
from app.models import GbpSnapshot, GoogleConnection, GoogleConnectionStatus, GoogleLocation, ReplyDraft, ReplyStatus, Review
from app.models.base import utcnow
db = system_session()
db.execute(text("UPDATE users SET email_verified_at = now() WHERE email = 'zz-gba-${TAG}@example.com'"))
tid, lid = uuid.UUID("${tenant.id}"), uuid.UUID("${locA.id}")
c = GoogleConnection(tenant_id=tid, google_email="seeded-gba@example.com", google_sub="seeded-gba-${TAG}", status=GoogleConnectionStatus.active, api_access="approved", connected_at=utcnow())
db.add(c); db.flush()
g = GoogleLocation(tenant_id=tid, connection_id=c.id, location_id=lid, google_account_name="accounts/1", google_location_name="locations/1", title="GBA Main (Google)", selected=True, last_synced_at=utcnow(), last_sync_status="ok")
db.add(g); db.flush()
for i, (rating, t, sensitive) in enumerate([(5, "Lovely and friendly staff", False), (4, "Good clinic, parking is hard", False), (1, "I will take you to court", True)]):
    rv = Review(tenant_id=tid, location_id=lid, google_location_id=g.id, external_id=f"gba-{i}", rating=rating, text=t, reviewer_name=["Asha", "Ravi", "Meera"][i],
                review_created_at=utcnow() - timedelta(days=i + 1), first_seen_at=utcnow())
    db.add(rv); db.flush()
    db.add(ReplyDraft(tenant_id=tid, review_id=rv.id, body="Thank you for your feedback. We'd love to hear more.", language="en", generated_by_ai=True,
                      requires_human_handling=sensitive, flag_reasons=["legal"] if sensitive else [], status=ReplyStatus.draft))
db.add(GbpSnapshot(tenant_id=tid, google_location_id=g.id, fetched_at=utcnow(), media=[{"name": "m1", "category": "EXTERIOR", "created_at": utcnow().isoformat()}], posts=[],
    info={"title": "Best Physio | Gomti Nagar", "description": "Physio.", "phone": "+91 98765 43210", "website": "https://clinic.example.com", "primary_category": {"id": "c", "name": "Physiotherapist"},
          "additional_categories": [], "hours": [], "services": [], "special_hours": [], "open_status": "OPEN"},
    performance={"current": 40, "previous": 30, "window_days": 28, "from": "2026-10-01", "to": "2026-10-28", "metrics": [],
                 "keywords": [{"keyword": "physiotherapist near me", "value": 120, "below": None}], "keywords_months": ["2026-08", "2026-10"]}))
db.commit()
print(g.id)
`).split('\n').pop();
    await page.goto('/overview');  // registering through ctx.request already signed this browser context in
    await page.getByRole('navigation', { name: 'Main' }).waitFor({ timeout: 30000 });
    ready = true;
  } catch (e) { console.log('SETUP FAILED:', e.message); results.push(['setup', false, e.message]); }

  if (ready) {
    await step('GBP overview is the entry point: six modules with live status', async () => {
      await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'GBP Manager' }).click();
      await page.waitForURL('**/gbp');
      for (const h of ['AI review replies', 'Profile optimizer', 'Review growth', 'Google posts', 'Photos', 'Performance']) await page.getByRole('heading', { name: h, exact: true }).waitFor({ timeout: 20000 });
      await page.getByText('drafts waiting for approval').waitFor();
    });
    await step('profile optimizer: checks from Google data, name-keyword rule, search terms', async () => {
      await page.goto('/gbp/info');
      await page.getByRole('heading', { name: 'Profile optimizer' }).waitFor({ timeout: 20000 });
      const txt = await page.locator('main').innerText();
      expect(/Opening hours/.test(txt) && /Services/.test(txt), 'missing hours/services checks');
      expect(txt.includes('never suggests adding keywords'), 'business-name rule not shown');
      await page.locator('text=physiotherapist near me >> visible=true').first().waitFor();  // the collapsed "Why this matters" text mentions it too, so only a visible match counts
    });
    await step('photos: coverage, validation-first upload, approval with a time; nothing claims to be live', async () => {
      await page.goto('/gbp/photos');
      await page.getByRole('heading', { name: 'Photo types on Google' }).waitFor({ timeout: 20000 });
      await page.getByText('Missing: add one').first().waitFor();
      await page.locator('input[type=file]').setInputFiles({ name: 'front.jpg', mimeType: 'image/jpeg', buffer: await makeJpeg(page) });
      await page.getByRole('radio', { name: 'Exterior' }).click();
      await page.getByRole('button', { name: 'Add to library' }).click();
      await toast('Approve it below');
      await page.getByText('Waiting for approval').first().waitFor();
      await page.getByRole('button', { name: 'Approve now' }).click();
      await page.getByText('Scheduled', { exact: true }).first().waitFor({ timeout: 20000 });
      // only the photo cards count: the page's own explanation mentions "Live on Google" as a state
      expect(!(await page.getByRole('listitem').filter({ hasText: 'Live on Google' }).count()), 'a photo claimed to be live without Google');
    });
    await step('posts: offer needs a title and dates; the preview shows the offer like Google does', async () => {
      await page.goto('/gbp/posts');
      await page.getByRole('radio', { name: 'Offer' }).click();
      await page.getByLabel('Offer title').fill('Winter check-up');
      await page.getByLabel('Starts').fill('2030-01-01T09:00');
      await page.getByLabel('Ends').fill('2030-01-31T18:00');
      await page.getByLabel('Details').fill('A posture and mobility check for anyone with winter back stiffness.');
      const preview = page.getByRole('figure', { name: 'Preview of this post on Google' });
      expect(/Offer ·/.test(await preview.innerText()) && /Winter check-up/.test(await preview.innerText()), 'offer preview missing title/type');
      await page.getByRole('button', { name: 'Save draft' }).click();
      await toast('Draft saved');
    });
    await step('performance: search terms keep Google\'s "fewer than" values', async () => {
      await page.goto('/overview/performance');
      await page.getByRole('heading', { name: 'What people searched' }).waitFor({ timeout: 20000 });
      await page.getByText('< 15').waitFor();
      await page.getByRole('heading', { name: 'What these numbers mean' }).waitFor();
    });
    await step('reply assistant: batch approval excludes flagged reviews', async () => {
      await page.goto('/ai');
      const b = page.getByRole('button', { name: /Approve & publish 2 unflagged/ });
      await b.waitFor({ timeout: 20000 });
      await page.getByText('Needs you personally').first().waitFor();
    });
    await step('review detail: tone and language choices are offered', async () => {
      await page.goto('/gbp/reviews');
      await page.getByRole('link', { name: /Asha/ }).first().click();
      await page.getByRole('combobox', { name: 'Reply tone' }).selectOption('brief');
      await page.getByRole('combobox', { name: 'Reply language' }).selectOption('hi');
    });
    await step('review request templates refuse incentives and fill in the campaign link', async () => {
      const camp = await (await ctx.request.post('/api/v1/review-growth/campaigns', { data: { name: 'GBA counter', location_id: locA.id }, headers: H() })).json();
      await page.goto(`/gbp/campaigns/${camp.id}`);
      await page.getByRole('heading', { name: 'Ask customers for a review' }).waitFor({ timeout: 20000 });
      await page.getByRole('button', { name: /WhatsApp after a visit/ }).click();
      await page.getByRole('textbox', { name: 'Message' }).fill('Leave us 5 stars and get a free gift: {link}');
      await page.getByRole('button', { name: 'Save template' }).click();
      await page.getByText(/rewards for reviews aren't allowed/i).waitFor();
      await page.getByRole('textbox', { name: 'Message' }).fill('Hi {customer}, please share your honest experience of {business}: {link}');
      await page.getByRole('button', { name: 'Save template' }).click();
      await toast('Template saved');
      await page.locator('button[aria-pressed]').filter({ hasText: 'WhatsApp after a visit' }).first().click();  // the saved template, not the preset
      await page.getByText(/\/r\//).first().waitFor();
    });
    if (process.env.SHOOT) {  // phone-width pass of the same pages (screenshots only; reviewed by hand)
      await page.setViewportSize({ width: 390, height: 844 });
      for (const [n, u] of [['gbp', '/gbp'], ['photos', '/gbp/photos'], ['info', '/gbp/info'], ['posts', '/gbp/posts'], ['perf', '/overview/performance'], ['ai', '/ai'], ['automations', '/ai/automations'], ['notfound', '/no-such-page']]) {
        await page.goto(u); await page.waitForTimeout(1500);
        await page.screenshot({ path: path.join(OUT, `mobile-${n}.png`), fullPage: true }).catch(() => {});
      }
      await page.setViewportSize({ width: 1280, height: 900 });
      for (const [n, u] of [['automations', '/ai/automations'], ['notfound', '/no-such-page']]) {
        await page.goto(u); await page.waitForTimeout(1500);
        await page.screenshot({ path: path.join(OUT, `desktop-${n}.png`), fullPage: true }).catch(() => {});
      }
    }
    await step('local ranking: add a term, run a real Places check, see a dated result; old URL redirects', async () => {
      // The seeded location gets a position so the check needs no place lookup; its place ID is not a real place, so the honest result is "Not in top 20".
      sql(`UPDATE google_locations SET place_id = 'ChIJ-e2e-seeded', lat = 26.8467, lng = 80.9462 WHERE id = '${gid}';`);
      await page.goto('/gbp');
      await page.getByRole('link', { name: /Local ranking/ }).first().click();
      await page.waitForURL('**/gbp/rank');
      await page.getByRole('heading', { name: 'Where you appear for the searches that matter' }).waitFor({ timeout: 20000 });
      await page.getByLabel('Add a search term').fill('physiotherapy');
      await page.getByRole('button', { name: 'Add', exact: true }).click();
      await toast('Search term added');
      await page.getByText('Not measured yet').waitFor();
      await page.getByRole('button', { name: 'Check physiotherapy now' }).click();
      await toast('Checked 1 search term');
      await page.getByText('Not in top 20').first().waitFor({ timeout: 20000 });
      await page.getByText(/Measured .* · 20 results read/).waitFor();
      await page.getByRole('button', { name: 'Who ranks above' }).click();
      expect(await page.locator('ol > li').count() >= 10, 'competitor list should show the real top results');
      await page.getByText(/checks left this month/).waitFor();
      expect(!(await page.content()).includes('AIza'), 'the Places key must never reach the browser');
      await page.goto('/overview/visibility');
      await page.waitForURL('**/gbp/rank');
      await page.getByRole('button', { name: 'Remove physiotherapy' }).click();
      await toast('Removed');
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
      DELETE FROM audit_logs WHERE tenant_id IN (SELECT id FROM tenants WHERE name = '${NAME}') OR user_id IN (SELECT id FROM users WHERE email LIKE 'zz-gba-%${TAG}@example.com');
      DELETE FROM tenants WHERE name = '${NAME}';
      DELETE FROM users WHERE email LIKE 'zz-gba-%${TAG}@example.com';
      SELECT 'left: ' || (SELECT count(*) FROM tenants WHERE name = '${NAME}') || ' tenants';`);
    console.log('cleanup', left.split('\n').pop());
  } catch (e) { console.log('CLEANUP FAILED (remove ' + NAME + ' by hand):', String(e.message).slice(0, 300)); }
  const failed = results.filter((r) => !r[1]);
  console.log(`\n${results.length - failed.length}/${results.length} browser checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
