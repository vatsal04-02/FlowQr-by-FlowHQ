"""The registration gate (services/registration.py; owner decision 2026-11-15: production defaults to `allowlist`).
Real application and PostgreSQL; Google sign-in runs the real provider code against a mocked Google transport (tests/test_google_sign_in.py). Nothing here talks to Google or sends mail."""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, config_problems, settings
from app.main import app
from app.services import registration as reg
from tests.conftest import Session, latest_token, make_business, make_user, owner_exec, owner_query
from tests.test_config_guard import good
from tests.test_google_sign_in import google, landing, sign_in  # noqa: F401

PW = "Str0ngPassw0rd!"
STRANGER = {"detail": {"code": "registration_restricted", "message": reg.MESSAGE}}


@pytest.fixture(autouse=True)
def clean_list():
    owner_exec("DELETE FROM registration_allowlist")
    yield
    owner_exec("DELETE FROM registration_allowlist")


def mode(monkeypatch, m, allow=""):
    monkeypatch.setattr(settings, "registration_mode", m)
    monkeypatch.setattr(settings, "registration_allowlist", allow)


def attempt(email, name="Reg Test", client=None):
    c = client or TestClient(app, base_url="http://testserver")
    return c, c.post("/api/v1/auth/register", json={"email": email, "password": PW, "full_name": name})


def fresh(prefix="p"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


def users_with(email):
    return owner_query("SELECT count(*) FROM users WHERE email = :e", e=email.lower())[0][0]


def audits(action):
    return owner_query("SELECT metadata, ip FROM audit_logs WHERE action = :a ORDER BY created_at", a=action)


# ------------------------------------------------------------------------------------------------------------------------------ the modes
def test_the_default_mode_is_allowlist_in_staging_and_production_and_open_in_development():
    assert Settings(_env_file=None, app_env="production").effective_registration_mode == "allowlist"
    assert Settings(_env_file=None, app_env="staging").effective_registration_mode == "allowlist"
    assert Settings(_env_file=None, app_env="development").effective_registration_mode == "open"
    assert Settings(_env_file=None, app_env="test").effective_registration_mode == "open"


@pytest.mark.parametrize("explicit,expected", [("closed", "closed"), ("ALLOWLIST", "allowlist"), (" open ", "open"), ("anything-else", "closed"), ("yes", "closed"), ("true", "closed")])
def test_an_explicit_mode_wins_and_an_unknown_value_fails_closed(explicit, expected):
    assert Settings(_env_file=None, app_env="production", registration_mode=explicit).effective_registration_mode == expected


def test_the_production_guard_refuses_an_unknown_mode_and_accepts_open_only_when_written_explicitly():
    assert any("REGISTRATION_MODE" in p for p in config_problems(good(registration_mode="public")))
    assert config_problems(good(registration_mode="open")) == [] and config_problems(good(registration_mode="closed")) == [] and config_problems(good()) == []
    assert Settings(_env_file=None, app_env="production").effective_registration_mode != "open"  # nobody gets public sign-ups by forgetting a setting


# ------------------------------------------------------------------------------------------------------------------------------ normalisation
@pytest.mark.parametrize("raw,norm", [
    ("  Alice@Example.COM ", "alice@example.com"), ("ＡＬＩＣＥ@ＥＸＡＭＰＬＥ.ＣＯＭ", "alice@example.com"), ("a.b+tag@example.com", "a.b+tag@example.com"),
    ("a@b", None), ("a@@b.com", None), ("two words@example.com", None), ("a@example..com", None), ("@example.com", None), ("", None), (None, None), (12345, None), ("a@example.com\n", "a@example.com"),
])
def test_emails_are_normalised_before_comparison(raw, norm):
    assert reg.normalize_email(raw) == norm


def test_look_alike_characters_and_plus_aliases_are_not_the_listed_address(monkeypatch):
    mode(monkeypatch, "allowlist", "priya@example.com")
    from app.core.db import system_session
    db = system_session()
    try:
        assert reg.permits(db, "PRIYA@Example.com") is True
        for lookalike in ("рriya@example.com", "priya+x@example.com", "priya@example.co", "priya@exаmple.com"):  # Cyrillic letters in the first and last
            assert reg.permits(db, lookalike) is False, lookalike
    finally:
        db.close()


# ------------------------------------------------------------------------------------------------------------------------------ password registration
def test_closed_mode_refuses_every_new_account_with_the_standard_answer_and_creates_nothing(monkeypatch):
    mode(monkeypatch, "closed", "listed@example.com")  # even a listed address: closed means closed
    email = fresh()
    _, r = attempt(email)
    assert r.status_code == 403 and r.json() == STRANGER and users_with(email) == 0
    _, r2 = attempt("listed@example.com")
    assert r2.status_code == 403 and users_with("listed@example.com") == 0


def test_allowlist_mode_lets_a_listed_address_register_and_refuses_everyone_else(monkeypatch):
    listed = fresh("ok")
    mode(monkeypatch, "allowlist", f"someone-else@example.com, {listed}")
    c, r = attempt(listed)
    assert r.status_code == 201 and r.json()["user"]["email"] == listed and users_with(listed) == 1
    other = fresh("no")
    _, r2 = attempt(other)
    assert r2.status_code == 403 and r2.json() == STRANGER and users_with(other) == 0


def test_matching_is_case_and_whitespace_insensitive_on_both_sides(monkeypatch):
    mode(monkeypatch, "allowlist", "  Mixed.Case@Example.COM  ")
    _, r = attempt("MIXED.case@example.com")
    assert r.status_code == 201, r.text


def test_a_refused_address_gets_the_same_answer_whether_it_is_unlisted_or_the_mode_is_closed(monkeypatch):
    email = fresh()
    mode(monkeypatch, "allowlist", "someone@example.com")
    a = attempt(email)[1]
    mode(monkeypatch, "closed", "")
    b = attempt(email)[1]
    assert a.status_code == b.status_code == 403 and a.json() == b.json() == STRANGER


def test_the_gate_answers_before_account_exists_so_a_refusal_never_reveals_whether_an_address_is_registered(monkeypatch):
    existing = make_user()  # registered while the mode was open
    mode(monkeypatch, "allowlist", "someone@example.com")
    _, r = attempt(existing.email)
    assert r.status_code == 403 and r.json() == STRANGER  # NOT 409 "already exists"
    _, fresh_r = attempt(fresh())
    assert fresh_r.json() == r.json()


def test_the_database_list_and_the_environment_list_are_both_honoured(monkeypatch):
    mode(monkeypatch, "allowlist", "")
    a, b = fresh("db"), fresh("env")
    owner_exec("INSERT INTO registration_allowlist (id, email, created_at) VALUES (gen_random_uuid(), :e, now())", e=a)
    assert attempt(a)[1].status_code == 201
    mode(monkeypatch, "allowlist", b)
    assert attempt(b)[1].status_code == 201
    assert owner_query("SELECT used_at IS NOT NULL FROM registration_allowlist WHERE email = :e", e=a)[0][0] is True  # recorded as used


def test_open_mode_is_public_registration(monkeypatch):
    mode(monkeypatch, "open")
    assert attempt(fresh())[1].status_code == 201


def test_repeated_refusals_from_one_address_are_rate_limited(monkeypatch):
    mode(monkeypatch, "allowlist", "")
    codes = [attempt(fresh())[1].status_code for _ in range(8)]
    assert codes[:5] == [403] * 5 and 429 in codes[5:], codes


def test_every_attempt_is_audited_and_a_refused_address_is_never_stored_in_full(monkeypatch):
    mode(monkeypatch, "allowlist", "")
    refused, allowed = fresh("secret-name"), fresh("welcome")
    attempt(refused)
    owner_exec("INSERT INTO registration_allowlist (id, email, created_at) VALUES (gen_random_uuid(), :e, now())", e=allowed)
    attempt(allowed)
    rej = [m for m, _ in audits("registration.rejected") if m.get("domain") == "example.com"]
    ok = [m for m, _ in audits("registration.allowed") if m.get("domain") == "example.com"]
    assert rej and ok and rej[-1]["via"] == "password" and rej[-1]["mode"] == "allowlist" and len(rej[-1]["email_sha256"]) == 16
    everything = str(owner_query("SELECT metadata::text FROM audit_logs WHERE action LIKE 'registration.%'"))
    assert refused not in everything and allowed not in everything, "a full address was written to the audit log"


# ------------------------------------------------------------------------------------------------------------------------------ administrators and verification
def test_an_administrator_address_can_always_register_but_is_no_administrator_until_it_is_verified(monkeypatch):
    mode(monkeypatch, "closed", "")
    admin_email = f"first-admin-{uuid.uuid4().hex[:6]}@example.com"
    monkeypatch.setattr(settings, "platform_admin_emails", f"{settings.platform_admin_emails},{admin_email}")
    c, r = attempt(admin_email)
    assert r.status_code == 201 and r.json()["user"]["is_platform_admin"] is False
    assert c.get("/api/v1/admin/stats").status_code == 403
    assert c.post("/api/v1/auth/verify-email", json={"token": latest_token(admin_email, "verify-email")}).status_code == 204
    assert c.get("/api/v1/auth/me").json()["user"]["is_platform_admin"] is True and c.get("/api/v1/admin/stats").status_code == 200


def test_being_on_the_list_grants_no_privileges_and_verification_still_works(monkeypatch):
    email = fresh("member")
    mode(monkeypatch, "allowlist", email)
    c, r = attempt(email)
    assert r.status_code == 201 and r.json()["user"]["is_platform_admin"] is False and r.json()["user"]["email_verified_at"] is None
    assert c.get("/api/v1/admin/stats").status_code == 403
    assert c.post("/api/v1/auth/verify-email", json={"token": latest_token(email, "verify-email")}).status_code == 204
    assert c.get("/api/v1/auth/me").json()["user"]["email_verified_at"] is not None


# ------------------------------------------------------------------------------------------------------------------------------ business creation
def new_business(c, csrf, name="Gate Clinic"):
    return c.post("/api/v1/tenants", json={"name": name, "category": "Physiotherapy clinic", "language": "en"}, headers={"X-CSRF-Token": csrf})


def test_outside_open_mode_a_business_needs_a_listed_and_verified_address(monkeypatch):
    email = fresh("owner")
    mode(monkeypatch, "allowlist", email)
    c, r = attempt(email)
    csrf = r.json()["csrf_token"]
    unverified = new_business(c, csrf)
    assert unverified.status_code == 403 and unverified.json()["detail"]["code"] == "email_not_verified"  # someone who squats an approved address cannot spend its trial
    assert c.post("/api/v1/auth/verify-email", json={"token": latest_token(email, "verify-email")}).status_code == 204
    assert new_business(c, csrf).status_code == 201


def test_a_signed_in_user_who_is_not_approved_cannot_create_a_business_in_allowlist_or_closed_mode(monkeypatch):
    early = make_user()  # registered while the mode was open: keeps signing in, but is not approved to open a business
    mode(monkeypatch, "allowlist", "")
    r = early.post("/tenants", json={"name": "Late Clinic", "category": "Physiotherapy clinic", "language": "en"})
    assert r.status_code == 403 and r.json() == STRANGER
    mode(monkeypatch, "closed", early.email)
    r = early.post("/tenants", json={"name": "Late Clinic", "category": "Physiotherapy clinic", "language": "en"})
    assert r.status_code == 403 and r.json() == STRANGER
    assert early.get("/auth/me").status_code == 200  # but signing in and using the account is untouched


def test_a_platform_administrator_can_still_create_a_business_when_closed(monkeypatch, admin):
    mode(monkeypatch, "closed", "")
    r = admin.post("/tenants", json={"name": "Admin Test Co", "category": "Physiotherapy clinic", "language": "en"})
    assert r.status_code == 201, r.text


def test_open_mode_leaves_business_creation_exactly_as_it_was(monkeypatch):
    mode(monkeypatch, "open")
    u = make_user(verify=False)
    assert u.post("/tenants", json={"name": "Open Co", "category": "Physiotherapy clinic", "language": "en"}).status_code == 201


# ------------------------------------------------------------------------------------------------------------------------------ existing users keep signing in
def test_existing_users_sign_in_and_stay_signed_in_in_every_mode(monkeypatch):
    biz = make_business("Existing Co")
    for m in ("closed", "allowlist", "open"):
        mode(monkeypatch, m, "")
        c = TestClient(app, base_url="http://testserver")
        r = c.post("/api/v1/auth/login", json={"email": biz.email, "password": biz.password})
        assert r.status_code == 200, (m, r.text)
        assert c.get("/api/v1/tenant").status_code == 200
        assert c.get("/api/v1/auth/registration").json() == {"mode": m}


def test_the_public_registration_endpoint_discloses_only_the_mode(monkeypatch):
    owner_exec("INSERT INTO registration_allowlist (id, email, created_at) VALUES (gen_random_uuid(), 'private-person@example.com', now())")
    mode(monkeypatch, "allowlist", "secret-env@example.com")
    body = TestClient(app, base_url="http://testserver").get("/api/v1/auth/registration")
    assert body.status_code == 200 and body.json() == {"mode": "allowlist"} and "private-person" not in body.text and "secret-env" not in body.text


# ------------------------------------------------------------------------------------------------------------------------------ Google
def user_row(email):
    return owner_query("SELECT id, email_verified_at IS NOT NULL, google_sub FROM users WHERE email = :e", e=email.lower())


def test_google_sign_up_is_refused_in_closed_mode_and_creates_nothing(google, monkeypatch):
    mode(monkeypatch, "closed", "")
    email = fresh("g")
    _, r = sign_in(google, email=email, email_verified=True)
    path, q = landing(r)
    assert path == "/login" and q["google_error"] == "registration_restricted" and user_row(email) == []
    assert any(m["via"] == "google" for m, _ in audits("registration.rejected"))


def test_google_sign_up_follows_the_allowlist_including_case(google, monkeypatch):
    listed, other = fresh("glisted"), fresh("gother")
    mode(monkeypatch, "allowlist", listed)
    _, r = sign_in(google, email=listed.upper(), email_verified=True)  # Google may return any case
    path, q = landing(r)
    assert path == "/onboarding" and "google_error" not in q and len(user_row(listed)) == 1
    _, r2 = sign_in(google, email=other, email_verified=True)
    assert landing(r2)[1]["google_error"] == "registration_restricted" and user_row(other) == []


def test_google_sign_in_of_an_existing_account_is_never_blocked(google, monkeypatch):
    email = fresh("gexisting")
    mode(monkeypatch, "open")
    s, r = sign_in(google, email=email, email_verified=True, sub="g-existing-sub-1")
    assert landing(r)[0] == "/onboarding"
    mode(monkeypatch, "closed", "")
    _, again = sign_in(google, email=email, email_verified=True, sub="g-existing-sub-1")  # a returning Google identity
    assert landing(again)[0] == "/overview" or landing(again)[0] == "/onboarding"
    assert "google_error" not in landing(again)[1]


def test_a_verified_password_account_can_link_google_when_closed(google, monkeypatch):
    mode(monkeypatch, "open")
    u = make_user()  # verified
    mode(monkeypatch, "closed", "")
    _, r = sign_in(google, email=u.email, email_verified=True, sub="g-link-sub-9")
    assert "google_error" not in landing(r)[1] and user_row(u.email)[0][2] == "g-link-sub-9"


def test_google_cannot_create_an_account_for_an_unverified_google_email_in_any_mode(google, monkeypatch):
    mode(monkeypatch, "open")
    _, r = sign_in(google, email=fresh("gunv"), email_verified=False)
    assert landing(r)[1]["google_error"] == "email_not_verified"


# ------------------------------------------------------------------------------------------------------------------------------ administrator tools
def test_an_administrator_manages_the_list_through_the_api_and_every_change_is_audited(admin, monkeypatch):
    mode(monkeypatch, "allowlist", "")
    target = fresh("approve")
    r = admin.post("/admin/registration/allowlist", json={"email": f"  {target.upper()} ", "note": "pilot clinic"})
    assert r.status_code == 201 and r.json()["email"] == target
    assert admin.post("/admin/registration/allowlist", json={"email": target.upper()}).json()["id"] == r.json()["id"]  # same address, same entry
    listing = admin.get("/admin/registration").json()
    assert listing["mode"] == "allowlist" and any(e["email"] == target and e["note"] == "pilot clinic" for e in listing["entries"])
    assert attempt(target)[1].status_code == 201
    assert admin.delete(f"/admin/registration/allowlist/{r.json()['id']}").status_code == 204
    assert attempt(fresh("after"))[1].status_code == 403
    assert attempt(target)[1].status_code == 403  # removed: a second registration of that address is refused too
    actions = [a for (a,) in owner_query("SELECT action FROM audit_logs WHERE action LIKE 'admin.registration_%'")]
    assert "admin.registration_allow" in actions and "admin.registration_disallow" in actions


def test_removing_an_address_stops_new_registration_but_not_an_existing_account(admin, monkeypatch):
    mode(monkeypatch, "allowlist", "")
    email = fresh("temp")
    entry = admin.post("/admin/registration/allowlist", json={"email": email}).json()
    c, r = attempt(email)
    assert r.status_code == 201
    admin.delete(f"/admin/registration/allowlist/{entry['id']}")
    assert TestClient(app, base_url="http://testserver").post("/api/v1/auth/login", json={"email": email, "password": PW}).status_code == 200


def test_the_list_api_refuses_invalid_addresses_and_everyone_who_is_not_a_platform_admin(admin, biz_a):
    assert admin.post("/admin/registration/allowlist", json={"email": "not an email"}).status_code == 422
    assert admin.post("/admin/registration/allowlist", json={"email": "a@b"}).status_code == 422
    for call in (lambda: biz_a.get("/admin/registration"), lambda: biz_a.post("/admin/registration/allowlist", json={"email": fresh()}),
                 lambda: biz_a.delete(f"/admin/registration/allowlist/{uuid.uuid4()}")):
        assert call().status_code == 403
    assert TestClient(app, base_url="http://testserver").get("/api/v1/admin/registration").status_code in (401, 403)


def test_the_command_line_tool_adds_lists_and_removes(monkeypatch, capsys):
    import argparse

    from app import ops_cli
    ns = lambda **k: argparse.Namespace(**{"add": None, "remove": None, "note": "", **k})  # noqa: E731
    mode(monkeypatch, "allowlist", "")
    email = fresh("cli")
    assert ops_cli.registration_cmd(ns(add=email.upper(), note="from the shell")) == 0
    out = capsys.readouterr().out
    assert f"allowed: {email}" in out and "registration mode: allowlist" in out and email in out
    assert attempt(email)[1].status_code == 201
    assert ops_cli.registration_cmd(ns(remove=email)) == 0 and ops_cli.registration_cmd(ns(remove=email)) == 1
    assert ops_cli.registration_cmd(ns(add="not an address")) == 1


# ------------------------------------------------------------------------------------------------------------------------------ the frontend says what the backend enforces
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


@pytest.mark.skipif(not FRONTEND.exists(), reason="the frontend sources are not mounted in this run")
def test_the_frontend_handles_every_refusal_the_backend_can_give():
    google_messages = (FRONTEND / "components" / "GoogleAuth.tsx").read_text(encoding="utf-8")
    register_page = (FRONTEND / "app" / "(auth)" / "register" / "page.tsx").read_text(encoding="utf-8")
    onboarding = (FRONTEND / "app" / "onboarding" / "page.tsx").read_text(encoding="utf-8")
    backend_google_codes = set(__import__("re").findall(r'fail\("([a-z_]+)"\)', (Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "auth_google.py").read_text(encoding="utf-8")))
    assert "registration_restricted" in backend_google_codes
    for code in backend_google_codes:
        assert f"{code}:" in google_messages, f"the frontend has no message for the Google sign-in error '{code}'"
    assert "/auth/registration" in register_page and "closed" in register_page and "allowlist" in register_page  # the page reads the mode and says so
    assert "email_not_verified" in onboarding and "resend-verification" in onboarding  # an unverified person is told to verify, with a way to ask again
    assert "registration_restricted" in onboarding or "403" in onboarding or "errorMessage" in onboarding  # a refused business is shown the backend's message, not a blank form
