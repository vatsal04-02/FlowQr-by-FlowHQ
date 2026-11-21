"""Agency onboarding as a product flow: invitation tracking, verification, tenant safety, the dashboard states, and the policy gate.

Every test runs against tests/fake_agency_google.FakeAgencyClient. NO test makes a live Google call, sends an invitation, revokes a token, automates a browser, or touches production.
What these prove is that FlowQR's code behaves correctly given what Google's pages say. They do not prove Google behaves as its pages say (see section 12 of docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md).
"""
import re
import uuid
from contextlib import closing
from datetime import timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, config_problems, settings
from app.core.db import system_session
from app.models import GoogleAgencyAuthorization as Auth, GoogleConnection, GoogleConnectionStatus, GoogleLocation
from app.models.base import utcnow
from app.services import google as g
from app.services.google import agency
from app.services.google.agency_client import AdminEntry
from app.services.google.sync import sync_google_location
from app.services.google.tokens import get_access_token
from tests.conftest import make_business, owner_exec, owner_query
from tests.fake_agency_google import AGENCY_ACCESS, CLIENT_ACCESS, CLIENT_REFRESH, GROUP
from tests.test_google_agency import ADMIN_EMAIL, _clean, advance, auths_of, calls, conn_of, consent, gloc_of, go, mail, seed, untouched  # noqa: F401  (_clean is an autouse fixture)
from tests.test_google_agency_group import gfake  # noqa: F401  (fixture: switch ON, operations ON, the FlowQR group configured)


@pytest.fixture()
def onb(gfake, monkeypatch):
    """The DEFAULT product state: the feature is on, OPERATIONS ARE OFF. Onboarding must stop at 'access verified' and change nothing for the client."""
    monkeypatch.setattr(settings, "google_agency_operations_enabled", False)
    return gfake


def transitions(auth_id) -> list[tuple]:
    rows = owner_query("SELECT metadata->>'from', metadata->>'to', metadata->>'code' FROM audit_logs WHERE action = 'google.agency.transition' AND entity_id = :i ORDER BY created_at, id", i=str(auth_id))
    return [tuple(r) for r in rows]


def age_invitation(s, minutes):
    owner_exec("UPDATE google_agency_authorizations SET invite_sent_at = now() - make_interval(mins => :m), next_attempt_at = NULL WHERE connection_id = :c", m=minutes, c=str(s.conn_id))


def status_of(biz, s) -> dict:
    r = biz.get("/google/agency/status")
    assert r.status_code == 200, r.text
    return next(c for c in r.json()["connections"] if c["connection_id"] == str(s.conn_id))


# ------------------------------------------------------------------ onboarding ends at "access verified": nothing runs, nothing switches
def test_onboarding_stops_at_access_verified_and_changes_nothing_for_the_client(onb):
    biz = make_business("Verified Only Clinic")
    s = seed(biz)
    assert go(biz, s) == [("verified", None)]
    untouched(s)  # still on the client's own token; the connection, its token and its account names are exactly as they were
    assert not calls(onb, "revoke")
    assert {c[0] for c in onb.calls} == {"list_admins", "invite_group", "list_group_invitations", "accept", "list_group_locations"}  # no review, reply, post, photo or performance call
    v = status_of(biz, s)
    assert v["state"] == "access_verified" and v["operations_enabled"] is False and "switched off" in v["detail"] and v["locations"][0]["status"] == "verified"
    with closing(system_session()) as db:  # and the client's own sync still runs on THEIR token, as it always did
        assert sync_google_location(db, db.get(GoogleLocation, s.gids[0]), onb, sleep=lambda x: None)["status"] == "ok"
    assert calls(onb, "list_reviews")[-1][2] == CLIENT_ACCESS


def test_an_accepted_invitation_is_not_api_approval(onb):
    biz = make_business("Not Approval Clinic")
    s = seed(biz)
    go(biz, s)
    before = conn_of(s)
    v = status_of(biz, s)
    assert "not Google's approval" in v["policy_note"] and v["api_access"] == before.api_access == "approved"  # untouched: an invitation says nothing about API access
    assert owner_query("SELECT api_access FROM google_connections WHERE id = :i", i=str(s.conn_id))[0][0] == "approved"


def test_enabling_operations_later_is_what_switches_and_revokes(onb, monkeypatch):
    biz = make_business("Later Switch Clinic")
    s = seed(biz)
    assert go(biz, s) == [("verified", None)]
    monkeypatch.setattr(settings, "google_agency_operations_enabled", True)
    with closing(system_session()) as db:
        assert agency.housekeeping(db)["advanced"] == 1
    assert conn_of(s).auth_mode == "agency_account" and auths_of(s)[0].status == "active" and calls(onb, "revoke")
    names = [c[0] for c in onb.calls]
    assert names.index("revoke") > max(i for i, n in enumerate(names) if n == "list_group_locations")


def test_a_switched_connection_stops_acting_the_moment_operations_are_switched_off(gfake, monkeypatch):
    biz = make_business("Ops Off Again Clinic")
    s = seed(biz)
    assert go(biz, s) == [("active", None)]
    n = len(gfake.calls)
    monkeypatch.setattr(settings, "google_agency_operations_enabled", False)
    with closing(system_session()) as db:
        with pytest.raises(g.GoogleAgencyUnavailable):
            get_access_token(db, db.get(GoogleConnection, s.conn_id), gfake)
        assert sync_google_location(db, db.get(GoogleLocation, s.gids[0]), gfake, sleep=lambda x: None)["status"] == "revoked"
    assert len(gfake.calls) == n  # nothing was sent to Google
    assert conn_of(s).auth_mode == "agency_account" and conn_of(s).status == GoogleConnectionStatus.active  # state kept: switching back on resumes it


def test_the_production_guard_refuses_operations_without_a_recorded_google_answer():
    def prod(**over):
        base = dict(app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True, public_card_base_url="https://go.flowqr.co.in",
                    frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in", database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr",
                    platform_admin_emails="ops@flowhq.in", smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
                    card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback", google_client_id="id", google_client_secret="secret",
                    google_agency_manager_enabled=True, agency_token_encryption_key=Fernet.generate_key().decode(), google_agency_location_group_id="5488245563")
        base.update(over)
        return Settings(_env_file=None, **base)

    assert config_problems(prod()) == []
    assert any("GOOGLE_AGENCY_POLICY_REFERENCE" in p for p in config_problems(prod(google_agency_operations_enabled=True)))
    assert any("GOOGLE_AGENCY_PROJECT_MODEL" in x for x in config_problems(prod(google_agency_operations_enabled=True, google_agency_policy_reference="Google case 1-2345 (written answer on file)")))  # a reference alone is not enough: the project model must be decided too
    assert config_problems(prod(google_agency_operations_enabled=True, google_agency_policy_reference="Google case 1-2345 (written answer on file)", google_agency_project_model="flowhq_own_project")) == []
    d = Settings(_env_file=None)
    assert d.google_agency_manager_enabled is False and d.google_agency_operations_enabled is False and d.google_agency_policy_reference == ""


# ------------------------------------------------------------------ invitation tracking: pending, accepted, withdrawn, revoked. Never fabricated.
def test_a_pending_invitation_is_shown_as_pending_and_becomes_verified_only_on_evidence(onb):
    onb.accept_error = g.GoogleAPIError(503, "down")  # FlowQR's group has not accepted yet
    biz = make_business("Pending Clinic")
    s = seed(biz)
    assert go(biz, s) == [("invited", "accept_retry")]
    v = status_of(biz, s)
    assert v["state"] == "invitation_pending" and v["waiting_on"] == "flowqr" and not v["client_action"] and "retry" in v["actions"] and "disconnect" in v["actions"]
    assert "accepted" not in v["detail"].lower() or "accepts it" in v["detail"]  # it never says accepted
    assert auths_of(s)[0].accepted_at is None and auths_of(s)[0].last_polled_at is not None
    onb.accept_error = None
    assert advance(s, force=True) == [("verified", None)]
    assert status_of(biz, s)["state"] == "access_verified"


def test_polling_is_slow_configurable_and_recorded(onb, monkeypatch):
    from app.workers.celery_app import celery_app

    assert celery_app.conf.beat_schedule["agency-housekeeping"]["schedule"] == 3600.0  # Google offers no notification, so it is polled, and no more often than hourly
    monkeypatch.setattr(settings, "google_agency_poll_minutes", 10)
    onb.invitation_account = "accounts/9001"  # never appears in the group's list: the step keeps waiting
    biz = make_business("Polling Clinic")
    s = seed(biz)
    go(biz, s)
    for _ in range(8):
        owner_exec("UPDATE google_agency_authorizations SET next_attempt_at = NULL WHERE connection_id = :c", c=str(s.conn_id))
        advance(s, force=True)
    a = auths_of(s)[0]
    assert a.attempts >= 8 and a.next_attempt_at - utcnow() <= timedelta(minutes=10, seconds=5)  # the pauses grow, then stop growing at the configured ceiling
    assert a.last_polled_at is not None


def test_an_invitation_that_has_gone_is_called_withdrawn_only_on_evidence_and_never_rejected_or_expired(onb):
    onb.invitation_account = "accounts/9001"  # not in the group's list
    biz = make_business("Withdrawn Clinic")
    s = seed(biz)
    assert go(biz, s) == [("invited", "invitation_pending")]
    key = s.key[0]
    onb.admins[key] = []  # the owner removed the pending invitation in Google
    onb.group_invitations.clear()
    # too soon: a new invitation can take a moment to appear, so absence proves nothing yet
    assert advance(s, force=True) == [("invited", "invitation_pending")]
    age_invitation(s, minutes=settings.google_agency_withdrawn_after_minutes + 1)
    assert advance(s, force=True) == [("withdrawn", "invitation_withdrawn")]
    v = status_of(biz, s)
    assert v["state"] == "client_action_required" and v["client_action"] and v["actions"] == ["restart"]
    assert "withdrawn, declined or expired" in v["detail"] and "rejected" not in v["detail"].lower()  # Google does not say which, so neither does FlowQR
    assert not calls(onb, "accept") and not calls(onb, "revoke")
    untouched(s)
    assert transitions(auths_of(s)[0].id)[-1] == ("invited", "withdrawn", "invitation_withdrawn")


def test_absence_is_not_evidence_when_the_owners_admin_list_cannot_be_read_or_shows_another_pending_invitation(onb):
    onb.invitation_account = "accounts/9001"
    biz = make_business("No Evidence Clinic")
    s = seed(biz)
    go(biz, s)
    onb.admins[s.key[0]] = []
    onb.group_invitations.clear()
    age_invitation(s, minutes=settings.google_agency_withdrawn_after_minutes + 5)
    onb.list_error = g.GoogleAPIError(503, "down")  # unreadable
    assert advance(s, force=True) == [("invited", "invitation_pending")]
    onb.list_error = None
    onb.admins[s.key[0]] = [AdminEntry(f"locations/{s.key[0]}/admins/someone", "someone@else.test", "MANAGER", True)]  # somebody else's pending invitation is there
    owner_exec("UPDATE google_agency_authorizations SET next_attempt_at = NULL WHERE connection_id = :c", c=str(s.conn_id))
    assert advance(s, force=True) == [("invited", "invitation_pending")]


def test_revoked_access_while_only_verified_marks_the_authorization_lost_and_leaves_the_clients_own_connection_alone(onb):
    biz = make_business("Lost Verified Clinic")
    s = seed(biz)
    assert go(biz, s) == [("verified", None)]
    onb.client_removes_agency(s.names[0])
    owner_exec("UPDATE google_agency_authorizations SET last_verified_at = now() - interval '7 hours' WHERE connection_id = :c", c=str(s.conn_id))
    with closing(system_session()) as db:
        assert agency.housekeeping(db)["checked"] == 1
    assert auths_of(s)[0].status == "lost"
    c = conn_of(s)
    assert c.status == GoogleConnectionStatus.active and c.auth_mode == "client_token" and c.refresh_token_encrypted  # their own working connection is NOT killed
    v = status_of(biz, s)
    assert v["state"] == "connection_lost" and v["client_action"] and "restart" in v["actions"] and "reconnect" in v["actions"]
    assert mail(ADMIN_EMAIL, "removed FlowQR") and "Their own connection is unchanged" in mail(ADMIN_EMAIL, "removed FlowQR")[0]["body"]


# ------------------------------------------------------------------ verification: the right place, the right tenant, nothing imported
def test_a_listed_location_with_a_different_place_id_is_never_accepted_as_the_selected_profile(onb):
    biz = make_business("Place Mismatch Clinic")
    s = seed(biz)
    owner_exec("UPDATE google_locations SET place_id = 'PLACE-OURS' WHERE id = :i", i=str(s.gids[0]))
    onb.place_ids[s.key[0]] = "PLACE-SOMEONE-ELSES"
    assert go(biz, s) == [("needs_attention", "location_identity_mismatch")]
    untouched(s)
    assert not calls(onb, "revoke") and mail(ADMIN_EMAIL, "does not match")
    onb.place_ids[s.key[0]] = "PLACE-OURS"  # the same place
    assert advance(s, force=True, retry=True) == [("verified", None)]


def test_wrong_location_an_invitation_for_a_different_location_is_never_accepted(onb):
    biz = make_business("Wrong Location Clinic")
    s = seed(biz)
    other = "5550001"
    onb.group_invitations[f"{GROUP}/invitations/other"] = (other, GROUP)  # somebody else's invitation sits in the group's list
    onb.admins[other] = [AdminEntry(f"locations/{other}/admins/o1", None, "MANAGER", True, GROUP)]
    onb.invitation_account = "accounts/9001"  # and ours never reaches the group's list
    assert go(biz, s) == [("invited", "invitation_pending")]
    assert calls(onb, "accept") == [] and f"{GROUP}/invitations/other" in onb.group_invitations  # it was looked at, matched against OUR location, and left alone
    untouched(s)


def test_the_group_listing_another_location_is_not_access_to_the_selected_one(onb):
    biz = make_business("Other Listed Clinic")
    s = seed(biz)
    onb.visible_after_accept = False
    onb.group_sees.add("5550002")  # the group lists some other location
    assert go(biz, s) == [("accepted", "not_visible_yet")]
    untouched(s)
    assert auths_of(s)[0].agency_account_name is None


def test_wrong_agency_group_an_authorization_for_a_group_the_agency_user_does_not_administer_is_blocked_before_anything_is_sent(onb):
    biz = make_business("Wrong Group Clinic")
    s = seed(biz)
    consent(biz, s)
    owner_exec("UPDATE google_agency_authorizations SET target_account_name = 'accounts/777' WHERE connection_id = :c", c=str(s.conn_id))
    assert advance(s, force=True) == [("needs_attention", "group_access_missing")]
    assert onb.calls == [] and onb.admins == {}
    untouched(s)


def test_an_expired_agency_token_and_an_expired_client_token_are_each_refreshed_once_and_the_flow_completes(onb):
    biz = make_business("Expired Tokens Clinic")
    s = seed(biz)
    owner_exec("UPDATE google_agency_accounts SET access_token_expires_at = now() - interval '1 hour'")
    owner_exec("UPDATE google_connections SET access_token_expires_at = now() - interval '1 hour' WHERE id = :c", c=str(s.conn_id))
    assert go(biz, s) == [("verified", None)]
    assert onb.refresh_calls == 2  # one for the client's token, one for the agency login's
    assert advance(s, force=True) == [("verified", None)] and onb.refresh_calls == 2  # valid now: no second refresh


# ------------------------------------------------------------------ one Google location, one business
def two_businesses_one_location():
    a_biz, b_biz = make_business("Tenant A Clinic"), make_business("Tenant B Clinic")
    sa, sb = seed(a_biz), seed(b_biz)
    for s in (sa, sb):
        owner_exec("UPDATE google_locations SET google_location_name = 'locations/777000111' WHERE id = :i", i=str(s.gids[0]))
        s.names, s.key = ["locations/777000111"], ["777000111"]
    return a_biz, b_biz, sa, sb


def test_two_businesses_can_never_both_be_mapped_to_the_same_google_location(onb):
    a_biz, b_biz, sa, sb = two_businesses_one_location()
    r = a_biz.post("/google/agency/consent", json={"connection_id": str(sa.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION})
    assert r.status_code == 200, r.text
    r = b_biz.post("/google/agency/consent", json={"connection_id": str(sb.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "location_already_managed" and str(sa.conn_id) not in r.text and "Tenant A" not in r.text  # and it says nothing about the other business
    assert auths_of(sb) == [] and len(calls(onb, "invite_group")) == 1  # B started nothing at Google
    untouched(sb)


def test_the_database_itself_refuses_a_second_open_authorization_for_the_same_google_location(onb, monkeypatch):
    a_biz, b_biz, sa, sb = two_businesses_one_location()
    consent(a_biz, sa)
    monkeypatch.setattr(agency, "_location_taken", lambda *a, **k: False)  # a race: the application-level check was passed by both
    with closing(system_session()) as db:
        with pytest.raises(agency.LocationAlreadyManaged):
            agency.record_consent(db, conn=db.get(GoogleConnection, sb.conn_id), user=SimpleNamespace(id=None, email=b_biz.email), agree=True, version=agency.CONSENT_VERSION)
        a = db.scalar(select(Auth).where(Auth.connection_id == sa.conn_id))
        dup = Auth(id=uuid.uuid4(), tenant_id=uuid.UUID(b_biz.tenant_id), connection_id=sb.conn_id, google_location_id=sb.gids[0], consent_version="v", consent_text_sha256="h", consented_at=utcnow(),
                   google_location_resource=a.google_location_resource, status="consented")
        db.add(dup)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_the_location_is_free_again_once_the_first_business_has_stopped(onb):
    a_biz, b_biz, sa, sb = two_businesses_one_location()
    go(a_biz, sa)
    assert a_biz.post(f"/google/agency/connections/{sa.conn_id}/stop", json={"confirm": True}).status_code == 200
    assert b_biz.post("/google/agency/consent", json={"connection_id": str(sb.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION}).status_code == 200


def test_a_business_cannot_touch_another_businesss_connection_or_see_its_state(onb):
    a_biz, b_biz, sa, sb = two_businesses_one_location()
    go(a_biz, sa)
    body = {"connection_id": str(sa.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION}
    assert b_biz.post("/google/agency/consent", json=body).status_code == 404
    assert b_biz.post(f"/google/agency/connections/{sa.conn_id}/advance").status_code == 404
    assert b_biz.post(f"/google/agency/connections/{sa.conn_id}/stop", json={"confirm": True}).status_code == 404
    assert str(sa.conn_id) not in b_biz.get("/google/agency/status").text
    assert [c["connection_id"] for c in b_biz.get("/google/agency/status").json()["connections"]] == [str(sb.conn_id)]
    assert auths_of(sa)[0].status in ("verified", "active")


def test_other_businesses_locations_in_the_group_are_never_imported_or_shown(gfake):
    biz = make_business("No Import Clinic")
    s = seed(biz)
    go(biz, s)
    gfake.group_sees |= {"880001", "880002"}  # other clients, visible through the group
    before = sorted(r[0] for r in owner_query("SELECT google_location_name FROM google_locations WHERE tenant_id = :t", t=biz.tenant_id))
    with closing(system_session()) as db:
        assert agency.housekeeping(db)["checked"] in (0, 1)
        agency.check_access(db, db.get(GoogleConnection, s.conn_id))
    assert sorted(r[0] for r in owner_query("SELECT google_location_name FROM google_locations WHERE tenant_id = :t", t=biz.tenant_id)) == before
    assert "880001" not in str(status_of(biz, s)) and "Another client" not in str(status_of(biz, s))


# ------------------------------------------------------------------ retry, replay and idempotency
def test_repeating_every_step_changes_nothing_and_adds_no_audit_entries(onb):
    biz = make_business("Idempotent Clinic")
    s = seed(biz)
    assert go(biz, s) == [("verified", None)]
    aid, n_calls = auths_of(s)[0].id, len(onb.calls)
    first = transitions(aid)
    for _ in range(3):
        assert advance(s, force=True) == [("verified", None)]
        assert advance(s, force=True, retry=True) == [("verified", None)]
    assert transitions(aid) == first  # a status that did not change is not a transition
    assert len(calls(onb, "invite_group")) == 1 and len(calls(onb, "accept")) == 1 and len(onb.admins[s.key[0]]) == 1
    assert len(onb.calls) == n_calls  # a verified authorization is not asked about again by advance at all (the periodic access check does that, on its own slow schedule)


def test_a_replayed_consent_returns_the_same_authorization_and_never_a_second_invitation(onb):
    biz = make_business("Replay Clinic")
    s = seed(biz)
    body = {"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION, "request_id": "req-0001"}
    r1, r2 = biz.post("/google/agency/consent", json=body), biz.post("/google/agency/consent", json=body)
    assert r1.status_code == r2.status_code == 200
    assert len(auths_of(s)) == 1 and len(calls(onb, "invite_group")) == 1 and auths_of(s)[0].consent_request_id == "req-0001"
    assert biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True}).status_code == 200
    r3 = biz.post("/google/agency/consent", json=body)  # the same request, replayed after the authorization ended
    assert r3.status_code == 409 and r3.json()["detail"]["code"] == "replay_detected"
    assert len(calls(onb, "invite_group")) == 1


def test_every_transition_is_audited_in_order_without_tokens_or_addresses(gfake):
    biz = make_business("Audit Clinic")
    s = seed(biz)
    go(biz, s)
    aid = auths_of(s)[0].id
    assert transitions(aid) == [(None, "consented", None), ("consented", "invited", None), ("invited", "accepted", None), ("accepted", "verified", None), ("verified", "active", None)]
    assert biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True}).status_code == 200
    assert [t[1] for t in transitions(aid)][-2:] == ["stopping", "stopped"]
    for (meta,) in owner_query("SELECT metadata::text FROM audit_logs WHERE action = 'google.agency.transition' AND entity_id = :i", i=str(aid)):
        assert not re.search(r"@|token|REFRESH|ACCESS|accounts/|locations/", meta), meta


def test_failure_and_wait_transitions_are_audited_too(onb):
    onb.agency_in_group = False
    biz = make_business("Audit Failure Clinic")
    s = seed(biz)
    go(biz, s)
    onb.agency_in_group = True
    advance(s, force=True, retry=True)
    t = transitions(auths_of(s)[0].id)
    assert (None, "consented", None) in t and ("consented", "needs_attention", "group_access_missing") in t and t[-1] == ("accepted", "verified", None)


# ------------------------------------------------------------------ the routes the client can choose
def test_the_two_routes_are_validated_against_what_the_client_selected(onb):
    biz = make_business("Routes Clinic")
    one = seed(biz)
    body = {"connection_id": str(one.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION}
    assert status_of(biz, one)["routes"] == {"selected": 1, "available": ["location"], "reason": ""}
    r = biz.post("/google/agency/consent", json={**body, "scope": "business_group"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "scope_invalid" and auths_of(one) == [] and onb.calls == []
    assert biz.post("/google/agency/consent", json={**body, "scope": "nonsense"}).status_code == 422
    assert biz.post("/google/agency/consent", json={**body, "scope": "location"}).status_code == 200
    assert auths_of(one)[0].invite_scope == "location"

    two = seed(make_business("Routes Group Clinic"), n=2)
    biz2 = make_business("Routes Group Clinic 2")
    s2 = seed(biz2, n=2)
    b2 = {"connection_id": str(s2.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION}
    assert status_of(biz2, s2)["routes"]["available"] == ["business_group"]
    assert biz2.post("/google/agency/consent", json={**b2, "scope": "location"}).status_code == 422  # two profiles: not the single-profile route
    assert biz2.post("/google/agency/consent", json={**b2, "scope": "business_group"}).status_code == 200
    assert {a.invite_scope for a in auths_of(s2)} == {"business_group"} and len(auths_of(s2)) == 2
    assert two  # (seeded only to prove several businesses can have several profiles)

    biz3 = make_business("Routes Mixed Clinic")
    s3 = seed(biz3, n=2)
    owner_exec("UPDATE google_locations SET google_account_name = 'accounts/222' WHERE id = :i", i=str(s3.gids[1]))
    v = status_of(biz3, s3)["routes"]
    assert v["available"] == [] and "different Google business groups" in v["reason"]
    assert biz3.post("/google/agency/consent", json={"connection_id": str(s3.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION, "scope": "business_group"}).status_code == 422


# ------------------------------------------------------------------ the dashboard states
def _auth(status, code=None):
    return SimpleNamespace(status=status, failure_code=code)


@pytest.mark.parametrize("status,code,state,client_action", [
    ("consented", None, "invitation_pending", False), ("invited", None, "invitation_pending", False), ("accepted", None, "invitation_pending", False),
    ("needs_attention", "group_access_missing", "invitation_pending", False), ("needs_attention", "client_token_invalid", "client_action_required", True),
    ("verified", None, "access_verified", False), ("active", None, "access_verified", False), ("withdrawn", "invitation_withdrawn", "client_action_required", True),
    ("failed", "invite_refused", "client_action_required", True), ("lost", None, "connection_lost", True), ("stopping", None, "disconnected", False),
    ("stopped", None, "disconnected", False), ("cancelled", None, "disconnected", False)])
def test_every_status_maps_to_one_of_the_six_dashboard_states(status, code, state, client_action):
    d = agency.dashboard_state(_auth(status, code))
    assert d["state"] == state and d["state"] in agency.STATES and d["client_action"] is client_action and d["headline"] and d["detail"]


def test_the_dashboard_never_says_accepted_or_verified_before_the_record_does():
    for status in ("consented", "invited"):
        d = agency.dashboard_state(_auth(status))
        assert d["state"] == "invitation_pending" and "verified" not in d["headline"].lower() and "verified" not in d["detail"].lower()
    assert "accepted" not in agency.dashboard_state(_auth("consented"))["detail"].lower()


def test_each_state_offers_the_buttons_that_make_sense():
    assert agency.dashboard_state(_auth("invited"))["actions"] == ["retry", "disconnect"]
    assert agency.dashboard_state(_auth("verified"))["actions"] == ["retry", "disconnect"]
    assert agency.dashboard_state(_auth("active"))["actions"] == ["disconnect"]
    assert agency.dashboard_state(_auth("needs_attention", "client_token_invalid"))["actions"] == ["retry", "reconnect", "disconnect"]
    assert agency.dashboard_state(_auth("withdrawn"))["actions"] == ["restart"]
    assert agency.dashboard_state(_auth("lost"))["actions"] == ["reconnect", "restart"]
    assert agency.dashboard_state(_auth("stopped"))["actions"] == ["restart"]
    assert "reconnect" in agency.dashboard_state(_auth("invited"), conn_status="revoked")["actions"]


def test_a_connected_google_account_with_nothing_started_is_its_own_state_and_the_view_carries_no_secret(onb):
    biz = make_business("Connected Only Clinic")
    s = seed(biz)
    v = status_of(biz, s)
    assert v["state"] == "google_connected" and v["headline"] == "Google account connected" and v["actions"] == ["start"] and v["locations"] == []
    go(biz, s)
    text = str(status_of(biz, s))
    for secret in (CLIENT_REFRESH, CLIENT_ACCESS, AGENCY_ACCESS, "REFRESH", "refresh_token", "access_token"):
        assert secret not in text


# ------------------------------------------------------------------ the feature switch, and Google's rules
def test_with_the_feature_switch_off_nothing_is_reachable_and_the_operations_switch_alone_does_nothing(onb, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_manager_enabled", False)
    monkeypatch.setattr(settings, "google_agency_operations_enabled", True)  # on, but without the master switch it means nothing
    assert agency.operations_enabled() is False
    biz = make_business("Flag Off Onboarding Clinic")
    s = seed(biz)
    assert biz.get("/google/agency/status").status_code == 404
    assert biz.post("/google/agency/consent", json={"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION}).status_code == 404
    with closing(system_session()) as db:
        with pytest.raises(agency.AgencyDisabled):
            agency.advance_connection(db, db.get(GoogleConnection, s.conn_id))
    assert onb.calls == [] and auths_of(s) == []
    untouched(s)


def test_nothing_in_the_flow_drives_a_browser_or_uses_an_unofficial_endpoint():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    code = "\n".join((root / "app" / "services" / "google" / n).read_text(encoding="utf-8") for n in ("agency.py", "agency_client.py", "agency_audit.py")) + (root / "app" / "api" / "v1" / "google_agency.py").read_text(encoding="utf-8")
    for banned in ("playwright", "selenium", "pyppeteer", "mechanize", "business.google.com", "google.com/business", "chromium", "webdriver"):
        assert banned not in code.lower(), banned
    reqs = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("requirements*.txt")).lower()
    assert not any(x in reqs for x in ("playwright", "selenium", "pyppeteer"))
    urls = set(re.findall(r"https://[a-z0-9.-]+", (root / "app" / "services" / "google" / "agency_client.py").read_text(encoding="utf-8")))
    assert urls and all(u.endswith("googleapis.com") for u in urls), urls  # only Google's published API hosts
