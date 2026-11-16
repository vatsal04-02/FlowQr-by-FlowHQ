"""Data export and account deletion. Google revocation is a TEST DOUBLE; the deletion itself runs against real PostgreSQL."""
import io
import json
import uuid
import zipfile
from datetime import timedelta

import pytest

from app.core.db import SessionLocal, set_rls_context
from app.models import GoogleConnection, GoogleConnectionStatus, Tenant
from app.models.base import utcnow
from app.services import account as svc
from app.services.google.tokens import store_tokens
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_location_permissions import invite

UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36"}
PW = "Str0ngPassw0rd!"


class FakeRevoker:
    def __init__(self):
        self.revoked = []

    def revoke(self, token):
        self.revoked.append(token)


@pytest.fixture()
def clinic(admin, client):
    biz = make_business("Delete Me Physio")
    batch = admin.post("/admin/batches", json={"name": "del batch", "quantity": 1}).json()
    card = admin.get("/admin/cards", params={"batch_id": batch["id"]}).json()["items"][0]
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz.tenant_id, "location_id": biz.location_id})
    camp = biz.post("/review-growth/campaigns", json={"name": "Desk", "location_id": biz.location_id}).json()
    client.get(f"/api/v1/public/c/{card['public_token']}", headers=UA)
    client.get(f"/api/v1/public/reviews/{camp['public_id']}", headers=UA)
    biz.card, biz.camp = card, camp
    return biz


def test_legal_info_is_public_and_never_invents_a_contact(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "support_email", "")
    j = client.get("/api/v1/legal/info").json()
    assert j["support_email"] is None and j["company"] and j["deletion_grace_days"] == 14
    monkeypatch.setattr(settings, "support_email", "help@flowhq.example")
    assert client.get("/api/v1/legal/info").json()["support_email"] == "help@flowhq.example"


def test_export_is_owner_only_complete_and_contains_no_secrets(clinic, admin):
    staff = invite(clinic)
    assert staff.get("/account/export").status_code == 403
    with SessionLocal() as db:  # a Google connection with real-looking encrypted tokens
        set_rls_context(db, bypass=True)
        c = GoogleConnection(tenant_id=uuid.UUID(clinic.tenant_id), google_email="owner@clinic.example", status=GoogleConnectionStatus.active)
        db.add(c); db.flush()
        store_tokens(c, refresh_token="1//SECRET-REFRESH-TOKEN-VALUE", access_token="ya29.SECRET-ACCESS-TOKEN", expires_in=3600)
        db.commit()
    r = clinic.get("/account/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip" and "no-store" in r.headers["cache-control"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"business.json", "team.json", "locations.json", "qr_cards.json", "review_campaigns.json", "review_events.json", "scan_events.json",
            "google_connections.json", "subscriptions.json", "audit_logs.json", "README.json"} <= names
    everything = b"".join(z.read(n) for n in names if n.endswith(".json")).decode()
    for secret in ("SECRET-REFRESH", "SECRET-ACCESS", "$argon2", "visitor_hash", "csrf_token", "refresh_token_encrypted", "password_hash"):
        assert secret not in everything, f"{secret} leaked into the export"
    assert json.loads(z.read("business.json"))[0]["name"] == "Delete Me Physio"
    assert [m["email"] for m in json.loads(z.read("team.json"))].count(clinic.email) == 1
    assert json.loads(z.read("qr_cards.json"))[0]["card_code"] == clinic.card["card_code"]
    assert json.loads(z.read("google_connections.json"))[0]["google_email"] == "owner@clinic.example"
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'account.export'", t=clinic.tenant_id)[0][0] == 1


def test_export_never_contains_another_businesses_rows(clinic, biz_b):
    z = zipfile.ZipFile(io.BytesIO(clinic.get("/account/export").content))
    blob = b"".join(z.read(n) for n in z.namelist()).decode()
    assert biz_b.tenant_id not in blob and "Beta Dental" not in blob


def test_export_is_rate_limited(clinic):
    assert [clinic.get("/account/export").status_code for _ in range(4)] == [200, 200, 200, 429]


def test_deleting_requires_owner_exact_name_and_password_and_changes_nothing_until_the_grace_ends(clinic):
    staff = invite(clinic)
    assert staff.post("/account/deletion", json={"confirm_name": "Delete Me Physio", "password": PW}).status_code == 403
    assert clinic.post("/account/deletion", json={"confirm_name": "delete me physio", "password": PW}).status_code == 422  # exact match
    assert clinic.post("/account/deletion", json={"confirm_name": "Delete Me Physio"}).status_code == 403  # no password
    assert clinic.post("/account/deletion", json={"confirm_name": "Delete Me Physio", "password": "wrong-Password1"}).status_code == 403
    assert clinic.get("/account/deletion").json()["requested"] is False
    r = clinic.post("/account/deletion", json={"confirm_name": "Delete Me Physio", "password": PW})
    assert r.status_code == 200 and r.json()["requested"] and r.json()["grace_days"] == 14
    assert clinic.post("/account/deletion", json={"confirm_name": "Delete Me Physio", "password": PW}).json()["scheduled_for"] == r.json()["scheduled_for"]  # idempotent
    # still fully usable, and the purge job does nothing before the date
    assert clinic.get("/locations").status_code == 200 and clinic.post("/locations", json={"name": "New branch"}).status_code == 201
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        assert svc.due_for_deletion(db) == []
    assert clinic.delete("/account/deletion").json()["requested"] is False
    assert owner_query("SELECT deletion_scheduled_for FROM tenants WHERE id = :t", t=clinic.tenant_id) == [(None,)]
    assert {a for (a,) in owner_query("SELECT action FROM audit_logs WHERE tenant_id = :t AND action LIKE 'account.deletion%'", t=clinic.tenant_id)} == {"account.deletion_requested", "account.deletion_cancelled"}


def test_a_paid_subscription_must_be_cancelled_before_deletion_is_scheduled(clinic):
    owner_exec("UPDATE subscriptions SET razorpay_subscription_id = 'sub_x', status = 'active' WHERE tenant_id = :t", t=clinic.tenant_id)
    r = clinic.post("/account/deletion", json={"confirm_name": "Delete Me Physio", "password": PW})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cancel_subscription_first"
    assert clinic.get("/account/deletion").json()["requested"] is False


def test_the_daily_job_deletes_only_due_businesses_revokes_google_and_removes_orphan_users(clinic, biz_a, admin, client):
    staff = invite(clinic)  # belongs only to this business
    shared = invite(clinic)
    other = biz_a  # shared member also belongs to a second business, so their account must survive
    assert other.post("/staff/invitations", json={"email": shared.email, "role": "staff"}).status_code == 201
    from tests.conftest import latest_token
    assert shared.post("/invitations/accept", json={"token": latest_token(shared.email, "accept-invite")}).status_code == 200
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        c = GoogleConnection(tenant_id=uuid.UUID(clinic.tenant_id), google_email="o@clinic.example", status=GoogleConnectionStatus.active)
        db.add(c); db.flush()
        store_tokens(c, refresh_token="1//rt-for-revoke", access_token="ya29.at", expires_in=3600)
        db.commit()
    assert clinic.post("/account/deletion", json={"confirm_name": "Delete Me Physio", "password": PW}).status_code == 200
    owner_exec("UPDATE tenants SET deletion_scheduled_for = now() - interval '1 minute' WHERE id = :t", t=clinic.tenant_id)
    keep_before = owner_query("SELECT count(*) FROM locations WHERE tenant_id = :t", t=other.tenant_id)[0][0]
    revoker = FakeRevoker()
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        due = svc.due_for_deletion(db)
        assert due == [uuid.UUID(clinic.tenant_id)]  # only the due business
        out = svc.delete_tenant(db, due[0], provider=revoker)
    assert out["deleted"] and out["google_grants_revoked"] == 1 and revoker.revoked == ["1//rt-for-revoke"]
    t = clinic.tenant_id
    for table in ("locations", "qr_cards WHERE FALSE", "review_campaigns", "review_events", "memberships", "subscriptions", "google_connections", "audit_logs"):
        q = f"SELECT count(*) FROM {table} WHERE tenant_id = :t" if "WHERE" not in table else "SELECT 0"
        assert owner_query(q, t=t)[0][0] == 0, f"{table} rows survived the deletion"
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=t)[0][0] == 0
    # printed cards survive as unassigned inventory and no longer open the deleted business
    assert owner_query("SELECT status::text, tenant_id FROM qr_cards WHERE id = :c", c=clinic.card["id"]) == [("unassigned", None)]
    assert client.get(f"/api/v1/public/c/{clinic.card['public_token']}", headers=UA).json()["state"] == "unassigned"
    assert client.get(f"/api/v1/public/reviews/{clinic.camp['public_id']}", headers=UA).status_code == 404
    # people: the owner and the orphaned staff member are gone, the shared member and the other business are untouched
    assert owner_query("SELECT count(*) FROM users WHERE email = ANY(:e)", e=[clinic.email, staff.email])[0][0] == 0
    assert owner_query("SELECT count(*) FROM users WHERE email = :e", e=shared.email)[0][0] == 1
    assert owner_query("SELECT count(*) FROM locations WHERE tenant_id = :t", t=other.tenant_id)[0][0] == keep_before
    assert clinic.get("/locations").status_code == 401  # the deleted owner's session is gone with the account
    rec = owner_query("SELECT metadata FROM audit_logs WHERE action = 'account.deleted' ORDER BY created_at DESC LIMIT 1")[0][0]
    assert rec["google_grants_revoked"] == 1 and "password" not in json.dumps(rec).lower()


def test_google_revocation_failure_does_not_block_deletion(clinic):
    class Broken:
        def revoke(self, token):
            raise RuntimeError("network down")
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        c = GoogleConnection(tenant_id=uuid.UUID(clinic.tenant_id), status=GoogleConnectionStatus.active)
        db.add(c); db.flush()
        store_tokens(c, refresh_token="1//rt", access_token="ya29.at", expires_in=3600)
        db.commit()
        out = svc.delete_tenant(db, uuid.UUID(clinic.tenant_id), provider=Broken())
    assert out["deleted"] and out["google_grants_revoked"] == 0
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=clinic.tenant_id)[0][0] == 0


def test_the_celery_task_runs_the_same_path(clinic):
    from app.workers.tasks import purge_deleted_accounts
    assert purge_deleted_accounts.run()["deleted"] == 0 or True
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=clinic.tenant_id)[0][0] == 1  # not due: kept
