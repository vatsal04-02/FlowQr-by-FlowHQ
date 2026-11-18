// Run: node --test deploy/cloudflare/sites-worker/test/   (Node 20 or newer; no dependencies)
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import worker, { CSP, fileFor, slugFromHost } from "../index.mjs";

const BASE = "flowqr.site";
const HERE = dirname(fileURLToPath(import.meta.url));
const SITE = "11111111-2222-3333-4444-555555555555";
const TOKEN = "T".repeat(40);

function envWith({ pointers = {}, files = {}, token = TOKEN } = {}) {
  return {
    SITES_BASE_DOMAIN: BASE, FLOWQR_API_URL: "https://api.example.test", SITES_SERVICE_TOKEN: token,
    HOSTS: { async get(key) { return pointers[key] ?? null; } },
    SITES: { async get(key) { return key in files ? { body: new Response(files[key]).body, httpEtag: '"etag1"' } : null; } },
  };
}
const live = (host = `sharma.${BASE}`, status = "published") => ({ [`host:${host}`]: { site_id: SITE, version: 3, status } });
const FILES = {
  [`sites/${SITE}/v3/index.html`]: "<html>HOME</html>", [`sites/${SITE}/v3/privacy/index.html`]: "<html>PRIVACY</html>", [`sites/${SITE}/v3/thanks/index.html`]: "<html>THANKS</html>",
  [`sites/${SITE}/v3/style.0123456789.css`]: "body{}", [`sites/${SITE}/v3/assets/abcd.webp`]: "RIFFxxxxWEBP", [`sites/${SITE}/v3/robots.txt`]: "User-agent: *", [`sites/${SITE}/v3/favicon.svg`]: "<svg xmlns='http://www.w3.org/2000/svg'/>", [`sites/${SITE}/v3/_manifest.json`]: "{}",
};
const get = (url, env, init = {}) => worker.fetch(new Request(url, init), env);
const hdr = (r, name) => r.headers.get(name);

// ------------------------------------------------------------------------------------------------ hostnames
test("only <label>.<base> resolves", () => {
  for (const [h, want] of [["sharma.flowqr.site", "sharma"], ["SHARMA.FlowQR.site", "sharma"], ["sharma.flowqr.site:443", "sharma"], ["sharma.flowqr.site.", "sharma"], ["royal-salon.flowqr.site", "royal-salon"]]) assert.equal(slugFromHost(h, BASE), want, h);
  for (const h of [null, undefined, "", "flowqr.site", "a.b.flowqr.site", "sharma.flowqr.site.evil.com", "evilflowqr.site", "sharma.evil.com", "sharma.flowqr.site:8443", "1.2.3.4", "[::1]", "xn--abc.flowqr.site",
    "shärma.flowqr.site", "sharma.flowqr.site\0", "sharma .flowqr.site", "sharma.flowqr.site/evil", "sharma@evil.com.flowqr.site", ".flowqr.site", "-x-.flowqr.site", "ab.flowqr.site", "123456.flowqr.site", "x".repeat(300) + ".flowqr.site"]) {
    assert.equal(slugFromHost(h, BASE), null, String(h));
  }
  assert.equal(slugFromHost("sharma.sites.example", "sites.example"), "sharma");
  assert.equal(slugFromHost("sharma.flowqr.site", "sites.example"), null);
});

test("file paths: only plain files under the site", () => {
  assert.deepEqual(fileFor("/"), { key: "index.html", redirect: null });
  assert.deepEqual(fileFor("/privacy/"), { key: "privacy/index.html", redirect: null });
  assert.deepEqual(fileFor("/privacy"), { key: null, redirect: "/privacy/" });
  assert.deepEqual(fileFor("/assets/abcd.webp"), { key: "assets/abcd.webp", redirect: null });
  for (const p of ["/../etc/passwd", "/a/../b", "/./x.html", "/%2e%2e/x.html", "/%2E%2E%2Fx", "/a\\b.html", "/_manifest.json", "/assets/_x.webp", "/.env", "/x.php", "/x.js", "/x.json", "/a//b.html", "/a%00.html", "/%E0%A4%A", "/sp ace.html", "/x.html?x"]) {
    assert.equal(fileFor(p), null, p);
  }
});

// ------------------------------------------------------------------------------------------------ serving
test("a published site serves its files with the full security headers and no cookie", async () => {
  const env = envWith({ pointers: live(), files: FILES });
  const r = await get(`https://sharma.${BASE}/`, env, { headers: { Cookie: "flowqr_session=SECRET; flowqr_csrf=SECRET2" } });
  assert.equal(r.status, 200);
  assert.equal(await r.text(), "<html>HOME</html>");
  assert.equal(hdr(r, "Content-Security-Policy"), CSP);
  assert.equal(hdr(r, "X-Content-Type-Options"), "nosniff");
  assert.equal(hdr(r, "X-Frame-Options"), "DENY");
  assert.equal(hdr(r, "Content-Type"), "text/html; charset=utf-8");
  assert.equal(hdr(r, "Set-Cookie"), null, "the Worker must never set a cookie");
  assert.match(hdr(r, "Cache-Control"), /s-maxage=60/);
  assert.equal(hdr(r, "ETag"), '"etag1"');
  assert.ok(!JSON.stringify([...r.headers]).includes("SECRET"), "a cookie value leaked into a response header");
});

test("assets and the stylesheet are cached for a year, pages for a minute", async () => {
  const env = envWith({ pointers: live(), files: FILES });
  assert.match(hdr(await get(`https://sharma.${BASE}/assets/abcd.webp`, env), "Cache-Control"), /immutable/);
  assert.match(hdr(await get(`https://sharma.${BASE}/style.0123456789.css`, env), "Cache-Control"), /immutable/);
  assert.equal(hdr(await get(`https://sharma.${BASE}/assets/abcd.webp`, env), "Content-Type"), "image/webp");
  assert.doesNotMatch(hdr(await get(`https://sharma.${BASE}/privacy/`, env), "Cache-Control"), /immutable/);
});

test("the favicon is an image served with the same headers", async () => {
  const r = await get(`https://sharma.${BASE}/favicon.svg`, envWith({ pointers: live(), files: FILES }));
  assert.equal(r.status, 200);
  assert.equal(hdr(r, "Content-Type"), "image/svg+xml");
  assert.equal(hdr(r, "Content-Security-Policy"), CSP);
});

test("HEAD has the headers and no body; directories redirect to their slash form", async () => {
  const env = envWith({ pointers: live(), files: FILES });
  const h = await get(`https://sharma.${BASE}/`, env, { method: "HEAD" });
  assert.equal(h.status, 200);
  assert.equal(await h.text(), "");
  assert.equal(hdr(h, "Content-Security-Policy"), CSP);
  const r = await get(`https://sharma.${BASE}/privacy`, env);
  assert.equal(r.status, 308);
  assert.equal(hdr(r, "Location"), "/privacy/");
});

test("thanks and problem pages are noindex", async () => {
  const env = envWith({ pointers: live(), files: FILES });
  assert.match(hdr(await get(`https://sharma.${BASE}/thanks/`, env), "X-Robots-Tag"), /noindex/);
});

test("unknown host, unpublished site and missing file all give the same plain 404", async () => {
  const unknown = await get(`https://nobody.${BASE}/`, envWith({ files: FILES }));
  const unpublished = await get(`https://sharma.${BASE}/`, envWith({ files: FILES }));  // files exist, but no pointer: unpublished
  const missingFile = await get(`https://sharma.${BASE}/nope.html`, envWith({ pointers: live(), files: FILES }));
  const bodies = await Promise.all([unknown, unpublished, missingFile].map((r) => r.text()));
  for (const r of [unknown, unpublished, missingFile]) {
    assert.equal(r.status, 404);
    assert.equal(hdr(r, "Content-Security-Policy"), CSP);
    assert.equal(hdr(r, "Set-Cookie"), null);
    assert.match(hdr(r, "X-Robots-Tag"), /noindex/);
    assert.equal(hdr(r, "Cache-Control"), "no-store");
  }
  assert.equal(new Set(bodies).size, 1, "the answers differ, which would reveal whether a site exists");
  assert.ok(!bodies[0].includes("sharma") && !bodies[0].includes(SITE));
});

test("a suspended site answers 503 and serves none of its files", async () => {
  const env = envWith({ pointers: live(`sharma.${BASE}`, "suspended"), files: FILES });
  for (const p of ["/", "/privacy/", "/assets/abcd.webp"]) {
    const r = await get(`https://sharma.${BASE}${p}`, env);
    assert.equal(r.status, 503);
    assert.equal(hdr(r, "Retry-After"), "3600");
    assert.ok(!(await r.text()).includes("HOME"));
  }
});

test("hosts that are not a valid site address never reach the registry", async () => {
  let reads = 0;
  const env = envWith({ pointers: { ...live(), [`host:www.${BASE}`]: { site_id: SITE, version: 3, status: "published" } }, files: FILES });
  env.HOSTS.get = async (k) => { reads++; return null; };
  for (const h of [`www.${BASE}`.replace("www", "a.b"), "sharma.evil.com", BASE, "1.2.3.4"]) assert.equal((await get(`https://${h}/`, env)).status, 404);
  assert.equal(reads, 0);
});

test("path traversal and internal files are not served", async () => {
  const env = envWith({ pointers: live(), files: { ...FILES, [`sites/${SITE}/v3/../secret.html`]: "SECRET" } });
  for (const p of ["/_manifest.json", "/%2e%2e/secret.html", "/../secret.html", "/..%2fsecret.html", "/privacy/../../x.html", "/x.php", "/robots.txt%00.html"]) {
    const r = await get(`https://sharma.${BASE}${p}`, env);
    assert.ok([404, 308].includes(r.status), `${p} -> ${r.status}`);
    assert.ok(!(await r.text()).includes("SECRET"));
  }
});

test("only the host the request arrived on is trusted, never a forwarded header", async () => {
  const env = envWith({ pointers: live(), files: FILES });
  const r = await get(`https://nobody.${BASE}/`, env, { headers: { "X-Forwarded-Host": `sharma.${BASE}`, "X-Original-Host": `sharma.${BASE}`, Forwarded: `host=sharma.${BASE}` } });
  assert.equal(r.status, 404);
  const ok = await get(`https://sharma.${BASE}/`, env, { headers: { "X-Forwarded-Host": "evil.example" } });
  assert.equal(ok.status, 200);
});

test("only GET and HEAD are accepted, and the registry failing is a 503 not a 404", async () => {
  const env = envWith({ pointers: live(), files: FILES });
  for (const m of ["PUT", "DELETE", "PATCH", "OPTIONS"]) {
    const r = await get(`https://sharma.${BASE}/`, env, { method: m });
    assert.equal(r.status, 405);
    assert.equal(hdr(r, "Allow"), "GET, HEAD");
  }
  assert.equal((await get(`https://sharma.${BASE}/other`, env, { method: "POST", body: "x" })).status, 405);
  env.HOSTS.get = async () => { throw new Error("kv down"); };
  assert.equal((await get(`https://sharma.${BASE}/`, env)).status, 503);
});

// ------------------------------------------------------------------------------------------------ the enquiry relay
const form = (o = {}) => new URLSearchParams({ name: "Asha Verma", phone: "98765 43210", email: "", message: "Do you have a slot?", consent: "yes", website: "", ...o }).toString();
const post = (env, body, headers = {}, url = `https://sharma.${BASE}/_enquiry`) => get(url, env, { method: "POST", body, headers: { "Content-Type": "application/x-www-form-urlencoded", ...headers } });
function fakeApi(status = 201) {
  const calls = [];
  globalThis.fetch = async (url, init) => { calls.push({ url, init }); if (status === "throw") throw new Error("network"); return new Response("{}", { status }); };
  return calls;
}

test("the form is relayed server to server with the token and nothing of the visitor's cookies", async () => {
  const calls = fakeApi(201);
  const r = await post(envWith({ pointers: live() }), form({ email: "a@b.example" }), { Cookie: "flowqr_session=SECRET", Authorization: "Bearer SECRET", "CF-Connecting-IP": "203.0.113.7", Origin: `https://sharma.${BASE}` });
  assert.equal(r.status, 303);
  assert.equal(hdr(r, "Location"), "/thanks/");
  assert.equal(hdr(r, "Set-Cookie"), null);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://api.example.test/api/v1/site-enquiry");
  const sent = JSON.parse(calls[0].init.body);
  assert.deepEqual(sent, { host: `sharma.${BASE}`, client_ip: "203.0.113.7", name: "Asha Verma", phone: "98765 43210", email: "a@b.example", message: "Do you have a slot?", consent: true, website: "" });
  const h = calls[0].init.headers;
  assert.deepEqual(Object.keys(h).sort(), ["Content-Type", "X-Sites-Token"]);
  assert.equal(h["X-Sites-Token"], TOKEN);
  assert.ok(!JSON.stringify(calls[0].init).includes("SECRET"), "a cookie or authorization value was forwarded");
});

test("consent only counts when it is exactly yes; unknown fields are dropped", async () => {
  const calls = fakeApi(201);
  await post(envWith({ pointers: live() }), form({ consent: "true" }) + "&admin=1&host=evil.example");
  const sent = JSON.parse(calls[0].init.body);
  assert.equal(sent.consent, false);
  assert.equal(sent.host, `sharma.${BASE}`, "the host comes from the request, never from the form");
  assert.ok(!("admin" in sent));
});

test("every outcome ends in a redirect to the site's own static page", async () => {
  for (const [status, want] of [[201, "/thanks/"], [422, "/problem/"], [429, "/problem/"], [404, "/problem/"], [500, "/problem/"], ["throw", "/problem/"]]) {
    fakeApi(status);
    const r = await post(envWith({ pointers: live() }), form());
    assert.equal(r.status, 303, String(status));
    assert.equal(hdr(r, "Location"), want, String(status));
    assert.equal(hdr(r, "Cache-Control"), "no-store");
  }
});

test("a cross-site post, a wrong encoding, an oversized body and a non-published site never reach the API", async () => {
  const calls = fakeApi(201);
  assert.equal((await post(envWith({ pointers: live() }), form(), { Origin: "https://evil.example" })).status, 403);
  assert.equal((await post(envWith({ pointers: live() }), form(), { "Content-Type": "application/json" })).status, 415);
  assert.equal((await post(envWith({ pointers: live() }), "message=" + "x".repeat(9000))).status, 413);
  assert.equal((await post(envWith({ pointers: live(`sharma.${BASE}`, "suspended") }), form())).status, 503);
  assert.equal((await post(envWith({}), form())).status, 404);
  assert.equal((await post(envWith({ pointers: live() }), form(), {}, `https://sharma.${BASE}/other`)).status, 405);
  assert.equal(calls.length, 0);
});

test("without the service token configured the form fails safely and calls nothing", async () => {
  const calls = fakeApi(201);
  const r = await post(envWith({ pointers: live(), token: "" }), form());
  assert.equal(hdr(r, "Location"), "/problem/");
  assert.equal(calls.length, 0);
});

test("viewing a page never calls the API", async () => {
  const calls = fakeApi(201);
  await get(`https://sharma.${BASE}/`, envWith({ pointers: live(), files: FILES }));
  assert.equal(calls.length, 0);
});

// ------------------------------------------------------------------------------------------------ the Worker and the backend agree
test("the Content-Security-Policy equals the one in the backend", () => {
  const py = readFileSync(resolve(HERE, "../../../../backend/app/services/sites/hosting.py"), "utf8");
  const m = /^CSP = "(.*)"$/m.exec(py);
  assert.ok(m, "CSP not found in hosting.py");
  assert.equal(m[1], CSP);
  assert.ok(CSP.includes("script-src 'none'") && !CSP.includes("unsafe-inline") && !CSP.includes("*"));
});

test("the Worker contains no credential and no other origin than the API variable", () => {
  const src = readFileSync(resolve(HERE, "../index.mjs"), "utf8");
  assert.ok(!/api\.cloudflare\.com|Bearer |secret|password/i.test(src.replace(/\/\/.*$/gm, "")), "unexpected credential or provider API in the Worker");
  assert.ok(!/set-cookie/i.test(src.replace(/\/\/.*$/gm, "")), "the Worker must not set cookies");
  assert.ok(!/request\.headers\.get\(["']cookie["']\)/i.test(src), "the Worker must not read cookies");
  assert.ok(!/x-forwarded-host|x-original-host/i.test(src.replace(/\/\/.*$/gm, "")), "the Worker must not use forwarded host headers");
});
