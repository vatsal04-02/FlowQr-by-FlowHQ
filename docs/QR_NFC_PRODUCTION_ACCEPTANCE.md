# QR / NFC production acceptance and print-readiness audit

Audited 2026-11-18. First audit: production `prod-0dd82fd`. **Updated the same day (section 16):** production is now `prod-048b797` (migration 0045), the two fixes are deployed, DNS for `go.flowqr.site` is verified, and the Caddy block is validated but **not yet applied** (blocked on file permission).
**Recommendation: NOT READY TO PRINT** until the Caddy block is applied, `PUBLIC_CARD_BASE_URL` is switched and the controlled physical test passes (section 15 and 16).

## 1. Architecture overview

```
printed QR  ->  https://flowqr.site/q/<code>
NFC tag     ->  https://flowqr.site/n/<code>        (same <code>, door letter n)
older cards ->  https://flowqr.site/c/<code>

TODAY (measured on production):
phone -> flowqr.site (Vercel)  --308-->  www.flowqr.site/q/<code> (Vercel, HTML + JavaScript)
      -> browser runs JS -> GET api.flowqr.site/api/v1/public/c/<code>?channel=qr   (records the scan)
      -> API answers {state: ok | redirect | inactive ...}
      -> JS either shows the review page or does window.location.replace(destination)

NOT ON THE PRINT PATH: GET /api/v1/go/<code>  (a real HTTP 302). It exists and works but nothing printed points at it.
```

Consequences of the current path: it needs Vercel, JavaScript and the API all working; a scanner or browser without JavaScript sees an empty page (measured); the printed domain is the same host as the website, so moving the website moves the printed codes' address.

## 2. Database entities
`card_batches` -> `qr_cards` (public_token UNIQUE, card_code UNIQUE, status, tenant_id, location_id, campaign_id, label, qr_path, **destination_url, nfc_programmed_at**) -> `card_assignments` (history, one open row per card) -> `scan_events` (card, tenant, location, channel qr|nfc, is_bot, visitor_hash, **device, referrer_host, placement, campaign_id**) ; `card_destination_history` (append-only). Tenant tables are RLS-forced. Audit entries go to `audit_logs`.

## 3. Bulk generation
Platform admin only. 1 to 2000 per batch (422 outside). Each code is `secrets.token_urlsafe(18)`: 24 URL-safe characters, 144 bits, checked against the table before insert, with UNIQUE constraints on code and serial as the backstop. The whole batch is one transaction: a collision rolls back everything (tested: no batch and no cards remain). Initial state: `generated`, owned by nobody, no destination, `qr_path='q'`. **No rate limit on batch creation** (platform admin only; see findings).

## 4. Business assignment
Admin picks card(s), business, location, optional campaign/placement. Unknown or foreign business, location or campaign is refused and changes nothing. A card already in use cannot move without `confirm`, which names old and new; one open assignment per card; the old one is closed and kept; each assignment writes an audit entry. Bulk assignment is all-or-nothing.

## 5. Redirect lifecycle (as built)
1. Resolve the code (24-char alphabet only reaches the database; anything else is 404 without a query).
2. Unknown -> 404, not recorded, miss counter (30 per 5 minutes per address, then 429).
3. Stock / reserved / archived / paused / retired / deactivated / lost, or inactive business or location -> neutral notice, **never** the destination.
4. Live -> record scan (channel from the door, bot flag, 20-second same-door refresh filter), then destination if set, else the review page or campaign.
5. `/go/<code>` answers 302 with `Cache-Control: no-store`, `Referrer-Policy: no-referrer`; with no destination it sends the visitor to the app's landing page for the same door (`FRONTEND_URL/q|n|c/<code>`).
The destination comes only from the database. Nothing in the request path, query or headers can choose it (tested with hostile parameters and hosts).

## 6. QR / NFC parity
Same token, same card, same destination. The addresses differ only by door letter (`/q/` QR, `/n/` NFC): this is how attribution works, so no `?source=` is needed and the existing printed format is unchanged. The NFC programming panel shows the exact NFC address with a copy button. Status is `not programmed` -> `marked programmed` (admin's statement) -> `tap confirmed` (a real, non-bot NFC visit after marking). There is no API field that can set "verified": forged bodies are rejected (422). **Physical NFC tags were not tested (no hardware in this audit).**

## 7. Analytics
Recorded per event: card, business, location, campaign and placement at the time, channel (qr/nfc), timestamp, device class, referrer host only, bot flag. Totals separate QR scans, NFC taps, unique visitors (salted daily hash), automated visits (counted apart, excluded from totals). A scan never creates a review or a conversion event (tested: only `scan` rows). Output contains no hashes, IPs, user agents or referrer paths (tested). Businesses see only their own cards; admin analytics are platform-admin only (401 anonymous, 403 for businesses).

## 8. PDF and print specification
Poster: approved artwork, page 253.2 x 357.84 pt (about 89 x 126 mm), PNG 1055 x 1491 at 300 dpi (x2, x3 for large prints), A6/A5/A4 PDF, A4 sheets of four with crop marks and serial. Every poster is decoded with an independent decoder (ZXing) before it is ever served and is refused otherwise; at 1x, shrunk 3x and blurred. Existing tests also decode PNG, SVG and PDF at every size, phone-photo simulations and a 500-poster sheet; added here: addresses for `go.flowqr.site` and the apex decode at 2x/3x/4x reduction; 25 cards on a sheet decode to 25 distinct, correct addresses. **A physical print scanned by real phones was not done.**

## 9. Security findings
| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | **A card's destination survived a move to another business or return to stock**, so the next owner's customers could be sent to the previous owner's address. | High (once destinations are used) | **Fixed locally** (cleared and recorded on reassign, unassign, reserve); tests fail without the fix. **Not deployed.** |
| 2 | `/go` fallback pointed at the print domain; once `go.flowqr.site` fronts `/q` and `/n` it would redirect to itself forever. | High (for the planned domain) | **Fixed locally** (falls back to the app's landing page, same door). **Not deployed.** |
| 3 | Printed path depends on Vercel + JavaScript + an apex 308; non-JS clients see nothing. | Medium | Open: solved by the permanent domain (section 11). |
| 4 | No rate limit on batch creation. | Low (platform admin only, max 2000) | Open, recommended. |
| 5 | Access logs and audit rows contain card codes and destination URLs (codes are public identifiers; audit is admin-only). No query strings are logged by the app. | Info | Accepted. |
| 6 | The scanned code is also the lookup key: anyone holding the printed code can scan it. By design. Guessing is not feasible (144 bits) and is rate limited (30 misses / 5 min). | Info | Accepted. |
Checked and passing: open redirect (parameters, host headers, `//`, `javascript:`, encoded forms), SQL-injection-shaped and traversal paths, IDOR across businesses (view, edit, download, assign, retire), unauthorised destination and analytics access, forged NFC verification, https-only/IP/credential/port/self-address destination rules, the server never fetching destinations (no SSRF).

## 10. Production routing (measured, read-only)
`flowqr.site` A 216.198.79.1 (Vercel) -> 308 -> `www.flowqr.site` CNAME `...vercel-dns-017.com` (Vercel). `api.flowqr.site` A 201.18.202.128 (the VPS; the shared Caddy `gkp-final-build-caddy-1`, upstream 172.17.0.1:18000). TLS: Let's Encrypt, valid to 2027-02-13 (apex) and 2027-02-13 (api). On production: unknown code via `/q`, `/n`, `/c` -> 308 -> 200 page -> API 404 -> "Card not found"; `/api/v1/go/<unknown>` and traversal/garbage -> 404 `no-store`; admin analytics and prepaid offers anonymous -> 401.

## 11. Permanent domain `go.flowqr.site`
**Required, in this order (none done):**
1. DNS at GoDaddy (nameservers ns27/ns28.domaincontrol.com; no CAA record exists): `Type A | Host go | Points to 201.18.202.128 | TTL 3600`. Wait until it resolves.
2. Back up the shared Caddyfile (`/home/deploy/GKP-Final-Build/Caddyfile`), append the block below, `caddy validate`, then `caddy reload` (zero downtime; the same file serves the clinic apps).
3. Set `PUBLIC_CARD_BASE_URL=https://go.flowqr.site` only after step 2 works, so new batches and exports encode it. Keep `FRONTEND_URL` unchanged. Recreate api/worker/beat with both compose files.
4. Print only after the controlled test (section 14) passes on this domain.
```
go.flowqr.site {
	header { Strict-Transport-Security "max-age=31536000"; X-Content-Type-Options "nosniff"; Referrer-Policy "no-referrer"; Cache-Control "no-store"; -Server }
	@q path_regexp q ^/q/([A-Za-z0-9_-]{16,64})$
	@n path_regexp n ^/n/([A-Za-z0-9_-]{16,64})$
	@c path_regexp c ^/c/([A-Za-z0-9_-]{16,64})$
	handle @q { rewrite * /api/v1/go/{re.q.1}?channel=qr
		reverse_proxy 172.17.0.1:18000 { header_up X-Forwarded-For {remote_host} } }
	handle @n { rewrite * /api/v1/go/{re.n.1}?channel=nfc
		reverse_proxy 172.17.0.1:18000 { header_up X-Forwarded-For {remote_host} } }
	handle @c { rewrite * /api/v1/go/{re.c.1}
		reverse_proxy 172.17.0.1:18000 { header_up X-Forwarded-For {remote_host} } }
	handle { redir https://www.flowqr.site 302 }
}
```
**This block was run locally** with the real `caddy:2` image in front of the local API (plain HTTP, upstream swapped) and tested: `/q`, `/n`, `/c` with a destination -> 302 to it; without a destination or for stock -> 302 to the app landing page on the same door; unknown valid-shape code -> 404; `..%2f`, `%2e%2e/`, extra segments, `/`, `/api/v1/admin/...` -> 302 to the website (the API is not exposed through this host); `?channel=`, `?url=` and `?ref=` on the printed URL cannot change the recorded channel or the target. TLS issuance and the real hostname were not testable locally.
**Independence and limits.** This host does not touch Vercel: the website can move without affecting printed codes (only `FRONTEND_URL`, used for the no-destination landing page, changes). It still depends on the VPS and the shared Caddy being up, which is also true of the API today. `/q/<code>` on the apex keeps working in parallel for every code already printed. A reprint of an old batch will encode whatever `PUBLIC_CARD_BASE_URL` is at export time.

## 12. Automated test results
Local, real PostgreSQL, Cashfree/Google not involved, run on the working tree that contains the fixes (uncommitted).
- Full backend suite: **1896 passed, 2 skipped, 1 failed** (917 s). The failure is `test_seo_metrics.py::test_previous_period_comparison_uses_only_stored_days_and_leaves_google_lag_out`, a UTC-versus-India-date test that fails on the code production ran before this work too. The 2 skips are the same two skipped in every earlier full run (not investigated further in this audit).
- New: `tests/test_qr_acceptance.py` (51 tests) and 2 updated expectations in `tests/test_qr_assets.py`; together 104 passed. Removing the two fixes makes 6 of the new tests fail (verified), so they prove the bugs, not just the fixes.
- Frontend: typecheck clean, 33 tests passed (no frontend file changed in this audit).
- Local routing test of the proposed `go.flowqr.site` Caddy block with the real `caddy:2` image: 13 request shapes behaved as expected (section 11).

## 13. Production read-only results
API health 200; anonymous admin analytics 401; anonymous prepaid offers 401; unknown/garbage/traversal codes 404 `no-store`; `go.flowqr.site` does not resolve; TLS valid; browser visit to `flowqr.site/q/<unknown>` (read-only): JS on -> 308, 200, one API call (404), "Card not found"; JS off -> an empty page. Production database held 0 cards, 0 destinations, 0 NFC marks (checked after deploy). **Not done:** any live batch, assignment, scan, destination change, NFC tap or print.

## 14. Controlled production acceptance test (NOT executed: needs approval)
Preconditions: section 11 steps 1 to 3 done; the section 9 fixes deployed. Use the existing test business "Isolation Test Co" (a prior test tenant, not a customer) and destinations `https://example.org/flowqr-acceptance-a` / `-b`.
1. Generate a batch of 2 named `ZZ-ACCEPTANCE (test, do not print)`.
2. Assign card 1 to the test business and its location; leave card 2 in stock.
3. Set destination A on card 1; scan `https://go.flowqr.site/q/<code1>` from a phone: expect example.org A, one `qr` event.
4. Change to destination B (confirm); scan again: expect B, same printed code.
5. Scan card 2 (stock): expect the neutral "not set up" notice, never a destination.
6. Program one blank NFC tag with `https://go.flowqr.site/n/<code1>`; mark programmed; tap it: expect B, status `tap confirmed`, one `nfc` event.
7. Check analytics show 2+ qr and 1 nfc separately, none counted as reviews.
8. Pause card 1: expect the notice; resume; retire it: expect the notice permanently.
9. Cleanup: retire both cards (permanent, history kept), clear destinations, leave the test business untouched. No hard delete exists by design; the records remain labelled `ZZ-ACCEPTANCE`.

## 15. Rollback, recovery and readiness
Rollback of code: set `FLOWQR_TAG` to the previous image and recreate api/worker/beat with both compose files (0042 is additive; downgrade is tested). Backups: `/opt/flowqr/backups/pre-qr-assets-20261118015248.dump`. Recovery of a printed code: its address never changes; any destination can be changed or cleared; a card can be paused or retired. Removing the `go` Caddy block and DNS record returns to today's `flowqr.site/q` path, which keeps working throughout.

**NOT READY TO PRINT because:** (1) the two defects above are fixed only in the local working tree and are not deployed; (2) the permanent redirect domain does not exist yet and the current printed path depends on JavaScript and Vercel; (3) no live card has ever been generated, assigned, scanned or tapped on production; (4) a real NFC tag and a real printed card have not been scanned by real phones.

## 16. Configuration log, 2026-11-18 (after the audit)
**Production state differed from the brief.** The brief said `prod-0dd82fd`; another session had since released `prod-2c95397`, then `prod-4fbebec`, then `prod-d5829c1` (privacy and account lifecycle, consent, user picture; migrations 0043 to 0045). Nothing here was deployed from an older tree: the fixes were merged onto the live release tip and re-tested before shipping.
| Step | Result | Evidence |
|---|---|---|
| DNS | PASS | `go.flowqr.site` A 201.18.202.128 from 8.8.8.8, 1.1.1.1, 9.9.9.9, 208.67.222.222 and both GoDaddy nameservers; no AAAA, no CNAME; TTL 3600 |
| Backups | PASS | `/opt/flowqr/backups/pre-go-fixes-20261118124525.dump`, `env.production.pre-go-fixes-20261118124525`, `docker-compose.yml.pre-go-fixes-20261118124525`. The Caddyfile itself was **not** backed up (nothing changed it; the apply script backs it up in place) |
| Caddy block written and validated | PASS | `deploy/vps/Caddyfile.flowqr-go` (sha256 starts 22effe6fc2520675). Production Caddy v2.11.7, current Caddyfile + block: `caddy validate` exit 0, "Valid configuration"; live file checksum unchanged; temp files removed |
| Caddy block applied | **BLOCKED** | The Caddyfile is `/home/deploy/GKP-Final-Build/Caddyfile`, owned by `deploy`. The FlowQR deploy user has no access to that directory and no sudo; the sanctioned script refuses ("run this as the file's owner (deploy) or root"). Working around it through Docker's root access was not done without explicit approval |
| TLS for go.flowqr.site | NOT TESTED | Cannot be issued until the block is applied. Baseline today: :80 answers 308 to https, :443 has no site (TLS internal error, no certificate) |
| Existing certificates | PASS | www.flowqr.site and api.flowqr.site valid to Feb 2027 |
| `PUBLIC_CARD_BASE_URL` | NOT DONE (on purpose) | Stays `https://flowqr.site` until the domain answers, otherwise new codes would encode a dead address. Existing codes are unaffected either way (the per-code address never changes) |
| Two fixes deployed | PASS | `prod-048b797`, only the three app files differ from the live release (23 lines); api, worker, beat healthy; alembic 0045; API port 172.17.0.1:18000; public ready 200 |
| Test results on the deployed tree | PASS | Backend 1992 passed, 0 failed, 0 skipped; frontend typecheck clean, 40 tests passed |
| Production smoke (read-only) | PASS | website, login, pricing, admin shell 200; anonymous admin analytics, card list, prepaid offers 401; `/go` unknown, traversal, SQL-shaped and 200-character codes 404 with `Cache-Control: no-store`. Admin login and the inventory data pages were **not** exercised (no credentials used) |

**Known failure and skips, investigated.** `test_seo_metrics ... leaves_google_lag_out` builds "today" from the machine's UTC date while the application uses each business's timezone (Asia/Kolkata, UTC+5:30): the two dates differ between 18:30 and 24:00 UTC, which matches every failure seen (all in the evening, UTC) and it passed at 06:37 UTC. It is a test-only defect (not changed here). The two skips were `skipif(frontend not mounted)`; with `frontend/src` mounted both pass, and the final run mounted it.

**To finish the domain (needs the Caddyfile owner, `deploy` or root, or your explicit approval for another route):**
1. `bash /opt/flowqr/deploy/vps/apply-caddy-go.sh --dry-run`, then without `--dry-run` (the files are already staged in `/opt/flowqr/deploy/vps/`; it backs up the Caddyfile, appends in place, validates, reloads gracefully and restores itself if validation fails).
2. Check `https://go.flowqr.site/q/<unknown>` answers 404 over a valid certificate and `http://` redirects to https.
3. Only then set `PUBLIC_CARD_BASE_URL=https://go.flowqr.site` in `/opt/flowqr/.env.production` and recreate the api (the setting is read by the API; worker and beat do not render card addresses, but recreate them too to keep versions aligned).
**Rollback.** Caddy: `cat <printed .bak path> > /home/deploy/GKP-Final-Build/Caddyfile` (in place, never `mv`/`cp` over it) then `docker exec gkp-final-build-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile`. Backend: set `FLOWQR_TAG=prod-d5829c1` in `/opt/flowqr/.env.production` and `docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml up -d --no-deps api worker beat` (image still on the server; migrations are additive and stay). Environment: `/opt/flowqr/backups/env.production.pre-go-fixes-20261118124525`.

## Final acceptance table
| Area | Status | Evidence | Remaining action |
|---|---|---|---|
| Bulk generation | PASS | Local runtime tests: batches of 1, 10, 2000; 144-bit unique codes; DB UNIQUE; transactional rollback; limits | Production batch not created (by instruction); add a creation rate limit |
| Inventory | PASS | Local: filters, lifecycle, history, tenant isolation | Run in the controlled production test |
| Business assignment | PASS | Local: invalid/foreign ids refused, confirmation to move, one open assignment, audit; destination-clearing fix deployed in `prod-048b797` | Run in the controlled production test |
| Destination update | PASS | Local runtime tests incl. the reassign/stock/reserve clearing (fail without the fix); fix deployed | Verify on production in the controlled test |
| Redirect | BLOCKED | `/go` deployed and tested (loop fixed); the permanent host answers nothing over HTTPS until the Caddy block is applied; today's printed path is still apex 308 + JavaScript | Apply the Caddy block, then re-test over the real domain |
| QR/NFC parity | PASS | Local: same card and destination, door-letter attribution, forged verification rejected | Physical NFC tag test (row below) |
| NFC physical tag | NOT TESTED | No hardware used | Program and tap a real tag |
| Analytics | PASS | Local: QR/NFC/bot separated, no personal data, no review counted, access closed | Verify on production in the controlled test |
| PDF printing | PASS | Local: PNG/SVG/PDF decode to exact URL, reductions, 25-card sheet, page size | Scan a real printed card |
| Security | PASS | Local: open redirect, injection-shaped paths, IDOR, anonymous/foreign access, rate limits; findings 1 and 2 fixed and deployed | Accept or fix findings 3 and 4 |
| DNS go.flowqr.site | PASS | Four resolvers and both authoritative servers | none |
| Permanent domain (HTTPS, Caddy) | BLOCKED | Block validated against production Caddy; not applied (file owner `deploy`); no certificate yet | Section 16 steps 1 to 3 |

## 17. Switching `PUBLIC_CARD_BASE_URL` to `https://go.flowqr.site` (2026-11-18, attempted and rolled back)
Independently verified first (read-only): certificate for `go.flowqr.site` issued by Let's Encrypt (valid 2026-11-18 to 2027-02-16, chain verifies); `http` -> 308 to `https`; unknown `/q`, `/n`, `/c` -> 404 `no-store`; `/` and `/api/v1/admin/cards`, traversal and extra segments -> 302 to the website; `?channel=` and `?url=` on a code do not change the result; `www` and `api` certificates unchanged.

| Check | Result | Evidence |
|---|---|---|
| Env backup | PASS | `/opt/flowqr/backups/env.production.pre-go-base-20261118130147` (mode 600) |
| Value set, only that line changed | PASS | every other env line identical to the backup |
| Only the API recreated (worker and beat do not render card addresses) | PASS | api healthy on `prod-048b797`, worker/beat untouched and healthy, port 172.17.0.1:18000 |
| Application reads the setting | PASS | running container: base `https://go.flowqr.site`, `permanent_url_problem` None, config guard clean |
| QR / NFC / old-door addresses | PASS | `go.flowqr.site/q/<code>`, `/n/<code>`, `/c/<code>`; posters for both decode to the exact address |
| Existing cards, assignments, destinations, events | PASS | all five tables empty before and after (nothing existed to change); subscriptions, prepaid orders, payments fingerprints captured, no writes performed |
| Safety settings | PASS | emergency stop true, prepaid on, billing provider unchanged |
| **Campaign addresses** | **FAIL** | the same setting also builds campaign links (`campaign_url`), which came out as `https://go.flowqr.site/r/<id>`; that host serves only `/q`, `/n`, `/c` and sends everything else to the home page (verified: 302 to `www.flowqr.site`). Production has 2 active campaigns, so every new campaign link, QR download, poster and message link would have been dead |
**Action taken:** because a printed campaign code cannot be recalled, the value was restored from the backup the same hour (file byte-identical to the backup; api recreated; campaign addresses confirmed back to `https://flowqr.site/r/...`). No campaign link was produced in the window (no campaign API traffic in the log).
**Fix prepared, not deployed:** `campaign_url` now follows `FRONTEND_URL` (the website serves `/r/`), identical to the old address while the two settings match, and the poster print gate judges the address actually encoded. New tests `tests/test_campaign_address.py`; campaign, poster, QR, inventory and card suites: 282 passed. Existing printed campaign codes (`flowqr.site/r/...`) are unaffected in either state.
**To complete the switch:** deploy that fix, then set `PUBLIC_CARD_BASE_URL=https://go.flowqr.site` again and recreate only the api (the same steps), then re-run the checks above plus: a campaign address is still `https://flowqr.site/r/...`. Rollback is the backup file above plus `docker compose ... up -d --no-deps api`.
