"""Internal-only agency operations: a FlowHQ OPERATOR opens the path for a business (a platform-level grant), the business's OWN administrator gives the consent. Both are enforced in the backend.
Mock Google only."""
from contextlib import closing
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings, config_problems, settings
from app.core.db import system_session
from app.models import GoogleConnection, GoogleLocation
from app.services.google import agency
from tests.conftest import make_business, owner_query
from tests.test_google_agency import _clean, auths_of, calls, go, seed  # noqa: F401  (_clean is an autouse fixture)
from tests.test_google_agency_group import gfake  # noqa: F401  (gfake is a fixture)

OPERATOR = "operator@flowhq.example"
OPERATOR2 = "operator2@flowhq.example"


@pytest.fixture()
def internal(monkeypatch):
    monkeypatch.setattr(settings, "google_agency_internal_only", True)
    monkeypatch.setattr(settings, "google_agency_operator_emails", OPERATOR + "," + OPERATOR2)


def consent_post(biz, s):
    return biz.post("/google/agency/consent", json={"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION})


def resolve(s):
    with closing(system_session()) as db:
        return agency.resolve_agency_access(db, db.get(GoogleConnection, s.conn_id), db.get(GoogleLocation, s.gids[0]))


# ------------------------------------------------------------------ a business that no operator has opened the path for
def test_a_business_without_an_operator_grant_is_told_exactly_what_an_unknown_path_says(gfake, internal):
    biz = make_business("Customer Clinic")
    s = seed(biz)
    assert biz.get("/google/agency/status").status_code == 404
    assert consent_post(biz, s).status_code == 404
    assert biz.post(f"/google/agency/connections/{s.conn_id}/advance").status_code == 404
    assert auths_of(s) == [] and calls(gfake, "invite_group") == []  # nothing was recorded or sent
    with closing(system_session()) as db:
        with pytest.raises(agency.TenantNotGranted):  # the service refuses too, whatever route (or job) calls it
            agency.record_consent(db, conn=db.get(GoogleConnection, s.conn_id), user=SimpleNamespace(id=None, email=biz.email), agree=True, version=agency.CONSENT_VERSION)


def test_only_a_listed_operator_can_open_or_close_the_path(gfake, internal):
    biz = make_business("Grant Rules Clinic")
    for who in ("customer@clinic.example", "", None):
        with pytest.raises(agency.NotAnOperator):
            agency.grant_tenant(biz.tenant_id, operator_email=who)
        with pytest.raises(agency.NotAnOperator):
            agency.revoke_tenant_grant(biz.tenant_id, operator_email=who)
    assert not agency.tenant_allowed(biz.tenant_id)


# ------------------------------------------------------------------ operator opens it, the client consents, the operator can close it
def test_the_operator_opens_the_path_and_the_clients_own_admin_gives_the_consent(gfake, internal):
    biz = make_business("Granted Clinic")  # the client; its administrator is NOT an operator
    s = seed(biz)
    row = agency.grant_tenant(biz.tenant_id, operator_email=OPERATOR.upper(), note="internal rollout")
    assert row.granted_by_email == OPERATOR and agency.tenant_allowed(biz.tenant_id)
    assert biz.get("/google/agency/status").status_code == 200
    assert consent_post(biz, s).status_code == 200
    (a,) = auths_of(s)
    assert a.status == "active" and a.consented_by_email == biz.email and a.consented_by_email != OPERATOR  # the consent is the client's, the grant is the operator's
    assert resolve(s).location_resource == f"locations/{s.key[0]}"
    audit = owner_query("SELECT metadata->>'operator' FROM audit_logs WHERE action = 'google.agency.tenant_granted' AND tenant_id = :t", t=biz.tenant_id)
    assert audit and audit[-1][0] == OPERATOR


def test_closing_the_path_stops_every_use_and_reopening_resumes_it_without_a_new_consent(gfake, internal):
    biz = make_business("Revoke Clinic")
    s = seed(biz)
    agency.grant_tenant(biz.tenant_id, operator_email=OPERATOR)
    assert consent_post(biz, s).status_code == 200
    n = len(gfake.calls)
    assert agency.revoke_tenant_grant(biz.tenant_id, operator_email=OPERATOR2) is True
    assert agency.revoke_tenant_grant(biz.tenant_id, operator_email=OPERATOR2) is False  # nothing left to close
    with closing(system_session()) as db:
        with pytest.raises(agency.AgencyResolutionError) as e:
            agency.resolve_agency_access(db, db.get(GoogleConnection, s.conn_id), db.get(GoogleLocation, s.gids[0]))
    assert e.value.code == "tenant_not_granted" and len(gfake.calls) == n  # nothing reached Google
    assert biz.get("/google/agency/status").status_code == 404
    assert [x.status for x in auths_of(s)] == ["active"]  # the client's own authorization is untouched
    agency.grant_tenant(biz.tenant_id, operator_email=OPERATOR)
    assert resolve(s).location_resource == f"locations/{s.key[0]}"
    rows = owner_query("SELECT revoked_by_email IS NOT NULL FROM google_agency_tenant_grants WHERE tenant_id = :t ORDER BY granted_at", t=biz.tenant_id)
    assert [r[0] for r in rows] == [True, False]  # the closed grant is kept as history, the new one is open


def test_a_grant_for_one_business_gives_another_nothing(gfake, internal):
    (a_biz, b_biz) = make_business("Granted One"), make_business("Not Granted Two")
    a, b = seed(a_biz), seed(b_biz)
    agency.grant_tenant(a_biz.tenant_id, operator_email=OPERATOR)
    assert consent_post(a_biz, a).status_code == 200
    assert consent_post(b_biz, b).status_code == 404 and auths_of(b) == []
    assert not agency.tenant_allowed(b_biz.tenant_id)


# ------------------------------------------------------------------ the operator's own interface (platform level, no business role)
def test_the_operator_endpoints_work_for_a_listed_operator_without_any_membership_in_the_client(gfake, internal):
    operator = make_business("Operator Own Space", email=OPERATOR)  # the operator has a login (and an unrelated space of their own), and NO membership in the client
    client = make_business("Client Of Operator")
    seed(client)
    assert operator.get("/agency-ops/tenants").status_code == 200
    rows = {r["tenant_id"]: r for r in operator.get("/agency-ops/tenants").json()["tenants"]}
    assert client.tenant_id in rows and rows[client.tenant_id]["agency_path_open"] is False
    r = operator.post(f"/agency-ops/tenants/{client.tenant_id}/grant", json={"note": "internal"})
    assert r.status_code == 201 and r.json()["granted_by"] == OPERATOR
    assert client.get("/google/agency/status").status_code == 200
    assert {r["tenant_id"]: r for r in operator.get("/agency-ops/tenants").json()["tenants"]}[client.tenant_id]["agency_path_open"] is True
    assert operator.get("/agency-ops/readiness").status_code == 200 and "lines" in operator.get("/agency-ops/readiness").json()
    assert operator.post(f"/agency-ops/tenants/{client.tenant_id}/revoke").json()["agency_path_open"] is False
    assert client.get("/google/agency/status").status_code == 404
    assert operator.get(f"/google/agency/status").status_code == 404  # being an operator gives no right inside any business: the operator is not in the client's business, and has no grant of its own
    assert operator.post(f"/agency-ops/tenants/{operator.tenant_id}/grant", json={}).status_code == 201  # (an operator may open the path for a business, including their own space; that is still a grant, not a consent)


def test_everyone_else_gets_404_from_every_operator_endpoint(gfake, internal):
    other = make_business("Not An Operator")
    victim = make_business("Victim Clinic")
    for method, path in (("get", "/agency-ops/tenants"), ("get", "/agency-ops/readiness"), ("post", f"/agency-ops/tenants/{victim.tenant_id}/grant"), ("post", f"/agency-ops/tenants/{victim.tenant_id}/revoke")):
        r = getattr(other, method)(path, **({"json": {}} if method == "post" and path.endswith("grant") else {}))
        assert r.status_code == 404, (path, r.status_code)
    assert not agency.tenant_allowed(victim.tenant_id)


def test_no_credential_appears_in_any_customer_or_operator_response(gfake, internal):
    operator = make_business("Leak Check Operator", email=OPERATOR2)
    client = make_business("Leak Check Client")
    s = seed(client)
    operator.post(f"/agency-ops/tenants/{client.tenant_id}/grant", json={})
    body = consent_post(client, s).text + client.get("/google/agency/status").text + client.get("/google/status").text + operator.get("/agency-ops/tenants").text + operator.get("/agency-ops/readiness").text
    for needle in ("refresh_token", "access_token", "gAAAA", "agency_token_encrypted", "ya29."):  # (names of settings may appear in the operator checklist; values and tokens never)
        assert needle not in body


# ------------------------------------------------------------------ configuration
def prod(**over):
    base = dict(app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True, public_card_base_url="https://go.flowqr.co.in",
                frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in", database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr",
                platform_admin_emails="ops@flowhq.in", smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
                card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback", google_client_id="id", google_client_secret="secret",
                google_agency_manager_enabled=True, agency_token_encryption_key=Fernet.generate_key().decode(), google_agency_location_group_id="accounts/114863040359228435467",
                google_agency_operations_enabled=True, google_agency_project_model="flowhq_own_project")
    base.update(over)
    return Settings(_env_file=None, **base)


def test_the_guard_needs_operators_and_a_recorded_decision_and_a_recorded_google_answer_still_works_alone():
    assert any("GOOGLE_AGENCY_INTERNAL_ONLY" in p for p in config_problems(prod()))
    assert any("GOOGLE_AGENCY_INTERNAL_ONLY needs" in p for p in config_problems(prod(google_agency_internal_only=True, google_agency_internal_decision="d")))
    assert config_problems(prod(google_agency_internal_only=True, google_agency_operator_emails="a@flowhq.example", google_agency_internal_decision="owner decision 2026-11-22")) == []
    assert config_problems(prod(google_agency_policy_reference="written-answer-on-file")) == []


def test_the_internal_basis_enables_operations_in_production_only_with_every_part(gfake, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "google_agency_project_model", "flowhq_own_project")
    monkeypatch.setattr(settings, "google_agency_policy_reference", "")
    assert agency.operations_enabled() is False
    monkeypatch.setattr(settings, "google_agency_internal_only", True)
    monkeypatch.setattr(settings, "google_agency_operator_emails", OPERATOR)
    assert agency.operations_enabled() is False  # no recorded decision yet
    monkeypatch.setattr(settings, "google_agency_internal_decision", "owner decision")
    assert agency.operations_enabled() is True
    monkeypatch.setattr(settings, "google_agency_internal_only", False)
    assert agency.operations_enabled() is False  # the basis is internal-only: without the rule enforced it does not count
