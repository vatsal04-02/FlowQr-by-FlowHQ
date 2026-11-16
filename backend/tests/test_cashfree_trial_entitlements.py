"""Owner decision 2026-11-16: during the 7-day trial a customer gets the features and limits of the plan they SELECTED (Launch -> Launch, Growth -> Growth, Scale -> Scale), never Growth's by default.
The selected plan is persisted on the subscription (`trial_plan`) and enforced server-side through the same entitlement columns every route reads. The duration is the same 7 days for all three.
Real application and PostgreSQL; Cashfree is the TEST DOUBLE of the other Cashfree tests."""
from datetime import timedelta

import pytest

from app.core.config import settings
from app.models.base import utcnow
from app.services import plans
from tests.conftest import make_business, owner_query
from tests.test_cashfree_billing import charge, events_of, set_sub, start, sub_of, sync
from tests.test_cashfree_mandate_gate import authorise, info, mandate  # noqa: F401  (fixture)

CODES = ["starter", "growth", "pro"]


def stored(biz):
    r = owner_query("SELECT trial_plan, plan, status, max_locations, max_staff, review_generations, review_replies, features, trial_ends_at, trial_started_at FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0]
    return dict(zip(("trial_plan", "plan", "status", "max_locations", "max_staff", "review_generations", "review_replies", "features", "trial_ends_at", "trial_started_at"), r))


@pytest.mark.parametrize("code", CODES)
def test_the_trial_grants_the_selected_plans_features_and_limits_and_persists_the_choice(mandate, code):
    spec = plans.PLANS[code]
    biz = make_business(location_cap=None)  # the plan's REAL location cap
    authorise(mandate, biz, code)
    s = stored(biz)
    assert (s["trial_plan"], s["plan"], s["status"]) == (code, "trial", "trialing")
    assert (s["max_locations"], s["max_staff"], s["review_generations"], s["review_replies"]) == (spec["max_locations"], spec["max_staff"], spec["review_generations"], spec["review_replies"])
    assert sorted(s["features"]) == sorted(spec["features"])
    assert abs((s["trial_ends_at"] - s["trial_started_at"]).total_seconds() / 86400 - settings.trial_days) < 0.01  # 7 days for every plan
    api = info(biz)
    assert api["active"] is True and api["trial_plan"] == code and api["trial_plan_name"] == spec["name"] and api["plan_name"] == "Free trial"
    assert api["limits"] == {"locations": spec["max_locations"], "ai_generations": spec["monthly_ai_generations"], "review_generations": spec["review_generations"],
                             "review_replies": spec["review_replies"], "staff": spec["max_staff"], "features": sorted(spec["features"])}
    meta = owner_query("SELECT metadata FROM subscription_events WHERE tenant_id = :t AND kind = 'trial_started'", t=biz.tenant_id)[0][0]
    assert meta["entitlements_of"] == code


@pytest.mark.parametrize("code", CODES)
def test_the_selected_plans_limits_and_features_are_enforced_by_the_server_not_the_screen(mandate, code):
    spec = plans.PLANS[code]
    biz = make_business(location_cap=None)
    authorise(mandate, biz, code)
    second = biz.post("/locations", json={"name": "Second branch", "city": "Delhi", "review_url": "https://g.page/r/Second123/review"})
    if spec["max_locations"] > 1:
        assert second.status_code == 201  # Scale: up to 10 locations during its trial
    else:
        assert second.status_code == 402 and second.json()["detail"]["code"] == "plan_limit"  # Launch and Growth: one location
    insights = biz.get("/analytics/insights")
    if "insights" in spec["features"]:
        assert insights.status_code != 402  # Growth and Scale include Insights
    else:
        assert insights.status_code == 402 and "isn't included in your current plan" in insights.json()["detail"]["message"]  # Launch does not, even though the trial is running


def test_a_launch_trial_is_not_given_growths_features_and_a_scale_trial_is_not_limited_to_growths(mandate):
    a = make_business(location_cap=None)
    authorise(mandate, a, "starter")
    b = make_business(location_cap=None)
    authorise(mandate, b, "pro")
    fa, fb = set(info(a)["limits"]["features"]), set(info(b)["limits"]["features"])
    assert "gbp_posts" not in fa and "autonomy" not in fa and "multi_location" not in fa
    assert {"gbp_posts", "autonomy", "multi_location"} <= fb
    assert info(a)["limits"]["staff"] == 3 and info(b)["limits"]["staff"] == 50


def test_changing_the_selection_before_authorising_gives_the_plan_that_was_selected_last(mandate):
    biz = make_business(location_cap=None)
    assert start(biz, "starter").status_code == 200
    assert start(biz, "pro").status_code == 200  # a different plan before the first was authorised: the earlier checkout is closed
    sid = sub_of(biz)["cashfree_subscription_id"]
    mandate.set_status(sid, "ACTIVE"); mandate.pay(sid, f"auth_{sid}", "AUTH", "SUCCESS", 100)
    sync(biz)
    assert stored(biz)["trial_plan"] == "pro" and info(biz)["limits"]["locations"] == 10 and sub_of(biz)["pending_plan"] == "pro"


def test_the_browser_cannot_choose_or_change_the_trial_plan_through_the_return_call(mandate):
    biz = make_business(location_cap=None)
    authorise(mandate, biz, "starter")
    assert biz.post("/billing/subscription/sync?plan=pro&trial_plan=pro&pending_plan=pro").status_code == 200
    assert stored(biz)["trial_plan"] == "starter" and info(biz)["limits"]["locations"] == 1


def test_a_plan_change_during_the_trial_takes_effect_at_the_next_payment_not_now(mandate):
    biz = make_business(location_cap=None)
    sid = authorise(mandate, biz, "starter")
    mandate.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=38))
    r = biz.post("/billing/subscription/change-plan", json={"plan": "pro"})
    assert r.status_code == 200 and r.json()["pending_plan"] == "pro"
    assert stored(biz)["trial_plan"] == "starter" and info(biz)["limits"]["locations"] == 1 and info(biz)["pending_plan_name"] == "Scale"  # the trial keeps its own plan's entitlements
    charge(mandate, biz, sid, 149900, pid="scale_first")  # the first payment, at the NEW amount: now the plan changes
    s = sub_of(biz)
    assert (s["status"], s["plan"], s["pending_plan"]) == ("active", "pro", None) and info(biz)["limits"]["locations"] == 10


def test_the_first_payment_makes_the_selected_plan_the_paid_plan_with_the_same_entitlements(mandate):
    biz = make_business(location_cap=None)
    sid = authorise(mandate, biz, "growth")
    before = info(biz)["limits"]
    mandate.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=38))
    charge(mandate, biz, sid, 79900, pid="growth_first")
    assert sub_of(biz)["plan"] == "growth" and info(biz)["limits"] == before  # nothing changes for the customer at the first payment


def test_a_business_that_never_chose_a_plan_keeps_the_default_trial_entitlements_as_before(monkeypatch):
    monkeypatch.setattr(settings, "billing_provider", "")  # no Cashfree gate: the original trial, which has no selection
    biz = make_business(location_cap=None)
    s = stored(biz)
    assert s["trial_plan"] is None and s["status"] == "trialing" and sorted(s["features"]) == sorted(plans.PLANS[settings.trial_plan]["features"])
    assert info(biz)["trial_plan"] is None and info(biz)["trial_plan_name"] is None


def test_an_incomplete_account_unlocks_nothing_whichever_plan_is_pending(mandate):
    biz = make_business(location_cap=None)
    start(biz, "pro")  # selected, checkout open, NOT authorised
    s = stored(biz)
    assert s["status"] == "incomplete" and s["trial_plan"] is None and info(biz)["active"] is False
    assert biz.get("/analytics/insights").status_code == 402  # not even the features of the plan being chosen
    assert "trial_started" not in events_of(biz)
    set_sub(biz, last_provider_sync_at=utcnow())
