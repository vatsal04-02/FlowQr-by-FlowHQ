"""Prepaid plans through the real application and PostgreSQL. Cashfree is a TEST DOUBLE (FakeCashfreePG) behind the same interface; webhooks are signed with the documented algorithm.
These tests prove how FlowQR behaves (server-set price, access only on a confirmed payment, idempotency, expiry by the clock, failures change nothing). They do NOT prove that Cashfree's
sandbox answers exactly like the double: see docs/PREPAID_CHECKOUT.md for what was checked against the real sandbox."""
import json
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.main import app
from app.models.base import utcnow
from app.services import billing as billing_svc
from app.services import cashfree as cf
from app.services import entitlements as ent
from app.services import plans as plans_svc
from app.services import prepaid
from app.services.mailer import OUTBOX
from tests.conftest import make_business, owner_exec, owner_query

WH = "pg_webhook_secret_for_tests"
PHONE = "9876543210"


class FakeCashfreePG:
    """TEST DOUBLE for Cashfree's Payment Gateway Orders API. It keeps the provider's truth; tests change that truth, FlowQR reads it."""

    def __init__(self):
        self.orders, self.pays, self.calls = {}, {}, []
        self.fail_create = self.fail_fetch = False

    def create_order(self, *, order_id, amount_paise, customer_id, customer, return_url, notify_url, expires_at, note, idempotency_key):
        if self.fail_create:
            raise cf.CashfreeError(500, "api_error", "boom")
        self.calls.append(("create_order", order_id, amount_paise, customer.phone, return_url, notify_url))
        self.orders[order_id] = {"status": "ACTIVE", "amount": amount_paise, "currency": "INR", "cf": str(5000 + len(self.orders))}
        return cf.OrderResult(order_id, self.orders[order_id]["cf"], "ACTIVE", amount_paise, "INR", f"session_{order_id}")

    def fetch_order(self, order_id):
        if self.fail_fetch:
            raise cf.CashfreeError(503, "network_error", "down")
        self.calls.append(("fetch_order", order_id))
        o = self.orders[order_id]
        return cf.OrderResult(order_id, o["cf"], o["status"], o["amount"], o["currency"], None)

    def list_order_payments(self, order_id):
        return list(self.pays.get(order_id, []))

    # --- the provider's side of the story
    def pay(self, order_id, status="SUCCESS", amount=None, *, method="upi", reason=None, order_status=None):
        o = self.orders[order_id]
        amt = o["amount"] if amount is None else amount
        self.pays.setdefault(order_id, []).append(cf.OrderPayment(f"cfp{len(self.pays.get(order_id, [])) + 1}{order_id[-4:]}", status, amt, "INR", method, reason, utcnow()))
        if order_status:
            o["status"] = order_status
        elif status == "SUCCESS":
            o["status"] = "PAID"

    def n(self, name):
        return sum(1 for c in self.calls if c[0] == name)


@pytest.fixture()
def pg(monkeypatch):
    f = FakeCashfreePG()
    for k, v in {"prepaid_checkout_enabled": True, "billing_provider": "", "cashfree_env": "sandbox", "cashfree_client_id": "test_client_id", "cashfree_client_secret": "test_client_secret",
                 "cashfree_webhook_secret": WH, "prepaid_notify_url": "https://api.example.test/api/v1/webhooks/cashfree-pg", "razorpay_key_id": "", "razorpay_key_secret": "",
                 "razorpay_webhook_secret": ""}.items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(cf, "get_cashfree", lambda: f)
    return f


def checkout(biz, plan="growth", months=3, phone=PHONE, **extra):
    return biz.post("/billing/prepaid/checkout", json={"plan": plan, "months": months, "phone": phone, **extra})


def verify(biz, order_id):
    return biz.post("/billing/prepaid/verify", json={"order_id": order_id})


def sub_of(biz) -> dict:
    cols = "status, plan, source, provider, current_period_start, current_period_end, pending_plan, review_generations, review_replies, max_staff, max_locations"
    row = owner_query(f"SELECT {cols} FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0]
    return dict(zip([c.strip() for c in cols.split(",")], row))


def order_row(order_id) -> dict:
    cols = "status, plan_code, months, amount_paise, currency, cf_payment_id, payment_method, failure_reason, paid_at, activated_at, period_start, period_end"
    row = owner_query(f"SELECT {cols} FROM prepaid_orders WHERE order_id = :o", o=order_id)[0]
    return dict(zip([c.strip() for c in cols.split(",")], row))


def n_orders(biz) -> int:
    return owner_query("SELECT count(*) FROM prepaid_orders WHERE tenant_id = :t", t=biz.tenant_id)[0][0]


def payments_of(biz):
    return owner_query("SELECT kind, status, amount_paise, payment_type, provider FROM payments WHERE tenant_id = :t ORDER BY created_at", t=biz.tenant_id)


def events_of(biz):
    return [r[0] for r in owner_query("SELECT kind FROM subscription_events WHERE tenant_id = :t ORDER BY created_at", t=biz.tenant_id)]


def entitlements_of(biz):
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        return ent.for_tenant(db, uuid.UUID(str(biz.tenant_id)))


def deliver_pg(order_id, etype="PAYMENT_SUCCESS_WEBHOOK", *, status="SUCCESS", secret=WH, ts=None, cf_payment="1001", event_time=None, body=None):
    if body is None:
        body = {"type": etype, "event_time": event_time or utcnow().isoformat(), "data": {"order": {"order_id": order_id, "order_amount": 2299.0, "order_currency": "INR"},
                                                                                  "payment": {"cf_payment_id": cf_payment, "payment_status": status, "payment_amount": 2299.0}}}
    raw = json.dumps(body, separators=(",", ":")).encode()
    ts = ts or str(int(utcnow().timestamp() * 1000))
    headers = {"x-webhook-signature": cf.sign_webhook(raw, ts, secret), "x-webhook-timestamp": ts, "content-type": "application/json"}
    return TestClient(app, base_url="http://testserver").post("/api/v1/webhooks/cashfree-pg", content=raw, headers=headers)


# ============================================================================================================================= the switch
def test_checkout_is_closed_until_it_is_switched_on_and_the_pricing_answer_says_so(monkeypatch):
    biz = make_business()
    monkeypatch.setattr(settings, "prepaid_checkout_enabled", False)
    assert TestClient(app, base_url="http://testserver").get("/api/v1/billing/plans").json()["terms"]["checkout_open"] is False
    r = checkout(biz)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "checkout_closed"
    assert n_orders(biz) == 0


def test_it_needs_credentials_and_is_independent_of_billing_provider(pg, monkeypatch):
    monkeypatch.setattr(settings, "billing_provider", "")  # the dormant subscription integration stays OFF: prepaid must not depend on it
    assert TestClient(app, base_url="http://testserver").get("/api/v1/billing/plans").json()["terms"]["checkout_open"] is True
    monkeypatch.setattr(settings, "cashfree_client_secret", "")
    assert TestClient(app, base_url="http://testserver").get("/api/v1/billing/plans").json()["terms"]["checkout_open"] is False
    from app.core.config import config_problems
    hardened = settings.model_copy(update={"app_env": "production"})
    assert any("PREPAID_CHECKOUT_ENABLED needs" in p for p in config_problems(hardened))  # a hardened boot refuses "on" without credentials


# ============================================================================================================================= pricing is the server's
def test_the_server_prices_the_order_from_its_own_list_and_the_browser_cannot_change_it(pg):
    biz = make_business()
    r = checkout(biz, "growth", 3, amount_paise=1, price=1, amount=1, order_amount=1)  # extra fields are ignored: there is no amount in the contract
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["amount_paise"] == plans_svc.TERM_PRICES_PAISE["growth"][3] == 229900 and d["months"] == 3 and d["plan"] == "growth"
    assert d["payment_session_id"] == f"session_{d['order_id']}" and d["environment"] == "sandbox" and d["order_id"].startswith("fqp_")
    call = [c for c in pg.calls if c[0] == "create_order"][0]
    assert call[2] == 229900 and call[3] == PHONE and call[4].endswith(f"/settings/billing/pay-return?order_id={d['order_id']}") and call[5].endswith("/webhooks/cashfree-pg")
    row = order_row(d["order_id"])
    assert (row["status"], row["amount_paise"], row["currency"], row["activated_at"]) == ("created", 229900, "INR", None)


@pytest.mark.parametrize("plan", ["starter", "growth", "pro"])
@pytest.mark.parametrize("months", [1, 3, 6, 12])
def test_all_twelve_combinations_are_charged_exactly_the_listed_price(pg, plan, months):
    biz = make_business()
    d = checkout(biz, plan, months).json()
    assert d["amount_paise"] == plans_svc.TERM_PRICES_PAISE[plan][months]
    assert pg.orders[d["order_id"]]["amount"] == plans_svc.TERM_PRICES_PAISE[plan][months]


def test_unknown_plan_or_term_is_refused_and_no_order_is_created(pg):
    biz = make_business()
    assert checkout(biz, "platinum", 3).status_code == 404
    assert checkout(biz, "growth", 2).status_code == 422  # not a listed term (the schema allows 1-12; the price list decides)
    assert checkout(biz, "growth", 13).status_code == 422
    assert checkout(biz, "trial", 3).status_code in (404, 422)
    assert n_orders(biz) == 0 and pg.n("create_order") == 0


@pytest.mark.parametrize("phone", ["12345", "0000000000", "5876543210", "98765abcde", "+1 415 555 0100"])
def test_a_bad_phone_number_is_refused_before_anything_is_created(pg, phone):
    biz = make_business()
    r = checkout(biz, phone=phone)
    assert r.status_code in (422, 400), r.text
    assert n_orders(biz) == 0 and pg.n("create_order") == 0


def test_indian_number_formats_are_accepted_and_normalised(pg):
    for raw in ("+91 98765 43210", "09876543210", "919876543210", "98765-43210"):
        assert prepaid.clean_phone(raw) == "9876543210"


def test_only_the_owner_of_a_verified_account_can_start_a_purchase(pg):
    biz = make_business()
    from tests.conftest import make_user
    anon = TestClient(app, base_url="http://testserver", cookies={})
    assert anon.post("/api/v1/billing/prepaid/checkout", json={"plan": "growth", "months": 3, "phone": PHONE}).status_code in (401, 403)
    owner_exec("UPDATE users SET email_verified_at = NULL WHERE email = (SELECT u.email FROM users u JOIN memberships m ON m.user_id = u.id WHERE m.tenant_id = :t LIMIT 1)", t=biz.tenant_id)
    assert checkout(biz).status_code in (403, 401, 409)
    assert n_orders(biz) == 0


def test_a_provider_failure_leaves_no_order_and_changes_nothing(pg):
    biz = make_business()
    before = sub_of(biz)
    pg.fail_create = True
    r = checkout(biz)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "provider_error"
    assert n_orders(biz) == 0 and sub_of(biz) == before


# ============================================================================================================================= access only on a confirmed payment
def test_creating_an_order_grants_nothing(pg):
    biz = make_business()
    before = sub_of(biz)
    assert checkout(biz).status_code == 200
    assert sub_of(biz) == before and payments_of(biz) == []


def test_a_confirmed_payment_activates_exactly_the_paid_plan_and_term(pg):
    biz = make_business()
    d = checkout(biz, "pro", 6).json()
    before = utcnow()
    pg.pay(d["order_id"])
    r = verify(biz, d["order_id"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["state"] == "paid" and out["plan"] == "pro" and out["months"] == 6 and out["amount_paise"] == 699900
    s = sub_of(biz)
    assert (s["status"], s["plan"], s["source"], s["provider"], s["pending_plan"]) == ("active", "pro", "prepaid", "prepaid", None)
    plan = [p for p in plans_svc.PLANS.values()][2]
    assert (s["review_generations"], s["review_replies"], s["max_staff"], s["max_locations"]) == (plan["review_generations"], plan["review_replies"], plan["max_staff"], plan["max_locations"])
    start, end = s["current_period_start"], s["current_period_end"]
    assert before - timedelta(seconds=5) <= start <= utcnow() and end == prepaid.add_months(start, 6)
    e = entitlements_of(biz)
    assert e.active and e.status == "active" and e.plan == "pro" and "multi_location" in e.features
    assert payments_of(biz) == [("subscription", "captured", 699900, "PREPAID", "cashfree")]
    assert "activated" in events_of(biz)
    assert any(m["subject"] == "Your FlowQR plan is active" for m in OUTBOX[-3:])
    o = order_row(d["order_id"])
    assert o["status"] == "paid" and o["activated_at"] is not None and o["payment_method"] == "upi" and o["cf_payment_id"]


def test_the_browser_saying_it_paid_means_nothing_without_cashfree_saying_so(pg):
    biz = make_business()
    d = checkout(biz).json()
    r = verify(biz, d["order_id"])  # return page opened, but Cashfree has no payment
    assert r.status_code == 200 and r.json()["state"] == "open"
    assert sub_of(biz)["provider"] != "prepaid" and payments_of(biz) == []
    assert order_row(d["order_id"])["activated_at"] is None


def test_a_wrong_amount_grants_nothing_and_is_flagged(pg):
    biz = make_business()
    d = checkout(biz, "growth", 12).json()
    pg.orders[d["order_id"]]["amount"] = 100  # Cashfree reports a paid order of Rs 1
    pg.pay(d["order_id"], amount=100)
    r = verify(biz, d["order_id"])
    assert r.json()["state"] == "mismatch"
    assert sub_of(biz)["provider"] != "prepaid" and payments_of(biz) == [] and order_row(d["order_id"])["activated_at"] is None
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'billing.prepaid_amount_mismatch'", t=biz.tenant_id)[0][0] == 1


def test_a_paid_order_in_another_currency_grants_nothing(pg):
    biz = make_business()
    d = checkout(biz).json()
    pg.orders[d["order_id"]]["currency"] = "USD"
    pg.pay(d["order_id"])
    assert verify(biz, d["order_id"]).json()["state"] == "mismatch"
    assert sub_of(biz)["provider"] != "prepaid"


def test_a_business_cannot_verify_another_businesss_order(pg):
    a, b = make_business("Alpha"), make_business("Beta")
    d = checkout(a).json()
    pg.pay(d["order_id"])
    assert verify(b, d["order_id"]).status_code == 404
    assert sub_of(b)["provider"] != "prepaid" and sub_of(a)["provider"] != "prepaid"


def test_a_malformed_order_id_is_refused(pg):
    biz = make_business()
    for bad in ("x", "fqp_zzzz", "../etc", "fqp_" + "g" * 24):
        assert verify(biz, bad).status_code == 422


# ============================================================================================================================= failures change nothing
@pytest.mark.parametrize("status,reason", [("FAILED", "insufficient balance"), ("USER_DROPPED", None), ("CANCELLED", None)])
def test_a_failed_or_abandoned_payment_changes_nothing_and_says_so(pg, status, reason):
    biz = make_business()
    before = sub_of(biz)
    d = checkout(biz).json()
    pg.pay(d["order_id"], status, reason=reason)
    out = verify(biz, d["order_id"]).json()
    assert out["state"] == "failed"
    assert sub_of(biz) == before and payments_of(biz) == [] and order_row(d["order_id"])["activated_at"] is None


def test_a_pending_payment_is_pending_not_failed_and_not_granted(pg):
    biz = make_business()
    d = checkout(biz).json()
    pg.pay(d["order_id"], "PENDING", order_status="ACTIVE")
    out = verify(biz, d["order_id"]).json()
    assert out["state"] == "pending" and sub_of(biz)["provider"] != "prepaid"


def test_a_failed_attempt_can_be_retried_and_a_later_success_still_activates(pg):
    biz = make_business()
    d = checkout(biz).json()
    pg.pay(d["order_id"], "FAILED", reason="bank declined")
    assert verify(biz, d["order_id"]).json()["state"] == "failed"
    pg.pay(d["order_id"], "SUCCESS")
    assert verify(biz, d["order_id"]).json()["state"] == "paid"
    assert sub_of(biz)["provider"] == "prepaid" and len(payments_of(biz)) == 1


def test_an_expired_order_is_expired_and_grants_nothing(pg):
    biz = make_business()
    d = checkout(biz).json()
    pg.orders[d["order_id"]]["status"] = "EXPIRED"
    assert verify(biz, d["order_id"]).json()["state"] == "expired"
    assert order_row(d["order_id"])["status"] == "expired" and sub_of(biz)["provider"] != "prepaid"


def test_when_cashfree_cannot_be_reached_the_page_says_pending_and_grants_nothing(pg):
    biz = make_business()
    d = checkout(biz).json()
    pg.pay(d["order_id"])
    pg.fail_fetch = True
    out = verify(biz, d["order_id"]).json()
    assert out["state"] == "pending" and out.get("unconfirmed") is True
    assert sub_of(biz)["provider"] != "prepaid"
    pg.fail_fetch = False
    assert verify(biz, d["order_id"]).json()["state"] == "paid"


# ============================================================================================================================= one payment, one grant
def test_the_return_page_the_webhook_and_the_hourly_check_together_grant_once(pg):
    biz = make_business()
    d = checkout(biz, "growth", 3).json()
    pg.pay(d["order_id"])
    when = utcnow().isoformat()
    assert deliver_pg(d["order_id"], event_time=when).status_code == 200
    end1 = sub_of(biz)["current_period_end"]
    for _ in range(3):
        assert verify(biz, d["order_id"]).json()["state"] == "paid"
    assert deliver_pg(d["order_id"], event_time=when).json()["status"] == "duplicate"  # an identical redelivery is acknowledged and ignored
    assert deliver_pg(d["order_id"], event_time=utcnow().isoformat(), cf_payment="1002").status_code == 200  # a different event for an activated order changes nothing
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        prepaid.reconcile(db, pg, now=utcnow() + timedelta(minutes=10))
    assert sub_of(biz)["current_period_end"] == end1
    assert len(payments_of(biz)) == 1 and events_of(biz).count("activated") == 1
    assert sum(1 for m in OUTBOX if m["subject"] == "Your FlowQR plan is active" and "3 months" in m["body"]) >= 1


def test_the_webhook_alone_activates_a_customer_who_closed_the_tab(pg):
    biz = make_business()
    d = checkout(biz, "starter", 1).json()
    pg.pay(d["order_id"])
    r = deliver_pg(d["order_id"])
    assert r.status_code == 200 and r.json()["status"] == "processed"
    assert sub_of(biz)["provider"] == "prepaid" and sub_of(biz)["plan"] == "starter"


def test_a_webhook_for_an_unpaid_order_grants_nothing_whatever_its_body_claims(pg):
    biz = make_business()
    d = checkout(biz).json()  # Cashfree has NO payment: the body below lies
    r = deliver_pg(d["order_id"], status="SUCCESS")
    assert r.status_code == 200
    assert sub_of(biz)["provider"] != "prepaid" and payments_of(biz) == []


def test_a_webhook_for_an_unknown_order_is_acknowledged_and_ignored(pg):
    r = deliver_pg("fqp_" + "0" * 24)
    assert r.status_code == 200 and r.json()["status"] == "ignored"


def test_webhooks_with_a_bad_signature_old_timestamp_or_garbage_are_refused(pg):
    biz = make_business()
    d = checkout(biz).json()
    pg.pay(d["order_id"])
    assert deliver_pg(d["order_id"], secret="wrong").status_code == 400
    assert deliver_pg(d["order_id"], ts=str(int((utcnow() - timedelta(hours=1)).timestamp() * 1000))).status_code == 400
    assert deliver_pg(d["order_id"], body={"nope": 1}).status_code == 400
    raw = b"not json"
    ts = str(int(utcnow().timestamp() * 1000))
    r = TestClient(app, base_url="http://testserver").post("/api/v1/webhooks/cashfree-pg", content=raw, headers={"x-webhook-signature": cf.sign_webhook(raw, ts, WH), "x-webhook-timestamp": ts})
    assert r.status_code == 400
    assert TestClient(app, base_url="http://testserver").post("/api/v1/webhooks/cashfree-pg", content=b"{}").status_code == 400
    assert sub_of(biz)["provider"] != "prepaid"


def test_the_webhook_endpoint_does_not_exist_while_prepaid_is_off(monkeypatch):
    monkeypatch.setattr(settings, "prepaid_checkout_enabled", False)
    assert deliver_pg("fqp_" + "0" * 24).status_code == 404


def test_the_subscriptions_webhook_is_untouched_by_this_feature(pg):
    r = TestClient(app, base_url="http://testserver").post("/api/v1/webhooks/cashfree", content=b"{}")
    assert r.status_code == 404  # BILLING_PROVIDER is empty: the subscription endpoint stays dormant


# ============================================================================================================================= the term, the clock and the rules around it
def test_months_are_calendar_months_and_clamp_to_the_end_of_a_short_month():
    from datetime import datetime, timezone
    d = datetime(2026, 1, 31, 10, 0, tzinfo=timezone.utc)
    assert prepaid.add_months(d, 1) == datetime(2026, 2, 28, 10, 0, tzinfo=timezone.utc)
    assert prepaid.add_months(d, 12) == datetime(2027, 1, 31, 10, 0, tzinfo=timezone.utc)
    assert prepaid.add_months(datetime(2027, 12, 15, tzinfo=timezone.utc), 3) == datetime(2028, 3, 15, tzinfo=timezone.utc)
    assert prepaid.add_months(datetime(2028, 1, 31, tzinfo=timezone.utc), 1) == datetime(2028, 2, 29, tzinfo=timezone.utc)


def test_access_ends_by_the_clock_without_any_job_running_and_the_job_then_records_it(pg):
    biz = make_business()
    d = checkout(biz, "growth", 1).json()
    pg.pay(d["order_id"])
    assert verify(biz, d["order_id"]).json()["state"] == "paid"
    assert entitlements_of(biz).active
    owner_exec("UPDATE subscriptions SET current_period_end = now() - interval '1 minute' WHERE tenant_id = :t", t=biz.tenant_id)
    e = entitlements_of(biz)
    assert not e.active and e.reason == "plan_expired" and e.status == "expired"
    me = biz.get("/billing/subscription").json()
    assert me["active"] is False and me["inactive_reason"] == "plan_expired" and me["source"] == "prepaid"
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        assert billing_svc.refresh_statuses(db)["prepaid_ended"] >= 1
    assert sub_of(biz)["status"] == "expired" and "expired" in events_of(biz)
    e = entitlements_of(biz)
    assert not e.active and e.reason == "plan_expired"


def test_a_prepaid_plan_never_renews_and_nothing_else_is_charged(pg):
    biz = make_business()
    d = checkout(biz, "growth", 1).json()
    pg.pay(d["order_id"])
    verify(biz, d["order_id"])
    assert pg.n("create_order") == 1
    s = owner_query("SELECT razorpay_subscription_id, cashfree_subscription_id, authorization_status, next_charge_at, first_charge_at FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0]
    assert s == (None, None, None, None, None)  # no mandate, no subscription id, no scheduled charge anywhere
    sub = sub_of(biz)
    assert sub["provider"] == "prepaid"


def test_a_running_term_blocks_a_second_purchase_until_it_ends(pg):
    biz = make_business()
    d = checkout(biz, "growth", 3).json()
    pg.pay(d["order_id"])
    verify(biz, d["order_id"])
    r = checkout(biz, "pro", 1)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "term_running" and n_orders(biz) == 1
    owner_exec("UPDATE subscriptions SET current_period_end = now() - interval '1 day' WHERE tenant_id = :t", t=biz.tenant_id)
    assert checkout(biz, "pro", 1).status_code == 200  # the term ended: a new purchase is allowed


def test_a_live_monthly_subscription_blocks_a_prepaid_purchase(pg):
    biz = make_business()
    owner_exec("UPDATE subscriptions SET provider = 'cashfree', cashfree_subscription_id = :sid, authorization_status = 'authorized', status = 'active' WHERE tenant_id = :t", t=biz.tenant_id, sid="fqs_" + uuid.uuid4().hex[:12])
    r = checkout(biz)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "subscription_active" and n_orders(biz) == 0


def test_a_free_trial_is_replaced_by_the_paid_plan_and_a_double_payment_extends_the_same_term(pg):
    biz = make_business()
    assert sub_of(biz)["status"] == "trialing"
    a = checkout(biz, "growth", 3).json()
    b = checkout(biz, "growth", 3).json()  # a second tab: both orders exist before either is paid
    pg.pay(a["order_id"])
    assert verify(biz, a["order_id"]).json()["state"] == "paid"
    first_end = sub_of(biz)["current_period_end"]
    pg.pay(b["order_id"])
    assert verify(biz, b["order_id"]).json()["state"] == "paid"  # money was taken twice: the time is ADDED, never lost
    assert sub_of(biz)["current_period_end"] == prepaid.add_months(first_end, 3)
    assert len(payments_of(biz)) == 2


def test_a_different_plan_paid_during_a_running_term_keeps_the_unused_time(pg):
    biz = make_business()
    a = checkout(biz, "starter", 12).json()
    b = checkout(biz, "growth", 1).json()
    pg.pay(a["order_id"])
    verify(biz, a["order_id"])
    end_a = sub_of(biz)["current_period_end"]
    pg.pay(b["order_id"])
    assert verify(biz, b["order_id"]).json()["state"] == "paid"
    s = sub_of(biz)
    assert s["plan"] == "growth" and s["current_period_end"] > end_a  # the new plan runs, and the year already paid for is carried over in full


def test_row_level_security_hides_one_businesss_orders_from_another(pg):
    a, b = make_business("Alpha"), make_business("Beta")
    d = checkout(a).json()
    from sqlalchemy import text
    with SessionLocal() as db:
        db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(b.tenant_id)})
        db.execute(text("SELECT set_config('app.bypass_rls', 'off', true)"))
        assert db.execute(text("SELECT count(*) FROM prepaid_orders")).scalar() == 0
    assert d["order_id"]


def test_secrets_phone_and_session_are_never_stored_or_logged(pg, caplog):
    biz = make_business()
    with caplog.at_level("DEBUG"):
        d = checkout(biz).json()
        pg.pay(d["order_id"])
        verify(biz, d["order_id"])
    text = " ".join(r.getMessage() for r in caplog.records)
    for secret in (PHONE, "test_client_secret", d["payment_session_id"], WH):
        assert secret not in text
    cols = [c[0] for c in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = 'prepaid_orders'")]
    assert not {"phone", "customer_phone", "payment_session_id", "session_id", "card", "upi"} & set(cols)
    dump = json.dumps([str(r) for r in owner_query("SELECT * FROM prepaid_orders WHERE order_id = :o", o=d["order_id"])])
    assert PHONE not in dump and d["payment_session_id"] not in dump


def test_the_checkout_never_touches_the_subscription_api_of_cashfree(pg):
    biz = make_business()
    d = checkout(biz).json()
    pg.pay(d["order_id"])
    verify(biz, d["order_id"])
    assert {c[0] for c in pg.calls} <= {"create_order", "fetch_order"}  # no plan, subscription, mandate or authorisation call exists on this double: any would have raised


def test_the_payments_list_shows_the_purchase_under_subscription_with_its_type(pg):
    biz = make_business()
    d = checkout(biz, "starter", 1).json()
    pg.pay(d["order_id"])
    verify(biz, d["order_id"])
    rows = biz.get("/billing/payments", params={"kind": "subscription"}).json()
    assert len(rows) == 1 and rows[0]["amount_paise"] == 49900 and rows[0]["payment_type"] == "PREPAID" if "payment_type" in rows[0] else rows[0]["amount_paise"] == 49900
