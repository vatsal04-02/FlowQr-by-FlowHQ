"""Cashfree recurring billing through the real application and PostgreSQL. Cashfree itself is a TEST DOUBLE (FakeCashfree) behind the same interface; webhooks are signed with the real
documented algorithm. Nothing here talks to Cashfree. These tests prove how FlowQR behaves; they do NOT prove that Cashfree's sandbox behaves the same: see docs/CASHFREE_SANDBOX_TEST.md."""
import json
import time
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.main import app
from app.models.base import utcnow
from app.services import billing as billing_svc
from app.services import billing_cashfree as cfb
from app.services import cashfree as cf
from app.services import finance
from app.services.mailer import OUTBOX
from tests.conftest import make_business, make_user, owner_exec, owner_query

WH = "cf_webhook_secret_for_tests"


class FakeCashfree:
    """TEST DOUBLE for Cashfree's HTTP API. It keeps the provider's truth (statuses and payments); the tests change that truth, FlowQR reads it."""

    def __init__(self):
        self.plans, self.subs, self.payments, self.calls = {}, {}, {}, []
        self.fail_fetch = self.fail_cancel = self.fail_create = False

    def ensure_plan(self, *, plan_id, name, amount_paise, max_amount_paise):
        self.calls.append(("ensure_plan", plan_id, amount_paise, max_amount_paise))
        self.plans[plan_id] = amount_paise
        return cf.PlanResult(plan_id, "ACTIVE", amount_paise, max_amount_paise)

    def create_subscription(self, **kw):
        if self.fail_create:
            raise cf.CashfreeError(500, "api_error", "boom")
        sid = kw["subscription_id"]
        self.calls.append(("create", kw))
        self.subs[sid] = {"status": "INITIALIZED", "plan_id": kw["plan_id"], "cf_id": str(900 + len(self.subs)), "session": f"sess_{sid}", "first": kw["first_charge_at"], "next": None}
        return self._res(sid)

    def _res(self, sid):
        s = self.subs[sid]
        return cf.SubscriptionResult(sid, s["cf_id"], s["status"], s["session"], s["plan_id"], s["first"], s["next"], None)

    def fetch_subscription(self, sid):
        if self.fail_fetch:
            raise cf.CashfreeError(503, "network_error", "down")
        self.calls.append(("fetch", sid))
        return self._res(sid)

    def list_payments(self, sid):
        return list(self.payments.get(sid, {}).values())

    def cancel_subscription(self, sid):
        if self.fail_cancel:
            raise cf.CashfreeError(500, "api_error", "boom")
        self.calls.append(("cancel", sid))
        self.subs[sid]["status"] = "CANCELLED"

    def change_plan(self, sid, plan_id):
        self.calls.append(("change_plan", sid, plan_id))
        self.subs[sid]["plan_id"] = plan_id

    def retry_payment(self, sid, payment_id, on):
        self.calls.append(("retry", sid, payment_id, on))

    # --- the provider's side of the story
    def set_status(self, sid, status, next_charge=None):
        self.subs[sid]["status"] = status
        if next_charge is not None:
            self.subs[sid]["next"] = next_charge

    def pay(self, sid, pid, ptype, status, amount_paise, *, method="upi", when=None, reason=None, retries=0):
        when = when or utcnow()
        self.payments.setdefault(sid, {})[pid] = cf.PaymentResult(pid, f"cf{abs(hash(pid)) % 10**6}", ptype, status, amount_paise, when, when, reason, method, retries)

    def n(self, name):
        return sum(1 for c in self.calls if c[0] == name)


@pytest.fixture()
def cfree(monkeypatch):
    f = FakeCashfree()
    for k, v in {"billing_provider": "cashfree", "cashfree_env": "sandbox", "cashfree_client_id": "test_client_id", "cashfree_client_secret": "test_client_secret", "cashfree_webhook_secret": WH,
                 "razorpay_key_id": "", "razorpay_key_secret": "", "razorpay_webhook_secret": "",
                 "trial_requires_mandate": False}.items():  # these tests start from a running trial; the mandatory-authorisation gate has its own file (test_cashfree_mandate_gate.py)
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(cf, "get_cashfree", lambda: f)
    owner_exec("DELETE FROM payments WHERE cashfree_payment_id IS NOT NULL")  # provider payment ids are globally unique; tests reuse readable ones
    owner_exec("UPDATE subscriptions SET last_provider_sync_at = now() WHERE cashfree_subscription_id IS NOT NULL")  # subscriptions left by earlier tests are unknown to this fake: reconcile must skip them
    return f


# ----------------------------------------------------------------------------------------------------------------------------- helpers
def sub_of(biz) -> dict:
    cols = ("status, plan, source, provider, authorization_status, cashfree_subscription_id, pending_plan, past_due_since, trial_ends_at, first_charge_at, next_charge_at, current_period_end, "
            "cancel_at_period_end, canceled_at, last_provider_sync_at")
    row = owner_query(f"SELECT {cols} FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0]
    return dict(zip([c.strip() for c in cols.split(",")], row))


def set_sub(biz, **kw):
    owner_exec("UPDATE subscriptions SET " + ", ".join(f"{k} = :{k}" for k in kw) + " WHERE tenant_id = :t", t=biz.tenant_id, **kw)


def payments_of(biz):
    return owner_query("SELECT kind, status, amount_paise, payment_type, cashfree_payment_id FROM payments WHERE tenant_id = :t ORDER BY created_at, cashfree_payment_id", t=biz.tenant_id)


def events_of(biz, kind=None):
    q = "SELECT kind FROM subscription_events WHERE tenant_id = :t" + (" AND kind = :k" if kind else "") + " ORDER BY created_at"
    return [r[0] for r in owner_query(q, t=biz.tenant_id, **({"k": kind} if kind else {}))]


def start(biz, plan="growth", phone="9876543210", **extra):
    return biz.post("/billing/subscription/checkout", json={"plan": plan, "phone": phone, **extra})


def sync(biz):
    return biz.post("/billing/subscription/sync")


def authorized(cfree, plan="growth", **bkw):
    """A business that has chosen a plan and authorised the mandate (and paid the refundable authorisation) but has not been charged yet."""
    biz = make_business(**bkw)
    r = start(biz, plan)
    assert r.status_code == 200, r.text
    sid = sub_of(biz)["cashfree_subscription_id"]
    cfree.set_status(sid, "ACTIVE")
    cfree.pay(sid, f"auth_{sid}", "AUTH", "SUCCESS", 100)
    assert sync(biz).status_code == 200
    return biz, sid


def charge(cfree, biz, sid, amount, pid=None, status="SUCCESS", **kw):
    cfree.pay(sid, pid or f"chg_{uuid.uuid4().hex[:8]}", "CHARGE", status, amount, **kw)
    return sync(biz)


def deliver(sid, etype="SUBSCRIPTION_PAYMENT_SUCCESS", *, pid="pay-x", status="SUCCESS", secret=WH, ts=None, event_time=None, body=None):
    if body is None:
        if etype == "SUBSCRIPTION_STATUS_CHANGED":
            data = {"subscription_details": {"subscription_id": sid, "subscription_status": status}}
        else:
            data = {"payment_id": pid, "subscription_id": sid, "payment_status": status, "payment_type": "CHARGE", "payment_amount": 799.0}
        body = {"type": etype, "event_time": event_time or utcnow().isoformat(), "data": data}
    raw = json.dumps(body).encode()
    ts = ts or str(int(time.time() * 1000))
    return TestClient(app, base_url="http://testserver").post("/api/v1/webhooks/cashfree", content=raw, headers={
        "x-webhook-signature": cf.sign_webhook(raw, ts, secret), "x-webhook-timestamp": ts, "content-type": "application/json"})


def webhook_rows(sid):
    return owner_query("SELECT event_type, status, attempts, last_error, payload_hash FROM webhook_events WHERE subscription_ref = :s ORDER BY received_at", s=sid)


# ----------------------------------------------------------------------------------------------------------------------------- plans, names, prices
def test_plans_are_launch_growth_scale_with_stable_codes_and_the_confirmed_prices(cfree):
    r = TestClient(app, base_url="http://testserver").get("/api/v1/billing/plans").json()
    assert [(p["code"], p["name"], p["price_paise"]) for p in r["plans"]] == [("starter", "Launch", 49900), ("growth", "Growth", 79900), ("pro", "Scale", 149900)]
    assert r["billing"]["provider"] == "cashfree" and r["billing"]["configured"] is True and r["billing"]["key_id"] is None and r["billing"]["authorization_paise"] == 100
    assert "test_client_secret" not in json.dumps(r) and "test_client_id" not in json.dumps(r)
    assert r["trial_days"] == settings.trial_days


# ----------------------------------------------------------------------------------------------------------------------------- checkout
def test_checkout_prices_the_plan_on_the_server_and_asks_cashfree_for_a_refundable_one_rupee_authorisation(cfree):
    biz = make_business()
    r = start(biz, "growth", price_paise=1, amount=1, currency="USD")  # the browser's idea of a price is ignored (or refused)
    assert r.status_code in (200, 422)
    if r.status_code == 422:
        r = start(biz, "growth")
    out = r.json()
    assert out["amount_paise"] == 79900 and out["plan_name"] == "Growth" and out["authorization_paise"] == 100 and out["authorization_refunded"] is True
    assert out["subscription_session_id"].startswith("sess_fqs_") and out["environment"] == "sandbox" and out["methods"] == ["upi", "card"]
    ensure = [c for c in cfree.calls if c[0] == "ensure_plan"][0]
    assert ensure[2] == 79900 and ensure[3] == 149900  # the mandate ceiling is the highest plan price, so plan changes never need a new authorisation
    created = [c for c in cfree.calls if c[0] == "create"][0][1]
    assert created["authorization_paise"] == 100 and created["refund_authorization"] is True and created["methods"] == ["upi", "card"]
    assert created["customer"].phone == "9876543210" and created["return_url"] == settings.frontend_url.rstrip("/") + "/onboarding?checkout=return"  # the business is still being set up: the customer comes back into onboarding
    s = sub_of(biz)
    assert s["status"] == "trialing" and s["provider"] == "cashfree" and s["authorization_status"] == "initialized" and s["pending_plan"] == "growth"
    assert s["cashfree_subscription_id"].startswith("fqs_") and s["plan"] == "trial"  # nothing is granted by starting a checkout
    # the first charge is the end of the free trial, not today
    assert abs((s["first_charge_at"] - s["trial_ends_at"]).total_seconds()) < 60
    assert out["free_period_honoured"] is True


def test_first_charge_is_at_trial_end_and_a_business_with_no_free_period_left_waits_two_days(cfree):
    trial = make_business()
    assert start(trial, "starter").status_code == 200
    s = sub_of(trial)
    assert abs((s["first_charge_at"] - s["trial_ends_at"]).total_seconds()) < 60 and 6 <= (s["first_charge_at"] - utcnow()).days <= 7
    over = make_business()
    set_sub(over, status="expired", trial_ends_at=utcnow() - timedelta(days=2))
    r = start(over, "growth")
    assert r.status_code == 200 and r.json()["free_period_honoured"] is False
    s2 = sub_of(over)
    assert s2["status"] == "pending"
    # The first charge is "two days ahead, at 10:00 India time". Counting from the moment of the request that is 58h minus the India time of day, so it is anywhere between 34 and 58 hours (1.42 to 2.42 days)
    # whatever the hour the test runs at (a fixed 1.5-day lower bound failed after about 22:00 India time). billing_cashfree.first_charge_at_for is unchanged.
    assert 1.41 < (s2["first_charge_at"] - utcnow()).total_seconds() / 86400 < 2.43
    assert s2["first_charge_at"].hour == 4 and s2["first_charge_at"].minute == 30  # 10:00 India time


def test_a_free_period_more_than_thirteen_days_away_cannot_be_scheduled_and_says_when_to_come_back(cfree):
    biz = make_business()
    set_sub(biz, trial_ends_at=utcnow() + timedelta(days=20))
    r = start(biz, "growth")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "too_early" and "earliest" in r.json()["detail"]
    assert cfree.n("create") == 0 and sub_of(biz)["cashfree_subscription_id"] is None


def test_checkout_needs_a_mobile_number_an_active_plan_and_a_verified_owner(cfree):
    biz = make_business()
    r = biz.post("/billing/subscription/checkout", json={"plan": "growth"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "phone_required"
    assert start(biz, "essential").status_code == 404  # a retired plan cannot be bought
    assert start(biz, "nonsense").status_code == 404
    unverified = make_user(verify=False)
    assert unverified.post("/tenants", json={"name": "Unverified Co", "category": "Physiotherapy clinic", "language": "en"}).status_code in (201, 403)


def test_the_same_plan_twice_reuses_one_open_checkout_and_a_different_plan_closes_the_old_one(cfree):
    biz = make_business()
    first = start(biz, "growth").json()
    again = start(biz, "growth").json()
    assert again["reused"] is True and again["subscription_session_id"] == first["subscription_session_id"] and cfree.n("create") == 1
    sid_old = sub_of(biz)["cashfree_subscription_id"]
    switched = start(biz, "pro")
    assert switched.status_code == 200 and cfree.n("cancel") == 1 and ("cancel", sid_old) in cfree.calls
    assert sub_of(biz)["cashfree_subscription_id"] != sid_old and sub_of(biz)["pending_plan"] == "pro"
    assert "checkout_replaced" in events_of(biz)


def test_a_different_plan_is_refused_if_the_old_open_checkout_cannot_be_closed(cfree):
    biz = make_business()
    start(biz, "growth")
    cfree.fail_cancel = True
    r = start(biz, "pro")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "checkout_in_progress"
    assert sub_of(biz)["pending_plan"] == "growth"


def test_a_second_mandate_cannot_be_started_once_one_is_authorised(cfree):
    biz, sid = authorized(cfree)
    r = start(biz, "pro")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_subscribed" and cfree.n("create") == 1


def test_a_provider_failure_creates_nothing_and_leaks_nothing(cfree):
    biz = make_business()
    cfree.fail_create = True
    r = start(biz, "growth")
    assert r.status_code == 502 and "boom" not in r.text and "test_client" not in r.text
    assert sub_of(biz)["cashfree_subscription_id"] is None and sub_of(biz)["pending_plan"] is None


def test_cashfree_billing_is_off_unless_the_provider_is_switched_on(monkeypatch):
    monkeypatch.setattr(settings, "billing_provider", "")
    biz = make_business()
    r = start(biz, "growth")
    assert r.status_code == 503  # the legacy path answers "payments are not configured": nothing new was switched on
    assert TestClient(app, base_url="http://testserver").post("/api/v1/webhooks/cashfree", content=b"{}").status_code == 404


# ----------------------------------------------------------------------------------------------------------------------------- authorising is not paying
def test_an_authorised_mandate_keeps_the_trial_running_and_the_one_rupee_is_not_revenue(cfree):
    biz, sid = authorized(cfree)
    s = sub_of(biz)
    assert s["status"] == "trialing" and s["authorization_status"] == "authorized" and s["plan"] == "trial" and s["trial_ends_at"] is not None
    api = biz.get("/billing/subscription").json()
    assert api["active"] is True and api["billing_state"] == "trialing" and api["pending_plan"] == "growth" and api["has_cashfree_subscription"] is True
    pays = payments_of(biz)
    assert pays == [("sub_auth", "captured", 100, "AUTH", f"auth_{sid}")]  # its own kind: every revenue query filters kind == 'subscription', so it can never be counted
    assert [p for p in biz.get("/billing/payments").json() if p["kind"] == "sub_auth"][0]["payment_type"] == "AUTH"
    assert "activated" not in events_of(biz)


def test_cashfree_active_alone_never_makes_a_business_paid(cfree):
    biz, sid = authorized(cfree)
    cfree.set_status(sid, "ACTIVE")
    assert sync(biz).status_code == 200
    assert sub_of(biz)["status"] == "trialing" and sub_of(biz)["plan"] == "trial"
    over = make_business()
    set_sub(over, status="expired", trial_ends_at=utcnow() - timedelta(days=1))
    start(over, "growth")
    sid2 = sub_of(over)["cashfree_subscription_id"]
    cfree.set_status(sid2, "ACTIVE")
    sync(over)
    assert sub_of(over)["status"] == "pending" and over.get("/billing/subscription").json()["active"] is False  # mandate live, nothing collected: no access yet


def test_a_bank_approval_that_is_still_pending_is_shown_as_authorisation_pending(cfree):
    biz = make_business()
    start(biz, "growth")
    sid = sub_of(biz)["cashfree_subscription_id"]
    cfree.set_status(sid, "BANK_APPROVAL_PENDING")
    sync(biz)
    api = biz.get("/billing/subscription").json()
    assert sub_of(biz)["authorization_status"] == "bank_pending" and api["billing_state"] == "authorization_pending" and api["active"] is True  # the trial is untouched
    assert biz.get("/billing/subscription/status").json()["billing_state"] == "authorization_pending"


# ----------------------------------------------------------------------------------------------------------------------------- the first and every later charge
def test_a_verified_successful_charge_activates_the_chosen_plan_exactly_once(cfree):
    biz, sid = authorized(cfree, "growth")
    nxt = utcnow() + timedelta(days=30)
    cfree.set_status(sid, "ACTIVE", next_charge=nxt)
    r = charge(cfree, biz, sid, 79900, pid="chg_first")
    assert r.status_code == 200 and r.json()["status"] == "active"
    s = sub_of(biz)
    assert (s["status"], s["plan"], s["source"], s["provider"], s["pending_plan"], s["trial_ends_at"]) == ("active", "growth", "cashfree", "cashfree", None, None)
    assert abs((s["current_period_end"] - nxt).total_seconds()) < 2 and s["past_due_since"] is None
    assert sync(biz).status_code == 200 and sync(biz).status_code == 200  # the same answer applied again changes nothing
    assert events_of(biz).count("activated") == 1 and events_of(biz).count("renewed") == 0
    assert [p for p in payments_of(biz) if p[0] == "subscription"] == [("subscription", "captured", 79900, "CHARGE", "chg_first")]
    api = biz.get("/billing/subscription").json()
    assert api["plan_name"] == "Growth" and api["active"] is True and api["billing_state"] == "active" and api["limits"]["review_generations"] == 300


def test_the_next_months_charge_renews_and_moves_the_period(cfree):
    biz, sid = authorized(cfree, "starter")
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    charge(cfree, biz, sid, 49900, pid="m1")
    end1 = sub_of(biz)["current_period_end"]
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=60))
    charge(cfree, biz, sid, 49900, pid="m2")
    assert sub_of(biz)["status"] == "active" and sub_of(biz)["current_period_end"] > end1 + timedelta(days=20)
    assert events_of(biz).count("activated") == 1 and events_of(biz).count("renewed") == 1


def test_a_charge_for_an_amount_nobody_can_explain_changes_no_entitlements(cfree):
    biz, sid = authorized(cfree, "growth")
    charge(cfree, biz, sid, 12345, pid="odd")
    assert sub_of(biz)["status"] == "trialing" and sub_of(biz)["plan"] == "trial"
    assert "amount_mismatch" in events_of(biz)


def test_failed_pending_and_dropped_charges_never_activate(cfree):
    biz, sid = authorized(cfree, "growth")
    for i, st in enumerate(("PENDING", "INITIALIZED", "USER_DROPPED", "CANCELLED")):
        charge(cfree, biz, sid, 79900, pid=f"x{i}", status=st)
        assert sub_of(biz)["status"] != "active"


# ----------------------------------------------------------------------------------------------------------------------------- failure, grace, recovery
def test_a_failed_charge_starts_the_seven_day_grace_notifies_the_owner_and_keeps_access_until_it_ends(cfree):
    biz, sid = authorized(cfree, "growth")
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    charge(cfree, biz, sid, 79900, pid="ok1")
    before = len(OUTBOX)
    cfree.set_status(sid, "ON_HOLD")
    r = charge(cfree, biz, sid, 79900, pid="bad1", status="FAILED", reason="DEBIT FAILED | Insufficient Funds", method="card")
    assert r.status_code == 200
    s = sub_of(biz)
    assert s["status"] == "past_due" and s["past_due_since"] is not None and settings.past_due_grace_days == 7
    api = biz.get("/billing/subscription").json()
    assert api["active"] is True and api["billing_state"] == "past_due" and api["grace_until"] is not None
    mails = [m for m in OUTBOX[before:] if "didn't go through" in m["subject"]]
    assert len(mails) == 1 and "Insufficient" in mails[0]["body"] and "/settings/billing" in mails[0]["body"]
    assert [p for p in payments_of(biz) if p[1] == "failed"] == [("subscription", "failed", 79900, "CHARGE", "bad1")]
    sync(biz); sync(biz)
    assert len([m for m in OUTBOX[before:] if "didn't go through" in m["subject"]]) == 1  # one notice, not one per sync
    assert "payment_failed" in events_of(biz)
    set_sub(biz, past_due_since=utcnow() - timedelta(days=8))
    assert biz.get("/billing/subscription").json()["active"] is False  # the grace period does not give unlimited access


def test_the_housekeeping_job_halts_a_subscription_whose_grace_has_ended(cfree):
    biz, sid = authorized(cfree, "growth")
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    charge(cfree, biz, sid, 79900, pid="ok2")
    cfree.set_status(sid, "ON_HOLD")
    charge(cfree, biz, sid, 79900, pid="bad2", status="FAILED", reason="x")
    set_sub(biz, past_due_since=utcnow() - timedelta(days=8))
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        assert billing_svc.refresh_statuses(db)["lapsed_past_due"] >= 1
    finally:
        db.close()
    assert sub_of(biz)["status"] == "halted"


def test_a_later_successful_charge_restores_paid_access(cfree):
    biz, sid = authorized(cfree, "growth")
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    charge(cfree, biz, sid, 79900, pid="ok3")
    cfree.set_status(sid, "ON_HOLD")
    charge(cfree, biz, sid, 79900, pid="bad3", status="FAILED", reason="x")
    assert sub_of(biz)["status"] == "past_due"
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    charge(cfree, biz, sid, 79900, pid="retry3")
    s = sub_of(biz)
    assert s["status"] == "active" and s["past_due_since"] is None


def test_a_failed_card_charge_is_retried_through_cashfree_at_most_once_a_day_and_three_times_a_cycle_while_upi_is_left_to_cashfree(cfree):
    def failing(method, retries=0):
        biz, sid = authorized(cfree, "growth")
        cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
        charge(cfree, biz, sid, 79900, pid=f"ok_{method}{retries}")
        cfree.set_status(sid, "ON_HOLD")
        charge(cfree, biz, sid, 79900, pid=f"bad_{method}{retries}", status="FAILED", reason="x", method=method, retries=retries)
        set_sub(biz, last_provider_sync_at=utcnow() - timedelta(hours=2))
        return biz, sid

    def run():
        db = SessionLocal(); set_rls_context(db, bypass=True)
        try:
            return cfb.reconcile(db, cfree)
        finally:
            db.close()
    card, csid = failing("card")
    n0 = cfree.n("retry")
    assert run()["retries_requested"] >= 1 and cfree.n("retry") == n0 + 1 and ("retry", csid) == cfree.calls[-1][:2]
    set_sub(card, last_provider_sync_at=utcnow() - timedelta(hours=2))
    n1 = cfree.n("retry")
    run()
    assert cfree.n("retry") == n1  # not twice within a day
    upi, usid = failing("upi")
    n2 = cfree.n("retry")
    run()
    assert not any(c[0] == "retry" and c[1] == usid for c in cfree.calls[n2:])  # UPI AutoPay retries by itself
    maxed, msid = failing("card", retries=3)
    n3 = cfree.n("retry")
    run()
    assert not any(c[0] == "retry" and c[1] == msid for c in cfree.calls[n3:])
    assert "retry_requested" in events_of(card)


# ----------------------------------------------------------------------------------------------------------------------------- the settlement window and the trial
def test_access_continues_while_the_first_charge_is_settling_then_stops(cfree):
    biz, sid = authorized(cfree, "growth")
    set_sub(biz, trial_ends_at=utcnow() - timedelta(hours=1), first_charge_at=utcnow() - timedelta(hours=1))
    assert biz.get("/billing/subscription").json()["active"] is True  # the payment is due and in flight: nobody who is paying is locked out
    set_sub(biz, first_charge_at=utcnow() - timedelta(hours=settings.cashfree_charge_settlement_hours + 1))
    assert biz.get("/billing/subscription").json()["active"] is False
    unauthorised = make_business()
    start(unauthorised, "growth")
    set_sub(unauthorised, trial_ends_at=utcnow() - timedelta(hours=1), first_charge_at=utcnow() - timedelta(hours=1))
    assert unauthorised.get("/billing/subscription").json()["active"] is False  # a checkout that was never authorised extends nothing


def test_housekeeping_does_not_expire_a_trial_whose_authorised_first_charge_is_settling(cfree):
    biz, sid = authorized(cfree, "growth")
    set_sub(biz, trial_ends_at=utcnow() - timedelta(hours=1), first_charge_at=utcnow() - timedelta(hours=1))
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        billing_svc.refresh_statuses(db)
    finally:
        db.close()
    assert sub_of(biz)["status"] == "trialing"
    set_sub(biz, first_charge_at=utcnow() - timedelta(hours=60))
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        billing_svc.refresh_statuses(db)
    finally:
        db.close()
    assert sub_of(biz)["status"] == "expired"


def test_the_seven_day_trial_and_its_start_date_are_recorded_for_a_new_business():
    biz = make_business()
    row = owner_query("SELECT trial_started_at, trial_ends_at FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0]
    assert row[0] is not None and abs((row[1] - row[0]).days - settings.trial_days) <= 1


# ----------------------------------------------------------------------------------------------------------------------------- cancellation
def test_cancelling_during_the_trial_stops_all_charges_and_keeps_the_free_days(cfree):
    biz, sid = authorized(cfree, "growth")
    r = biz.post("/billing/subscription/cancel", json={"at_cycle_end": True})
    assert r.status_code == 200 and r.json()["cancel_at_period_end"] is True and ("cancel", sid) in cfree.calls
    s = sub_of(biz)
    assert s["status"] == "canceled" and s["authorization_status"] == "cancelled" and s["pending_plan"] is None
    api = biz.get("/billing/subscription").json()
    assert api["active"] is True and api["billing_state"] == "cancellation_pending"  # the days that were free stay free
    set_sub(biz, current_period_end=utcnow() - timedelta(minutes=1))
    assert biz.get("/billing/subscription").json()["active"] is False
    assert start(biz, "growth").status_code in (200, 409)


def test_cancelling_a_paid_subscription_keeps_access_to_the_end_of_the_paid_month(cfree):
    biz, sid = authorized(cfree, "growth")
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=25))
    charge(cfree, biz, sid, 79900, pid="ok4")
    assert biz.post("/billing/subscription/cancel", json={"at_cycle_end": True}).status_code == 200
    api = biz.get("/billing/subscription").json()
    assert api["active"] is True and api["status"] == "canceled" and api["billing_state"] == "cancellation_pending" and api["plan"] == "growth"
    assert "cancel_requested" in events_of(biz)


def test_a_cancellation_that_cashfree_refuses_changes_nothing(cfree):
    biz, sid = authorized(cfree, "growth")
    cfree.fail_cancel = True
    r = biz.post("/billing/subscription/cancel", json={"at_cycle_end": True})
    assert r.status_code == 502 and sub_of(biz)["status"] == "trialing" and sub_of(biz)["authorization_status"] == "authorized"


def test_cancelling_when_there_is_nothing_to_cancel_is_refused(cfree):
    assert make_business().post("/billing/subscription/cancel", json={"at_cycle_end": True}).status_code == 409


def test_money_that_arrives_after_a_cancellation_never_silently_reactivates(cfree):
    biz, sid = authorized(cfree, "growth")
    biz.post("/billing/subscription/cancel", json={"at_cycle_end": True})
    charge(cfree, biz, sid, 79900, pid="late")
    assert sub_of(biz)["status"] == "canceled" and "charge_after_cancel" in events_of(biz)


def test_a_customer_who_cancels_in_their_upi_app_is_cancelled_here_too(cfree):
    biz, sid = authorized(cfree, "growth")
    cfree.set_status(sid, "CUSTOMER_CANCELLED")
    sync(biz)
    assert sub_of(biz)["status"] == "canceled" and sub_of(biz)["authorization_status"] == "cancelled"


# ----------------------------------------------------------------------------------------------------------------------------- plan changes: next billing cycle only
def test_a_plan_change_is_scheduled_for_the_next_charge_and_changes_nothing_today(cfree):
    biz, sid = authorized(cfree, "growth")
    nxt = utcnow() + timedelta(days=30)
    cfree.set_status(sid, "ACTIVE", next_charge=nxt)
    charge(cfree, biz, sid, 79900, pid="m1")
    r = biz.post("/billing/subscription/change-plan", json={"plan": "pro"})
    assert r.status_code == 200 and r.json()["pending_plan"] == "pro" and r.json()["plan"] == "growth"
    assert abs((cf_dt(r.json()["effective_at"]) - nxt).total_seconds()) < 5
    assert ("change_plan", sid, "flowqr-pro-149900") in cfree.calls and not any(c[0] == "cancel" for c in cfree.calls) and cfree.n("create") == 1
    api = biz.get("/billing/subscription").json()
    assert api["plan"] == "growth" and api["limits"]["locations"] == 1 and api["pending_plan_name"] == "Scale" and api["pending_plan_effective_at"] is not None
    assert [p for p in payments_of(biz) if p[0] == "subscription"] and len([p for p in payments_of(biz) if p[0] == "subscription"]) == 1  # no extra or prorated charge was made
    # the new plan applies only at the successful charge of the NEW amount
    charge(cfree, biz, sid, 79900, pid="stale_old_amount")
    assert sub_of(biz)["plan"] == "growth" and sub_of(biz)["pending_plan"] == "pro"
    cfree.set_status(sid, "ACTIVE", next_charge=nxt + timedelta(days=30))
    charge(cfree, biz, sid, 149900, pid="m2")
    s = sub_of(biz)
    assert s["plan"] == "pro" and s["pending_plan"] is None and s["status"] == "active"
    assert biz.get("/billing/subscription").json()["limits"]["locations"] == 10


def cf_dt(value):
    from datetime import datetime
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def test_a_downgrade_is_also_next_cycle_and_the_usage_guard_still_applies(cfree):
    biz, sid = authorized(cfree, "pro")
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    charge(cfree, biz, sid, 149900, pid="p1")
    assert biz.post("/locations", json={"name": "Second branch", "city": "Delhi", "review_url": "https://g.page/r/XYZ999/review"}).status_code == 201
    blocked = biz.post("/billing/subscription/change-plan", json={"plan": "starter"})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "downgrade_blocked"
    ok = biz.post("/billing/subscription/change-plan", json={"plan": "growth"})
    assert ok.status_code == 409  # Growth also includes one location
    assert sub_of(biz)["pending_plan"] is None


def test_a_scheduled_change_can_be_withdrawn_and_nonsense_changes_are_refused(cfree):
    biz, sid = authorized(cfree, "growth")
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    charge(cfree, biz, sid, 79900, pid="w1")
    assert biz.post("/billing/subscription/change-plan", json={"plan": "pro"}).status_code == 200
    assert biz.post("/billing/subscription/change-plan", json={"plan": "growth"}).status_code == 200  # back to the current plan
    assert sub_of(biz)["pending_plan"] is None
    assert biz.post("/billing/subscription/change-plan", json={"plan": "growth"}).status_code == 409  # already on it
    assert biz.post("/billing/subscription/change-plan", json={"plan": "essential"}).status_code == 404
    assert make_business().post("/billing/subscription/change-plan", json={"plan": "pro"}).status_code == 409  # no payment set up yet


def test_a_change_to_a_plan_above_the_mandate_ceiling_needs_a_new_authorisation(cfree, monkeypatch):
    biz, sid = authorized(cfree, "starter")
    monkeypatch.setattr(settings, "cashfree_plan_max_amount_paise", 79900)
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    charge(cfree, biz, sid, 49900, pid="c1")
    r = biz.post("/billing/subscription/change-plan", json={"plan": "pro"})
    assert r.status_code == 409 and "new payment authorisation" in r.json()["detail"]


# ----------------------------------------------------------------------------------------------------------------------------- provider statuses that are not "paid"
@pytest.mark.parametrize("remote,expect_status,expect_auth", [
    ("INITIALIZED", "trialing", "initialized"), ("BANK_APPROVAL_PENDING", "trialing", "bank_pending"), ("ACTIVE", "trialing", "authorized"),
    ("CUSTOMER_CANCELLED", "canceled", "cancelled"), ("CANCELLED", "canceled", "cancelled"), ("EXPIRED", "expired", "expired"),
    ("COMPLETED", "expired", "authorized"), ("LINK_EXPIRED", "trialing", "expired"),
])
def test_cashfree_subscription_statuses_map_to_the_right_flowqr_state(cfree, remote, expect_status, expect_auth):
    biz = make_business()
    start(biz, "growth")
    sid = sub_of(biz)["cashfree_subscription_id"]
    cfree.set_status(sid, remote)
    assert sync(biz).status_code == 200
    s = sub_of(biz)
    assert (s["status"], s["authorization_status"]) == (expect_status, expect_auth)
    if remote == "LINK_EXPIRED":
        assert s["pending_plan"] is None  # an abandoned checkout leaves the trial exactly as it was


def test_a_paused_mandate_or_expired_card_on_a_paying_business_starts_the_grace_period(cfree):
    for bad in ("PAUSED", "CUSTOMER_PAUSED", "CARD_EXPIRED"):
        biz, sid = authorized(cfree, "growth")
        cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
        charge(cfree, biz, sid, 79900, pid=f"ok_{bad}")
        cfree.set_status(sid, bad)
        sync(biz)
        assert sub_of(biz)["status"] == "past_due", bad


def test_an_unknown_status_changes_nothing(cfree):
    biz, sid = authorized(cfree, "growth")
    cfree.set_status(sid, "SOMETHING_NEW")
    sync(biz)
    assert sub_of(biz)["status"] == "trialing" and sub_of(biz)["authorization_status"] == "authorized"


# ----------------------------------------------------------------------------------------------------------------------------- the return page
def test_the_return_page_sync_asks_cashfree_and_ignores_whatever_the_url_says(cfree):
    biz = make_business()
    start(biz, "growth")
    sid = sub_of(biz)["cashfree_subscription_id"]
    forged = biz.post("/billing/subscription/sync?s=anything&status=SUCCESS&payment_status=SUCCESS")
    assert forged.status_code == 200 and forged.json()["status"] == "trialing" and sub_of(biz)["authorization_status"] == "initialized"
    cfree.set_status(sid, "ACTIVE")
    assert sync(biz).json()["authorization_status"] == "authorized"
    assert make_business().post("/billing/subscription/sync").status_code == 404  # another business has nothing to sync, and cannot reach this one's
    cfree.fail_fetch = True
    r = sync(biz)
    assert r.status_code == 502 and "down" not in r.text


# ----------------------------------------------------------------------------------------------------------------------------- webhooks
def test_a_webhook_without_a_valid_signature_or_with_a_stale_timestamp_changes_nothing(cfree):
    biz, sid = authorized(cfree, "growth")
    cfree.pay(sid, "w_ok", "CHARGE", "SUCCESS", 79900)
    assert deliver(sid, secret="wrong").status_code == 400
    assert deliver(sid, ts=str(int((time.time() - 600) * 1000))).status_code == 400
    c = TestClient(app, base_url="http://testserver")
    assert c.post("/api/v1/webhooks/cashfree", content=b"{}").status_code == 400
    assert c.post("/api/v1/webhooks/cashfree", content=b"x" * 70000, headers={"content-length": "70000"}).status_code == 413
    assert sub_of(biz)["status"] == "trialing" and webhook_rows(sid) == []


def test_a_signed_webhook_is_only_a_hint_the_state_follows_cashfree_not_the_payload(cfree):
    biz, sid = authorized(cfree, "growth")
    # the payload CLAIMS a successful charge, but Cashfree itself reports nothing: nothing is activated
    r = deliver(sid, pid="claimed", status="SUCCESS")
    assert r.status_code == 200 and r.json()["status"] == "processed"
    assert sub_of(biz)["status"] == "trialing" and not [p for p in payments_of(biz) if p[0] == "subscription"]
    # now Cashfree really has the payment
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    cfree.pay(sid, "claimed", "CHARGE", "SUCCESS", 79900)
    assert deliver(sid, pid="claimed", status="SUCCESS", event_time=utcnow().isoformat() + "Z").status_code == 200
    assert sub_of(biz)["status"] == "active"


def test_a_duplicate_delivery_is_acknowledged_once_processed_once(cfree):
    biz, sid = authorized(cfree, "growth")
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    cfree.pay(sid, "dup1", "CHARGE", "SUCCESS", 79900)
    et = utcnow().isoformat()
    fetches = cfree.n("fetch")
    assert deliver(sid, pid="dup1", event_time=et).json()["status"] == "processed"
    assert deliver(sid, pid="dup1", event_time=et).json()["status"] == "duplicate"
    assert deliver(sid, pid="dup1", event_time=et).json()["status"] == "duplicate"
    assert cfree.n("fetch") == fetches + 1  # the repeats never reached Cashfree
    rows = webhook_rows(sid)
    assert len(rows) == 1 and rows[0][1] == "processed" and rows[0][2] == 1 and len(rows[0][4]) == 64
    assert events_of(biz).count("activated") == 1 and len([p for p in payments_of(biz) if p[0] == "subscription"]) == 1


def test_a_failed_processing_is_stored_answers_500_and_a_redelivery_finishes_the_job(cfree):
    biz, sid = authorized(cfree, "growth")
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    cfree.pay(sid, "retry_me", "CHARGE", "SUCCESS", 79900)
    et = utcnow().isoformat()
    cfree.fail_fetch = True
    r = deliver(sid, pid="retry_me", event_time=et)
    assert r.status_code == 500 and "down" not in r.text
    row = webhook_rows(sid)[0]
    assert row[1] == "failed" and row[2] == 1 and row[3] == "provider 503 network_error" and sub_of(biz)["status"] == "trialing"
    cfree.fail_fetch = False
    assert deliver(sid, pid="retry_me", event_time=et).json()["status"] == "processed"
    row = webhook_rows(sid)[0]
    assert len(webhook_rows(sid)) == 1 and row[1] == "processed" and row[2] == 2 and row[3] is None and sub_of(biz)["status"] == "active"


def test_events_in_the_wrong_order_cannot_move_state_backwards(cfree):
    biz, sid = authorized(cfree, "growth")
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    cfree.pay(sid, "ord1", "CHARGE", "SUCCESS", 79900)
    assert deliver(sid, pid="ord1", status="SUCCESS").status_code == 200
    assert sub_of(biz)["status"] == "active"
    # a late, older "on hold" event arrives AFTER the success: Cashfree's own answer is still active, so nothing changes
    late = deliver(sid, "SUBSCRIPTION_STATUS_CHANGED", status="ON_HOLD", event_time=(utcnow() - timedelta(minutes=3)).isoformat())
    assert late.status_code == 200 and sub_of(biz)["status"] == "active"


def test_an_unknown_subscription_is_ignored_and_touches_no_business(cfree):
    biz, sid = authorized(cfree, "growth")
    r = deliver("fqs_does_not_exist")
    assert r.status_code == 200 and r.json()["status"] == "ignored" and sub_of(biz)["status"] == "trialing"
    assert deliver(None, body={"type": "SUBSCRIPTION_PAYMENT_SUCCESS", "event_time": utcnow().isoformat(), "data": {"payment_id": "p"}}).json()["status"] == "ignored"


def test_a_webhook_for_one_business_can_never_change_another(cfree):
    a, asid = authorized(cfree, "growth")
    b, bsid = authorized(cfree, "starter")
    cfree.set_status(asid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    cfree.pay(asid, "pay_for_a", "CHARGE", "SUCCESS", 79900)
    # the event names A's subscription but ALSO carries B's identifiers and B's payment id: only A can change
    body = {"type": "SUBSCRIPTION_PAYMENT_SUCCESS", "event_time": utcnow().isoformat(), "data": {"payment_id": "pay_for_a", "subscription_id": asid, "cf_subscription_id": "999",
            "payment_status": "SUCCESS", "tenant_id": b.tenant_id, "subscription_details": {"subscription_id": bsid}}}
    assert deliver(asid, body=body).status_code == 200
    assert sub_of(a)["status"] == "active" and sub_of(b)["status"] == "trialing" and sub_of(b)["plan"] == "trial"
    assert payments_of(b) == [("sub_auth", "captured", 100, "AUTH", f"auth_{bsid}")]


def test_a_payment_id_that_already_belongs_to_another_business_is_ignored(cfree):
    a, asid = authorized(cfree, "growth")
    b, bsid = authorized(cfree, "growth")
    cfree.set_status(asid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    charge(cfree, a, asid, 79900, pid="shared_id")
    cfree.pay(bsid, "shared_id", "CHARGE", "SUCCESS", 79900)  # a collision across businesses must not give B a free activation or move A's payment
    cfree.set_status(bsid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    sync(b)
    assert sub_of(b)["status"] == "trialing"
    assert [p[4] for p in payments_of(a) if p[0] == "subscription"] == ["shared_id"] and not [p for p in payments_of(b) if p[0] == "subscription"]


def test_webhook_records_hold_hashes_and_ids_but_never_a_payload_or_customer_details(cfree):
    biz, sid = authorized(cfree, "growth")
    deliver(sid, body={"type": "SUBSCRIPTION_STATUS_CHANGED", "event_time": utcnow().isoformat(),
                       "data": {"subscription_details": {"subscription_id": sid, "subscription_status": "ACTIVE"}, "customer_details": {"customer_email": "secret.person@example.com", "customer_phone": "9876501234"}}})
    dump = json.dumps(owner_query("SELECT * FROM webhook_events WHERE subscription_ref = :s", s=sid), default=str)
    assert "secret.person" not in dump and "9876501234" not in dump and "test_client_secret" not in dump and WH not in dump


# ----------------------------------------------------------------------------------------------------------------------------- reconciliation
def test_reconciliation_recovers_what_a_missing_webhook_would_have_told_us_and_one_failure_does_not_stop_the_rest(cfree):
    a, asid = authorized(cfree, "growth")
    b, bsid = authorized(cfree, "starter")
    for biz, sid, amt in ((a, asid, 79900), (b, bsid, 49900)):
        cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
        cfree.pay(sid, f"missed_{sid}", "CHARGE", "SUCCESS", amt)
        set_sub(biz, status="pending", last_provider_sync_at=utcnow() - timedelta(hours=2))
    real = cfree.fetch_subscription

    def flaky(sid):
        if sid == asid:
            raise cf.CashfreeError(503, "network_error", "down")
        return real(sid)
    cfree.fetch_subscription = flaky
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        out = cfb.reconcile(db, cfree)
    finally:
        db.close()
    assert out["errors"] >= 1 and out["synced"] >= 1
    assert sub_of(b)["status"] == "active" and sub_of(a)["status"] == "pending"
    cfree.fetch_subscription = real
    set_sub(a, last_provider_sync_at=utcnow() - timedelta(hours=2))
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        cfb.reconcile(db, cfree)
    finally:
        db.close()
    assert sub_of(a)["status"] == "active"


def test_reconciliation_leaves_recently_synced_and_settled_subscriptions_alone(cfree):
    biz, sid = authorized(cfree, "growth")
    n = cfree.n("fetch")
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        cfb.reconcile(db, cfree)
    finally:
        db.close()
    assert cfree.n("fetch") == n  # synced a moment ago, first charge days away: nothing to do


# ----------------------------------------------------------------------------------------------------------------------------- admin, revenue
def test_admin_sees_cashfree_state_and_webhook_health_and_ordinary_users_cannot(cfree, admin, biz_a):
    biz, sid = authorized(cfree, "growth")
    deliver(sid, pid="adm1")
    subs = [s for s in admin.get("/admin/subscriptions?limit=200").json() if s["cashfree_subscription_id"] == sid][0]
    assert subs["provider"] == "cashfree" and subs["authorization_status"] == "authorized" and subs["pending_plan"] == "growth"
    hooks = [h for h in admin.get("/admin/webhooks").json() if h["subscription_ref"] == sid]
    assert hooks and hooks[0]["status"] == "processed" and "payload" not in hooks[0]
    pays = [p for p in admin.get("/admin/payments?limit=200").json() if p["cashfree_payment_id"] == f"auth_{sid}"]
    assert pays and pays[0]["payment_type"] == "AUTH" and pays[0]["kind"] == "sub_auth"
    assert biz_a.get("/admin/webhooks").status_code == 403 and biz_a.post(f"/admin/webhooks/{hooks[0]['id']}/reprocess").status_code == 403


def test_admin_can_reprocess_a_failed_event_but_only_the_providers_truth_can_change_a_subscription(cfree, admin):
    biz, sid = authorized(cfree, "growth")
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    cfree.fail_fetch = True
    assert deliver(sid, pid="adm2").status_code == 500
    cfree.fail_fetch = False
    hook = [h for h in admin.get("/admin/webhooks?status=failed").json() if h["subscription_ref"] == sid][0]
    assert hook["last_error"] == "provider 503 network_error"
    out = admin.post(f"/admin/webhooks/{hook['id']}/reprocess")
    assert out.status_code == 200 and sub_of(biz)["status"] == "trialing"  # nothing was paid at Cashfree, so nothing becomes paid
    cfree.pay(sid, "adm2", "CHARGE", "SUCCESS", 79900)
    assert admin.post(f"/admin/webhooks/{hook['id']}/reprocess").status_code == 200 and sub_of(biz)["status"] == "active"
    assert "admin.webhook_reprocess" in [r[0] for r in owner_query("SELECT action FROM audit_logs WHERE tenant_id = :t", t=biz.tenant_id)]


def test_mrr_counts_verified_cashfree_revenue_keeps_razorpay_history_and_never_counts_the_authorisation(cfree):
    def snapshot():
        db = SessionLocal(); set_rls_context(db, bypass=True)
        try:
            return finance.revenue(db)
        finally:
            db.close()
    before = snapshot()
    biz, sid = authorized(cfree, "growth")  # authorised, 1 rupee authorisation captured, nothing charged
    mid = snapshot()
    assert mid["mrr_paise"]["value"] == before["mrr_paise"]["value"]
    assert mid["subscription_cash_collected_paise"]["value"] == before["subscription_cash_collected_paise"]["value"]  # the authorisation is not revenue
    cfree.set_status(sid, "ACTIVE", next_charge=utcnow() + timedelta(days=30))
    charge(cfree, biz, sid, 79900, pid="rev1")
    after = snapshot()
    assert after["mrr_paise"]["value"] == before["mrr_paise"]["value"] + 79900
    assert after["mrr_by_provider_paise"]["value"]["cashfree"] == before["mrr_by_provider_paise"]["value"]["cashfree"] + 79900
    assert after["mrr_by_provider_paise"]["value"]["razorpay"] == before["mrr_by_provider_paise"]["value"]["razorpay"]
    assert after["subscription_cash_collected_paise"]["value"] == before["subscription_cash_collected_paise"]["value"] + 79900
    legacy = make_business()
    set_sub(legacy, status="active", source="razorpay", plan="starter")
    assert snapshot()["mrr_by_provider_paise"]["value"]["razorpay"] == before["mrr_by_provider_paise"]["value"]["razorpay"] + 49900  # a historical Razorpay subscription still counts, as before


# ----------------------------------------------------------------------------------------------------------------------------- derived state names
def test_billing_state_names(cfree):
    from types import SimpleNamespace as S
    now = utcnow()
    mk = lambda **k: S(**{"status": "trialing", "provider": None, "authorization_status": None, "current_period_end": None, **k})  # noqa: E731
    assert cfb.billing_state(None) == "none"
    assert cfb.billing_state(mk(status="canceled", current_period_end=now + timedelta(days=3))) == "cancellation_pending"
    assert cfb.billing_state(mk(status="canceled", current_period_end=now - timedelta(days=3))) == "cancelled"
    assert cfb.billing_state(mk(status="past_due")) == "past_due"
    assert cfb.billing_state(mk(provider="cashfree", authorization_status="bank_pending")) == "authorization_pending"
    assert [cfb.billing_state(mk(status=s)) for s in ("pending", "trialing", "active", "expired", "halted")] == ["pending", "trialing", "active", "expired", "expired"]
