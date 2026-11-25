"""Owner decision (final, 2026-11-16): EVERY customer gets the complete Growth feature set for the whole seven-day trial, whichever paid plan they select. Launch -> Growth access during the trial,
Growth -> Growth, Scale -> Growth (Scale's own capabilities are NOT available during the trial). The selected plan is kept separately and becomes the paid plan only after a verified successful payment.

`trial_entitlement` (always Growth) and the selected plan (`pending_plan`, reported as `selected_plan`) never overwrite one another. Enforcement is server-side: these tests call the real routes.
Real application and PostgreSQL; Cashfree is the TEST DOUBLE of the other Cashfree tests."""
from datetime import timedelta

import pytest

from app.core.config import settings
from app.models.base import utcnow
from app.services import plans
from tests.conftest import make_business, owner_query
from tests.test_cashfree_billing import charge, events_of, start, sub_of, sync
from tests.test_cashfree_mandate_gate import authorise, info, mandate  # noqa: F401  (fixture)

CODES = ["starter", "growth", "pro"]
AMOUNT = {"starter": 49900, "growth": 79900, "pro": 149900}
GROWTH = plans.PLANS["growth"]
SCALE_ONLY = set(plans.PLANS["pro"]["features"]) - set(GROWTH["features"])
COLS = ("trial_entitlement", "plan", "status", "max_locations", "max_staff", "review_generations", "review_replies", "features", "trial_ends_at", "trial_started_at", "pending_plan")


def stored(biz):
    r = owner_query(f"SELECT {', '.join(COLS)} FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0]
    return dict(zip(COLS, r))


def growth_limits():
    return {"locations": GROWTH["max_locations"], "ai_generations": settings.trial_review_generations + settings.trial_review_replies, "review_generations": settings.trial_review_generations,
            "review_replies": settings.trial_review_replies, "staff": GROWTH["max_staff"], "features": sorted(GROWTH["features"])}


def test_scale_has_capabilities_growth_lacks_so_the_tests_below_mean_something():
    assert SCALE_ONLY and "multi_location" in SCALE_ONLY and plans.PLANS["pro"]["max_locations"] > GROWTH["max_locations"] and plans.PLANS["pro"]["max_staff"] > GROWTH["max_staff"]
    assert set(plans.PLANS["starter"]["features"]) < set(GROWTH["features"])  # Launch has less than Growth


@pytest.mark.parametrize("code", CODES)
def test_every_selected_plan_gets_the_complete_growth_trial_and_the_selection_is_preserved(mandate, code):
    biz = make_business(location_cap=None)  # the plan's REAL location cap, not the test default
    authorise(mandate, biz, code)
    s = stored(biz)
    assert (s["trial_entitlement"], s["plan"], s["status"]) == ("growth", "trial", "trialing")
    assert s["pending_plan"] == code  # the selected paid plan is NOT overwritten by assigning Growth's entitlements
    assert (s["max_locations"], s["max_staff"], s["review_generations"], s["review_replies"]) == (GROWTH["max_locations"], GROWTH["max_staff"], settings.trial_review_generations, settings.trial_review_replies)  # Growth's features, a small trial allowance
    assert sorted(s["features"]) == sorted(GROWTH["features"])
    assert abs((s["trial_ends_at"] - s["trial_started_at"]).total_seconds() / 86400 - settings.trial_days) < 0.01  # 7 days for every plan
    api = info(biz)
    assert api["active"] is True and api["plan_name"] == "Free trial"
    assert api["trial_entitlement"] == "growth" and api["trial_entitlement_name"] == "Growth"
    assert api["selected_plan"] == code and api["selected_plan_name"] == plans.PLANS[code]["name"]
    assert api["limits"] == growth_limits()
    meta = owner_query("SELECT metadata FROM subscription_events WHERE tenant_id = :t AND kind = 'trial_started'", t=biz.tenant_id)[0][0]
    assert meta["entitlements_of"] == "growth" and meta["selected_plan"] == code


@pytest.mark.parametrize("code", CODES)
def test_growth_access_is_enforced_by_the_server_and_scale_only_capabilities_stay_closed(mandate, code):
    biz = make_business(location_cap=None)
    authorise(mandate, biz, code)
    second = biz.post("/locations", json={"name": "Second branch", "city": "Delhi", "review_url": "https://g.page/r/Second123/review"})
    assert second.status_code == 402 and second.json()["detail"]["code"] == "plan_limit"  # Growth's one location, even for a customer who selected Scale
    assert biz.get("/analytics/insights").status_code != 402  # Growth's Insights, even for a customer who selected Launch
    features = set(info(biz)["limits"]["features"])
    assert set(GROWTH["features"]) <= features and not (SCALE_ONLY & features)
    assert info(biz)["limits"]["staff"] == GROWTH["max_staff"] < plans.PLANS["pro"]["max_staff"]


def test_launch_and_growth_trials_have_identical_access_and_a_scale_trial_has_nothing_more(mandate):
    seen = []
    for code in CODES:
        biz = make_business(location_cap=None)
        authorise(mandate, biz, code)
        seen.append(info(biz)["limits"])
    assert seen[0] == seen[1] == seen[2] == growth_limits()


@pytest.mark.parametrize("code", CODES)
def test_the_selected_plan_becomes_the_paid_plan_only_after_a_verified_successful_payment(mandate, code):
    biz = make_business(location_cap=None)
    sid = authorise(mandate, biz, code)
    assert stored(biz)["plan"] == "trial"  # authorised (and the refundable amount taken), but nothing paid: still the Growth trial
    assert sub_of(biz)["pending_plan"] == code
    charge(mandate, biz, sid, AMOUNT[code], pid=f"first_{code}")  # the first real charge, at the SELECTED plan's amount
    s, spec = stored(biz), plans.PLANS[code]
    assert (s["plan"], s["status"], s["pending_plan"]) == (code, "active", None)
    assert (s["max_locations"], s["max_staff"]) == (spec["max_locations"], spec["max_staff"]) and sorted(s["features"]) == sorted(spec["features"])
    api = info(biz)
    assert api["limits"]["features"] == sorted(spec["features"]) and api["plan_name"] == spec["name"] and api["selected_plan"] == code


def test_after_the_trial_a_launch_customer_loses_growth_only_features_and_a_scale_customer_gains_scale(mandate):
    launch = make_business(location_cap=None)
    sid = authorise(mandate, launch, "starter")
    assert launch.get("/analytics/insights").status_code != 402  # during the trial: Growth access
    charge(mandate, launch, sid, AMOUNT["starter"], pid="launch_first")
    insights = launch.get("/analytics/insights")
    assert insights.status_code == 402 and "isn't included in your current plan" in insights.json()["detail"]["message"]  # after payment: Launch's own plan
    scale = make_business(location_cap=None)
    sid = authorise(mandate, scale, "pro")
    assert scale.post("/locations", json={"name": "Second branch", "city": "Delhi", "review_url": "https://g.page/r/Second123/review"}).status_code == 402  # trial: Growth's one location
    charge(mandate, scale, sid, AMOUNT["pro"], pid="scale_first")
    assert scale.post("/locations", json={"name": "Second branch", "city": "Delhi", "review_url": "https://g.page/r/Second123/review"}).status_code == 201  # paid Scale: up to 10


def test_a_payment_of_the_wrong_amount_changes_nothing_the_trial_and_the_selection_stay(mandate):
    biz = make_business(location_cap=None)
    sid = authorise(mandate, biz, "pro")
    charge(mandate, biz, sid, AMOUNT["growth"], pid="wrong_amount")  # not the amount of the selected plan: unexplained money never changes entitlements
    s = stored(biz)
    assert (s["plan"], s["status"], s["pending_plan"], s["trial_entitlement"]) == ("trial", "trialing", "pro", "growth")
    assert "amount_mismatch" in events_of(biz)


def test_changing_the_selected_plan_during_the_trial_changes_only_what_is_billed_later(mandate):
    biz = make_business(location_cap=None)
    sid = authorise(mandate, biz, "starter")
    mandate.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=38))
    r = biz.post("/billing/subscription/change-plan", json={"plan": "pro"})
    assert r.status_code == 200 and r.json()["pending_plan"] == "pro"
    s = stored(biz)
    assert (s["pending_plan"], s["trial_entitlement"], s["plan"]) == ("pro", "growth", "trial") and info(biz)["limits"] == growth_limits() and info(biz)["selected_plan"] == "pro"
    charge(mandate, biz, sid, AMOUNT["pro"], pid="scale_first")
    assert stored(biz)["plan"] == "pro" and info(biz)["limits"]["locations"] == 10


def test_the_browser_cannot_choose_or_change_the_trial_entitlement_or_selected_plan_through_the_return_call(mandate):
    biz = make_business(location_cap=None)
    authorise(mandate, biz, "starter")
    assert biz.post("/billing/subscription/sync?plan=pro&trial_entitlement=pro&pending_plan=pro&selected_plan=pro").status_code == 200
    s = stored(biz)
    assert (s["trial_entitlement"], s["pending_plan"]) == ("growth", "starter") and info(biz)["limits"] == growth_limits()


def test_choosing_again_before_authorising_keeps_the_last_selection_and_still_gives_growth(mandate):
    biz = make_business(location_cap=None)
    assert start(biz, "starter").status_code == 200
    assert start(biz, "pro").status_code == 200  # a different plan before the first was authorised: the earlier checkout is closed
    sid = sub_of(biz)["cashfree_subscription_id"]
    mandate.set_status(sid, "ACTIVE"); mandate.pay(sid, f"auth_{sid}", "AUTH", "SUCCESS", 100)
    sync(biz)
    assert stored(biz)["pending_plan"] == "pro" and info(biz)["limits"] == growth_limits()


def test_an_incomplete_account_unlocks_nothing_whichever_plan_is_selected(mandate):
    biz = make_business(location_cap=None)
    start(biz, "pro")  # selected, checkout open, NOT authorised
    s = stored(biz)
    assert s["status"] == "incomplete" and s["trial_entitlement"] is None and info(biz)["active"] is False
    assert biz.get("/analytics/insights").status_code == 402  # not even Growth's features before the authorisation is verified
    assert "trial_started" not in events_of(biz)


def test_a_business_from_before_the_gate_keeps_its_original_trial_and_has_no_selection(monkeypatch):
    monkeypatch.setattr(settings, "billing_provider", "")  # no Cashfree gate: the original trial, which already was Growth's features
    biz = make_business(location_cap=None)
    s = stored(biz)
    assert s["trial_entitlement"] is None and s["pending_plan"] is None and s["status"] == "trialing" and sorted(s["features"]) == sorted(GROWTH["features"])
    api = info(biz)
    assert api["trial_entitlement"] is None and api["selected_plan"] is None and api["limits"] == growth_limits()
