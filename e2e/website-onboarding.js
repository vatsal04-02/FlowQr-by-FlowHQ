// AI website from onboarding: REAL BROWSER test (Playwright) at desktop and 320/360/375/390/414 px.
// Real Next.js app and FlowQR API on a throwaway database; the AI is a scripted stand-in and the worker a thread (e2e/website-rig/rig_api.py). Proves the screens, not Google or a real model.
//   BASE_URL=http://localhost:3012 RIG_URL=http://127.0.0.1:18031 CHROME_PATH=<chrome.exe> SHOTS_DIR=./shots node e2e/website-onboarding.js   (exits 1 on any failure)
let chromium; try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }
const fs = require('fs');
const BASE = process.env.BASE_URL || 'http://localhost:3012';
const RIG = process.env.RIG_URL || 'http://127.0.0.1:18031';
const SHOTS = process.env.SHOTS_DIR || './e2e/shots-website';
const PW = 'Str0ngPassw0rd!';
const rnd = Math.random().toString(36).slice(2, 7);
fs.mkdirSync(SHOTS, { recursive: true });
let failures = 0, passes = 0;
const check = (name, ok, extra = '') => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  ' + extra : ''}`); ok ? passes++ : failures++; };
const sql = (q, p) => fetch(RIG + '/rig/sql', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ q, p }) }).then((r) => r.json());

async function account(browser, email, name, vp) {
  const ctx = await browser.newContext({ baseURL: BASE, viewport: vp });
  await ctx.request.post('/api/v1/auth/register', { data: { email, password: PW, age_confirmed: true, full_name: name } });
  await sql('UPDATE users SET email_verified_at = now() WHERE email = :e', { e: email });
  const r = await ctx.request.post('/api/v1/auth/login', { data: { email, password: PW } });
  const h = { 'X-CSRF-Token': (await r.json()).csrf_token };
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  return { ctx, page, h, errors };
}
const settle = (page) => page.getByRole('status', { name: 'Loading FlowQR' }).waitFor({ state: 'detached', timeout: 20000 }).catch(() => {});
const noSideScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);

(async () => {
  const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});
  const a = await account(browser, `web-${rnd}@clinic.example`, 'Gomti Physio', { width: 1440, height: 900 });
  const { page, ctx, h } = a;
  const shot = (n) => page.screenshot({ path: `${SHOTS}/${n}.png`, fullPage: true });

  // ------------------------------------------------ onboarding question
  await page.goto('/onboarding'); await settle(page);
  await page.getByText('Do you have a website?').first().waitFor({ timeout: 30000 });
  const radios = page.locator('input[name="website_interest"]');
  check('onboarding asks the website question with exactly two answers', await radios.count() === 2, String(await radios.count()));
  await page.getByText('No, I don’t have a website').click();
  check('choosing "no" shows the AI promise and that nothing publishes without approval', await page.getByText('build your business website with AI', { exact: false }).count() >= 1 && await page.getByText('nothing is published until you approve it', { exact: false }).count() === 1);
  await shot('onboarding-question');
  await page.getByText('Yes, I already have a website').click();
  check('choosing "yes" asks for the website address and shows no generation promise', await page.getByLabel('Your website address').count() === 1 && await page.getByText('Your AI team will understand your business', { exact: false }).count() === 0);

  // the business and its first location (the same calls the step makes), then the website stage
  let r = await ctx.request.post('/api/v1/tenants', { data: { name: 'Gomti Physio', category: 'Physiotherapy clinic', language: 'en', phone: '98765 43210' }, headers: h });
  const tenant = await r.json();
  await ctx.request.post('/api/v1/locations', { data: { name: 'Main branch', city: 'Lucknow', address_line: '2 Viram Khand' }, headers: h });
  await ctx.request.put('/api/v1/agent/knowledge', { data: { description: 'Physiotherapy for back and neck pain in Lucknow.', services: ['Back care', 'Neck pain physiotherapy'], offers: [], faqs: [], prohibited_claims: [] }, headers: h });
  await ctx.request.put('/api/v1/tenant/website-interest', { data: { interest: 'wants_site' }, headers: h });

  await page.goto('/onboarding/website'); await settle(page);
  await page.getByRole('button', { name: 'Create my website with AI' }).waitFor({ timeout: 60000 });
  check('start screen offers creating without Google, and Google as optional', await page.getByText('(optional)').count() === 1);
  await page.getByRole('button', { name: 'Create my website with AI' }).click();
  await page.getByRole('heading', { name: 'Building your digital presence.' }).waitFor();
  await page.locator('ol li[aria-current="step"]').waitFor({ timeout: 15000 });
  const steps = page.locator('section[aria-label="Progress"] ol li');
  const mid = await steps.allInnerTexts();
  const finishedMid = mid.filter((t) => /Completed|Skipped/.test(t)).length;
  check('twelve real steps are listed, and not all are finished while one is running', mid.length === 12 && finishedMid < 12, `${finishedMid}/12 finished`);
  await page.waitForFunction(() => /[4-9] of 12|1[01] of 12/.test(document.body.innerText), null, { timeout: 30000 });
  await page.frameLocator('iframe[title="Preview of your website"]').locator('body').waitFor({ timeout: 20000 });
  const building = await page.getByRole('heading', { name: 'Building your digital presence.' }).count();
  check('the live preview shows the page while it is still being built', building === 1);
  await page.waitForTimeout(600);
  await shot('generating-desktop');

  // ------------------------------------------------ refresh in the middle: same job, no duplicate
  await page.reload(); await settle(page);
  await page.getByRole('heading', { name: /Building your digital presence|Your website is ready/ }).waitFor();
  const jobs = (await sql('SELECT count(*) FROM site_generation_jobs WHERE tenant_id = :t', { t: tenant.id })).rows[0][0];
  check('refreshing during generation recovers the same job and starts no second one', jobs === 1, `jobs=${jobs}`);

  await page.getByRole('heading', { name: 'Your website is ready for review.' }).waitFor({ timeout: 60000 });
  const frame = page.frameLocator('iframe[title="Preview of your website"]');
  await frame.getByText('Physiotherapy for back and neck pain in Lucknow').first().waitFor({ timeout: 20000 });
  check('the preview shows the generated page rendered by the builder', true);
  check('it says the website was generated and is a draft that is not public', await page.getByText('Website generated').count() === 1 && await page.getByText('Draft: not public').count() === 1);
  check('missing details are listed for the owner to check', await page.getByText('Please check these').count() === 1);
  await shot('review-desktop');
  for (const d of ['Tablet', 'Mobile', 'Desktop']) await page.getByRole('tab', { name: d }).click();
  check('desktop, tablet and mobile previews switch', await page.getByRole('tab', { name: 'Desktop' }).getAttribute('aria-selected') === 'true');

  // ------------------------------------------------ edit, AI change, colour, publish
  await page.getByRole('button', { name: /^About/ }).click();
  await page.getByLabel('Heading').first().fill('About Gomti Physio today');
  await page.getByRole('button', { name: 'Save section' }).click();
  await page.getByText('About saved.').waitFor();
  await frame.getByText('About Gomti Physio today').waitFor({ timeout: 15000 });
  check('the owner edits a section and the preview shows it', true);
  await page.getByRole('button', { name: 'Improve the headline' }).click();
  await frame.getByText('Move comfortably again').first().waitFor({ timeout: 15000 });
  check('an AI change updates only what was asked (the edited section stays)', await frame.getByText('About Gomti Physio today').count() === 1);
  await page.getByRole('radio', { name: 'navy' }).click();
  await page.waitForFunction(() => document.querySelector('[role="radio"][aria-label="navy"]')?.getAttribute('aria-checked') === 'true');
  check('the colour can be changed', true);
  await page.getByRole('button', { name: 'Approve for publishing' }).click();
  await page.getByText('Your approval is recorded. Nothing is public yet', { exact: false }).waitFor();
  const site = (await sql('SELECT status, published_content IS NULL, commercial_status FROM sites WHERE tenant_id = :t', { t: tenant.id })).rows[0];
  check('publishing needs hosting: the approval is recorded and nothing is public', site[0] === 'draft' && site[1] === true && site[2] === 'not_activated', JSON.stringify(site));
  await page.getByRole('button', { name: 'Keep as draft and continue' }).click();
  await page.waitForURL(/\/onboarding\?step=launch/);
  check('"keep as draft" continues set-up at the launch step', true);

  // ------------------------------------------------ small screens
  await page.goto('/onboarding/website'); await settle(page);
  await page.getByRole('heading', { name: 'Your website is ready for review.' }).waitFor({ timeout: 30000 });
  for (const w of [320, 360, 375, 390, 414]) {
    await page.setViewportSize({ width: w, height: 780 });
    await page.waitForTimeout(500);
    check(`${w}px review: no sideways scroll`, await noSideScroll(page));
  }
  await shot('review-phone');
  const small = await page.evaluate(() => [...document.querySelectorAll('main button, main a, main select')].filter((e) => e.offsetParent !== null).filter((e) => { const b = e.getBoundingClientRect(); return b.width < 24 || b.height < 24; }).map((e) => e.innerText.slice(0, 20)));
  check('phone: every control is at least 24px', small.length === 0, small.join(' ; '));

  // ------------------------------------------------ progress on a phone
  const b = await account(browser, `web2-${rnd}@clinic.example`, 'Aliganj Physio', { width: 360, height: 760 });
  r = await b.ctx.request.post('/api/v1/tenants', { data: { name: 'Aliganj Physio', category: 'Physiotherapy clinic', language: 'en' }, headers: b.h });
  await b.ctx.request.post('/api/v1/locations', { data: { name: 'Main', city: 'Lucknow' }, headers: b.h });
  await b.ctx.request.put('/api/v1/tenant/website-interest', { data: { interest: 'wants_site' }, headers: b.h });
  await b.page.goto('/onboarding/website'); await settle(b.page);
  await b.page.getByRole('button', { name: 'Create my website with AI' }).click();
  await b.page.getByRole('tab', { name: 'Progress' }).waitFor();
  check('phone: progress first, preview behind a tab, no sideways scroll', await b.page.locator('section[aria-label="Progress"]').isVisible() && await noSideScroll(b.page));
  await b.page.screenshot({ path: `${SHOTS}/generating-phone.png` });
  await b.page.getByRole('tab', { name: 'Preview' }).click();
  check('phone: the preview tab opens without sideways scroll', await noSideScroll(b.page));
  const other = await (await b.ctx.request.get('/api/v1/website/preview')).text();
  check('a business only ever sees its own draft', !other.includes('About Gomti Physio today'));

  check('no uncaught page errors', a.errors.length + b.errors.length === 0, [...a.errors, ...b.errors].slice(0, 2).join(' | '));
  await browser.close();
  console.log(failures ? `${failures} FAILED, ${passes} passed` : `ALL ${passes} PASSED`);
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR', e.stack || e.message); process.exit(2); });
