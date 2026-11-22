# Local SEO engine V2: what was built

Branch `feature/local-seo-engine-v2` (from `origin/release/gbp-agency` @ `0604555`), migration **0066**. Not pushed, not deployed. No upstream is set on the branch, so an accidental `git push` fails.

**Status in one line:** the detect, recommend, approve, validate, execute, verify architecture is built and passes its mocked tests. **Nothing has been run against a real Google test profile**, and customer writes are **gated closed** until Google answers in writing. Do not call any of this production-ready for customers.

## 1. Design: extend, do not duplicate

There is still one engine. V2 plugs into `seo_engine.scan_tenant` (the existing 6-hourly `autonomy_scan`), `executor.propose/decide/execute/recover_stuck`, `autonomy_policy`, `consent`, the history hash chain and `agent_actions`. New code lives in `backend/app/services/agent/v2/`:

| Module | Job |
|---|---|
| `fields.py` | Canonical forms, Google's stated limits and Google<->FlowQR converters for services, special hours, attributes, service area, category sets. Pure. |
| `discovery.py` | Pure assessment/drafting: service plan, category evidence, unanswered attributes, hours problems/comparison, holiday gaps, service area, contacts. |
| `keywords.py` | Local search opportunities from verified services, business type, places, Google's own search terms and review mentions. No invented volume or difficulty. |
| `catalog.py` | Google reference data for a profile (service types, attribute metadata, category candidates, `getGoogleUpdated` masks), stored in the snapshot so the scan makes no Google call. |
| `scan.py` | Per-location V2 scan: advisory lock, reconcile stale drafts, Google-change detection, evidenced proposals. |
| `field_ops.py` | The only place that knows how each field is read, dry-run and written. The executor has no per-field branches. |
| `gate.py` | The Google policy gate. |
| `owner.py` | Owner-entered changes (holiday hours, attribute answers, services, service area) as proposals. |
| `overview.py`, `present.py` | Dashboard data and plain-language BEFORE/AFTER. |
| `notice.py` | The separate notice after a verified customer-visible change. |

## 2. Lifecycle (the unified action system)

Requested: DETECTED -> RECOMMENDED -> APPROVAL_REQUIRED -> APPROVED -> VALIDATED -> EXECUTING -> VERIFIED, plus REJECTED, FAILED, BLOCKED, EXPIRED, SUPERSEDED. Mapping onto `agent_actions` (no new table, so no new RLS/export/deletion entry):

| Requested | Stored as |
|---|---|
| DETECTED | an area state on the dashboard (`overview.areas`), not a row |
| RECOMMENDED | `status = recommended` (new): drafted, shown, **not executable** (gate closed) |
| APPROVAL_REQUIRED | `pending_approval` |
| APPROVED | `approved` + an `agent_action_approvals` row (who, role, exact scope hash, expiry) |
| VALIDATED | `validation_status = validated`, `validation` JSON, history event `validated` (new columns) |
| EXECUTING | `executing` (claim committed before Google is touched) |
| VERIFIED | `executed` with `verified_at` set only after an independent read-back matched |
| FAILED / BLOCKED / REJECTED / EXPIRED | existing statuses; a Google dry-run refusal is `blocked` (`validation_failed`), not a write failure |
| SUPERSEDED | `superseded` (new): the profile changed under a draft |

Idempotency: the existing partial unique index now also covers `recommended`. One `executing` write per location+field (existing index). A V2 scan takes `pg_try_advisory_xact_lock` per location, so two simultaneous scans cannot both propose.

## 3. What each field does

| Field | Detected | Drafted | Written | Approval | Notes |
|---|---|---|---|---|---|
| Description | yes (existing) | yes (existing, improved evidence) | yes (existing) | Level 1, policy/consent as before | Unchanged path; not held by the V2 gate. |
| Categories | candidates from Google's category search on the owner's own words | additional categories only, max 3 per run, cap 9, each traced to a verified service/business type; primary kept | as a **set** (primary+additional together) | **Owner only** (Level 3); a primary change or removal escalates | Competitor categories are accepted as supporting evidence but **nothing stores them yet**, so none is supplied. |
| Services | complete list vs Business Brain; `canModifyServiceList` read | **complete** list = current + verified missing; predefined (structured) when a name matches Google's service types for the category, else custom (needs the primary category) | complete list via `serviceItems` | Level 2, person each time (never pre-authorised); dropping any service escalates to owner | Locked or unknown eligibility -> no proposal, area says "Google does not allow this through FlowQR". An unread list is "unknown", never "empty". |
| Regular hours | missing, overlaps, close-before-open, comparison with hours the owner wrote when every clause parses exactly (never guessed) | corrected schedule only for an exact comparison | existing write, now supports split periods, after-midnight (`HH:MM+1`) and `24:00` | Level 2 as before | Closed day = no entry. Timezone is not modelled; times are the profile's local times as Google holds them. |
| Special hours | fixed-date Indian public holidays in the next 60 days without an entry; movable festivals deliberately not listed | only from dates the owner enters | complete list under `specialHours` | Level 2 person; changing/dropping a future entry escalates to owner | Existing future entries kept; a clashing date is a conflict the owner resolves, never an overwrite. Needs regular hours first. |
| Attributes | which of Google's attributes for this business are unanswered | **never**: it asks (Yes/No in the UI) | `updateAttributes` with an explicit `attributeMask`, only changed attributes | Level 2 person; removal escalates | Types come from Google's metadata, not the request. Deprecated or not-offered attributes refused. |
| Service area | kind (storefront / area business), missing areas | only areas the owner names | `serviceArea` | **Owner only** (Level 3) | Never widened to chase searches; type/region changes refused. |
| Phone / website | missing vs record; **differs** from record | fill or a replacement | existing | missing->fill Level 2; replacing a working value Level 3 | A value that fails validation in the record is never preferred. |
| Business name | warning only (existing) | never | never | n/a | `business_name_change` stays `writable=False`. |
| Posts / photos / review replies | existing checks/flows | existing | existing | person each time | **Not extended in V2** beyond what existed: no new topic or photo-category suggester was built. |
| Search opportunities | service+place, type+place, "near me", Google's own terms, review mentions | n/a | n/a | the owner presses Track | Scored on relevance, intent, geography, coverage gap, evidence; Places position is never called a Maps rank. |

Risk mapping vs the brief: low = description/spelling; medium = services, attributes, regular and special hours, additional categories; high = primary category, name, replacing contact details, service area, any removal.

## 4. Validation, execution, verification

1. `propose` classifies by code, validates evidence (every new service/category must trace to a service or business type in the owner's Business Brain; attributes/special hours/areas only from owner input), fingerprints the live value.
2. `decide` re-checks the profile and facts at approval; a stale one is `invalidated`.
3. `execute` repeats every check, then for V2 fields runs the **dry run** (`validateOnly` for location fields; attribute metadata for attributes) **before claiming**. Google's 400 = `blocked` (not counted toward failure suspension); transient errors retry with backoff; a provider with no dry run **cannot** write a V2 field.
4. Claim, write (complete list for services/special hours), then an independent read-back compared to the canonical value. A write Google accepts but the profile does not show is `failed`, never success. Interrupted writes are resolved by reading Google (`recover_stuck`), never by writing again.
5. Only after verification: ranking follow-ups (rank-relevant types) and the **separate notice** email to the approver (and an audit row). Notice states what changed, links the record, says FlowQR never reverts by itself, how to disconnect.

## 5. The Google policy gate

`SEO_V2_CUSTOMER_WRITES_ENABLED` (default **false**), `SEO_V2_POLICY_REFERENCE`, `SEO_V2_TEST_LOCATION_NAMES`. With the gate closed for a profile, V2 still detects and drafts, the action is `recommended`, an approval click returns 409 with the reason, nothing is dry-run or written with a customer token, and an action forced to `approved` is **held** by the executor. The gate opens only for a dedicated test profile named by an operator, or (non-test) when the switch is on **and** a policy reference is recorded; production refuses to start with the switch on and no reference, or a reference without the switch. Nothing disables existing owner OAuth or connections; the legacy description/contact path is not held by the gate.

## 6. Dashboard

`/seo` (GBP > Overview) gets "Fix your profile" (`OptimizationCenter`), fed by `GET /seo/v2/overview`: issue/fix/pending/verified/failed counts, area-by-area state with how each fix is made (`automatic`, `owner_approved`, `recommended_only`, `owner_input_needed`, `unavailable_via_api`, `edit_in_google`), BEFORE -> AFTER for every drafted change with added/removed, pending approvals (existing approve/reject card), failed and blocked, recent verified changes, Google-changed fields, holiday/service/attribute input forms, search ideas with a Track button, 28-day customer actions vs the previous 28. Health score comes from the existing health formula and shows "–" when there is not enough real data. No placeholder numbers: when a profile has not been read the card says so.

## 7. Continuous scan behaviour

Eligibility/consent and the gate are checked per proposal; a rejected exact change is not re-proposed for 180 days, a different one is suppressed 14 days; failures pause a type; a change the owner or Google already made supersedes the draft (`reconcile`); fields in Google's `diffMask` are not proposed over and never reverted; the scan runs in a savepoint so it cannot break the original scan. The scan uses the stored snapshot (which now carries V2 reads) and makes no Google call.

## 8. What changed outside `v2/`

`autonomy_policy.py` (new types, V2 canon/validation/escalations, `WRITABLE_FIELDS`), `executor.py` (generic field ops, dry run, gate hold, `recommended`/`superseded`, notice), `provider.py` (`build_location_patch` shared by write and dry run; new reads/writes; after-midnight hours), `snapshots.py` (V2 reads, never costing the snapshot), `seo_engine.py` (calls the V2 scan), `readiness.py` (V2 dry-run probes), `config.py` (three settings + start-up checks), `models/autonomy.py`, migration `0066`, `main.py`, `route_access_manifest.txt` (five new routes), `test_phase1_policy.py` (pinned table updated: attribute_change is now Level 2 per the requested risk model), frontend `autonomy.ts`, `seo/page.tsx`, new `seo-v2.ts` and `OptimizationCenter.tsx`.

`service_update` and `attribute_change` changed meaning: `service_update` was Level 2, non-writable, grantable; now Level 2, writable, **person-only** (cannot be consented/pre-authorised). `attribute_change` moved from Level 3 non-writable to Level 2 person-only. `category_set_update` is new, Level 3.

## 9. Not done (honest list)

* No live run against any Google profile (no dedicated test profile/credentials were used). The `google-readiness` tool now has V2 dry-run/read probes, **unrun**.
* No special handling of timezones or daylight saving; no per-profile region (India is assumed for category/attribute reads).
* No offer/event posts, no new post-topic or photo-category suggestions, no review-reply changes.
* No undo/revert (by design: Google's policy forbids reverting Google's changes; FlowQR's own changes are reverted by the owner in Google).
* No Place Actions, verification state, or competitor category storage.
* Attribute UI handles Yes/No questions only; enum/multi-value/link attributes are reported as "not shown here yet".
* Free-form service prices are not set by FlowQR.
