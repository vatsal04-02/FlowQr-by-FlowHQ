// FlowQR responsive shell test (Playwright). Real browser, real app: navigation on phone / tablet / desktop, the More sheet, the Home page rules, mobile tables and redirects.
//
//   BASE_URL=http://localhost:3000 E2E_SESSION=<flowqr_session cookie> E2E_CSRF=<flowqr_csrf cookie> node e2e/mobile-shell.js
//
// It needs a logged-in business that has finished onboarding (use any test business on a local stack; the cookies come from POST /api/v1/auth/login). Set PW_CHANNEL=chrome to use the
// installed Google Chrome instead of Playwright's own Chromium. Exits 1 on the first failed check group.
const { chromium } = require('playwright');
const BASE = process.env.BASE_URL || 'http://localhost:3000';
const SESSION = process.env.E2E_SESSION, CSRF = process.env.E2E_CSRF;
if (!SESSION || !CSRF) { console.error('Set E2E_SESSION and E2E_CSRF (the flowqr_session and flowqr_csrf cookies of a logged-in test business).'); process.exit(2); }
const host = new URL(BASE).hostname;
let failures = 0;
const check = (name, ok, extra = '') => { console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  ' + extra : ''}`); if (!ok) failures++; };

async function open(browser, viewport, opts = {}) {
  const ctx = await browser.newContext({ baseURL: BASE, viewport, hasTouch: viewport.width < 768, isMobile: viewport.width < 768, reducedMotion: opts.reducedMotion, colorScheme: opts.colorScheme || 'light' });
  await ctx.addCookies([{ name: 'flowqr_session', value: SESSION, domain: host, path: '/', httpOnly: true }, { name: 'flowqr_csrf', value: CSRF, domain: host, path: '/' }]);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  return { ctx, page, errors };
}
const noSideScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);

(async () => {
  const browser = await chromium.launch(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {});

  // ------------------------------------------------------------------ phone
  for (const vp of [{ width: 360, height: 800 }, { width: 390, height: 844 }, { width: 430, height: 932 }]) {
    const { ctx, page, errors } = await open(browser, vp);
    await page.goto('/overview'); await page.getByRole('heading', { level: 1 }).waitFor();
    const tag = `phone ${vp.width}x${vp.height}`;
    const bar = page.getByRole('navigation', { name: 'Primary' });
    check(`${tag}: bottom bar is visible`, await bar.isVisible());
    const labels = await bar.locator('a, button').allInnerTexts();
    check(`${tag}: exactly Home, Studio, Reviews, Google, More`, JSON.stringify(labels.map((t) => t.split(String.fromCharCode(10))[0].trim())) === JSON.stringify(['Home', 'Studio', 'Reviews', 'Google', 'More']), JSON.stringify(labels));
    const sizes = await bar.locator('a, button').evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }));
    check(`${tag}: every bottom-bar target is at least 44px`, sizes.every(([w, h]) => w >= 44 && h >= 44), JSON.stringify(sizes));
    const gap = await bar.evaluate((n) => Math.round(window.innerHeight - n.getBoundingClientRect().bottom));
    check(`${tag}: bar sits on the bottom edge`, gap === 0, `gap ${gap}`);
    check(`${tag}: no sidebar and no second navigation`, !(await page.getByRole('navigation', { name: 'Main navigation' }).isVisible().catch(() => false)) && (await page.locator('aside').filter({ hasText: 'FlowQR' }).isVisible().catch(() => false)) === false);
    check(`${tag}: top bar has business, search, notifications, account`, await page.getByRole('button', { name: 'Business menu' }).isVisible() && await page.getByRole('button', { name: /Search/ }).isVisible() && await page.getByRole('button', { name: /Notifications/ }).isVisible() && await page.getByRole('button', { name: 'Account menu' }).isVisible());
    check(`${tag}: Home has no sideways scroll`, await noSideScroll(page));
    // the last content is not hidden behind the bar
    await page.waitForTimeout(2500); // let the page finish loading so its full height is known
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const clear = await page.evaluate(() => { const last = document.querySelector('#app-main').lastElementChild; const b = document.querySelector('nav[aria-label=Primary]'); return last.getBoundingClientRect().bottom <= b.getBoundingClientRect().top + 1; });
    check(`${tag}: page content ends above the bottom bar`, clear);

    await bar.getByRole('link', { name: 'Reviews' }).click(); await page.waitForURL('**/gbp/reviews**');
    check(`${tag}: Reviews opens the reviews page`, true);
    await bar.getByRole('link', { name: /GBP/ }).click(); await page.waitForURL('**/seo');
    check(`${tag}: GBP is marked current`, (await bar.getByRole('link', { name: /GBP/ }).getAttribute('aria-current')) === 'page');

    // More sheet
    const more = bar.getByRole('button', { name: 'More' });
    await more.click();
    const dlg = page.getByRole('dialog', { name: 'More' });
    await dlg.waitFor();
    for (const t of ['Business', 'Assistant', 'Account']) check(`${tag}: More shows the group "${t}"`, await dlg.getByRole('heading', { name: t }).isVisible());
    for (const t of ['Locations', 'AI Assistant', 'Tasks & Approvals', 'Activity', 'Settings', 'Billing', 'Help & Support']) check(`${tag}: More lists ${t}`, (await dlg.getByText(t, { exact: true }).count()) > 0);
    const focusInside = await page.evaluate(() => !!document.activeElement.closest('[role=dialog]'));
    check(`${tag}: focus moves into the sheet`, focusInside);
    await page.keyboard.press('Escape'); await dlg.waitFor({ state: 'hidden' });
    check(`${tag}: Escape closes the sheet and focus returns to More`, await page.evaluate(() => document.activeElement && document.activeElement.textContent.includes('More')));
    await more.click(); await dlg.getByRole('link', { name: /Locations/ }).click(); await page.waitForURL('**/gbp/locations'); await dlg.waitFor({ state: 'hidden' });
    check(`${tag}: choosing a page closes the sheet and opens it (More stays lit)`, !(await dlg.isVisible().catch(() => false)) && (await more.evaluate((b) => b.className.includes('accent'))));

    // Home rules
    await page.goto('/overview'); await page.getByRole('heading', { level: 1 }).waitFor(); await page.waitForTimeout(1500);
    const metrics = await page.locator('main .grid.grid-cols-2 > a').count();
    check(`${tag}: Home shows four numbers`, metrics === 4, `${metrics}`);
    check(`${tag}: Home opens with the Growth score`, await page.getByRole('img', { name: /Growth score|No score yet/ }).first().isVisible());
    const todos = await page.locator('section[aria-label="Do this week"] li').first().locator('xpath=..').locator('li').count();
    check(`${tag}: Home lists exactly three moves for the week`, todos === 3, `${todos}`);
    check(`${tag}: no console errors`, errors.length === 0, errors.slice(0, 2).join(' | '));
    await ctx.close();
  }

  // ------------------------------------------------------------------ tables become cards on a phone
  {
    const { ctx, page } = await open(browser, { width: 390, height: 844 });
    await page.goto('/seo/competitors'); await page.getByRole('heading', { level: 1 }).waitFor(); await page.waitForTimeout(2500);
    const list = page.getByRole('list', { name: 'Businesses seen next to you' });
    if (await list.count()) {
      check('phone: a table becomes a list of cards (competitors)', await list.isVisible() && !(await page.locator('table[aria-label="Businesses seen next to you"]').isVisible()));
    } else { console.log('SKIP  phone: no tracked words in this test business'); }
    await ctx.close();
  }

  // ------------------------------------------------------------------ tablet and desktop
  {
    const { ctx, page } = await open(browser, { width: 768, height: 1024 });
    await page.goto('/overview'); await page.getByRole('heading', { level: 1 }).waitFor();
    const side = page.getByRole('navigation', { name: 'Main navigation' }).or(page.locator('aside[aria-label="Main navigation"]'));
    check('tablet 768: sidebar is shown as an icon rail (68px)', Math.round((await page.locator('aside[aria-label="Main navigation"]').boundingBox()).width) === 68);
    check('tablet 768: no bottom bar', !(await page.getByRole('navigation', { name: 'Primary' }).isVisible()));
    check('tablet 768: no sideways scroll', await noSideScroll(page));
    void side;
    await ctx.close();
  }
  for (const vp of [{ width: 1024, height: 768 }, { width: 1440, height: 900 }]) {
    const { ctx, page } = await open(browser, vp);
    const tag = `desktop ${vp.width}`;
    await page.goto('/overview'); await page.getByRole('heading', { level: 1 }).waitFor();
    const aside = page.locator('aside[aria-label="Main navigation"]');
    await page.evaluate(() => localStorage.removeItem('flowqr:sidebar')); await page.reload(); await page.getByRole('heading', { level: 1 }).waitFor();
    const w = Math.round((await aside.boundingBox()).width);
    check(`${tag}: one sidebar, ${vp.width >= 1100 ? 'expanded (about 232px)' : 'a rail (68px) by default'}`, vp.width >= 1100 ? w >= 220 && w <= 240 : w === 68, `${w}px`);
    check(`${tag}: no bottom bar`, !(await page.getByRole('navigation', { name: 'Primary' }).isVisible()));
    check(`${tag}: only one primary navigation (no second pill nav)`, (await page.getByRole('navigation', { name: 'Main', exact: true }).count()) === 0);
    if (vp.width >= 1100) {
      const names = await aside.locator('nav[aria-label=Pages] > div > ul > li > div > a').allInnerTexts();
      check(`${tag}: sidebar lists Home, Marketing Studio, GBP, Locations, Reviews, Growth, AI Assistant, Tasks & Approvals, Activity, Settings, Billing`,
        JSON.stringify(names.map((t) => t.trim())) === JSON.stringify(['Home', 'Marketing Studio', 'GBP', 'Locations', 'Reviews', 'Growth', 'AI Assistant', 'Tasks & Approvals', 'Activity', 'Settings', 'Billing']), JSON.stringify(names));
      check(`${tag}: the current page is marked`, (await aside.locator('a[aria-current=page]').first().innerText()).trim() === 'Home');
      await aside.getByRole('button', { name: 'Collapse sidebar' }).click(); await page.waitForTimeout(400);
      check(`${tag}: collapses to a 68px rail`, Math.round((await aside.boundingBox()).width) === 68);
      await page.reload(); await page.getByRole('heading', { level: 1 }).waitFor();
      check(`${tag}: the collapsed state is remembered`, Math.round((await aside.boundingBox()).width) === 68);
      await aside.getByRole('button', { name: 'Expand sidebar' }).click();
    }
    check(`${tag}: no sideways scroll`, await noSideScroll(page));
    await ctx.close();
  }

  // ------------------------------------------------------------------ redirects and hidden placeholders
  {
    const { ctx, page } = await open(browser, { width: 1280, height: 800 });
    for (const [from, to] of [['/gbp/rank', '/seo/rankings'], ['/analytics/performance', '/seo/performance'], ['/analytics/reports', '/growth/reports'], ['/ai/voice', '/settings/ai/voice'], ['/gbp', '/overview'], ['/overview/performance', '/seo/performance'], ['/dashboard', '/overview'], ['/reviews', '/gbp/reviews']]) {
      await page.goto(from); await page.waitForURL('**' + to + '**', { timeout: 15000 }).catch(() => {});
      check(`redirect ${from} -> ${to}`, new URL(page.url()).pathname.startsWith(to));
    }
    await page.goto('/gbp/inbox'); await page.waitForTimeout(1500);
    check('hidden WhatsApp page still opens by URL', (await page.getByRole('heading', { level: 1 }).count()) > 0);
    const text = (await page.locator('aside[aria-label="Main navigation"]').innerText()) + (await page.locator('header').first().innerText());
    check('placeholder pages are not advertised in navigation', !/WhatsApp|Leads|Appointments|Brand kit|Social publishing/i.test(text));
    await ctx.close();
  }

  // ------------------------------------------------------------------ dark mode and reduced motion
  {
    const { ctx, page, errors } = await open(browser, { width: 390, height: 844 }, { colorScheme: 'dark', reducedMotion: 'reduce' });
    await page.goto('/overview'); await page.getByRole('heading', { level: 1 }).waitFor();
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('button', { name: 'More' }).click();
    const dlg = page.getByRole('dialog', { name: 'More' }); await dlg.waitFor();
    check('dark + reduced motion: More sheet opens and shows its groups', await dlg.getByRole('heading', { name: 'Account' }).isVisible());
    const dur = await page.evaluate(() => getComputedStyle(document.querySelector('aside, nav')).transitionDuration);
    check('dark + reduced motion: no console errors', errors.length === 0, errors.slice(0, 2).join(' | '));
    void dur;
    await ctx.close();
  }

  await browser.close();
  console.log(failures ? `\n${failures} check(s) FAILED` : '\nAll checks passed');
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
