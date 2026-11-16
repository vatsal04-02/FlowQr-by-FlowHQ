"""POST /billing/subscription/checkout answered 403 in the local Sandbox and the page showed nothing. The exact reasons a 403 can come from this route, each proved here and each told apart by its body:

  * the owner's email address is not verified  -> {"code": "email_not_verified", "message": "Please verify your email address first."}   (the one seen in the Sandbox)
  * no CSRF header on a state-changing call    -> "Invalid CSRF token"
  * a signed-in member who is not the owner    -> "You do not have permission to do this"
  * no session                                 -> 401

Nothing is weakened: an unverified owner is still refused and Cashfree is never called for them. Real application and PostgreSQL; Cashfree is the TEST DOUBLE of the other Cashfree tests."""
from app.core.config import settings
from tests.conftest import latest_token, make_user, owner_query
from tests.test_cashfree_billing import start
from tests.test_cashfree_mandate_gate import info, mandate  # noqa: F401  (fixture)

EXACT = {"code": "email_not_verified", "message": "Please verify your email address first."}


def unverified_owner(**kw):
    """What the Sandbox owner was: registered (registration is open there), business and location created, email NOT verified."""
    s = make_user(verify=False)
    r = s.post("/tenants", json={"name": "Unverified Cafe", "category": "cafe", "language": "en"})
    assert r.status_code == 201, r.text
    s.tenant_id = r.json()["id"]
    assert s.post("/locations", json={"name": "Main", "city": "Lucknow", "review_url": "https://g.page/r/ABC123/review"}).status_code == 201
    return s


def test_an_unverified_owner_gets_403_email_not_verified_and_cashfree_is_never_called(mandate, monkeypatch):
    monkeypatch.setattr(settings, "require_verified_email", True)
    s = unverified_owner()
    r = start(s, "growth")
    assert r.status_code == 403 and r.json()["detail"] == EXACT
    assert not [c for c in mandate.calls if c[0] in ("ensure_plan", "create")]  # no plan, no subscription at Cashfree
    row = owner_query("SELECT cashfree_subscription_id, authorization_status, status FROM subscriptions WHERE tenant_id = :t", t=s.tenant_id)[0]
    assert row[0] is None and row[1] is None and row[2] == "incomplete"  # nothing was created or started


def test_the_read_only_preview_still_works_for_an_unverified_owner_so_the_page_loads_before_the_refusal(mandate, monkeypatch):
    monkeypatch.setattr(settings, "require_verified_email", True)
    s = unverified_owner()
    assert s.get("/billing/subscription/preview?plan=growth").status_code == 200
    assert start(s, "growth").status_code == 403


def test_after_verifying_the_same_owner_can_create_a_subscription_and_gets_the_hosted_checkout_session(mandate, monkeypatch):
    monkeypatch.setattr(settings, "require_verified_email", True)
    s = unverified_owner()
    assert start(s, "growth").status_code == 403
    assert s.http.post("/api/v1/auth/verify-email", json={"token": latest_token(s.email, "verify-email")}).status_code == 204
    r = start(s, "growth")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subscription_session_id"] and body["environment"] == "sandbox" and body["plan"] == "growth"
    assert [c for c in mandate.calls if c[0] == "create"]
    assert info(s)["authorization_status"] == "initialized" and info(s)["status"] == "incomplete"  # trial still waits for the verified authorisation


def test_the_resend_route_the_page_offers_exists_for_an_unverified_owner(mandate, monkeypatch):
    s = unverified_owner()
    r = s.post("/auth/resend-verification")
    assert r.status_code in (200, 202) and r.json()["email_sent"] is True


def test_a_missing_csrf_header_is_a_different_403_with_its_own_message(mandate):
    s = unverified_owner()
    r = s.http.post("/api/v1/billing/subscription/checkout", json={"plan": "growth", "phone": "9876543210"})  # same session cookie, no X-CSRF-Token
    assert r.status_code == 403 and r.json()["detail"] == "Invalid CSRF token"


def test_no_session_is_401_not_403(mandate):
    from fastapi.testclient import TestClient
    from app.main import app
    r = TestClient(app).post("/api/v1/billing/subscription/checkout", json={"plan": "growth", "phone": "9876543210"})
    assert r.status_code in (401, 403) and r.json()["detail"] != EXACT
