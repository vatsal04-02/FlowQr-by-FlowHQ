// FlowQR business websites: ONE shared Cloudflare Worker for every business.
//
// A request for <slug>.<SITES_BASE_DOMAIN> is resolved like this:
//   1. the hostname must be exactly one valid label under the base domain (the Host the request arrived on; X-Forwarded-Host and every other header are never consulted)
//   2. Workers KV key "host:<hostname>" holds {site_id, version, status}. No entry = unknown or unpublished = the same plain 404
//   3. status "suspended" = a plain 503; status "published" = the file is read from R2 at sites/<site_id>/v<version>/<path>
// The Worker only reads. It never reads or forwards a Cookie header and never sets a cookie, so the FlowQR session and CSRF cookies (scoped to a parent domain in production) have no effect here.
// The one write is the enquiry form: POST /_enquiry on the site's own address is relayed server to server to the FlowQR API with a secret token; the browser never talks to the API.
//
// Bindings (wrangler.toml): HOSTS (KV namespace), SITES (R2 bucket). Variables: SITES_BASE_DOMAIN, FLOWQR_API_URL. Secret: SITES_SERVICE_TOKEN (wrangler secret put). Nothing here is a credential.

// Must equal backend/app/services/sites/hosting.py CSP (deploy/cloudflare/sites-worker/test/worker.test.mjs checks it).
export const CSP = "default-src 'none'; script-src 'none'; style-src 'self'; img-src 'self'; font-src 'none'; connect-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'";

const TYPES = { ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".webp": "image/webp", ".txt": "text/plain; charset=utf-8", ".xml": "application/xml; charset=utf-8", ".svg": "image/svg+xml" };
const LABEL = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/;
const MAX_FORM_BYTES = 8192;
const FIELDS = ["name", "phone", "email", "message", "consent", "whatsapp_ok", "website"];

export function slugFromHost(raw, base) {
  if (typeof raw !== "string" || raw.length === 0 || raw.length > 253 || /[^\x21-\x7e]/.test(raw)) return null;
  let host = raw.toLowerCase().replace(/\.$/, "");
  if (host.endsWith(":443")) host = host.slice(0, -4);
  const b = String(base || "").toLowerCase().replace(/^\.+|\.+$/g, "");
  if (!b || !host.endsWith("." + b)) return null;
  const label = host.slice(0, host.length - b.length - 1);
  if (label.includes(".") || label.length < 3 || label.length > 40 || !LABEL.test(label) || label.includes("--") || /^\d+$/.test(label)) return null;
  return label;
}

function securityHeaders(extra = {}) {
  return {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000",
    ...extra,
  };
}

const page = (status, title, text, extra = {}) =>
  new Response(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>${title}</title></head><body><main><h1>${title}</h1><p>${text}</p></main></body></html>`, {
    status,
    headers: securityHeaders({ "Content-Type": TYPES[".html"], "X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store", ...extra }),
  });

// Unknown, unpublished and unpaid hosts are indistinguishable from each other: the same answer, with nothing about the site in it.
const notFound = () => page(404, "Not found", "There is nothing at this address.");
const unavailable = () => page(503, "Temporarily unavailable", "This website is temporarily unavailable.", { "Retry-After": "3600" });

async function pointer(env, host) {
  try {
    const p = await env.HOSTS.get(`host:${host}`, { type: "json", cacheTtl: 60 });
    return p && typeof p === "object" && typeof p.site_id === "string" && Number.isInteger(p.version) && (p.status === "published" || p.status === "suspended") ? p : null;
  } catch {
    return undefined; // the registry could not be read: a 503, not a 404 (the site may exist)
  }
}

function extOf(path) {
  const m = /\.[a-z0-9]+$/.exec(path);
  return m ? m[0] : "";
}

// "/" -> index.html, "/privacy/" -> privacy/index.html. Returns null for anything that is not a plain file path under the site (no "..", no backslash, no "_" internals, no odd characters).
export function fileFor(pathname) {
  let p;
  try {
    p = decodeURIComponent(pathname);
  } catch {
    return null;
  }
  if (!p.startsWith("/") || p.includes("\\") || p.includes("\0") || p.includes("//") || p.split("/").some((s) => s === ".." || s === "." || s.startsWith("_") || s.startsWith("."))) return null;
  if (!/^[A-Za-z0-9_./-]*$/.test(p)) return null;
  if (p.endsWith("/")) return { key: p.slice(1) + "index.html", redirect: null };
  const ext = extOf(p);
  if (!ext) return { key: null, redirect: p + "/" };
  return TYPES[ext] ? { key: p.slice(1), redirect: null } : null;
}

function cacheControl(key) {
  return /^(assets\/|style\.[0-9a-f]+\.css$)/.test(key) ? "public, max-age=31536000, immutable" : "public, max-age=60, s-maxage=60";
}

async function serve(request, env, host, ptr, url) {
  const f = fileFor(url.pathname);
  if (!f) return notFound();
  if (f.redirect) return new Response(null, { status: 308, headers: securityHeaders({ Location: f.redirect, "Cache-Control": "public, max-age=3600" }) });
  const obj = await env.SITES.get(`sites/${ptr.site_id}/v${ptr.version}/${f.key}`);
  if (!obj) return notFound();
  const h = securityHeaders({ "Content-Type": TYPES[extOf(f.key)] || "application/octet-stream", "Cache-Control": cacheControl(f.key) });
  if (obj.httpEtag) h["ETag"] = obj.httpEtag;
  if (f.key.startsWith("thanks/") || f.key.startsWith("problem/")) h["X-Robots-Tag"] = "noindex, nofollow";
  return new Response(request.method === "HEAD" ? null : obj.body, { status: 200, headers: h });
}

async function enquiry(request, env, host, ptr) {
  const back = (path) => new Response(null, { status: 303, headers: securityHeaders({ Location: path, "Cache-Control": "no-store" }) });
  const origin = request.headers.get("Origin");
  if (origin && origin !== `https://${host}`) return page(403, "Not allowed", "This form can only be sent from the website itself.");
  if (!(request.headers.get("Content-Type") || "").toLowerCase().startsWith("application/x-www-form-urlencoded")) return page(415, "Not supported", "Unsupported form encoding.");
  const declared = Number(request.headers.get("Content-Length") || 0);
  if (declared > MAX_FORM_BYTES) return page(413, "Too large", "That message is too long.");
  let raw = "";
  try {
    raw = await request.text();
  } catch {
    return back("/problem/");
  }
  if (raw.length > MAX_FORM_BYTES) return page(413, "Too large", "That message is too long.");
  if (ptr.status !== "published") return unavailable();
  if (!env.SITES_SERVICE_TOKEN || !env.FLOWQR_API_URL) return back("/problem/");
  const form = new URLSearchParams(raw);
  const body = { host, client_ip: request.headers.get("CF-Connecting-IP") || null };
  for (const k of FIELDS) body[k] = String(form.get(k) ?? "").slice(0, 4000);
  body.consent = form.get("consent") === "yes";
  body.whatsapp_ok = form.get("whatsapp_ok") === "yes";
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 8000);
  try {
    // A fresh set of headers: the visitor's cookies, authorization and everything else are NOT forwarded.
    const r = await fetch(`${String(env.FLOWQR_API_URL).replace(/\/$/, "")}/api/v1/site-enquiry`, {
      method: "POST", signal: ctl.signal,
      headers: { "Content-Type": "application/json", "X-Sites-Token": env.SITES_SERVICE_TOKEN },
      body: JSON.stringify(body),
    });
    return back(r.status === 201 || r.status === 200 ? "/thanks/" : "/problem/");
  } catch {
    return back("/problem/");
  } finally {
    clearTimeout(timer);
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const host = url.hostname.toLowerCase();
    if (!slugFromHost(host, env.SITES_BASE_DOMAIN)) return notFound();
    const isEnquiry = request.method === "POST" && url.pathname === "/_enquiry";
    if (request.method !== "GET" && request.method !== "HEAD" && !isEnquiry) {
      return page(405, "Not allowed", "This address only accepts viewing.", { Allow: "GET, HEAD" });
    }
    const ptr = await pointer(env, host);
    if (ptr === undefined) return unavailable();
    if (!ptr) return notFound();
    if (isEnquiry) return enquiry(request, env, host, ptr);
    if (ptr.status === "suspended") return unavailable();
    return serve(request, env, host, ptr, url);
  },
};
