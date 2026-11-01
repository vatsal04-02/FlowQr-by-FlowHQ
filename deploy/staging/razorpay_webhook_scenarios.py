#!/usr/bin/env python3
"""Razorpay webhook scenarios against the RUNNING stack (signed with the stack's webhook secret over HTTPS).

This validates OUR handler (signature, idempotency, state machine, entitlements). It does NOT prove that Razorpay itself
will send these payloads: that needs real rzp_test_ keys (see docs/STAGING_READINESS.md).
Prereq: deploy/staging/seed_billing.sh (links the seeded tenant to a Razorpay subscription id + plan ids in the DB).
"""
import hashlib, hmac, json, os, sys, time, uuid
import httpx

D = os.environ.get("STAGING_DOMAIN", "flowqr-staging.dev")
SECRET = os.environ["RAZORPAY_WEBHOOK_SECRET"]
seed = json.load(open("/out/seed.json"))
SUB, PLAN, ORDER = "sub_STAGING0001", "plan_STAGING_growth", "order_STAGING0001"
APP, API = f"https://app.{D}/api/v1", f"https://api.{D}/api/v1"
res = []


def check(ok, name, detail=""):
    res.append(ok); print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)


def post(event: dict, event_id=None, secret=SECRET, raw=None):
    raw = raw if raw is not None else json.dumps(event).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    h = {"X-Razorpay-Signature": sig, "Content-Type": "application/json"}
    if event_id: h["X-Razorpay-Event-Id"] = f"{event_id}-{seed['run']}"  # unique per run: idempotency is global
    return httpx.post(f"{API}/billing/razorpay/webhook", content=raw, headers=h, timeout=20)


owner = httpx.Client(base_url=APP, timeout=20)
r = owner.post("/auth/login", json={"email": seed["owner"]["email"], "password": seed["owner"]["password"]}); H = {"X-CSRF-Token": r.json()["csrf_token"]}
sub = lambda: owner.get("/billing/subscription").json()
pays = lambda: owner.get("/billing/payments").json()
now = lambda: int(time.time())
ent = lambda s, **kw: {"id": SUB, "plan_id": PLAN, "status": s, "current_start": now(), "current_end": now() + 30 * 86400, **kw}
ev = lambda t, s=None, pay=None, at=None: {"event": t, "created_at": at or now(), "payload": ({"subscription": {"entity": s}} if s else {}) | ({"payment": {"entity": pay}} if pay else {})}
payment = lambda pid, st="captured", **kw: {"id": pid, "amount": 79900, "currency": "INR", "status": st, "method": "upi", "created_at": now(), **kw}

# 1 signature validation
body = json.dumps(ev("subscription.activated", ent("active"))).encode()
check(post({}, raw=body, secret="wrong-secret").status_code == 400, "wrong signature rejected (400)")
check(httpx.post(f"{API}/billing/razorpay/webhook", content=body, timeout=20).status_code == 400, "missing signature rejected (400)")
sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
check(httpx.post(f"{API}/billing/razorpay/webhook", content=body.replace(b"active", b"actiVe", 1), headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"}, timeout=20).status_code == 400, "tampered body rejected (400)")
check(sub()["status"] == "trialing", "rejected webhooks changed nothing (still trialing)")

# 2 activation
r = post(ev("subscription.activated", ent("active")), "evt_stg_activated")
check(r.status_code == 200 and r.json()["status"] == "processed", "subscription.activated processed")
s = sub(); check(s["status"] == "active" and s["plan"] == "growth" and s["source"] == "razorpay" and s["active"], "tenant now active on Growth via Razorpay", f"{s['status']}/{s['plan']}")
# 3 renewal charge
r = post(ev("subscription.charged", ent("active", paid_count=2), payment(f"pay_stg_renew_1_{seed['run']}", invoice_id="inv_stg_1")), "evt_stg_charged_1")
check(r.json()["status"] == "processed" and len(pays()) == 1, "renewal #1 recorded as one captured subscription payment", str([(p["status"], p["amount_paise"]) for p in pays()]))
# 4 duplicate delivery
r = post(ev("subscription.charged", ent("active", paid_count=2), payment(f"pay_stg_renew_1_{seed['run']}", invoice_id="inv_stg_1")), "evt_stg_charged_1")
check(r.status_code == 200 and r.json()["status"] == "duplicate" and len(pays()) == 1, "duplicate webhook delivery is a no-op", r.text)
# same payment, different event id (Razorpay can resend with a new id)
post(ev("subscription.charged", ent("active"), payment(f"pay_stg_renew_1_{seed['run']}", invoice_id="inv_stg_1")), "evt_stg_charged_1b")
check(len(pays()) == 1, "same payment id under a new event id does not double-count")
# 5 second renewal
post(ev("subscription.charged", ent("active", paid_count=3), payment(f"pay_stg_renew_2_{seed['run']}", invoice_id="inv_stg_2")), "evt_stg_charged_2")
check(len(pays()) == 2 and all(p["kind"] == "subscription" and p["status"] == "captured" for p in pays()), "renewal #2 recorded (2 payments total)")
# 6 failed payment -> grace
post(ev(  "payment.failed", pay=payment(f"pay_stg_fail_1_{seed['run']}", "failed", subscription_id=SUB, error_code="BAD_REQUEST_ERROR", error_description="Card declined by bank", created_at=now() + 2), at=now() + 2), "evt_stg_failed_1")
s = sub(); failed = [p for p in pays() if p["status"] == "failed"]
check(s["status"] == "past_due" and s["active"] and bool(s["grace_until"]) and len(failed) == 1 and failed[0]["error_description"] == "Card declined by bank", "payment.failed -> past_due, still active inside grace, failure reason kept", f"{s['status']} grace_until={s['grace_until']}")
post(ev("subscription.pending", ent("pending"), at=now() + 3), "evt_stg_pending_1")
check(sub()["status"] == "past_due", "subscription.pending keeps past_due")
print("PHASE2: need DB shift of past_due_since")  # driven by the shell wrapper
json.dump({"ok": all(res)}, open("/out/phase1.json", "w"))
sys.exit(0 if all(res) else 1)
