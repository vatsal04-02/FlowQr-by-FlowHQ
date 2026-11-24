// Frontend + mobile measurement against a LOCAL production build (next start) and a LOCAL API on a throwaway database. Nothing here touches production.
// Usage: BASE=http://127.0.0.1:3155 node perf.js   (PAGES=/a,/b  W=320,360  OUT=file.json)
const { chromium } = require('playwright-core'); const fs = require('fs');
const BASE = process.env.BASE || 'http://127.0.0.1:3155';
const EMAIL = process.env.EMAIL || 'bench0@example.com', PW = process.env.PW || 'Str0ngPassw0rd!bench';
const pages = (process.env.PAGES || '/login,/overview,/reviews,/posts,/marketing,/ai/today,/gbp/cards,/seo,/settings/team,/review-growth').split(',');
const widths = (process.env.W || '320,360,375,390,414,768').split(',').map(Number);
const THROTTLE = process.env.THROTTLE || 'none'; // 'none' | 'slow4g' (CPU x4 + 1.6 Mbps / 150 ms): a mid-range phone on a poor network
(async () => {
  const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
  const out = [];
  for (const w of widths) {
    const ctx = await b.newContext({ baseURL: BASE, viewport: { width: w, height: 800 }, isMobile: w < 768, hasTouch: w < 768, deviceScaleFactor: w < 768 ? 2 : 1 });
    if (!process.env.NOAUTH) { const lr = await ctx.request.post('/api/v1/auth/login', { data: { email: EMAIL, password: PW } });
    if (lr.status() !== 200) { console.log('login failed', lr.status()); process.exit(1); } }
    for (const u of pages) {
      const p = await ctx.newPage();
      const cdp = await ctx.newCDPSession(p);
      await cdp.send('Network.enable');
      if (THROTTLE === 'slow4g') {
        await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: 1.6 * 1024 * 1024 / 8, uploadThroughput: 750 * 1024 / 8 });
        await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
      }
      const reqs = new Map(); let bytes = 0;
      cdp.on('Network.requestWillBeSent', e => { if (/kaspersky/i.test(e.request.url)) return; reqs.set(e.requestId, { url: e.request.url, type: e.type }); }); // the antivirus on the test PC injects its own script into every page; it is not FlowQR's, so it is left out
      cdp.on('Network.loadingFinished', e => { const r = reqs.get(e.requestId); if (r) { bytes += e.encodedDataLength; r.bytes = e.encodedDataLength; } });
      await p.addInitScript(() => {
        window.__m = { lcp: 0, cls: 0, longTasks: 0, longMs: 0 };
        new PerformanceObserver(l => { for (const e of l.getEntries()) window.__m.lcp = e.startTime; }).observe({ type: 'largest-contentful-paint', buffered: true });
        new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__m.cls += e.value; }).observe({ type: 'layout-shift', buffered: true });
        new PerformanceObserver(l => { for (const e of l.getEntries()) { window.__m.longTasks++; window.__m.longMs += e.duration; } }).observe({ type: 'longtask', buffered: true });
      });
      const t0 = Date.now(); let status = 0;
      try { const r = await p.goto(u, { waitUntil: 'networkidle', timeout: 60000 }); status = r ? r.status() : 0; } catch (e) { status = -1; }
      const loadMs = Date.now() - t0;
      await p.waitForTimeout(700);
      const m = await p.evaluate(() => {
        const W = document.documentElement.clientWidth; let wide = 0, small = 0;
        for (const e of document.querySelectorAll('body *')) { const s = getComputedStyle(e); if (s.display === 'none' || s.visibility === 'hidden') continue; const q = e.getBoundingClientRect(); if (q.width > 0 && q.right > W + 1 && !e.closest('table,[class*=overflow-x],[class*=scroll]')) wide++; }
        for (const e of document.querySelectorAll('a,button,input,select,textarea,[role=button]')) { const s = getComputedStyle(e); if (s.display === 'none' || s.visibility === 'hidden') continue; const q = e.getBoundingClientRect(); if (q.width > 0 && (q.height < 32 || q.width < 32) && !e.closest('[aria-hidden=true]')) small++; }
        const nav = performance.getEntriesByType('navigation')[0] || {};
        return { ...window.__m, docOverflow: document.documentElement.scrollWidth > W + 1, wide, small, dcl: Math.round(nav.domContentLoadedEventEnd || 0), load: Math.round(nav.loadEventEnd || 0), ttfb: Math.round(nav.responseStart || 0), h1: document.querySelector('h1')?.textContent?.slice(0, 40) || null };
      });
      const all = [...reqs.values()]; const api = all.filter(r => r.url.includes('/api/')); const seen = {}; for (const r of api) { const k = r.url.replace(BASE, ''); seen[k] = (seen[k] || 0) + 1; }
      const dups = Object.entries(seen).filter(([, n]) => n > 1).map(([k, n]) => `${k} x${n}`);
      const js = all.filter(r => r.type === 'Script').reduce((a, r) => a + (r.bytes || 0), 0), img = all.filter(r => r.type === 'Image').reduce((a, r) => a + (r.bytes || 0), 0), font = all.filter(r => r.type === 'Font').reduce((a, r) => a + (r.bytes || 0), 0);
      out.push({ width: w, page: u, status, requests: all.length, apiCalls: api.length, dupApi: dups, // note: keys are path-only; see diag5 for full-URL duplicates
  kbTotal: Math.round(bytes / 1024), kbJs: Math.round(js / 1024), kbImg: Math.round(img / 1024), kbFont: Math.round(font / 1024), lcpMs: Math.round(m.lcp), cls: +m.cls.toFixed(3), longTasks: m.longTasks, longMs: Math.round(m.longMs), loadMs, ttfb: m.ttfb, dcl: m.dcl, docOverflow: m.docOverflow, offscreen: m.wide, smallTargets: m.small, h1: m.h1 });
      await p.close();
    }
    await ctx.close();
  }
  await b.close();
  fs.writeFileSync(process.env.OUT || 'perf-out.json', JSON.stringify(out, null, 1));
  console.log('width page status req api KB(js/img/font) LCP CLS longMs overflow wide small dupApi');
  for (const r of out) console.log(r.width, r.page, r.status, r.requests, r.apiCalls, `${r.kbTotal}(${r.kbJs}/${r.kbImg}/${r.kbFont})`, r.lcpMs, r.cls, r.longMs, r.docOverflow ? 'OVERFLOW' : '-', r.offscreen, r.smallTargets, r.dupApi.join(';'));
})();
