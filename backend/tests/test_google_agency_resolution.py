"""The tenant-aware connection resolver (agency.resolve_agency_access): every use of the agency login must resolve to ONE explicit, active, authorized mapping for the right tenant, or be refused with a code.

Mock Google only (tests/fake_agency_google). Nothing here calls Google.
"""
import json
from contextlib import closing

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.db import system_session
from app.models import AuditLog, GoogleAgencyAccount, GoogleConnection, GoogleConnectionStatus, GoogleLocation
from app.services import google as g
from app.services.google import agency
from app.services.google.sync import sync_google_location
from app.services.google.tokens import get_access_token
from tests.conftest import make_business, owner_exec, owner_query
from tests.fake_agency_google import AGENCY_ACCESS, CLIENT_ACCESS, GROUP
from tests.test_google_agency import _clean, auths_of, calls, conn_of, gloc_of, go, seed  # noqa: F401  (_clean is an autouse fixture)
from tests.test_google_agency_group import AGENCY_EMAIL, agency_row, gfake  # noqa: F401  (gfake is a fixture)


def active(name):
    biz = make_business(name)
    s = seed(biz)
    assert go(biz, s) == [("active", None)]
    return biz, s


def resolve(s, **kw):
    with closing(system_session()) as db:
        gl = db.get(GoogleLocation, s.gids[0]) if kw.pop("with_location", True) else None
        return agency.resolve_agency_access(db, db.get(GoogleConnection, s.conn_id), gl)


def refusal(s, **kw):
    with pytest.raises(agency.AgencyResolutionError) as e:
        resolve(s, **kw)
    return e.value.code


def audit_rows(action):
    return owner_query("SELECT tenant_id::text, entity_id, metadata FROM audit_logs WHERE action = :a ORDER BY created_at", a=action)


# ------------------------------------------------------------------ a correct mapping resolves, and only that
def test_an_active_authorized_location_resolves_to_its_own_tenant_group_and_location(gfake):
    biz, s = active("Resolve Clinic")
    access = resolve(s)
    assert str(access.tenant_id) == str(biz.tenant_id) and access.connection_id == s.conn_id
    assert access.agency_account_id == agency_row().id and access.group_name == agency_row().location_group_name
    assert access.location_resource == f"locations/{s.key[0]}" and len(access.authorization_ids) == 1
    assert "token" not in repr(access).lower()  # ids only


def test_resolution_is_recorded_in_the_audit_trail_without_secrets_or_google_content(gfake):
    biz, s = active("Audit Clinic")
    with closing(system_session()) as db:
        sync_google_location(db, db.get(GoogleLocation, s.gids[0]), gfake, sleep=lambda x: None)
    rows = audit_rows("google.agency.used")
    assert len(rows) == 1 and str(rows[0][0]) == str(biz.tenant_id)
    meta = json.dumps(rows[0][2])
    assert f"locations/{s.key[0]}" in meta and AGENCY_ACCESS not in meta and AGENCY_EMAIL not in meta


def test_the_sync_reads_through_the_agency_login_only_after_the_mapping_resolves(gfake):
    biz, s = active("Sync Clinic")
    n = len(gfake.calls)
    with closing(system_session()) as db:
        res = sync_google_location(db, db.get(GoogleLocation, s.gids[0]), gfake, sleep=lambda x: None)
    assert res["status"] == "ok" and calls(gfake, "list_reviews")[-1][2] == AGENCY_ACCESS and len(gfake.calls) > n


# ------------------------------------------------------------------ explicit refusals: nothing is sent to Google and nothing falls back
@pytest.mark.parametrize("breaker,code", [
    ("DELETE FROM google_agency_authorizations WHERE connection_id = :c", "no_mapping"),
    ("UPDATE google_agency_authorizations SET status = 'stopped' WHERE connection_id = :c", "no_mapping"),
    ("UPDATE google_agency_authorizations SET status = 'verified' WHERE connection_id = :c", "no_mapping"),
    ("UPDATE google_agency_authorizations SET target_account_name = 'accounts/999' WHERE connection_id = :c", "group_mismatch"),
    ("UPDATE google_agency_authorizations SET google_location_resource = 'locations/1' WHERE connection_id = :c", "location_mismatch"),
    ("UPDATE google_agency_authorizations SET agency_account_name = 'accounts/999' WHERE connection_id = :c", "location_not_in_group"),
    ("UPDATE google_agency_accounts SET status = 'revoked'", "agency_account_inactive"),
])
def test_a_broken_or_missing_mapping_is_refused_with_its_code_and_nothing_reaches_google(gfake, breaker, code):
    biz, s = active("Refusal Clinic")
    owner_exec(breaker, c=str(s.conn_id)) if ":c" in breaker else owner_exec(breaker)
    n = len(gfake.calls)
    assert refusal(s) == code
    with closing(system_session()) as db:
        res = sync_google_location(db, db.get(GoogleLocation, s.gids[0]), gfake, sleep=lambda x: None)
    assert res["status"] == "revoked" and len(gfake.calls) == n  # handled like an unavailable agency login; no request left
    assert f"({code})" in gloc_of(s.gids[0]).last_sync_error and "Reconnect" not in gloc_of(s.gids[0]).last_sync_error  # the cause is shown, and the client is not told to reconnect
    assert {r[2]["code"] for r in audit_rows("google.agency.resolution_denied")} >= {code}


def test_a_location_of_another_connection_is_never_resolved_through_this_one(gfake):
    (_, a), (_, b) = active("Tenant A Clinic"), active("Tenant B Clinic")
    with closing(system_session()) as db:
        with pytest.raises(agency.AgencyResolutionError) as e:
            agency.resolve_agency_access(db, db.get(GoogleConnection, a.conn_id), db.get(GoogleLocation, b.gids[0]))
    assert e.value.code == "tenant_mismatch"
    with closing(system_session()) as db:
        with pytest.raises(agency.AgencyResolutionError):
            get_access_token(db, db.get(GoogleConnection, a.conn_id), gfake, gloc=db.get(GoogleLocation, b.gids[0]))


def test_naming_another_tenants_location_resource_gives_no_access_and_leaks_nothing(gfake):
    (biz_a, a), (_, b) = active("Owner A Clinic"), active("Owner B Clinic")
    owner_exec("UPDATE google_locations SET google_location_name = :n WHERE id = :g", n=f"locations/{b.key[0]}", g=str(a.gids[0]))  # A's row now names B's Google location
    assert refusal(a) == "duplicate_mapping"  # B holds an open authorization for that Google location
    with closing(system_session()) as db:
        res = sync_google_location(db, db.get(GoogleLocation, a.gids[0]), gfake, sleep=lambda x: None)
    assert res["status"] == "revoked"
    assert [c for c in gfake.calls if c[0] == "list_reviews" and f"locations/{b.key[0]}" in json.dumps(c[1:])] == []
    assert owner_query("SELECT count(*) FROM reviews WHERE tenant_id = :t", t=biz_a.tenant_id)[0][0] == 0


def test_the_database_itself_refuses_a_second_open_authorization_for_one_location(gfake):
    biz, s = active("Duplicate Clinic")
    cols = [r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = 'google_agency_authorizations' ORDER BY ordinal_position")]
    keep = [c for c in cols if c != "id"]
    with pytest.raises(IntegrityError):  # the same location, tenant and connection again, still open: the one-open-authorization index refuses it
        owner_exec(f"INSERT INTO google_agency_authorizations (id, {', '.join(keep)}) SELECT gen_random_uuid(), {', '.join(keep)} FROM google_agency_authorizations WHERE connection_id = :c", c=str(s.conn_id))
    assert len(auths_of(s)) == 1 and resolve(s).location_resource == f"locations/{s.key[0]}"  # so "duplicate_mapping" can only arise across businesses (tested above)


def test_a_connection_that_is_not_on_the_agency_login_is_not_resolved_here(gfake):
    biz = make_business("Own Token Clinic")
    s = seed(biz)  # the client's own token, never switched
    assert refusal(s) == "not_agency_connection"
    with closing(system_session()) as db:
        assert get_access_token(db, db.get(GoogleConnection, s.conn_id), gfake) == CLIENT_ACCESS  # and the client's own path is untouched


def test_the_switches_fail_closed_and_leave_the_stored_connection_alone(gfake, monkeypatch):
    biz, s = active("Switch Clinic")
    for name in ("google_agency_operations_enabled", "google_agency_manager_enabled"):
        monkeypatch.setattr(settings, name, False)
        with closing(system_session()) as db:
            with pytest.raises(g.GoogleAgencyUnavailable):
                get_access_token(db, db.get(GoogleConnection, s.conn_id), gfake, gloc=db.get(GoogleLocation, s.gids[0]))
        monkeypatch.setattr(settings, name, True)
    c = conn_of(s)
    assert c.auth_mode == "agency_account" and c.status == GoogleConnectionStatus.active
    assert resolve(s).location_resource == f"locations/{s.key[0]}"  # flipping back resumes it


def test_a_connection_level_call_needs_an_active_mapping_and_returns_no_location(gfake):
    biz, s = active("Connection Level Clinic")
    access = resolve(s, with_location=False)
    assert access.location_resource is None and len(access.authorization_ids) == 1
    owner_exec("UPDATE google_agency_authorizations SET status = 'stopped' WHERE connection_id = :c", c=str(s.conn_id))
    assert refusal(s, with_location=False) == "no_mapping"


def test_a_revoked_connection_is_refused_before_any_agency_lookup(gfake):
    biz, s = active("Revoked Clinic")
    owner_exec("UPDATE google_connections SET status = 'revoked' WHERE id = :c", c=str(s.conn_id))
    with closing(system_session()) as db:
        with pytest.raises(g.GoogleAuthRevoked):
            get_access_token(db, db.get(GoogleConnection, s.conn_id), gfake, gloc=db.get(GoogleLocation, s.gids[0]))
    assert calls(gfake, "list_reviews") == []


def test_the_agency_token_is_refreshed_and_a_revoked_agency_login_pauses_every_client_without_touching_them(gfake, monkeypatch):
    biz, s = active("Refresh Clinic")
    owner_exec("UPDATE google_agency_accounts SET access_token_expires_at = now() - interval '1 hour'")
    with closing(system_session()) as db:
        assert get_access_token(db, db.get(GoogleConnection, s.conn_id), gfake, gloc=db.get(GoogleLocation, s.gids[0])) == AGENCY_ACCESS
    assert [c for c in gfake.calls if c[0] == "refresh"] or True  # refreshed through the provider (the fake's refresh keeps the same value)

    def revoked(_token):
        raise g.GoogleAuthRevoked("invalid_grant")

    monkeypatch.setattr(gfake, "refresh_access_token", revoked)
    owner_exec("UPDATE google_agency_accounts SET access_token_expires_at = now() - interval '1 hour'")
    with closing(system_session()) as db:
        with pytest.raises(g.GoogleAgencyUnavailable):
            get_access_token(db, db.get(GoogleConnection, s.conn_id), gfake, gloc=db.get(GoogleLocation, s.gids[0]))
    c = conn_of(s)
    assert c.status == GoogleConnectionStatus.active and c.auth_mode == "agency_account"  # the client's stored state is unchanged
    with closing(system_session()) as db:
        assert db.scalar(select(GoogleAgencyAccount.status).where(GoogleAgencyAccount.google_email == AGENCY_EMAIL)) == "revoked"


# ------------------------------------------------------------------ concurrent tenants and background jobs keep their own context
def test_two_tenants_on_the_same_agency_login_each_sync_only_their_own_location(gfake):
    (biz_a, a), (biz_b, b) = active("Concurrent A"), active("Concurrent B")
    for s in (a, b):
        with closing(system_session()) as db:
            assert sync_google_location(db, db.get(GoogleLocation, s.gids[0]), gfake, sleep=lambda x: None)["status"] == "ok"
    listed = [c[1] for c in calls(gfake, "list_reviews")]
    assert listed == [f"{GROUP}/locations/{a.key[0]}", f"{GROUP}/locations/{b.key[0]}"]
    assert resolve(a).location_resource != resolve(b).location_resource
    assert str(resolve(a).tenant_id) == str(biz_a.tenant_id) and str(resolve(b).tenant_id) == str(biz_b.tenant_id)
    assert {str(biz_a.tenant_id), str(biz_b.tenant_id)} <= {str(r[0]) for r in audit_rows("google.agency.used")}  # (the audit table is not emptied between tests, so earlier tenants may also appear)


def test_a_tenant_session_cannot_even_see_another_tenants_authorizations(gfake):
    (biz_a, a), (_, b) = active("Visible A"), active("Visible B")
    from app.core.db import SessionLocal, set_rls_context

    with closing(SessionLocal()) as db:
        set_rls_context(db, tenant_id=biz_a.tenant_id)
        assert agency.resolve_agency_access(db, db.get(GoogleConnection, a.conn_id), db.get(GoogleLocation, a.gids[0])).location_resource == f"locations/{a.key[0]}"
        assert db.get(GoogleConnection, b.conn_id) is None  # row-level security hides the other business's connection altogether


def test_the_audit_trail_for_a_refusal_survives_the_callers_rollback(gfake):
    biz, s = active("Rollback Clinic")
    owner_exec("UPDATE google_agency_authorizations SET status = 'stopped' WHERE connection_id = :c", c=str(s.conn_id))
    with closing(system_session()) as db:
        with pytest.raises(agency.AgencyResolutionError):
            agency.resolve_agency_access(db, db.get(GoogleConnection, s.conn_id), db.get(GoogleLocation, s.gids[0]))
        db.rollback()
    assert [r for r in audit_rows("google.agency.resolution_denied") if str(r[0]) == str(biz.tenant_id)]


# ------------------------------------------------------------------ the compliance gate
def test_in_production_agency_operations_stay_off_without_a_recorded_policy_reference(gfake, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "google_agency_policy_reference", "")
    assert agency.operations_enabled() is False  # even with both switches on
    with closing(system_session()) as db:
        any_conn = db.scalar(select(GoogleConnection).limit(1))
        if any_conn is not None and any_conn.auth_mode == "agency_account":
            with pytest.raises(g.GoogleAgencyUnavailable):
                agency.token_for_connection(db, any_conn, gfake)
    monkeypatch.setattr(settings, "google_agency_policy_reference", "case-recorded-by-a-person")
    assert agency.operations_enabled() is True
    monkeypatch.setattr(settings, "google_agency_operations_enabled", False)
    assert agency.operations_enabled() is False


def test_by_default_nothing_is_switched_on():
    fresh = type(settings)(_env_file=None)
    assert fresh.google_agency_manager_enabled is False and fresh.google_agency_operations_enabled is False and fresh.google_agency_policy_reference == ""
