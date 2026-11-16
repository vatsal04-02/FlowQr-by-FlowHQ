# Merge of `phase-2/commercial-readiness` into `billing/cashfree-phase1`: how the nine conflicts were resolved

Written for the engineer reviewing the merge commit. "Ours" is the Cashfree branch; "theirs" is `phase-2/commercial-readiness` (onboarding redesign `a49ca6e`, Growth-only free trial `0138e15`).

## The two decisions that settled every conflict

1. **The Razorpay card-on-file trial gate is withdrawn.** Theirs added a card gate (`trial_requires_card`, `card_required`, `card_blocks`, `card_on_file`, `require_active_for_setup`, `/billing/subscription/checkout` opening Razorpay). Ours replaces it with the Cashfree authorisation gate: a new business is `incomplete` and the 7-day trial starts only when the server has read a confirmed (`ACTIVE`) Cashfree mandate. Migration `0033` (the withdrawn card migration) is **not** reintroduced; `0034` still descends from `0032`.
2. **Every trial is the complete Growth plan** (owner decision, final; this corrects the first merge commit `da62e04`, which gave each customer the plan they selected). The trial entitlement is always Growth; the selected paid plan (Launch, Growth or Scale) is kept separately in `pending_plan` and becomes the paid plan only after a verified successful payment. See design doc section 14. The trial length stays 7 days for every plan. `0138e15`'s other rule (Starter and Pro charged from today) stays withdrawn: all three plans start with the trial.

Everything else from theirs is kept: the redesigned wizard (business + first location in one step, Google suggestions, `places` API, `Combobox`, `Shell`), auth page redesign, and all unrelated fixes.

## The nine conflicted files

| # | File | Resolution |
|---|---|---|
| 1 | `backend/app/main.py` | **Union.** Both routers are registered: their `places`, our `webhooks` (the Cashfree webhook). Nothing else differed. |
| 2 | `backend/app/api/v1/tenants.py` | **Ours.** `complete-onboarding` answers 402 `authorization_required` while the subscription is `incomplete`. Their 402 `card_required` is gone. |
| 3 | `backend/app/services/entitlements.py` | **Ours**, then their leftovers removed: `card_blocks`, the `card_required` lock reason and their second `require_active_for_setup` (card version). Ours keeps `authorization_required` as the reason for an `incomplete` account and a single `require_active_for_setup` that lets an account whose authorisation is outstanding create only its first location, only while onboarding is unfinished. |
| 4 | `backend/app/api/v1/billing.py` | **Ours.** `/billing/plans` reports `billing.mandate_required` (not `trial_requires_card`/`trial_plan`). The Growth-only rule (`free_until` only for `settings.trial_plan`) is reverted to the carried-over trial, per decision 2. `/billing/subscription` additionally returns `trial_entitlement`, `trial_entitlement_name`, `selected_plan` and `selected_plan_name`. |
| 5 | `backend/tests/test_billing.py` | **Ours.** Their card-lock tests and the two Growth-only tests (`test_only_the_trial_plan_is_free_during_the_trial`, `test_the_plans_endpoint_names_the_trial_plan`) encode rules that were withdrawn or overruled and were removed; their replacements are in `test_cashfree_mandate_gate.py` and `test_cashfree_trial_entitlements.py`. |
| 6 | `frontend/src/app/(auth)/register/page.tsx` | **Combined.** Keeps their new `AuthShell` props (`mobileNote`, `points`); the wording comes from the server (`usePlans().mandateRequired`, `trialTerms()`), so it says "authorise UPI AutoPay or a card, first payment after the trial" only where that is true. |
| 7 | `frontend/src/app/onboarding/page.tsx` | **Theirs (the redesigned wizard)**, plus: the plan step is the Cashfree step; the starting step is derived from the server (a return from Cashfree, or an authorisation already started, opens the plan step); `LaunchStep` sends the person back to the plan step on 402 `authorization_required`. My earlier five-step wizard and `PlanAuthorizationStep.tsx` are deleted. |
| 8 | `frontend/src/components/marketing/PlansFromConfig.tsx` | **Combined.** "N-day free trial." followed by server-driven terms, and our Cashfree disclosure paragraph (₹1 refundable authorisation, first payment after the trial). "on Growth" is dropped (decision 2). |
| 9 | `frontend/src/lib/types.ts` | **Ours.** `PlansResponse.billing` carries `provider`, `authorization_paise`, `methods`, `mandate_required`; `SubscriptionInfo` gains `trial_entitlement`, `selected_plan` (and their names). |

## Files changed outside the nine (they referenced the withdrawn gate)

* `frontend/src/components/onboarding/PlanStep.tsx`: rewritten as the Cashfree "Plan and payment" step in the redesigned style. All three plans show "N days free"; the server's preview gives the first payment date and amount; the ₹1 refundable authorisation is disclosed before Cashfree opens. States: choose, open (not yet received), bank approval pending (polls), failed/expired/cancelled (retry), authorised (shows the trial that started and its plan). Where authorisation is not required it is the original "your free trial starts now" step.
* `components/onboarding/LaunchStep.tsx` (`card_required` → `authorization_required`; summary says "payment method authorised"), `components/onboarding/Shell.tsx` ("Plan and card" → "Plan and payment").
* `frontend/src/lib/plans.ts`: `TRIAL_TERMS` constant replaced by `trialTerms(mandateRequired)` and `usePlans().mandateRequired` (`null` until the server answers, in which case nothing is claimed). `TrialBanner`, `TrialHeadline`, `TrialNote` updated.
* `backend/app/models/platform.py`, `alembic/versions/0034_cashfree_billing.py`, `services/billing_cashfree.py`: `subscriptions.trial_entitlement`; the trial applies Growth's entitlements when authorisation is verified, leaving the selected plan untouched.
* `backend/tests/test_places_suggest.py`: the section that tested their card gate now tests the Cashfree gate. `test_migration_0034.py`: expects `trial_entitlement`.
* `e2e/phase2-onboarding-and-queue.js`, `e2e/prod-auth.js`: use `billing.mandate_required` and the authorisation button.
* New: `backend/tests/test_cashfree_trial_entitlements.py`.

## What is enforced where

* New business with `mandate_required`: `incomplete`, no trial dates, nothing unlocked (`authorization_required`).
* The trial starts only in `_start_trial_if_authorized`, which reads the subscription from Cashfree. A webhook, the return URL or any browser parameter can only prompt that read.
* `complete-onboarding`, and every entitled route, refuse an `incomplete` account.
* Existing businesses and running trials are untouched: no migration step changes a subscription row's plan, status or dates; `trial_entitlement` is NULL for them (tested).

## Not done / not proven

Real Cashfree behaviour (card and UPI AutoPay authorisation, real webhook signatures and payloads, first-charge scheduling, recurring charges, failures, plan changes) has not been exercised: it needs Sandbox credentials. Everything above is proved against the test double only. Recurring billing must not be called working until two consecutive successful Sandbox recurring charges are observed (`docs/CASHFREE_SANDBOX_TEST.md`).
