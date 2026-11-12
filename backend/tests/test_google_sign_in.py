"""Continue with Google: the REAL provider code (PKCE, token exchange, ID-token verification) runs against a mocked
Google HTTP transport and a locally generated RSA key, so signature/audience/issuer/expiry/nonce checks are genuinely
exercised. Nothing here talks to Google or uses real credentials."""
import base64
import json
import os
import subprocess
import sys
import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.services.google import login as gl
from tests.conftest import Session, make_business, make_user, owner_exec, owner_query

CLIENT_ID = "login-client.apps.googleusercontent.com"
KID = "test-key-1"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict:
    jwk = json.loads(RSAAlgorithm.to_jwk(_KEY.public_key()))
    return {"keys": [{**jwk, "kid": KID, "alg": "RS256", "use": "sig"}]}


class FakeGoogle:
    """Mock Google: serves JWKS and the token endpoint, and signs whatever ID token the test asks for."""

    def __init__(self):
        self.claims: dict = {}
        self.key = _KEY
        self.alg = "RS256"
        self.token_status = 200
        self.token_requests: list[dict] = []
        self.nonce_from_auth_url: str | None = None

    def id_token(self, **over) -> str:
        now = int(time.time())
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "g-" + uuid.uuid4().hex[:12],
                  "email": f"g-{uuid.uuid4().hex[:8]}@example.com", "email_verified": True, "name": "Gina Google",
                  "iat": now, "exp": now + 600, "nonce": self.nonce_from_auth_url, **self.claims, **over}
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, self.key, algorithm=self.alg, headers={"kid": KID})

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(gl.JWKS_URL):
            return httpx.Response(200, json=_jwks())
        if request.url == httpx.URL(gl.TOKEN_URL):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": self.id_token(), "access_token": "ignored"})
        return httpx.Response(404)


@pytest.fixture()
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(settings, "google_login_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_login_client_secret", "login-secret")
    monkeypatch.setattr(settings, "google_login_redirect_uri", "http://localhost:3000/api/v1/auth/google/callback")
    gl.clear_jwks_cache()
    provider = gl.HttpGoogleLoginProvider(http=httpx.Client(transport=httpx.MockTransport(fake.handler)))
    monkeypatch.setattr("app.api.v1.auth_google.get_google_login_provider", lambda: provider)
    yield fake
    gl.clear_jwks_cache()


def begin(fake: FakeGoogle, s: Session | None = None, link: bool = False):
    """Click the button: returns (session, state, auth_query). Does NOT follow the redirect to Google."""
    s = s or Session(None, "anon")
    if link:
        r = s.post("/auth/google/link")
        assert r.status_code == 200, r.text
        url = r.json()["auth_url"]
    else:
        r = s.http.get("/api/v1/auth/google/start", follow_redirects=False)
        assert r.status_code == 303, r.text
        url = r.headers["location"]
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    fake.nonce_from_auth_url = q["nonce"]
    return s, q["state"], q


def finish(s: Session, state: str, code="auth-code", **params):
    return s.http.get("/api/v1/auth/google/callback", params={"code": code, "state": state, **params}, follow_redirects=False)


def sign_in(fake, s=None, **claims):
    fake.claims = claims
    s, state, _ = begin(fake, s)
    return s, finish(s, state)


def landing(r) -> tuple[str, dict]:
    u = urlparse(r.headers["location"])
    return u.path, {k: v[0] for k, v in parse_qs(u.query).items()}


# ---------------------------------------------------------------------------------------------- the authorize request

def test_start_builds_oidc_request_with_state_nonce_and_pkce_s256(google):
    s, state, q = begin(google)
    assert q["client_id"] == CLIENT_ID and q["response_type"] == "code"
    assert q["scope"] == "openid email profile"  # nothing near business.manage
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert q["state"] and q["nonce"] and q["state"] != q["nonce"]
    assert "login-secret" not in json.dumps(q) and "access_type" not in q


def test_flow_cookie_is_httponly_short_lived_and_path_scoped(google):
    r = Session(None, "x").http.get("/api/v1/auth/google/start", follow_redirects=False)
    c = next(h for h in r.headers.get_list("set-cookie") if h.startswith("flowqr_gl_oauth="))
    assert "HttpOnly" in c and "Max-Age=600" in c and "SameSite=lax" in c and "Path=/api/v1/auth/google" in c


def test_pkce_verifier_sent_to_google_matches_challenge(google):
    s, state, q = begin(google)
    assert finish(s, state).status_code == 303
    sent = google.token_requests[0]
    assert gl.pkce_challenge(sent["code_verifier"]) == q["code_challenge"]
    assert sent["client_id"] == CLIENT_ID and sent["grant_type"] == "authorization_code"


def test_not_configured_is_reported_not_faked(monkeypatch):
    monkeypatch.setattr(settings, "google_login_client_id", "")
    r = Session(None, "x").http.get("/api/v1/auth/google/start", follow_redirects=False)
    assert landing(r) == ("/login", {"google_error": "not_configured"})


# ---------------------------------------------------------------------------------------------- new / returning users

def test_new_google_user_is_created_verified_passwordless_and_sent_to_onboarding(google):
    email = f"new-{uuid.uuid4().hex[:6]}@example.com"
    s, r = sign_in(google, email=email, name="Nina New")
    assert r.status_code == 303 and landing(r)[0] == "/onboarding"
    me = s.get("/auth/me").json()  # session persists: the cookie set on the redirect authenticates the next call
    assert me["user"]["email"] == email and me["user"]["full_name"] == "Nina New"
    assert me["user"]["email_verified_at"] and me["user"]["has_local_login"] is False and me["user"]["google_linked"] is True
    assert me["memberships"] == []  # no business yet => existing onboarding flow creates it
    h, sub = owner_query("SELECT password_hash, google_sub FROM users WHERE email=:e", e=email)[0]
    assert h is None and sub
    s.csrf = me["csrf_token"]
    assert s.post("/tenants", json={"name": "Nina's Salon", "category": "Salon"}).status_code == 201  # onboarding works


def test_returning_google_user_logs_in_by_sub_even_if_google_email_changes(google):
    sub = "g-" + uuid.uuid4().hex
    first_email = f"ret-{uuid.uuid4().hex[:6]}@example.com"
    _, r = sign_in(google, sub=sub, email=first_email)
    assert landing(r)[0] == "/onboarding"
    s2, r2 = sign_in(google, sub=sub, email=f"renamed-{uuid.uuid4().hex[:6]}@example.com")
    assert landing(r2)[0] == "/dashboard"
    assert s2.get("/auth/me").json()["user"]["email"] == first_email
    assert owner_query("SELECT count(*) FROM users WHERE google_sub=:s", s=sub)[0][0] == 1


def test_session_cookies_after_callback(google):
    _, r = sign_in(google)
    cookies = r.headers.get_list("set-cookie")
    sess = next(c for c in cookies if c.startswith("flowqr_session="))
    assert "HttpOnly" in sess and "SameSite=lax" in sess
    assert not any("HttpOnly" in c for c in cookies if c.startswith("flowqr_csrf="))
    assert any(c.startswith("flowqr_gl_oauth=") and "Max-Age=0" in c for c in cookies)  # flow cookie cleared (single use)


def test_logout_then_google_login_again(google):
    sub = "g-" + uuid.uuid4().hex
    s, _ = sign_in(google, sub=sub)
    s.csrf = s.get("/auth/me").json()["csrf_token"]
    assert s.post("/auth/logout").status_code == 204 and s.get("/auth/me").status_code == 401
    s2, r = sign_in(google, sub=sub)
    assert landing(r)[0] == "/dashboard" and s2.get("/auth/me").status_code == 200


def test_platform_admin_is_never_granted_through_an_unverified_google_email(google):
    _, r = sign_in(google, email="root@flowhq-admin.example.com", email_verified=False)
    assert landing(r)[1]["google_error"] == "email_not_verified"


# ---------------------------------------------------------------------------------------------- account linking

def test_links_to_existing_account_with_verified_email_and_password_still_works(google):
    u = make_user()  # registered AND email-verified
    s, r = sign_in(google, email=u.email)
    assert landing(r)[0] == "/dashboard"
    me = s.get("/auth/me").json()["user"]
    assert me["email"] == u.email and me["google_linked"] and me["has_local_login"]
    assert owner_query("SELECT count(*) FROM users WHERE email=:e", e=u.email)[0][0] == 1
    again = Session(None, u.email).http.post("/api/v1/auth/login", json={"email": u.email, "password": u.password})
    assert again.status_code == 200  # email/password login unaffected by linking


def test_refuses_to_link_unverified_existing_account(google):
    u = make_user(verify=False)  # pre-registered (possibly by an attacker) and never verified
    s, r = sign_in(google, email=u.email)
    assert landing(r) == ("/login", {"google_error": "account_unverified"})
    assert s.get("/auth/me").status_code == 401
    assert owner_query("SELECT google_sub FROM users WHERE email=:e", e=u.email)[0][0] is None


def test_unverified_google_email_never_links_or_creates(google):
    u = make_user()
    s, r = sign_in(google, email=u.email, email_verified=False)
    assert landing(r)[1]["google_error"] == "email_not_verified" and s.get("/auth/me").status_code == 401
    assert owner_query("SELECT google_sub FROM users WHERE email=:e", e=u.email)[0][0] is None
    new_email = f"nv-{uuid.uuid4().hex[:6]}@example.com"
    sign_in(google, email=new_email, email_verified=False)
    assert owner_query("SELECT count(*) FROM users WHERE email=:e", e=new_email)[0][0] == 0


def test_email_verified_as_string_false_is_not_trusted(google):
    _, r = sign_in(google, email=f"s-{uuid.uuid4().hex[:6]}@example.com", email_verified="false")
    assert landing(r)[1]["google_error"] == "email_not_verified"


def test_different_google_account_cannot_take_over_a_linked_user(google):
    u = make_user()
    sign_in(google, email=u.email, sub="g-first-" + uuid.uuid4().hex[:8])
    _, r = sign_in(google, email=u.email, sub="g-second-" + uuid.uuid4().hex[:8])
    assert landing(r)[1]["google_error"] == "already_linked"


def test_deactivated_account_cannot_sign_in_with_google(google):
    u = make_user()
    sub = "g-" + uuid.uuid4().hex
    sign_in(google, email=u.email, sub=sub)
    owner_exec("UPDATE users SET is_active=false WHERE email=:e", e=u.email)
    s, r = sign_in(google, email=u.email, sub=sub)
    assert landing(r)[1]["google_error"] == "account_disabled" and s.get("/auth/me").status_code == 401


def test_signed_in_user_can_link_google_via_post_only(google):
    u = make_user()
    assert Session(None, "x").http.get("/api/v1/auth/google/link", follow_redirects=False).status_code in (404, 405)
    no_csrf = u.http.post("/api/v1/auth/google/link")
    assert no_csrf.status_code == 403  # a third-party page cannot start a link
    google.claims = {"email": "someone-else@example.com"}  # linking does not require matching emails, only a verified Google identity
    s, state, _ = begin(google, u, link=True)
    r = finish(s, state)
    assert landing(r) == ("/settings", {"google": "linked"})
    assert u.get("/auth/me").json()["user"]["google_linked"] is True


def test_link_flow_requires_the_same_signed_in_user(google):
    a, b = make_user(), make_user()
    s, state, _ = begin(google, a, link=True)  # flow cookie is bound to user A
    swap = s.http.post("/api/v1/auth/login", json={"email": b.email, "password": b.password})  # same browser, now user B
    assert swap.status_code == 200
    r = finish(s, state)
    assert landing(r)[1]["google_error"] == "session_mismatch"
    assert owner_query("SELECT count(*) FROM users WHERE google_sub IS NOT NULL AND email IN (:a,:b)", a=a.email, b=b.email)[0][0] == 0


# ---------------------------------------------------------------------------------------------- state / nonce / token attacks

def test_invalid_state_is_rejected(google):
    s, state, _ = begin(google)
    r = finish(s, "not-the-state")
    assert landing(r) == ("/login", {"google_error": "invalid_state"}) and s.get("/auth/me").status_code == 401
    assert google.token_requests == []  # rejected before any code exchange


def test_missing_flow_cookie_is_rejected(google):
    _, state, _ = begin(google)
    r = finish(Session(None, "other-browser"), state)  # callback arrives in a browser that never started the flow
    assert landing(r)[1]["google_error"] == "invalid_state"


def test_tampered_or_expired_flow_cookie_is_rejected(google, monkeypatch):
    s, state, _ = begin(google)
    good = s.http.cookies.get("flowqr_gl_oauth")
    s.http.cookies.set("flowqr_gl_oauth", good[:-4] + "0000", path="/api/v1/auth/google")
    assert landing(finish(s, state))[1]["google_error"] == "invalid_state"
    s, state, _ = begin(google)
    real = time.time()
    monkeypatch.setattr("app.api.v1.auth_google.time.time", lambda: real + 601)
    assert landing(finish(s, state))[1]["google_error"] == "invalid_state"


def test_state_is_single_use(google):
    s, state, _ = begin(google)
    assert landing(finish(s, state))[0] == "/onboarding"
    assert landing(finish(s, state))[1]["google_error"] == "invalid_state"  # cookie was cleared by the first completion


def test_nonce_mismatch_is_rejected(google):
    google.claims = {"nonce": "attacker-replayed-nonce"}
    s, state, _ = begin(google)
    google.nonce_from_auth_url = "attacker-replayed-nonce"
    r = finish(s, state)
    assert landing(r)[1]["google_error"] == "invalid_nonce" and s.get("/auth/me").status_code == 401


def test_missing_nonce_claim_is_rejected(google):
    s, state, _ = begin(google)
    google.nonce_from_auth_url = None
    assert landing(finish(s, state))[1]["google_error"] == "invalid_nonce"


def test_access_denied_by_user(google):
    s, _, _ = begin(google)
    r = s.http.get("/api/v1/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert landing(r)[1]["google_error"] == "access_denied"


@pytest.mark.parametrize("name,setup,expect", [
    ("expired", dict(claims=dict(exp=int(time.time()) - 3600, iat=int(time.time()) - 7200)), "invalid_token"),
    ("wrong audience", dict(claims=dict(aud="some-other-client")), "invalid_token"),
    ("wrong issuer", dict(claims=dict(iss="https://evil.example.com")), "invalid_token"),
    ("signed by another key", dict(key=_OTHER_KEY), "invalid_token"),
    ("HS256 token", dict(key="x" * 40, alg="HS256"), "invalid_token"),
])
def test_bad_id_tokens_are_rejected_and_create_nothing(google, name, setup, expect):
    email = f"bad-{uuid.uuid4().hex[:6]}@example.com"
    google.claims = {"email": email, **setup.get("claims", {})}
    if "key" in setup:
        google.key, google.alg = setup["key"], setup.get("alg", "RS256")
    s, state, _ = begin(google)
    r = finish(s, state)
    assert landing(r)[1]["google_error"] == expect, name
    assert s.get("/auth/me").status_code == 401
    assert owner_query("SELECT count(*) FROM users WHERE email=:e", e=email)[0][0] == 0


def test_unsigned_alg_none_token_is_rejected(google):
    prov = gl.HttpGoogleLoginProvider(http=httpx.Client(transport=httpx.MockTransport(google.handler)))
    forged = jwt.encode({"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "x", "iat": int(time.time()),
                         "exp": int(time.time()) + 60, "nonce": "n"}, key=None, algorithm="none")
    with pytest.raises(gl.GoogleLoginError) as e:
        prov._verify(forged, "n")
    assert e.value.code == "invalid_token"


def test_issuer_without_scheme_is_accepted(google):
    _, r = sign_in(google, iss="accounts.google.com")
    assert landing(r)[0] == "/onboarding"


def test_token_endpoint_failure_is_a_clean_error(google):
    google.token_status = 400
    s, state, _ = begin(google)
    assert landing(finish(s, state))[1]["google_error"] == "exchange_failed"


# ---------------------------------------------------------------------------------------------- passwords

def google_only_user(google) -> tuple[Session, str]:
    email = f"go-{uuid.uuid4().hex[:6]}@example.com"
    s, _ = sign_in(google, email=email)
    s.csrf = s.get("/auth/me").json()["csrf_token"]
    s.email = email
    return s, email


def test_google_only_account_cannot_password_login_and_is_indistinguishable_from_wrong_password(google):
    s, email = google_only_user(google)
    r = Session(None, email).http.post("/api/v1/auth/login", json={"email": email, "password": "Str0ngPassw0rd!"})
    ghost = Session(None, "x").http.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "Str0ngPassw0rd!"})
    assert r.status_code == ghost.status_code == 401 and r.json() == ghost.json()  # no 500, no account-type leak


def test_google_only_user_can_set_password_then_use_both_methods(google):
    s, email = google_only_user(google)
    assert s.post("/auth/change-password", json={"current_password": "x", "new_password": "NewPassw0rd!!"}).json()["detail"]["code"] == "no_password_set"
    assert s.post("/auth/set-password", json={"new_password": "short"}).status_code == 422
    assert s.post("/auth/set-password", json={"new_password": "NewPassw0rd!!"}).status_code == 204
    assert s.get("/auth/me").json()["user"]["has_local_login"] is True
    pw = Session(None, email).http.post("/api/v1/auth/login", json={"email": email, "password": "NewPassw0rd!!"})
    assert pw.status_code == 200
    again = s.post("/auth/set-password", json={"new_password": "AnotherPassw0rd!"})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "password_already_set"
    assert s.post("/auth/change-password", json={"current_password": "NewPassw0rd!!", "new_password": "ThirdPassw0rd!!"}).status_code == 204
    assert owner_query("SELECT password_hash FROM users WHERE email=:e", e=email)[0][0].startswith("$argon2id$")


def test_set_password_requires_auth_and_csrf(google):
    s, _ = google_only_user(google)
    assert Session(None, "x").http.post("/api/v1/auth/set-password", json={"new_password": "NewPassw0rd!!"}).status_code == 401
    assert s.http.post("/api/v1/auth/set-password", json={"new_password": "NewPassw0rd!!"}).status_code == 403


def test_forgot_password_also_works_for_google_only_accounts(google):
    from tests.conftest import latest_token

    s, email = google_only_user(google)
    assert Session(None, "x").http.post("/api/v1/auth/password-reset/request", json={"email": email}).status_code == 202
    tok = latest_token(email, "reset-password")
    r = Session(None, "x").http.post("/api/v1/auth/password-reset/confirm", json={"token": tok, "new_password": "ResetPassw0rd!!"})
    assert r.status_code == 204
    assert Session(None, email).http.post("/api/v1/auth/login", json={"email": email, "password": "ResetPassw0rd!!"}).status_code == 200


def test_existing_password_login_and_registration_still_work():
    u = make_user()
    r = Session(None, u.email).http.post("/api/v1/auth/login", json={"email": u.email, "password": u.password})
    assert r.status_code == 200 and r.json()["user"]["has_local_login"] is True and r.json()["user"]["google_linked"] is False
    assert u.http.post("/api/v1/auth/register", json={"email": u.email, "password": u.password, "full_name": "Dup"}).status_code == 409


def test_business_profile_google_integration_is_untouched():
    """The Business Profile client/scopes/endpoints are independent of the login client."""
    from app.services.google.provider import HttpGoogleProvider

    url = HttpGoogleProvider().build_auth_url("st")
    assert "business.manage" in url and "test-client-id" in url
    biz = make_business()
    assert biz.get("/google/status").json()["configured"] is True


# ---------------------------------------------------------------------------------------------- config + migration

def test_config_guard_for_login_client():
    from tests.test_config_guard import good
    from app.core.config import config_problems

    ok = good(google_login_client_id="login.apps.googleusercontent.com", google_login_client_secret="s",
              google_login_redirect_uri="https://app.flowqr.co.in/api/v1/auth/google/callback", google_client_id="biz.apps.googleusercontent.com")
    assert config_problems(ok) == []
    cases = {
        "both be set": dict(google_login_client_secret=""),
        "GOOGLE_LOGIN_REDIRECT_URI": dict(google_login_redirect_uri="http://localhost:3000/api/v1/auth/google/callback"),
        "separate OAuth client": dict(google_client_id="login.apps.googleusercontent.com"),
    }
    for needle, over in cases.items():
        probs = config_problems(good(**{**dict(google_login_client_id="login.apps.googleusercontent.com", google_login_client_secret="s",
                                               google_login_redirect_uri="https://app.flowqr.co.in/api/v1/auth/google/callback",
                                               google_client_id="biz.apps.googleusercontent.com"), **over}))
        assert any(needle in p for p in probs), (needle, probs)


def test_migration_0006_is_reversible_and_keeps_existing_users(google):
    backend = os.path.dirname(os.path.dirname(__file__))

    def alembic(*args):
        subprocess.run([sys.executable, "-m", "alembic", *args], check=True, env={**os.environ}, cwd=backend)

    pw_user = make_user()
    gonly, email = google_only_user(google)
    before = owner_query("SELECT password_hash FROM users WHERE email=:e", e=pw_user.email)[0][0]
    alembic("downgrade", "0005")
    try:
        cols = {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name='users'")}
        assert "google_sub" not in cols
        assert owner_query("SELECT password_hash FROM users WHERE email=:e", e=pw_user.email)[0][0] == before  # untouched
        placeholder = owner_query("SELECT password_hash FROM users WHERE email=:e", e=email)[0][0]
        assert placeholder == "!"  # NOT NULL restored; not a valid Argon2 hash, so it can never authenticate
    finally:
        alembic("upgrade", "head")
    assert "google_sub" in {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name='users'")}
    eng = create_engine(settings.migration_database_url)
    with eng.begin() as c:
        nullable = c.execute(text("SELECT is_nullable FROM information_schema.columns WHERE table_name='users' AND column_name='password_hash'")).scalar()
    assert nullable == "YES"
    assert Session(None, pw_user.email).http.post("/api/v1/auth/login", json={"email": pw_user.email, "password": pw_user.password}).status_code == 200
