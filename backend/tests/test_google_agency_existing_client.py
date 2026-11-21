"""Agency manager account: verifying the agency login's real access, and moving a client who ALREADY added FlowQR's group in Google (services/google/agency.py, agency_check.py).

The situation this is for: the client approved the group's management request in Business Profile Manager, the location is listed under the FlowQR LocationGroup, and the FlowQR connection
still runs on the client's own Google login. EVERY test runs against tests/fake_agency_google.FakeAgencyClient: no test makes a live Google call, sends an invitation or touches a real token.
These tests prove the CODE; they do not prove that Google behaves this way. The read-only command `google-agency-check` is what proves that, with the real token.
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
from app.core.security import get_cipher
from app.models import GoogleAgencyAccount, GoogleAgencyAuthorization as Auth, GoogleConnection, GoogleConnectionStatus, GoogleLocation
from app.models.base import utcnow
from app.services import google as g
from app.services.google import agency, agency_check
from app.services.google import agency_client as ac
from app.services.google.agency_client import AdminEntry
from app.services.google.errors import GoogleAPIError, GoogleApiNotApproved, GoogleAuthRevoked, GoogleRateLimited
from app.services.google.sync import sync_google_location
from app.services.google.tokens import get_access_token
from tests.conftest import make_business, owner_exec, owner_query
from tests.fake_agency_google import AGENCY_ACCESS, CLIENT_ACCESS, CLIENT_REFRESH, GROUP, FakeAgencyClient, denied
from tests.test_google_agency import ADMIN_EMAIL, _clean, advance, auths_of, calls, conn_of, consent, gloc_of, go, mail, seed, untouched  # noqa: F401  (_clean is an autouse fixture)
from tests.test_google_agency_group import AGENCY_EMAIL, agency_row, gfake  # noqa: F401  (gfake is a fixture)

ORG = "5234249121"  # the Google ORGANISATION id: never the group's


@pytest.fixture()
def adopt(gfake, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_adopt_existing_access", True)
    return gfake


def already_in_group(f, key, *, pending=False, role="MANAGER"):
    """The client added FlowQR's group by hand in Google: the location is listed under the group, and the group is on its admin list."""
    f.group_sees.add(key)
    f.admins.setdefault(key, []).append(AdminEntry(f"locations/{key}/admins/pre{key}", None, role, pending, GROUP))


def client_token_calls(f):
    return [c for c in f.calls if c[2] == CLIENT_ACCESS]


def run(f, **kw):
    kw.setdefault("account", "flowqr-agency")
    kw.setdefault("expected_email", AGENCY_EMAIL)
    return agency_check.run_checks(client=f, **kw)


def by_name(checks):
    out = {}
    for c in checks:
        out.setdefault(c.name, []).append(c)
    return out


def text(checks):
    return "\n".join(f"{c.name} {c.status} {c.detail}" for c in checks)


# ================================================================== the agency identity
def test_a_sign_in_as_the_wrong_google_account_is_revoked_and_never_stored(gfake):
    other = FakeAgencyClient("a.client@gmail.example")  # someone else signed in (a client, or a personal account)
    revoked_before = len(other.revoked)
    with pytest.raises(agency.AgencyError) as e:
        agency.register_account("flowhq-agency", code="c", provider=other, expected_email=AGENCY_EMAIL)
    assert "a.client@gmail.example" not in str(e.value)  # the wrong account's address is not echoed
    assert len(other.revoked) == revoked_before + 1  # the grant just issued is revoked at Google
    with closing(system_session()) as db:
        assert db.scalar(select(GoogleAgencyAccount).where(GoogleAgencyAccount.google_email == "a.client@gmail.example")) is None
        assert db.scalar(select(GoogleAgencyAccount).where(GoogleAgencyAccount.label == "flowhq-agency")) is None  # the label alone creates nothing


def test_the_expected_identity_is_matched_on_what_google_returns_not_on_the_label(gfake):
    same = FakeAgencyClient(AGENCY_EMAIL.upper())  # Google's answer, in any letter case
    agency.register_account("whatever-label", code="c", provider=same, expected_email=f"  {AGENCY_EMAIL}  ")
    with closing(system_session()) as db:
        rows = db.scalars(select(GoogleAgencyAccount).where(GoogleAgencyAccount.google_email == AGENCY_EMAIL.lower())).all()
        assert len(rows) == 1 and rows[0].label == "flowqr-agency"  # Google's answer, normalised, identified the SAME login as the one the fixture registered: no second row, and the new label changed nothing
    # a different expectation than what Google says is refused even though the LABEL looks right
    with pytest.raises(agency.AgencyError):
        agency.register_account("vatsal-flowhq", code="c", provider=same, expected_email="vatsal@flowhq.example")


def test_without_an_expectation_registration_behaves_as_before(gfake):
    agency.register_account("no-expectation", code="c", provider=FakeAgencyClient("anyone@example.test"))
    with closing(system_session()) as db:
        assert db.scalar(select(GoogleAgencyAccount).where(GoogleAgencyAccount.label == "no-expectation")) is not None


# ================================================================== the read-only check (google-agency-check)
def test_the_check_reads_the_group_and_the_clients_location_through_it_and_writes_nothing(gfake):
    biz = make_business("Check Clinic")
    s = seed(biz)
    key = s.key[0]
    already_in_group(gfake, key)
    for other in ("111000111", "222000222"):  # two other clients in the same group
        gfake.group_sees.add(other)
    checks = run(gfake, locations=[s.names[0]], connection_id=None)
    got = by_name(checks)
    assert [c.status for c in got["identity"]] == ["PASS"] and [c.status for c in got["accounts.list"]] == ["PASS"]
    assert [c.status for c in got["group locations"]] == ["PASS"] and "3 location(s)" in got["group locations"][0].detail
    assert [c.status for c in got["location match"]] == ["PASS"] and f"{GROUP}" in got["location match"][0].detail
    assert [c.status for c in got["location read"]] == ["PASS"]
    assert [c.status for c in got["tenant mapping"]] == ["PASS"] and biz.tenant_id in got["tenant mapping"][0].detail and str(s.conn_id) in got["tenant mapping"][0].detail
    assert agency_check.ok(checks)
    # the real review sync path: the GROUP account, the location, the AGENCY token
    (rd,) = calls(gfake, "list_reviews")
    assert rd[1] == f"{GROUP}/locations/{key}" and rd[2] == AGENCY_ACCESS
    # reads only: no invitation, acceptance, removal, reply, post, photo or revoke was made, and the client's token was never used
    assert {c[0] for c in gfake.calls} <= {"list_group_locations", "list_reviews"}
    assert gfake.requests == [] and client_token_calls(gfake) == [] and gfake.revoked == []
    # the other clients are counted, never named; the output carries no token
    out = text(checks)
    assert "111000111" not in out and "222000222" not in out and "Location 111000111" not in out
    assert AGENCY_ACCESS not in out and "refresh" not in out.lower()
    untouched(s)  # and the database is as it was


def test_the_check_refuses_a_stored_login_that_is_not_the_expected_account(gfake):
    checks = run(gfake, expected_email="someone.else@flowhq.example", locations=["locations/1"])
    assert [(c.name, c.status) for c in checks] == [("identity", "FAIL")] and not agency_check.ok(checks)
    assert gfake.calls == [] and gfake.account_lists == []  # nothing was asked of Google
    assert [c.status for c in run(gfake, account="nope", locations=["1"])] == ["FAIL"]  # no such login


def test_the_check_refuses_when_google_says_the_token_belongs_to_someone_else(gfake):
    gfake.agency_email = "swapped@example.test"  # Google now answers userinfo for a different account than the one that was registered
    checks = run(gfake, locations=["locations/1"])
    assert [(c.name, c.status) for c in checks] == [("identity", "FAIL")]
    assert "different account" in checks[0].detail and "swapped@example.test" not in checks[0].detail
    assert gfake.account_lists == [] and calls(gfake, "list_group_locations") == []  # it stopped before the group


def test_a_login_that_is_not_a_member_of_the_group_fails_at_accounts_list_and_goes_no_further(gfake):
    gfake.agency_in_group = False
    checks = run(gfake, locations=["locations/1"])
    got = by_name(checks)
    assert got["accounts.list"][0].status == "FAIL" and "not a member or administrator" in got["accounts.list"][0].detail
    assert "group locations" not in got and calls(gfake, "list_group_locations") == []
    assert not agency_check.ok(checks)


def test_the_organisation_id_is_never_used_as_the_group_id(gfake, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_organization_id", ORG)
    # asked to use the organisation as the group: refused before any request
    checks = run(gfake, group=ORG, locations=["locations/1"])
    assert checks[-1].name == "accounts.list" and checks[-1].status == "FAIL" and "organisation" in checks[-1].detail
    assert gfake.account_lists == []
    # the group the login really holds is typed LOCATION_GROUP, and only its id appears in any request
    gfake.calls.clear()
    key = "333000333"
    already_in_group(gfake, key)
    checks = run(gfake, locations=[key])
    assert agency_check.ok(checks) and all(ORG not in (c[1] or "") for c in gfake.calls)
    # and a group typed ORGANIZATION by Google is refused even when the ids were not configured
    monkeypatch.setattr(settings, "google_agency_organization_id", "")
    gfake.group_type = "ORGANIZATION"
    assert by_name(run(gfake, locations=[key]))["accounts.list"][0].status == "FAIL"


def test_a_location_the_group_does_not_list_is_a_failure_and_is_not_read(gfake):
    biz = make_business("Missing Clinic")
    s = seed(biz)  # the client's connection exists, but the location was never added to the group
    checks = run(gfake, locations=[s.names[0]])
    got = by_name(checks)
    assert got["location match"][0].status == "FAIL" and "NOT listed" in got["location match"][0].detail
    assert got["location read"][0].status == "SKIP" and calls(gfake, "list_reviews") == []
    assert not agency_check.ok(checks)


def test_a_location_listed_under_another_account_is_not_group_access(gfake):
    key = "444000444"
    already_in_group(gfake, key)
    gfake.group_visible_account = "accounts/9999"  # listed, but somewhere that is not the group
    got = by_name(run(gfake, locations=[key]))
    assert got["location match"][0].status == "FAIL" and "accounts/9999" in got["location match"][0].detail and calls(gfake, "list_reviews") == []


def test_location_ids_are_normalised_and_a_non_numeric_id_never_becomes_a_request(gfake):
    key = "555000555"
    already_in_group(gfake, key)
    for form in (key, f"locations/{key}", f"accounts/777/locations/{key}"):
        assert agency_check.location_name(form) == f"locations/{key}"
    for bad in ("../etc", "locations/abc", "", "locations/1; drop"):
        with pytest.raises(ValueError):
            agency_check.location_name(bad)
    gfake.calls.clear()
    checks = run(gfake, locations=["locations/not-a-number"])
    assert checks[-1].name == "location match" and checks[-1].status == "FAIL" and calls(gfake, "list_reviews") == []


def test_the_check_finds_the_location_of_a_connection_by_its_selection_only(gfake):
    biz = make_business("By Connection Clinic")
    s = seed(biz, n=2)
    owner_exec("UPDATE google_locations SET selected = false WHERE id = :g", g=str(s.gids[1]))  # one is not selected
    already_in_group(gfake, s.key[0])
    already_in_group(gfake, s.key[1])
    got = by_name(run(gfake, connection_id=s.conn_id))
    assert len(got["location match"]) == 1 and s.key[0] in got["location match"][0].detail  # only the selected one is looked for
    assert s.key[1] not in text(run(gfake, connection_id=s.conn_id))


def test_the_check_reports_a_location_held_by_two_businesses_as_a_failure(gfake):
    a_biz, b_biz = make_business("Dup A Clinic"), make_business("Dup B Clinic")
    sa, sb = seed(a_biz), seed(b_biz)
    owner_exec("UPDATE google_locations SET google_location_name = :n WHERE id = :g", n=sa.names[0], g=str(sb.gids[0]))  # the same Google location, two businesses
    already_in_group(gfake, sa.key[0])
    got = by_name(run(gfake, locations=[sa.names[0]]))
    assert got["tenant mapping"][0].status == "FAIL" and "2 different businesses" in got["tenant mapping"][0].detail
    # it says HOW MANY, never which other business: no id of either business is in that line
    assert a_biz.tenant_id not in got["tenant mapping"][0].detail and b_biz.tenant_id not in got["tenant mapping"][0].detail
    assert not agency_check.ok(list(sum(got.values(), [])))


def test_the_check_never_shows_another_businesss_connection_when_asked_for_one_location(gfake):
    a_biz, b_biz = make_business("Only A Clinic"), make_business("Only B Clinic")
    sa, sb = seed(a_biz), seed(b_biz)
    already_in_group(gfake, sa.key[0])
    already_in_group(gfake, sb.key[0])
    out = text(run(gfake, locations=[sa.names[0]]))
    assert a_biz.tenant_id in out and b_biz.tenant_id not in out and str(sb.conn_id) not in out and sb.key[0] not in out


@pytest.mark.parametrize("which,err,expect", [
    ("accounts", GoogleAPIError(500, "boom"), "Google answered 500"),
    ("accounts", GoogleRateLimited(30), "rate limit"),
    ("accounts", GoogleApiNotApproved(403, "no"), "not approved"),
    ("group", GoogleAPIError(403, "denied", google_status="PERMISSION_DENIED"), "Google answered 403"),
    ("group", GoogleRateLimited(), "rate limit"),
    ("read", GoogleAPIError(429, "slow"), "Google answered 429"),
    ("read", GoogleRateLimited(), "rate limit"),
])
def test_google_errors_and_rate_limits_are_reported_at_the_step_that_met_them(gfake, monkeypatch, which, err, expect):
    key = "666000666"
    already_in_group(gfake, key)
    if which == "accounts":
        monkeypatch.setattr(gfake, "list_accounts", lambda token: (_ for _ in ()).throw(err))
    elif which == "group":
        gfake.group_list_error = err
    else:
        monkeypatch.setattr(gfake, "list_reviews", lambda *a, **k: (_ for _ in ()).throw(err))
    checks = run(gfake, locations=[key])
    failing = [c for c in checks if c.status == "FAIL"]
    assert failing and expect in failing[0].detail and not agency_check.ok(checks)
    assert {"accounts": "accounts.list", "group": "group locations", "read": "location read"}[which] == failing[0].name


def test_an_unusable_agency_token_is_reported_and_nothing_else_runs(gfake):
    gfake.fail_refresh_with = GoogleAuthRevoked("revoked")  # the agency login's refresh token no longer works
    owner_exec("UPDATE google_agency_accounts SET access_token_expires_at = now() - interval '1 hour'")  # so a refresh is needed
    checks = run(gfake, locations=["1"])
    assert [(c.name, c.status) for c in checks] == [("identity", "FAIL")] and "Could not use the agency token" in checks[0].detail
    assert gfake.account_lists == []


def test_the_check_command_prints_results_without_any_token_and_exits_by_outcome(gfake, capsys):
    from app import cli

    key = "777000777"
    already_in_group(gfake, key)
    args = SimpleNamespace(cmd="google-agency-check", expect_email=AGENCY_EMAIL, account=None, location=[key], connection_id=None, location_group_id=None)
    assert cli._agency_cli(args) == 0
    out = capsys.readouterr().out
    assert "[PASS] location read" in out and "READ-ONLY CHECK PASSED" in out and AGENCY_ACCESS not in out
    args.location = ["888000888"]  # a location the group does not list
    assert cli._agency_cli(args) == 1
    assert "[FAIL] location match" in capsys.readouterr().out
    args.expect_email = "someone.else@flowhq.example"
    assert cli._agency_cli(args) == 1 and "[FAIL] identity" in capsys.readouterr().out


# ================================================================== a client who already added FlowQR's group
def test_without_the_adoption_switch_a_listed_location_is_still_invited_as_before(gfake):
    biz = make_business("No Adopt Clinic")
    s = seed(biz)
    gfake.group_sees.add(s.key[0])  # already listed under the group, no admin entry the flow could recognise
    assert settings.google_agency_adopt_existing_access is False  # the default
    assert go(biz, s) == [("active", None)]
    assert len(calls(gfake, "invite_group")) == 1 and calls(gfake, "invite_group")[0][2] == CLIENT_ACCESS  # the old behaviour: the CLIENT's token sends another invitation


def test_a_location_already_in_the_group_is_verified_directly_without_an_invitation_or_the_clients_token(adopt):
    biz = make_business("Existing Group Clinic")
    s = seed(biz)
    already_in_group(adopt, s.key[0])
    assert go(biz, s) == [("active", None)]
    assert calls(adopt, "invite_group") == [] and calls(adopt, "invite") == [] and adopt.requests == []  # nothing was sent to Google
    assert client_token_calls(adopt) == []  # the client's token was never used for anything before the switch
    assert [(c[0], c[2]) for c in adopt.calls if c[0] != "revoke"] == [("list_group_locations", AGENCY_ACCESS), ("list_group_locations", AGENCY_ACCESS), ("list_admins", AGENCY_ACCESS)]
    (a,) = auths_of(s)
    assert a.target_type == "flowhq_location_group" and a.target_account_name == GROUP and a.agency_account_name == GROUP and a.agency_account_id == agency_row().id
    assert a.invite_sent_at == a.accepted_at and a.invitation_name is None and a.verified_at and a.switched_at and a.admin_resource_name  # recorded as access FlowQR already had; the manager entry is named from the list
    c, gl = conn_of(s), gloc_of(s.gids[0])
    assert c.auth_mode == "agency_account" and c.agency_account_id == agency_row().id
    assert gl.google_account_name == GROUP and gl.client_google_account_name == "accounts/111"
    # the adoption is on the record, and the separate notice goes out like for any other client
    rows = owner_query("SELECT action FROM audit_logs WHERE tenant_id = :t AND action = 'google.agency.adopted_existing'", t=biz.tenant_id)
    assert len(rows) == 1
    (m,) = mail(biz.email, "now a manager")
    assert "FlowQR's business group (accounts/5488245563)" in m["body"]


def test_the_same_consent_is_still_required_before_an_existing_location_is_touched(adopt):
    biz = make_business("Consent First Clinic")
    s = seed(biz)
    already_in_group(adopt, s.key[0])
    r = biz.post("/google/agency/consent", json={"connection_id": str(s.conn_id), "agree": False, "consent_version": agency.CONSENT_VERSION})
    assert r.status_code == 422 and adopt.calls == [] and auths_of(s) == []
    with pytest.raises(agency.ConsentRequired):
        with closing(system_session()) as db:
            agency.advance_connection(db, db.get(GoogleConnection, s.conn_id), force=True)
    assert adopt.calls == []
    untouched(s)


def test_a_location_that_is_not_in_the_group_is_still_invited_when_adoption_is_on(adopt):
    biz = make_business("Not Yet Clinic")
    s = seed(biz)
    assert go(biz, s) == [("active", None)]
    assert len(calls(adopt, "invite_group")) == 1  # the normal invitation: the client's token invites the group
    assert [c[0] for c in adopt.calls][:3] == ["list_group_locations", "list_admins", "invite_group"]  # the adoption look came first and found nothing


def test_no_token_is_switched_while_the_groups_own_entry_is_still_pending(adopt):
    biz = make_business("Pending Clinic")
    s = seed(biz)
    already_in_group(adopt, s.key[0], pending=True)  # listed, but the group's admin entry is not settled
    assert go(biz, s) == [("accepted", "group_invite_pending")]
    untouched(s)  # connection, client token and account name unchanged
    assert "revoke" not in [c[0] for c in adopt.calls]


def test_a_group_role_other_than_manager_stops_the_switch(adopt):
    biz = make_business("Odd Role Clinic")
    s = seed(biz)
    already_in_group(adopt, s.key[0], role="OWNER")
    result = go(biz, s)
    assert result == [("needs_attention", "unexpected_role")]
    untouched(s)


def test_an_agency_login_without_group_access_stops_before_anything_else(adopt):
    biz = make_business("No Access Clinic")
    s = seed(biz)
    already_in_group(adopt, s.key[0])
    adopt.agency_in_group = False
    (st,) = go(biz, s)
    assert st == ("needs_attention", "group_access_missing")
    assert client_token_calls(adopt) == [] and calls(adopt, "invite_group") == [] and calls(adopt, "list_group_locations") == []
    untouched(s)


@pytest.mark.parametrize("err,status,code", [
    (denied(), "needs_attention", "group_access_missing"),
    (GoogleAPIError(503, "down"), "consented", "adopt_retry"),
    (GoogleRateLimited(60), "consented", "rate_limited"),
    (GoogleApiNotApproved(403, "no"), "needs_attention", "api_not_approved"),
])
def test_google_errors_while_looking_for_the_group_access_never_fall_through_to_an_invitation(adopt, err, status, code):
    biz = make_business("Error Clinic")
    s = seed(biz)
    adopt.group_list_error = err
    assert go(biz, s) == [(status, code)]
    assert calls(adopt, "invite_group") == [] and client_token_calls(adopt) == []  # a failed look is not "not listed": nothing was invited
    untouched(s)


def test_a_second_business_cannot_take_over_a_location_another_business_already_holds(adopt):
    a_biz, b_biz = make_business("Owner Clinic"), make_business("Latecomer Clinic")
    sa, sb = seed(a_biz), seed(b_biz)
    owner_exec("UPDATE google_locations SET google_location_name = :n WHERE id = :g", n=sa.names[0], g=str(sb.gids[0]))  # B claims A's Google location
    already_in_group(adopt, sa.key[0])
    consent(a_biz, sa)  # A has an open authorization for it
    with pytest.raises(agency.LocationAlreadyManaged):  # refused UP FRONT (onboarding's platform-wide rule: one open authorization per Google location), before anything reaches Google
        consent(b_biz, sb)
    untouched(sb)
    assert client_token_calls(adopt) == [] and calls(adopt, "invite_group") == [] and auths_of(sb) == []
    assert [a.status for a in auths_of(sa)] == ["consented"]  # A's record was not touched
    owner_exec("DELETE FROM google_agency_authorizations WHERE connection_id = :c", c=str(sa.conn_id))  # A never advanced; clean up so it does not hold a slot


def test_the_adopt_step_still_refuses_a_claimed_location_if_the_up_front_rule_is_ever_bypassed(adopt):
    """Defence in depth: the adopt step looks the location up again, by its Google id, across businesses (a row written before the platform-wide rule existed has no resource name recorded)."""
    a_biz, b_biz = make_business("Owner Clinic Two"), make_business("Latecomer Clinic Two")
    sa, sb = seed(a_biz), seed(b_biz)
    owner_exec("UPDATE google_locations SET google_location_name = :n WHERE id = :g", n=sa.names[0], g=str(sb.gids[0]))
    already_in_group(adopt, sa.key[0])
    consent(a_biz, sa)
    owner_exec("UPDATE google_agency_authorizations SET google_location_resource = NULL WHERE connection_id = :c", c=str(sa.conn_id))  # as if recorded before 0063
    consent(b_biz, sb)  # so the up-front rule cannot see it ...
    assert advance(sb, force=True) == [("needs_attention", "location_claimed")]  # ... and the adopt step does
    untouched(sb)
    assert client_token_calls(adopt) == [] and calls(adopt, "invite_group") == []
    assert mail(subject_has="two businesses claim one Google location")
    owner_exec("DELETE FROM google_agency_authorizations WHERE connection_id IN (:a, :b)", a=str(sa.conn_id), b=str(sb.conn_id))


def test_an_adopted_connection_never_copies_the_groups_other_locations_into_the_business(adopt):
    biz = make_business("Isolated Clinic")
    s = seed(biz)
    already_in_group(adopt, s.key[0])
    for other in ("910000001", "910000002"):
        adopt.group_sees.add(other)
    assert go(biz, s) == [("active", None)]
    rows = owner_query("SELECT google_location_name FROM google_locations WHERE tenant_id = :t", t=biz.tenant_id)
    assert [r[0] for r in rows] == [s.names[0]]  # exactly its own location
    r = biz.post(f"/google/connections/{s.conn_id}/refresh-locations")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "managed_by_flowqr"
    assert owner_query("SELECT count(*) FROM google_locations WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 1
    assert calls(adopt, "list_locations") == []  # the full group listing was never even requested


def test_several_businesses_can_share_the_agency_login_and_each_stays_inside_its_own_location(adopt):
    a_biz, b_biz = make_business("Share A Clinic"), make_business("Share B Clinic")
    sa, sb = seed(a_biz), seed(b_biz)
    already_in_group(adopt, sa.key[0])
    already_in_group(adopt, sb.key[0])
    assert go(a_biz, sa) == [("active", None)] and go(b_biz, sb) == [("active", None)]
    assert conn_of(sa).agency_account_id == conn_of(sb).agency_account_id == agency_row().id  # one login, two businesses
    # each business's sync touches only its own location, with the agency token, under the group account
    adopt.calls.clear()
    with closing(system_session()) as db:
        sync_google_location(db, db.get(GoogleLocation, sa.gids[0]), adopt, sleep=lambda x: None)
    (c,) = calls(adopt, "list_reviews")
    assert c[1] == f"{GROUP}/{sa.names[0]}" and c[2] == AGENCY_ACCESS and sb.key[0] not in c[1]
    # row-level security: each business sees only its own authorization
    for biz_, s_, other in ((a_biz, sa, sb), (b_biz, sb, sa)):
        with closing(SessionLocal()) as db:
            set_rls_context(db, tenant_id=uuid.UUID(biz_.tenant_id))
            seen = db.scalars(select(Auth)).all()
        assert [x.connection_id for x in seen] == [s_.conn_id] and other.conn_id not in [x.connection_id for x in seen]


def test_the_adoption_switch_alone_does_nothing_without_the_main_switch(gfake, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_adopt_existing_access", True)
    monkeypatch.setattr(settings, "google_agency_manager_enabled", False)
    biz = make_business("Switch Off Clinic")
    s = seed(biz)
    already_in_group(gfake, s.key[0])
    with pytest.raises(agency.AgencyDisabled):
        with closing(system_session()) as db:
            agency.advance_connection(db, db.get(GoogleConnection, s.conn_id), force=True)
    assert gfake.calls == [] and biz.get("/google/agency/status").status_code == 404
    untouched(s)


def test_the_production_guard_covers_the_new_settings():
    def prod(**over):
        base = dict(app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True, public_card_base_url="https://go.flowqr.co.in",
                    frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in", database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr",
                    platform_admin_emails="ops@flowhq.in", smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
                    card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback", google_client_id="id", google_client_secret="secret")
        base.update(over)
        return Settings(_env_file=None, **base)

    def mine(**over):
        return [p for p in config_problems(prod(**over)) if "ADOPT_EXISTING" in p or "KEEP_HOURS" in p]

    on = dict(google_agency_manager_enabled=True, agency_token_encryption_key=Fernet.generate_key().decode(), google_agency_location_group_id="5488245563")
    assert any("needs GOOGLE_AGENCY_MANAGER_ENABLED" in p for p in mine(google_agency_adopt_existing_access=True))  # alone it would do nothing
    assert any("needs GOOGLE_AGENCY_LOCATION_GROUP_ID" in p for p in mine(google_agency_manager_enabled=True, agency_token_encryption_key=Fernet.generate_key().decode(),
                                                                          google_agency_individual_fallback=True, google_agency_adopt_existing_access=True))
    assert mine(google_agency_adopt_existing_access=True, **on) == []
    for bad in (-1, 721):
        assert any("KEEP_HOURS" in p for p in mine(google_agency_client_token_keep_hours=bad))
    assert mine(google_agency_client_token_keep_hours=168) == [] and mine() == []  # a valid window and the defaults say nothing
    assert Settings(_env_file=None).google_agency_adopt_existing_access is False and Settings(_env_file=None).google_agency_client_token_keep_hours == 0


# ================================================================== keeping the client's token, and rolling back
def test_with_a_keep_window_the_clients_token_is_held_unused_until_it_ends(adopt, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_client_token_keep_hours", 168)
    biz = make_business("Keep Window Clinic")
    s = seed(biz)
    already_in_group(adopt, s.key[0])
    assert go(biz, s) == [("active", None)]
    c = conn_of(s)
    assert c.auth_mode == "agency_account" and c.refresh_token_encrypted and get_cipher().decrypt(c.refresh_token_encrypted) == CLIENT_REFRESH  # still held, encrypted
    assert "revoke" not in [x[0] for x in adopt.calls] and auths_of(s)[0].client_token_revoked_at is None
    with closing(system_session()) as db:  # the work runs on the AGENCY token, never the held client token
        assert get_access_token(db, db.get(GoogleConnection, s.conn_id), adopt) == AGENCY_ACCESS
    # housekeeping inside the window revokes nothing and raises no "could not revoke" alert
    owner_exec("UPDATE google_agency_authorizations SET switched_at = now() - interval '30 hours' WHERE connection_id = :c", c=str(s.conn_id))
    with closing(system_session()) as db:
        out = agency.housekeeping(db, client=adopt, provider=adopt)
    assert out["revoked"] == 0 and out["alerts"] == 0 and "revoke" not in [x[0] for x in adopt.calls]
    assert conn_of(s).refresh_token_encrypted
    # once the window has passed the token is revoked at Google and dropped
    owner_exec("UPDATE google_connections SET agency_switched_at = now() - interval '169 hours' WHERE id = :c", c=str(s.conn_id))
    with closing(system_session()) as db:
        out = agency.housekeeping(db, client=adopt, provider=adopt)
    assert out["revoked"] == 1 and ("revoke", None, CLIENT_REFRESH) in adopt.calls
    assert conn_of(s).refresh_token_encrypted is None and auths_of(s)[0].client_token_revoked_at


def test_the_consent_text_tells_the_truth_about_the_keep_window(monkeypatch):
    now_text, now_sha = agency.consent_text(), agency.consent_sha()
    assert "signs out of the Google login you just used and revokes it" in now_text and "hours" not in now_text  # the default wording is unchanged
    monkeypatch.setattr(settings, "google_agency_client_token_keep_hours", 168)
    later = agency.consent_text()
    assert "168 hours" in later and "signs out of the Google login" not in later  # what is said is what happens
    assert agency.consent_sha() != now_sha  # the stored hash is of the wording the client actually saw


def test_rollback_puts_the_connection_back_on_the_clients_own_login(adopt, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_client_token_keep_hours", 168)
    biz = make_business("Rollback Clinic")
    s = seed(biz)
    already_in_group(adopt, s.key[0])
    go(biz, s)
    with closing(system_session()) as db:
        agency.rollback_to_client_token(db, db.get(GoogleConnection, s.conn_id), provider=adopt)
    c, (a,), gl = conn_of(s), auths_of(s), gloc_of(s.gids[0])
    assert c.auth_mode == "client_token" and c.agency_account_id is None and c.agency_switched_at is None and c.status == GoogleConnectionStatus.active
    assert gl.google_account_name == "accounts/111"  # the client's own account again
    assert (a.status, a.failure_code) == ("cancelled", "rolled_back")
    with closing(system_session()) as db:
        assert get_access_token(db, db.get(GoogleConnection, s.conn_id), adopt) == CLIENT_ACCESS
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'google.agency.rolled_back'", t=biz.tenant_id)[0][0] == 1
    assert "remove" not in [x[0] for x in adopt.calls]  # Google's side was not touched: FlowQR's group is still a manager there


def test_rollback_is_refused_and_changes_nothing_when_the_clients_token_is_gone_or_broken(adopt, monkeypatch):
    biz = make_business("No Rollback Clinic")
    s = seed(biz)
    already_in_group(adopt, s.key[0])
    go(biz, s)  # default keep window 0: the client's token was revoked and dropped
    assert conn_of(s).refresh_token_encrypted is None
    with pytest.raises(agency.AgencyError) as e:
        with closing(system_session()) as db:
            agency.rollback_to_client_token(db, db.get(GoogleConnection, s.conn_id), provider=adopt)
    assert "reconnect Google" in str(e.value) and conn_of(s).auth_mode == "agency_account"
    # a held token that no longer works is refused too, and the connection stays as it was
    monkeypatch.setattr(settings, "google_agency_client_token_keep_hours", 168)
    biz2 = make_business("Broken Token Clinic")
    s2 = seed(biz2)
    already_in_group(adopt, s2.key[0])
    go(biz2, s2)
    monkeypatch.setattr(adopt, "refresh_access_token", lambda t: (_ for _ in ()).throw(GoogleAuthRevoked("gone")))
    with pytest.raises(agency.AgencyError):
        with closing(system_session()) as db:
            agency.rollback_to_client_token(db, db.get(GoogleConnection, s2.conn_id), provider=adopt)
    c = conn_of(s2)
    assert c.auth_mode == "agency_account" and c.agency_account_id and gloc_of(s2.gids[0]).google_account_name == GROUP and [a.status for a in auths_of(s2)] == ["active"]
    # and a connection that is not agency-managed has nothing to roll back
    s3 = seed(make_business("Plain Clinic"))
    with pytest.raises(agency.AgencyError):
        with closing(system_session()) as db:
            agency.rollback_to_client_token(db, db.get(GoogleConnection, s3.conn_id), provider=adopt)


def test_the_rollback_command_reports_by_exit_code(adopt, monkeypatch, capsys):
    from app import cli

    monkeypatch.setattr(settings, "google_agency_client_token_keep_hours", 168)
    biz = make_business("Cli Rollback Clinic")
    s = seed(biz)
    already_in_group(adopt, s.key[0])
    go(biz, s)
    monkeypatch.setattr(g, "get_google_provider", lambda: adopt)
    assert cli._agency_cli(SimpleNamespace(cmd="google-agency-rollback", connection_id=s.conn_id)) == 0
    assert "uses the client's own Google login again" in capsys.readouterr().out and conn_of(s).auth_mode == "client_token"
    assert cli._agency_cli(SimpleNamespace(cmd="google-agency-rollback", connection_id=s.conn_id)) == 1  # nothing left to roll back
    assert cli._agency_cli(SimpleNamespace(cmd="google-agency-rollback", connection_id=uuid.uuid4())) == 1


# ================================================================== stopping a location that was adopted
def test_stopping_an_adopted_location_is_not_reported_as_done_when_the_manager_entry_cannot_be_named(adopt, monkeypatch):
    biz = make_business("Stop Adopted Clinic")
    s = seed(biz)
    already_in_group(adopt, s.key[0])
    go(biz, s)
    owner_exec("UPDATE google_agency_authorizations SET admin_resource_name = NULL WHERE connection_id = :c", c=str(s.conn_id))  # nothing names the entry
    adopt.admins[s.key[0]] = []  # and the list does not return it either
    with closing(system_session()) as db:
        agency.request_stop(db, db.get(GoogleConnection, s.conn_id), client=adopt, provider=adopt)
    (a,) = auths_of(s)
    assert a.status == "stopping" and a.failure_code == "removal_refused" and a.removed_at is None  # FlowQR is still a manager: a person must remove it, and is alerted near the deadline
    assert "remove" not in [x[0] for x in adopt.calls]  # no request was made with a guessed name
    # once Google no longer lists the location for the agency login, the access really is gone and it is closed
    adopt.hidden.add(s.key[0])
    with closing(system_session()) as db:
        agency.housekeeping(db, client=adopt, provider=adopt)
    assert auths_of(s)[0].status == "stopped"


def test_stopping_an_adopted_location_removes_the_group_by_the_name_the_verification_recorded(adopt):
    biz = make_business("Stop Named Clinic")
    s = seed(biz)
    already_in_group(adopt, s.key[0])
    go(biz, s)
    with closing(system_session()) as db:
        agency.request_stop(db, db.get(GoogleConnection, s.conn_id), client=adopt, provider=adopt)
    (a,) = auths_of(s)
    assert a.status == "stopped" and a.removed_at
    (rm,) = calls(adopt, "remove")
    assert rm[1] == f"locations/{s.key[0]}/admins/pre{s.key[0]}" and rm[2] == AGENCY_ACCESS
    assert s.key[0] not in adopt.group_sees  # the group no longer lists it
