// Depth/quality evaluation against the LIVE stack + REAL model. Throwaway businesses (zz-ev-*), deleted by the caller.
// usage: node eval-depth.js [reps=3] [label=run]   -> prints per-bucket word counts, opening diversity, invention audit, cost, latency. Writes evals/<label>.json
const { request } = require("playwright-core");
const fs = require("fs");
const BASE = "http://localhost:3000";
const UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const REPS = Number(process.argv[2] || 3), LABEL = process.argv[3] || "run";

const BUSINESSES = [
  { category: "Physiotherapy clinic", name: "Sunrise Physio", context: { description: "Exercise-based rehabilitation clinic.", services: ["Back pain rehabilitation", "Sports injury rehabilitation"] }, cases: [
    ["1 topic", "1", { suggestions: ["staff"], sentiment: "good" }],
    ["2 topics", "2-3", { suggestions: ["staff", "explanations"], sentiment: "good" }],
    ["3 topics", "2-3", { suggestions: ["staff", "explanations", "exercises"], sentiment: "good" }],
    ["3 topics + details", "detail", { suggestions: ["staff", "explanations", "exercises"], sentiment: "good", text: "the exercises were shown step by step and the waiting area was tidy" }],
    ["not good, 2 topics", "neg", { suggestions: ["appointment", "treatment"], sentiment: "not_good" }],
    ["okay, 2 topics", "neg", { suggestions: ["staff", "appointment"], sentiment: "okay" }],
    ["Hindi, 3 topics", "hi", { suggestions: ["staff", "explanations", "exercises"], sentiment: "good", language: "hi" }],
  ] },
  { category: "Restaurant", name: "Spice Route", context: { description: "Family restaurant serving North Indian food." }, cases: [
    ["1 topic", "1", { suggestions: ["food"], sentiment: "good" }],
    ["3 topics", "2-3", { suggestions: ["food", "service", "ambience"], sentiment: "good" }],
    ["3 topics + details", "detail", { suggestions: ["food", "service", "ambience"], sentiment: "good", text: "we came with kids, the dal makhani was rich" }],
    ["not good, waiting", "neg", { suggestions: ["waiting", "service"], sentiment: "not_good" }],
  ] },
  { category: "Hotel", name: "Lakeview Hotel", context: {}, cases: [
    ["3 topics", "2-3", { suggestions: ["room", "hospitality", "checkin"], sentiment: "good" }],
    ["Hindi, 2 topics", "hi", { suggestions: ["room", "hospitality"], sentiment: "good", language: "hi" }],
  ] },
  { category: "Salon / Spa", name: "Glow Salon", context: {}, cases: [["3 topics", "2-3", { suggestions: ["service_result", "staff", "hygiene"], sentiment: "good" }]] },
  { category: "Automobile service centre", name: "Metro Auto Care", context: {}, cases: [["3 topics", "2-3", { suggestions: ["service_quality", "communication", "turnaround"], sentiment: "good" }]] },
];
// things that must never appear unless the customer wrote them (the user's "must not add automatically" list + common fabrication)
const INVENTED = /\b(recover\w*|relief|pain[- ]free|less pain|reduced|improv\w*|healed|cured|on time|punctual\w*|no wait|didn'?t have to wait|answered all|patiently answered|every question|recommend\w*|highly|definitely|overall|will (?:be )?(?:visit|return|come)|again|always|best|perfect|amazing|excellent|felt (?:comfortable|welcome|relieved|reassured))\b|ठीक हो|राहत|दोबारा|ज़रूर|जरूर|कुल मिलाकर|सिफ़ारिश|सिफारिश/i;
const words = (s) => (s.match(/[A-Za-z]+|[ऀ-ॿ]+/g) || []).length;

(async () => {
  const pub = await request.newContext({ baseURL: BASE, extraHTTPHeaders: { "user-agent": UA } });
  const emails = [], rows = [], lat = [];
  for (const b of BUSINESSES) {
    const api = await request.newContext({ baseURL: BASE });
    const email = `zz-ev-${Date.now().toString(36)}-${emails.length}@example.com`; emails.push(email);
    const reg = await (await api.post("/api/v1/auth/register", { data: { email, password: "Str0ngPassw0rd!", full_name: "Eval" } })).json();
    const H = { "X-CSRF-Token": reg.csrf_token };
    await api.post("/api/v1/tenants", { headers: H, data: { name: b.name, category: b.category } });
    const loc = await (await api.post("/api/v1/locations", { headers: H, data: { name: "Main branch", city: "Lucknow", review_url: "https://g.page/r/EV/review" } })).json();
    await api.post("/api/v1/tenant/complete-onboarding", { headers: H });
    if (Object.keys(b.context).length) await api.put("/api/v1/review-growth/context", { headers: H, data: b.context });
    b.rows = [];
    for (const [name, bucket, body] of b.cases) {
      for (let i = 0; i < REPS; i++) {
        const camp = await (await api.post("/api/v1/review-growth/campaigns", { headers: H, data: { name: `${name} ${i}`.slice(0, 100), location_id: loc.id } })).json();
        if (process.env.DELAY_MS) await new Promise((r) => setTimeout(r, Number(process.env.DELAY_MS))); // pace requests for free-tier rate limits
        const t0 = Date.now();
        const r = await (await pub.post(`/api/v1/public/reviews/${camp.public_id}/generate`, { data: { language: "en", mode: "ai", ...body, sentiment: undefined, rating: ({ good: 4 + (i % 2), okay: 3, not_good: 1 + (i % 2) })[body.sentiment] } })).json();
        lat.push(Date.now() - t0);
        const row = { biz: b.name, name, bucket, status: r.ai_status, draft: r.draft || null, words: r.draft ? words(r.draft) : 0, followUp: r.follow_up || null };
        row.invented = row.draft && !body.text && INVENTED.test(row.draft) ? (row.draft.match(INVENTED) || [])[0] : null;
        rows.push(row);
      }
    }
    const a = await (await api.get("/api/v1/review-growth/analytics")).json(); b.ai = a.ai;
  }
  const ok = rows.filter((r) => r.status === "ok");
  const avg = (xs) => (xs.length ? (xs.reduce((s, x) => s + x, 0) / xs.length).toFixed(1) : "-");
  console.log(`\n===== ${LABEL}: ${rows.length} requests, accepted ${ok.length} (${Math.round((100 * ok.length) / rows.length)}%) =====`);
  for (const bk of ["1", "2-3", "detail", "neg", "hi"]) {
    const xs = ok.filter((r) => r.bucket === bk);
    console.log(`bucket ${bk.padEnd(6)} n=${String(xs.length).padStart(2)}  avg words ${avg(xs.map((r) => r.words))}  min ${Math.min(...xs.map((r) => r.words), 999)}  max ${Math.max(...xs.map((r) => r.words), 0)}`);
  }
  const open = (r) => r.draft.toLowerCase().split(/\s+/).slice(0, 3).join(" ");
  const en = ok.filter((r) => r.bucket !== "hi");
  console.log(`opening diversity (distinct first-3-words / drafts, English): ${new Set(en.map(open)).size}/${en.length}`);
  const endings = en.map((r) => r.draft.split(/(?<=[.!?])\s+/).pop().toLowerCase().split(/\s+/).slice(0, 3).join(" "));
  console.log(`ending diversity (distinct last-sentence first-3-words): ${new Set(endings).size}/${en.length}`);
  const inv = ok.filter((r) => r.invented);
  console.log(`invention audit: ${inv.length} drafts contain a banned/unsupported term` + inv.map((r) => `\n   [${r.invented}] ${r.draft}`).join(""));
  console.log(`follow-up question returned: ${rows.filter((r) => r.followUp).length}`);
  const sum = (k) => BUSINESSES.reduce((s, b) => s + (b.ai[k] || 0), 0), cost = BUSINESSES.reduce((s, b) => s + (b.ai.cost_usd || 0), 0);
  lat.sort((x, y) => x - y);
  console.log(`model calls/request ${(sum("model_calls") / rows.length).toFixed(2)} | tokens in/out per request ${Math.round(sum("tokens_in") / rows.length)}/${Math.round(sum("tokens_out") / rows.length)} | cost per accepted draft $${(cost / Math.max(1, sum("accepted"))).toFixed(6)} | latency median ${lat[Math.floor(lat.length / 2)]}ms p90 ${lat[Math.floor(lat.length * 0.9)]}ms`);
  console.log("\n--- SAMPLE DRAFTS (first of each case) ---");
  const seen = new Set();
  for (const r of rows) { const k = r.biz + r.name; if (seen.has(k)) continue; seen.add(k); console.log(`[${r.biz} | ${r.name}] (${r.words}w) ${r.status === "ok" ? r.draft : "REJECTED"}`); }
  fs.mkdirSync("evals", { recursive: true }); fs.writeFileSync(`evals/${LABEL}.json`, JSON.stringify(rows, null, 1));
  console.log("EMAILS=" + emails.join(","));
})().catch((e) => { console.error("FAILED:", e.message.split("\n")[0]); process.exit(1); });
