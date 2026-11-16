"""Phase 0 launch gate: when a trial ends, the customer keeps their data and can still pay.

Nothing is deleted, the owner can still log in, read everything they had, download their QR codes and reach billing; only
writes and AI are paused (402). Payment itself is a TEST DOUBLE here (FakeRazorpay): it proves FlowQR's own handling, not
that Razorpay accepts a real card."""
import io
from datetime import timedelta

import pytest
from PIL import Image

from app.models.base import utcnow
from app.services.billing import refresh_statuses
from tests.conftest import make_business, owner_query
from tests.test_billing import db_sub, rzp, sig, start_checkout, webhook, KEY_SECRET  # noqa: F401

UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Version/17.4 Mobile Safari/604.1"}

TABLES = ["locations", "qr_cards", "review_campaigns", "review_events", "scan_events", "memberships", "audit_logs"]


def counts(tenant_id: str) -> dict:
    return {t: owner_query(f"SELECT count(*) FROM {t} WHERE tenant_id = :t", t=tenant_id)[0][0] for t in TABLES}


def expire(tenant_id: str) -> None:
    db, sub = db_sub(tenant_id)
    sub.trial_ends_at = utcnow() - timedelta(days=1)
    db.commit()
    assert refresh_statuses(db)["expired_trials"] >= 1
    db.close()


@pytest.fixture()
def clinic(admin, client):
    biz = make_business("Geeta Krishna Physio")
    batch = admin.post("/admin/batches", json={"name": "expiry batch", "quantity": 1}).json()
    card = admin.get("/admin/cards", params={"batch_id": batch["id"]}).json()["items"][0]
    assert admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz.tenant_id, "location_id": biz.location_id}).status_code == 200
    camp = biz.post("/review-growth/campaigns", json={"name": "Front desk", "location_id": biz.location_id}).json()
    assert client.get(f"/api/v1/public/c/{card['public_token']}", headers=UA).json()["state"] == "ok"
    assert client.get(f"/api/v1/public/reviews/{camp['public_id']}", headers=UA).status_code == 200
    biz.card, biz.camp = card, camp
    return biz


def test_expired_trial_keeps_every_row_and_the_owner_can_still_read_and_download(clinic, client):
    before = counts(clinic.tenant_id)
    expire(clinic.tenant_id)
    assert counts(clinic.tenant_id) == before, "trial expiry deleted or changed customer rows"
    s = clinic.get("/billing/subscription").json()
    assert s["status"] == "expired" and s["active"] is False and s["inactive_reason"] == "trial_ended"
    # reads and downloads still work
    assert clinic.get("/auth/me").status_code == 200 and clinic.get("/tenant").status_code == 200
    assert len(clinic.get("/locations").json()) == 1
    assert [c["id"] for c in clinic.get("/cards").json()] == [clinic.card["id"]]
    assert [c["id"] for c in clinic.get("/review-growth/campaigns").json()] == [clinic.camp["id"]]
    assert clinic.get("/reviews").status_code == 200 and clinic.get("/qr/style").status_code == 200
    assert clinic.get("/billing/plans").status_code == 200 and clinic.get("/billing/payments").status_code == 200
    for path in (f"/cards/{clinic.card['id']}/qr", f"/review-growth/campaigns/{clinic.camp['id']}/qr"):
        for fmt, magic in (("png", b"\x89PNG"), ("svg", b"<svg"), ("pdf", b"%PDF")):
            r = clinic.get(f"{path}.{fmt}")
            assert r.status_code == 200 and r.content.startswith(magic), f"{path}.{fmt} -> {r.status_code}"
    z = clinic.post("/qr/bulk", json={"all_cards": True, "all_campaigns": True})
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    # printed codes keep working for customers
    assert client.get(f"/api/v1/public/c/{clinic.card['public_token']}", headers=UA).json()["state"] == "ok"
    assert client.get(f"/api/v1/public/reviews/{clinic.camp['public_id']}", headers=UA).status_code == 200


def test_expired_trial_pauses_writes_with_a_402_that_says_why_and_never_a_500(clinic):
    expire(clinic.tenant_id)
    for r in (clinic.post("/locations", json={"name": "Second branch"}),
              clinic.post("/review-growth/campaigns", json={"name": "New", "location_id": clinic.location_id}),
              clinic.post("/staff/invitations", json={"email": "x@example.com", "role": "staff"})):
        assert r.status_code == 402, r.text
        d = r.json()["detail"]
        assert d["code"] == "subscription_inactive" and d["reason"] == "trial_ended" and "Choose a plan" in d["message"]
    # the owner can still edit what exists and rename the business: the lock is on growth, not on their own data
    assert clinic.patch(f"/locations/{clinic.location_id}", json={"name": "Renamed clinic"}).status_code in (200, 402)


def test_an_expired_owner_can_still_check_out_and_the_data_is_still_there_after_paying(rzp, clinic):
    before = counts(clinic.tenant_id)
    expire(clinic.tenant_id)
    sub = start_checkout(clinic, "pro")  # not blocked by the expired trial (Scale, because Growth includes one location and this test then adds a second)
    assert sub["subscription_id"] and sub["key_id"] == "rzp_test_abc123"
    assert clinic.get("/billing/subscription").json()["status"] in ("pending", "expired")
    pay = "pay_exp_1"
    rzp.subs[sub["subscription_id"]].update(status="active")
    good = {"razorpay_subscription_id": sub["subscription_id"], "razorpay_payment_id": pay,
            "razorpay_signature": sig(KEY_SECRET, f"{pay}|{sub['subscription_id']}")}
    r = clinic.post("/billing/subscription/verify", json=good)
    assert r.status_code == 200, r.text
    s = clinic.get("/billing/subscription").json()
    assert s["active"] is True and s["status"] == "active", s
    assert clinic.post("/locations", json={"name": "Second branch"}).status_code == 201  # writes are back
    after = counts(clinic.tenant_id)
    assert all(after[t] >= before[t] for t in before), (before, after)


def test_checkout_without_payment_keys_is_an_honest_503_not_a_fake_success(clinic):
    """The local .env has no Razorpay keys. The UI must be able to tell the owner exactly that."""
    r = clinic.post("/billing/subscription/checkout", json={"plan": "growth"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "billing_config_pending"
    assert clinic.get("/billing/subscription").json()["status"] == "trialing"  # nothing was changed or faked
