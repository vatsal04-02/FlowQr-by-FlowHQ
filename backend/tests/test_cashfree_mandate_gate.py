"""The free trial starts ONLY after Cashfree confirms a payment authorisation (owner requirement 2026-11-16). Real application and PostgreSQL; Cashfree is the same TEST DOUBLE as in
test_cashfree_billing.py. These tests prove how FlowQR behaves; whether Cashfree's sandbox reports ACTIVE the way the documentation says is checked by the sandbox runbook, not here."""
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.main import app
from app.models.base import utcnow
from app.services import cashfree as cf
from app.services import finance
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_cashfree_billing import FakeCashfree, WH, charge, deliver, events_of, payments_of, set_sub, start, sub_of, sync


@pytest.fixture()
def mandate(monkeypatch):
    f = FakeCashfree()
    for k, v in {"billing_provider": "cashfree", "cashfree_env": "sandbox", "cashfree_client_id": "test_client_id", "cashfree_client_secret": "test_client_secret", "cashfree_webhook_secret": WH,
                 "razorpay_key_id": "", "razorpay_key_secret": "", "razorpay_webhook_secret": "", "trial_requires_mandate": True}.items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(cf, "get_cashfree", lambda: f)
    owner_exec("DELETE FROM payments WHERE cashfree_payment_id IS NOT NULL")
    owner_exec("UPDATE subscriptions SET last_provider_sync_at = now() WHERE cashfree_subscription_id IS NOT NULL")
    return f


def authorise(f, biz, plan="growth"):
    """Checkout, then Cashfree says the mandate is registered and the refundable authorisation went through, then FlowQR asks Cashfree."""
    assert start(biz, plan).status_code == 200
    sid = sub_of(biz)["cashfree_subscription_id"]
    f.set_status(sid, "ACTIVE")
    f.pay(sid, f"auth_{sid}", "AUTH", "SUCCESS", 100)
    assert sync(biz).status_code == 200
    return sid


def info(biz):
    return biz.get("/billing/subscription").json()


# ----------------------------------------------------------------------------------------------------------------------------- no trial before authorisation
def test_a_new_business_has_no_trial_and_nothing_unlocked_until_authorisation(mandate):
    biz = make_business()
    s = sub_of(biz)
    assert s["status"] == "incomplete" and s["trial_ends_at"] is None and s["provider"] is None
    assert owner_query("SELECT trial_started_at FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0][0] is None
    api = info(biz)
    assert api["active"] is False and api["inactive_reason"] == "authorization_required" and api["billing_state"] == "authorization_required" and api["mandate_required"] is True
    assert api["trial_ends_at"] is None and api["trial_days_left"] is None
    r = biz.post("/review-growth/campaigns", json={"name": "Too early", "location_id": biz.location_id})
    assert r.status_code == 402 and r.json()["detail"]["reason"] == "authorization_required" and "authorise your payment method" in r.json()["detail"]["message"]
    assert "signup_awaiting_authorization" in events_of(biz) and "trial_started" not in events_of(biz)


def test_the_setup_steps_before_the_plan_step_work_but_nothing_else_does(mandate):
    biz = make_business(with_location=False)
    r = biz.post("/locations", json={"name": "First branch", "city": "Lucknow", "review_url": "https://g.page/r/ABC123/review"})
    assert r.status_code == 201  # the first location must come before the plan step
    # after onboarding is marked finished the same call is locked again
    owner_exec("UPDATE tenants SET onboarding_completed = true WHERE id = :t", t=biz.tenant_id)
    assert biz.post("/locations", json={"name": "Second", "city": "Delhi"}).status_code == 402


def test_a_direct_api_call_cannot_skip_the_payment_step(mandate):
    biz = make_business()
    r = biz.post("/tenant/complete-onboarding")
    assert r.status_code == 402 and r.json()["detail"]["code"] == "authorization_required"
    assert owner_query("SELECT onboarding_completed FROM tenants WHERE id = :t", t=biz.tenant_id)[0][0] is False
    assert biz.post("/billing/subscription/sync").status_code == 404  # nothing to sync, and nothing the caller can say activates it
    assert biz.post("/billing/subscription/change-plan", json={"plan": "pro"}).status_code == 409
    assert TestClient(app, base_url="http://testserver").post("/api/v1/billing/subscription/checkout", json={"plan": "growth", "phone": "9876543210"}).status_code == 401
    assert sub_of(biz)["status"] == "incomplete"


def test_opening_checkout_does_not_start_the_trial(mandate):
    biz = make_business()
    out = start(biz, "starter").json()
    s = sub_of(biz)
    assert s["status"] == "incomplete" and s["authorization_status"] == "initialized" and s["pending_plan"] == "starter" and s["trial_ends_at"] is None
    assert out["free_period_honoured"] is True and 7.4 < (s["first_charge_at"] - utcnow()).total_seconds() / 86400 < 8.7  # day 8
    assert info(biz)["active"] is False and info(biz)["billing_state"] == "authorization_pending"
    created = [c for c in mandate.calls if c[0] == "create"][0][1]
    assert created["return_url"].endswith("/onboarding?checkout=return")  # back INTO onboarding while the business is being set up
    assert created["authorization_paise"] == 100 and created["refund_authorization"] is True


def test_the_preview_shows_the_first_payment_date_and_creates_nothing(mandate):
    biz = make_business()
    r = biz.get("/billing/subscription/preview?plan=growth")
    assert r.status_code == 200
    p = r.json()
    assert p["amount_paise"] == 79900 and p["plan_name"] == "Growth" and p["authorization_paise"] == 100 and p["authorization_refunded"] is True and p["trial_days"] == settings.trial_days
    assert p["trial_starts_on_authorization"] is True and p["free_period_honoured"] is True and 7.4 < (cf_dt(p["first_charge_at"]) - utcnow()).total_seconds() / 86400 < 8.7
    assert mandate.n("create") == 0 and mandate.n("ensure_plan") == 0 and sub_of(biz)["cashfree_subscription_id"] is None
    assert biz.get("/billing/subscription/preview?plan=essential").status_code == 404 and biz.get("/billing/subscription/preview").status_code == 422


def cf_dt(value):
    from datetime import datetime
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@pytest.mark.parametrize("status", ["INITIALIZED", "BANK_APPROVAL_PENDING"])
def test_an_unconfirmed_authorisation_never_starts_the_trial(mandate, status):
    biz = make_business()
    start(biz, "growth")
    sid = sub_of(biz)["cashfree_subscription_id"]
    mandate.set_status(sid, status)
    sync(biz)
    assert sub_of(biz)["status"] == "incomplete" and sub_of(biz)["trial_ends_at"] is None and info(biz)["active"] is False
    assert info(biz)["billing_state"] == "authorization_pending"


def test_a_forged_return_or_webhook_cannot_start_the_trial_only_cashfrees_own_answer_can(mandate):
    biz = make_business()
    start(biz, "growth")
    sid = sub_of(biz)["cashfree_subscription_id"]
    assert biz.post("/billing/subscription/sync?s=x&status=ACTIVE&subscription_status=ACTIVE&payment_status=SUCCESS").status_code == 200
    forged = deliver(sid, "SUBSCRIPTION_STATUS_CHANGED", status="ACTIVE")  # a correctly signed event that CLAIMS the mandate is active, while Cashfree itself says INITIALIZED
    assert forged.status_code == 200 and forged.json()["status"] == "processed"
    assert sub_of(biz)["status"] == "incomplete" and sub_of(biz)["trial_ends_at"] is None


def test_a_verified_authorisation_starts_the_seven_day_trial_exactly_once(mandate):
    biz = make_business()
    sid = authorise(mandate, biz, "growth")
    s = sub_of(biz)
    assert s["status"] == "trialing" and s["plan"] == "trial" and s["authorization_status"] == "authorized" and s["pending_plan"] == "growth"
    row = owner_query("SELECT trial_started_at, trial_ends_at, current_period_start, current_period_end FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0]
    assert abs((row[0] - utcnow()).total_seconds()) < 120 and abs((row[1] - row[0]).total_seconds() / 86400 - settings.trial_days) < 0.01 and row[3] == row[1]
    assert 3600 * 10 < (s["first_charge_at"] - row[1]).total_seconds() < 3600 * 36  # day 8: the first payment follows the 7 trial days
    api = info(biz)
    assert api["active"] is True and api["status"] == "trialing" and api["billing_state"] == "trialing" and api["trial_days_left"] in (6, 7) and api["limits"]["review_generations"] == 400
    assert api["trial_started_at"] is not None and api["payment_method"] == "upi" or api["payment_method"] is None
    assert api["next_charge_amount_paise"] == 79900 and api["pending_plan_name"] == "Growth"
    assert events_of(biz).count("trial_started") == 1
    again = (sync(biz), sync(biz))
    assert all(r.status_code == 200 for r in again)
    row2 = owner_query("SELECT trial_started_at, trial_ends_at FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0]
    assert row2 == (row[0], row[1]) and events_of(biz).count("trial_started") == 1  # the same answer again does not restart or extend it
    assert payments_of(biz) == [("sub_auth", "captured", 100, "AUTH", f"auth_{sid}")]  # the refundable rupee is not a subscription payment
    assert biz.post("/review-growth/campaigns", json={"name": "Now allowed", "location_id": biz.location_id}).status_code == 201
    assert biz.post("/tenant/complete-onboarding").status_code == 200


def test_an_active_mandate_alone_never_marks_the_business_paid_and_the_one_rupee_is_not_revenue(mandate):
    def snap():
        db = SessionLocal(); set_rls_context(db, bypass=True)
        try:
            return finance.revenue(db)
        finally:
            db.close()
    before = snap()
    biz = make_business()
    mid = snap()
    assert mid["awaiting_authorization"]["value"] == before["awaiting_authorization"]["value"] + 1
    authorise(mandate, biz, "growth")
    after = snap()
    assert after["awaiting_authorization"]["value"] == before["awaiting_authorization"]["value"]
    assert after["mrr_paise"]["value"] == before["mrr_paise"]["value"] and sub_of(biz)["status"] == "trialing"
    assert after["subscription_cash_collected_paise"]["value"] == before["subscription_cash_collected_paise"]["value"]


# ----------------------------------------------------------------------------------------------------------------------------- failed, abandoned, retried
@pytest.mark.parametrize("dead", ["LINK_EXPIRED", "EXPIRED", "CANCELLED", "CUSTOMER_CANCELLED"])
def test_an_abandoned_or_failed_authorisation_leaves_the_account_without_a_trial_and_can_be_retried(mandate, dead):
    biz = make_business()
    start(biz, "growth")
    old = sub_of(biz)["cashfree_subscription_id"]
    mandate.set_status(old, dead)
    sync(biz)
    s = sub_of(biz)
    assert s["status"] == "incomplete" and s["trial_ends_at"] is None and s["pending_plan"] is None and s["authorization_status"] in ("expired", "cancelled")
    assert info(biz)["active"] is False and info(biz)["billing_state"] == "authorization_required"
    retry = start(biz, "growth")
    assert retry.status_code == 200 and sub_of(biz)["cashfree_subscription_id"] != old and mandate.n("create") == 2
    assert not any(c[0] == "cancel" for c in mandate.calls)  # the dead one was already finished at Cashfree: nothing to close
    sid = sub_of(biz)["cashfree_subscription_id"]
    mandate.set_status(sid, "ACTIVE"); mandate.pay(sid, f"auth_{sid}", "AUTH", "SUCCESS", 100)
    sync(biz)
    assert sub_of(biz)["status"] == "trialing"


def test_leaving_checkout_open_and_choosing_again_reuses_it_and_a_different_plan_closes_it_first(mandate):
    biz = make_business()
    a = start(biz, "growth").json()
    b = start(biz, "growth").json()
    assert b["reused"] is True and b["subscription_session_id"] == a["subscription_session_id"] and mandate.n("create") == 1
    first = sub_of(biz)["cashfree_subscription_id"]
    c = start(biz, "pro")
    assert c.status_code == 200 and ("cancel", first) in mandate.calls and sub_of(biz)["pending_plan"] == "pro" and sub_of(biz)["status"] == "incomplete"


def test_a_second_authorisation_cannot_be_started_once_one_is_confirmed(mandate):
    biz = make_business()
    authorise(mandate, biz, "growth")
    r = start(biz, "pro")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_subscribed" and mandate.n("create") == 1


def test_cancelling_before_the_trial_started_just_returns_to_plan_selection(mandate):
    biz = make_business()
    start(biz, "growth")
    sid = sub_of(biz)["cashfree_subscription_id"]
    r = biz.post("/billing/subscription/cancel", json={"at_cycle_end": True})
    assert r.status_code == 200 and ("cancel", sid) in mandate.calls
    s = sub_of(biz)
    assert s["status"] == "incomplete" and s["authorization_status"] == "cancelled" and s["pending_plan"] is None and s["canceled_at"] is None
    assert "authorization_cancelled" in events_of(biz) and start(biz, "growth").status_code == 200


def test_an_authorisation_that_arrives_too_late_for_the_trial_is_closed_not_charged_without_a_trial(mandate):
    biz = make_business()
    start(biz, "growth")
    sid = sub_of(biz)["cashfree_subscription_id"]
    imminent = utcnow() + timedelta(hours=12)  # the checkout sat open for days: the day-8 charge is now imminent (at Cashfree too)
    set_sub(biz, first_charge_at=imminent)
    mandate.subs[sid]["first"] = imminent
    mandate.set_status(sid, "ACTIVE"); mandate.pay(sid, f"auth_{sid}", "AUTH", "SUCCESS", 100)
    sync(biz)
    s = sub_of(biz)
    assert s["status"] == "incomplete" and s["trial_ends_at"] is None and s["authorization_status"] == "cancelled" and ("cancel", sid) in mandate.calls
    assert "authorization_stale" in events_of(biz)


def test_reauthorising_after_the_customer_paused_the_mandate_closes_the_old_one_first(mandate):
    biz = make_business()
    old = authorise(mandate, biz, "growth")
    mandate.set_status(old, "CUSTOMER_PAUSED")
    sync(biz)
    assert sub_of(biz)["authorization_status"] == "paused" and sub_of(biz)["status"] == "trialing"
    r = start(biz, "growth")
    assert r.status_code == 200 and ("cancel", old) in mandate.calls  # a mandate the customer resumes later can never be charged next to the new one
    assert sub_of(biz)["cashfree_subscription_id"] != old and sub_of(biz)["status"] == "trialing" and "mandate_replaced" in events_of(biz)


def test_reauthorising_is_refused_if_the_old_mandate_cannot_be_closed(mandate):
    biz = make_business()
    old = authorise(mandate, biz, "growth")
    mandate.set_status(old, "CUSTOMER_PAUSED")
    sync(biz)
    mandate.fail_cancel = True
    r = start(biz, "growth")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "mandate_change_failed" and mandate.n("create") == 1 and sub_of(biz)["cashfree_subscription_id"] == old


# ----------------------------------------------------------------------------------------------------------------------------- the rest of the lifecycle after a gated trial
def test_the_whole_gated_journey_authorise_trial_first_charge_second_charge(mandate):
    biz = make_business()
    sid = authorise(mandate, biz, "starter")
    assert sub_of(biz)["status"] == "trialing"
    mandate.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=38))
    r = charge(mandate, biz, sid, 49900, pid="first")
    s = sub_of(biz)
    assert r.status_code == 200 and (s["status"], s["plan"], s["pending_plan"], s["source"]) == ("active", "starter", None, "cashfree") and s["trial_ends_at"] is None
    mandate.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=68))
    charge(mandate, biz, sid, 49900, pid="second")
    assert sub_of(biz)["status"] == "active" and events_of(biz).count("activated") == 1 and events_of(biz).count("renewed") == 1
    assert info(biz)["plan_name"] == "Launch" and info(biz)["limits"]["review_generations"] == 200


def test_a_failed_card_payment_can_be_retried_by_the_owner_within_cashfrees_limits(mandate):
    biz = make_business()
    sid = authorise(mandate, biz, "growth")
    mandate.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    charge(mandate, biz, sid, 79900, pid="ok1")
    assert biz.post("/billing/subscription/retry-payment").status_code == 409  # nothing has failed yet
    mandate.set_status(sid, "ON_HOLD")
    charge(mandate, biz, sid, 79900, pid="bad1", status="FAILED", reason="DEBIT FAILED", method="card")
    assert sub_of(biz)["status"] == "past_due"
    first = biz.post("/billing/subscription/retry-payment")
    assert first.status_code == 200 and first.json()["requested"] is True and mandate.n("retry") == 1
    second = biz.post("/billing/subscription/retry-payment")
    assert second.json()["requested"] is False and mandate.n("retry") == 1 and "once a day" in second.json()["message"]


def test_a_upi_failure_is_left_to_cashfrees_own_retries(mandate):
    biz = make_business()
    sid = authorise(mandate, biz, "growth")
    mandate.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    charge(mandate, biz, sid, 79900, pid="ok2")
    mandate.set_status(sid, "ON_HOLD")
    charge(mandate, biz, sid, 79900, pid="bad2", status="FAILED", reason="x", method="upi")
    r = biz.post("/billing/subscription/retry-payment")
    assert r.status_code == 200 and r.json()["requested"] is False and mandate.n("retry") == 0


# ----------------------------------------------------------------------------------------------------------------------------- who is affected
def test_businesses_that_existed_before_the_gate_keep_their_running_trial(mandate, monkeypatch):
    monkeypatch.setattr(settings, "trial_requires_mandate", False)
    old = make_business()
    monkeypatch.setattr(settings, "trial_requires_mandate", True)
    assert sub_of(old)["status"] == "trialing" and info(old)["active"] is True
    assert old.post("/review-growth/campaigns", json={"name": "Still fine", "location_id": old.location_id}).status_code == 201


@pytest.mark.parametrize("provider,flag", [("", True), ("cashfree", False)])
def test_without_the_gate_a_new_business_gets_the_trial_as_before(monkeypatch, provider, flag):
    monkeypatch.setattr(settings, "billing_provider", provider)
    monkeypatch.setattr(settings, "trial_requires_mandate", flag)
    biz = make_business()
    assert sub_of(biz)["status"] == "trialing" and sub_of(biz)["trial_ends_at"] is not None and info(biz)["active"] is True


def test_cashfree_switched_on_without_credentials_does_not_lock_everyone_out(monkeypatch):
    monkeypatch.setattr(settings, "billing_provider", "cashfree")
    monkeypatch.setattr(settings, "cashfree_client_id", "")
    monkeypatch.setattr(settings, "cashfree_client_secret", "")
    monkeypatch.setattr(settings, "trial_requires_mandate", True)
    assert settings.mandate_required is False
    assert sub_of(make_business())["status"] == "trialing"


def test_one_business_cannot_see_or_move_anothers_checkout_or_trial(mandate):
    a = make_business()
    b = make_business()
    sid_a = authorise(mandate, a, "growth")
    assert sub_of(b)["status"] == "incomplete"
    assert b.post("/billing/subscription/sync").status_code == 404 and sub_of(b)["status"] == "incomplete"
    assert b.get("/billing/subscription/preview?plan=growth").json()["amount_paise"] == 79900
    assert deliver(sid_a, "SUBSCRIPTION_STATUS_CHANGED", status="ACTIVE").status_code == 200 and sub_of(b)["status"] == "incomplete"
    assert sub_of(a)["cashfree_subscription_id"] == sid_a and sub_of(b)["cashfree_subscription_id"] is None


def test_the_return_page_is_used_once_onboarding_is_finished(mandate):
    biz = make_business()
    owner_exec("UPDATE tenants SET onboarding_completed = true WHERE id = :t", t=biz.tenant_id)
    assert start(biz, "growth").status_code == 200
    created = [c for c in mandate.calls if c[0] == "create"][0][1]
    assert "/settings/billing/return?s=fqs_" in created["return_url"]


def test_reconciliation_starts_the_trial_for_an_authorisation_whose_webhook_never_arrived(mandate):
    from app.services import billing_cashfree as cfb
    biz = make_business()
    start(biz, "growth")
    sid = sub_of(biz)["cashfree_subscription_id"]
    mandate.set_status(sid, "ACTIVE"); mandate.pay(sid, f"auth_{sid}", "AUTH", "SUCCESS", 100)
    set_sub(biz, last_provider_sync_at=utcnow() - timedelta(hours=2))
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        cfb.reconcile(db, mandate)
    finally:
        db.close()
    assert sub_of(biz)["status"] == "trialing" and info(biz)["active"] is True
