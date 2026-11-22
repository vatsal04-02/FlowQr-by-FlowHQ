"""Production-readiness hardening, finding F-05: the Locations screen asked every customer's browser for /google/agency/status, which answers 404 by design for a business the agency path is not open
for. The failed request was logged as an error in every customer's console on every visit. /google/status now says whether the path is open (`agency_available`) so the screen asks only when it
is. The 404 contract of the agency routes is unchanged and re-asserted here. Mock only."""
import pytest

from app.core.config import settings
from app.services.google import agency
from tests.conftest import make_business

OPERATOR = "operator@flowhq.example"


@pytest.fixture(autouse=True)
def _agency_defaults(monkeypatch):
    monkeypatch.setattr(settings, "google_agency_manager_enabled", False)
    monkeypatch.setattr(settings, "google_agency_internal_only", False)
    monkeypatch.setattr(settings, "google_agency_operator_emails", OPERATOR)


def available(biz) -> bool:
    r = biz.get("/google/status")
    assert r.status_code == 200, r.text
    return r.json()["agency_available"]


def test_agency_is_not_offered_while_the_manager_switch_is_off(monkeypatch):
    biz = make_business("No Agency Clinic")
    assert available(biz) is False
    assert biz.get("/google/agency/status").status_code == 404  # unchanged: an unknown path


def test_agency_is_offered_to_everyone_when_it_is_on_and_not_internal_only(monkeypatch):
    monkeypatch.setattr(settings, "google_agency_manager_enabled", True)
    biz = make_business("Open Agency Clinic")
    assert available(biz) is True
    assert biz.get("/google/agency/status").status_code == 200


def test_internal_only_offers_it_just_to_a_business_an_operator_opened_it_for(monkeypatch):
    monkeypatch.setattr(settings, "google_agency_manager_enabled", True)
    monkeypatch.setattr(settings, "google_agency_internal_only", True)
    granted, other = make_business("Granted Clinic"), make_business("Not Granted Clinic")
    assert available(granted) is False and available(other) is False
    assert other.get("/google/agency/status").status_code == 404 and granted.get("/google/agency/status").status_code == 404

    agency.grant_tenant(granted.tenant_id, operator_email=OPERATOR)
    assert available(granted) is True and granted.get("/google/agency/status").status_code == 200
    assert available(other) is False and other.get("/google/agency/status").status_code == 404  # a grant for one business gives another nothing

    agency.revoke_tenant_grant(granted.tenant_id, operator_email=OPERATOR)
    assert available(granted) is False and granted.get("/google/agency/status").status_code == 404


def test_the_hint_reveals_nothing_beyond_a_yes_or_no():
    biz = make_business("Plain Clinic")
    body = biz.get("/google/status").json()
    assert set(body) == {"configured", "configuration_note", "connections", "agency_available"}  # no operator address, no grant detail, no count
