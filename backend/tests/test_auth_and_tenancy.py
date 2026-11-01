import uuid

import pytest
from sqlalchemy import create_engine, text

from app.core.config import settings
from tests.conftest import Session, make_business, make_user


def test_register_login_logout_and_cookies():
    s = make_user()
    r = s.get("/auth/me")
    assert r.status_code == 200 and r.json()["user"]["email"] == s.email
    cookie = r.request.headers.get("cookie", "")
    set_cookie = s.http.cookies
    assert "flowqr_session" in set_cookie
    assert s.post("/auth/logout").status_code == 204
    assert s.get("/auth/me").status_code == 401


def test_session_cookie_is_httponly_and_token_not_in_body():
    s = Session(None, f"c-{uuid.uuid4().hex[:6]}@example.com")
    r = s.http.post("/api/v1/auth/register", json={"email": s.email, "password": s.password, "full_name": "Cookie Test"})
    sc = r.headers.get_list("set-cookie")
    session_cookie = next(c for c in sc if c.startswith("flowqr_session="))
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
    csrf_cookie = next(c for c in sc if c.startswith("flowqr_csrf="))
    assert "HttpOnly" not in csrf_cookie
    assert "password" not in r.text.lower()


def test_login_wrong_password_and_unknown_user_same_error():
    s = make_user()
    a = Session(None, s.email).http.post("/api/v1/auth/login", json={"email": s.email, "password": "WrongPassw0rd!!"})
    b = Session(None, "x").http.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "WrongPassw0rd!!"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_weak_password_rejected():
    s = Session(None, "weak@example.com")
    r = s.http.post("/api/v1/auth/register", json={"email": s.email, "password": "short", "full_name": "Weak"})
    assert r.status_code == 422


def test_duplicate_email_rejected():
    s = make_user()
    r = Session(None, s.email).http.post("/api/v1/auth/register", json={"email": s.email.upper(), "password": s.password, "full_name": "Dup"})
    assert r.status_code == 409


def test_csrf_required_on_state_changing_requests():
    s = make_business()
    r = s.http.post("/api/v1/locations", json={"name": "No CSRF Location"})  # no header
    assert r.status_code == 403
    r = s.http.post("/api/v1/locations", json={"name": "Bad CSRF"}, headers={"X-CSRF-Token": "nope"})
    assert r.status_code == 403
    assert s.post("/locations", json={"name": "Good CSRF"}).status_code == 201


def test_login_rate_limited_per_email():
    s = make_user()
    codes = []
    for _ in range(12):
        r = Session(None, s.email).http.post("/api/v1/auth/login", json={"email": s.email, "password": "WrongPassw0rd!!"})
        codes.append(r.status_code)
    assert 429 in codes


def test_password_hash_is_argon2id():
    s = make_user()
    from tests.conftest import owner_query
    h = owner_query("SELECT password_hash FROM users WHERE email=:e", e=s.email)[0][0]
    assert h.startswith("$argon2id$")


def test_onboarding_flow_and_phone_normalisation():
    s = make_user()
    r = s.post("/tenants", json={
        "name": "Geeta Krishna Physiotherapy", "category": "Physiotherapy", "phone": "98765 43210",
        "language": "hinglish", "timezone": "Asia/Kolkata", "website": "geetaphysio.in"})
    assert r.status_code == 201
    body = r.json()
    assert body["phone"] == "+91 98765 43210" and body["website"] == "https://geetaphysio.in"
    # cannot finish onboarding without a location
    assert s.post("/tenant/complete-onboarding").status_code == 400
    assert s.post("/locations", json={"name": "Gomti Nagar"}).status_code == 201
    r = s.post("/tenant/complete-onboarding")
    assert r.status_code == 200 and r.json()["onboarding_completed"] is True


def test_review_url_must_be_google_https():
    s = make_business()
    for bad in ["http://g.page/r/x", "https://evil.example.com/review", "javascript:alert(1)"]:
        r = s.patch(f"/locations/{s.location_id}", json={"review_url": bad})
        assert r.status_code == 422, bad
    r = s.patch(f"/locations/{s.location_id}", json={"review_url": "https://search.google.com/local/writereview?placeid=abc"})
    assert r.status_code == 200


# ---------------- Cross-tenant isolation ----------------

def test_cross_tenant_location_access_denied(biz_a, biz_b):
    loc_a = biz_a.location_id
    assert biz_b.get(f"/locations/{loc_a}").status_code == 404
    assert biz_b.patch(f"/locations/{loc_a}", json={"name": "Hacked"}).status_code == 404
    assert biz_b.delete(f"/locations/{loc_a}").status_code == 404
    ids = [l["id"] for l in biz_b.get("/locations").json()]
    assert loc_a not in ids
    assert biz_a.get(f"/locations/{loc_a}").json()["name"] != "Hacked"


def test_tenant_header_cannot_select_foreign_tenant(biz_a, biz_b):
    r = biz_b.get("/locations", headers={"X-Tenant-Id": biz_a.tenant_id})
    assert r.status_code == 403
    r = biz_b.get("/tenant", headers={"X-Tenant-Id": biz_a.tenant_id})
    assert r.status_code == 403
    r = biz_b.post("/auth/select-tenant", params={"tenant_id": biz_a.tenant_id})
    assert r.status_code == 403


def test_unauthenticated_requests_rejected():
    s = Session(None, "anon")
    for path in ["/locations", "/tenant", "/staff", "/auth/me"]:
        assert s.get(path).status_code == 401


def test_staff_role_cannot_manage_but_can_read(biz_a):
    staff = make_user()
    inv = biz_a.post("/staff/invitations", json={"email": staff.email, "role": "staff"})
    assert inv.status_code == 201
    # Fetch token the way a user would: it was "emailed"; in tests read the hash-less path via DB is impossible,
    # so create the invitation through the service with a known token instead.
    from app.core.db import SessionLocal, set_rls_context
    from app.core.security import hash_token
    from app.models import Invitation
    from app.models.base import utcnow
    from datetime import timedelta
    from sqlalchemy import select
    db = SessionLocal(); set_rls_context(db, bypass=True)
    row = db.scalar(select(Invitation).where(Invitation.email == staff.email))
    row.token_hash = hash_token("known-invite-token-for-tests-1234567890")
    db.commit(); db.close()
    r = staff.post("/invitations/accept", json={"token": "known-invite-token-for-tests-1234567890"})
    assert r.status_code == 200, r.text
    assert staff.get("/locations").status_code == 200
    assert staff.post("/locations", json={"name": "Staff Made"}).status_code == 403
    assert staff.patch("/tenant", json={"name": "Renamed"}).status_code == 403
    assert staff.post("/staff/invitations", json={"email": "z@example.com"}).status_code == 403


def test_invitation_for_other_email_rejected(biz_a):
    other = make_user()
    biz_a.post("/staff/invitations", json={"email": "someone-else@example.com", "role": "staff"})
    from app.core.db import SessionLocal, set_rls_context
    from app.core.security import hash_token
    from app.models import Invitation
    from sqlalchemy import select
    db = SessionLocal(); set_rls_context(db, bypass=True)
    row = db.scalar(select(Invitation).where(Invitation.email == "someone-else@example.com"))
    row.token_hash = hash_token("another-known-token-abcdefghijklmnop")
    db.commit(); db.close()
    assert other.post("/invitations/accept", json={"token": "another-known-token-abcdefghijklmnop"}).status_code == 400


def test_last_owner_cannot_be_removed(biz_a):
    me = biz_a.get("/auth/me").json()["user"]["id"]
    assert biz_a.delete(f"/staff/{me}").status_code == 400
    assert biz_a.patch(f"/staff/{me}", json={"role": "staff"}).status_code == 400


# ---------------- PostgreSQL Row-Level Security (defence in depth) ----------------

def test_rls_blocks_cross_tenant_rows_even_with_raw_sql(biz_a, biz_b):
    """Connect as the real (non-superuser) app role and bypass the application layer entirely."""
    eng = create_engine(settings.database_url)
    with eng.begin() as c:
        assert c.execute(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")).scalar() is False
        # default deny: no context => no rows
        assert c.execute(text("SELECT count(*) FROM locations")).scalar() == 0
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": biz_a.tenant_id})
        rows = c.execute(text("SELECT DISTINCT tenant_id::text FROM locations")).scalars().all()
        assert rows == [biz_a.tenant_id]
        # writing a row for another tenant is rejected by WITH CHECK
        with pytest.raises(Exception):
            c.execute(text("INSERT INTO locations (id, tenant_id, name, review_url_source, is_active, created_at, updated_at) "
                           "VALUES (gen_random_uuid(), :t, 'x', 'manual', true, now(), now())"), {"t": biz_b.tenant_id})


def test_audit_logs_are_append_only_for_app_role(biz_a):
    eng = create_engine(settings.database_url)
    with eng.connect() as c:
        with pytest.raises(Exception):
            c.execute(text("SELECT set_config('app.bypass_rls','on',false)"))
            c.execute(text("DELETE FROM audit_logs"))


def test_invitation_response_admits_undelivered_email(biz_a, monkeypatch):
    monkeypatch.setattr("app.api.v1.tenants.send_email", lambda *a, **k: False)
    r = biz_a.post("/staff/invitations", json={"email": "undelivered@example.com"})
    assert r.status_code == 201 and r.json()["email_sent"] is False
    monkeypatch.setattr("app.api.v1.auth.send_email", lambda *a, **k: False)
    s = make_user(verify=False)
    r = s.post("/auth/resend-verification")
    assert r.status_code == 202 and r.json()["email_sent"] is False
