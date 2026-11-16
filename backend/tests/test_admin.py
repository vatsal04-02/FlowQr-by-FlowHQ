import time
import uuid

import pytest

from tests.conftest import make_business, make_user
from tests.test_billing import FakeRazorpay, KEY_SECRET, activate, rzp, sig, sub_event, webhook  # noqa: F401

ADMIN_GETS = ["/admin/tenants", "/admin/subscriptions", "/admin/payments", "/admin/card-orders", "/admin/ai-usage", "/admin/audit", "/admin/stats"]


def test_admin_endpoints_closed_to_business_users(biz_a):
    for path in ADMIN_GETS:
        assert biz_a.get(path).status_code == 403, path
    tid = biz_a.tenant_id
    for path, body in [(f"/admin/tenants/{tid}/suspend", {"reason": "abc"}), (f"/admin/tenants/{tid}/subscription", {"plan": "pro", "note": "free"}),
                       (f"/admin/tenants/{tid}/unsuspend", None)]:
        assert biz_a.post(path, json=body).status_code == 403
    assert biz_a.patch(f"/admin/tenants/{tid}/support", json={"status": "open"}).status_code == 403
    assert biz_a.get(f"/admin/tenants/{tid}").status_code == 403


def test_unauthenticated_cannot_reach_admin(client):
    assert client.get("/api/v1/admin/stats").status_code == 401


def test_suspension_blocks_account_and_public_cards_then_restores(admin, biz_a, client):
    b = admin.post("/admin/batches", json={"name": "susp batch", "quantity": 1}).json()
    card = admin.get("/admin/cards", params={"batch_id": b["id"]}).json()["items"][0]
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    ua = {"user-agent": "Mozilla/5.0 (iPhone) Safari/604.1"}
    assert client.get(f"/api/v1/public/c/{card['public_token']}", headers=ua).json()["state"] == "ok"
    assert admin.post(f"/admin/tenants/{biz_a.tenant_id}/suspend", json={"reason": "Chargeback dispute"}).status_code == 204
    r = biz_a.get("/locations")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "account_suspended"
    assert biz_a.get("/auth/me").json()["memberships"][0]["tenant"]["suspension_reason"] == "Chargeback dispute"
    assert client.get(f"/api/v1/public/c/{card['public_token']}", headers={"user-agent": ua["user-agent"] + " 2"}).json()["state"] == "inactive"
    assert admin.post(f"/admin/tenants/{biz_a.tenant_id}/unsuspend").status_code == 204
    assert biz_a.get("/locations").status_code == 200


def test_support_status_and_tenant_detail(admin, biz_a):
    assert admin.patch(f"/admin/tenants/{biz_a.tenant_id}/support", json={"status": "open", "note": "Asked about NFC"}).status_code == 204
    d = admin.get(f"/admin/tenants/{biz_a.tenant_id}").json()
    assert d["tenant"]["support_status"] == "open" and d["tenant"]["support_note"] == "Asked about NFC"
    assert d["subscription"]["status"] == "trialing" and d["members"][0]["role"] == "owner" and len(d["locations"]) == 1
    assert admin.patch(f"/admin/tenants/{biz_a.tenant_id}/support", json={"status": "bogus"}).status_code == 422
    assert admin.get(f"/admin/tenants/{uuid.uuid4()}").status_code == 404


def test_subscription_override_and_audit_trail(admin, biz_a):
    r = admin.post(f"/admin/tenants/{biz_a.tenant_id}/subscription", json={"plan": "pro", "status": "manual", "note": "Pilot customer, 3 months free"})
    assert r.status_code == 200 and r.json()["source"] == "manual"
    s = biz_a.get("/billing/subscription").json()
    assert s["plan"] == "pro" and s["limits"]["locations"] == 10 and s["active"]
    r = admin.post(f"/admin/tenants/{biz_a.tenant_id}/subscription", json={"extend_trial_days": 30, "status": "trialing", "note": "Extension"})
    assert r.status_code == 200 and r.json()["status"] == "trialing"
    log = admin.get("/admin/audit", params={"tenant_id": biz_a.tenant_id, "action": "admin.subscription"}).json()
    assert len(log) == 2 and log[0]["meta"]["note"] and log[0]["user"] == "root@flowhq-admin.example.com"
    assert admin.post(f"/admin/tenants/{biz_a.tenant_id}/subscription", json={"plan": "starter"}).status_code == 422  # note required


def test_admin_sees_payments_separately_and_card_orders_need_payment(admin, rzp, client, biz_a):
    sid, _ = activate(biz_a, rzp)
    webhook(client, sub_event("subscription.charged", {"id": sid, "status": "active", "plan_id": rzp.subs[sid]["plan_id"]},
                              payment={"id": "pay_admin_1", "amount": 79900, "status": "captured"}))
    shipping = {"name": "Dr A", "phone": "9876543210", "address_line": "1 Main Road", "city": "Lucknow", "state": "UP", "postal_code": "226001"}
    o = biz_a.post("/billing/card-orders", json={"quantity": 10, "shipping": shipping}).json()
    pays = admin.get("/admin/payments").json()
    assert {p["kind"] for p in pays} >= {"subscription"} and all(p["tenant"] for p in pays)
    assert admin.get("/admin/payments", params={"kind": "card_order"}).json() == []
    order = admin.get("/admin/card-orders", params={"status": "created"}).json()[0]
    assert admin.patch(f"/admin/card-orders/{order['id']}", json={"status": "shipped"}).status_code == 409  # unpaid: cannot ship
    rzp.orders[o["order_id"]].update(status="paid", amount_paid=o["amount_paise"])
    pid = "pay_card_x"
    biz_a.post("/billing/card-orders/verify", json={"razorpay_order_id": o["order_id"], "razorpay_payment_id": pid, "razorpay_signature": sig(KEY_SECRET, f"{o['order_id']}|{pid}")})
    r = admin.patch(f"/admin/card-orders/{order['id']}", json={"status": "shipped", "tracking_note": "India Post EN123"})
    assert r.status_code == 200 and biz_a.get("/billing/card-orders").json()[0]["tracking_note"] == "India Post EN123"
    assert admin.get("/admin/payments", params={"kind": "card_order"}).json()[0]["amount_paise"] == o["amount_paise"]


def test_user_deactivation_kills_sessions(admin, biz_a):
    me = biz_a.get("/auth/me").json()["user"]["id"]
    assert admin.patch(f"/admin/users/{me}", json={"is_active": False}).status_code == 204
    assert biz_a.get("/auth/me").status_code == 401
    r = biz_a.http.post("/api/v1/auth/login", json={"email": biz_a.email, "password": biz_a.password})
    assert r.status_code == 401
    admin.patch(f"/admin/users/{me}", json={"is_active": True})
    assert biz_a.http.post("/api/v1/auth/login", json={"email": biz_a.email, "password": biz_a.password}).status_code == 200


def test_platform_stats_and_ai_usage(admin, rzp, client, biz_a):
    activate(biz_a, rzp, "growth")
    st = admin.get("/admin/stats").json()
    assert st["mrr_paise"] >= 79900 and st["subscriptions_by_status"].get("active", 0) >= 1 and len(st["signups_30d"]) == 30
    assert set(st["revenue_paise"]) == {"subscription", "card_order"}
    usage = admin.get("/admin/ai-usage").json()
    assert any(u["tenant_id"] == biz_a.tenant_id for u in usage)
    t = admin.get("/admin/tenants", params={"search": "Alpha"}).json()
    assert t["total"] >= 1 and t["items"][0]["owner_email"]
    assert admin.get("/admin/tenants", params={"status": "active"}).json()["total"] >= 1


def test_email_verification_flow():
    s = make_user(verify=False)
    assert s.get("/auth/me").json()["user"]["email_verified_at"] is None
    s.post("/tenants", json={"name": "Verify Co", "category": "Salon"})
    assert s.post("/staff/invitations", json={"email": "x1@example.com"}).json()["detail"]["code"] == "email_not_verified"
    from tests.conftest import latest_token
    assert s.http.post("/api/v1/auth/verify-email", json={"token": "x" * 30}).status_code == 400
    tok = latest_token(s.email, "verify-email")
    assert s.http.post("/api/v1/auth/verify-email", json={"token": tok}).status_code == 204
    assert s.http.post("/api/v1/auth/verify-email", json={"token": tok}).status_code == 400  # single use
    assert s.get("/auth/me").json()["user"]["email_verified_at"]
    assert s.post("/staff/invitations", json={"email": "x1@example.com"}).status_code == 201
