"""Self-service agency onboarding (services/google/agency_journey.py, /google/agency/journey, /agency-ops/journeys).

EVERY test here runs against tests/fake_agency_google.FakeAgencyClient: an in-memory Google. NO test makes a live Google call. What these prove is that FlowQR's code behaves correctly given what
Google's pages say. They do NOT prove that Google behaves as its pages say: that needs a dedicated test profile and two people (docs/AGENCY_SELF_SERVICE_ONBOARDING_RUNBOOK.md).
"""
import json
import uuid
from contextlib import closing
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core import rate_limit
from app.core.config import Settings, config_problems, settings
from app.core.db import system_session
from app.core.security import get_cipher
from app.models import AuditLog, GoogleAgencyAccount, GoogleAgencyAuthorization as Auth, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Review
from app.models.base import utcnow
from app.services import google as g
from app.services.audit import audit
from app.services.google import agency, agency_journey
from app.services.google.provider import GReview, GReviewPage
from app.services.google.sync import sync_google_location
from app.services.google.tokens import get_access_token
from app.services.mailer import OUTBOX
from tests.conftest import Session, make_business, make_user, owner_exec, owner_query
from tests.fake_agency_google import AGENCY_ACCESS, AGENCY_REFRESH, CLIENT_ACCESS, CLIENT_REFRESH, GROUP, FakeAgencyClient
from tests.test_location_permissions import invite
from tests.test_google_agency import _clean, advance, auths_of, calls, conn_of, gloc_of, mail, seed, untouched  # noqa: F401  (_clean is an autouse fixture)
from tests.test_google_agency_group import gfake  # noqa: F401  (fixture: switch ON, operations ON, the FlowQR group configured, one agency login registered)

ALL = ["read_reviews", "reply_to_reviews", "publish_posts", "edit_profile"]


@pytest.fixture()
def ss(gfake, monkeypatch):
    """The self-service switch ON and operations OFF: the DEFAULT product state (onboarding ends at 'access verified')."""
    monkeypatch.setattr(settings, "google_agency_self_service_enabled", True)
    monkeypatch.setattr(settings, "google_agency_operations_enabled", False)
    return gfake


@pytest.fixture()
def ssops(gfake, monkeypatch):
    """Self-service ON and operations ON: the switched path (the connection moves onto the agency login)."""
    monkeypatch.setattr(settings, "google_agency_self_service_enabled", True)
    return gfake


def journey(biz) -> dict:
    r = biz.get("/google/agency/journey")
    assert r.status_code == 200, r.text
    return r.json()


def the_journey(biz, s) -> dict:
    return next(j for j in journey(biz)["journeys"] if j["connection_id"] == str(s.conn_id))


def start(biz, s, actions=None, **over):
    body = {"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION, "actions": ALL if actions is None else actions, "request_id": uuid.uuid4().hex}
    body.update(over)
    return biz.post("/google/agency/journey/start", json=body)


def step(j, key) -> dict:
    return next(x for x in j["steps"] if x["key"] == key)


def unselect(s):
    owner_exec("UPDATE google_locations SET selected = false WHERE connection_id = :c", c=str(s.conn_id))


# ================================================================== 1. the switch, and the states BEFORE anything is sent
def test_with_the_self_service_switch_off_the_journey_routes_do_not_exist(gfake, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_self_service_enabled", False)
    biz = make_business("Switch Off Clinic")
    s = seed(biz)
    assert biz.get("/google/agency/journey").status_code == 404
    assert start(biz, s).status_code == 404
    assert biz.get("/google/agency/status").status_code == 200  # the earlier agency screens are untouched
    assert auths_of(s) == []


def test_the_config_guard_refuses_self_service_without_the_agency_switch():
    from cryptography.fernet import Fernet

    def prod(**over):
        base = dict(app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True, public_card_base_url="https://go.flowqr.co.in",
                    frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in", database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr",
                    platform_admin_emails="ops@flowhq.in", smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
                    card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback", google_client_id="id", google_client_secret="secret")
        base.update(over)
        return Settings(_env_file=None, **base)

    assert config_problems(prod()) == []
    assert any("GOOGLE_AGENCY_SELF_SERVICE_ENABLED needs GOOGLE_AGENCY_MANAGER_ENABLED" in p for p in config_problems(prod(google_agency_self_service_enabled=True)))


def test_a_new_business_has_not_started_and_is_offered_only_to_connect(ss):
    biz = make_business("Fresh Clinic")
    j = journey(biz)
    assert j["journeys"] == [] and j["start"]["state"] == "NOT_STARTED" and j["start"]["actions"] == ["connect"]
    assert [x["key"] for x in j["start"]["steps"]] == ["google", "locations", "select", "consent", "invite", "accept", "verify", "sync"]
    assert [x["label"] for x in j["start"]["steps"]][:3] == ["Connecting Google account", "Finding your business locations", "Selecting business location"]
    assert step(j["start"], "google")["status"] == "current" and step(j["start"], "sync")["status"] == "pending"


def test_a_started_but_unfinished_google_sign_in_is_oauth_pending_then_clears(ss, monkeypatch):
    biz = make_business("Midway Clinic")
    with closing(system_session()) as db:
        audit(db, action="google.connect_started", tenant_id=uuid.UUID(biz.tenant_id), entity_type="tenant", entity_id=uuid.UUID(biz.tenant_id))
        db.commit()
    assert journey(biz)["start"]["state"] == "CUSTOMER_OAUTH_PENDING"
    monkeypatch.setattr(agency_journey, "OAUTH_ATTEMPT_MINUTES", 0)  # the audit log is append-only, so the passing of time is modelled by the window
    assert journey(biz)["start"]["state"] == "NOT_STARTED"  # a sign-in nobody finished does not stay "pending" for ever


def test_connected_google_with_no_location_chosen_is_location_selection_pending(ss):
    biz = make_business("Choose Clinic")
    s = seed(biz)
    unselect(s)
    j = the_journey(biz, s)
    assert j["state"] == "LOCATION_SELECTION_PENDING" and "select_location" in j["actions"]
    assert step(j, "google")["status"] == "done" and step(j, "locations")["status"] == "done" and step(j, "select")["status"] == "current"
    assert j["google"]["locations_found"] == 1 and j["available_locations"][0]["selected"] is False and j["available_locations"][0]["title"] == "Clinic 0"


def test_a_google_account_with_no_locations_says_so_and_does_not_pretend(ss):
    biz = make_business("Empty Clinic")
    s = seed(biz)
    owner_exec("DELETE FROM google_locations WHERE connection_id = :c", c=str(s.conn_id))
    j = the_journey(biz, s)
    assert j["state"] == "LOCATION_SELECTION_PENDING" and step(j, "locations")["status"] == "current" and "no Business Profile location" in step(j, "locations")["message"]


def test_a_selected_location_waits_for_the_customers_own_agreement_and_nothing_is_sent(ss):
    biz = make_business("Agree Clinic")
    s = seed(biz)
    j = the_journey(biz, s)
    assert j["state"] == "CUSTOMER_CONSENT_PENDING" and "approve" in j["actions"] and step(j, "consent")["status"] == "current"
    assert auths_of(s) == [] and ss.calls == []  # looking at the page sent nothing to Google and recorded no consent


def test_google_api_not_approved_is_blocked_and_never_shown_as_progress(ss):
    biz = make_business("Unapproved Clinic")
    s = seed(biz)
    owner_exec("UPDATE google_connections SET api_access = 'awaiting_approval' WHERE id = :c", c=str(s.conn_id))
    j = the_journey(biz, s)
    assert j["state"] == "BLOCKED" and j["blocked"]["code"] == "api_not_approved" and step(j, "consent")["status"] == "blocked"
    assert all(x["status"] != "done" for x in j["steps"][3:])


def test_a_business_the_operator_has_not_opened_is_blocked_with_the_reason_not_a_404(ss, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_internal_only", True)
    monkeypatch.setattr(settings, "google_agency_operator_emails", "ssob-operator@flowhq.example")
    biz = make_business("Unopened Clinic")
    s = seed(biz)
    j = the_journey(biz, s)
    assert j["state"] == "BLOCKED" and j["blocked"]["code"] == "not_opened_for_business"
    assert start(biz, s).status_code == 404 and auths_of(s) == []  # and it cannot be started around the gate
    assert journey(make_business("Unopened Two"))["start"]["state"] == "BLOCKED"


def test_a_missing_agency_login_is_blocked_before_the_customer_is_asked_to_agree(ss):
    biz = make_business("No Agency Clinic")
    s = seed(biz)
    owner_exec("DELETE FROM google_agency_accounts")
    j = the_journey(biz, s)
    assert j["state"] == "BLOCKED" and j["blocked"]["code"] == "no_agency_account"


# ================================================================== 2. consent: the customer's own, specific, per category
def test_consent_needs_the_agreement_the_current_wording_and_known_categories(ss):
    biz = make_business("Consent Clinic")
    s = seed(biz)
    assert start(biz, s, agree=False).status_code == 422
    assert start(biz, s, consent_version="old-wording").status_code == 422
    assert start(biz, s, actions=["read_reviews", "take_over_my_account"]).status_code == 422  # an unknown permission is refused, not ignored
    assert auths_of(s) == [] and ss.calls == []  # nothing recorded, nothing sent


def test_the_categories_the_customer_ticked_are_stored_with_reading_always_included(ss):
    biz = make_business("Categories Clinic")
    s = seed(biz)
    assert start(biz, s, actions=["reply_to_reviews"]).status_code == 200
    (a,) = auths_of(s)
    assert a.consent_actions == ["read_reviews", "reply_to_reviews"] and a.consent_version == agency.CONSENT_VERSION and a.consented_by_email == biz.email and a.consented_at
    meta = owner_query("SELECT metadata->'actions' FROM audit_logs WHERE action = 'google.agency.consent' AND tenant_id = :t", t=biz.tenant_id)
    assert json.loads(json.dumps(meta[-1][0])) == ["read_reviews", "reply_to_reviews"]  # the audit trail records what was agreed


def test_a_category_that_was_not_agreed_is_refused_where_it_would_be_used(ssops):
    biz = make_business("Enforce Clinic")
    s = seed(biz)
    assert start(biz, s, actions=["reply_to_reviews"]).status_code == 200
    assert conn_of(s).auth_mode == "agency_account"
    with closing(system_session()) as db:
        conn, gl = db.get(GoogleConnection, s.conn_id), db.get(GoogleLocation, s.gids[0])
        assert get_access_token(db, conn, ssops, gloc=gl) == AGENCY_ACCESS  # reading: always
        assert get_access_token(db, conn, ssops, gloc=gl, action="reply_to_reviews") == AGENCY_ACCESS  # agreed
        for refused in ("publish_posts", "edit_profile"):
            with pytest.raises(agency.AgencyResolutionError) as e:
                get_access_token(db, conn, ssops, gloc=gl, action=refused)
            assert e.value.code == "action_not_consented"
    denied = owner_query("SELECT metadata->>'code' FROM audit_logs WHERE action = 'google.agency.resolution_denied' AND tenant_id = :t", t=biz.tenant_id)
    assert ("action_not_consented",) in [tuple(r) for r in denied]


def test_an_authorization_recorded_before_categories_existed_keeps_what_its_wording_covered(ssops):
    biz = make_business("Legacy Clinic")
    s = seed(biz)
    r = biz.post("/google/agency/consent", json={"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION})  # the earlier route: no categories asked
    assert r.status_code == 200 and auths_of(s)[0].consent_actions is None
    with closing(system_session()) as db:
        assert get_access_token(db, db.get(GoogleConnection, s.conn_id), ssops, gloc=db.get(GoogleLocation, s.gids[0]), action="publish_posts") == AGENCY_ACCESS


def test_only_an_administrator_of_the_business_can_give_the_consent(ss):
    biz = make_business("Staff Clinic")
    s = seed(biz)
    staff = invite(biz)
    assert start(staff, s).status_code == 403  # a person without the admin role in this business cannot, whatever they send
    assert staff.get("/google/agency/journey").status_code == 200  # they may look (the page says what is happening), but not act
    assert staff.get("/google/agency/journey").json()["can_act"] is False
    assert auths_of(s) == []


# ================================================================== 3. the whole journey, every stage evidenced by a record
def test_the_journey_reaches_connected_only_through_real_records_and_stops_at_verified_with_operations_off(ss):
    biz = make_business("Journey Clinic")
    s = seed(biz)
    r = start(biz, s)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["state"] == "CONNECTED" and j["blocked"] is None
    assert [step(j, k)["status"] for k in ("google", "locations", "select", "consent", "invite", "accept", "verify")] == ["done"] * 7
    assert step(j, "sync")["status"] == "blocked" and "not switched on" in step(j, "sync")["message"]  # honest: access is verified, automatic sync is NOT running
    (a,) = auths_of(s)
    assert a.status == "verified" and a.invite_sent_at and a.accepted_at and a.verified_at and a.target_type == "flowhq_location_group" and a.target_account_name == GROUP
    # who did what: the customer's token created the invitation, FlowHQ's own agency login accepted and verified, and nothing else was done to the customer's connection
    assert [(c[0], c[2]) for c in ss.calls if c[0] in ("invite_group", "accept", "list_group_locations")] == [
        ("invite_group", CLIENT_ACCESS), ("accept", AGENCY_ACCESS), ("list_group_locations", AGENCY_ACCESS)]
    assert ss.requests[0] == {"kind": "group", "location": s.names[0], "account": GROUP, "role": "MANAGER"}  # Manager, to the Location Group, never an e-mail, never Owner
    untouched(s)
    assert not calls(ss, "revoke")
    assert j["locations"][0]["sync"]["mode"] == "owner_oauth"  # their own sign-in keeps syncing: nothing about their existing sync was switched off
    assert all(c["ok"] for c in j["locations"][0]["mapping"]), j["locations"][0]["mapping"]
    assert mail(biz.email, "FlowQR is now a manager")  # the separate notice, in its own e-mail, not Google's
    kinds = [t["event"] for t in j["timeline"]]
    assert "You approved FlowQR as your Manager" in kinds and "Manager invitation sent to Google" in kinds and "FlowHQ accepted the invitation" in kinds
    assert any(e.startswith("Status changed: ") for e in kinds)  # every state transition is in the audit trail


def test_each_stage_is_reported_as_it_happens_and_a_stage_is_never_done_ahead_of_its_record(ss):
    biz = make_business("Stages Clinic")
    s = seed(biz)
    ss.accept_error = g.GoogleAPIError(500, "boom")  # Google accepts nothing for now
    r = start(biz, s)
    j = r.json()
    assert j["state"] == "AGENCY_ACCEPTANCE_PENDING" and step(j, "invite")["status"] == "done" and step(j, "accept")["status"] == "waiting"
    assert step(j, "verify")["status"] == "pending" and step(j, "sync")["status"] == "pending"  # not done, not "in progress": nothing has happened yet
    assert auths_of(s)[0].accepted_at is None and auths_of(s)[0].verified_at is None
    ss.accept_error = None
    advance(s, force=True)
    assert the_journey(biz, s)["state"] == "CONNECTED"


def test_an_invitation_google_has_not_yet_delivered_is_invite_pending_not_accepted(ss):
    biz = make_business("Undelivered Clinic")
    s = seed(biz)
    ss.list_pending_invitations = lambda token, accounts=None: []  # the invitation exists at Google but does not show up for the agency login yet
    j = start(biz, s).json()
    assert j["state"] == "MANAGER_INVITE_PENDING" and step(j, "invite")["status"] == "done" and step(j, "accept")["status"] == "waiting"
    (a,) = auths_of(s)
    assert a.status == "invited" and a.invitation_name is None and a.accepted_at is None and not calls(ss, "accept")


def test_an_invitation_that_never_becomes_visible_never_becomes_connected(ss):
    biz = make_business("Invisible Clinic")
    s = seed(biz)
    ss.visible_after_accept = False
    j = start(biz, s).json()
    assert j["state"] == "ACCESS_VERIFICATION_PENDING" and step(j, "accept")["status"] == "done" and step(j, "verify")["status"] == "waiting"
    assert auths_of(s)[0].verified_at is None
    untouched(s)


def test_access_to_a_different_place_is_not_accepted_as_this_business(ss):
    biz = make_business("Mismatch Clinic")
    s = seed(biz)
    owner_exec("UPDATE google_locations SET place_id = 'place-A' WHERE connection_id = :c", c=str(s.conn_id))
    ss.place_ids[s.key[0]] = "place-B"
    j = start(biz, s).json()
    assert j["state"] == "BLOCKED" and j["blocked"]["code"] == "location_identity_mismatch" and auths_of(s)[0].verified_at is None
    untouched(s)


# ================================================================== 4. the switched path: initial and recurring synchronization
def test_with_operations_on_the_connection_moves_and_the_first_sync_is_queued_once(ssops, monkeypatch):
    queued = []
    from app.workers import tasks

    monkeypatch.setattr(rate_limit, "_get_redis", lambda: object())
    monkeypatch.setattr(settings, "redis_url", "redis://test")
    monkeypatch.setattr(tasks.sync_location, "delay", lambda gid: queued.append(gid))
    biz = make_business("Switch Clinic")
    s = seed(biz)
    j = start(biz, s).json()
    assert j["state"] == "CONNECTED" and conn_of(s).auth_mode == "agency_account"
    assert queued == [str(s.gids[0])]
    assert auths_of(s)[0].initial_sync_enqueued_at is not None and step(j, "sync")["status"] == "waiting"  # queued, not finished: said so
    with closing(system_session()) as db:  # a second pass does not queue it again
        agency.enqueue_initial_sync(db, db.get(GoogleConnection, s.conn_id))
    assert queued == [str(s.gids[0])]
    assert not mail(biz.email, "could not")  # no failure notice for a success


class _PagedFake(FakeAgencyClient):
    """Two pages, and the SECOND page repeats a review of the first: pagination and de-duplication."""

    def list_reviews(self, token, account, location, page_token=None):
        self._profile("list_reviews", token, account, location)
        r = lambda i, t: GReview(f"rev-{i}", 5, t, "A Customer", "2026-11-01T10:00:00Z", "2026-11-01T10:00:00Z")  # noqa: E731
        if page_token is None:
            return GReviewPage([r(1, "great"), r(2, "good")], "p2")
        return GReviewPage([r(2, "good"), r(3, "fine")], None)


def test_the_first_sync_pages_through_google_de_duplicates_and_records_the_last_success(ssops, monkeypatch):
    f = _PagedFake("flowqr-agency@flowhq.example")
    f.__dict__.update({k: v for k, v in ssops.__dict__.items() if k not in ("calls", "requests")})
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    from app.services.google import agency_client as ac

    monkeypatch.setattr(ac, "get_agency_client", lambda: f)
    biz = make_business("Sync Clinic")
    s = seed(biz)
    assert start(biz, s).status_code == 200 and conn_of(s).auth_mode == "agency_account"
    with closing(system_session()) as db:
        res = sync_google_location(db, db.get(GoogleLocation, s.gids[0]), f, sleep=lambda x: None)
        assert res["status"] == "ok" and res["new"] == 3  # rev-2 appeared on both pages and was stored once
        res2 = sync_google_location(db, db.get(GoogleLocation, s.gids[0]), f, sleep=lambda x: None)
        assert res2["new"] == 0 and res2["updated"] == 0  # running it again duplicates nothing and changes nothing
        rows = list(db.scalars(select(Review).where(Review.google_location_id == s.gids[0])))
        assert sorted(r.external_id for r in rows) == ["rev-1", "rev-2", "rev-3"] and {r.tenant_id for r in rows} == {uuid.UUID(biz.tenant_id)}
    assert {c[2] for c in f.calls if c[0] == "list_reviews"} == {AGENCY_ACCESS}  # the agency login's own token, never the customer's
    j = the_journey(biz, s)
    assert step(j, "sync")["status"] == "done" and j["locations"][0]["sync"]["last_synced_at"] and j["locations"][0]["sync"]["mode"] == "agency"


def test_a_google_error_during_sync_is_recorded_and_never_shown_as_success(ssops):
    biz = make_business("Sync Error Clinic")
    s = seed(biz)
    assert start(biz, s).status_code == 200
    ssops.list_error = None
    with closing(system_session()) as db:
        gl = db.get(GoogleLocation, s.gids[0])
        owner_exec("UPDATE google_agency_accounts SET status = 'revoked'")  # the agency login is gone: nothing may be asked of Google
        res = sync_google_location(db, gl, ssops, sleep=lambda x: None)
    assert res["status"] == "revoked" and gloc_of(s.gids[0]).last_sync_status == "error" and gloc_of(s.gids[0]).last_synced_at is None
    assert step(the_journey(biz, s), "sync")["status"] != "done"


def test_one_business_failing_never_stops_the_others_in_the_hourly_job(ss, monkeypatch):
    a, b = make_business("Bad Clinic"), make_business("Good Clinic")
    sa, sb = seed(a), seed(b)
    for biz, s in ((a, sa), (b, sb)):
        with closing(system_session()) as db:
            agency.record_consent(db, conn=db.get(GoogleConnection, s.conn_id), user=SimpleNamespace(id=None, email=biz.email), agree=True, version=agency.CONSENT_VERSION, actions=ALL)
    real = agency.advance_connection

    def flaky(db, conn, **kw):
        if conn.id == sa.conn_id:
            raise RuntimeError("one business is broken")
        return real(db, conn, **kw)

    monkeypatch.setattr(agency, "advance_connection", flaky)
    with closing(system_session()) as db:
        out = agency.housekeeping(db)
    assert out["errors"] == 1 and out["advanced"] == 1
    assert auths_of(sb)[0].status == "verified" and auths_of(sa)[0].status == "consented"


def test_a_connection_that_another_worker_is_advancing_is_left_alone(ss, monkeypatch):
    class Lock:  # a Redis stand-in whose lock for this connection is already held by someone else
        def set(self, key, value, nx=False, ex=None):
            return False

        def get(self, key):
            return None

        def delete(self, key):
            pass

    biz = make_business("Locked Clinic")
    s = seed(biz)
    consent_only = start  # noqa: F841
    with closing(system_session()) as db:
        agency.record_consent(db, conn=db.get(GoogleConnection, s.conn_id), user=SimpleNamespace(id=None, email=biz.email), agree=True, version=agency.CONSENT_VERSION, actions=ALL)
    monkeypatch.setattr(rate_limit, "_get_redis", lambda: Lock())
    advance(s, force=True)
    assert ss.calls == [] and auths_of(s)[0].status == "consented"  # nothing was sent: the holder of the lock does the work, so two clicks can never send two invitations


# ================================================================== 5. failures and the states that are not success
def test_an_expired_customer_sign_in_is_expired_not_failed_and_not_success(ss):
    biz = make_business("Expired Clinic")
    s = seed(biz)
    owner_exec("UPDATE google_connections SET access_token_expires_at = now() - interval '1 day' WHERE id = :c", c=str(s.conn_id))
    real = ss.refresh_access_token

    def revoked(refresh_token):
        if refresh_token == CLIENT_REFRESH:
            raise g.GoogleAuthRevoked("invalid_grant")
        return real(refresh_token)

    ss.refresh_access_token = revoked  # Google no longer accepts the customer's refresh token (the agency login's is fine)
    j = start(biz, s).json()
    assert j["state"] == "EXPIRED" and "connect" in j["actions"] and step(j, "invite")["status"] == "failed"
    assert auths_of(s)[0].failure_code == "client_token_invalid" and calls(ss, "invite_group") == []
    assert mail(biz.email, "could not finish")  # the customer is told, once


def test_an_expired_or_revoked_agency_login_pauses_onboarding_and_never_succeeds(ss):
    biz = make_business("Agency Expired Clinic")
    s = seed(biz)
    owner_exec("UPDATE google_agency_accounts SET access_token_expires_at = now() - interval '1 day'")

    def revoked(refresh_token):
        raise g.GoogleAuthRevoked("invalid_grant")

    ss.refresh_access_token = revoked
    j = start(biz, s).json()
    assert j["state"] != "CONNECTED" and auths_of(s)[0].verified_at is None and calls(ss, "invite_group") == []  # not even the invitation is sent without a working agency login
    with closing(system_session()) as db:
        assert db.scalar(select(GoogleAgencyAccount.status)) == "revoked"
    untouched(s)


def test_the_agency_login_without_access_to_the_group_is_blocked_and_the_customer_token_is_not_used(ss):
    biz = make_business("No Group Clinic")
    s = seed(biz)
    ss.agency_in_group = False
    j = start(biz, s).json()
    assert j["state"] == "BLOCKED" and j["blocked"]["code"] == "group_access_missing"
    assert calls(ss, "invite_group") == [] and calls(ss, "list_admins") == []  # the customer's credentials were never used for it
    untouched(s)


def test_the_wrong_google_identity_can_never_accept(ss):
    biz = make_business("Wrong Identity Clinic")
    s = seed(biz)
    from tests.fake_agency_google import OTHER_ACCESS

    ss.group_admin_token = OTHER_ACCESS  # only SOMEONE ELSE is an administrator of the group: FlowHQ's own login is not
    j = start(biz, s).json()
    assert j["state"] == "BLOCKED" and not calls(ss, "accept") and auths_of(s)[0].verified_at is None


def test_the_same_google_location_cannot_be_mapped_to_two_businesses(ss):
    a, b = make_business("First Owner Clinic"), make_business("Second Owner Clinic")
    sa, sb = seed(a), seed(b)
    owner_exec("UPDATE google_locations SET google_location_name = :n WHERE connection_id = :c", n=sa.names[0], c=str(sb.conn_id))
    assert start(a, sa).status_code == 200
    r = start(b, sb)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "location_already_managed"
    assert auths_of(sb) == []
    j = the_journey(b, sb)
    assert j["state"] == "BLOCKED" and j["blocked"]["code"] == "location_taken"
    assert the_journey(a, sa)["state"] == "CONNECTED"  # the first business is unaffected


def test_a_second_attempt_for_the_same_location_creates_one_authorization_and_one_invitation(ss):
    biz = make_business("Double Click Clinic")
    s = seed(biz)
    rid = uuid.uuid4().hex
    assert start(biz, s, request_id=rid).status_code == 200
    assert start(biz, s, request_id=rid).status_code in (200, 409)
    assert len(auths_of(s)) == 1 and len(calls(ss, "invite_group")) == 1


# ================================================================== 6. disconnecting, revoking, reconnecting
def test_the_customer_can_stop_and_everything_afterwards_is_refused(ssops):
    biz = make_business("Stop Clinic")
    s = seed(biz)
    assert start(biz, s).status_code == 200
    r = biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True})
    assert r.status_code == 200
    (a,) = auths_of(s)
    assert a.status == "stopped" and a.removed_at and a.removal_requested_at
    assert ssops.admins[s.key[0]] == []  # FlowQR removed itself as a Manager in Google
    c = conn_of(s)
    assert c.status == GoogleConnectionStatus.disconnected and c.refresh_token_encrypted is None  # and the customer's own Google sign-in was revoked at Google, then dropped
    assert any(call[0] == "revoke" for call in ssops.calls)
    with closing(system_session()) as db:  # an old grant cannot be used again
        with pytest.raises(g.GoogleAuthRevoked):
            get_access_token(db, db.get(GoogleConnection, s.conn_id), ssops, gloc=db.get(GoogleLocation, s.gids[0]))
    assert mail(biz.email, "has stopped working") and mail(biz.email, "no longer a manager")  # both notices, once each
    j = journey(biz)["journeys"][0]
    assert j["state"] == "REVOKED" and all(x["status"] != "failed" for x in j["steps"])
    advance_again = biz.post(f"/google/agency/connections/{s.conn_id}/advance")
    assert advance_again.status_code in (200, 409)
    assert len(mail(biz.email, "no longer a manager")) == 1  # never sent twice


def test_stopping_an_invitation_that_was_never_accepted_withdraws_it_and_keeps_the_sign_in_only_until_done(ss):
    biz = make_business("Withdraw Clinic")
    s = seed(biz)
    ss.accept_error = g.GoogleAPIError(500, "boom")
    assert start(biz, s).json()["state"] == "AGENCY_ACCEPTANCE_PENDING"
    ss.remove_error = g.GoogleAPIError(500, "boom")  # withdrawing fails for now
    assert biz.delete(f"/google/connections/{s.conn_id}").status_code == 204
    c = conn_of(s)
    assert c.status == GoogleConnectionStatus.disconnected and c.refresh_token_encrypted is not None  # kept: withdrawing needs it
    assert auths_of(s)[0].status == "stopping" and not calls(ss, "revoke")
    ss.remove_error = None
    with closing(system_session()) as db:
        out = agency.housekeeping(db)
    assert out["removed"] == 1 and auths_of(s)[0].status == "stopped" and ss.admins[s.key[0]] == []
    assert conn_of(s).refresh_token_encrypted is None and calls(ss, "revoke")  # and only now is it revoked and dropped


def test_removal_by_the_customer_in_google_is_detected_and_stops_everything(ssops):
    biz = make_business("Lost Clinic")
    s = seed(biz)
    assert start(biz, s).status_code == 200
    ssops.client_removes_agency(s.names[0])
    with closing(system_session()) as db:
        assert agency.check_access(db, db.get(GoogleConnection, s.conn_id)) == "lost"
        agency.housekeeping(db)
    j = journey(biz)["journeys"][0]
    assert j["state"] == "REVOKED" and auths_of(s)[0].lost_at
    assert mail(biz.email, "no longer has access")


def test_the_customer_can_reconnect_and_start_again_after_stopping(ss):
    biz = make_business("Again Clinic")
    s = seed(biz)
    assert start(biz, s).status_code == 200
    assert biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True}).status_code == 200
    assert the_journey(biz, s)["state"] == "REVOKED" if journey(biz)["journeys"] else True
    s2 = seed(biz)  # a new Google sign-in creates a new connection, and the location row it rediscovers moves onto it
    owner_exec("DELETE FROM google_locations WHERE connection_id = :c", c=str(s2.conn_id))
    owner_exec("UPDATE google_locations SET connection_id = :c, selected = true WHERE id = :g", c=str(s2.conn_id), g=str(s.gids[0]))
    s2.gids, s2.names, s2.key = s.gids, s.names, s.key
    r = start(biz, s2)
    assert r.status_code == 200 and r.json()["state"] == "CONNECTED"  # the old, stopped authorization does not block a fresh one
    assert len(auths_of(s)) == 1 and len(auths_of(s2)) == 1 and auths_of(s)[0].status == "stopped" and auths_of(s2)[0].status == "verified"


# ================================================================== 7. isolation, rate limits, the operator
def test_another_business_sees_nothing_of_this_one_and_cannot_act_on_it(ss):
    a, b = make_business("Private Clinic"), make_business("Nosy Clinic")
    sa = seed(a)
    assert start(a, sa).status_code == 200
    jb = journey(b)
    assert jb["journeys"] == [] and str(sa.conn_id) not in json.dumps(jb)
    assert start(b, sa).status_code == 404  # naming another business's connection is "not found"
    assert b.post(f"/google/agency/connections/{sa.conn_id}/advance").status_code == 404
    assert b.post(f"/google/agency/connections/{sa.conn_id}/stop", json={"confirm": True}).status_code == 404
    assert auths_of(sa)[0].status == "verified"


def test_the_journey_never_carries_a_token_or_another_secret(ss):
    biz = make_business("Secret Clinic")
    s = seed(biz)
    assert start(biz, s).status_code == 200
    text = json.dumps(journey(biz), default=str).lower()
    for needle in (CLIENT_REFRESH, CLIENT_ACCESS, AGENCY_ACCESS, AGENCY_REFRESH, "refresh_token", "access_token", "secret"):
        assert needle.lower() not in text, needle


def test_starting_is_rate_limited(ss, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    rate_limit.reset_memory_limits()
    biz = make_business("Hammer Clinic")
    s = seed(biz)
    codes = [start(biz, s, agree=False).status_code for _ in range(12)]
    assert codes[:10] == [422] * 10 and codes[10:] == [429, 429]


OP = "ssob-operator@flowhq.example"  # not the address other test files register


def operator_session(monkeypatch):
    """The operator signs in through the ordinary supported path (registered once, e-mail verified); no business membership is involved."""
    monkeypatch.setattr(settings, "google_agency_operator_emails", OP)
    s = Session(None, OP)
    r = s.http.post("/api/v1/auth/login", json={"email": OP, "password": s.password})
    if r.status_code != 200:
        return make_user(OP)
    s.csrf = r.json()["csrf_token"]
    return s


def test_only_a_listed_signed_in_operator_reaches_the_operator_screens(ss, monkeypatch):
    biz = make_business("Operator Gate Clinic")
    s = seed(biz)
    assert start(biz, s).status_code == 200
    for path in ("/agency-ops/journeys", f"/agency-ops/journeys/{s.conn_id}"):
        assert biz.get(path).status_code == 404  # a customer, even the owner of this very business
    assert biz.post(f"/agency-ops/journeys/{s.conn_id}/advance").status_code == 404
    op = operator_session(monkeypatch)
    assert op.get("/agency-ops/journeys").status_code == 200


def test_the_operator_sees_the_whole_story_of_each_business_and_no_secret(ss, monkeypatch):
    biz = make_business("Operator View Clinic")
    s = seed(biz)
    ss.accept_error = g.GoogleAPIError(500, "boom")
    assert start(biz, s, actions=["reply_to_reviews"]).status_code == 200
    op = operator_session(monkeypatch)
    rows = op.get("/agency-ops/journeys").json()
    row = next(r for r in rows["journeys"] if r["tenant_id"] == biz.tenant_id)
    assert row["tenant_name"] == "Operator View Clinic" and row["state"] == "AGENCY_ACCEPTANCE_PENDING" and rows["counts"]["AGENCY_ACCEPTANCE_PENDING"] >= 1
    detail = op.get(f"/agency-ops/journeys/{s.conn_id}").json()
    loc, auth = detail["locations"][0], detail["locations"][0]["authorization"]
    assert loc["title"] == "Clinic 0" and auth["consent_actions"] == ["read_reviews", "reply_to_reviews"] and auth["consented_at"] and auth["consented_by_email"] == biz.email
    assert auth["invite_sent_at"] and auth["accepted_at"] is None and auth["failure_code"] == "accept_retry" and auth["attempts"] >= 1
    assert detail["google"]["status"] == "active" and detail["timeline"] and loc["mapping"] and detail["grant_open"] is False  # internal-only is off in this test, so no grant is needed or held
    assert "sync" in loc and "consecutive_failures" in loc["sync"]
    blob = json.dumps([rows, detail], default=str).lower()
    for needle in (CLIENT_REFRESH, CLIENT_ACCESS, AGENCY_ACCESS, AGENCY_REFRESH, "encrypted"):
        assert needle.lower() not in blob, needle
    only = op.get("/agency-ops/journeys", params={"state": "CONNECTED"}).json()
    assert all(r["state"] == "CONNECTED" for r in only["journeys"]) and op.get("/agency-ops/journeys", params={"state": "NOPE"}).status_code == 422


def test_the_operator_can_retry_but_gives_no_consent_and_leaves_an_audit_entry(ss, monkeypatch):
    biz = make_business("Operator Retry Clinic")
    s = seed(biz)
    ss.accept_error = g.GoogleAPIError(500, "boom")
    assert start(biz, s).status_code == 200
    ss.accept_error = None
    op = operator_session(monkeypatch)
    r = op.post(f"/agency-ops/journeys/{s.conn_id}/advance")
    assert r.status_code == 200 and r.json()["state"] == "CONNECTED"
    assert owner_query("SELECT count(*) FROM audit_logs WHERE action = 'agency_ops.advance' AND tenant_id = :t", t=biz.tenant_id)[0][0] == 1
    other = make_business("Operator No Consent Clinic")
    so = seed(other)
    assert op.post(f"/agency-ops/journeys/{so.conn_id}/advance").status_code == 409  # no consent on record: the operator cannot start anything for a business
    assert auths_of(so) == []


# ================================================================== 8. the migration
def test_migration_0066_is_additive_and_old_rows_keep_their_meaning():
    cols = {r[0]: r[1] for r in owner_query("SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = 'google_agency_authorizations'")}
    assert cols["consent_actions"] == "YES" and cols["initial_sync_enqueued_at"] == "YES" and cols["notices_sent"] == "NO"
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] == "0066"
    assert owner_query("SELECT column_default FROM information_schema.columns WHERE table_name = 'google_agency_authorizations' AND column_name = 'notices_sent'")[0][0].startswith("'{}'")
