// Visits pages on the LOCAL production build and lists what the report-only Content-Security-Policy WOULD have blocked. Nothing is blocked; this is only a survey.
const { chromium } = require('playwright-core');
const BASE = 'http://127.0.0.1:3155';
const app = ['/overview', '/gbp/reviews', '/gbp/posts', '/gbp/campaigns', '/gbp/cards', '/seo', '/growth', '/ai/today', '/settings/billing', '/settings/team', '/settings/connections/google', '/whatsapp/connect', '/whatsapp/inbox', '/reputation/assistant', '/onboarding'];
const pub = ['/login', '/register', '/pricing', '/', '/privacy', '/r/bench0001'];
(async () => {
  const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
  const seen = new Map(); let pages = 0, hdr = null;
  const visit = async (ctx, u) => {
    const p = await ctx.newPage();
    await p.addInitScript(() => { window.__v = []; document.addEventListener('securitypolicyviolation', e => window.__v.push([e.violatedDirective, e.blockedURI, e.disposition])); });
    const r = await p.goto(u, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => null);
    if (r && !hdr) hdr = { enforced: r.headers()['content-security-policy'], report: !!r.headers()['content-security-policy-report-only'] };
    await p.waitForTimeout(1200);
    for (const [d, uri, disp] of await p.evaluate(() => window.__v)) { const k = `${d} <- ${String(uri).replace(/\?.*/, '').slice(0, 90)} [${disp}]`; const e = seen.get(k) || { n: 0, on: new Set() }; e.n++; e.on.add(u); seen.set(k, e); }
    pages++; await p.close();
  };
  const authed = await b.newContext({ baseURL: BASE, viewport: { width: 1280, height: 800 } });
  await authed.request.post('/api/v1/auth/login', { data: { email: 'bench0@example.com', password: 'Str0ngPassw0rd!bench' } });
  for (const u of app) await visit(authed, u);
  const anon = await b.newContext({ baseURL: BASE, viewport: { width: 390, height: 800 } });
  for (const u of pub) await visit(anon, u);
  await b.close();
  console.log('pages visited:', pages, '| enforced CSP header present:', !!hdr.enforced, '| report-only header present:', hdr.report);
  console.log(seen.size ? 'WOULD BE BLOCKED by the full policy:' : 'nothing would be blocked on any visited page');
  for (const [k, v] of seen) console.log(' ', k, 'x' + v.n, 'on', [...v.on].slice(0, 4).join(','));
})();
