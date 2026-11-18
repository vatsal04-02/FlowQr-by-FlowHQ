# Website Builder: Cloudflare hosting, DNS migration plan, deployment and rollback

**Nothing in this document has been executed.** No DNS record, nameserver, Caddy file, VPS file, Docker Compose file, production environment variable, Cloudflare resource, Vercel setting or production database has been changed. This is the plan **for approval**. Every step marked `[NEEDS APPROVAL]` must not be done until the owner says so.

Prices and limits below are Cloudflare's published free-tier numbers as of this writing; confirm them on Cloudflare's pricing pages before relying on them, they change.

## 1. Model

One Cloudflare account hosts:

- **one Worker** `flowqr-sites` (code: `deploy/cloudflare/sites-worker/index.mjs`) bound to the route `*.<SITES_BASE_DOMAIN>/*`
- **one R2 bucket** (published files, read by the Worker, written by the FlowQR backend with an S3 token)
- **one Workers KV namespace** (`host:<hostname>` -> `{site_id, version, status}`, written by the FlowQR backend with an API token)

All businesses share them. Adding a business adds rows and objects, never Cloudflare resources.

## 2. Free-tier fit (verify current limits)

| Resource | Free allowance (approx.) | What FlowQR uses |
|---|---|---|
| Worker requests | 100,000 / day, 10 ms CPU per request | One request per page/asset view. A static read is far below 10 ms CPU. Daily cap is the first limit a successful launch would hit; at the cap the Worker errors until the next day. |
| Workers KV reads | 100,000 / day | One read per uncached request (`cacheTtl: 60` softens this). |
| Workers KV writes | 1,000 / day | One per publish/unpublish/suspend per site. Admin-driven, tiny. |
| R2 storage | 10 GB / month | A site is typically 200 KB to 3 MB (12 MB hard cap per site). |
| R2 Class A (writes) | 1 million / month | One per file per publish. |
| R2 Class B (reads) | 10 million / month | One per uncached file view. |
| R2 egress | free | |
| Universal SSL | included | Covers the apex and **one level** of wildcard (`*.domain`). `a.b.domain` is not covered, which matches the one-label slug rule. |

**Paid dependencies, if growth requires them:** Workers Paid (about 5 USD/month: 10 million requests included) when daily requests approach 100,000; R2/KV overage is cheap. **Custom customer domains** (`www.customer.com`) need **Cloudflare for SaaS custom hostnames**: a limited free allowance, then a per-hostname monthly fee, and it also requires a Cloudflare-hosted "fallback origin". Not implemented and not required for Phase 1.

Caching: HTML is `max-age=60`; hashed CSS and images are `immutable` for a year. Cloudflare's CDN absorbs most repeat views before the Worker runs only if cache rules are added; the default Worker response is not edge-cached beyond the `s-maxage` hint, so budget one Worker invocation per view.

## 3. Choose the sites domain (decision needed)

| Option | Pros | Cons |
|---|---|---|
| A. `<slug>.flowqr.site` | Familiar, zero new cost. | `flowqr.site`'s DNS would have to move to Cloudflare (nameserver change on the **main product domain**, which also serves Vercel, the API at `api.`, QR redirects at `go.`, email records). Session cookies (`COOKIE_DOMAIN=.flowqr.site`) are sent to business sites. |
| B. A separate registrable domain, e.g. `flowqr-sites.in` | Only that new domain moves to Cloudflare. **Production DNS for `flowqr.site` is untouched.** Cookies never reach business sites. Cleaner brand separation, safer for future self-edit. | One extra domain (about 1,000 INR/year for .in/.com; verify), shopkeepers see a different domain. |

**Recommendation: Option B.** It removes the riskiest step (changing nameservers of the live product domain) and the cookie-scope concern at once. The software supports either through `SITES_BASE_DOMAIN`. The remainder of this plan is written so that it applies to both; the extra steps for Option A are marked **(A only)**.

## 4. Cloudflare prerequisites (exact)

All `[NEEDS APPROVAL]`; performed in the Cloudflare dashboard by the account owner, not by Claude.

1. A Cloudflare account (free plan) with 2FA on.
2. Add the sites domain as a zone (**Add a site**), free plan. Cloudflare scans existing DNS records; **review the list** and add anything missing before the nameserver change.
3. Create the **KV namespace** `flowqr-sites-hosts`. Note its ID.
4. Create the **R2 bucket** `flowqr-sites` (private; **do not** enable the public `r2.dev` URL or a custom public domain; the Worker is the only reader).
5. Create an **R2 API token** scoped to **that one bucket**, permission *Object Read & Write*. Note the access key ID and secret.
6. Create a **Cloudflare API token** with only *Workers KV Storage: Edit* on the account, restricted to the one namespace if the dashboard allows it (else account-level KV edit is the minimum). Optionally *Zone: Cache Purge* on the sites zone only. Never use the Global API key.
7. Generate `SITES_SERVICE_TOKEN`: at least 32 random characters.
8. Install Wrangler locally; `wrangler login`.

## 5. DNS migration plan (for approval)

### Option B (recommended), sites on a new domain

Nothing about `flowqr.site` changes.

| Step | Action | Risk |
|---|---|---|
| B1 | Register the new domain. | None to production. |
| B2 | Add it to Cloudflare as a zone (section 4.2). | None. |
| B3 | At the registrar, set the domain's nameservers to the two Cloudflare names shown. | Only the new domain is affected; it hosts nothing yet. |
| B4 | In Cloudflare DNS add a **proxied (orange cloud)** wildcard record `*` -> any placeholder target (for a Worker-only origin use `A * 192.0.2.1` proxied, which is never contacted because the Worker answers first). Add nothing for the apex unless a landing page is wanted. | None. |
| B5 | Confirm **Universal SSL** is *Active* for `*.newdomain` and `newdomain` (Edge Certificates; can take minutes). SSL mode **Full** (not Flexible). Enable *Always Use HTTPS* and *Automatic HTTPS Rewrites*. | None. |
| B6 | Deploy the Worker with the route `*.newdomain/*` (section 6). | None to the main product. |
| B7 | Canary tests (section 7) with a throwaway site. | None. |

### Option A (only if the owner insists on `*.flowqr.site`), higher risk

| Step | Action | Risk |
|---|---|---|
| A1 | Inventory **every** DNS record of `flowqr.site` at GoDaddy (A/AAAA/CNAME for `@`, `www`, `api`, `go`; MX, SPF, DKIM, DMARC, any TXT verification for Google, Vercel, Cashfree; CAA). Export to a file. | Missing one breaks email or a product host. |
| A2 | Add the zone in Cloudflare and recreate every record **DNS only (grey cloud) for `api`, `go`, `@`, `www`**, exactly mirroring GoDaddy. **Do not proxy the API or Vercel records** (Vercel requires direct DNS, the API's Caddy handles its own TLS, QR redirects must keep working). Compare Cloudflare's imported list with the export line by line. | Proxying by accident breaks TLS or redirects. |
| A3 | Lower TTLs at GoDaddy to 300 s at least 24 h before. | |
| A4 | Change nameservers at GoDaddy to Cloudflare's. Pick a low-traffic window. Propagation up to 24-48 h; both old and new resolvers must return identical answers during that time, which A2 ensures. | **A mistake here is a production outage of the app, API, QR links and email.** |
| A5 | Verify: app loads, login, API health, `go.flowqr.site` redirect, sending and receiving email, Vercel domain still verified, Google OAuth redirect, Cashfree webhook reachability. | |
| A6 | Add the proxied wildcard `*` record, confirm Universal SSL, deploy the Worker route `*.flowqr.site/*`. The route must **not** match `www`, `api`, `go`: those records are grey-cloud (not proxied), so Worker routes do not apply to them, but the Worker also returns 404 for reserved/unregistered hosts as a second defence. | Route misconfiguration. |
| A7 | Backend: `SITES_ACCEPT_SHARED_COOKIE_SCOPE=true` is required (cookie decision in WEBSITE_BUILDER.md). | Cookie scope. |

**Option A rollback:** set the nameservers at GoDaddy back to GoDaddy's, which still hold the original records (do not delete them until the new setup has been stable for a week).

### What is **never** done by this plan

No change to `go.flowqr.site`, QR/NFC routing, Caddy or the VPS, Vercel domains, Cashfree or Google settings.

## 6. Deploying the Worker `[NEEDS APPROVAL]`

From `deploy/cloudflare/sites-worker`:

1. Edit `wrangler.toml` locally (do not commit secrets; none are in it): set `SITES_BASE_DOMAIN`, the KV `id`, the bucket name, uncomment `routes` with the sites zone, set `FLOWQR_API_URL=https://api.flowqr.site`.
2. `node --test test/worker.test.mjs` must pass.
3. `wrangler secret put SITES_SERVICE_TOKEN` (the same value as on the server).
4. `wrangler deploy`.
5. Note the deployed version ID (rollback uses it: `wrangler rollback`).

## 7. Validation with canary sites (before any customer)

Use only throwaway sites on the sites domain, status `complimentary` with reason "canary".

1. Unknown host `nosuch.<domain>` -> 404 plain page; headers include the CSP.
2. Publish a canary of each of the six templates; confirm 200, `Content-Security-Policy` exact, no `Set-Cookie`, `script-src 'none'`, correct title/canonical/JSON-LD, sitemap and robots.
3. `X-Forwarded-Host: other.<domain>` on a request to canary A still returns canary A (header ignored).
4. Unpublish -> 404 within one minute (KV pointer and the 60 s cache); suspend -> 503; resume -> 200.
5. A publish whose upload is made to fail (revoke the R2 token for a minute on a canary) leaves the previous version live and the admin sees the error.
6. Enquiry through the real form: arrives in the admin inbox; the honeypot field stores nothing; 6th enquiry within an hour from one IP is refused.
7. Performance: Lighthouse mobile >= 90 on every canary (static HTML, one CSS file, WebP images); time to first byte from India (e.g. WebPageTest Mumbai) under 400 ms warm.
8. Security: `curl -I` and a header scanner show the headers in WEBSITE_BUILDER.md; `/_manifest.json`, `/.env`, `/../x` all 404; `POST` to any path other than `/_enquiry` -> 405.
9. Cookie isolation: Option B: confirm a browser logged in to the app sends **no** cookie to the canary host (DevTools network). Option A: confirm the response has no `Set-Cookie` and no script runs.
10. Free-tier headroom: Cloudflare dashboard analytics after the test shows requests and KV operations well under limits.

## 8. FlowQR server configuration `[NEEDS APPROVAL]` (production environment: not changed yet)

When, and only when, sections 4-7 pass and approval is given, these are added to the server's environment (never to the repository):

```
SITES_ENABLED=true
SITES_BASE_DOMAIN=<the sites domain>
SITES_PROVIDER=cloudflare
SITES_SERVICE_TOKEN=<32+ random chars>
CLOUDFLARE_ACCOUNT_ID=...
CLOUDFLARE_API_TOKEN=...            # KV edit (and optional cache purge)
CLOUDFLARE_KV_NAMESPACE_ID=...
CLOUDFLARE_ZONE_ID=...              # optional
R2_BUCKET=flowqr-sites
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
SITES_ACCEPT_SHARED_COOKIE_SCOPE=true   # ONLY for Option A, after reading WEBSITE_BUILDER.md
```

The application refuses to start with `SITES_ENABLED=true` when any of these is missing or when the provider is `local` (the config check reports each problem in plain words). Check how the production compose file passes environment to the `api`, `worker` and `beat` services; add pass-through lines for the new variables **in the server's own override file**, never by overwriting the server's `docker-compose.yml` (it carries production-only lines).

## 9. Deployment sequence (for later approval)

1. Fetch and merge the latest release branch; re-run the full suites; build.
2. Back up the database (`docs/PRODUCTION_BACKUP_RESTORE.md`).
3. Deploy backend **with `SITES_ENABLED=false`**: migration 0047 applies (adds six empty tables, additive only). Verify health, QR redirects, login and that the Website card says "not enabled".
4. Deploy the frontend (Vercel root-directory recipe as before).
5. Complete sections 4-7 (Cloudflare) with throwaway sites against a **non-production** backend or with the flag on only briefly.
6. Set the section 8 environment, restart `api worker beat` with **both** compose files, set `SITES_ENABLED=true`, run canaries.
7. Only then create the first real customer's website, as a draft, with the owner's content approval; publish with a recorded commercial status.

## 10. Rollback

| Layer | Rollback | Data impact |
|---|---|---|
| Feature | Set `SITES_ENABLED=false`, restart `api worker beat`. All site routes answer `sites_disabled`, the public enquiry route 404s. Already published sites **keep being served by the Worker** (it does not depend on the API except for enquiries). | None |
| A bad site | Admin: Unpublish (404) or Suspend (503), or Rollback to an earlier revision. | None, content kept |
| Worker | `wrangler rollback` to the previous version; or delete the route to stop serving (all sites 404 at the edge). | None |
| All sites off at once | Delete/disable the Worker route, or empty the KV namespace (pointers only; files and content remain, republish restores). | None |
| Backend image | `up -d --no-deps api worker beat` with both compose files on the previous tag. **Do not downgrade the schema while the new image's data exists**; the older image works with 0047 present because the tables are additive. An older image cannot run `migrate` against a newer database. | None |
| Migration | `alembic downgrade 0046` drops the six new tables **and all site content and enquiries**. Use only on a database where the feature was never used, or after exporting. | Destructive |
| DNS (Option B) | Remove the wildcard record or point nameservers back; nothing else depended on it. | None |
| DNS (Option A) | Nameservers back to GoDaddy (records still there). | Propagation delay |

## 11. Remaining steps for a customer-ready launch

- Approve the sites domain (Option A or B), do sections 4-8 yourself or with explicit per-step approval.
- Decide on enquiry notifications (a proper transactional email provider rather than the shared Gmail account).
- Legal review of the generated privacy page text and the clinic disclaimer for each vertical.
- Custom customer domains (Cloudflare for SaaS) as a later phase.
