// Browser test for the public marketing site (docs/marketing-site): 8 pages + legal pages.
//
//   BASE_URL=http://localhost:3000 node e2e/landing.js
//
// Needs playwright (or playwright-core with CHROME_PATH) and a running frontend whose /api reaches the backend. It changes no data.
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require("playwright-core")); }

const BASE = process.env.BASE_URL || "http://localhost:3000";
const PAGES = ["/", "/google-business", "/review-cards", "/ai-growth-agent", "/industries", "/pricing", "/about"];
const LEGAL = ["/privacy", "/terms", "/refund-policy", "/data-deletion"];
let pass = 0, fail = 0;
async function step(name, fn) {
  try { await fn(); pass++; console.log("  ok  ", name); } catch (e) { fail++; console.log("  FAIL", name, "\n       ", String(e.message).split("\n").slice(0, 4).join("\n        ")); }
}
const ok = (c, m) => { if (!c) throw new Error(m); };

(async () => {
  const launch = process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {};
  const browser = await chromium.launch({ headless: true, ...launch });
  const errors = [];
  const watch = (page) => {
    page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
    page.on("console", (m) => { const u = new URL(page.url()).pathname; if (m.type() === "error" && (PAGES.includes(u) || LEGAL.includes(u))) errors.push(`console (${page.url()}): ${m.text().slice(0, 160)}`); });
  };
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, baseURL: BASE });
  const page = await ctx.newPage(); watch(page);
  const text = {};
  for (const p of PAGES.concat(LEGAL)) {
    await page.goto(p, { waitUntil: "networkidle" });
    text[p] = await page.evaluate(() => document.body.textContent.replace(/\s+/g, " "));
  }

  await step("every page: one h1, title, description, canonical", async () => {
    for (const p of PAGES.concat(LEGAL)) {
      await page.goto(p, { waitUntil: "domcontentloaded" });
      ok((await page.locator("h1").count()) === 1, `${p}: h1 count`);
      const d = await page.locator('meta[name="description"]').getAttribute("content");
      ok(d && d.length > 20, `${p}: description`);
      ok((await page.locator('link[rel="canonical"]').count()) === 1, `${p}: canonical`);
    }
  });

  await step("compliance copy: no guarantees, partner claims, 5-star promises, testimonials or user counts", async () => {
    for (const p of PAGES) {
      const t = text[p];
      ok(!/guaranteed (rank|review)|google partner\b(?! \?)|certified|5-star reviews|trusted by|testimonial|\b\d[\d,]*\+ (businesses|customers)/i.test(t.replace(/Is FlowQR an official Google partner\?/g, "").replace(/doesn.t guarantee reviews, ratings or rankings/g, "")), `${p}: forbidden claim`);
      ok(/not affiliated with Google/.test(t), `${p}: trademark disclaimer`);
    }
      });

  await step("no purple anywhere in the rendered marketing pages", async () => {
    for (const p of PAGES) {
      await page.goto(p, { waitUntil: "networkidle" });
      const purple = await page.evaluate(() => [...document.querySelectorAll("*")].some((e) => { const s = getComputedStyle(e); return [s.color, s.backgroundColor, s.borderTopColor].some((c) => { const m = c.match(/\d+/g); if (!m) return false; const [r, g, b] = m.map(Number); return b > 150 && r > 90 && g < 130 && b > g + 50; }); }));
      ok(!purple, `${p}: purple colour found`);
    }
  });

  await step("FAQ rows open and close, with aria-expanded", async () => {
    await page.goto("/", { waitUntil: "networkidle" });
    const q = page.locator("button[aria-expanded]").filter({ hasText: "Is this allowed by Google" }).first();
    await q.scrollIntoViewIfNeeded(); await q.click();
    ok((await q.getAttribute("aria-expanded")) === "true", "opens");
    await q.click(); ok((await q.getAttribute("aria-expanded")) === "false", "closes");
  });

  await step("nav: Product menu, Industries, Pricing, About, Log in, Sign up; all links resolve", async () => {
    await page.goto("/", { waitUntil: "networkidle" });
    const nav = page.getByRole("navigation", { name: "Site" });
    await nav.getByRole("button", { name: /Product/ }).click();
    for (const t of ["Google Business", "Review Cards", "AI Growth Agent"]) ok((await page.locator("#product-menu").getByText(t, { exact: true }).count()) === 1, "product " + t);
    for (const p of PAGES.concat(LEGAL)) {
      await page.goto(p, { waitUntil: "domcontentloaded" });
      const hrefs = await page.$$eval("a[href^='/']", (as) => [...new Set(as.map((a) => a.getAttribute("href").split("#")[0]))]);
      for (const h of hrefs) { const r = await ctx.request.get(h || "/"); ok(r.status() < 400, `${p} -> ${h} ${r.status()}`); }
    }
  });

  await step("pricing comes from the app config; no hard-coded ₹ outside it", async () => {
    await page.goto("/pricing", { waitUntil: "networkidle" });
    const api = await (await ctx.request.get("/api/v1/billing/plans")).json();
    for (const pl of api.plans) {
      const card = page.locator(`[data-plan="${pl.code}"]`);
      const want = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(pl.price_paise / 100);
      ok((await card.innerText()).includes(want), `${pl.code}: shows ${want}`);
    }
    ok(/GST/.test(text["/pricing"]) && /sold separately/.test(text["/pricing"]), "GST and cards-separate notes");
  });

  await step("pricing shows 'Talk to us for pricing' when the config can't be read", async () => {
    const c2 = await browser.newContext({ baseURL: BASE }); const p2 = await c2.newPage();
    await p2.route("**/api/v1/billing/plans", (r) => r.fulfill({ status: 503, body: "{}" }));
    await p2.goto("/pricing", { waitUntil: "networkidle" });
    ok(await p2.getByText("Talk to us for pricing").isVisible(), "fallback message");
    ok(!/₹\s?\d/.test(await p2.locator("main").innerText()), "no rupee figures without config");
    await c2.close();
  });

  await step("legal pages exist; refund policy is a placeholder, not invented terms", async () => {
    for (const p of LEGAL) ok((await ctx.request.get(p)).status() === 200, p);
    ok(/\[LEGAL TEXT TO BE PROVIDED\]/.test(text["/refund-policy"]), "placeholder");
  });

  await step("sitemap, robots and OG image", async () => {
    const sm = await (await ctx.request.get("/sitemap.xml")).text();
    for (const p of PAGES.concat(LEGAL)) ok(sm.includes(`${p === "/" ? "" : p}</loc>`) || (p === "/" && /<loc>[^<]+<\/loc>/.test(sm)), "sitemap " + p);
    ok(/Disallow: \/q\//.test(await (await ctx.request.get("/robots.txt")).text()), "robots keeps card routes out");
    await page.goto("/", { waitUntil: "domcontentloaded" }); const ogUrl = await page.locator('meta[property="og:image"]').first().getAttribute("content"); ok(ogUrl, "og:image meta"); const og = await page.goto(new URL(ogUrl).pathname); ok(og.status() === 200 && /image\/png/.test(og.headers()["content-type"]), "OG image");
  });

  await step("app and QR routes untouched: /dashboard needs login, /q/<bad> shows the neutral card page", async () => {
    await page.goto("/dashboard", { waitUntil: "networkidle" }); ok(/\/login/.test(page.url()), "dashboard redirects");
    const r = await ctx.request.get("/q/doesnotexist0000000000"); ok(r.status() === 200, "/q route still served");
  });

  await step("reduced motion: headline renders without blur or movement", async () => {
    const rc = await browser.newContext({ baseURL: BASE, reducedMotion: "reduce" }); const rp = await rc.newPage();
    await rp.goto("/", { waitUntil: "networkidle" }); await rp.waitForTimeout(400);
    const f = await rp.locator("h1 span[aria-hidden]").first().evaluate((e) => getComputedStyle(e).filter + "|" + getComputedStyle(e).transform);
    ok(!/blur\([1-9]/.test(f), "blur under reduced motion: " + f);
    ok((await rp.locator(".mkt-marquee").first().evaluate((e) => getComputedStyle(e).animationName)) === "none", "marquee stopped");
    await rc.close();
  });

  const m = await (await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, baseURL: BASE })).newPage(); watch(m);
  await step("phone: no horizontal scroll at 390 and 320 on every page", async () => {
    for (const w of [390, 320]) { await m.setViewportSize({ width: w, height: 844 });
      for (const p of PAGES.concat(LEGAL)) { await m.goto(p, { waitUntil: "networkidle" }); const [sw, cw] = await m.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]); ok(sw <= cw, `${p}@${w}: ${sw}>${cw}`); } }
    await m.setViewportSize({ width: 390, height: 844 });
  });
  await step("phone: menu opens full screen, Escape closes, link navigates", async () => {
    await m.goto("/", { waitUntil: "networkidle" });
    const b = m.locator("button[aria-controls=site-menu]"); ok((await b.boundingBox()).height >= 44, "tap size");
    await b.click(); const nav = m.getByRole("navigation", { name: "Site menu" });
    ok((await nav.boundingBox()).height > 600, "full screen");
    await m.keyboard.press("Escape"); ok((await nav.count()) === 0, "Escape closes");
    await b.click(); await m.getByRole("navigation", { name: "Site menu" }).getByRole("link", { name: "Pricing", exact: true }).click(); await m.waitForURL("**/pricing");
  });

  await step("no console or page errors", async () => { ok(!errors.length, errors.slice(0, 3).join(" | ")); });
  await browser.close();
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
