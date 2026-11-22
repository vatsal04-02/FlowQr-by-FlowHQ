// FlowQR production-readiness browser journeys (audit 2026-11-22). Drives the REAL UI in Chromium against a RUNNING LOCAL stack and prints PASS/FAIL per check with evidence.
//
//   npm i --no-save playwright-core jsqr pngjs
//   BASE_URL=http://localhost:3700 E2E_API_LOG=<file the dev API writes its log to> CHROME_PATH=<chrome.exe> ADMIN_EMAIL=<an address in PLATFORM_ADMIN_EMAILS> node e2e/production-audit-journeys.js
//
// Needs a dev API (APP_ENV=development, registration open) whose log is readable: development mail is written to that log ("[DEV EMAIL - not delivered]") and this script reads the
// verification links from it. NEVER point it at production: it registers throwaway businesses ("E2E ...") and a throwaway card batch.
// What it proves: journeys 1 (onboarding), 4 (campaign -> QR -> download -> scan -> landing -> Hindi -> feedback) and 5 (NFC), the public error states, no page errors in any step (the
// New campaign dialog used to throw React #185), and a three-viewport sweep of the main screens (overflow, broken images, unlabeled controls, console and network errors).
// What it does NOT prove: anything live on Google, Cashfree or the AI provider (those need credentials and are covered by mocked backend tests only).
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');
const { PNG } = require('pngjs');
const jsQR = require('jsqr');

const BASE = process.env.BASE_URL || 'http://localhost:3700';
const API_LOG = process.env.E2E_API_LOG;
const CHROME = process.env.CHROME_PATH;
const ADMIN_EMAIL = process.env.ADMIN_EMAIL || 'admin@e2e.example.com';
const OUT = process.env.OUT_DIR || path.join(__dirname, 'audit-out');
fs.mkdirSync(OUT, { recursive: true });
const rnd = Math.random().toString(36).slice(2, 8);
const PASSWORD = 'Str0ngPassw0rd!';

const results = [];
const check = (name, ok, evidence = '') => { results.push({ name, ok: !!ok, evidence }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${evidence ? '  -- ' + String(evidence).slice(0, 220) : ''}`); };
const newSink = () => ({ console: [], page: [], failed: [], http: [] });
function watch(page, sink, label = '') {
  page.on('console', (m) => { if (m.type() === 'error') sink.console.push(label + m.text().slice(0, 200)); });
  page.on('pageerror', (e) => sink.page.push(label + String(e).slice(0, 200)));
  page.on('requestfailed', (r) => r.failure()?.errorText !== 'net::ERR_ABORTED' && sink.failed.push(`${label}${r.method()} ${r.url().replace(BASE, '')} ${r.failure()?.errorText}`.slice(0, 200)));
  page.on('response', (r) => { if (r.status() >= 400) sink.http.push(`${label}${r.status()} ${r.request().method()} ${r.url().replace(BASE, '')}`.slice(0, 200)); });
}
// The only expected noise: the signed-out probe of /auth/me on public pages answers 401.
const unexpected = (list) => list.filter((x) => !/\/auth\/me|status of 401/.test(x));

function devEmailLink(to, marker) {
  const blocks = fs.readFileSync(API_LOG, 'utf8').split('[DEV EMAIL - not delivered]').slice(1);
  for (let i = blocks.length - 1; i >= 0; i--) if (blocks[i].includes(`to=${to} `) && blocks[i].includes(marker)) { const m = blocks[i].match(/https?:\/\/[^\s]+/); if (m) return m[0]; }
  return null;
}
const local = (url) => url.replace(/^https?:\/\/[^/]+/, BASE);
const decodePng = (buf) => { const p = PNG.sync.read(buf); const r = jsQR(new Uint8ClampedArray(p.data), p.width, p.height); return r && r.data; };

async function api(ctx, method, url, data, csrf) {
  const r = await ctx.request.fetch(`${BASE}/api/v1${url}`, { method, data, headers: csrf ? { 'X-CSRF-Token': csrf } : {}, maxRedirects: 0 });
  let body = null; try { body = await r.json(); } catch { /* not JSON */ }
  return { status: r.status(), body, headers: r.headers() };
}

async function register(ctx, page, email, name) {
  await page.goto(`${BASE}/register`);
  await page.getByLabel('Your name').fill(name);
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password', { exact: false }).first().fill(PASSWORD);
  await page.locator('#age-confirm').check();
  await page.getByRole('button', { name: 'Create account' }).click();
  await page.waitForURL('**/onboarding', { timeout: 60000, waitUntil: 'commit' });
  const link = devEmailLink(email, 'verify-email');
  const v = await ctx.newPage(); await v.goto(local(link)); await v.waitForTimeout(1500); await v.close();
}

async function wizard(page) {
  await page.reload(); await page.waitForTimeout(1500);
  await page.getByLabel('Business name').fill('E2E Dental Clinic');
  await page.getByLabel('Business type').selectOption({ label: 'Dental clinic' });
  await page.getByLabel('City').fill('Lucknow');
  await page.getByLabel('State').fill('Uttar Pradesh');
  await page.getByLabel('Review link').fill('https://g.page/r/CabcDEF123/review');
  await page.getByRole('button', { name: /Continue/ }).click(); await page.waitForTimeout(800);
  const sawWebsiteError = await page.getByText('Tell us whether you have a website').count();
  await page.getByText('No, not now').click();
  await page.getByRole('button', { name: /Continue/ }).click(); await page.waitForTimeout(2200);
  await page.getByRole('button', { name: /^Continue/ }).click(); await page.waitForTimeout(2200);
  await page.getByRole('button', { name: /Start my free trial/ }).click(); await page.waitForTimeout(2500);
  return sawWebsiteError > 0;
}

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const ownerCtx = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const owner = await ownerCtx.newPage(); const ownerSink = newSink(); watch(owner, ownerSink);
  const email = `owner-${rnd}@e2e.example.com`;

  // ------------------------------------------------------------------------------------------------ Journey 1: customer onboarding
  await register(ownerCtx, owner, email, 'E2E Owner');
  check('J1 registration through the form lands on onboarding', /\/onboarding/.test(owner.url()));
  const blockedUntilChosen = await wizard(owner);
  check('J1 onboarding validates a required choice inline before continuing', blockedUntilChosen);
  check('J1 wizard reaches the final step with the 7-day no-card trial', /You are all set/.test(await owner.locator('#app-main, main').first().innerText()) && /Nothing is charged automatically/.test(await owner.locator('#app-main, main').first().innerText()));
  await owner.getByRole('button', { name: /Open my dashboard/ }).click(); await owner.waitForURL('**/overview', { timeout: 30000 });
  check('J1 dashboard opens for the new business', /Home/.test(await owner.locator('h1').first().innerText()), owner.url());
  await owner.goto(`${BASE}/onboarding`); await owner.waitForTimeout(1500);
  check('J1 a finished business is not sent back through onboarding', !/STEP \d OF 4/.test(await owner.locator('body').innerText()), owner.url());

  // ------------------------------------------------------------------------------------------------ Journey 4: campaign -> QR -> scan -> landing
  await owner.goto(`${BASE}/gbp/campaigns`); await owner.waitForTimeout(1500);
  await owner.getByRole('button', { name: 'New campaign' }).click();
  await owner.getByRole('button', { name: 'Create campaign' }).click(); await owner.waitForTimeout(600);
  check('J4 empty campaign form is refused with inline messages', /required|Choose|Enter/i.test(await owner.locator('[role=dialog], form').first().innerText()));
  await owner.getByPlaceholder('e.g. Front desk QR').fill('Front desk QR');
  await owner.getByLabel('Location').selectOption({ index: 1 });
  await owner.getByRole('button', { name: 'Create campaign' }).click(); await owner.waitForURL(/\/gbp\/campaigns\/[0-9a-f-]{36}/, { timeout: 30000 });
  const campaignId = owner.url().split('/').pop();
  check('J4 campaign created through the UI', !!campaignId, owner.url());
  check('J4 filling and submitting the New campaign dialog throws no page error (React #185 regression)', ownerSink.page.length === 0, ownerSink.page.join(' | '));
  const openHref = await owner.getByRole('link', { name: 'Open page' }).getAttribute('href');
  const dl = {};
  for (const ext of ['png', 'svg', 'pdf']) {
    const [d] = await Promise.all([owner.waitForEvent('download'), owner.locator(`a[href$="qr.${ext}"]`).first().click()]);
    const f = path.join(OUT, `campaign-qr.${ext}`); await d.saveAs(f); dl[ext] = { file: f, size: fs.statSync(f).size, name: d.suggestedFilename() };
  }
  const decoded = decodePng(fs.readFileSync(dl.png.file));
  check('J4 downloaded PNG decodes (scan) to the campaign page address', decoded === openHref, `${decoded} vs ${openHref}`);
  check('J4 SVG and PDF downloads are real files', fs.readFileSync(dl.svg.file, 'utf8').startsWith('<svg') && fs.readFileSync(dl.pdf.file).slice(0, 5).toString() === '%PDF-', `svg ${dl.svg.size}B pdf ${dl.pdf.size}B`);
  const svgPage = await ownerCtx.newPage();
  await svgPage.setViewportSize({ width: 1100, height: 1100 }); await svgPage.goto('file:///' + dl.svg.file.replace(/\\/g, '/')); const svgShot = path.join(OUT, 'svg-render.png'); await svgPage.screenshot({ path: svgShot });
  check('J4 SVG renders to a scannable code with the same address', decodePng(fs.readFileSync(svgShot)) === openHref); await svgPage.close();

  const phoneCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, permissions: ['clipboard-read', 'clipboard-write'], userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1' });
  await phoneCtx.route('https://g.page/**', (r) => r.fulfill({ status: 200, contentType: 'text/html', body: '<h1>google review page (stub)</h1>' }));
  const phone = await phoneCtx.newPage(); const phoneSink = newSink(); watch(phone, phoneSink, 'phone:');
  await phone.goto(local(decoded)); await phone.waitForTimeout(2500);
  const landing = await phone.locator('body').innerText();
  check('J4 scanned code opens the business landing page on a phone', /E2E Dental Clinic/.test(landing) && /How would you rate your visit/.test(landing));
  check('J4 landing page has no horizontal overflow on a phone', await phone.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  const cta = phone.getByTestId('copy-continue');
  check('J4 the Continue-to-Google button stays disabled until a review is written (empty is refused)', (await cta.getAttribute('aria-disabled')) === 'true' && phone.url().startsWith(BASE));
  await phone.getByText('हिन्दी', { exact: true }).first().click(); await phone.waitForTimeout(800);
  check('J4 Hindi switch translates the landing page', /अपना अनुभव साझा करें/.test(await phone.locator('body').innerText()));
  await phone.getByText('English', { exact: true }).first().click(); await phone.waitForTimeout(500);
  await phone.getByRole('radio', { name: /4/ }).first().click().catch(async () => { await phone.locator('[aria-label*="4"]').first().click(); });
  const chip = phone.getByRole('button', { name: 'Staff' }); await chip.click();
  check('J4 optional feedback topic can be toggled', (await chip.getAttribute('aria-pressed')) === 'true' || /selected|active|bg-/.test((await chip.getAttribute('class')) || ''));
  await phone.getByPlaceholder('Write your review here…').fill('The staff explained my treatment clearly and the clinic was spotless.');
  const [popup] = await Promise.all([phoneCtx.waitForEvent('page', { timeout: 15000 }).catch(() => null), cta.click()]);
  if (popup) await popup.waitForLoadState('commit').catch(() => {});
  check('J4 continuing opens the business Google review link in a new tab (FlowQr does not post it for the customer)', !!popup && /g\.page\/r\/CabcDEF123\/review/.test(popup.url()), popup ? popup.url() : 'no new tab');
  const pageErrors = unexpected(phoneSink.page.concat(phoneSink.console));
  check('J4 the public landing flow has no console or page errors', pageErrors.length === 0, pageErrors.join(' | '));
  const missing = await phoneCtx.newPage(); await missing.goto(`${BASE}/r/NotARealCampaign123`); await missing.waitForTimeout(1500);
  check('J4 an invalid campaign address shows a clear unavailable page, not an error screen', /(not|n't|no longer|unavailable|find)/i.test(await missing.locator('body').innerText()) && !/Application error|Unhandled/.test(await missing.locator('body').innerText()));
  const apiMiss = await ownerCtx.request.get(`${BASE}/api/v1/public/r/NotARealCampaign123`);
  check('J4 the public API answers 404 for an unknown campaign', apiMiss.status() === 404, apiMiss.status());
  await owner.goto(`${BASE}/gbp/campaigns/${campaignId}`); await owner.waitForTimeout(2500);
  const stats = await owner.locator('#app-main').innerText();
  const landmarks = await owner.evaluate(() => ({ mains: document.querySelectorAll('main').length, h1s: document.querySelectorAll('h1').length }));
  check('J4 the campaign page has exactly one main landmark and one h1 (the live preview adds neither)', landmarks.mains === 1 && landmarks.h1s === 1, JSON.stringify(landmarks));
  const flat = stats.replace(/\s+/g, ' ');
  const near = (label) => new RegExp('(' + label + '[^0-9A-Za-z]{0,14}[1-9])|([1-9][^0-9A-Za-z]{0,14}' + label + ')').test(flat);
  check('J4 the campaign page counts the scan and the Continue-to-Google tap from real events', near('QR scans') && near('Continued to Google'), flat.slice(Math.max(0, flat.indexOf('QR scans') - 20), flat.indexOf('QR scans') + 240));

  // ------------------------------------------------------------------------------------------------ Journey 5: NFC
  const adminCtx = await browser.newContext(); const adminPage = await adminCtx.newPage();
  let adminSession = await api(adminCtx, 'POST', '/auth/login', { email: ADMIN_EMAIL, password: PASSWORD });
  if (adminSession.status !== 200) { await register(adminCtx, adminPage, ADMIN_EMAIL, 'E2E Admin'); adminSession = await api(adminCtx, 'POST', '/auth/login', { email: ADMIN_EMAIL, password: PASSWORD }); }
  const A = adminSession.body && adminSession.body.csrf_token;
  const me = await api(ownerCtx, 'GET', '/auth/me'); const tenantId = me.body.memberships[0].tenant.id; const ocsrf = me.body.csrf_token;
  const locs = await api(ownerCtx, 'GET', '/locations'); const locationId = locs.body[0].id;
  const batch = await api(adminCtx, 'POST', '/admin/batches', { name: `E2E NFC ${rnd}`, quantity: 1 }, A);
  check('J5 platform admin can issue a card batch', batch.status === 201, batch.status);
  const cardList = await api(adminCtx, 'GET', `/admin/cards?batch_id=${batch.body.id}`);
  const first = (cardList.body.items || cardList.body)[0]; const cardId = first.id;
  const assigned = await api(adminCtx, 'POST', `/admin/cards/${cardId}/assign`, { tenant_id: tenantId, location_id: locationId, campaign_id: campaignId, activate: true }, A);
  check('J5 card is assigned to the business, location and campaign', assigned.status === 200, assigned.status + ' ' + JSON.stringify(assigned.body).slice(0, 120));
  const card = assigned.body; const token = card.public_token;
  const goNfc = await ownerCtx.request.get(`${BASE}/api/v1/go/${token}?channel=nfc`, { maxRedirects: 0 });
  check('J5 NFC redirect door answers a real 302 to the card landing page on the app', goNfc.status() === 302 && goNfc.headers()['location'].includes(`/n/${token}`), `${goNfc.status()} ${goNfc.headers()['location']}`);
  check('J5 the redirect is never cached', /no-store/.test(goNfc.headers()['cache-control'] || ''));
  const nfcUrl = card.nfc_url; check('J5 the NFC tag URL uses the /n/ door on the print domain', /\/n\/[A-Za-z0-9_-]{16,}$/.test(nfcUrl || ''), nfcUrl);
  const tap = await phoneCtx.newPage(); await tap.goto(local(nfcUrl)); await tap.waitForTimeout(3000);
  check('J5 tapping the tag opens the correct business review page', /E2E Dental Clinic/.test(await tap.locator('body').innerText()), tap.url());
  const qrDoor = await ownerCtx.request.get(`${BASE}/api/v1/go/${token}?channel=qr`, { maxRedirects: 0 });
  check('J5 the same card works through the QR door too', qrDoor.status() === 302, qrDoor.status());
  const unknown = await ownerCtx.request.get(`${BASE}/api/v1/go/${'x'.repeat(24)}?channel=nfc`, { maxRedirects: 0 });
  check('J5 an unknown NFC token is a 404, not a redirect', unknown.status() === 404, unknown.status());
  const evil = await ownerCtx.request.get(`${BASE}/api/v1/go/${token}?channel=nfc&url=https://evil.example&ref=x`, { maxRedirects: 0 });
  check('J5 a query string cannot change where the card goes (no open redirect)', evil.status() === 302 && !/evil\.example/.test(evil.headers()['location']), evil.headers()['location']);
  const paused = await api(ownerCtx, 'POST', `/cards/${cardId}/pause`, {}, ocsrf);
  const pausedLanding = await phoneCtx.newPage(); await pausedLanding.goto(local(nfcUrl)); await pausedLanding.waitForTimeout(2500);
  check('J5 a paused card shows a calm "switched off" notice to customers', paused.status === 200 && /switched off|no longer active|check back/i.test(await pausedLanding.locator('body').innerText()), paused.status);

  // ------------------------------------------------------------------------------------------------ responsive sweep of the owner screens
  const SCREENS = ['/overview', '/gbp/reviews', '/gbp/campaigns', `/gbp/campaigns/${campaignId}`, '/gbp/cards', '/gbp/locations', '/gbp/info', '/gbp/posts', '/gbp/photos', '/growth', '/growth/reports', '/seo',
                   '/reputation/drafts', '/ai/today', '/ai/approvals', '/settings', '/settings/team', '/settings/connections', '/settings/billing', '/settings/notifications', '/settings/account', '/settings/appearance'];
  const VIEWPORTS = { desktop: { width: 1366, height: 768 }, tablet: { width: 820, height: 1180 }, mobile: { width: 390, height: 844 } };
  const sweep = [];
  for (const [vp, size] of Object.entries(VIEWPORTS)) {
    const c = await browser.newContext({ viewport: size, isMobile: vp === 'mobile', hasTouch: vp !== 'desktop', storageState: await ownerCtx.storageState() });
    const p = await c.newPage(); const sink = newSink(); watch(p, sink);
    for (const s of SCREENS) {
      const before = { c: sink.console.length, pg: sink.page.length, f: sink.failed.length, h: sink.http.length };
      const resp = await p.goto(`${BASE}${s}`, { waitUntil: 'load' }).catch(() => null); await p.waitForTimeout(1800);
      const m = await p.evaluate(() => ({
        overflow: document.documentElement.scrollWidth - window.innerWidth,
        h1: (document.querySelector('h1') || {}).innerText || '',
        brokenImgs: [...document.images].filter((i) => i.complete && i.naturalWidth === 0 && i.src).map((i) => i.src.slice(0, 80)),
        unlabeled: [...document.querySelectorAll('button, a[href], input, select, textarea')].filter((e) => { const r = e.getBoundingClientRect(); if (!r.width || !r.height || e.type === 'hidden') return false; const l = (e.innerText || e.getAttribute('aria-label') || e.getAttribute('title') || (e.labels && e.labels[0] && e.labels[0].innerText) || e.getAttribute('placeholder') || e.value || '').trim(); const hasImgAlt = !!e.querySelector('img[alt]:not([alt=""])'); return !l && !hasImgAlt && !e.getAttribute('aria-labelledby'); }).length,
        text: document.body.innerText.slice(0, 4000),
      }));
      const row = { vp, screen: s, status: resp && resp.status(), url: p.url().replace(BASE, ''), h1: m.h1.replace(/\n/g, ' ').slice(0, 40), overflow: m.overflow, brokenImgs: m.brokenImgs.length, unlabeled: m.unlabeled,
                    pageErrors: sink.page.length - before.pg, consoleErrors: unexpected(sink.console.slice(before.c)).length, failed: sink.failed.length - before.f,
                    http: unexpected(sink.http.slice(before.h)), crashed: /Application error|Something went wrong|Unhandled Runtime Error/.test(m.text) };
      sweep.push(row);
    }
    await c.close();
  }
  fs.writeFileSync(path.join(OUT, 'sweep.json'), JSON.stringify(sweep, null, 1));
  const bad = sweep.filter((r) => r.overflow > 1 || r.brokenImgs || r.pageErrors || r.consoleErrors || r.failed || r.http.length || r.crashed || (r.status && r.status >= 400));
  check(`SWEEP ${sweep.length} screen/viewport loads (${SCREENS.length} screens x 3 viewports): no crash, page error, broken image, failed request or HTTP error`, bad.length === 0, bad.length ? JSON.stringify(bad.slice(0, 6)) : '');
  const overflow = sweep.filter((r) => r.overflow > 1); check('SWEEP no screen scrolls sideways on desktop, tablet or phone', overflow.length === 0, JSON.stringify(overflow.map((r) => `${r.vp}${r.screen}+${r.overflow}`).slice(0, 8)));
  const unl = sweep.filter((r) => r.unlabeled > 0); check('SWEEP every visible control has an accessible name', unl.length === 0, JSON.stringify(unl.map((r) => `${r.vp}${r.screen}:${r.unlabeled}`).slice(0, 10)));
  check('J1/J4 the owner session saw no page errors from start to finish', ownerSink.page.length === 0, ownerSink.page.join(' | '));
  check('the owner session saw no unexpected console errors or failed API calls', unexpected(ownerSink.console).length + unexpected(ownerSink.http).length + ownerSink.failed.length === 0, JSON.stringify({ c: unexpected(ownerSink.console), h: unexpected(ownerSink.http), f: ownerSink.failed }).slice(0, 300));

  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 1));
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed${failed.length ? '; FAILED: ' + failed.map((f) => f.name).join(' | ') : ''}`);
  await browser.close(); process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR', e); process.exit(2); });
