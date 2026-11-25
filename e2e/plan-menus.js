// REAL BROWSER test: what each plan's menu shows, and what a pasted link to a page outside the plan shows. The plan is set in the database (the rig has no payment); everything else is the real app.
//   BASE_URL=http://localhost:3012 RIG_URL=http://127.0.0.1:18031 CHROME_PATH=<chrome.exe> SHOTS_DIR=./shots node e2e/plan-menus.js
let chromium; try { ({ chromium } = require('playwright')); } catch { ({ chromium } = require('playwright-core')); }
const BASE = process.env.BASE_URL || 'http://localhost:3012', RIG = process.env.RIG_URL || 'http://127.0.0.1:18031', SHOTS = process.env.SHOTS_DIR || './shots';
require('fs').mkdirSync(SHOTS, { recursive: true });
const PW = 'Str0ngPassw0rd!', rnd = Math.random().toString(36).slice(2, 7);
let failures = 0, passes = 0;
const check = (n, ok, x = '') => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${x ? '  ' + x : ''}`); ok ? passes++ : failures++; };
const sql = (q, p) => fetch(RIG + '/rig/sql', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ q, p }) }).then((r) => r.json());
const STUDIO = ['/gbp/studio', '/gbp/posts', '/gbp/photos'], SEO_PRO = ['/seo/rankings', '/seo/performance'], AI = ['/ai/today', '/ai/tasks', '/ai/activity', '/ai/operator'], ALWAYS = ['/overview', '/gbp/reviews', '/growth', '/gbp/locations', '/settings', '/seo'];
(async () => {
  const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});
  for (const [code, label] of [['starter', 'Launch'], ['growth', 'Growth'], ['pro', 'Scale']]) {
    const ctx = await browser.newContext({ baseURL: BASE, viewport: { width: 1440, height: 900 } });
    const email = `${code}-${rnd}@plan.example`;
    await ctx.request.post('/api/v1/auth/register', { data: { email, password: PW, age_confirmed: true, full_name: `${label} Owner` } });
    await sql('UPDATE users SET email_verified_at = now() WHERE email = :e', { e: email });
    const r = await ctx.request.post('/api/v1/auth/login', { data: { email, password: PW } });
    const h = { 'X-CSRF-Token': (await r.json()).csrf_token };
    const t = await (await ctx.request.post('/api/v1/tenants', { data: { name: `${label} Cafe ${rnd}`, category: 'Cafe', language: 'en', phone: '98765 43210' }, headers: h })).json();
    await sql('UPDATE tenants SET onboarding_completed = true WHERE id = :t', { t: t.id });
    await sql("UPDATE subscriptions s SET plan = bp.code, status = 'active', features = bp.features, review_generations = bp.review_generations, review_replies = bp.review_replies FROM billing_plans bp WHERE bp.code = :p AND s.tenant_id = :t", { p: code, t: t.id });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto('/overview');
    await page.locator('aside a[href="/overview"], nav a[href="/overview"]').first().waitFor({ timeout: 90000 });
    await page.waitForTimeout(1500);
    const links = await page.evaluate(() => [...new Set([...document.querySelectorAll('aside a[href], nav a[href]')].map((a) => a.getAttribute('href')))]);
    const shows = (list) => list.filter((x) => links.includes(x));
    check(`${label}: the menu keeps what every plan has`, ALWAYS.filter((x) => !links.includes(x)).length === 0, 'missing ' + ALWAYS.filter((x) => !links.includes(x)).join(' '));
    if (code === 'starter') {
      check(`${label}: no Marketing Studio, no rankings or performance, no AI assistant in the menu`, shows([...STUDIO, ...SEO_PRO, ...AI]).length === 0, 'still shown: ' + shows([...STUDIO, ...SEO_PRO, ...AI]).join(' '));
      await page.goto('/gbp/studio');
      await page.getByRole('heading', { name: /is not part of your Launch plan/ }).waitFor({ timeout: 30000 });
      check(`${label}: a pasted link to the Studio says it is not in the plan and offers the plans`, await page.getByText('included in Growth and Scale', { exact: false }).count() > 0 && await page.getByRole('link', { name: 'See plans' }).count() === 1);
      await page.screenshot({ path: `${SHOTS}/plan-locked-${code}.png` });
      await page.goto('/seo/rankings');
      check(`${label}: a pasted link to rankings is locked`, await page.getByRole('heading', { name: /is not part of your Launch plan/ }).waitFor({ timeout: 30000 }).then(() => true, () => false));
      await page.goto('/ai/today');
      check(`${label}: the AI assistant link is locked too`, await page.getByRole('heading', { name: /is not part of your Launch plan/ }).waitFor({ timeout: 30000 }).then(() => true, () => false));
      await page.goto('/gbp/reviews');
      check(`${label}: reviews still open`, await page.getByRole('heading', { name: /is not part of your/ }).count() === 0);
    } else {
      check(`${label}: Studio, rankings and the AI assistant are in the menu`, ['/gbp/studio', '/ai/today', '/ai/tasks'].every((x) => links.includes(x)), 'shown: ' + shows([...STUDIO, ...SEO_PRO, ...AI]).join(' '));
      await page.goto('/gbp/studio');
      await page.waitForTimeout(2500);
      check(`${label}: the Studio opens, no plan panel`, await page.getByRole('heading', { name: /is not part of your/ }).count() === 0);
      await page.goto('/seo/rankings'); await page.waitForTimeout(2500);
      check(`${label}: rankings open, no plan panel`, await page.getByRole('heading', { name: /is not part of your/ }).count() === 0);
    }
    await page.setViewportSize({ width: 390, height: 800 });
    await page.goto('/overview');
    await page.getByRole('button', { name: /More/ }).first().click({ timeout: 30000 });
    await page.waitForTimeout(800);
    const more = await page.evaluate(() => [...document.querySelectorAll('[role="dialog"] a[href]')].map((a) => a.getAttribute('href')));
    check(`${label}: the phone More sheet follows the plan`, code === 'starter' ? !more.includes('/ai/today') && !more.includes('/ai/tasks') && more.includes('/growth') : more.includes('/ai/today'), more.join(' '));
    await page.screenshot({ path: `${SHOTS}/plan-more-${code}.png` });
    check(`${label}: no uncaught errors`, errors.length === 0, errors.slice(0, 2).join(' | '));
    await ctx.close();
  }
  await browser.close();
  console.log(failures ? `${failures} FAILED, ${passes} passed` : `ALL ${passes} PASSED`);
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR', e.stack || e.message); process.exit(2); });
