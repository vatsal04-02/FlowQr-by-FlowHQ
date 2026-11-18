# Launch readiness checklist (privacy and account lifecycle)

Status date: 2026-11-18. Source of detail: [PRIVACY_COMPLIANCE_AUDIT.md](PRIVACY_COMPLIANCE_AUDIT.md). All code changes named here are in the working tree only: **nothing is committed, pushed or deployed**, production is untouched, the worker and beat are stopped, the emergency stop is on, and autonomy and automatic replies are off.

**Two items are UNRESOLVED and block a controlled launch with real customers' Google data until evidence exists:** (1) Google's content-storage and retention rules, and (2) the data-use terms of the Gemini key. Nothing in this repository resolves either, and nothing here claims to.

## 1. Technically complete (built, tested in the working tree, not deployed)

| # | Item | How it behaves | Evidence |
|---|---|---|---|
| T1 | 18+ declaration at sign-up | Unticked box (English only; the AI notice on customer pages stays bilingual); the server refuses password sign-up without it and refuses a brand-new Google account without it; stores a timestamp and a wording version; no date of birth; existing users stay "unknown" | `tests/test_privacy_lifecycle.py` (A), `frontend/tests/privacy-ui.test.mjs` |
| T2 | Delete my own account | Typed email + password (or a very recent sign-in for Google-only accounts) -> emailed single-use link (24 h) -> sign-out everywhere -> 14-day cancellable grace -> anonymised by the hourly job; never deletes a business; blocked for a sole owner and for platform admins; revokes the Google grants the person made; cancels their still-queued posts and photos; removes their IP from audit entries | same file (B) |
| T3 | Lifecycle emails | Export downloaded; business deletion requested and completed; personal deletion requested (the link), completed, and "could not be completed". No data in any email; outcome-only audit entries; no duplicates | same file (C) |
| T4 | Retention jobs (provisional) | Ended sessions 30 d, reset tokens 30 d, audit-log IPs 12 months (IP only), demo leads 12 months. **Off until `PRIVACY_RETENTION_ENABLED=true`**; dry-run report command; repeatable; per-step failure isolation | same file (D) |
| T5 | AI notice for customers | Owner's exact English/Hindi wording, before any text can be sent for AI help, on both customer pages, only when AI help is offered | `privacy-ui.test.mjs` |
| T6 | Gemini safeguard (interim) | Review data is **not** sent to Gemini unless `GEMINI_DATA_TERMS_VERIFIED=true`; `AI_REVIEW_DATA_KILL_SWITCH=true` stops all providers; reviewer name never sent; emails, phone numbers and links masked; customer pages hide AI help while blocked | same file (E/3) |
| T7 | Refund page | No placeholder presented as policy: says plainly that it is not published yet, invents no terms, not indexed | `privacy-ui.test.mjs` |
| T8 | Export completeness | 21 more tables exported; a test fails when a new tenant table is added without being exported | `tests/test_account_lifecycle.py` |
| T9 | Fonts self-hosted; demo form not pre-ticked | No request to Google's font servers (checked in the build output) | build + audit §4 |
| T10 | Earlier consent work (Milestone 2) | Preserved, untouched, still passing | `tests/test_consent.py` |

## 2. Owner approval or action required

| # | Needed | Why it is the owner's | Where |
|---|---|---|---|
| O1 | **Provide written evidence** that the Gemini key's terms do not allow the provider to train on or retain prompts, then set `GEMINI_DATA_TERMS_VERIFIED=true` | Until then review AI is off in production by default. Setting it is the owner's statement, not a fix | audit §9 |
| O2 | Approve the **deployment sequence** (migration 0039, env settings, order) | Production change | audit §14 |
| O3 | After the dry-run report, **switch retention on** (`PRIVACY_RETENTION_ENABLED=true`) and confirm the four periods as final | Destructive; periods are provisional | audit §8 (D) |
| O4 | Decide whether the AI notice stays a notice or becomes an explicit consent step | The lawyer's answer decides; code can add a checkbox either way | audit §8 (E) |
| O5 | Verify on the VPS that **no container other than Caddy can reach the API port**, then restrict `--forwarded-allow-ips` | A shared host: other containers can reach `172.17.0.1:18000` and could forge `X-Forwarded-For` | audit §11 |
| O6 | Decide whether to stop writing email addresses into audit metadata for admin actions (use a hash, as the registration gate already does) | The audit trail is append-only, so existing entries keep them | audit §11 |
| O7 | Approve building the **content-reporting** tables and admin screen (design is in the audit) after the lawyer decides the process | Needs a process the owner and lawyer define | audit §12 |
| O8 | Google retention route (written clarification, legal advice, or redesign) and which option per data type | Unresolved launch blocker D3 | audit §10 |
| O9 | The other Milestone 2 decisions still open: real-write test sequence (D5), revoking the two clinic tokens at Google, production OAuth checks (D7), paid Places lookups (D6) | Real customer data or money | `GOOGLE_READINESS_M2.md` |
| O10 | Fill the business facts the drafts need: legal name, address, support, privacy and security emails, backup retention, processor names | Only the owner knows them | `PRIVACY_POLICY_DRAFT.md` |

## 3. Legal approval or external confirmation required

| # | Needed | Status |
|---|---|---|
| L1 | **Google content storage and retention** (30-day wording, whether reviews and metrics for a sync product are covered, Limited Use scope for `business.manage`, Places Service Specific Terms, disconnect deletion) | **UNRESOLVED. No evidence. No retention rule has been invented for Google data.** |
| L2 | **Gemini data-use confirmation** (tier, training, retention for the key in use) | **UNRESOLVED. No evidence.** Interim safeguard in place (T6) |
| L3 | Privacy policy wording and lawful basis per purpose (India DPDP, EU/UK if targeted) | Draft only; not published |
| L4 | Refund and cancellation policy text | Not written |
| L5 | Terms of service: add the 18+ statement; check the cancellation wording | Not changed |
| L6 | Breach duties, deadlines and regulator wording | Draft runbook with placeholders |
| L7 | Grievance officer, takedown and report-content process; legal response times | Nothing invented |
| L8 | Children: whether the daily hashed visitor code on public review pages is "tracking"; whether the 18+ declaration is enough | Open |
| L9 | Whether records that survive deletion are acceptable: audit entries (without IP after the period), anonymised user tombstones, scan counts, usage counters, **email addresses inside admin audit metadata** | Open |
| L10 | The provisional retention periods | Pending review; described as settings, never as compliance |
| L11 | Processor agreements and international transfers (Google, Gemini, Cashfree, email, hosting) | Open |
