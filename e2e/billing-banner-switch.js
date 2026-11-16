// Regression: the "Plan inactive" notice follows the SELECTED business (it used to keep the previous business's status after a switch, until a hard reload).
//   BASE_URL=http://localhost:3000 E2E_SESSION=<flowqr_session cookie> E2E_CSRF=<flowqr_csrf cookie> [PW_CHANNEL=chrome] node e2e/billing-banner-switch.js
// Any logged-in test business works. The network is mocked at the browser edge (two businesses: A has an ended trial, B a running one; the plan answer follows whichever is selected),
// so nothing is read from or written to a real subscription. Covers both directions, the loading gap (the old status must not show while the new one is fetched), a hard reload, and 390 + 1440.
const { chromium } = require('playwright');

const BASE = process.env.BASE_URL || 'http://localhost:3000';
const SESSION = process.env.E2E_SESSION, CSRF = process.env.E2E_CSRF;
if (!SESSION || !CSRF) { console.error('Set E2E_SESSION and E2E_CSRF (the flowqr_session and flowqr_csrf cookies of a logged-in test business).'); process.exit(2); }
const host = new URL(BASE).hostname;
const A = { id: 'aaaaaaaa-0000-0000-0000-000000000001', name: 'Business A (trial ended)' };
const B = { id: 'bbbbbbbb-0000-0000-0000-000000000002', name: 'Business B (trial running)' };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const check = (name, ok, extra) => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  ' + extra : ''}`); };

async function session(browser, viewport, start) {
  const ctx = await browser.newContext({ baseURL: BASE, viewport, hasTouch: viewport.width < 768, isMobile: viewport.width < 768, reducedMotion: 'reduce' });
  await ctx.addCookies([{ name: 'flowqr_session', value: SESSION, domain: host, path: '/', httpOnly: true }, { name: 'flowqr_csrf', value: CSRF, domain: host, path: '/' }]);
  const page = await ctx.newPage();
  const st = { current: start, subscriptionCalls: 0, delayMs: 0 };
  await page.route(/\/api\/v1\/auth\/me$/, async (route) => {
    const res = await route.fetch(); const j = await res.json(); const base = j.memberships[0];
    j.memberships = [A, B].map((t) => ({ ...base, tenant: { ...base.tenant, id: t.id, name: t.name } }));
    j.active_tenant_id = (st.current === 'A' ? A : B).id;
    return route.fulfill({ response: res, json: j });
  });
  await page.route(/\/api\/v1\/auth\/select-tenant/, (route) => { st.current = route.request().url().includes(B.id) ? 'B' : 'A'; return route.fulfill({ json: { ok: true } }); });
  await page.route(/\/api\/v1\/billing\/subscription$/, async (route) => {
    st.subscriptionCalls++;
    const answeringFor = st.current; // what the server would answer for: the business selected at the moment the request arrives
    if (st.delayMs) await sleep(st.delayMs);
    const res = await route.fetch(); const j = await res.json();
    Object.assign(j, answeringFor === 'A' ? { status: 'expired', active: false, inactive_reason: 'trial_ended' } : { status: 'trialing', active: true, inactive_reason: null });
    return route.fulfill({ response: res, json: j });
  });
  await page.goto('/overview'); await page.waitForTimeout(2500);
  return { ctx, page, st };
}
const banner = (page) => page.getByText('Plan inactive').first().isVisible().catch(() => false);
async function switchTo(page, t) { await page.getByRole('button', { name: 'Business menu' }).click(); await page.getByRole('button', { name: t.name }).click(); }

(async () => {
  const browser = await chromium.launch(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {});
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    const tag = `${w}px`;
    // direction 1: expired -> active. The old business's "Plan inactive" must go, and must not linger while the new answer is loading.
    { const { ctx, page, st } = await session(browser, { width: w, height: h }, 'A');
      check(`${tag} start on A (trial ended): banner shown`, await banner(page));
      st.delayMs = 1500; const before = st.subscriptionCalls;
      await switchTo(page, B); await page.waitForTimeout(500);
      check(`${tag} A->B: no stale "Plan inactive" while the new status is loading`, !(await banner(page)));
      await page.waitForTimeout(2500);
      check(`${tag} A->B: plan status fetched again for B`, st.subscriptionCalls === before + 1, `(calls ${before} -> ${st.subscriptionCalls})`);
      check(`${tag} A->B: no banner for the running trial`, !(await banner(page)));
      await page.reload(); await page.waitForTimeout(2500);
      check(`${tag} A->B: still no banner after a hard reload`, !(await banner(page)));
      await ctx.close(); }
    // direction 2: active -> expired, then back again in the same session (no reload anywhere).
    { const { ctx, page, st } = await session(browser, { width: w, height: h }, 'B');
      check(`${tag} start on B (trial running): no banner`, !(await banner(page)));
      st.delayMs = 1500; const before = st.subscriptionCalls;
      await switchTo(page, A); await page.waitForTimeout(500);
      check(`${tag} B->A: nothing shown while the new status is loading`, !(await banner(page)));
      await page.waitForTimeout(2500);
      check(`${tag} B->A: "Plan inactive" shown for the ended trial`, await banner(page));
      check(`${tag} B->A: plan status fetched again for A`, st.subscriptionCalls === before + 1, `(calls ${before} -> ${st.subscriptionCalls})`);
      st.delayMs = 0; await switchTo(page, B); await page.waitForTimeout(1500);
      check(`${tag} A->B again in the same session: banner gone`, !(await banner(page)));
      await switchTo(page, A); await page.waitForTimeout(1500);
      check(`${tag} B->A again: banner back`, await banner(page));
      await ctx.close(); }
  }
  await browser.close();
  console.log(failed ? `\n${failed} check(s) FAILED` : '\nAll checks passed');
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
