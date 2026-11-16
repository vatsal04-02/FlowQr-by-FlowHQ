# Migration reconciliation: Phase 2 and the Cashfree billing branch

Checked 2026-11-16. Nothing in production was changed to produce this; the production revision was read with one `select` on `alembic_version`.

## The facts

| Where | Revision chain | Note |
|---|---|---|
| **Production (VPS, image `prod-0138e15`)** | `… 0031 → 0032 → 0033` | `alembic_version = 0033` (read-only check). `0033_trial_card_required` added `subscriptions.card_status`. |
| `phase-2/commercial-readiness` (this branch, before this work) | `… 0032 → 0033` | Head `0033`. |
| `billing/cashfree-phase1` (unmerged, being developed separately) | `… 0032 → 0034` | **`0033` was withdrawn there** ("card-on-file trial removed"). `0034_cashfree_billing.py` has `down_revision = "0032"`, drops `subscriptions.card_status` if present, renames plan display names to Launch/Growth/Scale, and adds Cashfree columns. Its docstring says production "went 0032 to this revision", which is **no longer true**: production is at `0033`. |

### The conflict that already existed
A production database at `0033` cannot be upgraded by the Cashfree branch as it stands: that branch contains no revision `0033`, so Alembic stops with "Can't locate revision '0033'". That is independent of Phase 2. It needs a decision by the Cashfree work (below). **I did not touch that branch.**

## What Phase 2 does

* New revision **`0035`** (`0035_gbp_metric_daily.py`), `down_revision = "0033"`: exactly one new table, `gbp_metric_daily`, RLS forced, tenant policy, app role `SELECT, INSERT, UPDATE` only.
* **`0034` is not used**, because the Cashfree branch already owns the id `0034`. Two files with one revision id would be the "duplicate revision id" failure. The numeric gap is intentional and documented in the migration.
* New revision **`0036`** (`0036_pinned_competitors.py`, Competitor Analysis stage 2), `down_revision = "0035"`: two additive tables (`pinned_competitors`, `competitor_snapshots`), RLS forced, tenant policy; snapshots are append-only for the app role.
* Result on this branch: **one head (`0036`)**, a single path from the actual production revision: `0033 → 0035 → 0036`.

### Verified (disposable databases, local Postgres 16, run as the table owner)
| Check | Result |
|---|---|
| `alembic heads` on this branch | one head only (`0036`; verified again after 0036 was added, see below) |
| Fresh DB `upgrade 0033` → `upgrade head` | `0035`; table, forced RLS, `tenant_isolation` policy, grants `INSERT, SELECT, UPDATE` present |
| `downgrade 0033` | table gone, `alembic_version = 0033` |
| `upgrade head` again | `0035 (head)` |
| Backend test suite | rebuilds the schema from the migrations on every run; `tests/test_seo_metrics.py` asserts forced RLS, policy and grants |
| **Rehearsal of the reconciled chain** (a throwaway copy, not committed): Cashfree `0034` re-parented to `0033`, Phase 2 `0035` re-parented to `0034` | single head `0035`; `upgrade 0033 → head` and `downgrade → 0033` both clean |

## Recommended reconciliation (a decision for the Cashfree work, not made here)

Whichever branch is deployed second must be re-parented; this is a one-line change per file and has been rehearsed above.

1. **If Phase 2 ships first** (production goes `0033 → 0035 → 0036`): on the Cashfree branch renumber `0034` to `0037` (`0037_cashfree_billing.py`, `revision = "0037"`, `down_revision = "0036"`); keep its `DROP COLUMN IF EXISTS card_status` behaviour only if the card gate really is being withdrawn (see below).
2. **If Cashfree ships first**: re-parent its `0034` to `down_revision = "0033"`, then change this branch's `0035` to `down_revision = "0034"` (`0034 → 0035 → 0036`, the rehearsed chain).
3. Never leave two heads; run `alembic heads` (must print one line) before any deployment, and the usual backup-and-restore rehearsal from `docs/PRODUCTION_DATABASE_MIGRATION.md`.

### A product conflict the migration reconciliation exposes (needs your decision)
The Cashfree `0034` **drops `subscriptions.card_status`**. The current production code (commits `a49ca6e`, `0138e15`) **uses** `card_status` for the card gate (`ent.card_blocks`, `require_active_for_setup`, `/tenant/complete-onboarding` 402 `card_required`). The two lines also disagree on the trial rule:

| | Production today (Razorpay line) | Cashfree line / your Phase 2 brief §I |
|---|---|---|
| Trial entitlements | Free 7-day trial is on **Growth only**; Starter and Pro are charged from today | All new customers get **Growth entitlements for 7 days**; the selected paid plan is stored separately and billed after the trial |
| Plan names | `starter` / `growth` / `pro`, shown as Starter / Growth / Pro | Same codes, shown as Launch / Growth / Scale |
| Card gate | `card_status` column | Mandatory Cashfree authorisation before the trial |

Phase 2 changes **none** of this: no billing, entitlement, plan or trial code was modified. Reconciling the two trial models is the Cashfree integration's job and should be decided before either branch is deployed.
