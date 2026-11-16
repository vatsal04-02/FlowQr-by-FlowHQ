# Commercial limits and cost inputs: what is confirmed, what is assumed, what is missing

One page for the owner. Every number that decides what a customer gets or what a customer costs, where it is set, and how sure we are of it. Status words mean exactly this:

* **CONFIRMED**: the owner gave the number (Phase 2 brief, 2026-11-15).
* **PROVISIONAL**: a number FlowQR needed in order to run, chosen by the builder. It is **not approved**. It is the first thing to review.
* **MISSING**: no number exists. The product does the safe thing (shown below) until one is entered. A missing price is never treated as zero.
* **DECISION**: needs the owner's choice, not a measurement.

Nothing here has been checked against a real invoice from Google, a payment provider, a printer or a host.

## 1. What a customer gets

| Item | Value | Status | Where it is set | If it is wrong or missing |
|---|---|---|---|---|
| Plan prices | Launch ₹499, Growth ₹799, Scale ₹1,499 a month | CONFIRMED | `billing_plans` (seeded by migration 0029; specification in `backend/app/services/plans.py`) | A price change is a reviewed SQL update or a new migration; the admin screen edits only the map limits. Existing subscribers keep the amount they were created with at the payment provider |
| Review-writing allowance | 200 / 400 / 800 a month (Launch / Growth / Scale) | CONFIRMED | `billing_plans.review_generations`, copied into each subscription | Enforced by the backend before any AI call; the customer sees "0 left", not a surprise bill |
| AI reply allowance | 200 / 400 / 800 a month, **separate** from the line above | CONFIRMED | `billing_plans.review_replies` | as above |
| Card offer | ₹800 for 1 card, ₹1,000 for 2, each with one free Growth month | CONFIRMED | `CARD_OFFERS` (JSON, defaults to these two) | Recorded as one-time revenue, never as MRR; the free month is a promotional grant, not a payment, and nothing is charged when it ends |
| Second card gives a second free month? | **No**: one grant per business | CONFIRMED (the brief says a second card gives none) | `PROMO_MAX_GRANTS_PER_BUSINESS` = 1 | |
| Length of the free "month" | 30 days | PROVISIONAL | `PROMO_CARD_DAYS` | DECISION: 30 days or a calendar month |
| Locations per plan | Launch 1, **Growth 1**, **Scale 10** | PROVISIONAL (Growth: "multi-location is No by default" in the brief; Pro: carried over from the retired Multi plan) | `billing_plans.max_locations` | DECISION |
| Team seats | 3 / 10 / 50 | PROVISIONAL (carried over from the retired plans) | `billing_plans.max_staff` | DECISION |
| Launch's feature set | manual profile editing yes; Google Posts, Photos, autonomy start at Growth | PROVISIONAL | `billing_plans.features` | DECISION |
| Trial | 7 days, card required (charged after the trial) | owner decision 2026-11-15 (was 14 days, no card) | `TRIAL_DAYS` | |
| Search terms tracked per location | 10 | PROVISIONAL (was a hardcoded constant until this pass; now a setting) | `RANK_MAX_KEYWORDS_PER_LOCATION` | DECISION: a per-plan number needs a schema change, not built because no number has been chosen |

## 2. Local ranking and maps (each one spends Google money)

| Item | Value | Status | Where | Behaviour when missing |
|---|---|---|---|---|
| **Maps (geo-grid) allowance per plan**: maps per location, points per map, points per month | **none** | **MISSING, DECISION** | Admin > Plans, per plan (`billing_plans.limits.geo`) | **Maps are OFF for that plan** (fail closed): the page says so and no scan runs. All three numbers must be positive whole numbers; one missing keeps maps off. Pinned by tests |
| Searches one business may spend per month on keyword checks | 300 | PROVISIONAL | `RANK_MONTHLY_CHECK_CAP` | Checks stop at the cap |
| Searches the whole platform may spend per month | 0 = **no platform cap** | MISSING | `RANK_PLATFORM_MONTHLY_CAP` | **With 0 there is no platform-wide ceiling.** Set one before the first paying customer |
| Per-business ceiling an admin can set | unset | optional | Admin > Customers (`places_monthly_cap`) | Falls back to the number above |
| Scan frequency | keywords re-checked every 7 days; an active map re-scanned every 7 days **only if the whole scan fits the monthly allowance** | PROVISIONAL | `RANK_AUTO_CHECK_DAYS`, `RANK_GRID_AUTO_DAYS` | |
| Map point spacing | 250 m to 10 km | PROVISIONAL | `RANK_GRID_MIN_SPACING_M`, `RANK_GRID_MAX_SPACING_M` | Closer points are the same search twice |
| Search radius around the location | 3 km | PROVISIONAL | `RANK_RADIUS_M` | |
| Map size (points) | follows the plan's "points per map" | MISSING (same as the first row) | | |
| **Price of one Places search** | **none configured** | **MISSING** | `API_PRICES` (JSON, USD per unit, e.g. `{"places.searchText": <price>}`), copied from **your** Google Cloud billing page or SKU list, not from memory | Calls are counted and shown as **unpriced**; no cost is invented and no total pretends to be complete. Places spending is bounded by **counts** (per-business cap, plan map allowance, platform cap), not by dollars, so a missing price does not stop scans: only the cost display is incomplete. That is why the platform-wide cap in this table matters |
| One grid point = one request? | **Not assumed.** Each point is recorded as one request in the usage ledger; the real number of billed requests per point (page size, field mask, SKU) must be read from a real scan's Cloud Console usage | MISSING until a real scan | `docs/LIVE_VALIDATION_RUNBOOK.md` stage 5 | |

## 3. What it costs us

| Input | Value | Status | Where | Effect on Admin > Finance |
|---|---|---|---|---|
| AI model price per million tokens (in / out) | 0 | MISSING | `AI_PRICE_IN_PER_MTOK`, `AI_PRICE_OUT_PER_MTOK` | AI calls are counted, cost shown as unpriced; per-tenant and platform USD limits **refuse** calls while unpriced |
| Google Business Profile API cost | none configured | MISSING (verify in Google Cloud; do not assume free) | `API_PRICES` keys `gbp.*` | Counted, unpriced |
| Places API (New) price | see section 2 | MISSING | `API_PRICES` | |
| USD to INR rate | unset | MISSING | `USD_INR_RATE` | USD costs cannot be put next to rupee revenue: margin shown as missing |
| Hosting | unset | MISSING | `HOSTING_MONTHLY_INR` | Margin missing |
| Support | unset | MISSING | `SUPPORT_MONTHLY_INR` | Margin missing |
| Payment-provider fee | unset | MISSING (provider chosen: Cashfree; **its current fee has not been looked up**) | `PAYMENT_FEE_PCT` | Margin missing |
| Card manufacturing, per card | unset (an earlier note estimated about ₹75, ₹150 for two) | **PROVISIONAL at best, unconfirmed**; ignore until a quote exists | `CARD_UNIT_COST_INR` | Card margin missing |
| Packaging, shipping, fulfilment, per order | unset | MISSING | `CARD_FULFILMENT_PER_ORDER_INR` | Card margin missing |
| Marketing spend | unset | MISSING | `MARKETING_SPEND_MONTHLY_INR` | CAC, payback and LTV/CAC missing |

**How Finance treats this.** Every figure on Admin > Finance and usage carries `actual` (measured), `estimated` (measured plus an assumption you configured) or `missing` (an input was never entered). A contribution margin appears **only when every variable-cost input exists**. Card sales are one-time revenue, never MRR or ARR. The free card month is not revenue. Lifetime value stays missing until churn has been observed.

## 4. Things that fail closed until you decide (and how to open them)

1. **Maps** stay off until a plan has all three map numbers (Admin > Plans).
2. **AI dollar budgets** (per business and platform) refuse calls until AI prices are entered (`AI_PRICE_*`). Places has no dollar budget: it is limited by counts (see section 2).
3. **Platform-wide Places ceiling** is *off* (0). It is the one control that fails **open**: set `RANK_PLATFORM_MONTHLY_CAP` before launch.
4. **Card ordering** is disabled until `CARD_OFFERS` or `CARD_PRICE_PAISE` is set (the two offers above are the defaults, so ordering is available once a payment provider is wired).
5. **Payments** are not wired: Cashfree is the intended provider and integration waits for the live website (see section 5).

## 5. Payment provider status (decision recorded 2026-11-15)

Cashfree Payments is the intended provider; integration is **deliberately deferred until the website is live**. No Cashfree code exists. The Razorpay client and webhook that exist in the repository date from earlier phases; they are not configured here (no keys in staging or the development stack), they were not extended in Phase 2, and they must not be configured for production. Subscription entitlement (trial, plan, allowances, grace, cancellation, history, the free card month) works without any payment provider: an administrator can set a business's plan from Admin > Customers, and every change is written to the subscription history. Retiring the Razorpay code, or leaving it dormant behind the provider interface, is a clean-up for the Cashfree integration, not for now.

## 6. To make a business decision here

| Decision | Who | Where to record it |
|---|---|---|
| Map allowances per plan | owner | Admin > Plans; then update this page |
| Per-plan keyword numbers, location counts, seat counts, free-month length | owner | new migration or reviewed SQL for `billing_plans`; `PROMO_CARD_DAYS` |
| All prices and costs in section 3 | owner, from real quotes and invoices | environment (`docs/ENVIRONMENT_VARIABLES.md`) |
| Platform-wide Places ceiling | owner | `RANK_PLATFORM_MONTHLY_CAP` |
