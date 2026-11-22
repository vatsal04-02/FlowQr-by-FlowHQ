"""Agency manager account (services/google/agency.py). EVERY test runs against tests/fake_agency_google.FakeAgencyClient: no test makes a live Google call, and none can.

What is pinned: the flag-off guarantee, consent before anything is sent, the order and tokens of each Google call, the switch only after the agency login can see the location, the client's
token revoked only after the switch, every failure path leaving the connection untouched, duplicate-safe and resumable steps, the separate notice and its overdue alert, stopping, and detecting
that the client removed FlowQR in Google.
"""
import uuid
from contextlib import closing
from datetime import timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import Settings, config_problems, settings
from app.core.db import SessionLocal, set_rls_context, system_session
from app.core.security import TokenCipher, get_cipher
from app.models import (
    GoogleAgencyAccount, GoogleAgencyAuthorization as Auth, GoogleConnection, GoogleConnectionStatus, GoogleLocation, ReplyDraft, ReplyStatus, Review,
)
from app.models.base import utcnow
from app.services import google as g
from app.services.google import agency
from app.services.google import agency_client as ac
from app.services.google.agency_client import AdminEntry
from app.services.google.provider import BUSINESS_SCOPE
from app.services.google.sync import due_locations, sync_google_location
from app.services.google.tokens import get_access_token
from app.services.mailer import OUTBOX
from tests.conftest import make_business, owner_exec, owner_query
from tests.fake_agency_google import AGENCY_ACCESS, AGENCY_REFRESH, CLIENT_ACCESS, CLIENT_REFRESH, FakeAgencyClient

ADMIN_EMAIL = "root@flowhq-admin.example.com"


@pytest.fixture(autouse=True)
def _clean():
    owner_exec("UPDATE google_connections SET auth_mode = 'client_token', agency_account_id = NULL WHERE agency_account_id IS NOT NULL")
    owner_exec("DELETE FROM google_agency_authorizations")
    owner_exec("DELETE FROM google_agency_accounts")
    OUTBOX.clear()  # the outbox is global: without this an earlier test's alert would satisfy (or break) a mail assertion here
    yield
    # and again afterwards, so the LAST test of a module cannot leave an agency-mode connection for a later file (test_migration_0061 asserts there are none)
    owner_exec("UPDATE google_connections SET auth_mode = 'client_token', agency_account_id = NULL WHERE agency_account_id IS NOT NULL")
    owner_exec("DELETE FROM google_agency_authorizations")
    owner_exec("DELETE FROM google_agency_accounts")


@pytest.fixture()
def fake(monkeypatch):
    """Agency switch ON, an agency key, one registered agency login, and the fake standing in for Google."""
    monkeypatch.setattr(settings, "google_agency_manager_enabled", True)
    monkeypatch.setattr(settings, "agency_token_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "google_agency_operations_enabled", True)  # setup: these tests exercise the SWITCHED path; the default (off) stops at "access verified" and is tested in test_google_agency_onboarding.py
    monkeypatch.setattr(settings, "google_agency_individual_fallback", True)  # these tests exercise the documented individual fallback; the group path is tested in test_google_agency_group.py
    f = FakeAgencyClient()
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    monkeypatch.setattr(ac, "get_agency_client", lambda: f)
    agency.register_account("agency-1", code="the-code", provider=f)
    return f


def seed(biz, n=1) -> SimpleNamespace:
    """A business that connected Google the old way: an active connection, the client's own encrypted tokens, n selected locations."""
    with closing(system_session()) as db:
        tid, cipher = uuid.UUID(biz.tenant_id), get_cipher()
        conn = GoogleConnection(tenant_id=tid, google_sub=f"sub-{uuid.uuid4().hex[:8]}", google_email="owner@clinic.example.com", refresh_token_encrypted=cipher.encrypt(CLIENT_REFRESH),
                                access_token_encrypted=cipher.encrypt(CLIENT_ACCESS), access_token_expires_at=utcnow() + timedelta(days=1), scopes=BUSINESS_SCOPE,
                                status=GoogleConnectionStatus.active, connected_at=utcnow(), api_access="approved")
        db.add(conn)
        db.flush()
        glocs = []
        for i in range(n):
            gl = GoogleLocation(tenant_id=tid, connection_id=conn.id, location_id=uuid.UUID(biz.location_id) if i == 0 else None, google_account_name="accounts/111",
                                google_location_name=f"locations/{uuid.uuid4().int % 10**9}", title=f"Clinic {i}", selected=True)
            db.add(gl)
            glocs.append(gl)
        db.commit()
        return SimpleNamespace(conn_id=conn.id, gids=[x.id for x in glocs], names=[x.google_location_name for x in glocs], key=[x.google_location_name.split("/")[-1] for x in glocs])


def consent(biz, s):
    user = SimpleNamespace(id=None, email=biz.email)
    with closing(system_session()) as db:
        agency.record_consent(db, conn=db.get(GoogleConnection, s.conn_id), user=user, agree=True, version=agency.CONSENT_VERSION)


def advance(s, **kw):
    with closing(system_session()) as db:
        return [(a.status, a.failure_code) for a in agency.advance_connection(db, db.get(GoogleConnection, s.conn_id), **kw)]


def go(biz, s, **kw):
    consent(biz, s)
    return advance(s, force=True, **kw)


def conn_of(s) -> GoogleConnection:
    with closing(system_session()) as db:
        c = db.get(GoogleConnection, s.conn_id)
        db.expunge(c)
        return c


def auths_of(s) -> list[Auth]:
    with closing(system_session()) as db:
        rows = list(db.scalars(select(Auth).where(Auth.connection_id == s.conn_id).order_by(Auth.created_at)))
        for r in rows:
            db.expunge(r)
        return rows


def gloc_of(gid) -> GoogleLocation:
    with closing(system_session()) as db:
        x = db.get(GoogleLocation, gid)
        db.expunge(x)
        return x


def calls(fake, name):
    return [c for c in fake.calls if c[0] == name]


def mail(to=None, subject_has=None):
    return [m for m in OUTBOX if (to is None or m["to"] == to) and (subject_has is None or subject_has in m["subject"])]


def untouched(s):
    """The guarantee for every failure before the switch: the connection and the client's token are exactly as they were."""
    c = conn_of(s)
    assert c.auth_mode == "client_token" and c.agency_account_id is None and c.status == GoogleConnectionStatus.active
    assert c.refresh_token_encrypted and get_cipher().decrypt(c.refresh_token_encrypted) == CLIENT_REFRESH
    assert gloc_of(s.gids[0]).google_account_name == "accounts/111"


# ------------------------------------------------------------------ flag off
def test_with_the_switch_off_nothing_changes(monkeypatch):
    f = FakeAgencyClient()
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    monkeypatch.setattr(ac, "get_agency_client", lambda: f)
    assert settings.google_agency_manager_enabled is False  # the default
    biz = make_business("Flag Off Clinic")
    s = seed(biz)
    # the new routes answer exactly as an unknown path would
    assert biz.get("/google/agency/status").status_code == 404
    assert biz.post("/google/agency/consent", json={"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION}).status_code == 404
    assert biz.post(f"/google/agency/connections/{s.conn_id}/advance").status_code == 404
    # the existing status response has no agency field
    assert "auth_mode" not in biz.get("/google/status").text
    # the client's own token still drives everything, and a sync is the same sync
    with closing(system_session()) as db:
        assert get_access_token(db, db.get(GoogleConnection, s.conn_id), f) == CLIENT_ACCESS
        res = sync_google_location(db, db.get(GoogleLocation, s.gids[0]), f, sleep=lambda x: None)
    assert res["status"] == "ok" and calls(f, "list_reviews")[0][2] == CLIENT_ACCESS
    # the periodic task has nothing to do and asks Google for nothing
    with closing(system_session()) as db:
        assert agency.housekeeping(db) == {"advanced": 0, "checked": 0, "revoked": 0, "removed": 0, "notices": 0, "alerts": 0}
    assert not [c for c in f.calls if c[0] != "list_reviews"]
    untouched(s)
    with pytest.raises(agency.AgencyDisabled):
        with closing(system_session()) as db:
            agency.advance_connection(db, db.get(GoogleConnection, s.conn_id))


def test_switching_off_stops_an_agency_connection_without_changing_it(fake, monkeypatch):
    biz = make_business("Kill Switch Clinic")
    s = seed(biz)
    assert go(biz, s) == [("active", None)]
    n = len(fake.calls)
    monkeypatch.setattr(settings, "google_agency_manager_enabled", False)
    with closing(system_session()) as db:
        with pytest.raises(g.GoogleAgencyUnavailable):
            get_access_token(db, db.get(GoogleConnection, s.conn_id), fake)
        res = sync_google_location(db, db.get(GoogleLocation, s.gids[0]), fake, sleep=lambda x: None)
    assert res["status"] == "revoked" and len(fake.calls) == n  # nothing was sent to Google
    c = conn_of(s)
    assert c.auth_mode == "agency_account" and c.status == GoogleConnectionStatus.active  # stored state untouched: flipping the switch back resumes it
    monkeypatch.setattr(settings, "google_agency_manager_enabled", True)
    with closing(system_session()) as db:
        assert get_access_token(db, db.get(GoogleConnection, s.conn_id), fake) == AGENCY_ACCESS


def test_the_production_guard_needs_a_separate_agency_key(monkeypatch):
    def prod(**over):
        base = dict(app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True, public_card_base_url="https://go.flowqr.co.in",
                    frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in", database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr",
                    platform_admin_emails="ops@flowhq.in", smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
                    card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback", google_client_id="id", google_client_secret="secret")
        base.update(over)
        return Settings(_env_file=None, **base)

    key = Fernet.generate_key().decode()
    assert config_problems(prod()) == []  # off: nothing asked for
    assert any("AGENCY_TOKEN_ENCRYPTION_KEY" in p for p in config_problems(prod(google_agency_manager_enabled=True)))
    same = Fernet.generate_key().decode()
    assert any("must differ" in p for p in config_problems(prod(google_agency_manager_enabled=True, agency_token_encryption_key=same, token_encryption_key=same)))
    assert any("not a valid Fernet" in p for p in config_problems(prod(google_agency_manager_enabled=True, agency_token_encryption_key="nope")))
    assert config_problems(prod(google_agency_manager_enabled=True, agency_token_encryption_key=key, google_agency_location_group_id="5488245563")) == []


# ------------------------------------------------------------------ consent
def test_nothing_is_sent_to_google_without_a_stored_consent(fake):
    biz = make_business("No Consent Clinic")
    s = seed(biz)
    with closing(system_session()) as db:
        with pytest.raises(agency.ConsentRequired):
            agency.advance_connection(db, db.get(GoogleConnection, s.conn_id), force=True)
    assert fake.calls == [] and auths_of(s) == []
    for body in ({"agree": False, "consent_version": agency.CONSENT_VERSION}, {"agree": True, "consent_version": "an-older-text"}, {"agree": True}):
        r = biz.post("/google/agency/consent", json={"connection_id": str(s.conn_id), **body})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "consent_required", r.text
    assert fake.calls == [] and auths_of(s) == []
    untouched(s)


def test_consent_is_stored_with_version_hash_time_and_who(fake):
    biz = make_business("Consent Record Clinic")
    s = seed(biz)
    text = biz.get("/google/agency/status").json()
    assert text["consent_version"] == agency.CONSENT_VERSION and "never Owner" in text["consent_text"] and "Stop FlowQR managing my profile" in text["consent_text"]
    r = biz.post("/google/agency/consent", json={"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION})
    assert r.status_code == 200, r.text
    (a,) = auths_of(s)
    assert a.consent_version == agency.CONSENT_VERSION and a.consent_text_sha256 == agency.consent_sha() and a.consented_at and a.consented_by_email == biz.email


def test_consent_twice_makes_one_record_and_one_invite(fake):
    biz = make_business("Twice Clinic")
    s = seed(biz)
    consent(biz, s)
    consent(biz, s)
    assert len(auths_of(s)) == 1
    advance(s, force=True)
    advance(s, force=True)
    advance(s, force=True, retry=True)
    assert len(calls(fake, "invite")) == 1 and len(fake.admins[s.key[0]]) == 1


# ------------------------------------------------------------------ the happy path
def test_full_flow_order_tokens_switch_and_revoke(fake):
    biz = make_business("Happy Clinic")
    s = seed(biz)
    r = biz.post("/google/agency/consent", json={"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION})
    assert r.status_code == 200 and r.json()["auth_mode"] == "agency_account" and r.json()["locations"][0]["status"] == "active", r.text
    assert [(c[0], c[2]) for c in fake.calls] == [
        ("list_admins", CLIENT_ACCESS), ("invite", CLIENT_ACCESS),  # the client's token invites
        ("list_invitations", AGENCY_ACCESS), ("accept", AGENCY_ACCESS),  # the agency login accepts with its own
        ("list_visible", AGENCY_ACCESS),  # and is checked to see the location BEFORE anything changes
        ("revoke", CLIENT_REFRESH)]  # the client's token is revoked last
    assert fake.admins[s.key[0]][0].role == "MANAGER"
    c, (a,), gl = conn_of(s), auths_of(s), gloc_of(s.gids[0])
    assert c.auth_mode == "agency_account" and c.agency_account_id and a.agency_account_id == c.agency_account_id
    assert gl.google_account_name == "accounts/9001" and gl.client_google_account_name == "accounts/111"
    assert c.refresh_token_encrypted is None and c.access_token_encrypted is None and a.client_token_revoked_at
    assert a.invite_sent_at <= a.accepted_at <= a.verified_at <= a.switched_at
    with closing(system_session()) as db:
        assert get_access_token(db, db.get(GoogleConnection, s.conn_id), fake) == AGENCY_ACCESS
    assert "REFRESH" not in r.text and AGENCY_ACCESS not in r.text and CLIENT_ACCESS not in r.text


def test_every_google_action_uses_the_agency_account_after_the_switch(fake):
    biz = make_business("All Actions Clinic")
    s = seed(biz)
    go(biz, s)
    gl = gloc_of(s.gids[0])
    with closing(system_session()) as db:
        conn = db.get(GoogleConnection, s.conn_id)
        token = get_access_token(db, conn, fake)
        fake.list_reviews(token, gl.google_account_name, gl.google_location_name)
        fake.reply_to_review(token, gl.google_account_name, gl.google_location_name, "r1", "Thanks")
        fake.create_post(token, gl.google_account_name, gl.google_location_name, {"summary": "x"})
        fake.add_media(token, gl.google_account_name, gl.google_location_name, "https://example.com/p.jpg", "ADDITIONAL")
        fake.fetch_performance(token, gl.google_location_name, "2026-01-01", "2026-01-02", [])
    used = {c[0]: (c[1], c[2]) for c in fake.calls if c[0] in ("list_reviews", "reply", "post", "photo", "performance")}
    assert set(used) == {"list_reviews", "reply", "post", "photo", "performance"}
    assert all(tok == AGENCY_ACCESS for _, tok in used.values())
    assert used["reply"][0].startswith("accounts/9001/")


def test_no_code_path_reads_a_stored_google_token_except_the_reviewed_ones():
    """Every Google action gets its token from tokens.get_access_token, so agency mode covers reviews, replies, posts, photos and performance. A NEW file that reads the stored client
    tokens directly would bypass that: this fails until a person reviews it."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    users = sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*.py") if "refresh_token_encrypted" in p.read_text(encoding="utf-8") or "access_token_encrypted" in p.read_text(encoding="utf-8"))
    assert users == ["api/v1/google.py", "models/business.py", "services/account.py", "services/google/agency.py", "services/google/readiness.py", "services/google/smoke.py", "services/google/tokens.py"], users


# ------------------------------------------------------------------ approvals are unchanged
def test_the_agency_account_does_not_bypass_reply_approval(fake):
    from app.services.reviews import publish_draft

    biz = make_business("Approval Clinic")
    s = seed(biz)
    go(biz, s)
    with closing(system_session()) as db:
        gl = db.get(GoogleLocation, s.gids[0])
        rv = Review(tenant_id=gl.tenant_id, location_id=gl.location_id, google_location_id=gl.id, external_id="rev-1", rating=5, text="Great", reviewer_name="A",
                    review_created_at=utcnow(), first_seen_at=utcnow())
        db.add(rv)
        db.flush()
        draft = ReplyDraft(tenant_id=gl.tenant_id, review_id=rv.id, body="Thank you!", status=ReplyStatus.draft)
        db.add(draft)
        db.commit()
        with pytest.raises(ValueError):  # a draft nobody approved is refused exactly as before
            publish_draft(db, draft, by_user=None, provider=fake)
        assert not calls(fake, "reply")
        draft.status, draft.approved_at = ReplyStatus.approved, utcnow()
        db.commit()
        out = publish_draft(db, draft, by_user=None, provider=fake)
        assert out.status == ReplyStatus.published
    (c,) = calls(fake, "reply")
    assert c[2] == AGENCY_ACCESS and c[1].startswith("accounts/9001/")


# ------------------------------------------------------------------ failure paths
def test_invite_refused_leaves_everything_as_it_was(fake):
    fake.invite_error = g.GoogleAPIError(400, "bad request")
    biz = make_business("Invite Fail Clinic")
    s = seed(biz)
    assert go(biz, s) == [("failed", "invite_refused")]
    assert not calls(fake, "accept") and not calls(fake, "revoke")
    untouched(s)


def test_invite_hitting_a_transient_google_error_waits_and_resumes(fake):
    fake.invite_error = g.GoogleAPIError(503, "backend error")
    biz = make_business("Invite Retry Clinic")
    s = seed(biz)
    assert go(biz, s) == [("consented", "invite_retry")]
    (a,) = auths_of(s)
    assert a.attempts == 1 and a.next_attempt_at > utcnow()
    n = len(fake.calls)
    advance(s)  # not forced: the pause is respected, so no hammering
    assert len(fake.calls) == n
    fake.invite_error = None
    assert advance(s, force=True) == [("active", None)]  # resumed from where it stopped
    assert len(calls(fake, "invite")) == 2  # the refused attempt plus the good one, never a third
    assert len(fake.admins[s.key[0]]) == 1


def test_accept_failure_keeps_the_client_token_and_can_be_retried(fake):
    fake.accept_error = g.GoogleAPIError(400, "cannot accept")
    biz = make_business("Accept Fail Clinic")
    s = seed(biz)
    assert go(biz, s) == [("needs_attention", "accept_failed")]
    untouched(s)
    assert not calls(fake, "revoke")
    n = len(fake.calls)
    assert advance(s, force=True) == [("needs_attention", "accept_failed")] and len(fake.calls) == n  # a person is needed: no automatic retry loop
    fake.accept_error = None
    assert advance(s, force=True, retry=True) == [("active", None)]  # "Check again" resumes at the accept step, without inviting again
    assert len(calls(fake, "invite")) == 1


def test_location_not_visible_after_accept_never_switches(fake):
    fake.visible_after_accept = False
    biz = make_business("Invisible Clinic")
    s = seed(biz)
    assert go(biz, s) == [("accepted", "not_visible_yet")]
    untouched(s)
    assert not calls(fake, "revoke")
    owner_exec("UPDATE google_agency_authorizations SET accepted_at = now() - interval '49 hours', next_attempt_at = NULL WHERE connection_id = :c", c=str(s.conn_id))
    assert advance(s, force=True) == [("needs_attention", "not_visible")]
    untouched(s)
    assert mail(ADMIN_EMAIL, "cannot see a location")
    assert not calls(fake, "revoke")


def test_a_connection_switches_only_when_every_selected_location_is_visible(fake):
    fake.hidden = set()
    biz = make_business("Two Locations Clinic")
    s = seed(biz, n=2)
    fake.hidden = {s.key[1]}
    st = go(biz, s)
    assert sorted(x[0] for x in st) == ["accepted", "verified"]
    untouched(s)  # the first is verified, the second is not: nothing changes, nobody loses access
    assert not calls(fake, "revoke")
    fake.hidden = set()
    owner_exec("UPDATE google_agency_authorizations SET next_attempt_at = NULL WHERE connection_id = :c", c=str(s.conn_id))
    assert sorted(x[0] for x in advance(s, force=True)) == ["active", "active"]
    assert conn_of(s).auth_mode == "agency_account"
    assert {gloc_of(i).google_account_name for i in s.gids} == {"accounts/9001"}


def test_a_failed_token_revoke_keeps_the_token_and_is_retried(fake):
    fake.revoke_ok = False
    biz = make_business("Revoke Fail Clinic")
    s = seed(biz)
    assert go(biz, s) == [("active", None)]  # the switch happened; the agency account is doing the work
    c, (a,) = conn_of(s), auths_of(s)
    assert c.auth_mode == "agency_account" and c.refresh_token_encrypted and a.client_token_revoked_at is None and a.client_token_revoke_attempts == 1
    with closing(system_session()) as db:
        assert get_access_token(db, db.get(GoogleConnection, s.conn_id), fake) == AGENCY_ACCESS
    # still failing a day later: a person is told, once
    owner_exec("UPDATE google_agency_authorizations SET switched_at = now() - interval '25 hours' WHERE connection_id = :c", c=str(s.conn_id))
    with closing(system_session()) as db:
        out = agency.housekeeping(db)
        agency.housekeeping(db)
    assert out["revoked"] == 0 and len(mail(ADMIN_EMAIL, "could not be revoked")) == 1
    fake.revoke_ok = True
    with closing(system_session()) as db:
        assert agency.housekeeping(db)["revoked"] == 1
    c, (a,) = conn_of(s), auths_of(s)
    assert c.refresh_token_encrypted is None and a.client_token_revoked_at


# ------------------------------------------------------------------ duplicates
def test_an_invitation_that_already_exists_is_adopted_not_repeated(fake):
    biz = make_business("Duplicate Clinic")
    s = seed(biz)
    fake.admins[s.key[0]] = [AdminEntry(f"locations/{s.key[0]}/admins/old", fake.agency_email, "MANAGER", True)]
    fake.invitations["accounts/9001/invitations/old"] = s.key[0]
    assert go(biz, s) == [("active", None)]
    assert not calls(fake, "invite") and len(fake.admins[s.key[0]]) == 1


def test_a_duplicate_that_google_refuses_is_adopted_too(fake):
    """The reference says `admin` is only needed on creation, so a list may not show the e-mail. Then Google's own refusal is the signal."""
    fake.list_returns_emails = False
    biz = make_business("Duplicate Refused Clinic")
    s = seed(biz)
    fake.admins[s.key[0]] = [AdminEntry(f"locations/{s.key[0]}/admins/old", fake.agency_email, "MANAGER", True)]
    fake.invitations["accounts/9001/invitations/old"] = s.key[0]
    assert go(biz, s) == [("active", None)]
    assert len(calls(fake, "invite")) == 1 and len(fake.admins[s.key[0]]) == 1


# ------------------------------------------------------------------ the separate notice
def test_the_client_gets_a_separate_notice_and_the_date_is_recorded(fake):
    biz = make_business("Notice Clinic")
    s = seed(biz)
    go(biz, s)
    (m,) = mail(biz.email, "now a manager")
    assert "separate notice from FlowQR, not from Google" in m["body"] and "Stop FlowQR managing my profile" in m["body"] and "People and access" in m["body"]
    assert CLIENT_REFRESH not in m["body"] and AGENCY_REFRESH not in m["body"]
    (a,) = auths_of(s)
    assert a.notice_sent_at and abs((a.notice_due_at - a.accepted_at) - timedelta(hours=48)) < timedelta(seconds=2)


def test_an_overdue_notice_alerts_a_person_once_a_day_and_is_still_sent_when_possible(fake, monkeypatch):
    import app.services.mailer as mailer

    real, blocked = mailer.send_email, {"on": True}
    monkeypatch.setattr(mailer, "send_email", lambda to, subject, body: False if (blocked["on"] and to == biz.email) else real(to, subject, body))
    biz = make_business("Overdue Notice Clinic")
    s = seed(biz)
    go(biz, s)
    (a,) = auths_of(s)
    assert a.notice_sent_at is None and a.status == "active"
    late = a.accepted_at + timedelta(hours=49)
    with closing(system_session()) as db:
        assert agency.housekeeping(db, now=late)["alerts"] == 1
        assert agency.housekeeping(db, now=late + timedelta(hours=1))["alerts"] == 0  # not every hour
        assert agency.housekeeping(db, now=late + timedelta(hours=25))["alerts"] == 1  # but again the next day
    assert mail(ADMIN_EMAIL, "48-hour notice")
    blocked["on"] = False
    with closing(system_session()) as db:
        assert agency.housekeeping(db, now=late)["notices"] == 1
    assert auths_of(s)[0].notice_sent_at


# ------------------------------------------------------------------ the client removes FlowQR in Google
def test_a_permission_error_after_the_client_removed_flowqr_stops_everything(fake):
    biz = make_business("Removed Clinic")
    s = seed(biz)
    go(biz, s)
    fake.client_removes_agency(s.names[0])
    with closing(system_session()) as db:
        res = sync_google_location(db, db.get(GoogleLocation, s.gids[0]), fake, sleep=lambda x: None)
    assert res["status"] == "lost"
    c, (a,) = conn_of(s), auths_of(s)
    assert c.status == GoogleConnectionStatus.revoked and "removed in Google" in c.last_error and a.status == "lost" and a.lost_at
    assert mail(ADMIN_EMAIL, "removed FlowQR")
    n = len(fake.calls)
    with closing(system_session()) as db:
        assert not [x for x in due_locations(db) if x.id in s.gids]  # (the shared test database holds other tests' locations)
        assert sync_google_location(db, db.get(GoogleLocation, s.gids[0]), fake, sleep=lambda x: None)["status"] == "skipped"
        with pytest.raises(g.GoogleAuthRevoked):
            get_access_token(db, db.get(GoogleConnection, s.conn_id), fake)
        agency.housekeeping(db)
    assert len(fake.calls) == n  # not one more call against a profile FlowQR no longer manages


def test_one_permission_error_while_flowqr_is_still_a_manager_stops_nothing(fake, monkeypatch):
    biz = make_business("Still Manager Clinic")
    s = seed(biz)
    go(biz, s)

    def denied(*a, **k):
        raise g.GoogleAPIError(403, "some other permission detail", google_status="PERMISSION_DENIED")

    monkeypatch.setattr(fake, "list_reviews", denied)
    with closing(system_session()) as db:
        res = sync_google_location(db, db.get(GoogleLocation, s.gids[0]), fake, sleep=lambda x: None)
    assert res["status"] == "error"
    c, (a,) = conn_of(s), auths_of(s)
    assert c.status == GoogleConnectionStatus.active and a.status == "active" and not mail(ADMIN_EMAIL, "removed FlowQR")


def test_the_periodic_check_finds_a_removal_too_and_ignores_an_inconclusive_answer(fake):
    biz = make_business("Periodic Clinic")
    s = seed(biz)
    go(biz, s)
    owner_exec("UPDATE google_agency_authorizations SET last_verified_at = now() - interval '7 hours' WHERE connection_id = :c", c=str(s.conn_id))
    fake.visibility_error = g.GoogleAPIError(503, "down")
    with closing(system_session()) as db:
        agency.housekeeping(db)
    assert auths_of(s)[0].status == "active"  # Google being down says nothing about the client
    fake.visibility_error = None
    fake.client_removes_agency(s.names[0])
    with closing(system_session()) as db:
        assert agency.housekeeping(db)["checked"] == 1
    assert auths_of(s)[0].status == "lost" and conn_of(s).status == GoogleConnectionStatus.revoked


# ------------------------------------------------------------------ stopping
def test_stop_ends_all_work_now_removes_flowqr_and_records_the_dates(fake):
    biz = make_business("Stop Clinic")
    s = seed(biz)
    go(biz, s)
    assert biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": False}).status_code == 422
    r = biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True})
    assert r.status_code == 200, r.text
    c, (a,), gl = conn_of(s), auths_of(s), gloc_of(s.gids[0])
    assert c.status == GoogleConnectionStatus.disconnected and gl.selected is False  # all work stopped immediately
    assert a.status == "stopped" and a.removal_requested_at and a.removed_at
    assert a.removal_deadline_at.date() == agency.add_business_days(a.removal_requested_at, settings.google_agency_removal_business_days).date()
    (rm,) = calls(fake, "remove")
    assert rm[2] == AGENCY_ACCESS and rm[1].startswith(f"locations/{s.key[0]}/admins/") and fake.admins[s.key[0]] == []
    with closing(system_session()) as db:
        assert not [x for x in due_locations(db) if x.id in s.gids]  # (the shared test database holds other tests' locations)


def test_stop_works_even_when_the_switch_is_off(fake, monkeypatch):
    biz = make_business("Stop Off Clinic")
    s = seed(biz)
    go(biz, s)
    monkeypatch.setattr(settings, "google_agency_manager_enabled", False)
    assert biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True}).status_code == 200
    assert auths_of(s)[0].status == "stopped"


def test_stop_without_agency_state_is_a_plain_404(fake):
    biz = make_business("Stop Nothing Clinic")
    s = seed(biz)
    assert biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True}).status_code == 404
    untouched(s)


def test_disconnecting_in_the_existing_screen_also_removes_flowqr(fake):
    biz = make_business("Disconnect Clinic")
    s = seed(biz)
    go(biz, s)
    assert biz.delete(f"/google/connections/{s.conn_id}").status_code == 204
    assert auths_of(s)[0].status == "stopped" and calls(fake, "remove")


def test_removal_that_fails_is_retried_and_a_person_is_told_near_the_deadline(fake):
    biz = make_business("Removal Retry Clinic")
    s = seed(biz)
    go(biz, s)
    fake.remove_error = g.GoogleAPIError(503, "down")
    assert biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True}).status_code == 200
    (a,) = auths_of(s)
    assert a.status == "stopping" and a.failure_code == "removal_retry" and conn_of(s).status == GoogleConnectionStatus.disconnected  # work has stopped regardless
    fake.remove_error = g.GoogleAPIError(403, "not allowed", google_status="PERMISSION_DENIED")  # TODO(verify): may a manager remove itself?
    owner_exec("UPDATE google_agency_authorizations SET removal_deadline_at = now() + interval '1 day' WHERE connection_id = :c", c=str(s.conn_id))
    with closing(system_session()) as db:
        out = agency.housekeeping(db)
        again = agency.housekeeping(db)
    assert auths_of(s)[0].status == "stopping" and auths_of(s)[0].failure_code == "removal_refused"
    assert out["alerts"] == 1 and again["alerts"] == 0 and mail(ADMIN_EMAIL, "must be removed")
    fake.remove_error = None
    with closing(system_session()) as db:
        assert agency.housekeeping(db)["removed"] == 1
    assert auths_of(s)[0].status == "stopped"


def test_stopping_before_the_invitation_is_accepted_withdraws_it(fake):
    fake.accept_error = g.GoogleAPIError(503, "down")
    biz = make_business("Withdraw Clinic")
    s = seed(biz)
    assert go(biz, s) == [("invited", "accept_retry")]
    assert fake.admins[s.key[0]]
    assert biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True}).status_code == 200
    assert auths_of(s)[0].status == "stopped" and fake.admins[s.key[0]] == [] and calls(fake, "remove")[0][2] == CLIENT_ACCESS


def test_stopping_before_any_invitation_just_cancels(fake):
    biz = make_business("Cancel Clinic")
    s = seed(biz)
    consent(biz, s)
    with closing(system_session()) as db:
        agency.request_stop(db, db.get(GoogleConnection, s.conn_id))
    assert auths_of(s)[0].status == "cancelled"
    assert [c[0] for c in fake.calls] == ["revoke"]  # no Business Profile call (nothing existed at Google); only the stopped connection's own Google sign-in is revoked, which nothing needs any more


# ------------------------------------------------------------------ accounts, keys, isolation
def test_agency_tokens_use_their_own_key_and_never_appear_anywhere(fake):
    biz = make_business("Keys Clinic")
    s = seed(biz)
    r = biz.post("/google/agency/consent", json={"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION})
    with closing(system_session()) as db:
        row = db.scalar(select(GoogleAgencyAccount))
        assert AGENCY_REFRESH not in row.refresh_token_encrypted and AGENCY_ACCESS not in row.access_token_encrypted
        assert TokenCipher(settings.agency_token_encryption_key).decrypt(row.refresh_token_encrypted) == AGENCY_REFRESH
        with pytest.raises(RuntimeError):
            get_cipher().decrypt(row.refresh_token_encrypted)  # the client-token key cannot open it
    for text in (r.text, biz.get("/google/agency/status").text, biz.get("/google/status").text):
        assert AGENCY_REFRESH not in text and AGENCY_ACCESS not in text and CLIENT_REFRESH not in text


def test_a_revoked_agency_login_pauses_its_clients_without_changing_them(fake):
    biz = make_business("Revoked Agency Clinic")
    s = seed(biz)
    go(biz, s)
    owner_exec("UPDATE google_agency_accounts SET access_token_expires_at = now() - interval '1 hour'")
    fake.fail_refresh_with = g.GoogleAuthRevoked("revoked")
    with closing(system_session()) as db:
        with pytest.raises(g.GoogleAgencyUnavailable):
            get_access_token(db, db.get(GoogleConnection, s.conn_id), fake)
    assert owner_query("SELECT status FROM google_agency_accounts")[0][0] == "revoked" and mail(ADMIN_EMAIL, "agency login revoked")
    assert conn_of(s).auth_mode == "agency_account" and conn_of(s).status == GoogleConnectionStatus.active  # not marked lost: it says nothing about the client


def test_several_agency_accounts_and_a_cap_that_is_configuration_not_a_guess(fake, monkeypatch):
    second = FakeAgencyClient("agency2@flowqr.test")
    agency.register_account("agency-2", code="c2", provider=second)
    biz1, biz2 = make_business("Cap One"), make_business("Cap Two")
    s1, s2 = seed(biz1), seed(biz2)
    consent(biz1, s1)
    consent(biz2, s2)
    a1, a2 = auths_of(s1)[0], auths_of(s2)[0]
    assert a1.agency_account_id != a2.agency_account_id  # the second business went to the less loaded login: a connection records which one it uses
    monkeypatch.setattr(settings, "google_agency_max_locations_per_account", 1)
    biz3 = make_business("Cap Three")
    s3 = seed(biz3, n=2)  # needs two places and no account has two free
    r = biz3.post("/google/agency/consent", json={"connection_id": str(s3.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "agency_unavailable"
    assert auths_of(s3) == []
    untouched(s3)
    assert agency.settings.google_agency_max_locations_per_account == 1 and Settings(_env_file=None).google_agency_max_locations_per_account == 0  # unknown by default, never "unlimited"


def test_agency_records_are_isolated_by_row_level_security(fake):
    a_biz, b_biz = make_business("RLS A"), make_business("RLS B")
    sa, sb = seed(a_biz), seed(b_biz)
    consent(a_biz, sa)
    consent(b_biz, sb)

    def visible(tenant_id):
        db = SessionLocal()
        try:
            set_rls_context(db, tenant_id=uuid.UUID(tenant_id))
            return db.scalars(select(Auth)).all(), db.scalars(select(GoogleAgencyAccount)).all()
        finally:
            db.close()

    auths, accounts = visible(a_biz.tenant_id)
    assert [x.connection_id for x in auths] == [sa.conn_id] and accounts == []  # own record only, and the agency logins are platform-only
    assert [x.connection_id for x in visible(b_biz.tenant_id)[0]] == [sb.conn_id]
    assert biz_status_hides_other(a_biz, sb)


def biz_status_hides_other(biz, other) -> bool:
    return str(other.conn_id) not in biz.get("/google/agency/status").text


def test_deleting_a_business_removes_flowqr_from_its_profiles_first(fake):
    from app.services.account import delete_tenant

    biz = make_business("Delete Me Clinic")
    s = seed(biz)
    go(biz, s)
    with closing(system_session()) as db:
        assert delete_tenant(db, uuid.UUID(biz.tenant_id), provider=fake)["deleted"] is True
    assert calls(fake, "remove") and fake.admins[s.key[0]] == []


def test_register_refuses_a_login_without_the_business_scope(fake):
    class NoScope(FakeAgencyClient):
        def exchange_code(self, code):
            from app.services.google.provider import TokenSet
            return TokenSet("a", 3600, "r", "openid email")

    with pytest.raises(agency.AgencyError):
        agency.register_account("bad", code="x", provider=NoScope("bad@flowqr.test"))
    assert owner_query("SELECT count(*) FROM google_agency_accounts WHERE label = 'bad'")[0][0] == 0
