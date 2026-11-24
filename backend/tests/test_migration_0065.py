"""Migration 0065 (agency tenant grants): platform-only, one open grant per business, additive, reversible."""
import pytest
from sqlalchemy.exc import IntegrityError, ProgrammingError

from tests.conftest import head_revision, make_business, owner_exec, owner_query
from tests.test_migration_0037 import alembic


def test_the_table_exists_is_platform_only_and_allows_one_open_grant_per_business():
    biz = make_business("Grant Migration Clinic")
    owner_exec("DELETE FROM google_agency_tenant_grants")
    owner_exec("INSERT INTO google_agency_tenant_grants (id, tenant_id, granted_by_email, granted_at) VALUES (gen_random_uuid(), :t, 'op@flowhq.example', now())", t=biz.tenant_id)
    with pytest.raises(IntegrityError):
        owner_exec("INSERT INTO google_agency_tenant_grants (id, tenant_id, granted_by_email, granted_at) VALUES (gen_random_uuid(), :t, 'op@flowhq.example', now())", t=biz.tenant_id)
    owner_exec("UPDATE google_agency_tenant_grants SET revoked_at = now(), revoked_by_email = 'op@flowhq.example' WHERE tenant_id = :t", t=biz.tenant_id)
    owner_exec("INSERT INTO google_agency_tenant_grants (id, tenant_id, granted_by_email, granted_at) VALUES (gen_random_uuid(), :t, 'op@flowhq.example', now())", t=biz.tenant_id)  # a closed grant frees the slot
    with pytest.raises(IntegrityError):  # a revoked row must say who revoked it
        owner_exec("UPDATE google_agency_tenant_grants SET revoked_at = now() WHERE tenant_id = :t AND revoked_at IS NULL", t=biz.tenant_id)
    owner_exec("DELETE FROM google_agency_tenant_grants")
    rls = owner_query("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'google_agency_tenant_grants'")[0]
    assert rls == (True, True)
    privs = {r[0] for r in owner_query("SELECT privilege_type FROM information_schema.role_table_grants WHERE table_name = 'google_agency_tenant_grants' AND grantee = 'flowqr_app'")}
    assert {"SELECT", "INSERT", "UPDATE"} <= privs and "DELETE" not in privs


def test_a_business_session_cannot_read_or_write_a_grant():
    from contextlib import closing

    from app.core.db import SessionLocal, set_rls_context

    biz = make_business("Grant Isolation Clinic")
    with closing(SessionLocal()) as db:
        set_rls_context(db, tenant_id=biz.tenant_id)
        assert db.execute(__import__("sqlalchemy").text("SELECT count(*) FROM google_agency_tenant_grants")).scalar() == 0
        with pytest.raises(ProgrammingError):
            db.execute(__import__("sqlalchemy").text("INSERT INTO google_agency_tenant_grants (id, tenant_id, granted_by_email, granted_at) VALUES (gen_random_uuid(), :t, 'x@y.z', now())"), {"t": biz.tenant_id})
        db.rollback()


def test_the_downgrade_removes_the_table_and_the_upgrade_restores_it():
    alembic("downgrade", "0064")
    try:
        assert owner_query("SELECT to_regclass('public.google_agency_tenant_grants')")[0][0] is None
    finally:
        alembic("upgrade", "head")
    assert owner_query("SELECT to_regclass('public.google_agency_tenant_grants')")[0][0] is not None
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] == head_revision()
