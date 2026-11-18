"""Admin-assisted export and deletion for businesses with no owner login; revoking a claim with optional allowlist removal; the aggregate managed-usage view.

The rules under test: a request only exists for an ownerless business; nothing is exported or deleted before the identity of the requester is verified against the contact details ALREADY on
the record; deletion is never automatic (not by the daily job either), needs a cooling-off period, the typed name and an acknowledgement; every step is an event and an audit entry; the
record outlives the business; the allowlist entry a claim created is removed only on request and only when nothing else needs it."""
import io
import json
import uuid
import zipfile
from datetime import timedelta

import pytest

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.models.base import utcnow
from app.services import account as account_svc
from tests.conftest import make_business, make_user, owner_exec, owner_query
from tests.test_admin_businesses import create, live_card, payload

def biz(admin, **kw):
    """A business with its OWN phone number each time (the duplicate check would otherwise refuse the second one)."""
    kw.setdefault("phone", f"9{uuid.uuid4().int % 10**9:09d}")
    return create(admin, **kw)


def ask(admin, b, kind="export", **kw):
    body = {"kind": kind, "requester_name": "Ramesh Sharma", "requester_role": "owner", "received_via": "phone", "requester_contact": "98765 43210", "note": "wants a copy"}
    body.update(kw)
    return admin.post(f"/admin/tenants/{b['id']}/data-requests", json=body)


def verify(admin, rid, **kw):
    phone = owner_query("SELECT t.phone FROM tenants t JOIN data_requests r ON r.tenant_id = t.id WHERE r.id = :r", r=rid)[0][0]
    body = {"method": "callback_to_shop_phone", "contacted_on": phone, "note": "called back, spoke to the owner", "confirm": True}
    body.update(kw)
    return admin.post(f"/admin/data-requests/{rid}/verify", json=body)


@pytest.fixture()
def claims_on(monkeypatch):
    monkeypatch.setattr(settings, "claim_invitations_enabled", True)


# ============================================================================================================================ 1. export and deletion requests
def test_a_request_is_logged_for_an_ownerless_business_and_changes_no_data(admin):
    b = biz(admin)
    before = owner_query("SELECT count(*) FROM locations WHERE tenant_id = :t", t=b["id"])[0][0]
    r = ask(admin, b)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "open" and d["kind"] == "export" and d["business_name"] == b["name"] and d["events"][0]["action"] == "requested"
    assert owner_query("SELECT count(*) FROM locations WHERE tenant_id = :t", t=b["id"])[0][0] == before
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'admin.data_request_created'", t=b["id"])[0][0] == 1
    assert ask(admin, b).status_code == 409  # one open request of a kind at a time
    assert ask(admin, b, kind="deletion").status_code == 201  # a different kind is fine


def test_a_business_with_an_owner_is_refused_because_the_owner_has_the_real_tools(admin):
    own = make_business("Owned Clinic")
    r = ask(admin, {"id": own.tenant_id})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "has_owner"


def test_the_data_request_routes_are_admin_only(admin, biz_a):
    from fastapi.testclient import TestClient

    from app.main import app

    b = biz(admin)
    rid = ask(admin, b).json()["id"]
    routes = [("post", f"/admin/tenants/{b['id']}/data-requests", {"kind": "export"}), ("get", f"/admin/tenants/{b['id']}/data-requests", None), ("get", "/admin/data-requests", None),
              ("post", f"/admin/data-requests/{rid}/verify", {"method": "in_person_at_shop", "confirm": True}), ("post", f"/admin/data-requests/{rid}/reject", {"reason": "not allowed"}),
              ("post", f"/admin/data-requests/{rid}/cancel", {"reason": "not allowed"}), ("get", f"/admin/data-requests/{rid}/export", None),
              ("post", f"/admin/data-requests/{rid}/delivered", {"delivery": "other"}), ("post", f"/admin/data-requests/{rid}/execute-deletion", {"confirm_name": b["name"], "acknowledge": True}),
              ("get", "/admin/managed-usage", None), ("post", f"/admin/tenants/{b['id']}/claim/{uuid.uuid4()}/revoke", {"remove_from_allowlist": True})]
    anon = TestClient(app, base_url="http://testserver")
    for method, path, body in routes:
        kw = {"json": body} if body is not None else {}
        assert anon.request(method.upper(), "/api/v1" + path, **kw).status_code in (401, 403), (method, path)
        assert getattr(biz_a, method)(path, **kw).status_code == 403, (method, path)
    assert owner_query("SELECT status FROM data_requests WHERE id = :r", r=rid)[0][0] == "open"  # nothing was changed by a refused caller
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=b["id"])[0][0] == 1


def test_nothing_is_exported_before_the_requester_is_verified(admin):
    b = biz(admin)
    rid = ask(admin, b).json()["id"]
    r = admin.get(f"/admin/data-requests/{rid}/export")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_ready"
    assert admin.post(f"/admin/data-requests/{rid}/delivered", json={"delivery": "handed_over_in_person"}).status_code == 409


def test_verification_must_use_the_contact_details_already_on_the_record(admin):
    b = biz(admin, email="shop@sweets.example")
    rid = ask(admin, b).json()["id"]
    # a number given in the request is not the number on the record
    r = verify(admin, rid, contacted_on="9000000001")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_the_number_on_record"
    r = verify(admin, rid, method="email_from_known_address", contacted_on="someone.else@example.com")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_the_email_on_record"
    assert verify(admin, rid, confirm=False).status_code == 422  # the administrator's own confirmation is required
    assert verify(admin, rid, method="other", note=None).status_code == 422  # "other" must be described
    assert owner_query("SELECT status FROM data_requests WHERE id = :r", r=rid)[0][0] == "open"
    ok = verify(admin, rid, method="email_from_known_address", contacted_on="Shop@Sweets.example")
    assert ok.status_code == 200 and ok.json()["status"] == "verified" and ok.json()["contact_matched_record"] is True and ok.json()["verified_by"] == "root@flowhq-admin.example.com"


def test_a_callback_needs_a_phone_on_record(admin):
    b = biz(admin)
    owner_exec("UPDATE tenants SET phone = NULL WHERE id = :t", t=b["id"])
    rid = ask(admin, b).json()["id"]
    assert verify(admin, rid).json()["detail"]["code"] == "no_phone_on_record"
    assert verify(admin, rid, method="in_person_at_shop", contacted_on=None).status_code == 200  # in person needs no number


def test_an_export_after_verification_is_the_owner_export_without_secrets_and_nothing_is_emailed(admin):
    from app.services.mailer import OUTBOX

    b = biz(admin)
    rid = ask(admin, b).json()["id"]
    assert verify(admin, rid).status_code == 200
    n = len(OUTBOX)
    r = admin.get(f"/admin/data-requests/{rid}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip" and "no-store" in r.headers["cache-control"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert json.loads(z.read("business.json"))[0]["name"] == b["name"]
    assert "tenant_agreements.json" in z.namelist() and "data_requests.json" in z.namelist()
    blob = b"".join(z.read(x) for x in z.namelist()).decode()
    for secret in ("password_hash", "refresh_token_encrypted", "visitor_hash", "token_hash"):
        assert secret not in blob
    assert len(OUTBOX) == n  # the system sends nothing: the administrator hands it over
    assert owner_query("SELECT export_count FROM data_requests WHERE id = :r", r=rid)[0][0] == 1
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'admin.data_request_export_generated'", t=b["id"])[0][0] == 1
    done = admin.post(f"/admin/data-requests/{rid}/delivered", json={"delivery": "handed_over_in_person", "note": "at the shop"})
    assert done.status_code == 200 and done.json()["status"] == "fulfilled"
    assert [e["action"] for e in done.json()["events"]] == ["requested", "verified", "export_generated", "fulfilled"]
    assert admin.get(f"/admin/data-requests/{rid}/export").status_code == 409  # resolved: no further exports


def test_delivery_cannot_be_recorded_before_an_export_was_generated(admin):
    b = biz(admin)
    rid = ask(admin, b).json()["id"]
    verify(admin, rid)
    r = admin.post(f"/admin/data-requests/{rid}/delivered", json={"delivery": "handed_over_in_person"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_generated"


def test_the_requesters_contact_is_erased_when_the_request_ends(admin):
    b = biz(admin)
    rid = ask(admin, b).json()["id"]
    assert owner_query("SELECT requester_contact FROM data_requests WHERE id = :r", r=rid)[0][0] == "98765 43210"
    assert admin.post(f"/admin/data-requests/{rid}/reject", json={"reason": "could not verify the caller"}).json()["status"] == "rejected"
    assert owner_query("SELECT requester_contact, status FROM data_requests WHERE id = :r", r=rid)[0] == (None, "rejected")
    assert admin.post(f"/admin/data-requests/{rid}/cancel", json={"reason": "no longer wanted"}).status_code == 409  # already resolved


def test_a_resolved_request_can_be_made_again(admin):
    b = biz(admin)
    rid = ask(admin, b).json()["id"]
    admin.post(f"/admin/data-requests/{rid}/cancel", json={"reason": "asked by mistake"})
    assert ask(admin, b).status_code == 201


# ---------------------------------------------------------------------------------------------------------------------------- deletion
def deletion_ready(admin, b):
    rid = ask(admin, b, kind="deletion").json()["id"]
    assert verify(admin, rid).status_code == 200
    return rid


def execute(admin, rid, name, ack=True):
    return admin.post(f"/admin/data-requests/{rid}/execute-deletion", json={"confirm_name": name, "acknowledge": ack})


def test_deletion_is_never_automatic_and_does_not_start_the_daily_deletion_job(admin):
    b = biz(admin)
    rid = deletion_ready(admin, b)
    t = owner_query("SELECT deletion_requested_at, deletion_scheduled_for FROM tenants WHERE id = :t", t=b["id"])[0]
    assert t == (None, None)  # the schedule the daily job reads is untouched
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        assert uuid.UUID(b["id"]) not in account_svc.due_for_deletion(db)
    owner_exec("UPDATE tenants SET deletion_scheduled_for = NULL WHERE id = :t", t=b["id"])
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=b["id"])[0][0] == 1
    assert rid


def test_deletion_waits_for_the_cooling_off_period(admin):
    b = biz(admin)
    rid = deletion_ready(admin, b)
    d = admin.get(f"/admin/tenants/{b['id']}").json()["data_requests"][0]
    assert d["deletion"]["ready"] is False and d["deletion"]["reason"] == "cooling_off"
    wait = (__import__("datetime").datetime.fromisoformat(d["eligible_at"].replace("Z", "+00:00")) - utcnow()).days
    assert settings.account_deletion_grace_days - 1 <= wait <= settings.account_deletion_grace_days
    r = execute(admin, rid, b["name"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cooling_off"
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=b["id"])[0][0] == 1


def test_deletion_needs_verification_the_exact_name_and_an_acknowledgement(admin):
    b = biz(admin)
    rid = ask(admin, b, kind="deletion").json()["id"]
    assert execute(admin, rid, b["name"]).json()["detail"]["code"] == "not_verified"
    verify(admin, rid)
    owner_exec("UPDATE data_requests SET eligible_at = now() - interval '1 minute' WHERE id = :r", r=rid)
    assert execute(admin, rid, b["name"].lower()).json()["detail"]["code"] == "name_mismatch"
    assert execute(admin, rid, b["name"], ack=False).json()["detail"]["code"] == "not_acknowledged"
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=b["id"])[0][0] == 1
    export_only = ask(admin, biz(admin)).json()["id"]
    assert execute(admin, export_only, "x").json()["detail"]["code"] == "not_deletion"


def test_an_executed_deletion_erases_the_business_returns_its_cards_and_keeps_the_record(admin):
    b = biz(admin)
    loc = b["location"]["id"]
    card = live_card(admin, b["id"], loc)
    rid = deletion_ready(admin, b)
    owner_exec("UPDATE data_requests SET eligible_at = now() - interval '1 minute' WHERE id = :r", r=rid)
    r = execute(admin, rid, b["name"])
    assert r.status_code == 200 and r.json()["deleted"] is True and r.json()["cards_returned"] == 1
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=b["id"])[0][0] == 0
    assert owner_query("SELECT count(*) FROM locations WHERE tenant_id = :t", t=b["id"])[0][0] == 0
    # the printed card survives as unassigned stock and its public address now says "not set up", never another business's page
    c = owner_query("SELECT status::text, tenant_id FROM qr_cards WHERE id = :c", c=card["id"])[0]
    assert c[1] is None and c[0] == "unassigned"
    # the request and its history outlive the business, the contact detail is gone, and the audit trail names who did what
    row = owner_query("SELECT status, tenant_id, business_name, requester_contact, resolution FROM data_requests WHERE id = :r", r=rid)[0]
    assert row[0] == "fulfilled" and row[1] is None and row[2] == b["name"] and row[3] is None and "deleted" in row[4]
    assert [e[0] for e in owner_query("SELECT action FROM data_request_events WHERE request_id = :r ORDER BY at", r=rid)] == ["requested", "verified", "deleted"]
    acts = {x[0] for x in owner_query("SELECT action FROM audit_logs WHERE tenant_id IS NULL AND entity_id = :r OR (tenant_id IS NULL AND action = 'account.deleted' AND metadata->>'slug' IS NOT NULL)", r=rid)}
    assert "admin.data_request_deletion_executed" in acts
    listed = admin.get("/admin/data-requests").json()["items"]
    assert any(x["id"] == rid and x["status"] == "fulfilled" and x["business_name"] == b["name"] for x in listed)
    assert admin.post(f"/admin/data-requests/{rid}/execute-deletion", json={"confirm_name": b["name"], "acknowledge": True}).status_code == 409  # cannot run twice


def test_other_businesses_are_untouched_by_a_deletion(admin):
    keep, gone = biz(admin), biz(admin)
    rid = deletion_ready(admin, gone)
    owner_exec("UPDATE data_requests SET eligible_at = now() - interval '1 minute' WHERE id = :r", r=rid)
    assert execute(admin, rid, gone["name"]).status_code == 200
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=keep["id"])[0][0] == 1
    assert owner_query("SELECT count(*) FROM locations WHERE tenant_id = :t", t=keep["id"])[0][0] == 1


def test_a_claim_after_the_request_stops_every_step_because_the_owner_has_the_real_tools(admin):
    b = biz(admin)
    rid = deletion_ready(admin, b)
    owner_exec("UPDATE data_requests SET eligible_at = now() - interval '1 minute' WHERE id = :r", r=rid)
    u = make_user("claimer@shop.example")
    from app.models import Membership, Role, User
    from sqlalchemy import select

    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        db.add(Membership(tenant_id=uuid.UUID(b["id"]), user_id=db.scalar(select(User.id).where(User.email == "claimer@shop.example")), role=Role.owner))
        db.commit()
    r = execute(admin, rid, b["name"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "has_owner"
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=b["id"])[0][0] == 1
    assert u


def test_a_paid_subscription_blocks_deletion_until_cancelled(admin):
    b = biz(admin)
    rid = deletion_ready(admin, b)
    owner_exec("UPDATE data_requests SET eligible_at = now() - interval '1 minute' WHERE id = :r", r=rid)
    owner_exec("UPDATE subscriptions SET razorpay_subscription_id = 'sub_test', status = 'active' WHERE tenant_id = :t", t=b["id"])
    r = execute(admin, rid, b["name"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cancel_subscription_first"
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=b["id"])[0][0] == 1


def test_data_request_tables_are_platform_only_and_the_history_is_append_only():
    app_role = settings.database_url.split("//")[1].split(":")[0]
    for t in ("data_requests", "data_request_events"):
        assert owner_query("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)", t=f"public.{t}")[0] == (True, True)
        assert owner_query("SELECT qual FROM pg_policies WHERE tablename = :t", t=t)[0][0].count("bypass_rls") == 1
        for priv in ("DELETE", "TRUNCATE"):
            assert owner_query("SELECT has_table_privilege(:r, :t, :p)", r=app_role, t=f"public.{t}", p=priv)[0][0] is False
    assert owner_query("SELECT has_table_privilege(:r, 'public.data_request_events', 'UPDATE')", r=app_role)[0][0] is False
    # a business's own session cannot see any request, not even its own
    own = make_business("Looks At Requests")
    with SessionLocal() as db:
        set_rls_context(db, tenant_id=uuid.UUID(own.tenant_id))
        from sqlalchemy import text
        assert db.execute(text("SELECT count(*) FROM data_requests")).scalar() == 0


def test_every_step_is_in_the_audit_log_with_who_and_when(admin):
    b = biz(admin)
    rid = ask(admin, b).json()["id"]
    verify(admin, rid)
    admin.get(f"/admin/data-requests/{rid}/export")
    admin.post(f"/admin/data-requests/{rid}/delivered", json={"delivery": "emailed_to_verified_address"})
    acts = [r[0] for r in owner_query("SELECT action FROM audit_logs WHERE tenant_id = :t AND action LIKE 'admin.data_request_%' ORDER BY created_at", t=b["id"])]
    assert acts == ["admin.data_request_created", "admin.data_request_verified", "admin.data_request_export_generated", "admin.data_request_fulfilled"]
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action LIKE 'admin.data_request_%' AND user_id IS NOT NULL", t=b["id"])[0][0] == 4


# ============================================================================================================================ 2. revoking a claim and the allowlist
def claim(admin, b, email="shopkeeper@shop.example"):
    r = admin.post(f"/admin/tenants/{b['id']}/claim", json={"email": email, "delivery": "link"})
    assert r.status_code == 201, r.text
    return r.json()


def on_list(email):
    return owner_query("SELECT count(*) FROM registration_allowlist WHERE email = :e", e=email)[0][0] == 1


def revoke(admin, b, inv, remove):
    return admin.post(f"/admin/tenants/{b['id']}/claim/{inv}/revoke", json={"remove_from_allowlist": remove})


def test_revoking_keeps_the_allowlist_entry_unless_removal_is_asked_for(admin, claims_on):
    b = biz(admin)
    c = claim(admin, b, "keep@shop.example")
    r = revoke(admin, b, c["invitation_id"], False)
    assert r.status_code == 200 and r.json()["allowlist"] == {"requested": False, "removed": False, "reason": None, "message": None}
    assert on_list("keep@shop.example")


def test_revoking_with_removal_deletes_only_the_entry_this_claim_created_and_keeps_the_history(admin, claims_on):
    b = biz(admin)
    c = claim(admin, b, "gone@shop.example")
    inv = admin.get(f"/admin/tenants/{b['id']}").json()["claim"]["invitations"][0]
    assert inv["allowlist"]["ok"] is True  # the page can show the box as available
    r = revoke(admin, b, c["invitation_id"], True)
    assert r.json()["allowlist"]["removed"] is True and r.json()["allowlist"]["requested"] is True
    assert not on_list("gone@shop.example")
    # history is preserved: the invitation row (revoked), and audit entries for the claim, the addition and the removal
    assert owner_query("SELECT revoked_at IS NOT NULL, allowlist_entry_id FROM invitations WHERE id = :i", i=c["invitation_id"])[0] == (True, None)  # the link to the deleted row is cleared, the row stays
    acts = {x[0] for x in owner_query("SELECT action FROM audit_logs WHERE tenant_id = :t", t=b["id"])}
    assert {"admin.claim_invitation_created", "admin.allowlist_added_for_claim", "admin.claim_invitation_revoked", "admin.allowlist_removed_after_claim_revoke"} <= acts
    # repeating is harmless and a later registration with that address is refused again in allowlist mode
    assert revoke(admin, b, c["invitation_id"], True).status_code == 200


def test_an_address_that_was_already_listed_is_never_removed(admin, claims_on):
    owner_exec("INSERT INTO registration_allowlist (id, email, note, created_at) VALUES (gen_random_uuid(), 'manual@shop.example', 'added by hand', now())")
    b = biz(admin)
    c = claim(admin, b, "manual@shop.example")
    r = revoke(admin, b, c["invitation_id"], True)
    assert r.json()["allowlist"]["removed"] is False and r.json()["allowlist"]["reason"] == "not_added_by_claim"
    assert on_list("manual@shop.example")
    assert "admin.allowlist_kept_after_claim_revoke" in {x[0] for x in owner_query("SELECT action FROM audit_logs WHERE tenant_id = :t", t=b["id"])}


def test_the_entry_stays_while_another_invitation_to_the_address_is_valid(admin, claims_on):
    b1, b2 = biz(admin), biz(admin)
    c1 = claim(admin, b1, "shared@shop.example")
    c2 = claim(admin, b2, "shared@shop.example")  # another business invites the same person
    r = revoke(admin, b1, c1["invitation_id"], True)
    assert r.json()["allowlist"]["removed"] is False and r.json()["allowlist"]["reason"] == "other_invitation"
    assert on_list("shared@shop.example")
    # once the other one is also revoked, removal is allowed again; the row was created by the FIRST claim, so it is that one that may remove it
    revoke(admin, b2, c2["invitation_id"], False)
    r = revoke(admin, b1, c1["invitation_id"], True)
    assert r.json()["allowlist"]["removed"] is True and not on_list("shared@shop.example")


def test_an_expired_other_invitation_does_not_keep_the_entry(admin, claims_on):
    b1, b2 = biz(admin), biz(admin)
    c1 = claim(admin, b1, "stale@shop.example")
    claim(admin, b2, "stale@shop.example")
    owner_exec("UPDATE invitations SET expires_at = now() - interval '1 hour' WHERE tenant_id = :t", t=b2["id"])
    assert revoke(admin, b1, c1["invitation_id"], True).json()["allowlist"]["removed"] is True


def test_the_entry_stays_when_an_account_already_exists_for_the_address(admin, claims_on):
    b = biz(admin)
    c = claim(admin, b, "existing@shop.example")
    make_user("existing@shop.example")  # signed up through the entry: it may be what lets them create a business
    r = revoke(admin, b, c["invitation_id"], True)
    assert r.json()["allowlist"]["removed"] is False and r.json()["allowlist"]["reason"] == "account_exists"
    assert on_list("existing@shop.example")


def test_an_address_permitted_by_server_configuration_is_not_touched(admin, claims_on, monkeypatch):
    b = biz(admin)
    c = claim(admin, b, "configured@shop.example")
    monkeypatch.setattr(settings, "registration_allowlist", "configured@shop.example")
    r = revoke(admin, b, c["invitation_id"], True)
    assert r.json()["allowlist"]["removed"] is False and r.json()["allowlist"]["reason"] == "permitted_elsewhere"


def test_an_accepted_invitation_cannot_be_revoked_or_have_its_address_removed(admin, claims_on):
    b = biz(admin)
    c = claim(admin, b, "accept@shop.example")
    u = make_user("accept@shop.example")
    assert u.post("/invitations/accept", json={"token": c["link"].split("token=")[1]}).status_code == 200
    r = revoke(admin, b, c["invitation_id"], True)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_accepted"
    assert on_list("accept@shop.example")


def test_revocation_in_another_business_is_not_possible(admin, claims_on):
    b1, b2 = biz(admin), biz(admin)
    c = claim(admin, b1, "cross@shop.example")
    assert revoke(admin, b2, c["invitation_id"], True).status_code == 404
    assert on_list("cross@shop.example")


# ============================================================================================================================ 4. aggregate managed usage and cost
def use_ai(tenant_id, kind, n=1, cost=None, tin=100, tout=50):
    """Record n successful generations (what the 200 + 200 allowance counts) and n matching per-call ledger rows (what the cost view reads)."""
    from decimal import Decimal

    from app.models import AICallLedger, AIGenerationLog

    tid = uuid.UUID(str(tenant_id))
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        for _ in range(n):
            db.add(AIGenerationLog(tenant_id=tid, kind=kind, provider="test", model="m1", language="en", input_chars=10, output_chars=10, prompt_tokens=tin, completion_tokens=tout,
                                   cost_usd=None if cost is None else Decimal(str(cost)), status="ok", created_at=utcnow()))
            db.add(AICallLedger(tenant_id=tid, kind=kind, provider="test", model="m1", input_tokens=tin, output_tokens=tout, cost_usd=None if cost is None else Decimal(str(cost)), status="ok", created_at=utcnow()))
        db.commit()


def row_of(data, tid):
    return next(r for r in data["businesses"] if r["id"] == tid)


def test_managed_usage_counts_only_admin_managed_businesses_and_real_usage(admin):
    a, b = biz(admin), biz(admin)
    own = make_business("Self Service Clinic")
    use_ai(a["id"], "review_assist", 3)
    use_ai(a["id"], "reply_draft", 2)
    use_ai(b["id"], "review_assist", 1)
    use_ai(own.tenant_id, "review_assist", 9)  # a business with its own account is not part of this view
    d = admin.get("/admin/managed-usage").json()
    ids = {r["id"] for r in d["businesses"]}
    assert a["id"] in ids and b["id"] in ids and own.tenant_id not in ids
    ra = row_of(d, a["id"])
    assert ra["review_writings"] == {"used": 3, "limit": 200} and ra["replies"] == {"used": 2, "limit": 200}
    t = d["totals"]
    assert t["businesses"] >= 2 and t["review_writings_used"] >= 4 and t["replies_used"] >= 2 and t["review_writings_allowed"] >= 400 and t["replies_allowed"] >= 400


def test_cost_is_the_recorded_cost_and_never_invented(admin, monkeypatch):
    monkeypatch.setattr(settings, "ai_price_in_per_mtok", 0.0)
    monkeypatch.setattr(settings, "ai_price_out_per_mtok", 0.0)
    a = biz(admin)
    use_ai(a["id"], "review_assist", 2, cost=0.0125)  # recorded cost per call
    use_ai(a["id"], "review_assist", 3, cost=None)  # no cost recorded and no price configured: it must not be guessed
    d = admin.get("/admin/managed-usage").json()
    r = row_of(d, a["id"])
    assert r["recorded_usd"] == pytest.approx(0.025) and r["repriced_usd"] == 0 and r["unpriced_calls"] == 3 and r["ai_calls"] == 5
    assert d["pricing"]["price_configured"] is False and d["pricing"]["input_per_million_tokens_usd"] is None
    assert d["totals"]["unpriced_calls"] >= 3 and d["totals"]["estimated_usd"] == pytest.approx(d["totals"]["recorded_usd"])


def test_unpriced_calls_are_priced_from_recorded_tokens_only_when_prices_are_configured(admin, monkeypatch):
    monkeypatch.setattr(settings, "ai_price_in_per_mtok", 2.0)
    monkeypatch.setattr(settings, "ai_price_out_per_mtok", 8.0)
    a = biz(admin)
    use_ai(a["id"], "review_assist", 2, cost=None, tin=1000, tout=500)  # (1000*2 + 500*8)/1e6 = 0.006 per call
    d = admin.get("/admin/managed-usage").json()
    r = row_of(d, a["id"])
    assert r["repriced_usd"] == pytest.approx(0.012) and r["recorded_usd"] == 0 and r["unpriced_calls"] == 0
    assert d["pricing"] == {**d["pricing"], "price_configured": True, "input_per_million_tokens_usd": 2.0, "output_per_million_tokens_usd": 8.0}
    assert d["totals"]["estimated_usd"] >= 0.012


def test_a_call_with_no_tokens_and_no_cost_stays_unpriced_even_when_prices_are_configured(admin, monkeypatch):
    monkeypatch.setattr(settings, "ai_price_in_per_mtok", 2.0)
    monkeypatch.setattr(settings, "ai_price_out_per_mtok", 8.0)
    a = biz(admin)
    from app.models import AICallLedger

    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        db.add(AICallLedger(tenant_id=uuid.UUID(a["id"]), kind="review_assist", provider="test", model="m1", input_tokens=None, output_tokens=None, cost_usd=None, status="ok", created_at=utcnow()))
        db.commit()
    r = row_of(admin.get("/admin/managed-usage").json(), a["id"])
    assert r["unpriced_calls"] == 1 and r["repriced_usd"] == 0


def test_usage_view_reflects_revoked_access_suspension_and_near_limit(admin):
    a, b = biz(admin), biz(admin)
    use_ai(a["id"], "review_assist", 170)  # 85% of 200
    admin.post(f"/admin/tenants/{b['id']}/managed-access", json={"action": "revoke", "note": "client stopped using it"})
    d = admin.get("/admin/managed-usage").json()
    assert row_of(d, a["id"])["percent_of_allowance"] == 85 and d["totals"]["near_limit"] >= 1
    rb = row_of(d, b["id"])
    assert rb["access_revoked"] is True and d["totals"]["access_revoked"] >= 1


def test_usage_view_is_read_only(admin):
    before = owner_query("SELECT (SELECT count(*) FROM ai_generation_logs), (SELECT count(*) FROM ai_call_ledger), (SELECT count(*) FROM audit_logs)")[0]
    admin.get("/admin/managed-usage")
    assert owner_query("SELECT (SELECT count(*) FROM ai_generation_logs), (SELECT count(*) FROM ai_call_ledger), (SELECT count(*) FROM audit_logs)")[0] == before
