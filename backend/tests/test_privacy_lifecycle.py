"""Privacy and account lifecycle (docs/PRIVACY_COMPLIANCE_AUDIT.md): the 18+ declaration, deleting one's OWN account, the three lifecycle emails, provisional retention, and the AI safeguard.
Everything runs against real PostgreSQL through the real API. Google (OIDC, revocation) and the AI provider are test doubles; no email leaves the machine (the test outbox)."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.models import Review, Tenant
from app.models.base import utcnow
from app.services import account as svc
from app.services import registration, retention
from app.services.ai import privacy
from app.services.ai.base import AIUnavailable
from app.services.mailer import OUTBOX
from tests.conftest import Session, latest_token, make_business, make_user, owner_exec, owner_query
from tests.test_google_sign_in import begin, finish, google, landing  # noqa: F401  (the Google test double and its helpers)
from tests.test_location_permissions import invite

PW = "Str0ngPassw0rd!"
UTC = timezone.utc


def mails(to: str, subject_part: str) -> list[dict]:
    return [m for m in OUTBOX if m["to"] == to and subject_part in m["subject"]]


def user_id(email: str) -> uuid.UUID:
    return owner_query("SELECT id FROM users WHERE email = :e", e=email)[0][0]


# ================================================================================================================================== A. age declaration
def test_registration_is_refused_on_the_server_without_the_age_declaration(client):
    email = f"age-{uuid.uuid4().hex[:8]}@example.com"
    for extra in ({}, {"age_confirmed": False}):
        r = client.post("/api/v1/auth/register", json={"email": email, "password": PW, "full_name": "Age Test", **extra})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "age_declaration_required"
    assert owner_query("SELECT count(*) FROM users WHERE email = :e", e=email)[0][0] == 0  # nothing was created
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PW, "full_name": "Age Test", "age_confirmed": True})
    assert r.status_code == 201
    at, ver = owner_query("SELECT age_confirmed_at, age_declaration_version FROM users WHERE email = :e", e=email)[0]
    assert at is not None and ver == registration.AGE_DECLARATION_VERSION
    meta = owner_query("SELECT metadata FROM audit_logs WHERE action = 'auth.register' AND user_id = :u", u=user_id(email))[0][0]
    assert meta["age_declared"] is True and "birth" not in json.dumps(meta).lower()


def test_no_date_of_birth_is_stored_and_existing_users_keep_an_unknown_age_status():
    cols = {c for (c,) in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")}
    assert not {c for c in cols if "birth" in c or c in ("dob", "age")}  # a declaration and a timestamp, never a date of birth
    legacy = make_user()
    owner_exec("UPDATE users SET age_confirmed_at = NULL, age_declaration_version = NULL WHERE email = :e", e=legacy.email)
    assert legacy.http.post("/api/v1/auth/login", json={"email": legacy.email, "password": PW}).status_code == 200
    assert owner_query("SELECT age_confirmed_at FROM users WHERE email = :e", e=legacy.email) == [(None,)]  # logging in never "confirms" anyone


def test_a_brand_new_google_account_needs_the_declaration_but_existing_ones_do_not(google):  # noqa: F811
    email = f"g-age-{uuid.uuid4().hex[:8]}@example.com"
    google.claims = {"email": email, "sub": "g-age-" + uuid.uuid4().hex[:8]}
    s, state, _ = begin(google, age=False)
    path, q = landing(finish(s, state))
    assert path == "/login" and q["google_error"] == "age_required"
    assert owner_query("SELECT count(*) FROM users WHERE email = :e", e=email)[0][0] == 0
    s, state, _ = begin(google, age=True)
    path, _ = landing(finish(s, state))
    assert path == "/onboarding"
    at, ver = owner_query("SELECT age_confirmed_at, age_declaration_version FROM users WHERE email = :e", e=email)[0]
    assert at is not None and ver == registration.AGE_DECLARATION_VERSION
    s, state, _ = begin(google, age=False)  # returning user, no declaration in the request: signs in as usual
    assert landing(finish(s, state))[0] == "/overview"


# ================================================================================================================================== B. deleting my own account
def ask(s: Session, **over):
    return s.post("/account/me/deletion", json={"confirm_email": s.email, "password": PW, **over})


def two_businesses():
    """X owns A together with a co-owner, and is staff in B. Returns (x, a_owner_session_is_x, co_owner_email, b)."""
    x = make_business("Shared Physio")
    co = invite(x)
    assert x.patch(f"/staff/{user_id(co.email)}", json={"role": "owner"}).status_code == 204
    b = make_business("Other Dental")
    assert b.post("/staff/invitations", json={"email": x.email, "role": "staff"}).status_code == 201
    assert x.post("/invitations/accept", json={"token": latest_token(x.email, "accept-invite")}).status_code == 200
    return x, co, b


def due_now(email: str):
    owner_exec("UPDATE users SET deletion_scheduled_for = now() - interval '1 minute' WHERE email = :e", e=email)


def test_the_full_flow_for_a_person_in_two_businesses(client):
    x, co, b = two_businesses()
    email = x.email
    uid = user_id(email)
    assert x.get("/account/me/deletion").json()["state"] == "none"
    # explicit confirmation + re-authentication
    assert ask(x, confirm_email="someone@else.example").status_code == 422
    r = ask(x, password="wrong-Password1")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "reauth_required"
    assert mails(email, "Confirm deleting") == []
    # request -> one email with one link, state awaiting; a retry creates and sends nothing more
    r = ask(x)
    assert r.status_code == 200 and r.json()["state"] == "awaiting_confirmation"
    assert len(mails(email, "Confirm deleting")) == 1
    assert ask(x).json()["state"] == "awaiting_confirmation" and len(mails(email, "Confirm deleting")) == 1
    body = mails(email, "Confirm deleting")[0]["body"]
    assert "confirm-account-deletion?token=" in body and PW not in body and email not in body  # the link only: no password, no address
    token = latest_token(email, "confirm-account-deletion")
    # the link is checked, expires, and works once
    assert client.post("/api/v1/account/me/deletion/confirm", json={"token": "x" * 43}).status_code == 400
    bad = client.post("/api/v1/account/me/deletion/confirm", json={"token": "y" * 43}).json()
    assert client.post("/api/v1/account/me/deletion/confirm", json={"token": token}).status_code == 204
    again = client.post("/api/v1/account/me/deletion/confirm", json={"token": token})
    assert again.status_code == 400 and again.json() == bad  # a used link answers exactly like a made-up one: nothing to learn
    # confirming signs the person out everywhere, and schedules (not performs) the deletion
    assert x.get("/auth/me").status_code == 401
    assert owner_query("SELECT deletion_scheduled_for IS NOT NULL, deleted_at IS NULL, deletion_token_hash IS NULL FROM users WHERE id = :u", u=uid) == [(True, True, True)]
    x.csrf = x.http.post("/api/v1/auth/login", json={"email": email, "password": PW}).json()["csrf_token"]  # still allowed to sign in during the grace period
    assert x.get("/account/me/deletion").json()["state"] == "scheduled"
    # cancelling restores everything
    assert x.delete("/account/me/deletion").json()["state"] == "none"
    assert owner_query("SELECT deletion_requested_at, deletion_scheduled_for FROM users WHERE id = :u", u=uid) == [(None, None)]
    # ask again, confirm, and let the grace period pass
    ask(x)
    assert client.post("/api/v1/account/me/deletion/confirm", json={"token": latest_token(email, "confirm-account-deletion")}).status_code == 204
    owner_exec("INSERT INTO audit_logs (id, user_id, action, ip, created_at, metadata) VALUES (gen_random_uuid(), :u, 'test.keep_entry', '203.0.113.7', now(), '{}'::jsonb)", u=uid)
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        assert svc.delete_user(db, uid)["reason"] == "not_due"  # never early
    due_now(email)
    from app.workers.tasks import purge_deleted_accounts
    out = purge_deleted_accounts.run()
    assert out["people_deleted"] >= 1
    # tombstone: no name, email, phone, password or Google id; nothing that identifies the person
    row = owner_query("SELECT email, full_name, phone, password_hash, google_sub, is_active, deleted_at FROM users WHERE id = :u", u=uid)[0]
    assert row[0] == f"deleted-{uid}@deleted.invalid" and row[1] == "Deleted user" and row[2] is None and row[3] is None and row[4] is None and row[5] is False and row[6] is not None
    # memberships, sessions and tokens gone; BOTH businesses and the co-owner untouched
    assert owner_query("SELECT count(*) FROM memberships WHERE user_id = :u", u=uid)[0][0] == 0
    assert owner_query("SELECT count(*) FROM auth_sessions WHERE user_id = :u", u=uid)[0][0] == 0
    assert owner_query("SELECT count(*) FROM tenants WHERE id = ANY(:t)", t=[uuid.UUID(x.tenant_id), uuid.UUID(b.tenant_id)])[0][0] == 2
    assert owner_query("SELECT role::text FROM memberships WHERE tenant_id = :t AND user_id = :u", t=x.tenant_id, u=user_id(co.email)) == [("owner",)]
    assert owner_query("SELECT count(*) FROM invitations WHERE email = :e", e=email)[0][0] == 0
    # the IP is removed from their audit entries; the entries stay
    assert owner_query("SELECT ip, action FROM audit_logs WHERE user_id = :u AND action = 'test.keep_entry'", u=uid) == [(None, "test.keep_entry")]
    assert owner_query("SELECT count(*) FROM audit_logs WHERE user_id = :u AND ip IS NOT NULL", u=uid)[0][0] == 0
    rec = owner_query("SELECT metadata FROM audit_logs WHERE action = 'account.user_deleted' AND user_id = :u", u=uid)[0][0]
    assert rec["memberships_removed"] == 2 and email not in json.dumps(rec)  # counts only
    # told once, at the old address, after it was done; the status and the completion time are recorded
    assert len(mails(email, "has been deleted")) == 1
    assert "Deleted user" not in mails(email, "has been deleted")[0]["body"]
    # idempotent: running everything again changes nothing and sends nothing
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        assert svc.delete_user(db, uid) == {"deleted": False, "reason": "already_deleted"}
    assert purge_deleted_accounts.run()["people_deleted"] == 0 and len(mails(email, "has been deleted")) == 1
    # the old sign-in is gone, a reset request reveals nothing, and the address can be used again
    assert Session(None, email).http.post("/api/v1/auth/login", json={"email": email, "password": PW}).status_code == 401
    assert Session(None, email).http.post("/api/v1/auth/password-reset/request", json={"email": email}).status_code == 202
    assert [m for m in OUTBOX if m["to"] == email and "Reset your" in m["subject"]] == []
    assert client.post("/api/v1/auth/register", json={"email": email, "password": PW, "full_name": "Back Again", "age_confirmed": True}).status_code == 201


def test_the_only_owner_of_a_business_cannot_delete_their_account(biz_a):
    r = ask(biz_a)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sole_owner" and r.json()["detail"]["businesses"] == ["Alpha Physio"]
    assert mails(biz_a.email, "Confirm deleting") == []
    st = biz_a.get("/account/me/deletion").json()
    assert st["state"] == "none" and st["blocked_by"] == ["Alpha Physio"]
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=biz_a.tenant_id)[0][0] == 1  # and no business was deleted


def test_a_business_is_never_left_without_an_owner_even_if_things_change_during_the_grace_period(client):
    x, co, b = two_businesses()
    ask(x)
    client.post("/api/v1/account/me/deletion/confirm", json={"token": latest_token(x.email, "confirm-account-deletion")})
    owner_exec("DELETE FROM memberships WHERE tenant_id = :t AND user_id = :u", t=x.tenant_id, u=user_id(co.email))  # the co-owner left: x is now the only owner
    due_now(x.email)
    from app.workers.tasks import purge_deleted_accounts
    assert purge_deleted_accounts.run()["people_deleted"] == 0
    assert owner_query("SELECT is_active, deleted_at, deletion_scheduled_for FROM users WHERE email = :e", e=x.email) == [(True, None, None)]  # still themselves, request cancelled
    assert owner_query("SELECT count(*) FROM memberships WHERE tenant_id = :t AND role = 'owner'", t=x.tenant_id)[0][0] == 1
    assert len(mails(x.email, "was not deleted")) == 1


def test_a_platform_administrator_cannot_delete_their_account_here(admin):
    r = ask(admin)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "platform_admin"


def test_the_link_expires(client):
    x, co, b = two_businesses()
    assert ask(x, password=None).status_code == 403  # a password account must give its password
    ask(x)
    token = latest_token(x.email, "confirm-account-deletion")
    owner_exec("UPDATE users SET deletion_token_expires_at = now() - interval '1 second' WHERE email = :e", e=x.email)
    assert x.get("/account/me/deletion").json()["state"] == "none"
    r = client.post("/api/v1/account/me/deletion/confirm", json={"token": token})
    assert r.status_code == 400
    assert owner_query("SELECT deletion_scheduled_for FROM users WHERE email = :e", e=x.email) == [(None,)]


def test_a_google_only_account_must_have_signed_in_recently(google):  # noqa: F811
    email = f"g-del-{uuid.uuid4().hex[:8]}@example.com"
    google.claims = {"email": email, "sub": "g-del-" + uuid.uuid4().hex[:8]}
    s, state, _ = begin(google, age=True)
    assert landing(finish(s, state))[0] == "/onboarding"
    s.email = email
    s.csrf = s.get("/auth/me").json()["csrf_token"]
    owner_exec("UPDATE auth_sessions SET created_at = now() - interval '2 hours' WHERE user_id = :u", u=user_id(email))
    r = s.post("/account/me/deletion", json={"confirm_email": email})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "reauth_required"
    owner_exec("UPDATE auth_sessions SET created_at = now() WHERE user_id = :u", u=user_id(email))
    assert s.post("/account/me/deletion", json={"confirm_email": email}).json()["state"] == "awaiting_confirmation"


def test_queued_posts_and_google_connections_of_the_person_are_handled(biz_a, client):
    from app.models import GoogleConnection, GoogleConnectionStatus, GoogleLocation, ScheduledPost
    from app.services.google.tokens import store_tokens
    x = biz_a
    co = invite(x)
    assert x.patch(f"/staff/{user_id(co.email)}", json={"role": "owner"}).status_code == 204
    uid = user_id(x.email)
    tid = uuid.UUID(x.tenant_id)
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        c = GoogleConnection(tenant_id=tid, connected_by=uid, google_email="x@example.com", status=GoogleConnectionStatus.active)
        db.add(c); db.flush()
        store_tokens(c, refresh_token="1//rt-x", access_token="ya29.x", expires_in=3600)
        gl = GoogleLocation(tenant_id=tid, connection_id=c.id, google_location_name="locations/1", google_account_name="accounts/1", title="X", selected=True)
        db.add(gl); db.flush()
        db.add(ScheduledPost(tenant_id=tid, google_location_id=gl.id, summary="queued", status="scheduled", scheduled_for=utcnow() + timedelta(days=1), created_by=uid))
        db.add(ScheduledPost(tenant_id=tid, google_location_id=gl.id, summary="theirs but a draft", status="draft", created_by=uid))
        db.commit()
    ask(x)
    client.post("/api/v1/account/me/deletion/confirm", json={"token": latest_token(x.email, "confirm-account-deletion")})
    due_now(x.email)

    class Revoker:
        calls = []

        def revoke(self, token):
            self.calls.append(token)

    rv = Revoker()
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        assert svc.delete_user(db, uid, provider=rv)["deleted"] is True
    assert rv.calls == ["1//rt-x"]
    assert owner_query("SELECT status::text, refresh_token_encrypted IS NULL FROM google_connections WHERE tenant_id = :t", t=x.tenant_id) == [("disconnected", True)]
    assert dict(owner_query("SELECT summary, status FROM scheduled_posts WHERE tenant_id = :t", t=x.tenant_id)) == {"queued": "canceled", "theirs but a draft": "draft"}


def test_deletion_and_confirmation_are_rate_limited(client):
    x, co, b = two_businesses()
    codes = [ask(x, confirm_email="nobody@example.com").status_code for _ in range(6)]
    assert codes[:5] == [422] * 5 and codes[5] == 429
    codes = [client.post("/api/v1/account/me/deletion/confirm", json={"token": "z" * 43}).status_code for _ in range(11)]
    assert codes[-1] == 429


def test_business_deletion_requests_are_rate_limited_so_the_password_cannot_be_guessed(biz_a):
    codes = [biz_a.post("/account/deletion", json={"confirm_name": "Alpha Physio", "password": f"wrong-Password{i}"}).status_code for i in range(6)]
    assert codes[:5] == [403] * 5 and codes[5] == 429


def test_anonymous_callers_cannot_use_the_personal_deletion_endpoints(client):
    assert client.get("/api/v1/account/me/deletion").status_code == 401
    assert client.post("/api/v1/account/me/deletion", json={"confirm_email": "a@b.co"}).status_code in (401, 403)
    assert client.delete("/api/v1/account/me/deletion").status_code in (401, 403)


# ================================================================================================================================== C. emails
def test_an_export_sends_one_notice_that_contains_none_of_the_data(biz_a):
    r = biz_a.get("/account/export")
    assert r.status_code == 200
    sent = mails(biz_a.email, "data export was downloaded")
    assert len(sent) == 1
    body = sent[0]["body"]
    assert "Alpha Physio" in body and "does not contain any of that data" in body
    for leak in (".json", "review", "token=", "http", "@"):  # no data, no link, no address
        assert leak not in body.lower(), leak
    assert biz_a.get("/account/export").status_code == 200  # a second download inside ten minutes is not announced twice
    assert len(mails(biz_a.email, "data export was downloaded")) == 1
    metas = [m for (m,) in owner_query("SELECT metadata FROM audit_logs WHERE tenant_id = :t AND action = 'email.sent'", t=biz_a.tenant_id)]
    assert metas == [{"kind": "export_downloaded"}]  # the outcome only: no address, no text, no link


def test_business_deletion_sends_a_request_notice_once_and_a_completion_notice_once(biz_a):
    assert biz_a.post("/account/deletion", json={"confirm_name": "Alpha Physio", "password": PW}).status_code == 200
    assert len(mails(biz_a.email, "received your request to delete")) == 1
    assert biz_a.post("/account/deletion", json={"confirm_name": "Alpha Physio", "password": PW}).status_code == 200
    assert len(mails(biz_a.email, "received your request to delete")) == 1  # the repeat is not announced again
    owner_exec("UPDATE tenants SET deletion_scheduled_for = now() - interval '1 minute' WHERE id = :t", t=biz_a.tenant_id)
    from app.workers.tasks import purge_deleted_accounts
    purge_deleted_accounts.run()
    done = mails(biz_a.email, "has been deleted")
    assert len(done) == 1 and "Alpha Physio" in done[0]["body"]
    purge_deleted_accounts.run()
    assert len(mails(biz_a.email, "has been deleted")) == 1


def test_a_failed_email_is_recorded_without_its_contents_and_does_not_undo_the_deletion(monkeypatch):
    x, co, b = two_businesses()
    monkeypatch.setattr("app.services.account_mail.send_email", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp down: secret-in-error")))
    assert ask(x).status_code == 200  # the request still succeeds; the person can ask again for a new link after ten minutes
    failed = owner_query("SELECT metadata FROM audit_logs WHERE action = 'email.failed' AND user_id = :u", u=user_id(x.email))
    assert failed == [({"kind": "deletion_requested"},)] and "secret-in-error" not in str(failed)


# ================================================================================================================================== D. retention
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture()
def retention_on(monkeypatch):
    for k, v in (("privacy_retention_enabled", True), ("session_retention_days", 30), ("password_reset_token_retention_days", 30), ("audit_ip_retention_days", 365), ("lead_retention_days", 365)):
        monkeypatch.setattr(settings, k, v)


def session_row(uid, *, expires: str, revoked: str | None = None) -> uuid.UUID:
    sid = uuid.uuid4()
    owner_exec("INSERT INTO auth_sessions (id, user_id, token_hash, csrf_token, ip, user_agent, created_at, expires_at, revoked_at) "
               "VALUES (:i, :u, :h, 'c', '198.51.100.9', 'ua', timestamptz '2026-01-01 00:00:00+00', CAST(:e AS timestamptz), CAST(:r AS timestamptz))",
               i=sid, u=uid, h=uuid.uuid4().hex, e=expires, r=revoked)
    return sid


def exists(table: str, rid) -> bool:
    return owner_query(f"SELECT count(*) FROM {table} WHERE id = :i", i=rid)[0][0] == 1


def run_retention(now=NOW, dry_run=False):
    with SessionLocal() as db:
        set_rls_context(db, bypass=True)
        return retention.run(db, now=now, dry_run=dry_run)


def test_ended_sessions_expire_30_days_after_they_ended_with_an_exact_boundary_in_any_timezone(retention_on):
    u = user_id(make_user().email)
    # NOW - 30 days = 2026-05-16 12:00 UTC = 17:30 at +05:30. A row that ended exactly then is KEPT; one second earlier goes.
    exact = session_row(u, expires="2026-05-16 17:30:00+05:30")
    older = session_row(u, expires="2026-05-16 17:29:59+05:30")
    newer = session_row(u, expires="2026-05-17 00:00:00+00")
    signed_out_long_ago = session_row(u, expires="2026-12-31 00:00:00+00", revoked="2026-05-01 00:00:00+00")  # revoked early, would have expired later: the sign-out is when it ended
    revoked_recently = session_row(u, expires="2026-12-31 00:00:00+00", revoked="2026-06-10 00:00:00+00")
    still_active = session_row(u, expires="2026-12-31 00:00:00+00")
    out = run_retention()
    assert out["enabled"] and out["errors"] == [] and out["counts"]["ended_sessions"] >= 2
    assert not exists("auth_sessions", older) and not exists("auth_sessions", signed_out_long_ago)
    for keep in (exact, newer, revoked_recently, still_active):
        assert exists("auth_sessions", keep)


def test_password_reset_tokens_go_30_days_after_creation_used_or_not(retention_on):
    u = user_id(make_user().email)
    ids = {}
    for name, created in (("old_unused", "2026-05-15 12:00:00+00"), ("old_used", "2026-05-01 00:00:00+00"), ("boundary", "2026-05-16 12:00:00+00"), ("recent", "2026-06-10 00:00:00+00")):
        ids[name] = uuid.uuid4()
        owner_exec("INSERT INTO password_reset_tokens (id, user_id, token_hash, created_at, expires_at, used_at) VALUES (:i, :u, :h, CAST(:c AS timestamptz), CAST(:c AS timestamptz) + interval '1 hour', "
                   "CASE WHEN :n = 'old_used' THEN CAST(:c AS timestamptz) END)", i=ids[name], u=u, h=uuid.uuid4().hex, c=created, n=name)
    run_retention()
    assert not exists("password_reset_tokens", ids["old_unused"]) and not exists("password_reset_tokens", ids["old_used"])
    assert exists("password_reset_tokens", ids["boundary"]) and exists("password_reset_tokens", ids["recent"])


def audit_row(uid, created: str) -> uuid.UUID:
    rid = uuid.uuid4()
    owner_exec("INSERT INTO audit_logs (id, user_id, action, entity_type, ip, created_at, metadata) VALUES (:i, :u, 'test.ip', 'x', '192.0.2.1', CAST(:c AS timestamptz), '{\"k\": 1}'::jsonb)", i=rid, u=uid, c=created)
    return rid


def test_audit_ip_addresses_are_removed_after_12_months_and_the_entry_stays(retention_on):
    u = user_id(make_user().email)
    old, boundary, recent = audit_row(u, "2025-06-14 12:00:00+00"), audit_row(u, "2025-06-15 12:00:00+00"), audit_row(u, "2026-06-01 00:00:00+00")
    run_retention()
    assert owner_query("SELECT ip, action, metadata FROM audit_logs WHERE id = :i", i=old) == [(None, "test.ip", {"k": 1})]  # the IP only
    assert owner_query("SELECT ip FROM audit_logs WHERE id = :i", i=boundary) == [("192.0.2.1",)]  # exactly 365 days old: kept
    assert owner_query("SELECT ip FROM audit_logs WHERE id = :i", i=recent) == [("192.0.2.1",)]


def test_the_database_lets_only_the_ip_of_an_audit_entry_be_removed(biz_a):
    rid = audit_row(user_id(biz_a.email), "2026-06-01 00:00:00+00")
    with SessionLocal() as db:  # the application role
        set_rls_context(db, bypass=True)
        for sql in ("UPDATE audit_logs SET action = 'tampered' WHERE id = :i", "UPDATE audit_logs SET metadata = '{}'::jsonb WHERE id = :i", "DELETE FROM audit_logs WHERE id = :i"):
            with pytest.raises(Exception):
                db.execute(text(sql), {"i": rid})
            db.rollback()
        assert db.execute(text("UPDATE audit_logs SET ip = NULL WHERE id = :i"), {"i": rid}).rowcount == 1
        db.commit()
    for sql in ("UPDATE audit_logs SET action = 'tampered' WHERE id = :i", "UPDATE audit_logs SET ip = '10.0.0.1' WHERE id = :i"):  # even the table owner: the trigger refuses
        with pytest.raises(Exception):
            owner_exec(sql, i=rid)
    assert owner_query("SELECT action, ip FROM audit_logs WHERE id = :i", i=rid) == [("test.ip", None)]


def lead_row(created: str) -> uuid.UUID:
    lid = uuid.uuid4()
    owner_exec("INSERT INTO leads (id, name, business_name, city, business_type, locations, phone, whatsapp_ok, source, created_at) "
               "VALUES (:i, 'L', 'B', 'C', 'clinic', 1, '+919876543210', false, 'demo', CAST(:c AS timestamptz))", i=lid, c=created)
    return lid


def test_demo_leads_are_deleted_after_12_months(retention_on):
    old, boundary, recent = lead_row("2025-06-14 11:59:59+00"), lead_row("2025-06-15 12:00:00+00"), lead_row("2026-06-01 00:00:00+00")
    run_retention()
    assert not exists("leads", old) and exists("leads", boundary) and exists("leads", recent)


def test_retention_is_repeatable_and_a_second_run_finds_nothing(retention_on):
    u = user_id(make_user().email)
    session_row(u, expires="2026-04-01 00:00:00+00")
    lead_row("2024-01-01 00:00:00+00")
    first = run_retention()
    assert first["counts"]["ended_sessions"] >= 1 and first["counts"]["leads"] >= 1
    second = run_retention()
    assert second["counts"] == {"ended_sessions": 0, "reset_tokens": 0, "audit_ips": 0, "leads": 0} and second["errors"] == []


def test_retention_does_nothing_unless_switched_on_and_a_dry_run_only_counts(monkeypatch):
    u = user_id(make_user().email)
    sid = session_row(u, expires="2026-04-01 00:00:00+00")
    monkeypatch.setattr(settings, "privacy_retention_enabled", False)
    assert run_retention() == {"enabled": False, "dry_run": False, "counts": {}, "errors": []}
    assert exists("auth_sessions", sid)
    out = run_retention(dry_run=True)  # the report works even while the job is off, and deletes nothing
    assert out["dry_run"] and out["counts"]["ended_sessions"] >= 1 and exists("auth_sessions", sid)
    from app.workers.tasks import privacy_retention
    assert privacy_retention.run()["enabled"] is False  # the scheduled task is the same no-op


def test_a_period_of_zero_keeps_the_data(retention_on, monkeypatch):
    monkeypatch.setattr(settings, "session_retention_days", 0)
    monkeypatch.setattr(settings, "lead_retention_days", 0)
    u = user_id(make_user().email)
    sid, lid = session_row(u, expires="2020-01-01 00:00:00+00"), lead_row("2020-01-01 00:00:00+00")
    run_retention()
    assert exists("auth_sessions", sid) and exists("leads", lid)


def test_one_failing_step_is_reported_and_does_not_stop_the_others(retention_on, monkeypatch):
    def broken(db, now, dry_run):
        db.execute(text("SELECT 1/0"))  # a real database error inside the transaction

    u = user_id(make_user().email)
    lid = lead_row("2020-01-01 00:00:00+00")
    monkeypatch.setattr(retention, "STEPS", (("ended_sessions", broken), ("leads", retention.old_leads)))
    out = run_retention()
    assert out["errors"] == ["ended_sessions"] and out["counts"]["leads"] >= 1 and not exists("leads", lid)
    meta = owner_query("SELECT metadata FROM audit_logs WHERE action = 'retention.privacy_run' ORDER BY created_at DESC LIMIT 1")[0][0]
    assert meta["errors"] == ["ended_sessions"] and meta["provisional"] is True and set(meta) == {"counts", "errors", "provisional", "days"}  # counts, never content


def test_the_retention_job_is_scheduled_once_on_the_existing_beat_and_the_periods_are_the_approved_ones():
    from app.workers.celery_app import celery_app
    assert celery_app.conf.beat_schedule["privacy-retention"]["task"] == "flowqr.privacy_retention"
    assert sorted(t for t in celery_app.conf.beat_schedule if "retention" in t) == ["autonomy-retention", "google-content-retention", "privacy-retention"]  # 0064 adds the Google-content job (off unless GOOGLE_CONTENT_RETENTION_ENABLED)
    from app.core.config import Settings
    s = Settings()
    assert (s.session_retention_days, s.password_reset_token_retention_days, s.audit_ip_retention_days, s.lead_retention_days, s.privacy_retention_enabled) == (30, 30, 365, 365, False)


# ================================================================================================================================== E/3. the AI safeguard
class Prov:
    def __init__(self, name="gemini", reply="Thank you for the kind words about the care you received."):
        self.name, self.model, self.prompts, self.reply = name, "m", [], reply
        self.usage = None

    def generate(self, system, user, **kw):
        self.prompts.append(user)
        return self.reply


def review(text_="Great physio, call me on +91 98765 43210 or priya.sharma@example.com", name="Priya Sharma"):
    return Review(text=text_, rating=5, reviewer_name=name)


def tenant():
    return Tenant(name="Clinic", category="Physiotherapy clinic", language="en")


def test_review_data_is_not_sent_to_gemini_unless_the_owner_has_confirmed_its_terms(monkeypatch):
    from app.services.ai.replies import draft_reply
    p = Prov("gemini")
    assert (settings.gemini_data_terms_verified, settings.ai_review_data_kill_switch) == (False, False)  # the defaults
    with pytest.raises(AIUnavailable) as e:
        draft_reply(p, review(), tenant(), "Main")
    assert e.value.code == "data_terms_unverified" and p.prompts == []  # failed BEFORE any prompt existed: nothing was sent
    monkeypatch.setattr(settings, "gemini_data_terms_verified", True)
    out, lang, reasons = draft_reply(p, review(), tenant(), "Main")
    assert out and len(p.prompts) >= 1


def test_the_kill_switch_stops_review_data_going_to_any_provider(monkeypatch):
    from app.services.ai.replies import draft_reply
    monkeypatch.setattr(settings, "gemini_data_terms_verified", True)
    monkeypatch.setattr(settings, "ai_review_data_kill_switch", True)
    for name in ("gemini", "openrouter", "fake"):
        p = Prov(name)
        with pytest.raises(AIUnavailable) as e:
            draft_reply(p, review(), tenant(), "Main")
        assert e.value.code == "kill_switch" and p.prompts == []


def test_other_providers_are_not_covered_by_the_gemini_rule_and_business_only_ai_is_untouched():
    from app.services.ai.replies import draft_reply
    p = Prov("fake")
    assert draft_reply(p, review(), tenant(), "Main")[0] and p.prompts  # not Gemini: the Gemini rule does not apply
    assert privacy.block_reason("gemini") == "data_terms_unverified" and privacy.block_reason("fake") is None


def test_the_reviewers_name_is_never_sent_and_obvious_identifiers_are_masked(monkeypatch):
    from app.services.ai.replies import build_prompt, draft_reply
    monkeypatch.setattr(settings, "gemini_data_terms_verified", True)
    p = Prov("gemini")
    draft_reply(p, review(), tenant(), "Main")
    for prompt in p.prompts:
        assert "Priya" not in prompt and "Sharma" not in prompt and "Reviewer name" not in prompt
        assert "98765" not in prompt and "priya.sharma@example.com" not in prompt
        assert "[phone number]" in prompt and "[email address]" in prompt
    assert "Priya" not in build_prompt(review(), tenant(), "Main", None, tone=None, lang="en", recent=None, intel=None)


def test_redaction_masks_contact_details_and_leaves_dates_and_prices_alone():
    r = privacy.redact
    assert r("mail me: a.b+c@x-y.co.in") == "mail me: [email address]"
    assert r("ph 98765 43210 / +91-98765-43210 / (0522) 4012345") == "ph [phone number] / [phone number] / [phone number]"
    assert r("see https://x.example/a?b=1 and www.y.example") == "see [link] and [link]"
    assert r("visited on 12-05-2024 and paid Rs 1,200") == "visited on 12-05-2024 and paid Rs 1,200"
    assert r(None) == "" and r("") == ""


def test_customer_words_and_the_risk_check_are_gated_and_masked_too(monkeypatch):
    from app.services.ai.review_assist import improve_review
    from app.services.ai.risk import review_risk
    p = Prov("gemini", reply="I liked the care and the staff.")
    with pytest.raises(AIUnavailable):
        improve_review(p, "liked the staff, call 9876543210", language="en", business_name="Clinic", category=None)
    assert p.prompts == []
    monkeypatch.setattr(settings, "ai_review_risk_check", True)
    r = review_risk(p, "terrible wait, email me at a@b.co", 2, "Physiotherapy clinic")
    assert p.prompts == [] and r.ai_failed is True and r.ai_checked is False and r.level in ("medium", "high")  # unchecked, so MORE cautious, never less
    monkeypatch.setattr(settings, "gemini_data_terms_verified", True)
    improve_review(p, "liked the staff, call 9876543210", language="en", business_name="Clinic", category=None)
    assert "9876543210" not in p.prompts[0] and "[phone number]" in p.prompts[0]


def test_the_review_generator_is_gated_and_masks_the_customers_words(monkeypatch):
    from app.services.ai.review_generate import STYLES, ReviewInput, generate_review
    STYLE = next(iter(STYLES))
    inp = ReviewInput(rating=5, note="the doctor was kind, my number is 9876543210", topics=("Staff",), sentiment="good")
    p = Prov("gemini")
    with pytest.raises(AIUnavailable):
        generate_review(p, inp, language="en", style=STYLE, business_name="Clinic")
    assert p.prompts == []
    from app.services.ai import review_generate as rg
    assert "9876543210" not in rg._answers_block(inp) and "[phone number]" in rg._answers_block(inp)


def test_customers_are_not_offered_ai_help_while_it_is_blocked_and_owners_are_told_why(biz_a, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "k-test")  # configured, so only the safeguard decides
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    assert settings.ai_configured and privacy.blocked_now() == "data_terms_unverified"
    ai = biz_a.get("/review-growth/settings").json()["ai"]
    assert ai["review_data_blocked"] == "data_terms_unverified"
    monkeypatch.setattr(settings, "gemini_data_terms_verified", True)
    assert biz_a.get("/review-growth/settings").json()["ai"]["review_data_blocked"] is None
    monkeypatch.setattr(settings, "ai_review_data_kill_switch", True)
    assert biz_a.get("/review-growth/settings").json()["ai"]["review_data_blocked"] == "kill_switch"
