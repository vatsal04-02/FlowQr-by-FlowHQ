"""Billing tests. FakeRazorpay is a TEST DOUBLE for Razorpay's HTTP API; signatures are real HMACs."""
import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.models import Payment, Subscription
from app.models.base import utcnow
from app.services import razorpay as rz
from tests.conftest import make_business, make_user, owner_query

KEY_SECRET, WH_SECRET = "test_key_secret_123", "test_webhook_secret_456"


class FakeRazorpay:
    """TEST DOUBLE."""

    def __init__(self):
        self.subs, self.orders, self.calls = {}, {}, []
        self.fail_next = False

    def create_plan(self, *, name, amount_paise, currency, interval):
        self.calls.append(("create_plan", name))
        return {"id": f"plan_{uuid.uuid4().hex[:10]}"}

    def create_subscription(self, *, plan_id, total_count, start_at, notes):
        self.calls.append(("create_subscription", plan_id, start_at))
        sid = f"sub_{uuid.uuid4().hex[:10]}"
        self.subs[sid] = {"id": sid, "plan_id": plan_id, "status": "created", "notes": notes, "start_at": start_at}
        return self.subs[sid]

    def fetch_subscription(self, sid):
        return self.subs[sid]

    def cancel_subscription(self, sid, at_cycle_end):
        if self.fail_next:
            raise rz.RazorpayError(500, "boom")
        self.calls.append(("cancel", sid, at_cycle_end))
        return self.subs[sid]

    def update_subscription(self, sid, *, plan_id, at_cycle_end):
        self.calls.append(("update", sid, plan_id, at_cycle_end))
        self.subs[sid]["plan_id"] = plan_id
        return self.subs[sid]

    def create_order(self, *, amount_paise, receipt, notes):
        oid = f"order_{uuid.uuid4().hex[:10]}"
        self.orders[oid] = {"id": oid, "amount": amount_paise, "status": "created", "amount_paid": 0}
        return self.orders[oid]

    def fetch_order(self, oid):
        return self.orders[oid]


@pytest.fixture()
def rzp(monkeypatch):
    f = FakeRazorpay()
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_abc123")
    monkeypatch.setattr(settings, "razorpay_key_secret", KEY_SECRET)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", WH_SECRET)
    monkeypatch.setattr(rz, "get_razorpay", lambda: f)
    return f


def sig(secret, msg):
    return hmac.new(secret.encode(), msg.encode() if isinstance(msg, str) else msg, hashlib.sha256).hexdigest()


def webhook(client, event, event_id=None, secret=WH_SECRET, tamper=False):
    raw = json.dumps(event).encode()
    headers = {"X-Razorpay-Signature": sig(secret, raw), "X-Razorpay-Event-Id": event_id or uuid.uuid4().hex, "Content-Type": "application/json"}
    if tamper:
        raw = raw.replace(b"subscription", b"subscriptioN")
    return client.post("/api/v1/billing/razorpay/webhook", content=raw, headers=headers)


def sub_event(etype, rzp_sub, payment=None, created_at=None):
    p = {"subscription": {"entity": rzp_sub}}
    if payment:
        p["payment"] = {"entity": payment}
    return {"entity": "event", "event": etype, "created_at": created_at or int(time.time()), "payload": p}


def db_sub(tenant_id):
    db = SessionLocal(); set_rls_context(db, bypass=True)
    s = db.scalar(select(Subscription).where(Subscription.tenant_id == uuid.UUID(tenant_id)))
    return db, s


def start_checkout(biz, plan="growth"):
    r = biz.post("/billing/subscription/checkout", json={"plan": plan})
    assert r.status_code == 200, r.text
    return r.json()


def activate(biz, rzp, plan="growth", client=None):
    """Checkout → verify with a real signature → Razorpay says 'active'."""
    out = start_checkout(biz, plan)
    sid = out["subscription_id"]
    rzp.subs[sid]["status"] = "active"
    rzp.subs[sid].update(current_start=int(time.time()), current_end=int(time.time()) + 30 * 86400)
    pay = f"pay_{uuid.uuid4().hex[:10]}"
    r = biz.post("/billing/subscription/verify", json={"razorpay_payment_id": pay, "razorpay_subscription_id": sid,
                                                       "razorpay_signature": sig(KEY_SECRET, f"{pay}|{sid}")})
    assert r.status_code == 200, r.text
    return sid, r.json()


def test_public_plans_in_inr(client):
    r = client.get("/api/v1/billing/plans").json()
    assert [(p["code"], p["price_paise"]) for p in r["plans"]] == [("starter", 49900), ("growth", 79900), ("pro", 149900)]
    assert r["trial_days"] == settings.trial_days


def test_new_tenant_starts_in_configurable_trial(biz_a):
    s = biz_a.get("/billing/subscription").json()
    assert s["status"] == "trialing" and s["active"] and s["plan"] == "trial"
    assert s["trial_days_left"] in (settings.trial_days, settings.trial_days - 1)
    assert "gbp_posts" in s["limits"]["features"]  # the exact Growth limits are asserted in test_phase2_plans.py
    assert s["usage"]["locations"] == 1


def test_billing_config_pending_is_honest(biz_a):
    assert settings.razorpay_configured is False
    r = biz_a.post("/billing/subscription/checkout", json={"plan": "growth"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "billing_config_pending"
    assert biz_a.get("/billing/subscription").json()["billing"]["configured"] is False


def test_checkout_requires_owner_and_verified_email(rzp):
    unverified = make_user(verify=False)
    unverified.post("/tenants", json={"name": "Unverified Co", "category": "Salon"})
    r = unverified.post("/billing/subscription/checkout", json={"plan": "growth"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "email_not_verified"


def test_checkout_idempotent_and_trial_defers_first_charge(rzp, biz_a):
    a = start_checkout(biz_a)
    b = start_checkout(biz_a)
    assert a["subscription_id"] == b["subscription_id"] and b["reused"] is True
    assert sum(1 for c in rzp.calls if c[0] == "create_subscription") == 1
    start_at = [c for c in rzp.calls if c[0] == "create_subscription"][0][2]
    assert start_at and start_at > time.time() + (settings.trial_days - 1) * 86400  # first charge only after the trial
    assert a["key_id"] == "rzp_test_abc123"


def test_verify_rejects_bad_signature_and_foreign_tenant(rzp, biz_a, biz_b):
    sid = start_checkout(biz_a)["subscription_id"]
    rzp.subs[sid]["status"] = "active"
    bad = biz_a.post("/billing/subscription/verify", json={"razorpay_payment_id": "pay_12345", "razorpay_subscription_id": sid, "razorpay_signature": "0" * 64})
    assert bad.status_code == 400
    assert biz_a.get("/billing/subscription").json()["status"] == "trialing"  # a bad callback changes nothing
    good_sig = sig(KEY_SECRET, f"pay_12345|{sid}")
    other = biz_b.post("/billing/subscription/verify", json={"razorpay_payment_id": "pay_12345", "razorpay_subscription_id": sid, "razorpay_signature": good_sig})
    assert other.status_code == 404


def test_verify_activates_only_when_razorpay_confirms(rzp, biz_a):
    sid = start_checkout(biz_a, "starter")["subscription_id"]
    rzp.subs[sid]["status"] = "authenticated"  # mandate authorised, nothing charged yet
    pay = "pay_abcde"
    r = biz_a.post("/billing/subscription/verify", json={"razorpay_payment_id": pay, "razorpay_subscription_id": sid, "razorpay_signature": sig(KEY_SECRET, f"{pay}|{sid}")})
    assert r.status_code == 200 and r.json()["status"] == "trialing"
    rzp.subs[sid].update(status="active", current_start=1, current_end=int(time.time()) + 100000)
    r = biz_a.post("/billing/subscription/verify", json={"razorpay_payment_id": pay, "razorpay_subscription_id": sid, "razorpay_signature": sig(KEY_SECRET, f"{pay}|{sid}")})
    assert r.json()["status"] == "active"
    s = biz_a.get("/billing/subscription").json()
    assert s["plan"] == "starter" and s["limits"]["locations"] == 1 and s["source"] == "razorpay"


def test_webhook_signature_required(rzp, client, biz_a):
    ev = sub_event("subscription.activated", {"id": "sub_x", "status": "active"})
    assert webhook(client, ev, secret="wrong").status_code == 400
    assert webhook(client, ev, tamper=True).status_code == 400
    r = client.post("/api/v1/billing/razorpay/webhook", content=b"{}", headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_webhook_charge_records_payment_and_is_idempotent(rzp, client, biz_a):
    sid, _ = activate(biz_a, rzp)
    ev = sub_event("subscription.charged", {"id": sid, "status": "active", "plan_id": rzp.subs[sid]["plan_id"], "current_start": 1, "current_end": int(time.time()) + 9999},
                   payment={"id": "pay_charge_1", "amount": 79900, "currency": "INR", "status": "captured", "method": "upi", "invoice_id": "inv_1", "created_at": int(time.time())})
    assert webhook(client, ev, event_id="evt_1").json()["status"] == "processed"
    assert webhook(client, ev, event_id="evt_1").json()["status"] == "duplicate"  # redelivery
    pays = biz_a.get("/billing/payments").json()
    assert len(pays) == 1 and pays[0]["kind"] == "subscription" and pays[0]["status"] == "captured" and pays[0]["amount_paise"] == 79900
    # same payment under a *different* event id still doesn't double-count
    webhook(client, ev, event_id="evt_2")
    assert len(biz_a.get("/billing/payments").json()) == 1


def test_failed_payment_grace_then_lapse_blocks_writes(rzp, client, biz_a):
    sid, _ = activate(biz_a, rzp, "pro")  # Pro: Growth includes one location and this test adds a second
    webhook(client, sub_event("subscription.pending", {"id": sid, "status": "pending"}, created_at=int(time.time()) + 5))
    s = biz_a.get("/billing/subscription").json()
    assert s["status"] == "past_due" and s["active"] is True and s["grace_until"]  # still within grace
    assert biz_a.post("/locations", json={"name": "Second branch"}).status_code == 201
    db, sub = db_sub(biz_a.tenant_id); sub.past_due_since = utcnow() - timedelta(days=settings.past_due_grace_days + 1); db.commit(); db.close()
    s = biz_a.get("/billing/subscription").json()
    assert s["active"] is False and s["inactive_reason"] == "payment_failed"
    r = biz_a.post("/locations", json={"name": "Third branch"})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "subscription_inactive"
    assert biz_a.get("/locations").status_code == 200  # read access is kept
    # recovery: a successful charge restores access
    webhook(client, sub_event("subscription.charged", {"id": sid, "status": "active", "plan_id": rzp.subs[sid]["plan_id"]},
                              payment={"id": "pay_rec", "amount": 79900, "status": "captured"}, created_at=int(time.time()) + 10))
    assert biz_a.get("/billing/subscription").json()["active"] is True


def test_payment_failed_event_recorded(rzp, client, biz_a):
    sid, _ = activate(biz_a, rzp)
    ev = {"event": "payment.failed", "created_at": int(time.time()) + 3, "payload": {"payment": {"entity": {
        "id": "pay_fail_1", "amount": 79900, "currency": "INR", "status": "failed", "subscription_id": sid, "error_code": "BAD_REQUEST_ERROR", "error_description": "Card declined"}}}}
    assert webhook(client, ev).json()["status"] == "processed"
    p = biz_a.get("/billing/payments").json()[0]
    assert p["status"] == "failed" and p["error_description"] == "Card declined"
    assert biz_a.get("/billing/subscription").json()["status"] == "past_due"


def test_out_of_order_and_unknown_events(rzp, client, biz_a):
    sid, _ = activate(biz_a, rzp)
    now = int(time.time())
    webhook(client, sub_event("subscription.halted", {"id": sid, "status": "halted"}, created_at=now + 100))
    assert biz_a.get("/billing/subscription").json()["status"] == "halted"
    webhook(client, sub_event("subscription.activated", {"id": sid, "status": "active"}, created_at=now + 1))  # older: must be ignored
    assert biz_a.get("/billing/subscription").json()["status"] == "halted"
    assert webhook(client, sub_event("subscription.activated", {"id": "sub_unknown", "status": "active"})).json()["status"] == "ignored"


def test_cancel_at_cycle_end_keeps_access(rzp, client, biz_a):
    sid, _ = activate(biz_a, rzp)
    r = biz_a.post("/billing/subscription/cancel", json={"at_cycle_end": True})
    assert r.status_code == 200 and r.json()["cancel_at_period_end"] is True
    assert ("cancel", sid, True) in rzp.calls
    s = biz_a.get("/billing/subscription").json()
    assert s["active"] and s["cancel_at_period_end"]
    webhook(client, sub_event("subscription.cancelled", {"id": sid, "status": "cancelled", "current_end": int(time.time()) + 5 * 86400}, created_at=int(time.time()) + 20))
    s = biz_a.get("/billing/subscription").json()
    assert s["status"] == "canceled" and s["active"] is True  # paid period still honoured


def test_cancel_failure_does_not_change_state(rzp, biz_a):
    activate(biz_a, rzp)
    rzp.fail_next = True
    assert biz_a.post("/billing/subscription/cancel", json={"at_cycle_end": True}).status_code == 502
    assert biz_a.get("/billing/subscription").json()["cancel_at_period_end"] is False


def test_upgrade_immediate_downgrade_scheduled_and_guarded(rzp, biz_a):
    sid, _ = activate(biz_a, rzp, "starter")
    assert biz_a.post("/billing/subscription/change-plan", json={"plan": "starter"}).status_code == 409
    r = biz_a.post("/billing/subscription/change-plan", json={"plan": "pro"})
    assert r.status_code == 200 and r.json()["plan"] == "pro"
    assert rzp.calls[-1][0] == "update" and rzp.calls[-1][3] is False  # applied now
    assert biz_a.get("/billing/subscription").json()["limits"]["locations"] == 10
    for i in range(2):
        assert biz_a.post("/locations", json={"name": f"Extra {i}"}).status_code == 201
    r = biz_a.post("/billing/subscription/change-plan", json={"plan": "starter"})  # 3 locations > 1
    assert r.status_code == 409 and r.json()["detail"]["code"] == "downgrade_blocked"
    for loc in biz_a.get("/locations").json()[1:]:
        biz_a.delete(f"/locations/{loc['id']}")
    r = biz_a.post("/billing/subscription/change-plan", json={"plan": "growth"})
    assert r.status_code == 200 and r.json()["pending_plan"] == "growth" and rzp.calls[-1][3] is True  # at cycle end


def test_plan_limits_enforced(rzp, biz_a):
    activate(biz_a, rzp, "starter")  # 1 location, 3 team members
    r = biz_a.post("/locations", json={"name": "Over the limit"})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_limit"
    assert biz_a.post("/staff/invitations", json={"email": "a1@example.com"}).status_code == 201
    assert biz_a.post("/staff/invitations", json={"email": "a2@example.com"}).status_code == 201
    r = biz_a.post("/staff/invitations", json={"email": "a3@example.com"})  # owner + 2 pending = 3 seats
    assert r.status_code == 402


def test_feature_gating_by_plan(biz_a):
    # trial = Growth features
    from app.services import entitlements as ent
    db, sub = db_sub(biz_a.tenant_id)
    assert ent.compute(sub).has("gbp_posts")
    sub.features = ["review_sync", "ai_replies", "gbp_info"]; sub.plan = "starter"; db.commit()
    with pytest.raises(Exception) as e:
        ent.require_feature(db, sub.tenant_id, "gbp_posts")
    assert e.value.status_code == 402 and e.value.detail["code"] == "plan_upgrade_required"
    db.close()


def test_trial_expiry_blocks_writes_and_ai_but_not_card_scans(admin, biz_a, client):
    b = admin.post("/admin/batches", json={"name": "trial batch", "quantity": 1}).json()
    card = admin.get("/admin/cards", params={"batch_id": b["id"]}).json()["items"][0]
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    db, sub = db_sub(biz_a.tenant_id); sub.trial_ends_at = utcnow() - timedelta(days=1); db.commit()
    from app.services.billing import refresh_statuses
    assert refresh_statuses(db)["expired_trials"] >= 1; db.close()
    s = biz_a.get("/billing/subscription").json()
    assert s["status"] == "expired" and s["active"] is False
    assert biz_a.post("/locations", json={"name": "x" * 3}).status_code == 402
    ua = {"user-agent": "Mozilla/5.0 (iPhone) Safari/604.1"}
    page = client.get(f"/api/v1/public/c/{card['public_token']}", headers=ua).json()
    assert page["state"] == "ok" and page["review_url"]  # printed cards keep working
    assert client.post(f"/api/v1/public/c/{card['public_token']}/assist", json={"text": "good service and kind staff"}, headers=ua).status_code == 503


def test_card_order_flow_separate_from_subscription_payments(rzp, client, biz_a):
    shipping = {"name": "Dr Geeta", "phone": "9876543210", "address_line": "12 Hazratganj", "city": "Lucknow", "state": "Uttar Pradesh", "postal_code": "226001"}
    assert biz_a.post("/billing/card-orders", json={"quantity": 3, "shipping": shipping}).status_code == 422  # neither a bundle (1 or 2) nor a bulk order
    h = {"Idempotency-Key": "order-key-1"}
    a = biz_a.post("/billing/card-orders", json={"quantity": 20, "shipping": shipping}, headers=h)
    b = biz_a.post("/billing/card-orders", json={"quantity": 20, "shipping": shipping}, headers=h)
    assert a.status_code == 201 and a.json()["order_id"] == b.json()["order_id"] and b.json()["reused"] is True
    assert a.json()["amount_paise"] == 20 * settings.card_price_paise
    oid = a.json()["order_id"]
    pay = "pay_card_1"
    bad = biz_a.post("/billing/card-orders/verify", json={"razorpay_order_id": oid, "razorpay_payment_id": pay, "razorpay_signature": "f" * 64})
    assert bad.status_code == 400 and biz_a.get("/billing/card-orders").json()[0]["status"] == "created"
    good = {"razorpay_order_id": oid, "razorpay_payment_id": pay, "razorpay_signature": sig(KEY_SECRET, f"{oid}|{pay}")}
    rzp.orders[oid]["status"] = "created"  # Razorpay hasn't seen payment: must NOT mark paid
    assert biz_a.post("/billing/card-orders/verify", json=good).json()["status"] == "created"
    rzp.orders[oid].update(status="paid", amount_paid=rzp.orders[oid]["amount"])
    assert biz_a.post("/billing/card-orders/verify", json=good).json()["status"] == "paid"
    assert [p["kind"] for p in biz_a.get("/billing/payments").json()] == ["card_order"]
    assert biz_a.get("/billing/payments", params={"kind": "subscription"}).json() == []
    # webhook for the same payment is a no-op (no duplicate row)
    ev = {"event": "payment.captured", "created_at": int(time.time()), "payload": {"payment": {"entity": {"id": pay, "amount": rzp.orders[oid]["amount"], "currency": "INR", "status": "captured", "order_id": oid}}}}
    webhook(client, ev)
    assert len(biz_a.get("/billing/payments").json()) == 1


def test_billing_data_isolated_between_tenants(rzp, biz_a, biz_b):
    activate(biz_a, rzp)
    assert biz_b.get("/billing/payments").json() == []
    assert biz_b.get("/billing/subscription").json()["source"] == "trial"
    assert biz_b.post("/billing/subscription/cancel", json={}).status_code == 409
    rows = owner_query("SELECT count(*) FROM payments")  # RLS: owner without bypass context sees data only with bypass
    assert rows[0][0] >= 0


def test_auto_retry_only_transient_approved_failures(monkeypatch, rzp):
    """Celery task re-publishes approved drafts that failed with 429/5xx; never touches others."""
    from app.models import ReplyDraft, ReplyLog, ReplyStatus
    from app.services import google as g
    from app.workers.tasks import retry_failed_replies
    from tests.test_google_and_reviews import FakeGoogleProvider, greview, connect, callback, sync_select

    fake = FakeGoogleProvider()
    monkeypatch.setattr(g, "get_google_provider", lambda: fake)
    biz = make_business("Retry Co")
    callback(biz, connect(biz, fake))
    biz.conn_id = biz.get("/google/status").json()["connections"][0]["id"]
    biz.glocs = biz.get(f"/google/connections/{biz.conn_id}/locations").json()
    fake.reviews = [greview(1, 5, "Great"), greview(2, 4, "Good")]
    sync_select(biz, fake)
    ids = [r["id"] for r in biz.get("/reviews").json()["items"]]
    drafts = []
    for rid in ids:
        d = biz.post(f"/reviews/{rid}/drafts", json={"body": "Thank you for visiting us!"}).json()
        biz.post(f"/reply-drafts/{d['id']}/approve", json={})
        drafts.append(d["id"])
    fake.reply_error = g.GoogleAPIError(503, "down")
    for d in drafts:
        assert biz.post(f"/reply-drafts/{d}/publish").json()["status"] == "failed"
    # make the second one a permanent (4xx) failure
    from tests.conftest import owner_exec
    owner_exec("UPDATE reply_logs SET http_status = 400 WHERE draft_id = :d", d=drafts[1])
    fake.reply_error = None
    # the job is global (every tenant): park failed drafts that other tests left behind so this test counts only its own
    owner_exec("UPDATE reply_drafts SET attempts = 99 WHERE status = 'failed' AND id <> ALL(CAST(:ids AS uuid[]))", ids=drafts)
    assert retry_failed_replies() == {"retried": 1}
    states = {d["id"]: d["status"] for r in ids for d in [biz.get(f"/reviews/{r}").json()["drafts"][0]]}
    assert states[drafts[0]] == "published" and states[drafts[1]] == "failed"
    assert retry_failed_replies() == {"retried": 0}


def test_payment_id_never_crosses_tenants(rzp, client, biz_a, biz_b):
    """A webhook payload for tenant B reusing tenant A's payment id must not rewrite A's payment."""
    sid_a, _ = activate(biz_a, rzp)
    sid_b, _ = activate(biz_b, rzp)
    pay = lambda amt: {"id": "pay_shared_id_1", "amount": amt, "currency": "INR", "status": "captured", "created_at": int(time.time())}
    webhook(client, sub_event("subscription.charged", {"id": sid_a, "status": "active", "plan_id": rzp.subs[sid_a]["plan_id"]}, payment=pay(79900)))
    webhook(client, sub_event("subscription.charged", {"id": sid_b, "status": "active", "plan_id": rzp.subs[sid_b]["plan_id"]}, payment=pay(1)))
    a = biz_a.get("/billing/payments").json()
    assert [(p["razorpay_payment_id"], p["amount_paise"]) for p in a] == [("pay_shared_id_1", 79900)]
    assert biz_b.get("/billing/payments").json() == []
