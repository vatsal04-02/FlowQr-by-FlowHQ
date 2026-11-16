# Geo-grid (maps): enablement checklist

Status: **maps are OFF everywhere** (`RANK_GRID_ENABLED=false`, the shipped default). Nothing below has been approved or configured. This file lists what must be true before anyone turns them on, and which control enforces each item. No price, allowance or cap in this repository is a real decision; the test suite uses clearly labelled test values.

## How maps are guarded (all enforced in code, `backend/app/services/rank_grid.py`)

A map scan can run only if **every** line is true. Otherwise the scan is refused before any Google call, the refusal is recorded in the usage ledger, and the UI says why.

| # | Guard | Setting | Refusal reason shown | Fails |
|---|---|---|---|---|
| 1 | Master switch / emergency stop on | `RANK_GRID_ENABLED=true` | "switched off by FlowQR" | **closed** (default off) |
| 2 | A platform-wide spending cap exists: daily and/or monthly | `RANK_PLATFORM_DAILY_CAP`, `RANK_PLATFORM_MONTHLY_CAP` (not both 0) | "off until FlowQR sets a platform-wide spending limit" | **closed**: with both 0, maps refuse to run |
| 3 | The price of one Places search has been recorded | `RANK_COST_PER_CALL_USD` > 0 | "off until FlowQR has recorded the price of one search" | **closed** |
| 4 | The business's plan includes maps and its allowances are set | Admin › Plans (`billing_plans.limits.geo`: maps per location, points per map, points per month) | "not included in your plan" / "allowances have not been set yet" | **closed** (existing) |
| 5 | The business is within its own monthly cap | Admin › Customers (`places_monthly_cap`), plan allowance | "this scan needs N searches and M are left" | closed (existing) |
| 6 | The whole scan fits what the platform has left today and this month | the two platform caps | "allowance for today / this month is used up" | closed; a scan is never half-bought |

Every scan point, manual or automatic, is one billed Places search recorded in `api_usage_ledger` (`status` ok / error / refused). Automatic re-scans (`check_rank_grids`, every 6 h, at most 3 scans per run) obey the same guards.

### Emergency disable
Set `RANK_GRID_ENABLED=false` in `/opt/flowqr/.env.production` and restart the API and worker (`docker compose … up -d api worker beat`). From that moment every manual and scheduled map scan is refused. Single-keyword rank checks are governed separately by `RANK_MONTHLY_CHECK_CAP`, `RANK_PLATFORM_MONTHLY_CAP` and the provider switch (`RANK_PROVIDER`). Removing `RANK_PROVIDER` stops all Places rank searches.

### Usage alerts
Admin › Operations › "Geo-grid maps": healthy ("switched off") while off; once on it shows searches used today and this month against each cap, a **warning at `RANK_ALERT_PCT` (default 80%)** and **critical at 100%**, and goes critical if maps are on without a cap or a price. Spend shown is `searches × RANK_COST_PER_CALL_USD` and is labelled as using the configured price. The existing `ops-watch` job (every 15 minutes) evaluates it with the other operations checks.

## What must be verified and decided before enabling (owner)

| Item | How to obtain it (do not guess) | Status |
|---|---|---|
| **Actual Google Cloud SKU and price** for the Places call FlowQR makes | Google Cloud Console › Billing › SKUs for your project, and Google's current Places API (New) price list for your billing country (India has its own list). FlowQR calls **Text Search**, so find that SKU. | **NOT DONE** |
| **Which requested fields change the billed SKU** | `services/rank.py` requests the field mask `places.id,places.displayName,places.rating,places.userRatingCount`. Compare each field against Google's field-to-SKU table. Fields such as rating and review count can place a request in a higher tier than id and name alone, but this must be confirmed from Google's table, not assumed. If a cheaper tier suffices, change the mask; if the extra fields are needed (competitor ratings and review counts are shown on the competitor page), accept that tier's price. | **NOT DONE** |
| Price to record | Put the confirmed per-search price (USD) in `RANK_COST_PER_CALL_USD` (and `API_PRICES` for the ledger, see `COMMERCIAL_LIMITS_AND_COSTS.md`) | **NOT DONE** |
| Per-plan monthly allowances | Admin › Plans: maps per location, points per map, searches per month, for each plan | **NOT DONE** |
| Platform-wide daily cap | `RANK_PLATFORM_DAILY_CAP` | **NOT DONE** |
| Platform-wide monthly cap | `RANK_PLATFORM_MONTHLY_CAP` | **NOT DONE** |
| Per-tenant limits | plan allowance and, where needed, Admin › Customers `places_monthly_cap` | **NOT DONE** |
| Monthly cost exposure | worst case = `RANK_PLATFORM_MONTHLY_CAP × price`. Per business = `plan monthly points × price`. Expected case = `active grids × points × scans per month × price` (`RANK_GRID_AUTO_DAYS`=7 means about 4 scheduled scans a month per grid and keyword). Sum for every business on each plan and compare with the cap. | **NOT DONE** |
| A billing alert in Google Cloud on the project | Cloud Console › Billing › Budgets & alerts, below the monthly cap's cost | **NOT DONE** |
| A separate, restricted Places key for the VPS | the key currently on the VPS is the same key used on a development laptop; create a key restricted to the VPS IP and the Places API only | **NOT DONE** |

## Turning it on (when all of the above are done)
1. Set the values in `/opt/flowqr/.env.production` (never in git); keep `RANK_GRID_ENABLED=false`.
2. Restart api, worker and beat; check Admin › Operations › "Geo-grid maps" says "Switched off".
3. Set the plan allowances in Admin › Plans.
4. Set `RANK_GRID_ENABLED=true`, restart, confirm the same row now shows the caps and a price, with 0 searches used.
5. Enable for one internal business first and watch the ledger (Admin › Operations, `api_usage_ledger`) for one day before opening to customers.
