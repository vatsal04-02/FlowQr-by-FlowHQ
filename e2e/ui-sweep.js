// Visits every FlowQR route at desktop, tablet and mobile sizes against a seeded DEMO stack. For each page it records
// horizontal overflow, console/page errors and failed requests, and saves a screenshot for docs/ART_DIRECTION_AND_UI_AUDIT.md.
//
//   BASE_URL=http://localhost:3100 node e2e/ui-sweep.js            (set CHROME_PATH to use a system Chrome with playwright-core)
//
// Output: docs/ui-audit/<size>/<route>.jpg and docs/ui-audit/results.json. Seed first with e2e/seed_demo.py.
const fs = require("fs");
const path = require("path");
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require("playwright-core")); }

const BASE = process.env.BASE_URL || "http://localhost:3100";
const OUT = process.env.OUT_DIR || path.join(__dirname, "..", "docs", "ui-audit");
const PASSWORD = process.env.DEMO_PASSWORD || "DemoPassw0rd!x";
const SIZES = { desktop: { width: 1440, height: 900 }, tablet: { width: 820, height: 1100 }, mobile: { width: 390, height: 844 } };
const WHO = { owner: "demo-owner@example.com", admin: "demo-admin@example.com", fresh: "demo-new@example.com", onboarding: "demo-onboarding@example.com", anon: null };

async function login(ctx, who) {
  if (!WHO[who]) return null;
  const r = await ctx.request.post("/api/v1/auth/login", { data: { email: WHO[who], password: PASSWORD } });
  if (!r.ok()) throw new Error(`login ${who} failed: ${r.status()}`);
  return ctx;
}

(async () => {
  const launch = process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {};
  const browser = await chromium.launch({ headless: true, ...launch });

  // Discover real ids (a review, a card, its public token, a customer) through the API, as the owner and the admin.
  const probe = await browser.newContext({ baseURL: BASE });
  await login(probe, "owner");
  const reviews = await (await probe.request.get("/api/v1/reviews?limit=1")).json();
  const cards = await (await probe.request.get("/api/v1/cards")).json();
  const adminProbe = await browser.newContext({ baseURL: BASE });
  await login(adminProbe, "admin");
  const tenants = await (await adminProbe.request.get("/api/v1/admin/tenants?limit=5")).json();
  const demoTenant = (tenants.items || []).find((t) => t.name === "Demo Clinic");
  await probe.close(); await adminProbe.close();

  const ROUTES = [
    ["anon", "/", "home"], ["anon", "/pricing", "pricing"], ["anon", "/login", "login"], ["anon", "/register", "register"], ["anon", "/forgot-password", "forgot-password"],
    ["anon", "/reset-password?token=demo", "reset-password"], ["anon", "/verify-email?token=demo", "verify-email"], ["anon", "/accept-invite?token=demo", "accept-invite"],
    ["anon", `/c/${cards[0]?.public_token}`, "card-public"], ["anon", "/c/not-a-real-token", "card-public-not-found"],
    ["onboarding", "/onboarding", "onboarding"],
    ["fresh", "/dashboard", "dashboard-new-business"], ["fresh", "/cards", "cards-empty"], ["fresh", "/reviews", "reviews-empty"],
    ["owner", "/dashboard", "dashboard"], ["owner", "/reviews", "reviews"], ["owner", `/reviews/${reviews.items?.[0]?.id}`, "review-detail"],
    ["owner", "/cards", "cards"], ["owner", `/cards/${cards[0]?.id}`, "card-detail"], ["owner", "/cards/analytics", "card-analytics"], ["owner", "/analytics", "analytics"],
    ["owner", "/locations", "locations"], ["owner", "/google", "google"], ["owner", "/profile", "google-profile"],
    ["owner", "/subscription", "subscription"], ["owner", "/payments", "payments"], ["owner", "/staff", "staff"], ["owner", "/settings", "settings"],
    ["admin", "/admin", "admin"], ["admin", "/admin/customers", "admin-customers"], ["admin", `/admin/customers/${demoTenant?.id}`, "admin-customer-detail"],
    ["admin", "/admin/cards", "admin-cards"], ["admin", "/admin/billing", "admin-billing"], ["admin", "/admin/audit", "admin-audit"],
  ];

  const results = [];
  for (const [sizeName, vp] of Object.entries(SIZES)) {
    fs.mkdirSync(path.join(OUT, sizeName), { recursive: true });
    for (const who of Object.keys(WHO)) {
      const list = ROUTES.filter((r) => r[0] === who);
      if (!list.length) continue;
      const ctx = await browser.newContext({ viewport: vp, baseURL: BASE, reducedMotion: "reduce" });
      await login(ctx, who);
      const page = await ctx.newPage();
      let problems = [];
      page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
      page.on("console", (m) => { if (m.type() === "error" && !/favicon|status of (401|404)/.test(m.text())) problems.push("console: " + m.text().slice(0, 160)); });
      page.on("requestfailed", (r) => problems.push("requestfailed: " + r.url().slice(0, 100)));
      for (const [, route, name] of list) {
        problems = [];
        try {
          await page.goto(route, { waitUntil: "networkidle", timeout: 60000 });
          await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
          await page.waitForTimeout(800);
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
          // Controls too small to tap on touch screens (44px) or without any accessible name.
          const audit = await page.evaluate((mobile) => {
            const bad = { unnamed: [], small: [] };
            document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea").forEach((el) => {
              const r = el.getBoundingClientRect(); if (!r.width || !r.height) return;
              const name = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("title") || el.getAttribute("placeholder") || "").trim() || (el.id && document.querySelector(`label[for="${el.id}"]`)) || el.closest("label");
              if (!name) bad.unnamed.push(el.tagName.toLowerCase() + (el.className ? "." + String(el.className).split(" ")[0] : ""));
              if (mobile && (r.height < 32 || r.width < 32) && el.tagName !== "A") bad.small.push(el.tagName.toLowerCase() + ` ${Math.round(r.width)}x${Math.round(r.height)}`);
            });
            return bad;
          }, sizeName === "mobile");
          await page.screenshot({ path: path.join(OUT, sizeName, `${name}.jpg`), type: "jpeg", quality: 60, fullPage: sizeName === "desktop" ? false : false });
          results.push({ route, name, size: sizeName, who, overflow: Math.max(0, overflow), unnamed: audit.unnamed.slice(0, 5), small: audit.small.slice(0, 5), problems: [...new Set(problems)] });
          console.log(`${overflow > 1 ? "OVERFLOW" : "ok      "} ${sizeName.padEnd(7)} ${name}${problems.length ? "  !! " + problems[0] : ""}`);
        } catch (e) { results.push({ route, name, size: sizeName, who, error: e.message.split("\n")[0] }); console.log("FAIL", sizeName, name, e.message.split("\n")[0]); }
      }
      await ctx.close();
    }
  }
  fs.writeFileSync(path.join(OUT, "results.json"), JSON.stringify(results, null, 1));
  const bad = results.filter((r) => r.error || r.overflow > 1 || r.problems?.length);
  console.log(`\n${results.length} captures, ${bad.length} with issues`);
  await browser.close();
})();
