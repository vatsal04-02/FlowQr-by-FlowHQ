// Captures the product screenshots used on the marketing site (frontend/public/product/*.jpg) from a running DEMO stack.
//
//   BASE_URL=http://localhost:3100 node e2e/capture-product-shots.js
//
// Requires playwright (or playwright-core with CHROME_PATH) and a stack seeded with e2e/seed_demo.py.
// Never point this at a real customer's data: the images are published on the public landing page.
const fs = require("fs");
const path = require("path");
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require("playwright-core")); }

const BASE = process.env.BASE_URL || "http://localhost:3100";
const OUT = process.env.OUT_DIR || path.join(__dirname, "..", "frontend", "public", "product");
const EMAIL = process.env.DEMO_EMAIL || "demo-owner@example.com";
const PASSWORD = process.env.DEMO_PASSWORD || "DemoPassw0rd!x";
// Only the pictures the landing page actually uses (see frontend/src/app/page.tsx).
const SHOTS = [["reviews", "/reviews"], ["analytics", "/analytics"], ["locations", "/locations"]];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const launch = process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {};
  const browser = await chromium.launch({ headless: true, ...launch });
  // 1280x800 at 1.5x = 1920x1200 (16:10), matching the width/height the <Shot> component reserves.
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1.5, baseURL: BASE, reducedMotion: "reduce" });
  const login = await ctx.request.post("/api/v1/auth/login", { data: { email: EMAIL, password: PASSWORD } });
  if (!login.ok()) throw new Error(`demo login failed (${login.status()}). Seed the demo stack first.`);
  const page = await ctx.newPage();
  await page.addStyleTag({ content: "nextjs-portal{display:none!important}" }).catch(() => {});
  for (const [name, route] of SHOTS) {
    await page.goto(route, { waitUntil: "networkidle" });
    await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(OUT, `${name}.jpg`), type: "jpeg", quality: 82 });
    console.log("captured", name);
  }
  await browser.close();
})();
