"""Agency manager account, LocationGroup delegation (services/google/agency.py, docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md section 11).

The client invites FlowQR's Business Group (`accounts/5488245563`, in Admin.account) instead of one person's e-mail. EVERY test runs against tests/fake_agency_google.FakeAgencyClient: no test makes a live
Google call, sends an invitation, or touches a real token. Where Google's documentation is silent (where a group invitation appears, who may accept it, how the agency user reaches the group),
the fake has a switch for each possibility, and the flow records what it observes instead of assuming.
"""
import json
import uuid
from contextlib import closing
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import Settings, config_problems, settings
from app.core.db import SessionLocal, set_rls_context, system_session
from app.models import GoogleAgencyAccount, GoogleAgencyAuthorization as Auth, GoogleConnection, GoogleConnectionStatus, GoogleLocation
from app.services import google as g
from app.services.google import agency
from app.services.google import agency_client as ac
from app.services.google.agency_client import AdminEntry
from app.services.google.sync import sync_google_location
from tests.conftest import make_business, owner_exec, owner_query
from tests.fake_agency_google import AGENCY_ACCESS, CLIENT_ACCESS, CLIENT_REFRESH, GROUP, FakeAgencyClient
from tests.test_google_agency import ADMIN_EMAIL, _clean, advance, auths_of, calls, conn_of, consent, gloc_of, go, mail, seed, untouched  # noqa: F401  (_clean is an autouse fixture)

AGENCY_EMAIL = "flowqr-agency@flowqr.test"


@pytest.fixture()
def gfake(monkeypatch):
    """Switch ON, an agency key, the FlowQR group configured, NO individual fallback, and one agency Google user registered as a member of that group."""
    monkeypatch.setattr(settings, "google_agency_manager_enabled", True)
    monkeypatch.setattr(settings, "agency_token_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "google_agency_location_group_id", "5488245563")
    monkeypatch.setattr(settings, "google_agency_individual_fallback", False)
    monkeypatch.setattr(settings, "google_agency_operations_enabled", True)  # setup: these tests exercise the SWITCHED path; the default (off) stops at "access verified" and is tested in test_google_agency_onboarding.py
    f = FakeAgencyClient(AGENCY_EMAIL)
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    monkeypatch.setattr(ac, "get_agency_client", lambda: f)
    agency.register_account("flowqr-agency", code="the-code", provider=f)
    return f


def agency_row() -> GoogleAgencyAccount:
    with closing(system_session()) as db:
        r = db.scalar(select(GoogleAgencyAccount).where(GoogleAgencyAccount.google_email == AGENCY_EMAIL))
        db.expunge(r)
        return r


def age_acceptance(s, hours=49):
    owner_exec("UPDATE google_agency_authorizations SET accepted_at = now() - make_interval(hours => :h), next_attempt_at = NULL WHERE connection_id = :c", h=hours, c=str(s.conn_id))


def clear_wait(s):
    owner_exec("UPDATE google_agency_authorizations SET next_attempt_at = NULL WHERE connection_id = :c", c=str(s.conn_id))


# ------------------------------------------------------------------ the agency login and the group
def test_the_agency_login_records_the_group_it_belongs_to_and_a_bad_id_is_refused_before_the_code_is_spent(gfake, monkeypatch):
    r = agency_row()
    assert r.location_group_name == GROUP and r.google_email == AGENCY_EMAIL
    spent = []
    monkeypatch.setattr(gfake, "exchange_code", lambda code: spent.append(code))
    for bad in ("agency@flowqr.test", "accounts/abc", "locations/1"):
        with pytest.raises(agency.AgencyError):
            agency.register_account("x", code="c", provider=gfake, location_group_id=bad)
    assert spent == []  # the single-use code was not consumed
    other = FakeAgencyClient("other@flowqr.test")
    agency.register_account("other", code="c", provider=other, location_group_id="777")  # the bare form is normalised
    with closing(system_session()) as db:
        assert db.scalar(select(GoogleAgencyAccount.location_group_name).where(GoogleAgencyAccount.google_email == "other@flowqr.test")) == "accounts/777"


def test_a_group_login_is_preferred_and_an_individual_one_is_used_only_when_the_fallback_is_on(gfake, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_location_group_id", "")
    indiv = FakeAgencyClient("person@flowqr.test")
    agency.register_account("person", code="c", provider=indiv)  # no group: an individual-only login
    monkeypatch.setattr(settings, "google_agency_individual_fallback", True)
    biz = make_business("Preference Clinic")
    s = seed(biz)
    consent(biz, s)
    (a,) = auths_of(s)
    assert a.target_type == "flowhq_location_group" and a.target_account_name == GROUP and a.agency_account_id == agency_row().id  # the group login wins even with the fallback on


def test_without_a_group_login_and_without_the_fallback_nothing_is_started(gfake, monkeypatch):
    owner_exec("DELETE FROM google_agency_accounts")
    monkeypatch.setattr(settings, "google_agency_location_group_id", "")
    agency.register_account("person", code="c", provider=FakeAgencyClient("person@flowqr.test"))  # individual-only
    biz = make_business("No Group Clinic")
    s = seed(biz)
    r = biz.post("/google/agency/consent", json={"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "agency_unavailable"
    assert auths_of(s) == [] and gfake.calls == []
    untouched(s)


# ------------------------------------------------------------------ creating, accepting, verifying
def test_a_location_group_manager_invitation_is_created_accepted_verified_and_only_then_switched(gfake):
    biz = make_business("Group Clinic")
    s = seed(biz)
    r = biz.post("/google/agency/consent", json={"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION})
    assert r.status_code == 200 and r.json()["auth_mode"] == "agency_account" and r.json()["locations"][0]["target_type"] == "flowhq_location_group", r.text
    assert gfake.requests == [{"kind": "group", "location": s.names[0], "account": "accounts/5488245563", "role": "MANAGER"}]  # the account resource, the role, nothing else
    assert [(c[0], c[2]) for c in gfake.calls] == [
        ("list_admins", CLIENT_ACCESS), ("invite_group", CLIENT_ACCESS),  # the CLIENT invites the group with their own token
        ("list_group_invitations", AGENCY_ACCESS), ("accept", AGENCY_ACCESS),  # the agency Google USER reads the group's invitations and accepts
        ("list_group_locations", AGENCY_ACCESS), ("list_admins", AGENCY_ACCESS),  # verified under the GROUP, and the group is seen as a settled manager
        ("revoke", CLIENT_REFRESH)]  # only then is the client's token revoked
    c, (a,), gl = conn_of(s), auths_of(s), gloc_of(s.gids[0])
    assert (a.target_type, a.target_account_name, a.receiving_account_name) == ("flowhq_location_group", GROUP, GROUP)  # what was invited, and where the invitation was found
    assert a.agency_account_id == agency_row().id  # the agency Google USER that accepted: a different thing from the group
    assert a.admin_resource_name.startswith(f"locations/{s.key[0]}/admins/grp")  # the accepted manager resource
    assert a.agency_account_name == GROUP and a.verified_at and a.invite_sent_at <= a.accepted_at <= a.verified_at <= a.switched_at  # verified location access
    assert c.auth_mode == "agency_account" and c.agency_account_id == agency_row().id and c.refresh_token_encrypted is None
    assert gl.google_account_name == GROUP and gl.client_google_account_name == "accounts/111"  # the v4 paths now use the group account


def test_no_email_is_ever_sent_to_google_in_group_mode(gfake):
    biz = make_business("No Email Clinic")
    s = seed(biz)
    go(biz, s)
    assert calls(gfake, "invite") == []  # the individual call was never made
    assert gfake.requests and all(r["kind"] == "group" and "admin" not in r for r in gfake.requests)
    assert AGENCY_EMAIL not in json.dumps(gfake.requests)
    assert all(a.email is None and a.account == GROUP for a in gfake.admins[s.key[0]])


def test_location_visibility_is_judged_under_the_group_not_for_the_individual(gfake):
    biz = make_business("Visibility Clinic")
    s = seed(biz)
    go(biz, s)
    assert calls(gfake, "list_visible") == []  # the user's own location list is never consulted in group mode
    assert [c[1] for c in calls(gfake, "list_group_locations")] == [GROUP]
    with closing(system_session()) as db:  # and the work really goes through the group's account path
        gl = db.get(GoogleLocation, s.gids[0])
        res = sync_google_location(db, gl, gfake, sleep=lambda x: None)
    assert res["status"] == "ok"
    (c,) = calls(gfake, "list_reviews")
    assert c[1] == f"{GROUP}/{s.names[0]}" and c[2] == AGENCY_ACCESS


def test_the_notice_names_the_group_not_a_persons_address(gfake):
    biz = make_business("Notice Group Clinic")
    s = seed(biz)
    go(biz, s)
    (m,) = mail(biz.email, "now a manager")
    assert "FlowQR's business group (accounts/5488245563)" in m["body"] and AGENCY_EMAIL not in m["body"]
    assert auths_of(s)[0].notice_sent_at


def test_the_consent_text_says_the_manager_is_a_flowqr_account_only_flowqr_staff_can_use(gfake):
    biz = make_business("Consent Group Clinic")
    seed(biz)
    st = biz.get("/google/agency/status").json()
    assert "only FlowQR staff can use" in st["consent_text"] and "never Owner" in st["consent_text"] and st["consent_version"] == agency.CONSENT_VERSION


# ------------------------------------------------------------------ duplicates and where invitations appear
def test_an_existing_group_invitation_is_adopted_not_repeated(gfake):
    biz = make_business("Duplicate Group Clinic")
    s = seed(biz)
    gfake.admins[s.key[0]] = [AdminEntry(f"locations/{s.key[0]}/admins/old", None, "MANAGER", True, GROUP)]
    gfake.group_invitations[f"{GROUP}/invitations/old"] = (s.key[0], GROUP)
    assert go(biz, s) == [("active", None)]
    assert calls(gfake, "invite_group") == [] and len(gfake.admins[s.key[0]]) == 1


def test_a_duplicate_that_google_refuses_is_adopted_even_when_the_pre_check_cannot_run(gfake):
    biz = make_business("Duplicate Refused Group Clinic")
    s = seed(biz)
    gfake.admins[s.key[0]] = [AdminEntry(f"locations/{s.key[0]}/admins/old", None, "MANAGER", True, GROUP)]
    gfake.group_invitations[f"{GROUP}/invitations/old"] = (s.key[0], GROUP)
    gfake.list_error = g.GoogleAPIError(503, "admin list unavailable")  # the pre-check fails, so Google's own refusal is the signal
    assert go(biz, s) == [("active", None)]
    assert len(calls(gfake, "invite_group")) == 1 and len(gfake.admins[s.key[0]]) == 1
    assert len(auths_of(s)) == 1


def test_consenting_and_advancing_repeatedly_sends_one_group_invitation(gfake):
    biz = make_business("Repeat Group Clinic")
    s = seed(biz)
    consent(biz, s)
    consent(biz, s)
    advance(s, force=True)
    advance(s, force=True)
    advance(s, force=True, retry=True)
    assert len(auths_of(s)) == 1 and len(calls(gfake, "invite_group")) == 1 and len(gfake.admins[s.key[0]]) == 1


def test_the_groups_invitation_list_is_read_and_the_account_it_was_found_under_is_recorded(gfake):
    gfake.accept_error = g.GoogleAPIError(503, "down")
    biz = make_business("Listing Clinic")
    s = seed(biz)
    assert go(biz, s) == [("invited", "accept_retry")]
    (a,) = auths_of(s)
    assert a.receiving_account_name == GROUP and a.invitation_name.startswith(f"{GROUP}/invitations/")
    assert [(c[0], c[1]) for c in gfake.calls if c[0].startswith("list_") and "invitations" in c[0]] == [("list_group_invitations", GROUP)]  # the group's own list was enough


def test_an_invitation_that_lands_somewhere_other_than_the_group_is_found_and_recorded_as_such(gfake, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_invitation_discovery", True)  # setup only: searching beyond the group's own list is a diagnostic that is OFF by default (see test_google_agency_group_sequence.py)
    gfake.invitation_account = "accounts/9001"  # models Google putting it in the agency user's own list (documentation is silent)
    biz = make_business("Elsewhere Clinic")
    s = seed(biz)
    assert go(biz, s) == [("active", None)]
    (a,) = auths_of(s)
    assert a.receiving_account_name == "accounts/9001" and a.target_account_name == GROUP  # where it was found is not what was invited
    assert [c[0] for c in gfake.calls if c[0].startswith("list_") and "invitations" in c[0]] == ["list_group_invitations", "list_invitations"]  # group first, then discovery


# ------------------------------------------------------------------ wrong or missing group access: nothing switches
def assert_nothing_switched(gfake, s):
    untouched(s)
    assert not calls(gfake, "revoke")


def test_an_agency_user_who_is_not_in_the_group_cannot_accept_and_a_person_is_told(gfake):
    gfake.agency_in_group = False
    biz = make_business("No Membership Clinic")
    s = seed(biz)
    assert go(biz, s) == [("needs_attention", "group_access_missing")]
    assert_nothing_switched(gfake, s)
    assert mail(ADMIN_EMAIL, "no access to the FlowQR group")
    n = len(gfake.calls)
    assert advance(s, force=True) == [("needs_attention", "group_access_missing")] and len(gfake.calls) == n  # no retry loop
    gfake.agency_in_group = True  # a person adds the user to the group
    assert advance(s, force=True, retry=True) == [("active", None)]
    assert len(calls(gfake, "invite_group")) == 1  # resumed at the accept step; not invited again


def test_a_location_listed_under_a_different_account_is_not_access_through_the_group(gfake):
    gfake.group_visible_account = "accounts/777"
    biz = make_business("Wrong Account Clinic")
    s = seed(biz)
    assert go(biz, s) == [("accepted", "not_visible_yet")]
    assert_nothing_switched(gfake, s)
    age_acceptance(s)
    assert advance(s, force=True) == [("needs_attention", "not_visible")]
    assert_nothing_switched(gfake, s)
    assert mail(ADMIN_EMAIL, "cannot see a location")


def test_seeing_the_location_as_an_individual_does_not_count_for_a_group_authorization(gfake):
    gfake.visible_after_accept = False
    biz = make_business("Individual Only Clinic")
    s = seed(biz)
    assert go(biz, s) == [("accepted", "not_visible_yet")]
    gfake.agency_sees.add(s.key[0])  # the user can see it personally, but the group cannot
    clear_wait(s)
    assert advance(s, force=True) == [("accepted", "not_visible_yet")]
    assert_nothing_switched(gfake, s) and calls(gfake, "list_visible") == []


def test_a_group_that_is_listed_but_still_pending_is_not_verified(gfake):
    gfake.group_admin_stays_pending = True
    biz = make_business("Pending Group Clinic")
    s = seed(biz)
    assert go(biz, s) == [("accepted", "group_invite_pending")]
    assert_nothing_switched(gfake, s)
    for adm in gfake.admins[s.key[0]]:
        adm.pending = False
    clear_wait(s)
    assert advance(s, force=True) == [("active", None)]


def test_a_group_that_holds_a_role_other_than_manager_stops_everything(gfake):
    gfake.group_admin_role = "OWNER"
    biz = make_business("Wrong Role Clinic")
    s = seed(biz)
    assert go(biz, s) == [("needs_attention", "unexpected_role")]
    assert_nothing_switched(gfake, s)
    assert mail(ADMIN_EMAIL, "unexpected role")


def test_google_creating_the_invitation_for_a_different_account_stops_everything(gfake, monkeypatch):
    real = gfake.invite_location_group

    def wrong(token, location, group):
        e = real(token, location, group)
        return AdminEntry(e.name, None, "MANAGER", True, "accounts/1")

    monkeypatch.setattr(gfake, "invite_location_group", wrong)
    biz = make_business("Mismatch Clinic")
    s = seed(biz)
    assert go(biz, s) == [("needs_attention", "invite_target_mismatch")]
    assert_nothing_switched(gfake, s)
    assert not calls(gfake, "accept") and mail(ADMIN_EMAIL, "wrong account")


def test_losing_access_to_the_group_between_accepting_and_verifying_needs_a_person(gfake):
    gfake.group_list_error = g.GoogleAPIError(403, "no", google_status="PERMISSION_DENIED")
    biz = make_business("Group Lost Midway Clinic")
    s = seed(biz)
    assert go(biz, s) == [("needs_attention", "group_access_missing")]
    assert_nothing_switched(gfake, s)


# ------------------------------------------------------------------ no switching before verification
def test_the_connection_is_only_switched_after_every_location_is_verified_under_the_group(gfake):
    biz = make_business("Two Group Locations Clinic")
    s = seed(biz, n=2)
    gfake.hidden = {s.key[1]}
    st = go(biz, s)
    assert sorted(x[0] for x in st) == ["accepted", "verified"]
    assert_nothing_switched(gfake, s)  # one is verified, one is not: nothing changes, nobody loses access
    gfake.hidden = set()
    clear_wait(s)
    assert sorted(x[0] for x in advance(s, force=True)) == ["active", "active"]
    assert {gloc_of(i).google_account_name for i in s.gids} == {GROUP} and {a.target_account_name for a in auths_of(s)} == {GROUP}


def test_the_clients_token_is_revoked_only_after_the_switch_is_committed_and_verified(gfake, monkeypatch):
    seen = {}
    real = gfake.revoke_token

    def spy(token):
        c, a = conn_of(biz_s), auths_of(biz_s)[0]
        seen.update(mode=c.auth_mode, verified=a.verified_at is not None, switched=a.switched_at is not None, group_listed=bool(calls(gfake, "list_group_locations")))
        return real(token)

    monkeypatch.setattr(gfake, "revoke_token", spy)
    biz = make_business("Order Clinic")
    biz_s = seed(biz)
    go(biz, biz_s)
    assert seen == {"mode": "agency_account", "verified": True, "switched": True, "group_listed": True}


# ------------------------------------------------------------------ removal, loss, and a missing group
def test_stopping_removes_the_group_from_the_location_and_records_the_dates(gfake):
    biz = make_business("Stop Group Clinic")
    s = seed(biz)
    go(biz, s)
    assert biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True}).status_code == 200
    c, (a,) = conn_of(s), auths_of(s)
    assert c.status == GoogleConnectionStatus.disconnected and a.status == "stopped" and a.removal_requested_at and a.removed_at and a.removal_deadline_at
    (rm,) = calls(gfake, "remove")
    assert rm[2] == AGENCY_ACCESS and rm[1].startswith(f"locations/{s.key[0]}/admins/grp")
    assert gfake.admins[s.key[0]] == [] and s.key[0] not in gfake.group_sees


def test_removal_finds_the_group_admin_by_account_when_its_name_was_never_stored(gfake):
    biz = make_business("Unknown Admin Clinic")
    s = seed(biz)
    go(biz, s)
    owner_exec("UPDATE google_agency_authorizations SET admin_resource_name = NULL WHERE connection_id = :c", c=str(s.conn_id))
    assert biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True}).status_code == 200
    assert auths_of(s)[0].status == "stopped"
    names = [c[0] for c in gfake.calls]
    assert names.index("remove") > len(names) - 1 - names[::-1].index("list_admins")  # the admin list was read (by the agency user) before the delete


def test_a_refused_removal_is_kept_and_counts_as_done_once_the_client_has_removed_the_group_themselves(gfake):
    biz = make_business("Refused Removal Clinic")
    s = seed(biz)
    go(biz, s)
    gfake.remove_error = g.GoogleAPIError(403, "not allowed", google_status="PERMISSION_DENIED")  # TODO(verify): may a group member remove the group?
    assert biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True}).status_code == 200
    assert (auths_of(s)[0].status, auths_of(s)[0].failure_code) == ("stopping", "removal_refused")  # still listed under the group, so it is NOT assumed gone
    gfake.client_removes_agency(s.names[0])  # the client removes it in Google
    with closing(system_session()) as db:
        assert agency.housekeeping(db)["removed"] == 1
    assert auths_of(s)[0].status == "stopped"


def test_stopping_before_the_group_accepted_withdraws_the_pending_invitation_with_the_clients_token(gfake):
    gfake.accept_error = g.GoogleAPIError(503, "down")
    biz = make_business("Withdraw Group Clinic")
    s = seed(biz)
    assert go(biz, s) == [("invited", "accept_retry")]
    assert biz.post(f"/google/agency/connections/{s.conn_id}/stop", json={"confirm": True}).status_code == 200
    assert auths_of(s)[0].status == "stopped" and gfake.admins[s.key[0]] == [] and calls(gfake, "remove")[0][2] == CLIENT_ACCESS


def test_the_client_removing_the_group_stops_everything_and_one_listing_serves_every_location(gfake):
    biz = make_business("Group Removed Clinic")
    s = seed(biz, n=2)
    go(biz, s)
    owner_exec("UPDATE google_agency_authorizations SET last_verified_at = now() - interval '7 hours' WHERE connection_id = :c", c=str(s.conn_id))
    gfake.client_removes_agency(s.names[0])
    before = len(calls(gfake, "list_group_locations"))
    with closing(system_session()) as db:
        assert agency.housekeeping(db)["checked"] == 1
    assert len(calls(gfake, "list_group_locations")) - before == 1  # one call for the group, not one per location
    assert conn_of(s).status == GoogleConnectionStatus.revoked and sorted(a.status for a in auths_of(s)) == ["active", "lost"]
    assert mail(ADMIN_EMAIL, "removed FlowQR")
    n = len(gfake.calls)
    with closing(system_session()) as db:
        agency.housekeeping(db)
        assert sync_google_location(db, db.get(GoogleLocation, s.gids[0]), gfake, sleep=lambda x: None)["status"] == "skipped"
    assert len(gfake.calls) == n


def test_the_agency_user_losing_group_membership_marks_nobody_lost_and_alerts_once(gfake):
    biz = make_business("Membership Lost Clinic")
    s = seed(biz)
    go(biz, s)
    gfake.agency_in_group = False
    with closing(system_session()) as db:
        conn = db.get(GoogleConnection, s.conn_id)
        assert agency.check_access(db, conn) == "unknown"
        assert agency.check_access(db, conn) == "unknown"
    assert auths_of(s)[0].status == "active" and conn_of(s).status == GoogleConnectionStatus.active  # this is FlowQR's side, not the client's
    assert len(mail(ADMIN_EMAIL, "lost access to the FlowQR group")) == 1  # once, not every check


# ------------------------------------------------------------------ isolation and the switch
def test_group_authorizations_and_their_new_columns_are_isolated_by_row_level_security(gfake):
    a_biz, b_biz = make_business("Group RLS A"), make_business("Group RLS B")
    sa, sb = seed(a_biz), seed(b_biz)
    go(a_biz, sa)
    go(b_biz, sb)

    def visible(tenant_id):
        db = SessionLocal()
        try:
            set_rls_context(db, tenant_id=uuid.UUID(tenant_id))
            return [(x.connection_id, x.target_type, x.target_account_name, x.receiving_account_name) for x in db.scalars(select(Auth)).all()], db.scalars(select(GoogleAgencyAccount)).all()
        finally:
            db.close()

    rows, accounts = visible(a_biz.tenant_id)
    assert rows == [(sa.conn_id, "flowhq_location_group", GROUP, GROUP)] and accounts == []  # the group login (and its group) are platform-only
    assert [r[0] for r in visible(b_biz.tenant_id)[0]] == [sb.conn_id]
    assert str(sb.conn_id) not in a_biz.get("/google/agency/status").text
    assert a_biz.post(f"/google/agency/connections/{sb.conn_id}/advance").status_code == 404  # another business's connection does not exist for you
    assert a_biz.post(f"/google/agency/connections/{sb.conn_id}/stop", json={"confirm": True}).status_code == 404
    assert auths_of(sb)[0].status == "active"


def test_with_the_switch_off_the_group_configuration_changes_nothing(gfake, monkeypatch):
    biz = make_business("Group Flag Off Clinic")
    s = seed(biz)
    monkeypatch.setattr(settings, "google_agency_manager_enabled", False)
    assert biz.get("/google/agency/status").status_code == 404
    assert biz.post("/google/agency/consent", json={"connection_id": str(s.conn_id), "agree": True, "consent_version": agency.CONSENT_VERSION}).status_code == 404
    assert biz.post(f"/google/agency/connections/{s.conn_id}/advance").status_code == 404
    with pytest.raises(agency.AgencyDisabled):
        with closing(system_session()) as db:
            agency.advance_connection(db, db.get(GoogleConnection, s.conn_id))
    with closing(system_session()) as db:
        res = sync_google_location(db, db.get(GoogleLocation, s.gids[0]), gfake, sleep=lambda x: None)
        assert agency.housekeeping(db) == {"advanced": 0, "checked": 0, "revoked": 0, "removed": 0, "notices": 0, "alerts": 0}
    assert res["status"] == "ok" and calls(gfake, "list_reviews")[0][2] == CLIENT_ACCESS  # the client's own token, exactly as before
    assert [c[0] for c in gfake.calls] == ["list_reviews"] and auths_of(s) == []
    untouched(s)


def test_the_production_guard_wants_the_group_or_an_explicit_choice_of_the_fallback():
    def prod(**over):
        base = dict(app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True, public_card_base_url="https://go.flowqr.co.in",
                    frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in", database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr",
                    platform_admin_emails="ops@flowhq.in", smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
                    card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback", google_client_id="id", google_client_secret="secret",
                    google_agency_manager_enabled=True, agency_token_encryption_key=Fernet.generate_key().decode())
        base.update(over)
        return Settings(_env_file=None, **base)

    assert any("GOOGLE_AGENCY_LOCATION_GROUP_ID" in p for p in config_problems(prod()))  # neither a group nor the fallback: refuse
    assert config_problems(prod(google_agency_location_group_id="5488245563")) == []
    assert config_problems(prod(google_agency_location_group_id="accounts/5488245563")) == []
    assert config_problems(prod(google_agency_individual_fallback=True)) == []
    assert any("numeric account id" in p for p in config_problems(prod(google_agency_location_group_id="agency@flowqr.test")))
    assert Settings(_env_file=None).google_agency_manager_enabled is False and Settings(_env_file=None).google_agency_individual_fallback is False  # off by default
