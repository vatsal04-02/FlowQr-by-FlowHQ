// FlowQR browser E2E for QR permanence, QR design/export, card pause/resume, staff location access and the Google
// connection states. Drives the real UI in Chromium against a RUNNING local stack (docker compose up).
//
//   npm i --no-save playwright && npx playwright install chromium        (or: playwright-core + CHROME_PATH=<system Chrome>)
//   node e2e/qr-and-access.js                                             (BASE_URL defaults to http://localhost:3000)
//
// It creates one throwaway business ("ZZ-E2E-<id>") and removes it at the end. Because cards are issued by the platform
// admin and emails are not delivered locally, setup and cleanup go through `docker compose exec` (seed() / sql() below).
//
// GOOGLE: nothing here talks to Google. The "Connect Google" step stops at the redirect to accounts.google.com, and the
// three connection states (API switched off / awaiting approval / access revoked) are SEEDED database rows. This proves the
// UI tells those states apart; it proves nothing about the live Business Profile API.
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
const PHONE_UA = 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36';
const results = [];

const docker = (args, input) => execFileSync('docker', ['compose', 'exec', '-T', ...args], { cwd: ROOT, input, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
const seed = (code) => docker(['api', 'python', '-'], code).trim();
const sql = (q) => docker(['db', 'psql', '-U', 'flowqr', '-d', 'flowqr', '-At', '-v', 'ON_ERROR_STOP=1'], `BEGIN; SELECT set_config('app.bypass_rls','on',true); ${q} COMMIT;`).trim();

function expect(cond, msg) { if (!cond) throw new Error(msg); }

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  const ctx = await browser.newContext({ baseURL: BASE, viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const pageErrors = [];
  const httpErrors = [];
  page.on('pageerror', (e) => pageErrors.push(e.message));
  page.on('response', (r) => { if (r.status() >= 500) httpErrors.push(`${r.status()} ${r.url()}`); });

  async function step(name, fn) {
    try { await fn(); results.push([name, true]); console.log('PASS', name); }
    catch (e) {
      results.push([name, false, String(e.message).split('\n')[0].slice(0, 300)]);
      console.log('FAIL', name, '\n     ', String(e.message).split('\n')[0].slice(0, 300));
      await page.screenshot({ path: path.join(OUT, `fail-${results.length}.png`), fullPage: true }).catch(() => {});
    }
  }
  const toast = (text) => page.getByRole('status').filter({ hasText: text }).first().waitFor({ timeout: 15000 });
  const publicGet = async (p) => { const r = await ctx.request.get(p, { headers: { 'User-Agent': PHONE_UA } }); let body = null; try { body = await r.json(); } catch { /* html */ } return { status: r.status(), body }; };
  const download = async (click) => {
    const [d] = await Promise.all([page.waitForEvent('download', { timeout: 30000 }), click()]);
    const file = await d.path();
    return { name: d.suggestedFilename(), bytes: fs.readFileSync(file) };
  };

  // ------------------------------------------------------------------ setup (API + seed)
  let csrf, tenant, locA, locB, campaign, cards = [], staffCtx, staffEmail = `zz-e2e-staff-${TAG}@example.com`;
  const H = () => ({ 'X-CSRF-Token': csrf });
  try {
    let r = await ctx.request.post('/api/v1/auth/register', { data: { email: `zz-e2e-${TAG}@example.com`, password: PW, full_name: 'ZZ E2E Owner' } });
    expect(r.status() === 201, `register ${r.status()} ${await r.text()}`);
    csrf = (await r.json()).csrf_token;
    tenant = await (await ctx.request.post('/api/v1/tenants', { data: { name: `ZZ-E2E-${TAG}`, category: 'Physiotherapy clinic', language: 'en' }, headers: H() })).json();
    locA = await (await ctx.request.post('/api/v1/locations', { data: { name: 'E2E Main', city: 'Lucknow', review_url: 'https://g.page/r/ABC123/review' }, headers: H() })).json();
    locB = await (await ctx.request.post('/api/v1/locations', { data: { name: 'E2E Branch', city: 'Kanpur', review_url: 'https://g.page/r/XYZ789/review' }, headers: H() })).json();
    await ctx.request.post('/api/v1/tenant/complete-onboarding', { headers: H() });
    campaign = await (await ctx.request.post('/api/v1/review-growth/campaigns', { data: { name: 'E2E front desk', location_id: locA.id }, headers: H() })).json();
    expect(campaign.public_id, 'campaign not created: ' + JSON.stringify(campaign).slice(0, 200));

    staffCtx = await browser.newContext({ baseURL: BASE, viewport: { width: 1280, height: 900 } });
    r = await staffCtx.request.post('/api/v1/auth/register', { data: { email: staffEmail, password: PW, full_name: 'ZZ E2E Staff' } });
    expect(r.status() === 201, `staff register ${r.status()}`);

    seed(`
import uuid
from sqlalchemy import select, text
from app.core.db import system_session
from app.models import Location, Membership, QRCard, Role, Tenant, User
from app.models.base import utcnow
from app.services import cards as svc
db = system_session()
db.execute(text("UPDATE users SET email_verified_at = now() WHERE email LIKE 'zz-e2e-%${TAG}@example.com'"))
t, loc = db.get(Tenant, uuid.UUID("${tenant.id}")), db.get(Location, uuid.UUID("${locA.id}"))
b = svc.create_batch(db, name="ZZ-E2E-${TAG}", quantity=2, prefix="ZZE", created_by=None, notes="temporary e2e batch")
for c in db.scalars(select(QRCard).where(QRCard.batch_id == b.id)):
    svc.assign_card(db, c, tenant=t, location=loc, by=None)
uid = db.scalar(select(User.id).where(User.email == "${staffEmail}"))
db.add(Membership(tenant_id=t.id, user_id=uid, role=Role.staff))
db.commit()
`);
    cards = await (await ctx.request.get('/api/v1/cards')).json();
    expect(cards.length === 2, 'expected 2 seeded cards, got ' + cards.length);
  } catch (e) {
    console.log('SETUP FAILED:', e.message);
    results.push(['setup', false, e.message]);
  }

  if (results.length === 0) {
    const card = cards[0];
    // ------------------------------------------------------------------ 1. Google onboarding
    await step('google: page explains manual mode and offers to connect', async () => {
      await page.goto('/google');
      await page.getByText('Manual review-link mode').waitFor({ timeout: 20000 });
      await page.getByRole('button', { name: 'Connect Google' }).waitFor();
    });
    await step('google: Connect sends the browser to Google with offline access and only the business scope', async () => {
      let authUrl = null;
      await page.route('https://accounts.google.com/**', async (route) => { authUrl = route.request().url(); await route.fulfill({ status: 200, contentType: 'text/html', body: '<h1>stub: Google consent screen</h1>' }); });
      await page.goto('/google');
      await page.getByRole('button', { name: 'Connect Google' }).click();
      await page.waitForURL('https://accounts.google.com/**', { timeout: 20000 });
      await page.unroute('https://accounts.google.com/**');
      const u = new URL(authUrl);
      expect(u.searchParams.get('access_type') === 'offline' && u.searchParams.get('prompt') === 'consent', 'offline access not requested');
      expect(u.searchParams.get('scope') === 'openid email https://www.googleapis.com/auth/business.manage', 'unexpected scope: ' + u.searchParams.get('scope'));
      expect((u.searchParams.get('redirect_uri') || '').endsWith('/api/v1/google/callback') && u.searchParams.get('state'), 'redirect_uri/state missing');
    });
    await step('google: declining on Google and an unticked permission each get their own message', async () => {
      await page.goto('/api/v1/google/callback?error=access_denied');
      await page.waitForURL('**/google?error=access_denied');
      await page.getByText('You declined access, so nothing was connected.').waitFor();
      await page.goto('/google?error=scope_missing');
      await page.getByText('the Business Profile permission was not granted').waitFor();
      const s = await (await ctx.request.get('/api/v1/google/status')).json();
      expect(s.connections.length === 0, 'a connection was stored after a failed connect');
    });
    const setConn = (status, access, err) => seed(`
import uuid
from sqlalchemy import select
from app.core.db import system_session
from app.models import GoogleConnection, GoogleConnectionStatus
from app.models.base import utcnow
db = system_session()
c = db.scalar(select(GoogleConnection).where(GoogleConnection.tenant_id == uuid.UUID("${tenant.id}")))
if c is None:
    c = GoogleConnection(tenant_id=uuid.UUID("${tenant.id}"), google_email="seeded-e2e@example.com", google_sub="seeded-${TAG}", connected_at=utcnow())
    db.add(c)
c.status, c.api_access, c.last_error = GoogleConnectionStatus("${status}"), "${access}", ${err ? JSON.stringify(err) : 'None'}
db.commit()
`);
    await step('google (seeded state): "API switched off" names the API and is not called awaiting approval', async () => {
      setConn('error', 'api_disabled', "A required Google Business Profile API is not enabled on FlowQR's Google Cloud project (mybusinessaccountmanagement.googleapis.com).");
      await page.goto('/google');
      await page.getByText('A Google API is switched off for FlowQR').waitFor({ timeout: 20000 });
      await page.getByText('mybusinessaccountmanagement.googleapis.com').first().waitFor();
      expect(await page.getByText('Awaiting Google approval').count() === 0, 'api-disabled state also shows awaiting approval');
    });
    await step('google (seeded state): "awaiting approval" is shown as its own state', async () => {
      setConn('error', 'awaiting_approval', 'Google has not yet approved FlowQR for Business Profile API access (quota 0).');
      await page.goto('/google');
      await page.getByText('Awaiting Google approval').waitFor({ timeout: 20000 });
      expect(await page.getByText('A Google API is switched off for FlowQR').count() === 0, 'awaiting-approval state also shows API switched off');
    });
    await step('google (seeded state): lost authorization asks to reconnect, and Re-check reports it instead of pretending', async () => {
      await page.getByRole('button', { name: 'Re-check' }).click();   // the seeded row has no token: the server must answer "revoked"
      await toast('revoked');
      await page.goto('/google');
      await page.getByText('Needs attention').waitFor({ timeout: 20000 });
      await page.getByRole('button', { name: 'Reconnect' }).waitFor();
      expect(await page.getByText('Awaiting Google approval').count() === 0, 'revoked state still shows awaiting approval');
      const s = await (await ctx.request.get('/api/v1/google/status')).json();
      expect(s.connections[0].status === 'revoked', 'status is ' + s.connections[0].status);
      const raw = JSON.stringify(s);
      expect(!/refresh_token|access_token/.test(raw), 'token fields exposed to the browser');
    });

    // ------------------------------------------------------------------ 2. QR customisation
    await step('qr design: an unreadable colour is explained and cannot be saved', async () => {
      await page.goto('/qr');
      await page.getByLabel('Code colour hex value').waitFor({ timeout: 20000 });
      await page.getByLabel('Code colour hex value').fill('#FFFF00');
      await page.getByText("This design wouldn't scan reliably").waitFor();
      await page.getByText('These colours are too close').waitFor();
      expect(await page.getByRole('button', { name: 'Save design' }).isDisabled(), 'Save is enabled for an unreadable design');
    });
    await step('qr design: logo upload, colour and caption are saved after the server scan check', async () => {
      const png = await page.evaluate(() => { const c = document.createElement('canvas'); c.width = 320; c.height = 200; const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, 320, 200); g.fillStyle = '#c81e1e'; g.beginPath(); g.ellipse(160, 100, 140, 80, 0, 0, 7); g.fill(); return c.toDataURL('image/png').split(',')[1]; });
      await page.getByLabel('Choose a logo file').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: Buffer.from(png, 'base64') });
      await toast('Logo uploaded');
      await page.getByLabel('Code colour hex value').fill('#1B46B8');
      await page.getByLabel('Put the logo in the middle of the code').check();
      await page.getByLabel('Caption under the code (optional)').fill('Review us');
      await page.getByText('Scan check passed').waitFor({ timeout: 20000 });
      await page.getByRole('button', { name: 'Save design' }).click();
      await toast('Design saved');
      const s = await (await ctx.request.get('/api/v1/qr/style')).json();
      expect(s.style.dark === '#1B46B8' && s.style.use_logo === true && s.style.caption === 'Review us' && s.has_logo && !s.is_default, 'saved style is ' + JSON.stringify(s).slice(0, 200));
      await page.reload();
      await page.getByText('custom design').waitFor({ timeout: 20000 });
    });
    await step('qr design: a wrong file type is refused with a reason', async () => {
      await page.getByLabel('Choose a logo file').setInputFiles({ name: 'logo.gif', mimeType: 'image/gif', buffer: Buffer.from('GIF89a') });
      await page.getByText('The logo must be a PNG, JPEG or WebP image.').waitFor();
    });

    // ------------------------------------------------------------------ 3. downloads
    const magic = { PNG: (b) => b.subarray(0, 8).toString('hex') === '89504e470d0a1a0a', SVG: (b) => b.subarray(0, 4).toString() === '<svg', PDF: (b) => b.subarray(0, 8).toString() === '%PDF-1.4' };
    await step('downloads: card PNG, SVG and PDF', async () => {
      await page.goto(`/cards/${card.id}`);
      await page.getByRole('heading', { name: card.card_code }).waitFor({ timeout: 20000 });
      for (const fmt of ['PNG', 'SVG', 'PDF']) {
        const d = await download(() => page.getByRole('link', { name: fmt, exact: true }).click());
        expect(d.name === `${card.card_code}.${fmt.toLowerCase()}`, `${fmt} filename ${d.name}`);
        expect(magic[fmt](d.bytes) && d.bytes.length > 500, `${fmt} file is not a real ${fmt} (${d.bytes.length} bytes)`);
      }
    });
    await step('downloads: campaign PNG, SVG and PDF', async () => {
      await page.goto(`/review-growth/campaigns/${campaign.id}`);
      await page.getByRole('heading', { name: 'E2E front desk' }).waitFor({ timeout: 20000 });
      for (const fmt of ['PNG', 'SVG', 'PDF']) {
        const d = await download(() => page.getByRole('link', { name: fmt, exact: true }).click());
        expect(d.name === `flowqr-e2e-front-desk.${fmt.toLowerCase()}` && magic[fmt](d.bytes), `${fmt}: ${d.name}, ${d.bytes.length} bytes`);
      }
    });

    // ------------------------------------------------------------------ 4. bulk export
    await step('bulk export: nothing selected is explained; selecting all exports a ZIP of 3 codes', async () => {
      await page.goto('/qr');
      await page.getByRole('button', { name: 'Export codes' }).waitFor({ timeout: 20000 });
      await page.getByRole('button', { name: 'Export codes' }).click();
      await page.getByText('Select at least one card or campaign.').waitFor();
      await page.getByRole('button', { name: 'Select all' }).first().click();
      await page.getByText('2 selected').waitFor();
      await page.getByRole('button', { name: 'Select all' }).first().click();   // the cards button now reads "Clear", so this is the campaigns one
      await page.getByText('1 selected').waitFor();
      const d = await download(() => page.getByRole('button', { name: 'Export 3 codes' }).click());
      expect(d.name === 'flowqr-codes.zip' && d.bytes.subarray(0, 2).toString() === 'PK', 'not a zip: ' + d.name);
      const listing = d.bytes.toString('latin1');
      for (const f of [`png/${card.card_code}.png`, `svg/${card.card_code}.svg`, `pdf/${card.card_code}.pdf`, 'pdf/campaign-e2e-front-desk.pdf', 'print-sheet-A4.pdf', 'manifest.csv']) expect(listing.includes(f), 'zip is missing ' + f);
      await toast('Exported 3 code(s)');
    });

    // ------------------------------------------------------------------ 5. pause / resume
    await step('card: pause shows the inactive notice to customers, resume brings the same code back', async () => {
      await page.goto(`/cards/${card.id}`);
      await page.getByRole('button', { name: 'Pause' }).click();
      await toast('Card paused');
      await page.getByRole('button', { name: 'Resume' }).waitFor();
      expect((await publicGet(`/api/v1/public/c/${card.public_token}`)).body.state === 'inactive', 'paused card still resolves');
      await page.getByRole('button', { name: 'Resume' }).click();
      await toast('Card resumed');
      await page.getByRole('button', { name: 'Pause' }).waitFor();
      expect((await publicGet(`/api/v1/public/c/${card.public_token}`)).body.state === 'ok', 'resumed card does not resolve');
      const now = (await (await ctx.request.get('/api/v1/cards')).json()).find((c) => c.id === card.id);
      expect(now.public_token === card.public_token && now.url === card.url, 'card link changed');
    });

    // ------------------------------------------------------------------ 6. destination editing
    await step('campaign: changing the destination keeps the same printed link and re-points it', async () => {
      await page.goto(`/review-growth/campaigns/${campaign.id}`);
      await page.getByText(campaign.url, { exact: true }).waitFor({ timeout: 20000 });
      await page.getByLabel('Location', { exact: true }).selectOption(locB.id);
      await page.getByRole('button', { name: 'Change destination' }).click();
      await toast('Destination changed');
      await page.getByText(campaign.url, { exact: true }).waitFor();
      const land = await publicGet(`/api/v1/public/reviews/${campaign.public_id}`);
      expect(land.status === 200 && land.body.location.name === 'E2E Branch', 'old link leads to ' + JSON.stringify(land.body).slice(0, 120));
      const c = await (await ctx.request.get(`/api/v1/review-growth/campaigns/${campaign.id}`)).json();
      expect(c.public_id === campaign.public_id && c.old_codes.length === 0 && !c.qr_rotated_at, 'the code changed during a destination edit');
    });

    // ------------------------------------------------------------------ 7. new code keeps the old one; deactivation needs the typed word
    let newId = null;
    await step('campaign: issuing a new code keeps the printed one working', async () => {
      await page.getByRole('button', { name: 'Issue new code' }).click();
      const dlg = page.getByRole('dialog');
      await dlg.getByText('already printed keep working').waitFor();
      await dlg.getByRole('button', { name: 'Issue new code' }).click();
      await toast('The earlier code still works');
      const c = await (await ctx.request.get(`/api/v1/review-growth/campaigns/${campaign.id}`)).json();
      newId = c.public_id;
      expect(newId !== campaign.public_id && c.old_codes.length === 1 && c.old_codes[0].public_id === campaign.public_id && c.old_codes[0].active, 'unexpected codes: ' + JSON.stringify(c.old_codes));
      await page.getByRole('list', { name: 'Earlier codes' }).getByText(campaign.url).waitFor();
      await page.getByRole('list', { name: 'Earlier codes' }).getByText('Working', { exact: true }).waitFor();
      for (const id of [campaign.public_id, newId]) {
        const land = await publicGet(`/api/v1/public/reviews/${id}`);
        expect(land.status === 200 && land.body.location.name === 'E2E Branch', `code ${id} -> ${land.status}`);
      }
    });
    await step('customer: the OLD printed link still opens the review page in a browser', async () => {
      const phone = await browser.newContext({ baseURL: BASE, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, userAgent: PHONE_UA });
      const p = await phone.newPage();
      await p.goto(`/r/${campaign.public_id}`);
      await p.getByText(`ZZ-E2E-${TAG}`).first().waitFor({ timeout: 20000 });
      expect(await p.getByText('no longer active').count() === 0 && await p.getByText('switched off').count() === 0, 'old link shows an inactive page');
      await phone.close();
    });
    await step('campaign: switching an old code off needs the typed word, then customers are told so', async () => {
      await page.getByRole('button', { name: 'Switch off…' }).click();
      const dlg = page.getByRole('dialog');
      const go = dlg.getByRole('button', { name: 'Switch the code off' });
      expect(await go.isDisabled(), 'confirm button enabled before typing');
      await dlg.getByLabel('Type DEACTIVATE to confirm').fill('deactivate please');
      expect(await go.isDisabled(), 'confirm button enabled for the wrong word');
      expect((await publicGet(`/api/v1/public/reviews/${campaign.public_id}`)).status === 200, 'code stopped before confirmation');
      await dlg.getByLabel('Type DEACTIVATE to confirm').fill('DEACTIVATE');
      await go.click();
      await toast('switched off');
      await page.getByRole('list', { name: 'Earlier codes' }).getByText('Switched off', { exact: true }).waitFor();
      const dead = await publicGet(`/api/v1/public/reviews/${campaign.public_id}`);
      expect(dead.status === 410 && dead.body.detail.state === 'deactivated', 'old code -> ' + dead.status);
      expect((await publicGet(`/api/v1/public/reviews/${newId}`)).status === 200, 'the current code was affected');
      const phone = await browser.newContext({ baseURL: BASE, userAgent: PHONE_UA });
      const p = await phone.newPage();
      await p.goto(`/r/${campaign.public_id}`);
      await p.getByText('This QR code was switched off').waitFor({ timeout: 20000 });
      await phone.close();
    });
    await step('campaign: a switched-off code can be switched back on', async () => {
      await page.getByRole('button', { name: 'Switch back on' }).click();
      await toast('works again');
      expect((await publicGet(`/api/v1/public/reviews/${campaign.public_id}`)).status === 200, 'old code did not come back');
    });

    // ------------------------------------------------------------------ 8. staff location assignment
    await step('staff: limiting a teammate to one location takes effect for them', async () => {
      await page.goto('/staff');
      await page.getByRole('button', { name: 'Change location access for ZZ E2E Staff' }).click({ timeout: 20000 });
      const dlg = page.getByRole('dialog');
      await dlg.getByLabel('Only the locations ticked below').check();
      await dlg.getByText('this person will see no reviews').waitFor();
      await dlg.getByLabel('E2E Main').check();
      await dlg.getByRole('button', { name: 'Save access' }).click();
      await toast('is now limited to 1 location');
      await page.getByRole('row', { name: /ZZ E2E Staff/ }).getByText('E2E Main').waitFor();
      const sp = await staffCtx.newPage();
      await sp.goto('/locations');
      await sp.getByText('E2E Main').first().waitFor({ timeout: 20000 });
      expect(await sp.getByText('E2E Branch').count() === 0, 'restricted staff can see the other location');
      const direct = await staffCtx.request.get(`/api/v1/locations/${locB.id}`);
      expect(direct.status() === 404, 'direct API request for the other location -> ' + direct.status());
      const camp = await staffCtx.request.get(`/api/v1/review-growth/campaigns/${campaign.id}`);   // the campaign now lives at Branch
      expect(camp.status() === 404, 'restricted staff can open a campaign at another location -> ' + camp.status());
      await sp.close();
    });
    await step('staff: giving access to every location back works', async () => {
      await page.getByRole('button', { name: 'Change location access for ZZ E2E Staff' }).click();
      const dlg = page.getByRole('dialog');
      await dlg.getByLabel('Every location, including ones added later').check();
      await dlg.getByRole('button', { name: 'Save access' }).click();
      await toast('can now see every location');
      const all = await (await staffCtx.request.get('/api/v1/locations')).json();
      expect(all.length === 2, 'staff sees ' + all.length + ' locations');
    });
    await step('staff: an invitation can carry a location limit', async () => {
      await page.getByLabel('Email').fill(`zz-e2e-invite-${TAG}@example.com`);
      await page.getByLabel('Only the locations ticked below').check();
      await page.getByLabel('E2E Branch').check();
      await page.getByRole('button', { name: 'Send invite' }).click();
      await page.getByRole('row', { name: new RegExp(`zz-e2e-invite-${TAG}`) }).getByText('1 location').waitFor({ timeout: 15000 });
    });

    // ------------------------------------------------------------------ 9. deactivating a location that codes lead to
    await step('location: deactivating one that live codes lead to warns first, and cancelling changes nothing', async () => {
      let message = null;
      page.once('dialog', async (d) => { message = d.message(); await d.dismiss(); });
      const r = await ctx.request.delete(`/api/v1/locations/${locB.id}`, { headers: H() });
      expect(r.status() === 409 && (await r.json()).detail.code === 'codes_would_stop', 'API allowed it without confirmation: ' + r.status());
      await page.goto('/locations');
      await page.getByText('E2E Branch').first().click({ timeout: 20000 });
      const dlg = page.getByRole('dialog');
      if (await dlg.count() === 0) await page.getByRole('button', { name: /Edit/ }).last().click();
      await page.getByRole('dialog').getByRole('button', { name: 'Deactivate' }).click();
      await page.waitForTimeout(1500);
      expect(message && /QR campaign\(s\) lead to this location/.test(message), 'no warning dialog: ' + message);
      const loc = await (await ctx.request.get(`/api/v1/locations/${locB.id}`)).json();
      expect(loc.is_active === true, 'location was deactivated although the warning was dismissed');
      expect((await publicGet(`/api/v1/public/reviews/${newId}`)).status === 200, 'code stopped');
    });

    await step('no page crashed and no request returned a server error', async () => {
      expect(pageErrors.length === 0, 'page errors: ' + pageErrors.slice(0, 3).join(' | '));
      expect(httpErrors.length === 0, 'HTTP 5xx: ' + httpErrors.slice(0, 3).join(' | '));
    });
  }

  await browser.close();
  // ------------------------------------------------------------------ cleanup: only rows this run created
  try {
    const left = sql(`
      DELETE FROM scan_events WHERE card_id IN (SELECT id FROM qr_cards WHERE batch_id IN (SELECT id FROM card_batches WHERE name = 'ZZ-E2E-${TAG}'));
      DELETE FROM qr_cards WHERE batch_id IN (SELECT id FROM card_batches WHERE name = 'ZZ-E2E-${TAG}');
      DELETE FROM card_batches WHERE name = 'ZZ-E2E-${TAG}';
      DELETE FROM audit_logs WHERE tenant_id IN (SELECT id FROM tenants WHERE name = 'ZZ-E2E-${TAG}') OR user_id IN (SELECT id FROM users WHERE email LIKE 'zz-e2e-%${TAG}@example.com');
      DELETE FROM tenants WHERE name = 'ZZ-E2E-${TAG}';
      DELETE FROM users WHERE email LIKE 'zz-e2e-%${TAG}@example.com';
      SELECT 'left: ' || (SELECT count(*) FROM tenants WHERE name = 'ZZ-E2E-${TAG}') || ' tenants, ' || (SELECT count(*) FROM users WHERE email LIKE 'zz-e2e-%${TAG}@example.com') || ' users';`);
    console.log('cleanup', left.split('\n').pop());
  } catch (e) { console.log('CLEANUP FAILED (remove ZZ-E2E-' + TAG + ' by hand):', String(e.message).slice(0, 300)); }

  const failed = results.filter((r) => !r[1]);
  console.log(`\n${results.length - failed.length}/${results.length} browser checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
