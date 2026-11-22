"""Production-readiness hardening: the FlowHQ operator path under hostile and ordinary conditions, reply-draft input, and dashboard numbers against controlled database records.

Operator tests use a throwaway operator address in the test configuration only (no production identity is touched; `vatsal@flowhq.co.in` has not registered in production and none of this
creates or implies it). Mock Google only."""
import uuid
from dataclasses import replace

import pytest

from app.core.config import settings
from app.services.google import agency
from tests.conftest import make_business, make_user, owner_exec, owner_query
from tests.test_google_agency import seed  # noqa: F401
from tests.test_google_agency import _clean  # noqa: F401  (autouse)
from tests.test_google_agency_group import gfake  # noqa: F401
from tests.test_google_and_reviews import connected, fake, greview, sync_select  # noqa: F401

OPERATOR = "operator@flowhq.example"


@pytest.fixture()
def internal(monkeypatch):
    monkeypatch.setattr(settings, "google_agency_manager_enabled", True)
    monkeypatch.setattr(settings, "google_agency_internal_only", True)
    monkeypatch.setattr(settings, "google_agency_operator_emails", OPERATOR)
    monkeypatch.setattr(settings, "require_verified_email", True)


def operator_session(verify=True):
    email = f"op-{uuid.uuid4().hex[:6]}@flowhq.example"
    return email, make_user(email, "Op", verify=verify)


def test_an_operator_whose_address_is_unverified_is_refused_everywhere(monkeypatch, internal):
    email, op = operator_session(verify=False)
    monkeypatch.setattr(settings, "google_agency_operator_emails", email)
    for method, path in (("get", "/agency-ops/tenants"), ("get", "/agency-ops/readiness")):
        assert getattr(op, method)(path).status_code == 404  # exactly what an unknown path says
    victim = make_business("Unverified Op Victim")
    assert op.post(f"/agency-ops/tenants/{victim.tenant_id}/grant", json={}).status_code == 404
    assert not agency.tenant_allowed(victim.tenant_id)
    # once the person has proved the mailbox, the same session works
    from tests.conftest import latest_token

    assert op.http.post("/api/v1/auth/verify-email", json={"token": latest_token(email, "verify-email")}).status_code == 204
    assert op.get("/agency-ops/tenants").status_code == 200


def test_an_operator_who_signed_out_or_was_deactivated_is_refused(monkeypatch, internal):
    email, op = operator_session()
    monkeypatch.setattr(settings, "google_agency_operator_emails", email)
    assert op.get("/agency-ops/tenants").status_code == 200
    stale = {c.name: c.value for c in op.http.cookies.jar}
    assert op.post("/auth/logout").status_code == 204
    reuse = type(op.http)(op.http.app, base_url="http://testserver")
    for k, v in stale.items():
        reuse.cookies.set(k, v)
    assert reuse.get("/api/v1/agency-ops/tenants").status_code == 401  # the ended session cannot be replayed
    email2, op2 = operator_session()
    monkeypatch.setattr(settings, "google_agency_operator_emails", f"{email},{email2}")
    assert op2.get("/agency-ops/tenants").status_code == 200
    owner_exec("UPDATE users SET is_active = false WHERE email = :e", e=email2)
    assert op2.get("/agency-ops/tenants").status_code == 401  # a deactivated person loses access at once


def test_the_operator_endpoints_enforce_csrf_and_validate_their_input(monkeypatch, internal):
    email, op = operator_session()
    monkeypatch.setattr(settings, "google_agency_operator_emails", email)
    client = make_business("Csrf Target")
    no_csrf = op.http.post(f"/api/v1/agency-ops/tenants/{client.tenant_id}/grant", json={})  # cookie session, no X-CSRF-Token header
    assert no_csrf.status_code == 403 and not agency.tenant_allowed(client.tenant_id)
    assert op.post(f"/agency-ops/tenants/{uuid.uuid4()}/grant", json={}).status_code == 404  # unknown business: nothing written
    assert op.post("/agency-ops/tenants/not-a-uuid/grant", json={}).status_code == 422
    assert op.post(f"/agency-ops/tenants/{client.tenant_id}/grant", json={"note": "x" * 301}).status_code == 422
    assert op.post(f"/agency-ops/tenants/{client.tenant_id}/grant", json={"unexpected": "field"}).status_code == 422  # extra fields are refused
    assert owner_query("SELECT count(*) FROM google_agency_tenant_grants WHERE tenant_id = :t", t=client.tenant_id)[0][0] == 0


def test_every_grant_and_revoke_is_audited_with_who_did_it(monkeypatch, internal):
    email, op = operator_session()
    monkeypatch.setattr(settings, "google_agency_operator_emails", email)
    client = make_business("Audited Target")
    assert op.post(f"/agency-ops/tenants/{client.tenant_id}/grant", json={"note": "rollout"}).status_code == 201
    assert op.post(f"/agency-ops/tenants/{client.tenant_id}/revoke").status_code == 200
    rows = owner_query("SELECT action, user_id, metadata->>'operator' FROM audit_logs WHERE tenant_id = :t AND action LIKE '%agency%' ORDER BY created_at", t=client.tenant_id)
    actions = [r[0] for r in rows]
    assert {"agency_ops.grant", "google.agency.tenant_granted", "agency_ops.revoke", "google.agency.tenant_revoked"} <= set(actions), actions
    op_id = owner_query("SELECT id FROM users WHERE email = :e", e=email)[0][0]
    assert all(r[1] == op_id for r in rows if r[0].startswith("agency_ops."))  # the signed-in operator is on the record
    assert all(r[2] == email for r in rows if r[0].startswith("google.agency.tenant_"))


def test_taking_someone_off_the_operator_list_removes_access_without_a_restart(monkeypatch, internal):
    email, op = operator_session()
    monkeypatch.setattr(settings, "google_agency_operator_emails", email)
    assert op.get("/agency-ops/tenants").status_code == 200
    monkeypatch.setattr(settings, "google_agency_operator_emails", "someone.else@flowhq.example")
    assert op.get("/agency-ops/tenants").status_code == 404


def test_being_an_operator_gives_no_access_to_a_customers_business_data(monkeypatch, internal, gfake):
    email = f"op-{uuid.uuid4().hex[:6]}@flowhq.example"
    op = make_business("Operator Own Space", email=email)
    monkeypatch.setattr(settings, "google_agency_operator_emails", email)
    client = make_business("Customer Space")
    s = seed(client)
    for path in ("/reviews", "/locations", "/analytics/overview", "/google/status", "/cards", "/review-growth/campaigns"):
        r = op.get(path, headers={"X-Tenant-Id": client.tenant_id})
        assert r.status_code == 403, (path, r.status_code)  # the operator is not a member of the customer's business
    # nor can the operator speak for the customer: consent is the business's own administrator's act
    agency.grant_tenant(op.tenant_id, operator_email=email)  # even with the path open for the operator's OWN space ...
    r = op.post("/google/agency/consent", json={"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION})
    assert r.status_code == 404  # ... the customer's connection is not found from there
    assert owner_query("SELECT count(*) FROM google_agency_authorizations WHERE connection_id = :c", c=str(s.conn_id))[0][0] == 0


# ------------------------------------------------------------------------------------------------------------- reply drafts
def test_a_blank_reply_cannot_be_saved_as_a_draft(connected, fake):
    fake.reviews = [greview(1)]
    sync_select(connected, fake)
    review = connected.get("/reviews").json()["items"][0]["id"]
    for blank in ("  ", "\n\n", " \t "):
        r = connected.post(f"/reviews/{review}/drafts", json={"body": blank})
        assert r.status_code == 422, (repr(blank), r.status_code, r.text)
    good = connected.post(f"/reviews/{review}/drafts", json={"body": "  Thank you for coming in.  "})
    assert good.status_code == 201 and good.json()["body"] == "Thank you for coming in."
    assert connected.patch(f"/reply-drafts/{good.json()['id']}", json={"body": "   "}).status_code == 422  # editing to nothing is refused too
    assert owner_query("SELECT count(*) FROM reply_drafts WHERE review_id = :r AND btrim(body) = ''", r=review)[0][0] == 0


# ------------------------------------------------------------------------------------------------------------- dashboard numbers vs the database
def test_dashboard_numbers_match_the_database_at_the_india_midnight_boundary(connected, fake):
    # 23:59:59 and 00:00:00 India time on either side of 11 March, plus an older review: the tenant's day, not UTC's, decides which date a review belongs to.
    fake.reviews = [replace(greview(1, rating=5), created_at="2025-03-10T18:29:59Z", updated_at="2025-03-10T18:29:59Z"),
                    replace(greview(2, rating=2, text="Long wait"), created_at="2025-03-10T18:30:00Z", updated_at="2025-03-10T18:30:00Z"),
                    replace(greview(3, rating=4, reply="Thanks"), created_at="2025-03-01T08:00:00Z", updated_at="2025-03-01T08:00:00Z")]
    sync_select(connected, fake)
    day10 = connected.get("/analytics/overview", params={"from": "2025-03-10", "to": "2025-03-10"}).json()["reviews"]
    day11 = connected.get("/analytics/overview", params={"from": "2025-03-11", "to": "2025-03-11"}).json()["reviews"]
    assert (day10["new_in_range"], day10["average_rating_in_range"]) == (1, 5.0)  # 23:59:59 IST on the 10th
    assert (day11["new_in_range"], day11["average_rating_in_range"]) == (1, 2.0)  # 00:00:00 IST on the 11th
    span = connected.get("/analytics/overview", params={"from": "2025-03-01", "to": "2025-03-11"}).json()["reviews"]
    db = owner_query("SELECT count(*), round(avg(rating)::numeric, 2), count(*) FILTER (WHERE google_reply_text IS NOT NULL) FROM reviews WHERE tenant_id = :t", t=connected.tenant_id)[0]
    assert span["total_synced"] == db[0] == 3 and span["average_rating_all_time"] == float(db[1]) == 3.67
    assert span["new_in_range"] == 3 and span["rating_distribution"] == {"1": 0, "2": 1, "3": 0, "4": 1, "5": 1}
    assert sum(p["count"] for p in span["series"]) == 3 and {p["date"]: p["count"] for p in span["series"]}["2025-03-10"] == 1 and {p["date"]: p["count"] for p in span["series"]}["2025-03-11"] == 1
    assert span["awaiting_reply"] == 2 and span["reply_rate_in_range"] == round(1 / 3, 3)
    empty = connected.get("/analytics/overview", params={"from": "2024-01-01", "to": "2024-01-03"}).json()["reviews"]
    assert empty["new_in_range"] == 0 and empty["average_rating_in_range"] is None and empty["reply_rate_in_range"] is None  # no data is None, never 0 stars


def test_another_business_sees_none_of_those_numbers(connected, fake):
    fake.reviews = [greview(1)]
    sync_select(connected, fake)
    stranger = make_business("Stranger Co")
    o = stranger.get("/analytics/overview", params={"from": "2025-01-01", "to": "2025-01-31"}).json()
    assert o["reviews"]["total_synced"] == 0 and o["reviews"]["average_rating_all_time"] is None and o["sync"] == []
    assert stranger.get("/reviews").json()["total"] == 0
