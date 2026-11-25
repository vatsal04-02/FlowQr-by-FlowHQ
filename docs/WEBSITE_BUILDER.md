# Website Builder

Status: implemented in the repository, **not deployed, not enabled** (`SITES_ENABLED=false` is the default). Nothing in this document has been applied to production DNS, the VPS, Caddy, Vercel, Cloudflare or any production database.

Companion document: [WEBSITE_BUILDER_CLOUDFLARE.md](WEBSITE_BUILDER_CLOUDFLARE.md) (hosting prerequisites, the DNS migration plan for approval, deployment and rollback).

## What it is

A platform administrator opens **Admin → Businesses → a business → Website**, creates a website from one of six templates, edits its text and images, previews it on desktop and phone widths, saves a draft, and publishes it. The published site is a small set of **static files** served at `https://<slug>.<SITES_BASE_DOMAIN>/`. There is no shopkeeper login in Phase 1: the administrator does the work on the business's behalf.

## Architecture (and why)

```
 Admin (Next.js)  ->  FlowQR API (FastAPI, Postgres)  --writes-->  R2 bucket   sites/<site_id>/v<n>/<file>
                                                       --writes-->  Workers KV  host:<hostname> -> {site_id, version, status}
 Visitor  ->  <slug>.<base-domain>  ->  ONE shared Cloudflare Worker  --reads-->  KV (pointer) then R2 (file)
 Visitor enquiry form  ->  Worker  --server to server, X-Sites-Token-->  POST /api/v1/site-enquiry
```

Decisions:

| Decision | Reason |
|---|---|
| One shared Worker for every business, not one Pages project per customer | Pages projects have per-account limits, need an API round trip per customer to create, and each would need its own domain binding. One Worker plus a host registry scales with rows, not projects. Fits the free tier (see the Cloudflare document). |
| Files in R2 under a versioned prefix, pointer in KV | Publish = write all files of version N+1, **then** flip one KV pointer. The public sees the old version or the new version, never a mixture. A failed upload leaves the pointer untouched, so the live site is unaffected. |
| The Worker only reads | No credentials that can write are present in the Worker except the enquiry token. A bug in the Worker cannot change published content. |
| Static output, zero JavaScript | Nothing to exploit client-side, fast on cheap phones, no cookie/XSS reach into FlowQR (see Cookie and origin isolation). |
| Enquiries relayed server to server | The browser never calls the FlowQR API from a business site, so no CORS entry for any business host and no API origin is exposed to the page. |
| Wildcard hostname `*.<base-domain>` | Needs the sites domain's **DNS on Cloudflare** (Cloudflare cannot route a wildcard for a zone it does not host). That is a nameserver change and is a separate, unexecuted plan in the Cloudflare document. |
| Hosting behind a provider interface | `build_site`, `publish_site`, `unpublish_site`, `delete_site`, `get_publish_status`, `resolve_site_hostname` on `HostingProvider`. `LocalDirectoryProvider` (development and tests; the production config check refuses it) and `CloudflareProvider`. |

The earlier Vercel-per-site idea was **not** implemented.

## Data model (migration 0047)

`sites`, `site_domains`, `site_assets`, `site_enquiries`, `site_revisions`, `site_slug_quarantine`.

- Every tenant table has **forced row level security** with the standard `tenant_isolation` policy; `site_slug_quarantine` has a platform-only policy.
- One site per business (unique on tenant), unique slug, **one active primary hostname per site** (partial unique index), status/commercial/template check constraints.
- `site_revisions` is **append-only**: publish inserts a row; rollback republishes an older revision as a **new** revision; nothing is updated or deleted.
- `site_slug_quarantine`: a released slug (site deleted or renamed) cannot be claimed by another business for **90 days**.
- Reserved slugs (`www`, `api`, `go`, `admin`, `app`, `mail`, `static`, ... see `services/sites/rules.py`) can never be used; `suggest_slug` never returns one.
- Account export includes the new tables (`_ALSO_EXPORTED` drift test) and tenant deletion removes the site, assets, enquiries and its hosted files and pointer (`on_tenant_delete`).

### Alembic graph

`0045 -> 0046 -> 0047` (head). `0047_website_builder.py` has `down_revision = "0046"`. The migration tests that pinned the head to 0046 now pin 0047, and `test_the_chain_is_one_linear_line_ending_at_0047_and_0046_hangs_off_0045` asserts the graph is a single line. The migration was **only applied to local scratch databases**; downgrade is tested (drops everything it created).

**Known conflict, not touched:** the unmerged branch `feature/cardless-trial` carries a migration numbered 0039 with `down_revision` 0037. It cannot join the release chain as is. When it ships it must be **renumbered** onto the then-current head; it must never be merged blindly.

## Content model

- `draft_content` / `published_content` are JSONB documents: `business`, `theme` (template accent from a contrast-checked whitelist), `seo`, and an ordered list of `sections` (`type`, `enabled`, `data`).
- `services/sites/catalog.py` holds one spec per section type. That single source drives **validation, the editor's forms (`GET /admin/sites/templates`) and the defaults**, so the form, the API and the renderer cannot disagree.
- Two validation levels: **save** checks shape and safety only (so a half-written draft can be saved); **publish** also checks completeness (`publish_blockers`: every enabled section must have its required content, images need alt text, clinics keep the health disclaimer, etc.). The editor shows the blockers in plain words and disables Publish until none remain.
- Optimistic concurrency: `draft_version` must match on save; a stale editor gets a conflict instead of overwriting.
- Content is plain text only. Invisible and bidirectional control characters are stripped. There is no free HTML, CSS or script anywhere in the model.

### Templates

Six, each with its own layout, hero and default section order (not a re-skin of one page):

| Key | For | Hero |
|---|---|---|
| `clinic` | Clinic, physiotherapy | appointment panel with hours; credentials, conditions treated, process, FAQ, disclaimer |
| `salon` | Salon, beauty | photo-led, service menu, gallery |
| `restaurant` | Restaurant, cafe | food photo, menu highlights, hours, order/reserve |
| `retail` | Shop | introduction, what we sell, visit us |
| `home_services` | Plumber, electrician, cleaning | service-first, areas served, call-now |
| `professional` | Lawyer, CA, consultant | practice areas, credentials, consultation |

Visual direction: Swiss-minimal, strong typography, one accent colour, functional motion only (none that needs JavaScript), no gradients/blobs/glass.

## Onboarding question and the "Generate site" entry point

- Onboarding step 1 asks every new business **"Do you have a website?"**: *Yes, I have one* (optional address), *No, please build one*, or *No, not now*. The answer is stored on `tenants.website_interest` (`has_site | wants_site | not_now`, NULL = never asked; column added by migration 0047) through `PUT /api/v1/tenant/website-interest` (owner/admin of that business, audited). Choosing "please build one" **creates nothing, publishes nothing and charges nothing**; it only flags the business for staff. This works even while `SITES_ENABLED=false`.
- Admin → Businesses has a **Website** column (Wants a website / Has its own / Not now / Not asked, or the site's state once one exists), a **Website** filter (asked us to build one / we built one / no website yet) and a **Generate site** link that opens the business page with the create form already open. While the builder is switched off the column shows "Builder is off" instead of the link.

## Rendering

`services/sites/render.py` + `htmlkit.py` + `css.py` build a site from content to a dict of files.

- **Escape by construction**: `htmlkit.el()` only emits whitelisted tags and attributes; every text node is escaped; every URL attribute must match a strict pattern (`#anchor`, a single-slash path, `tel:+digits`, `mailto:`, `https://...`, or a `data:image/webp;base64` image, which only the admin preview uses so that draft images show without being public). `//evil.example`, `javascript:`, `data:text/html` are refused. JSON-LD is escaped for `</script>`. There is no `dangerouslySetInnerHTML` anywhere in the frontend; the admin preview is an `iframe srcDoc` with an empty `sandbox` attribute.
- **Deterministic**: the same content produces byte-identical files; the CSS file name carries a content hash. A `_manifest.json` (checksums) is written for integrity checks and is **never served** (the Worker refuses any path starting with `_`).
- **Link destinations** are whitelisted per kind (`rules.clean_https_url`): maps, review, social and order links must be on an allowlist of hosts; arbitrary URLs are refused.
- Files: `index.html`, `privacy/`, `thanks/`, `problem/`, `style.<hash>.css`, `assets/<hash>.webp`, `robots.txt`, `sitemap.xml`, `favicon.svg` (a plain accent-coloured square; no text, nothing from the business).
- **SEO**: unique title and description (length-checked), canonical, Open Graph, `LocalBusiness` JSON-LD from the business facts, sitemap, robots. Drafts and previews carry `noindex`; `thanks/` and `problem/` are `noindex`. The product **never promises rankings**.

## Media

`services/sites/media.py`. Upload is a raw body to `POST /admin/sites/{id}/assets`.

- Magic-byte sniff: JPEG, PNG, WebP only. **SVG, GIF/animated and everything else are refused** (the extension and the `Content-Type` header are not trusted).
- Pixel-count limit before decoding (decompression-bomb guard), 8 MB upload cap, max 24 images and 12 MB per site.
- The image is re-encoded as a **fresh WebP** after applying EXIF orientation. EXIF (including GPS), XMP and ICC chunks are verified absent in the output (`riff_chunks`). Max edge 1600 px (600 px thumbnail); de-duplicated by SHA-256.
- Assets are served only through the admin API (tenant-scoped, platform-admin only) while drafting, and copied into the published version as `assets/<hash>.webp` on publish. A published asset is a public file by design; a draft asset is not reachable by hostname.

## Admin API and authorisation

24 routes under `/api/v1/admin/sites...` and `/admin/tenants/{id}/site`, all behind `require_platform_admin`, all listed in `tests/route_access_manifest.txt`. Every state change is audited (`admin.site_create`, `admin.site_edit`, `admin.asset_add`, `admin.site_publish`, `admin.site_unpublish`, `admin.site_suspend`, `admin.site_unsuspend`, `admin.site_commercial`, `admin.site_enquiry_status`, ...).

The only public route is `POST /api/v1/site-enquiry`, authenticated by `X-Sites-Token` (constant-time compare; disabled when the token is unset), and is on the reviewed public-write list.

`SITES_ENABLED=false`: every admin site route answers `sites_disabled`; the public enquiry route answers 404; the Website card shows "not enabled". Nothing else in FlowQR changes and no provider is constructed.

## Publish, unpublish, suspend, rollback

| Action | Effect |
|---|---|
| Publish | Validate completeness, build files, write R2 (retry, ETag check), write KV pointer, insert revision, audit. On any failure the previous version stays live and the admin sees a plain error (`pointer_failed`: "The previous version is still live."). |
| Unpublish | Pointer removed: public answers 404. Draft and published content are **kept**. |
| Suspend / resume | Pointer status `suspended`: public answers 503 "temporarily unavailable" (no detail). Content kept. |
| Rollback | Republish an older revision as a new revision. |
| Delete site | Admin only; removes files, pointer, enquiries and content; slug goes into 90-day quarantine. |

Old versions: the last two are kept in R2, older ones pruned.

## Enquiries

Visitor form fields: name, phone and/or email, message, an explicit **consent checkbox**, and a hidden honeypot. Worker relays; the API checks the host is a live published site, rate-limits (5 per hour per site and IP hash, 100 per day per site), applies the honeypot (success shown, nothing stored), validates, and stores. The IP is stored only as a salted hash. Retention: 180 days (`SITES_ENQUIRY_RETENTION_DAYS`), purged by a Celery task. The admin inbox lists, filters, marks contacted/resolved, and exports CSV. Enquiries are never exposed publicly.

Notifications go through a `Notifier` interface. The default is **none**. An SMTP notifier exists but is **not enabled and not recommended on the shared Gmail account** (daily quota, deliverability and a Gmail From address for other people's businesses); review before use.

## Commercial status (recorded by hand; no billing)

Add-on: **₹199/month or ₹1,999/year, no setup fee**, two minor edits a month included; extra edits, a custom domain and redesigns are priced separately. This is shown as reference text only. **Nothing is billed from the application, no plan changes, Cashfree is untouched.**

`commercial_status`: `complimentary` (requires a written reason), `paid_offline`, `suspended`, `expired`. Creating a site requires choosing one explicitly (hosting is never silently free). Every manual change requires a reason and is audited. `expired` starts a grace period (`SITES_GRACE_DAYS`, 14); when it ends `enforce_commercial` suspends the site. **A lapse suspends; it never deletes content.** Account export covers the site content, so a business can always be handed its data.

## Security model

| Threat | Control |
|---|---|
| Cross-tenant access | RLS on every table; admin routes load the site through the tenant; asset lookups are `(site_id, asset_id)` pairs; tests cover cross-tenant asset and enquiry access. |
| Host header spoofing | The Worker uses the request's own `Host` only; `X-Forwarded-Host` and similar are never read. Host must be exactly one valid label under the base domain; the host registry (KV) must contain it. The API re-resolves the host against `site_domains`. |
| Unknown/unpublished/unpaid hosts | One identical 404 page with no information. Suspended: one identical 503. |
| XSS / injection | Escape-by-construction builder, URL scheme whitelist, no raw HTML/CSS/JS input, CSP `script-src 'none'`. |
| Malicious upload | Magic bytes, SVG refused, pixel and size limits, re-encode, metadata stripped. |
| Content injection into other sites | Files are written only under `sites/<site_id>/v<n>/`; the Worker only reads keys it builds from the registry's `site_id` and a validated path (no `..`, no `_`, no dot files, whitelisted extensions). |
| Secrets | Cloudflare token, R2 keys, service token are server environment only, never logged (errors are sanitized), never sent to the browser or put in the Worker repo. |
| Abuse of enquiries | Honeypot, rate limits, body size cap (8 KB at the Worker), consent required, token-authenticated relay. |
| Misleading claims | Clinic template cannot publish without its disclaimer; no ranking promises; no fake reviews feature. |

Headers on every site response: `Content-Security-Policy: default-src 'none'; script-src 'none'; style-src 'self'; img-src 'self'; font-src 'none'; connect-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` (camera, microphone, geolocation, payment off), COOP/CORP same-origin, HSTS. The CSP string is defined once in `hosting.py` and again in the Worker; a Worker test fails if they differ.

## Cookie and origin isolation (decision)

Production runs with `COOKIE_DOMAIN=.flowqr.site` so that `flowqr.site` (Vercel) and `api.flowqr.site` share a session. Any `<slug>.flowqr.site` would be a subdomain of that scope, so the **browser would attach the FlowQR session and CSRF cookies to every business website request**. This is acceptable only if no business site can run code or read them, so:

1. Published sites contain **no JavaScript** and the CSP forbids it (`script-src 'none'`, `connect-src 'none'`), no inline styles (the stylesheet is a same-origin file), no third-party anything. Content cannot add script (see Rendering).
2. The Worker **never reads, forwards or sets cookies**. The enquiry relay builds fresh headers.
3. **No CORS entry** is ever added for a business host; the API does not accept credentialed requests from them.
4. The session cookies are `HttpOnly`, so even a hypothetical injection could not read them.
5. A business-site `Set-Cookie` cannot be produced (no code path), so cookie tossing from a site into the app scope is not possible while 1 and 2 hold.

Because 1 and 2 are controls on code that FlowQR owns today, the backend config check **refuses to start in production with the sites base domain inside `COOKIE_DOMAIN`** unless `SITES_ACCEPT_SHARED_COOKIE_SCOPE=true` is set, which records that someone read this section.

**Recommendation:** use a **separate registrable domain** for business sites (not under `flowqr.site`) before shopkeepers can edit their own sites or any feature that adds scripts, embeds or custom CSS. Then the cookies are never sent to business sites at all. That needs one more domain (about the cost of a `.in`/`.com` registration) and the same Cloudflare setup, so the DNS plan below works for either.

## Tests

See the test run recorded in the final report. Files: `backend/tests/test_sites_content.py`, `test_sites_media.py`, `test_sites_hosting.py` (an in-memory fake of R2 and KV exercising failure injection and rollback), `test_sites_api.py` (authz, isolation, lifecycle, enquiries, export, deletion, disabled mode), the migration graph tests, `deploy/cloudflare/sites-worker/test/worker.test.mjs` (Worker routing, headers, hostnames, enquiry relay) and `frontend/tests/sites.test.mjs`.

## Local development

`SITES_PROVIDER=local` with `SITES_LOCAL_DIR` writes the same files and pointers a Worker would read. `deploy/cloudflare/sites-worker/dev-server.mjs` runs the **real Worker code** against that folder so a published site can be opened at `http://<slug>.sites.localhost:8787/` (browsers resolve `*.localhost`). Nothing in it talks to Cloudflare.

## Known limits (Phase 1)

- Custom customer domains are **not** implemented (they need Cloudflare for SaaS custom hostnames; paid beyond a free allowance; see the Cloudflare document). `site_domains` has the shape for it.
- No shopkeeper self-service editing; no analytics; no blog; no payments; no forms other than the one enquiry form.
- Enquiry notifications are off by default (inbox only).
- Google Business Profile is not written to by this feature.

## AI generation from onboarding (migration 0070, `SITES_AI_BUILDER_ENABLED`, default off)

A business that answers "No, I don't have a website" gets a **draft in this builder**: same `sites` row, templates, section catalogue, validator, renderer and publish path. There is no second builder or page format.

**Flow.** Onboarding: after the plan step, `/onboarding/website` (Google cannot be connected earlier: connecting needs an active plan). After onboarding: `/website`, with a line on Home. Connecting Google starts the build once, by itself, for a business that said it has no website.

**Job.** `site_generation_jobs` (forced RLS, one queued or running job per business), run by the Celery task `flowqr.build_website`. Twelve steps, each committed when it really finishes (`waiting | running | done | skipped | failed`); the screen polls every 1.5 s and the preview is fetched again only when more work is done. A job with no update for 6 minutes is reported as stopped. Two AI calls (plan, then copy) through the metered provider, so the platform spend cap applies.

**Truth rules** (code, `services/sites/generator.py`): services only from the Business Brain or Google; prices, offers, team, qualifications, testimonials, FAQs, menus and galleries are never generated; claim words (best, awards, years, guarantees, prices) and business-rule breaks are replaced with plain wording and the owner is told.

**Owner actions** (`/api/v1/website/*`): preview (private, noindex, no-store), edit one section, AI edit limited to five operations (optionally to one section), change layout or colour, add a photo, build again (draft only), approve publishing.

**Publishing is not opened by this.** An owner draft has `commercial_status = not_activated`. Publishing needs `SITES_ENABLED`, working hosting, and an administrator recording the hosting add-on as complimentary or paid. Until then the owner's approval is only recorded (audit `site.publish_requested`).

**To switch on:** apply 0070, set `SITES_AI_BUILDER_ENABLED=true` (listed in `docker-compose.yml` and the VPS overlay), restart api, worker and beat. Rollback: set it false; downgrade 0070 only if the image is rolled back (it turns `not_activated` into `expired`).

**Not built:** multi-page sites (the builder renders one page plus privacy); custom domains; a reviews section; import of Google photos (FlowQR deliberately stores no Google photo links); typography choices (fixed per template); administrator notification of a publish request beyond the audit record.

**Tested:** `backend/tests/test_website_generation.py` (14), `frontend/tests/website.test.mjs`, `e2e/website-onboarding.js` (26 checks at 1440, 320, 360, 375, 390, 414 px). The AI and Google are test doubles in all of them: no real model output and no real Google data has been tested.
