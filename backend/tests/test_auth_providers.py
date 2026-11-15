"""Which sign-in methods the server really offers (GET /auth/providers), email-and-password independence from Google, and the production cookie attributes of the split-host setup
(site on www.flowqr.site, API on api.flowqr.site). Real application and PostgreSQL; nothing talks to Google or sends mail."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from tests.conftest import make_user

PW = "Str0ngPassw0rd!"
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def anon():
    return TestClient(app, base_url="http://testserver")


# ------------------------------------------------------------------------------------------------------------------------------ providers
def test_google_is_reported_unavailable_when_the_sign_in_client_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "google_login_client_id", "")
    monkeypatch.setattr(settings, "google_login_client_secret", "")
    r = anon().get("/api/v1/auth/providers")
    assert r.status_code == 200 and r.json() == {"google": False}


@pytest.mark.parametrize("cid,secret", [("only-id.apps.googleusercontent.com", ""), ("", "only-secret")])
def test_half_configured_google_is_still_unavailable(monkeypatch, cid, secret):
    monkeypatch.setattr(settings, "google_login_client_id", cid)
    monkeypatch.setattr(settings, "google_login_client_secret", secret)
    assert anon().get("/api/v1/auth/providers").json() == {"google": False}


def test_google_is_reported_available_only_when_both_halves_exist_and_nothing_else_is_disclosed(monkeypatch):
    monkeypatch.setattr(settings, "google_login_client_id", "1234-abc.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_login_client_secret", "GOCSPX-super-secret-value")
    r = anon().get("/api/v1/auth/providers")
    assert r.json() == {"google": True}
    assert "1234-abc" not in r.text and "GOCSPX" not in r.text  # a boolean, never the client id or the secret


def test_the_business_profile_client_does_not_make_sign_in_available(monkeypatch):
    # two separate OAuth clients: configuring the Business Profile one must not light up "Continue with Google"
    monkeypatch.setattr(settings, "google_login_client_id", "")
    monkeypatch.setattr(settings, "google_login_client_secret", "")
    monkeypatch.setattr(settings, "google_client_id", "profile.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "profile-secret")
    assert anon().get("/api/v1/auth/providers").json() == {"google": False}


def test_email_and_password_work_while_google_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "google_login_client_id", "")
    monkeypatch.setattr(settings, "google_login_client_secret", "")
    u = make_user()
    c = anon()
    r = c.post("/api/v1/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 200 and c.get("/api/v1/auth/me").status_code == 200
    # and the Google entry points answer honestly instead of pretending
    start = c.get("/api/v1/auth/google/start", follow_redirects=False)
    assert start.status_code == 303 and "google_error=not_configured" in start.headers["location"] and "/login" in start.headers["location"]


# ------------------------------------------------------------------------------------------------------------------------------ production cookies
def cookies_of(response):
    out = {}
    for h in response.headers.get_list("set-cookie"):
        name = h.split("=", 1)[0]
        out[name] = h
    return out


def test_session_and_csrf_cookies_have_the_production_attributes_and_logout_clears_them_on_the_same_domain(monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "cookie_domain", ".flowqr.site")
    u = make_user()
    c = TestClient(app, base_url="https://api.flowqr.site")  # a Secure, Domain=.flowqr.site cookie is only sent back to https://*.flowqr.site, exactly like a browser
    r = c.post("/api/v1/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 200
    ck = cookies_of(r)
    sess, csrf = ck["flowqr_session"], ck["flowqr_csrf"]
    for cookie in (sess, csrf):
        assert "Domain=.flowqr.site" in cookie and "Secure" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "HttpOnly" in sess, "the session cookie must not be readable by JavaScript"
    assert "HttpOnly" not in csrf, "the CSRF cookie must be readable by the site so it can be echoed in X-CSRF-Token"
    assert r.json()["csrf_token"] and csrf.split("=", 1)[1].split(";")[0] == r.json()["csrf_token"]
    assert "token" not in r.text.lower().replace("csrf_token", "")  # no session token in the body

    out = c.post("/api/v1/auth/logout", headers={"Origin": "https://www.flowqr.site", "X-CSRF-Token": r.json()["csrf_token"]})
    assert out.status_code == 204
    gone = cookies_of(out)
    for name in ("flowqr_session", "flowqr_csrf"):
        assert name in gone and "Domain=.flowqr.site" in gone[name] and re.search(r"Max-Age=0|expires=", gone[name], re.I), (name, gone.get(name))
    assert c.get("/api/v1/auth/me").status_code == 401  # the session really is gone server-side too


def test_a_state_changing_call_without_the_csrf_header_is_refused_even_with_a_valid_session():
    u = make_user()
    c = anon()
    r = c.post("/api/v1/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 200
    assert c.post("/api/v1/auth/logout").status_code == 403  # cookie alone is not enough
    assert c.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert c.post("/api/v1/auth/logout", headers={"X-CSRF-Token": r.json()["csrf_token"]}).status_code == 204


def test_wrong_password_and_unknown_email_look_the_same():
    u = make_user()
    a = anon().post("/api/v1/auth/login", json={"email": u.email, "password": "Wrong-Passw0rd!1"})
    b = anon().post("/api/v1/auth/login", json={"email": "nobody-here@example.com", "password": "Wrong-Passw0rd!1"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


# ------------------------------------------------------------------------------------------------------------------------------ the frontend honours it
@pytest.mark.skipif(not FRONTEND.exists(), reason="the frontend sources are not mounted in this run")
def test_the_login_and_sign_up_pages_only_offer_google_when_the_server_says_it_works():
    google = (FRONTEND / "components" / "GoogleAuth.tsx").read_text(encoding="utf-8")
    login = (FRONTEND / "app" / "(auth)" / "login" / "page.tsx").read_text(encoding="utf-8")
    register = (FRONTEND / "app" / "(auth)" / "register" / "page.tsx").read_text(encoding="utf-8")
    assert "/auth/providers" in google
    for page in (login, register):
        assert "GoogleSignIn" in page and "<GoogleButton" not in page, "a page renders the Google button unconditionally"
    assert "GoogleSignIn" in (FRONTEND / "app" / "(app)" / "settings" / "account" / "page.tsx").read_text(encoding="utf-8") or "useGoogleAvailable" in (FRONTEND / "app" / "(app)" / "settings" / "account" / "page.tsx").read_text(encoding="utf-8")
