#!/usr/bin/env python3
"""Phase 2: after the grace period elapsed (shell shifted past_due_since), check lapse, recovery, cancellation, order payments."""
import hashlib, hmac, json, os, sys, time
import httpx

D = os.environ.get("STAGING_DOMAIN", "flowqr-staging.dev")
SECRET = os.environ["RAZORPAY_WEBHOOK_SECRET"]
seed = json.load(open("/out/seed.json"))
SUB, PLAN, ORDER = "sub_STAGING0001", "plan_STAGING_growth", "order_STAGING0001"
APP, API = f"https://app.{D}/api/v1", f"https://api.{D}/api/v1"
res = []
def check(ok, name, detail=""):
    res.append(ok); print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)
def post(event, event_id):
    raw = json.dumps(event).encode()
    return httpx.post(f"{API}/billing/razorpay/webhook", content=raw, timeout=20, headers={"X-Razorpay-Signature": hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest(), "X-Razorpay-Event-Id": f"{event_id}-{seed['run']}", "Content-Type": "application/json"})
owner = httpx.Client(base_url=APP, timeout=20)
r = owner.post("/auth/login", json={"email": seed["owner"]["email"], "password": seed["owner"]["password"]}); H = {"X-CSRF-Token": r.json()["csrf_token"]}
sub = lambda: owner.get("/billing/subscription").json()
now = lambda: int(time.time())
ent = lambda s, **kw: {"id": SUB, "plan_id": PLAN, "status": s, "current_start": now(), "current_end": now() + 30 * 86400, **kw}
ev = lambda t, s=None, pay=None, order=None, at=None: {"event": t, "created_at": at or now(), "payload": ({"subscription": {"entity": s}} if s else {}) | ({"payment": {"entity": pay}} if pay else {}) | ({"order": {"entity": order}} if order else {})}

s = sub()
check(s["active"] is False and s["inactive_reason"] == "payment_failed", "after grace period: subscription inactive (payment_failed)", f"{s['status']}")
r = owner.post("/locations", json={"name": "Blocked while unpaid"}, headers=H)
check(r.status_code == 402 and r.json()["detail"]["code"] == "subscription_inactive", "writes blocked while unpaid (402)")
check(owner.get("/locations").status_code == 200, "reads still allowed while unpaid")
pub = httpx.get(f"https://go.{D}/api/v1/public/c/{seed['card']['token']}", headers={"User-Agent": "Mozilla/5.0 (iPhone) Safari/604.1"}, timeout=20).json()
check(pub.get("state") == "ok", "printed card still resolves while unpaid")
# recovery
post(ev("subscription.charged", ent("active"), {"id": f"pay_stg_recover_{seed['run']}", "amount": 79900, "currency": "INR", "status": "captured", "created_at": now() + 5}, at=now() + 5), "evt_stg_recover")
s = sub(); check(s["status"] == "active" and s["active"], "successful retry charge restores access", s["status"])
check(owner.post("/locations", json={"name": "Second branch"}, headers=H).status_code == 201, "writes work again")
# stale event ignored
post(ev("subscription.halted", ent("halted"), at=now() - 3600), "evt_stg_stale")
check(sub()["status"] == "active", "stale (older) halted event ignored")
# halted -> inactive
post(ev("subscription.halted", ent("halted"), at=now() + 20), "evt_stg_halted")
s = sub(); check(s["status"] == "halted" and not s["active"], "subscription.halted -> inactive")
post(ev("subscription.charged", ent("active"), {"id": f"pay_stg_recover2_{seed['run']}", "amount": 79900, "currency": "INR", "status": "captured", "created_at": now() + 30}, at=now() + 30), "evt_stg_recover2")
check(sub()["active"], "re-activation after halt")
# cancellation: cancel API with DUMMY keys must fail safely
r = owner.post("/billing/subscription/cancel", json={"at_cycle_end": True}, headers=H)
check(r.status_code == 502 and sub()["cancel_at_period_end"] is False, "cancel API with dummy keys fails safely (502) and changes no state", f"HTTP {r.status_code}")
check(owner.post("/billing/subscription/checkout", json={"plan": "essential"}, headers=H).status_code in (409, 502), "checkout against real Razorpay with dummy keys fails safely (not 200)")
post(ev("subscription.cancelled", ent("cancelled", current_end=now() + 5 * 86400), at=now() + 40), "evt_stg_cancelled")
s = sub(); check(s["status"] == "canceled" and s["active"], "subscription.cancelled keeps access until period end", s["status"])
# card order payment (separate kind)
order = owner.get("/billing/card-orders").json()
check(len(order) == 1 and order[0]["status"] == "created", "seeded card order is unpaid", str(order and order[0]["status"]))
post(ev("payment.captured", pay={"id": f"pay_stg_card_1_{seed['run']}", "amount": order[0]["amount_paise"], "currency": "INR", "status": "captured", "order_id": ORDER, "created_at": now()}), "evt_stg_card_paid")
order = owner.get("/billing/card-orders").json()
kinds = sorted({p["kind"] for p in owner.get("/billing/payments").json()})
check(order[0]["status"] == "paid" and kinds == ["card_order", "subscription"], "card payment marks order paid and is a separate payment kind", f"{order[0]['status']} {kinds}")
check(len(owner.get("/billing/payments", params={"kind": "card_order"}).json()) == 1, "card_order payments filterable separately")
sys.exit(0 if all(res) else 1)
