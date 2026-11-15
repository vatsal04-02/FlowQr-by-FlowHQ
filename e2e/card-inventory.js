// FlowQR browser E2E for pre-printed card inventory: batches, scan-to-assign with a (fake) camera, QR/NFC doors, destination changes,
// pause/retire, reserved cards, isolation, poster downloads.  Drives the real UI in Chromium against a RUNNING local stack.
//
//   node e2e/card-inventory.js          (BASE_URL defaults to http://localhost:3000; CHROME_PATH=<system Chrome> with playwright-core)
//
// WHAT THIS DOES AND DOES NOT PROVE
//  * The "camera" is Chrome's fake capture device playing a video of the real FlowQR poster for the card. That exercises the scanner
//    component, the lookup and the assignment end to end. It does NOT prove a physical phone camera reads a printed card: that needs
//    printed samples and real phones (docs/CARD_INVENTORY.md).
//  * NFC is the public route /n/<id>. No tag is written or read here.
//  * Batch print exports need a permanent HTTPS address. A local stack uses http://localhost, so this script asserts that the server
//    REFUSES them with a clear message (when PUBLIC_CARD_BASE_URL is permanent it asserts they work instead).
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
let chromium;
try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }

const BASE = process.env.BASE_URL || 'http://localhost:3000';
const ROOT = path.resolve(__dirname, '..');
const OUT = process.env.SHOTS_DIR || path.join(ROOT, 'e2e', 'shots');
const TAG = Math.random().toString(36).slice(2, 8);
const PW = 'Str0ngPassw0rd!' + TAG;
const NAME = `ZZ-CARDS-${TAG}`;
const NAME_B = `ZZ-CARDS-OTHER-${TAG}`;
const BATCH = `ZZ-INV-${TAG}`;
const PHONE_UA = 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36';
const PHONE_UA2 = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Version/17.4 Mobile Safari/604.1';
const results = [];

const docker = (args, input, enc = 'utf8') => execFileSync('docker', ['compose', 'exec', '-T', ...args], { cwd: ROOT, input, encoding: enc, stdio: ['pipe', 'pipe', 'pipe'], maxBuffer: 256 * 1024 * 1024 });
const sql = (q) => docker(['db', 'psql', '-U', 'flowqr', '-d', 'flowqr', '-At', '-v', 'ON_ERROR_STOP=1'], `BEGIN; SELECT set_config('app.bypass_rls','on',true); ${q} COMMIT;`).trim();
function expect(cond, msg) { if (!cond) throw new Error(msg); }

/** A short video (Y4M) of `png` centred on white: what the fake camera will "see". */
function y4mOf(png) {
  const code = `
import sys, io
from PIL import Image
im = Image.open(io.BytesIO(sys.stdin.buffer.read())).convert('RGB')
W, H = 1280, 720
canvas = Image.new('RGB', (W, H), 'white')
s = H / im.height * 0.98
im2 = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
canvas.paste(im2, ((W - im2.width) // 2, (H - im2.height) // 2))
y, cb, cr = canvas.convert('YCbCr').split()
cb = cb.resize((W // 2, H // 2), Image.BOX); cr = cr.resize((W // 2, H // 2), Image.BOX)
out = sys.stdout.buffer
out.write(b'YUV4MPEG2 W%d H%d F10:1 Ip A1:1 C420jpeg\\n' % (W, H))
for _ in range(8):
    out.write(b'FRAME\\n'); out.write(y.tobytes()); out.write(cb.tobytes()); out.write(cr.tobytes())
`;
  return execFileSync('docker', ['compose', 'exec', '-T', 'api', 'python', '-c', code], { cwd: ROOT, input: png, stdio: ['pipe', 'pipe', 'pipe'], maxBuffer: 256 * 1024 * 1024 });
}
const pngSize = (b) => ({ w: b.readUInt32BE(16), h: b.readUInt32BE(20) });

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const chromeArgs = process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {};
  const browser = await chromium.launch({ headless: true, ...chromeArgs });
  const ownerCtx = await browser.newContext({ baseURL: BASE, viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const page = await ownerCtx.newPage();
  const pageErrors = []; const httpErrors = [];
  const watch = (p) => { p.on('pageerror', (e) => pageErrors.push(e.message)); p.on('response', (r) => { if (r.status() >= 500) httpErrors.push(`${r.status()} ${r.url()}`); }); };
  watch(page);

  async function step(name, fn) {
    try { await fn(); results.push([name, true]); console.log('PASS', name); }
    catch (e) {
      results.push([name, false, String(e.message).split('\n')[0].slice(0, 300)]);
      console.log('FAIL', name, '\n     ', String(e.message).split('\n')[0].slice(0, 300));
      for (const [i, p] of [['owner', page], ['admin', globalThis.__adminPage], ['cam', globalThis.__camPage]]) if (p) await p.screenshot({ path: path.join(OUT, `fail-inv-${results.length}-${i}.png`), fullPage: true }).catch(() => {});
    }
  }
  const toastOn = (p, text) => p.getByRole('status').filter({ hasText: text }).first().waitFor({ timeout: 20000 });
  const pub = async (p, headers) => { const r = await ownerCtx.request.get(p, { headers: headers ?? { 'User-Agent': PHONE_UA } }); return { status: r.status(), body: await r.json().catch(() => null) }; };

  // ------------------------------------------------------------------ setup (API + a platform admin)
  let csrf, tenant, locA, locB, campA, campB, adminReq, adminCsrf, otherCtx, otherCsrf;
  const H = () => ({ 'X-CSRF-Token': csrf });
  let ready = false; let X, Y, Z, W3;  // cards
  try {
    let r = await ownerCtx.request.post('/api/v1/auth/register', { data: { email: `zz-cards-${TAG}@example.com`, password: PW, full_name: 'ZZ Cards Owner' } });
    expect(r.status() === 201, `register ${r.status()} ${await r.text()}`);
    csrf = (await r.json()).csrf_token;
    tenant = await (await ownerCtx.request.post('/api/v1/tenants', { data: { name: NAME, category: 'Physiotherapy clinic', language: 'en' }, headers: H() })).json();
    locA = await (await ownerCtx.request.post('/api/v1/locations', { data: { name: 'Main clinic', city: 'Lucknow', review_url: 'https://g.page/r/AAA111/review' }, headers: H() })).json();
    locB = await (await ownerCtx.request.post('/api/v1/locations', { data: { name: 'Aliganj branch', city: 'Lucknow', review_url: 'https://g.page/r/BBB222/review' }, headers: H() })).json();
    await ownerCtx.request.post('/api/v1/tenant/complete-onboarding', { headers: H() });
    campA = await (await ownerCtx.request.post('/api/v1/review-growth/campaigns', { data: { name: 'Front desk', location_id: locA.id }, headers: H() })).json();
    campB = await (await ownerCtx.request.post('/api/v1/review-growth/campaigns', { data: { name: 'Branch desk', location_id: locB.id }, headers: H() })).json();
    // a second, unrelated business (own session) for isolation checks
    otherCtx = await browser.newContext({ baseURL: BASE });
    r = await otherCtx.request.post('/api/v1/auth/register', { data: { email: `zz-cards-other-${TAG}@example.com`, password: PW, full_name: 'ZZ Other Owner' } });
    otherCsrf = (await r.json()).csrf_token;
    await otherCtx.request.post('/api/v1/tenants', { data: { name: NAME_B, category: 'Dental clinic', language: 'en' }, headers: { 'X-CSRF-Token': otherCsrf } });
    await otherCtx.request.post('/api/v1/locations', { data: { name: 'Other main', city: 'Kanpur', review_url: 'https://g.page/r/OTH/review' }, headers: { 'X-CSRF-Token': otherCsrf } });
    await otherCtx.request.post('/api/v1/tenant/complete-onboarding', { headers: { 'X-CSRF-Token': otherCsrf } });
    // the platform admin (FlowHQ staff)
    const adminCtx = await browser.newContext({ baseURL: BASE, viewport: { width: 1280, height: 900 }, acceptDownloads: true });
    globalThis.__adminCtx = adminCtx;
    r = await adminCtx.request.post('/api/v1/auth/register', { data: { email: `zz-cards-admin-${TAG}@example.com`, password: PW, full_name: 'ZZ FlowHQ Admin' } });
    expect(r.status() === 201, 'admin register');
    sql(`UPDATE users SET email_verified_at = now(), is_platform_admin = true WHERE email IN ('zz-cards-${TAG}@example.com', 'zz-cards-other-${TAG}@example.com', 'zz-cards-admin-${TAG}@example.com') AND email LIKE 'zz-cards-admin-%';
         UPDATE users SET email_verified_at = now() WHERE email LIKE 'zz-cards-%${TAG}@example.com';`);
    r = await adminCtx.request.post('/api/v1/auth/login', { data: { email: `zz-cards-admin-${TAG}@example.com`, password: PW } });
    expect(r.status() === 200, 'admin login ' + r.status() + ' ' + await r.text());
    adminCsrf = (await r.json()).csrf_token;
    adminReq = adminCtx.request;
    globalThis.__adminPage = await adminCtx.newPage(); watch(globalThis.__adminPage);
    // stock for the camera / bulk / reserved scenarios, made through the API (the UI creates its own batch below)
    const b = await (await adminReq.post('/api/v1/admin/batches', { data: { name: BATCH + '-api', quantity: 8 }, headers: { 'X-CSRF-Token': adminCsrf } })).json();
    await adminReq.post(`/api/v1/admin/batches/${b.id}/release`, { headers: { 'X-CSRF-Token': adminCsrf } });
    const list = (await (await adminReq.get('/api/v1/admin/cards', { params: { batch_id: b.id, limit: 50 } })).json()).items;
    [X, Y, Z, W3] = list;
    globalThis.__stock = list;
    ready = true;
  } catch (e) { console.log('SETUP FAILED:', e.message); results.push(['setup', false, e.message]); }

  if (ready) {
    const A = globalThis.__adminPage;

    // ------------------------------------------------------------------ 1. batches and stock (admin UI)
    let uiBatchId;
    await step('admin: generate a batch of 50 from the size buttons; it starts as generated and is marked printed into stock', async () => {
      await A.goto('/admin/cards');
      await A.getByRole('heading', { name: 'Card inventory' }).waitFor({ timeout: 30000 });
      await A.getByRole('button', { name: 'New batch' }).click();
      await A.getByLabel('Batch name').fill(BATCH);
      const sizes = await A.getByRole('radiogroup', { name: 'Batch size' }).getByRole('radio').allInnerTexts();
      expect(sizes.join(',') === '50,100,250,500', 'batch sizes offered: ' + sizes.join(','));
      await A.getByRole('radio', { name: '50', exact: true }).click();
      await A.getByRole('button', { name: 'Generate cards' }).click();
      await toastOn(A, 'Created 50 cards');
      const row = A.getByTestId('batch-row').filter({ hasText: BATCH }).filter({ hasNotText: '-api' }).first();
      await row.waitFor({ timeout: 20000 });
      await row.getByText('not marked printed').waitFor();
      const before = (await (await adminReq.get('/api/v1/admin/inventory')).json());
      const mine = before.batches.find((x) => x.name === BATCH);
      uiBatchId = mine.id;
      expect(mine.quantity === 50 && mine.counts.generated === 50, 'new batch is not 50 generated cards: ' + JSON.stringify(mine.counts));
      await row.getByRole('button', { name: 'Mark printed' }).click();
      await toastOn(A, 'marked printed');
      const after = (await (await adminReq.get('/api/v1/admin/inventory')).json()).batches.find((x) => x.name === BATCH);
      expect(after.counts.unassigned === 50 && after.released_at, 'batch is not in stock: ' + JSON.stringify(after.counts));
      const tokens = (await (await adminReq.get('/api/v1/admin/cards', { params: { batch_id: uiBatchId, limit: 200 } })).json()).items;
      expect(new Set(tokens.map((c) => c.public_token)).size === 50 && tokens.every((c) => /\/q\//.test(c.url) && /\/n\//.test(c.nfc_url)), 'cards are not 50 unique tokens with QR and NFC addresses');
    });
    await step('admin: the stock strip counts every lifecycle state, and print exports are refused for a temporary address (or work for a permanent one)', async () => {
      await A.goto('/admin/cards');
      const strip = A.getByTestId('stock-strip');
      await strip.waitFor({ timeout: 20000 });
      await A.waitForFunction(() => !document.querySelector('[data-testid=stock-strip]').innerText.includes('–'), null, { timeout: 20000 });
      const labels = (await strip.getByRole('button').allInnerTexts()).map((t) => t.replace(/\d[\d,]*/, '').trim());
      expect(labels.join('|') === 'Generated|In stock|Reserved|Assigned|Live|Paused|Archived|Retired', 'strip: ' + labels.join('|'));
      expect(/^\d/.test((await strip.getByRole('button', { name: /In stock/ }).innerText()).trim()) && parseInt((await strip.getByRole('button', { name: /In stock/ }).innerText()), 10) >= 58, 'stock count too low');
      const probe = await adminReq.get(`/api/v1/admin/batches/${uiBatchId}/inventory.csv`);
      const row = A.getByTestId('batch-row').filter({ hasText: BATCH }).filter({ hasNotText: '-api' }).first();
      if (probe.status() === 409) {
        await row.getByRole('button', { name: 'Poster sheets (PDF)' }).click();
        await A.getByText('Not printable yet').waitFor({ timeout: 20000 });
        expect(/HTTPS|temporary|domain/i.test(await A.getByText('Not printable yet').locator('xpath=..').innerText()), 'the refusal does not explain why');
      } else {
        const [d] = await Promise.all([A.waitForEvent('download', { timeout: 60000 }), row.getByRole('button', { name: 'Poster sheets (PDF)' }).click()]);
        expect(fs.readFileSync(await d.path()).subarray(0, 5).toString() === '%PDF-', 'poster sheet is not a PDF');
        const [c] = await Promise.all([A.waitForEvent('download', { timeout: 60000 }), row.getByRole('button', { name: 'Inventory + NFC list (CSV)' }).click()]);
        const csv = fs.readFileSync(await c.path(), 'utf8');
        expect(csv.includes('/q/') && csv.includes('/n/') && csv.split('\n').filter(Boolean).length === 51, 'inventory csv is wrong');
      }
    });
    await step('admin: a poster downloads as PNG and PDF, with a live preview and a warning when the address is not permanent', async () => {
      await A.goto('/admin/cards');
      const card = (await (await adminReq.get('/api/v1/admin/cards', { params: { batch_id: uiBatchId, limit: 1 } })).json()).items[0];
      await A.getByRole('textbox', { name: 'Search by serial number' }).fill(card.card_code);
      const tr = A.getByTestId('card-row').filter({ hasText: card.card_code });
      await tr.waitFor({ timeout: 20000 });
      await tr.getByRole('button', { name: 'Poster' }).click();
      await A.getByTestId('poster-preview').waitFor({ timeout: 30000 });
      const sized = await A.getByTestId('poster-preview').evaluate((i) => [i.naturalWidth, i.naturalHeight]);
      expect(sized[0] === 1055 && sized[1] === 1491, 'preview size ' + sized);
      await A.locator('input[name="poster-format"][value="png-1"]').check();
      const [d] = await Promise.all([A.waitForEvent('download', { timeout: 30000 }), A.getByRole('button', { name: 'Download', exact: true }).click()]);
      const png = fs.readFileSync(await d.path());
      expect(png.subarray(1, 4).toString() === 'PNG' && pngSize(png).w === 1055 && pngSize(png).h === 1491, 'not the approved 1055x1491 png');
      await A.locator('input[name="poster-format"][value="pdf-ref"]').check();
      const [p] = await Promise.all([A.waitForEvent('download', { timeout: 30000 }), A.getByRole('button', { name: 'Download', exact: true }).click()]);
      expect(fs.readFileSync(await p.path()).subarray(0, 5).toString() === '%PDF-', 'not a pdf');
      await A.getByRole('button', { name: 'Close', exact: true }).last().click();
    });

    // ------------------------------------------------------------------ 2. scan-to-assign with the camera
    let cam, camBrowser;
    await step('admin: pick business, location and campaign, scan the poster with the camera, confirm the serial, assign and activate', async () => {
      const posterPng = Buffer.from(await (await adminReq.get(`/api/v1/admin/cards/${X.id}/poster.png`)).body());
      const y4m = path.join(os.tmpdir(), `flowqr-cam-${TAG}.y4m`);
      fs.writeFileSync(y4m, y4mOf(posterPng));
      camBrowser = await chromium.launch({ headless: true, ...chromeArgs, args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-video-capture=${y4m}`] });
      const camCtx = await camBrowser.newContext({ baseURL: BASE, viewport: { width: 1280, height: 1000 }, permissions: ['camera'] });
      // the same admin session, in the browser that has the fake camera
      const ck = await globalThis.__adminCtx.cookies(); await camCtx.addCookies(ck);
      cam = await camCtx.newPage(); globalThis.__camPage = cam; watch(cam);
      await cam.goto('/admin/cards');
      await cam.getByRole('radio', { name: 'Assign cards' }).click();
      await cam.getByTestId('assign-cards').getByLabel('Business').selectOption({ label: NAME });
      await cam.getByTestId('assign-cards').getByLabel('Location').selectOption({ label: 'Main clinic – Lucknow' });
      await cam.getByTestId('assign-cards').getByLabel('Review campaign').selectOption({ label: 'Front desk' });
      const scanBtn = cam.getByRole('button', { name: 'Scan card' });
      await scanBtn.click();
      await cam.getByTestId('card-scanner').waitFor();
      await cam.getByTestId('assign-confirm').waitFor({ timeout: 40000 });
      expect((await cam.getByTestId('confirm-serial').innerText()).trim() === X.card_code, 'scanned ' + await cam.getByTestId('confirm-serial').innerText() + ' expected ' + X.card_code);
      const dl = await cam.getByTestId('assign-confirm').innerText();
      expect(dl.includes(NAME) && dl.includes('Main clinic') && dl.includes('Front desk'), 'confirmation does not show business, location and campaign: ' + dl);
      expect(await cam.getByRole('button', { name: 'Assign and activate' }).isEnabled(), 'assign is disabled');
      await cam.getByRole('button', { name: 'Assign and activate' }).click();
      await cam.getByTestId('assigned-ok').waitFor({ timeout: 20000 });
      expect((await cam.getByTestId('assigned-ok').innerText()).includes(X.card_code), 'success message does not name the card');
      const now = (await (await adminReq.get(`/api/v1/admin/cards/${X.id}`)).json()).card;
      expect(now.status === 'active' && now.tenant_name === NAME && now.campaign_name === 'Front desk', 'card not active: ' + JSON.stringify([now.status, now.tenant_name, now.campaign_name]));
    });
    const openAssign = async (loc, camp) => {
      await A.goto('/admin/cards');
      await A.getByRole('radio', { name: 'Assign cards' }).click();
      await A.getByTestId('assign-cards').getByLabel('Business').selectOption({ label: NAME });
      await A.getByTestId('assign-cards').getByLabel('Location').selectOption({ label: loc });
      await A.getByTestId('assign-cards').getByLabel('Review campaign').selectOption({ label: camp });
    };
    await step('admin: a serial typed by hand works the same way, and a card that is already in use needs an explicit tick', async () => {
      await openAssign('Main clinic \u2013 Lucknow', 'Front desk');
      await A.getByRole('button', { name: 'Scan card' }).click();
      await A.getByRole('alert').filter({ hasText: /camera/i }).first().waitFor({ timeout: 20000 });  // a desktop without a usable camera says so and offers manual entry
      await A.getByLabel('Card serial number').fill(Y.card_code.toLowerCase());
      await A.getByRole('button', { name: 'Look up' }).click();
      await A.getByTestId('assign-confirm').waitFor({ timeout: 20000 });
      expect((await A.getByTestId('confirm-serial').innerText()).trim() === Y.card_code, 'serial lookup');
      await A.getByRole('button', { name: 'Assign and activate' }).click();
      await A.getByTestId('assigned-ok').waitFor();
      // X is live: assigning it elsewhere must ask
      await A.getByTestId('assign-cards').getByLabel('Location').selectOption({ label: 'Aliganj branch – Lucknow' });
      await A.getByRole('button', { name: 'Scan card' }).click();
      await A.getByLabel('Card serial number').fill(X.card_code);
      await A.getByRole('button', { name: 'Look up' }).click();
      await A.getByTestId('assign-confirm').waitFor({ timeout: 20000 });
      expect(await A.getByRole('button', { name: 'Assign and activate' }).isDisabled(), 'a card in use can be moved without confirming');
      await A.getByText(/already in use/).waitFor();
      await A.getByLabel(/I understand, move this card/).check({ force: true });
      expect(await A.getByRole('button', { name: 'Assign and activate' }).isEnabled(), 'still disabled after the tick');
      await A.getByRole('button', { name: 'Scan a different card' }).click();  // changed our mind: nothing moved
      await A.getByRole('button', { name: 'Stop scanning' }).click();
      const x = (await (await adminReq.get(`/api/v1/admin/cards/${X.id}`)).json()).card;
      expect(x.location_name === 'Main clinic', 'X moved without being confirmed: ' + x.location_name);
    });
    await step('admin: unknown, campaign and unrelated codes are refused with a reason', async () => {
      await A.getByTestId('assign-cards').getByLabel('Location').selectOption({ label: 'Main clinic – Lucknow' });
      await A.getByRole('button', { name: 'Scan card' }).click();
      for (const [text, msg] of [['FQR-999999', /No card with that code/], [`${BASE}/r/${campA.public_id}`, /campaign code, not a card/], ['https://example.com/x', /not a FlowQR card/]]) {
        await A.getByLabel('Card serial number').fill(text);
        await A.getByRole('button', { name: 'Look up' }).click();
        await A.getByRole('alert').filter({ hasText: msg }).first().waitFor({ timeout: 15000 });
      }
      await A.getByRole('button', { name: 'Stop scanning' }).click();
    });
    await step('admin: assigning many cards at once is all-or-nothing', async () => {
      await openAssign('Main clinic – Lucknow', 'Front desk');
      await A.getByTestId('assign-cards').getByLabel('Serial numbers').fill(`${Z.card_code}\n${W3.card_code}, FQR-NOPE-9`);
      await A.getByRole('button', { name: 'Assign these cards' }).click();
      await A.getByRole('alert').filter({ hasText: /FQR-NOPE-9|No card found/ }).first().waitFor({ timeout: 15000 });
      let z = (await (await adminReq.get(`/api/v1/admin/cards/${Z.id}`)).json()).card;
      expect(z.status === 'unassigned', 'a card was assigned although another in the list was invalid');
      await A.getByTestId('assign-cards').getByLabel('Serial numbers').fill(`${Z.card_code}\n${W3.card_code}`);
      await A.getByRole('button', { name: 'Assign these cards' }).click();
      await A.getByTestId('assigned-ok').waitFor({ timeout: 20000 });
      z = (await (await adminReq.get(`/api/v1/admin/cards/${Z.id}`)).json()).card;
      expect(z.status === 'active' && z.campaign_name === 'Front desk', 'bulk assign did not activate: ' + z.status);
    });

    // ------------------------------------------------------------------ 3. what customers get
    const phone = await browser.newContext({ baseURL: BASE, userAgent: PHONE_UA, viewport: { width: 390, height: 800 }, isMobile: true });
    const ph = await phone.newPage(); watch(ph);
    await step('customer: the printed QR address and the NFC address open the same business campaign, and an unassigned card shows nothing about anyone', async () => {
      await ph.goto(`/q/${X.public_token}`);
      await ph.getByRole('heading', { name: NAME }).first().waitFor({ timeout: 30000 });
      await ph.goto(`/n/${X.public_token}`);
      await ph.getByRole('heading', { name: NAME }).first().waitFor({ timeout: 30000 });
      await ph.goto(`/c/${X.public_token}`);  // the older printed address keeps working
      await ph.getByRole('heading', { name: NAME }).first().waitFor({ timeout: 30000 });
      const stock = globalThis.__stock[5];
      await ph.goto(`/q/${stock.public_token}`);
      await ph.getByText(/isn.t set up yet/i).waitFor({ timeout: 20000 });
      const body = await ph.locator('body').innerText();
      expect(!body.includes(NAME) && !body.includes(tenant.id), 'an unassigned card page leaks the business');
      await ph.goto(`/n/${stock.public_token}`);
      await ph.getByText(/isn.t set up yet/i).waitFor({ timeout: 20000 });
      const api = await pub(`/api/v1/public/c/${stock.public_token}?channel=nfc`);
      expect(Object.keys(api.body).sort().join() === 'message,state', 'public fallback exposes more than state and message: ' + Object.keys(api.body));
    });

    // ------------------------------------------------------------------ 4. the business side
    await step('business: its cards list shows the campaign and counts QR scans and NFC taps separately', async () => {
      // one more tap of each so both counters are definitely visible
      const other = await browser.newContext({ baseURL: BASE, userAgent: PHONE_UA2 });
      await (await other.newPage()).goto(`/n/${X.public_token}`);
      await other.close();
      await page.goto('/cards');
      const tile = page.getByTestId('card-tile').filter({ hasText: X.card_code });
      await tile.waitFor({ timeout: 30000 });
      await tile.getByText('Campaign: Front desk').waitFor();
      const dl = (await tile.locator('dl').innerText()).replace(/\s+/g, ' ');
      expect(/QR/.test(dl) && /NFC/.test(dl), 'tile does not show QR and NFC counts: ' + dl);
      const counts = await (await ownerCtx.request.get('/api/v1/cards')).json();
      const s = counts.find((c) => c.id === X.id).stats;
      expect((s.qr_scan ?? 0) >= 1 && (s.nfc_scan ?? 0) >= 1, 'qr/nfc stats: ' + JSON.stringify(s));
      const ov = await (await ownerCtx.request.get('/api/v1/analytics/overview')).json();
      expect(ov.engagement.by_channel.qr.scans >= 1 && ov.engagement.by_channel.nfc.scans >= 1, 'analytics by_channel: ' + JSON.stringify(ov.engagement.by_channel));
    });
    await step('business: card page shows the NFC address, and a poster with a live preview', async () => {
      await page.goto(`/cards/${X.id}`);
      const nfc = page.getByTestId('nfc-address');
      await nfc.waitFor({ timeout: 20000 });
      expect((await nfc.innerText()).includes(`/n/${X.public_token}`), 'NFC address missing');
      await page.getByRole('button', { name: 'Download poster' }).click();
      await page.getByTestId('poster-preview').waitFor({ timeout: 30000 });
      await page.getByRole('button', { name: 'Close', exact: true }).last().click();
    });
    await step('business: changing where a live card points needs a confirmation, then applies to the same printed code at once', async () => {
      await page.goto(`/cards/${X.id}`);
      await page.getByRole('button', { name: 'Change' }).click();
      await page.getByRole('dialog').getByLabel('Location').selectOption({ label: 'Aliganj branch, Lucknow' });
      await page.getByRole('dialog').getByLabel('Review page').selectOption({ label: 'Campaign: Branch desk' });
      const save = page.getByRole('button', { name: 'Save', exact: true });
      expect(await save.isDisabled(), 'save is enabled before the confirmation');
      await page.getByText(/This card is in use/).waitFor();
      await page.getByLabel(/I understand, change this card/).check();
      await save.click();
      await toastOn(page, 'Card updated');
      await ph.goto(`/q/${X.public_token}`);  // the same printed address
      await ph.getByRole('heading', { name: NAME }).first().waitFor({ timeout: 30000 });
      await ph.getByText('Aliganj branch').first().waitFor({ timeout: 20000 });
      const now = (await (await ownerCtx.request.get('/api/v1/cards')).json()).find((c) => c.id === X.id);
      expect(now.url === X.url && now.nfc_url === X.nfc_url && now.public_token === X.public_token, 'the card identity changed');
      const hist = (await (await adminReq.get(`/api/v1/admin/cards/${X.id}`)).json()).history;
      expect(hist.length >= 2 && hist.filter((h) => !h.unassigned_at).length === 1, 'assignment history was not kept');
    });
    await step('business: pause shows a neutral notice, resume brings the same code back', async () => {
      await page.goto(`/cards/${X.id}`);
      await page.getByRole('button', { name: 'Pause' }).click();
      await toastOn(page, 'Card paused');
      await ph.goto(`/q/${X.public_token}`);
      await ph.getByText(/switched off/i).first().waitFor({ timeout: 20000 });
      expect(!(await ph.locator('body').innerText()).includes(NAME), 'a paused card page names the business');
      await page.goto(`/cards/${X.id}`);
      await page.getByRole('button', { name: 'Resume' }).click();
      await toastOn(page, 'Card resumed');
      await ph.goto(`/q/${X.public_token}`);
      await ph.getByRole('heading', { name: NAME }).first().waitFor({ timeout: 30000 });
    });
    await step('business: retiring is explained, confirmed, permanent, and keeps the history', async () => {
      await page.goto(`/cards/${Y.id}`);
      let said = '';
      page.once('dialog', async (d) => { said = d.message(); await d.dismiss(); });
      await page.getByRole('button', { name: 'Retire' }).click();
      await page.waitForTimeout(500);
      expect(/permanent|never be used again/i.test(said), 'the confirmation does not explain permanence: ' + said);
      expect((await (await ownerCtx.request.get('/api/v1/cards')).json()).find((c) => c.id === Y.id).status !== 'retired', 'retired although the dialog was dismissed');
      page.once('dialog', (d) => void d.accept());
      await page.getByRole('button', { name: 'Retire' }).click();
      await toastOn(page, 'Card retired');
      await page.getByText('Retired', { exact: true }).first().waitFor();
      expect(await page.getByRole('button', { name: 'Retire' }).count() === 0 && await page.getByRole('button', { name: 'Resume' }).count() === 0, 'a retired card still offers actions');
      await ph.goto(`/q/${Y.public_token}`);
      await ph.getByText(/no longer active/i).first().waitFor({ timeout: 20000 });
      const detail = (await (await adminReq.get(`/api/v1/admin/cards/${Y.id}`)).json());
      expect(detail.card.status === 'retired' && detail.history[0].ended_reason === 'retired', 'history lost on retirement');
    });
    await step('business: a card FlowHQ reserved shows as waiting, and can be scanned in and placed by the owner', async () => {
      const spare = globalThis.__stock[6];
      let r = await adminReq.post(`/api/v1/admin/cards/${spare.id}/reserve`, { data: { tenant_id: tenant.id }, headers: { 'X-CSRF-Token': adminCsrf } });
      expect(r.status() === 200, 'reserve ' + r.status());
      await page.goto('/cards');
      await page.getByText(/1 card is waiting for you/).waitFor({ timeout: 30000 });
      await page.getByRole('radio', { name: 'Assign cards' }).click();
      await page.getByTestId('assign-cards').getByLabel('Location').selectOption({ label: 'Main clinic – Lucknow' });
      await page.getByRole('button', { name: 'Scan card' }).click();
      await page.getByLabel('Card serial number').fill(spare.card_code);
      await page.getByRole('button', { name: 'Look up' }).click();
      await page.getByTestId('assign-confirm').waitFor({ timeout: 20000 });
      await page.getByRole('button', { name: 'Assign and activate' }).click();
      await page.getByTestId('assigned-ok').waitFor({ timeout: 20000 });
      const now = (await (await ownerCtx.request.get('/api/v1/cards')).json()).find((c) => c.id === spare.id);
      expect(now.status === 'active' && now.location_name === 'Main clinic', 'reserved card was not placed: ' + now.status);
    });
    await step('isolation: another business cannot see, find or assign these cards, and stock cannot be claimed', async () => {
      const O = await otherCtx.newPage(); watch(O);
      await O.goto('/cards');
      await O.getByRole('heading', { name: 'QR/NFC cards' }).waitFor({ timeout: 30000 });
      expect(await O.getByTestId('card-tile').count() === 0, 'another business sees cards');
      await O.getByRole('radio', { name: 'Assign cards' }).click();
      await O.getByTestId('assign-cards').getByLabel('Location').selectOption({ label: 'Other main – Kanpur' });
      for (const serial of [X.card_code, globalThis.__stock[7].card_code]) {  // another business's card, and unclaimed stock
        await O.getByRole('button', { name: 'Scan card' }).click();
        await O.getByLabel('Card serial number').fill(serial);
        await O.getByRole('button', { name: 'Look up' }).click();
        await O.getByRole('alert').filter({ hasText: /not available to your business/ }).first().waitFor({ timeout: 15000 });
        await O.getByRole('button', { name: 'Stop scanning' }).click();
      }
      const claim = await otherCtx.request.post(`/api/v1/cards/${globalThis.__stock[7].id}/assign`, { data: { location_id: 'x' }, headers: { 'X-CSRF-Token': otherCsrf } });
      expect([404, 422].includes(claim.status()), 'a business could claim stock: ' + claim.status());
      expect((await (await adminReq.get(`/api/v1/admin/cards/${globalThis.__stock[7].id}`)).json()).card.status === 'unassigned', 'stock was claimed');
      expect((await otherCtx.request.get('/api/v1/admin/cards/lookup')).status() >= 400, 'a business reached admin');
    });
    await step('no page crashed and no request returned a server error', async () => {
      expect(pageErrors.length === 0, 'page errors: ' + pageErrors.slice(0, 3).join(' | '));
      expect(httpErrors.length === 0, 'HTTP 5xx: ' + httpErrors.slice(0, 3).join(' | '));
    });
    await phone.close();
    if (camBrowser) await camBrowser.close();
  }

  await browser.close();
  try {
    const left = sql(`
      DELETE FROM audit_logs WHERE tenant_id IN (SELECT id FROM tenants WHERE name IN ('${NAME}', '${NAME_B}')) OR user_id IN (SELECT id FROM users WHERE email LIKE 'zz-cards-%${TAG}@example.com');
      DELETE FROM scan_events WHERE card_id IN (SELECT id FROM qr_cards WHERE batch_id IN (SELECT id FROM card_batches WHERE name LIKE '${BATCH}%'));
      DELETE FROM card_assignments WHERE card_id IN (SELECT id FROM qr_cards WHERE batch_id IN (SELECT id FROM card_batches WHERE name LIKE '${BATCH}%'));
      DELETE FROM qr_cards WHERE batch_id IN (SELECT id FROM card_batches WHERE name LIKE '${BATCH}%');
      DELETE FROM card_batches WHERE name LIKE '${BATCH}%';
      DELETE FROM tenants WHERE name IN ('${NAME}', '${NAME_B}');
      DELETE FROM users WHERE email LIKE 'zz-cards-%${TAG}@example.com';
      SELECT 'left: ' || (SELECT count(*) FROM tenants WHERE name IN ('${NAME}', '${NAME_B}')) || ' tenants, ' || (SELECT count(*) FROM users WHERE email LIKE 'zz-cards-%${TAG}@example.com') || ' users, ' || (SELECT count(*) FROM card_batches WHERE name LIKE '${BATCH}%') || ' batches';`);
    console.log('cleanup', left.split('\n').pop());
  } catch (e) { console.log('CLEANUP FAILED (remove ' + NAME + ' and batch ' + BATCH + ' by hand):', String(e.message).slice(0, 300)); }
  const failed = results.filter((r) => !r[1]);
  console.log(`\n${results.length - failed.length}/${results.length} browser checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
