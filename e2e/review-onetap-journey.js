// One-tap review journey in real Chromium (Edge) with Android (Pixel 7), iPhone 13 and desktop emulation, against the live local stack.
// REAL: the page, landing (direct Google URL), sessions, approve, redirect, analytics, the browser's clipboard and new-tab behaviour.
// MOCKED: AI text only (/starter, /generate mode ai, /refine, /regenerate), because the provider free tiers are exhausted. Google itself is stubbed (no network to google.com).
// NOT covered: real Safari/WebKit engines (only Chromium with an iPhone profile) and real handsets.
const { chromium, request, devices } = require("playwright-core");
const fs = require("fs");
const BASE = "http://localhost:3000";
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const GOOGLE = "https://g.page/r/ONETAP/review";
let fails = 0;
const ok = (name, cond, extra = "") => { if (!cond) fails++; console.log(`${cond ? "PASS" : "FAIL"}  ${name}${extra ? "  -> " + extra : ""}`); };
fs.mkdirSync("shots4", { recursive: true });
const STARTER = { en: "Sharing my feedback on Sunrise Physio, a physiotherapy clinic in Lucknow.", hi: "Sunrise Physio, लखनऊ के बारे में अपनी राय साझा कर रहा हूँ।" };
const REFINED = { 1: "I wasn't happy with the staff.", 3: "The staff were okay.", 5: "I appreciated the way the staff dealt with me, and things were explained in a way that was easy to follow." };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const email = `zz-ot-${Date.now().toString(36)}@example.com`;
  const browser = await chromium.launch({ executablePath: EDGE, headless: true });
  const owner = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const reg = await (await owner.request.post(`${BASE}/api/v1/auth/register`, { data: { email, password: "Str0ngPassw0rd!", full_name: "One Tap" } })).json();
  const H = { "X-CSRF-Token": reg.csrf_token }, R = owner.request;
  await R.post(`${BASE}/api/v1/tenants`, { headers: H, data: { name: "Sunrise Physio", category: "Physiotherapy clinic" } });
  const loc = await (await R.post(`${BASE}/api/v1/locations`, { headers: H, data: { name: "Gomti Nagar clinic", city: "Lucknow", review_url: GOOGLE } })).json();
  await R.post(`${BASE}/api/v1/tenant/complete-onboarding`, { headers: H });
  const mkCamp = async (name) => (await (await R.post(`${BASE}/api/v1/review-growth/campaigns`, { headers: H, data: { name, location_id: loc.id, customization: { brand_color: "#0A7D6B", background: "gradient" } } })).json());
  await R.post(`${BASE}/api/v1/review-growth/context`, { headers: H, data: {} }).catch(() => {});

  /** A fresh browser context per scenario (own clipboard, storage, tabs). */
  async function open(camp, device, { clipboard = "grant", aiUp = true, starterDelay = 0, refineDelay = 0, submission = null, submitReply = null } = {}) {
    const ctx = await browser.newContext({ ...device, ...(clipboard === "grant" ? { permissions: ["clipboard-read", "clipboard-write"] } : {}) });
    if (clipboard === "grant") await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: BASE });
    await ctx.route(/^https:\/\/(g\.page|search\.google\.com|www\.google\.com)\//, (r) => r.fulfill({ status: 200, contentType: "text/html", body: "<html><title>Google (stub)</title><body>Google review box</body></html>" }));
    const p = await ctx.newPage();
    p.ctx = ctx; p.errs = []; p.reqs = []; p.opened = [];
    ctx.on("page", (np) => p.opened.push(np));
    p.on("pageerror", (e) => p.errs.push(e.message.slice(0, 140)));
    p.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) p.errs.push(m.text().slice(0, 140)); });
    p.on("request", (r) => { if (r.url().includes("/api/v1/public/reviews/") && r.method() !== "GET") { let b = {}; try { b = JSON.parse(r.postData() || "{}"); } catch {} p.reqs.push({ path: r.url().split("/").pop(), body: b }); } });
    let n = 0;
    await p.route(/\/api\/v1\/public\/reviews\/[^/?]+\/starter/, async (route) => {
      await sleep(starterDelay);
      const lang = new URL(route.request().url()).searchParams.get("language") || "en";
      if (!aiUp) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ draft: null, ai_status: "unavailable", language: lang, source: null }) });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ draft: STARTER[lang], ai_status: "ok", language: lang, source: "ai_suggestion" }) });
    });
    await p.route(/\/api\/v1\/public\/reviews\/[^/]+\/generate$/, async (route) => {
      const b = JSON.parse(route.request().postData() || "{}");
      if (b.mode !== "ai") return route.continue();
      await sleep(refineDelay);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session_id: `mockM${++n}`.padEnd(22, "x"), draft: REFINED[b.rating] || REFINED[5], ai_status: "ok", retryable: false, generation_count: 1, remaining_drafts: 4, follow_up: null }) });
    });
    await p.route(/\/api\/v1\/public\/reviews\/[^/]+\/refine$/, async (route) => {
      const b = JSON.parse(route.request().postData() || "{}");
      await sleep(refineDelay);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ session_id: b.session_id, draft: (REFINED[b.rating] || REFINED[5]) + (b.text ? " (built from the customer's words)" : ""), ai_status: "ok", retryable: false, generation_count: 1, remaining_drafts: 4, follow_up: null }) });
    });
    p.submits = [];
    if (submission) { // MOCKED: pretend the server says an approved direct provider exists (it does not, today) to exercise the page's direct-submit branch
      await p.route(/\/api\/v1\/public\/reviews\/[^/?]+$/, async (route) => {
        if (route.request().method() !== "GET") return route.continue();
        const res = await route.fetch(); const j = await res.json(); j.submission = { mode: submission };
        await route.fulfill({ response: res, json: j });
      });
      await p.route(/\/api\/v1\/public\/reviews\/[^/]+\/submit$/, async (route) => {
        p.submits.push(JSON.parse(route.request().postData() || "{}"));
        const r = submitReply || { status: 200, json: { status: "published", published: true, session_id: "mockSubmitSession0000xx" } };
        await route.fulfill({ status: r.status, contentType: "application/json", body: JSON.stringify(r.json) });
      });
    }
    await p.goto(`${BASE}/r/${camp.public_id}`);
    return p;
  }
  const stars = (p) => p.getByRole("radiogroup", { name: /rate your visit|कितने स्टार/ }).getByRole("radio");
  const chips = (p, hi) => p.getByRole("group", { name: hi ? /क्या खास/ : /What stood out/ }).getByRole("button");
  const box = (p) => p.locator("#review");
  const cta = (p) => p.getByTestId("copy-continue");
  const nextTab = async (p, ms = 8000) => { const t0 = Date.now(); while (!p.opened.length && Date.now() - t0 < ms) await sleep(100); const np = p.opened[0]; if (np) await np.waitForLoadState("domcontentloaded").catch(() => {}); return np; };
  const finish = async (p) => { await sleep(900); await p.ctx.close(); }; // let the tap's tracking request (sent with keepalive) land before the scenario ends

  const DEVICES = { "Android (Pixel 7)": devices["Pixel 7"], "iPhone 13": devices["iPhone 13"], "iPhone SE (small)": devices["iPhone SE"], "Desktop": { viewport: { width: 1360, height: 900 }, userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0" } };
  for (const [dname, dev] of Object.entries(DEVICES)) {
    const camp = await mkCamp(`Journey ${dname}`);
    const tag = `[${dname}]`;
    const mobile = dname !== "Desktop";

    // ---------- A. automatic starter, skeleton, no Generate button, no required input ----------
    const p = await open(camp, dev, { starterDelay: 1500, refineDelay: 700 });
    await p.getByRole("heading", { name: "Share your experience" }).waitFor();
    ok(`${tag} skeleton shown while the starter is prepared`, (await box(p).getAttribute("aria-busy")) === "true" && (await p.locator(".fq-skeleton").count()) >= 3);
    if (dname === "Android (Pixel 7)") await p.screenshot({ path: "shots4/01-android-loading.png", fullPage: false, animations: "disabled" });
    await p.waitForFunction(() => document.querySelector("#review")?.value.startsWith("Sharing my feedback"), null, { timeout: 8000 });
    ok(`${tag} starter appears inside the review box with no button pressed`, (await box(p).inputValue()) === STARTER.en && p.reqs.length === 0);
    ok(`${tag} clearly labelled as an AI suggestion`, (await p.getByTestId("origin-badge").innerText()).includes("AI suggestion"));
    ok(`${tag} no Generate / keyword step exists`, (await p.getByRole("button", { name: /Generate my review|I'll write myself/ }).count()) === 0);
    ok(`${tag} the starter says nothing about the visit`, !/visit|loved|great|excellent|recommend/i.test(await box(p).inputValue()));
    ok(`${tag} review text is >=16px (no iOS zoom)`, (await box(p).evaluate((e) => parseFloat(getComputedStyle(e).fontSize))) >= 16);
    ok(`${tag} no horizontal overflow`, await p.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    const bb = await cta(p).boundingBox(), vh = p.viewportSize().height;
    ok(`${tag} the one-tap button is visible on first screen`, bb && bb.y + bb.height <= vh + 1, `y=${Math.round(bb.y)} h=${Math.round(bb.height)} viewport=${vh}`);
    ok(`${tag} button is a real link to the DIRECT Google write-a-review URL`, (await cta(p).evaluate((a) => a.tagName)) === "A" && (await cta(p).getAttribute("href")) === GOOGLE && (await cta(p).getAttribute("target")) === "_blank" && /noopener/.test(await cta(p).getAttribute("rel")));
    ok(`${tag} instruction under the button`, await p.getByText(/Your review will be copied. Paste it into Google.s review box./).isVisible());
    ok(`${tag} a visible Copy review fallback exists`, await p.getByTestId("copy-only").isVisible());
    const barH = await p.evaluate(() => { const a = document.querySelector("[data-testid=copy-continue]"); const bar = a.parentElement; return Math.round(bar.getBoundingClientRect().height); });
    ok(`${tag} the sticky bar is compact (does not hide the page)`, barH <= (mobile ? 135 : 150), `bar height ${barH}px of ${vh}px`);
    const barBottom = await p.evaluate(() => Math.round(document.querySelector("[data-testid=copy-continue]").parentElement.getBoundingClientRect().bottom));
    ok(`${tag} the whole bar (button + hint) is inside the screen`, barBottom <= vh + 1, `bar bottom ${barBottom} of ${vh}`);
    ok(`${tag} the language toggle stays inside the screen`, await p.evaluate(() => { const r = document.querySelector("[role=radiogroup]").getBoundingClientRect(); return r.right <= window.innerWidth && r.left >= 0; }));
    const starTop = await stars(p).nth(2).boundingBox();
    const covered = await p.evaluate(([x, y]) => { const el = document.elementFromPoint(x, y); return !!el && !!el.closest("[role=radio]"); }, [starTop.x + starTop.width / 2, starTop.y + starTop.height / 2]);
    ok(`${tag} stars are visible and tappable on the first screen (not covered by the bar)`, covered && starTop.y + starTop.height < vh - barH, `star bottom ${Math.round(starTop.y + starTop.height)}, bar top ${vh - barH}`);
    const bx = await box(p).boundingBox();
    ok(`${tag} the suggested review starts on the first screen`, bx.y < vh - barH, `review box top ${Math.round(bx.y)} of ${vh - barH} usable`);
    if (dname === "Android (Pixel 7)") await p.screenshot({ path: "shots4/02-android-starter.png", fullPage: false, animations: "disabled" });

    // ---------- B. stars + chips refine the draft automatically ----------
    await chips(p, false).nth(0).click();
    ok(`${tag} chip before stars asks for stars, makes no AI request`, (await p.getByRole("alert").filter({ hasText: "Choose your stars" }).isVisible()) && p.reqs.length === 0);
    await stars(p).nth(4).click();
    await p.getByText("Tailoring your review…").first().waitFor({ timeout: 3000 });
    await p.waitForFunction(() => document.querySelector("#review")?.value.startsWith("I appreciated"), null, { timeout: 8000 });
    const g1 = p.reqs.find((r) => r.path === "generate");
    ok(`${tag} stars+chip refined the box automatically (first call creates the session)`, g1 && g1.body.rating === 5 && g1.body.suggestions.length === 1 && g1.body.text === "" && g1.body.mode === "ai", JSON.stringify(g1?.body));
    ok(`${tag} AI-written starter text is never sent back as the customer's words`, g1.body.text === "");
    ok(`${tag} label now says it was written from their answers`, (await p.getByTestId("origin-badge").innerText()).includes("Written from your answers"));
    await chips(p, false).nth(1).click();
    await p.waitForFunction(() => document.querySelector("#review")?.value.startsWith("I appreciated"), null, { timeout: 5000 });
    await sleep(1500);
    const rf = p.reqs.find((r) => r.path === "refine");
    ok(`${tag} a further change refines the SAME session (no new session)`, rf && /^mockM1/.test(rf.body.session_id) && rf.body.suggestions.length === 2 && p.reqs.filter((r) => r.path === "generate").length === 1, JSON.stringify(rf?.body));

    // ---------- C. edits are never overwritten without permission ----------
    await box(p).fill("I came for my knee and the receptionist was very kind to me.");
    ok(`${tag} label switches to the customer's own review once they edit`, (await p.getByTestId("origin-badge").innerText()).includes("edited by you"));
    await chips(p, false).nth(2).click();
    await p.getByRole("alertdialog").waitFor({ timeout: 4000 });
    ok(`${tag} changing topics after an edit ASKS first and keeps their text meanwhile`, (await box(p).inputValue()).startsWith("I came for my knee"));
    await p.getByRole("button", { name: "Keep my text" }).click();
    ok(`${tag} "Keep my text" keeps it`, (await box(p).inputValue()).startsWith("I came for my knee") && (await p.getByRole("alertdialog").count()) === 0);
    const refinesBefore = p.reqs.filter((r) => r.path === "refine").length;
    await chips(p, false).nth(3).click();
    await p.getByRole("alertdialog").waitFor({ timeout: 4000 });
    await p.getByRole("button", { name: "Update my review" }).click();
    await p.waitForFunction(() => document.querySelector("#review")?.value.includes("built from the customer's words"), null, { timeout: 8000 });
    const lastRef = p.reqs.filter((r) => r.path === "refine").pop();
    ok(`${tag} on permission the rewrite is built from the customer's OWN words`, p.reqs.filter((r) => r.path === "refine").length === refinesBefore + 1 && lastRef.body.text.startsWith("I came for my knee"), lastRef.body.text.slice(0, 40));
    await p.getByRole("button", { name: "Undo" }).click();
    ok(`${tag} Undo brings their text back`, (await box(p).inputValue()).startsWith("I came for my knee"));
    if (dname === "Android (Pixel 7)") await p.screenshot({ path: "shots4/03-android-edited-ask.png", fullPage: false, animations: "disabled" });
    ok(`${tag} no console errors so far`, p.errs.length === 0, p.errs.join(" ; "));
    await finish(p);

    // ---------- D. typing while a rewrite is in flight is never overwritten ----------
    const q = await open(camp, dev, { refineDelay: 1800 });
    await box(q).waitFor(); await q.waitForFunction(() => document.querySelector("#review")?.value.startsWith("Sharing"));
    await stars(q).nth(2).click(); await chips(q, false).nth(0).click();
    await q.getByText("Tailoring your review…").first().waitFor({ timeout: 4000 });
    await box(q).evaluate((e) => { e.removeAttribute("readonly"); });
    await sleep(2800);
    const kept = await box(q).inputValue();
    ok(`${tag} a draft that arrives is used when the box was untouched`, kept.startsWith("The staff were okay."), kept);
    await finish(q);

    // ---------- E. one tap: copy + open the direct Google link, review kept ----------
    const e = await open(camp, dev);
    await e.waitForFunction(() => document.querySelector("#review")?.value.startsWith("Sharing"));
    await stars(e).nth(4).click(); await chips(e, false).nth(0).click();
    await e.waitForFunction(() => document.querySelector("#review")?.value.startsWith("I appreciated"), null, { timeout: 8000 });
    await box(e).fill("I appreciated the way the staff dealt with me. Edited by me before posting.");
    const final = await box(e).inputValue();
    await cta(e).click();
    const g = await nextTab(e);
    ok(`${tag} ONE tap opened a new tab on Google's direct write-a-review URL`, !!g && g.url() === GOOGLE, g ? g.url() : "no tab opened");
    const clip = await e.evaluate(() => navigator.clipboard.readText()).catch((x) => "ERR " + x.message);
    ok(`${tag} the approved text (with their edits) is on the clipboard`, clip === final, clip.slice(0, 60));
    ok(`${tag} instruction shown: copied, paste it into Google's box`, await e.getByText("Your review is copied.").isVisible() && await e.getByText(/Paste it into Google's review box, then choose your own star rating and post it yourself/).isVisible());
    ok(`${tag} label says copied / ready to paste`, (await e.getByTestId("origin-badge").innerText()).includes("Copied"));
    ok(`${tag} nothing claims it was submitted or published`, !/published|submitted|posted for you|auto/i.test(await e.locator("main").innerText()));
    ok(`${tag} review is preserved on the original tab after returning from Google`, (await box(e).inputValue()) === final);
    if (g) await g.close();
    await e.bringToFront();
    await e.reload();
    await e.waitForFunction(() => document.querySelector("#review")?.value.length > 10);
    ok(`${tag} a refresh/return restores the review and the paste instruction`, (await box(e).inputValue()) === final && await e.getByText("Welcome back. Your review is still here.").isVisible());
    ok(`${tag} Open Google again is offered`, (await e.getByRole("link", { name: /Open Google again/ }).getAttribute("href")) === GOOGLE);
    if (dname === "Android (Pixel 7)") await e.screenshot({ path: "shots4/04-android-copied.png", fullPage: false, animations: "disabled" });
    ok(`${tag} no console errors`, e.errs.length === 0, e.errs.join(" ; "));
    await finish(e);

    // ---------- F. clipboard blocked: graceful, Google still opens, fallback works ----------
    const f = await open(camp, dev, { clipboard: "deny" });
    await f.addInitScript(() => { Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new DOMException("denied", "NotAllowedError")) }, configurable: true }); document.execCommand = () => false; });
    await f.reload();
    await f.waitForFunction(() => document.querySelector("#review")?.value.startsWith("Sharing"));
    await cta(f).click();
    const fg = await nextTab(f);
    ok(`${tag} clipboard blocked: Google still opens`, !!fg && fg.url() === GOOGLE);
    await f.getByText("We couldn't copy it automatically.").waitFor({ timeout: 4000 });
    ok(`${tag} clipboard blocked: honest message + what to do, no claim it was copied`, await f.getByText(/Tap Copy review below, then paste it/).isVisible() && !(await f.getByText("Your review is copied.").isVisible()));
    await f.getByTestId("copy-only").click();
    const sel = await box(f).evaluate((a) => [a.selectionStart, a.selectionEnd, a.value.length]);
    ok(`${tag} Copy review fallback selects the text so it can be copied by hand`, sel[0] === 0 && sel[1] === sel[2] && sel[2] > 10, JSON.stringify(sel));
    if (dname === "Android (Pixel 7)") { await f.bringToFront(); await f.screenshot({ path: "shots4/05-android-copy-blocked.png", fullPage: false, animations: "disabled" }); }
    if (fg) await fg.close();
    await finish(f);

    // ---------- G. visible Copy review (no navigation) ----------
    const c = await open(camp, dev);
    await c.waitForFunction(() => document.querySelector("#review")?.value.startsWith("Sharing"));
    await c.getByTestId("copy-only").click();
    ok(`${tag} Copy review copies without leaving the page`, (await c.evaluate(() => navigator.clipboard.readText())) === STARTER.en && c.opened.length === 0 && (await c.getByTestId("copy-only").innerText()).includes("Copied"));
    // too short: no navigation
    await box(c).fill("ok");
    await cta(c).click({ force: true }); await sleep(600); // aria-disabled links are not "enabled" for Playwright; a real finger can still tap them
    ok(`${tag} a too-short review does not open Google; asks for a sentence`, c.opened.length === 0 && await c.getByRole("alert").filter({ hasText: "at least a short sentence" }).isVisible());
    // manual typing works with the AI off for this scenario
    await finish(c);
    const m = await open(camp, dev, { aiUp: false });
    await box(m).waitFor();
    ok(`${tag} AI off: empty box, manual writing available, no AI label`, (await box(m).inputValue()) === "" && (await m.getByTestId("origin-badge").count()) === 0);
    await box(m).fill("Written entirely by me about my own visit here.");
    await cta(m).click();
    const mg = await nextTab(m);
    const mclip = await m.evaluate(() => navigator.clipboard.readText()).catch((x) => "ERR " + x.message); ok(`${tag} manual review: copied and sent to Google in the same single tap`, !!mg && mg.url() === GOOGLE && mclip === "Written entirely by me about my own visit here.", `url=${mg && mg.url()} clip=${mclip.slice(0, 50)} reqs=${JSON.stringify(m.reqs.map((r) => r.path))}`);
    await finish(m);
  }

  // ---------- Hindi, keyboard (desktop) ----------
  const camp2 = await mkCamp("Hindi + keyboard");
  const h = await open(camp2, devices["Pixel 7"]);
  await h.waitForFunction(() => document.querySelector("#review")?.value.startsWith("Sharing"));
  await h.getByRole("radio", { name: "हिन्दी" }).click();
  await h.waitForFunction(() => /[\u0900-\u097F]/.test(document.querySelector("#review")?.value || ""), null, { timeout: 8000 });
  ok("[Hindi] language switch re-prepares the untouched suggestion in Hindi", (await box(h).inputValue()) === STARTER.hi);
  ok("[Hindi] one-tap button, instruction and badge are Hindi", (await cta(h).innerText()).includes("कॉपी करें और Google पर जाएँ") && await h.getByText(/आपका रिव्यू कॉपी हो जाएगा/).isVisible() && (await h.getByTestId("origin-badge").innerText()).includes("AI का सुझाव"));
  await h.screenshot({ path: "shots4/06-android-hindi.png", fullPage: false, animations: "disabled" });
  await cta(h).click();
  const hg = await nextTab(h);
  ok("[Hindi] copies the Hindi review and opens Google", !!hg && hg.url() === GOOGLE && (await h.evaluate(() => navigator.clipboard.readText())) === STARTER.hi);
  await finish(h);

  const k = await open(camp2, { viewport: { width: 1360, height: 900 }, userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0" });
  await k.waitForFunction(() => document.querySelector("#review")?.value.startsWith("Sharing"));
  await cta(k).focus(); await k.keyboard.press("Enter");
  const kg = await nextTab(k);
  ok("[Keyboard] Enter on the focused one-tap link copies and opens Google", !!kg && kg.url() === GOOGLE && (await k.evaluate(() => navigator.clipboard.readText())) === STARTER.en);
  await k.screenshot({ path: "shots4/07-desktop-copied.png", animations: "disabled" });
  await finish(k);

  // ---------- DIRECT SUBMISSION UI (MOCKED server capability + replies: no Google API exists for this, so this proves only the page's rules) ----------
  const campD = await mkCamp("Direct mode UI");
  const dev = devices["Pixel 7"];
  const base = await open(campD, dev);
  await base.waitForFunction(() => document.querySelector("#review")?.value.startsWith("Sharing"));
  ok("[Direct UI] default (real server): handoff only, no Submit button, no consent box, no /submit call", (await base.getByTestId("submit-review").count()) === 0 && (await base.getByTestId("consent").count()) === 0 && base.submits.length === 0);
  await finish(base);

  const d1 = await open(campD, dev, { submission: "direct" });
  await d1.waitForFunction(() => document.querySelector("#review")?.value.startsWith("Sharing"));
  ok("[Direct UI] server says direct: a Submit review button replaces Copy & Continue as the primary action", await d1.getByTestId("submit-review").isVisible() && (await d1.getByTestId("submit-review").innerText()).includes("Submit review"));
  ok("[Direct UI] Submit is disabled until the customer explicitly consents", await d1.getByTestId("submit-review").isDisabled());
  ok("[Direct UI] consent wording names the exact action", await d1.getByText(/reflects my own experience, and I agree to submit exactly this review to Google/).isVisible());
  await d1.screenshot({ path: "shots4/08-direct-ui-android.png", animations: "disabled" });
  await d1.getByTestId("consent").check();
  await d1.getByTestId("submit-review").click();
  ok("[Direct UI] no star rating: asked for stars, nothing submitted", (await d1.getByRole("alert").filter({ hasText: "Choose your stars" }).isVisible()) && d1.submits.length === 0);
  await stars(d1).nth(0).click();   // 1 star: equal access, nothing is hidden or redirected
  await d1.getByTestId("submit-review").click();
  await d1.getByText("Your review was submitted to Google.").waitFor({ timeout: 5000 });
  ok("[Direct UI] a 1-star review is submitted exactly like any other: explicit consent + own rating + exact text", d1.submits.length === 1 && d1.submits[0].rating === 1 && d1.submits[0].consent === true && d1.submits[0].final_text === STARTER.en);
  ok("[Direct UI] success shown only because the server said published, and no Google tab was opened", (await d1.getByText("Thank you. Google may take a little while to show it.").isVisible()) && d1.opened.length === 0);
  await finish(d1);

  for (const [label2, reply] of [["published:false (pending)", { status: 200, json: { status: "pending", published: false } }], ["503 not authorised", { status: 503, json: { detail: { code: "not_authorized", message: "x", review_url: GOOGLE } } }], ["502 provider error", { status: 502, json: { detail: { code: "submit_failed" } } }]]) {
    const d2 = await open(campD, dev, { submission: "direct", submitReply: reply });
    await d2.waitForFunction(() => document.querySelector("#review")?.value.startsWith("Sharing"));
    await stars(d2).nth(4).click(); await d2.getByTestId("consent").check(); await d2.getByTestId("submit-review").click();
    await d2.getByText("We couldn't submit it from here.").waitFor({ timeout: 5000 });
    ok(`[Direct UI] ${label2}: never claims success; says so and keeps the review`, !(await d2.getByText("Your review was submitted to Google.").count()) && (await box(d2).inputValue()) === STARTER.en);
    ok(`[Direct UI] ${label2}: falls back to Copy & Continue to Google (the supported route)`, await cta(d2).isVisible() && (await cta(d2).getAttribute("href")) === GOOGLE && (await d2.getByTestId("submit-review").count()) === 0);
    await finish(d2);
  }
  // ---------- the backend saw it (real sessions, approvals, redirects, copy flags) ----------
  await sleep(1500);
  const a = await (await owner.request.get(`${BASE}/api/v1/review-growth/analytics`)).json();
  console.log("      analytics totals:", JSON.stringify({ started: a.totals.feedback_submitted, approved: a.totals.drafts_approved, copied: a.totals.review_copied, to_google: a.totals.google_redirects, ratings: a.ratings.distribution }));
  ok("backend: every one-tap was approved and counted as a Google tap", a.totals.drafts_approved === 14 && a.totals.google_redirects === 14, `${a.totals.drafts_approved}/${a.totals.google_redirects} of 14`);
  ok("backend: copied-before-Google is counted separately from blocked copies", a.totals.review_copied >= 1 && a.totals.review_copied < a.totals.google_redirects);
  ok("backend: Google taps are never reported as published reviews", /NOT a published review/.test(a.definitions.google_redirects));
  console.log("EMAIL=" + email);
  console.log(fails ? `\n${fails} FAILED` : "\nALL PASSED");
  await browser.close(); process.exit(fails ? 1 : 0);
})().catch((e) => { console.error("CRASH:", e.message.split("\n").slice(0, 8).join("\n")); process.exit(2); });
