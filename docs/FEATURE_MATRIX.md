# Feature matrix: what exists, what is partial, what is missing

Audit date 2026-11-12. Written from the repository as it stands in the working tree (including uncommitted work). "Verified" means a test or a live check was run; "Built" means code exists and is covered by tests; **Mocked** means only a fake provider or mock HTTP transport was used; **Blocked** names an external dependency. Nothing here is a claim about live Google, Meta, WhatsApp or Razorpay behaviour unless it says **Live**.

Legend: ✅ built and tested · 🟡 partial · ⬜ missing

## 1. Navigation and shell

| Roadmap item | State | Where | Notes |
|---|---|---|---|
| Sidebar with groups | 🟡 | `frontend/src/components/AppShell.tsx` | 5 flat groups (Reputation, Cards, Review Growth, Business). Two entries called "Overview" and two "Analytics"; the sidebar has its own inner scroll. Not the 8 expandable groups in the roadmap. |
| Breadcrumbs, location selector | ⬜ | | Back-links exist on a few detail pages only. No global location selector. |
| Old URLs keep working after a rename | ⬜ | | No redirect layer yet (needed before Phase 1 moves anything). |
| Loading/empty/error/disconnected states | 🟡 | per page | Present on most pages (Skeleton, Alert). Google pages have distinct API-disabled / awaiting-approval / reconnect states. |
| Trial and inactive-subscription banners | ✅ | `AppShell.tsx:73-75` | "Subscription inactive: your data is safe" and a banner at 5 days or fewer. |

## 2. Google Business

| Roadmap item | State | Where | Notes |
|---|---|---|---|
| OAuth connect, token encryption, reconnect, revoke | ✅ **Mocked** + live token refresh | `api/v1/google.py`, `services/google/tokens.py` | Real client configured. Token refresh verified live 2026-11-10. Browser consent flow not completed since the client was replaced. |
| Zero-location account is not a "connected business" | 🟡 | `api/v1/google.py:discover_locations`, `app/(app)/google/page.tsx` | Connection with no locations shows "No Business Profile locations were found", but the connection status is still "pending_selection", and there is no explicit **Connect another account** call-to-action beside that message. Roadmap rule 7. |
| Profile Manager (read, edit info/hours/categories/phone/website) | ✅ Mocked | `api/v1/gbp.py`, `app/(app)/profile/page.tsx` | Edits are direct and audited. **No AI suggestion step, no completeness score, no services/attributes/address editing.** |
| Reviews: sync, inbox, filters, AI reply drafts, approve, publish, retry | ✅ Mocked | `services/google/sync.py`, `api/v1/reviews.py`, `services/reviews.py` | Reply is published only after Google confirms and Google's `PENDING/REJECTED` state is honoured. Filters: rating, reply state, location, text search. **Missing:** date filter, sentiment/topic tags per review (analytics has aggregate topics only), automation policies. |
| Posts: create, edit, delete | ✅ Mocked | `api/v1/gbp.py` posts routes | Publishes immediately. **No AI drafts, no approval step, no scheduler, no calendar, no failure diagnostics/history.** Google does not schedule posts for us; this needs our own Celery scheduler. |
| Photos and media | 🟡 Mocked | `api/v1/gbp.py` media routes | Add by URL, list, delete. **No file upload** (Google needs a public URL or an upload reference), no processing status. |
| Performance | ✅ Mocked | `api/v1/gbp.py:performance` | Totals and daily series for the current metric list. **No location comparison, no CSV/PDF export, no "last synced" stamp.** |
| Local Visibility (rank provider) | ⬜ | | Nothing built. |
| Quotas, retries, token refresh, revoked access | ✅ | `services/google/sync.py`, `provider.py` | 10 edits/min/location enforced locally; backoff on 429/5xx. |
| **Live read/write against Google** | **Blocked** | | All four Business Profile APIs returned HTTP 403 `SERVICE_DISABLED` on 2026-11-10 for the previous project. No Business Profile call has ever succeeded. See `GOOGLE_API_AUDIT.md`. |

## 3. AI Growth Agent

| Roadmap item | State | Where | Notes |
|---|---|---|---|
| Business Knowledge Base | 🟡 | `ContextIn` in `schemas/review_growth.py`, `services/review_suggestions.py`, page `review-growth/settings` | Holds description (600 chars), up to 30 services, languages, disabled topics. **Missing:** verified prices/offers, hours, FAQs, brand voice, approved and prohibited claims, Hinglish. Used by the review generator; **not** by reply drafting. |
| Healthcare safety defaults | 🟡 | `services/ai/replies.py`, `services/review_generate.py` | Reply drafts flag medical/legal/refund content for human handling (`assess_review`). **No seeded "prohibited claims" list**, and no rule against confirming someone is a patient. |
| Business Health Score | ⬜ | | |
| Daily AI Plan, task cards, approve/edit/snooze | ⬜ | | |
| Action state machine | 🟡 | `ReplyStatus` in `models/business.py` | Exists for replies only (draft → approved → published / failed / rejected). Not generalised to posts, profile changes or agent tasks. |
| Agent Activity (jobs, approvals, retries) | 🟡 | Celery beat in `workers/celery_app.py`; admin AI usage | Jobs run (4 scheduled tasks); no tenant-facing job/approval view. |
| AI usage metering and limits | ✅ | `services/ai_usage.py`, `AIGenerationLog` | Per-plan monthly limit; "27 / 1,000" appears on the generator page. |
| Audit record for every AI action | 🟡 | `services/audit.py`, `AIGenerationLog` | Generation, approval and publish are logged. Not every future agent action exists yet. |

## 4. Content Studio, WhatsApp, Leads (Releases 2 and 3)

| Item | State |
|---|---|
| Captions, festival campaigns, brand kit, asset library, calendar, image generation | ⬜ |
| Facebook/Instagram publishing (Meta) | ⬜ |
| WhatsApp Business Platform, templates, consent, leads, appointments, follow-ups | ⬜ |

None of the Setup-required placeholders exist yet. No code in these areas exists; none can be tested without Meta/WhatsApp credentials.

## 5. Review Growth, QR, cards

| Item | State | Where |
|---|---|---|
| QR campaigns, customer page, AI review assistant, fact-check pass, user edits and posts it themselves | ✅ | `api/v1/review_growth.py`, `review_public.py`, `services/ai/review_generate.py` |
| No gating by rating, no auto-posting | ✅ | tests in `test_review_growth.py` |
| Cards/NFC, assign, pause, resume, deactivate, lost | ✅ | `api/v1/cards.py` |
| QR permanence (edits and new codes never invalidate printed codes) | ✅ | `docs/QR_RELIABILITY.md` |
| QR design, PNG/SVG/PDF, bulk export | ✅ | `api/v1/qr.py`, `services/qr_style.py` |
| Location-level staff permissions | ✅ | `core/deps.py`, `tests/test_location_permissions.py` |
| Review analytics and funnel | ✅ | `services/review_growth.py` |

## 6. Settings, billing, security

| Item | State | Where / notes |
|---|---|---|
| Plans, trial, entitlements | ✅ | `services/entitlements.py` |
| Checkout, verify, cancel, change plan, webhooks, idempotency | ✅ **Mocked** | `api/v1/billing.py`, `services/billing.py`. **Live Razorpay: Blocked.** `RAZORPAY_KEY_ID/SECRET/WEBHOOK_SECRET` are empty in the local `.env`, so checkout returns HTTP 503 `billing_config_pending` and the Subscription page says so. |
| Trial expiry keeps data and billing reachable | ✅ | `tests/test_trial_expiry_safety.py` (added in this phase) |
| Invoices | 🟡 | Payment history only; no tax invoices (GST). |
| Failed payment, cancellation | ✅ Mocked | |
| Staff, roles, location access | ✅ | |
| Audit log (admin-only view) | 🟡 | Written everywhere; tenant owners can't see their own log. |
| Data export | ⬜ | No endpoint or page. |
| Account deletion | ⬜ | No endpoint or page. |
| Privacy policy, terms, deletion-URL pages | ⬜ | None under `frontend/src/app`. Required for Google OAuth verification. |
| Reports with PDF/CSV export | ⬜ | Only on-screen analytics. |
| Overview with health score and today's plan | 🟡 | `app/(app)/dashboard/page.tsx` has reviews, scans, sync status. No score or plan. |
| Production env example, health checks | ✅ | `.env.example`, `docker-compose.yml`, `deploy/` |
| Error-monitoring hooks | ⬜ | None (no Sentry-style integration). |

## Defects found in the audit, ranked

| # | Severity | Finding | State |
|---|---|---|---|
| 1 | **Launch-blocking, external** | Checkout cannot complete: Razorpay keys are not configured. The UI already says so honestly; nothing can be fixed in code. | Needs the owner to add keys (see below). |
| 2 | High (verified safe) | Does trial expiry delete or lock data? **No.** `refresh_statuses` only flips status to `expired`; no rows are deleted, reads and downloads keep working, printed QR codes keep working, only writes and AI return 402 with a reason. | Covered by `test_trial_expiry_safety.py`. |
| 3 | High | No privacy policy / terms / deletion pages, no data export, no account deletion. Blocks Google OAuth verification and is a privacy-law exposure for a live customer. | Open (Phase 4). |
| 4 | Medium | Zero-location Google account is treated as a connection in `pending_selection`, not as an explanation plus "Connect another account" (roadmap rule 7). | Open (Phase 2). |
| 5 | Medium | Reply drafting does not use the Knowledge Base and has no prohibited-claims list; a drafted clinic reply could mention treatment. The "human handling" flag reduces but does not remove that risk. | Open (Phase 3). |
| 6 | Medium | Posts publish immediately, with no approval step or scheduler. | Open (Phase 2). |
| 7 | Low | Duplicate "Overview"/"Analytics" entries; inner sidebar scroll. | Open (Phase 1). |
| 8 | Low | Tenant owners cannot view their own audit log. | Open (Phase 4). |
| 9 | Info | ZBar fails at 40-50° rotation on non-black codes, including the existing default colour. | `QR_RELIABILITY.md`; product decision. |

## What is blocked on the owner

* Razorpay keys and webhook secret (checkout).
* Google: enable the Business Profile APIs on the project, access application, a verified location.
* Meta, WhatsApp, rank-provider credentials (Releases 2 and 3).

---

# After the growth-platform work (2026-11-12)

The tables above are the audit taken **before** this work and are kept as the baseline. Status now, by area. "Mocked" = tested against a fake Google/AI; **live Google READ calls are verified; live WRITES are not** (see `LAUNCH_REPORT.md`).

| Area | Before | After | Notes |
|---|---|---|---|
| Navigation | 🟡 flat, duplicate names | ✅ | 8 expandable groups, breadcrumbs, location picker (new pages only), every old URL still opens |
| Zero-location Google account | 🟡 | ✅ Mocked | Explained, offers "Connect another account", never shown as connected |
| Profile Manager | 🟡 | 🟡 | Completeness score and AI description draft with approval; no AI suggestions for hours/categories |
| Reviews | ✅ | 🟡→✅ | Replies grounded in the knowledge base with a safety re-check. **Still missing:** date/sentiment/topic filters; review-automation policies beyond auto-draft |
| Posts | 🟡 | ✅ Mocked | Draft → approval → scheduled → Celery publish; calendar; failures kept with reason; "published" only after Google confirms |
| Photos | 🟡 | 🟡 | Still by URL. **No file upload** |
| Performance | ✅ | ✅ | Unchanged; shown in reports |
| Local Visibility | ⬜ | 🟡 | Page + "Setup required" (no rank provider). No fake data |
| Knowledge Base + healthcare defaults | 🟡 | ✅ | Seeded prohibited claims; deterministic checker blocks invented prices/offers, appointment and health claims |
| Health Score | ⬜ | ✅ | Formula shown; unavailable measures are left out, not counted as zero |
| Daily Plan, approve/snooze/dismiss | ⬜ | ✅ | Built from real data only |
| Action state machine, Agent Activity | 🟡 | ✅ | Append-only events; tenant-facing activity, failed posts |
| Reports | 🟡 | ✅ | PDF + CSV (reviews, posts, tasks, AI), formula-injection-safe |
| Privacy / Terms / Data deletion pages | ⬜ | 🟡 | Written, **not legally reviewed**; support email unset |
| Data export / account deletion | ⬜ | ✅ Mocked | ZIP without secrets; grace period; cancel; cards returned to inventory |
| Audit log (tenant) | 🟡 | ✅ | Settings → Audit log, filterable |
| Content Studio, Inbox/Leads, Meta, WhatsApp | ⬜ | 🟡 | Structure + honest "Setup required". **No functionality**; needs Meta/WhatsApp credentials |
| Auto-publish | n/a | ⬜ by design | Disabled; owner approval is always required |
| Plan gating for agent, GST invoices, error monitoring | ⬜ | ⬜ | Not built |
