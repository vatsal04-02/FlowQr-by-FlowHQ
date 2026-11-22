"""Internal-only agency operations: FlowHQ's own operators only, enforced in the backend (services and routes), not by a hidden screen. Mock Google only."""
from contextlib import closing
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings, config_problems, settings
from app.core.db import system_session
from app.models import GoogleConnection, GoogleLocation
from app.services.google import agency
from tests.conftest import make_business
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


def test_a_business_that_is_not_an_operator_is_told_exactly_what_an_unknown_path_says(gfake, internal):
    biz = make_business("Customer Clinic")  # its e-mail is not on the operator list
    s = seed(biz)
    assert biz.get("/google/agency/status").status_code == 404
    assert consent_post(biz, s).status_code == 404
    assert biz.post(f"/google/agency/connections/{s.conn_id}/advance").status_code == 404
    assert auths_of(s) == [] and calls(gfake, "invite_group") == []  # nothing was recorded or sent
    with closing(system_session()) as db:
        with pytest.raises(agency.NotAnOperator):  # and the service itself refuses, whatever route (or job) calls it
            agency.record_consent(db, conn=db.get(GoogleConnection, s.conn_id), user=SimpleNamespace(id=None, email=biz.email), agree=True, version=agency.CONSENT_VERSION)


def test_a_listed_operator_can_start_it_and_it_resolves(gfake, internal):
    biz = make_business("Operator Clinic", email=OPERATOR)
    s = seed(biz)
    assert consent_post(biz, s).status_code == 200
    (a,) = auths_of(s)
    assert a.status == "active" and a.consented_by_email == OPERATOR
    with closing(system_session()) as db:
        assert agency.resolve_agency_access(db, db.get(GoogleConnection, s.conn_id), db.get(GoogleLocation, s.gids[0])).location_resource == f"locations/{s.key[0]}"


def test_an_authorization_not_recorded_by_an_operator_is_refused_at_use_even_if_one_exists(gfake, monkeypatch):
    biz = make_business("Earlier Clinic")
    s = seed(biz)
    assert go(biz, s) == [("active", None)]  # recorded before internal-only was switched on, by an ordinary business admin
    monkeypatch.setattr(settings, "google_agency_internal_only", True)
    monkeypatch.setattr(settings, "google_agency_operator_emails", OPERATOR)
    with closing(system_session()) as db:
        with pytest.raises(agency.AgencyResolutionError) as e:
            agency.resolve_agency_access(db, db.get(GoogleConnection, s.conn_id), db.get(GoogleLocation, s.gids[0]))
    assert e.value.code == "not_internal_operator"


def test_no_credential_appears_in_any_customer_response(gfake, internal):
    biz = make_business("Leak Check Clinic", email=OPERATOR2)
    s = seed(biz)
    body = consent_post(biz, s).text + biz.get("/google/agency/status").text + biz.get("/google/status").text
    for needle in ("refresh_token", "access_token", "gAAAA", "agency_token", "AGENCY_TOKEN"):
        assert needle not in body


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
    assert any("GOOGLE_AGENCY_INTERNAL_ONLY" in p for p in config_problems(prod()))  # nothing recorded: refused
    assert any("GOOGLE_AGENCY_INTERNAL_ONLY needs" in p for p in config_problems(prod(google_agency_internal_only=True, google_agency_internal_decision="d")))  # nobody listed
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
