"""Migration 0040 (prepaid orders): additive, tenant-isolated, reversible, and it touches no existing row."""
import os

from tests.conftest import make_business, owner_query
from tests.test_migration_0037 import alembic


def table_exists() -> bool:
    return bool(owner_query("SELECT to_regclass('public.prepaid_orders')")[0][0])


def test_the_table_is_tenant_isolated_with_the_constraints_that_matter():
    assert table_exists()
    assert owner_query("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'prepaid_orders'")[0] == (True, True)
    assert owner_query("SELECT count(*) FROM pg_policies WHERE tablename = 'prepaid_orders' AND policyname = 'tenant_isolation'")[0][0] == 1
    cons = {r[0] for r in owner_query("SELECT conname FROM pg_constraint WHERE conrelid = 'prepaid_orders'::regclass")}
    assert {"uq_prepaid_orders_order_id", "ck_prepaid_orders_months", "ck_prepaid_orders_amount"} <= cons
    privs = {r[0] for r in owner_query("SELECT privilege_type FROM information_schema.role_table_grants WHERE table_name = 'prepaid_orders' AND grantee = 'flowqr_app'")}
    assert privs == {"SELECT", "INSERT", "UPDATE"}  # an order is a payment record: the app can never delete it


def test_downgrade_removes_only_the_new_table_and_upgrade_restores_it_without_touching_a_customer_row():
    biz = make_business()
    before = owner_query("SELECT count(*), md5(string_agg(id::text || plan || status, ',' ORDER BY id::text)) FROM subscriptions")[0]
    alembic("downgrade", "0037")
    try:
        assert not table_exists()
        assert owner_query("SELECT version_num FROM alembic_version")[0][0] == "0037"
        assert owner_query("SELECT count(*), md5(string_agg(id::text || plan || status, ',' ORDER BY id::text)) FROM subscriptions")[0] == before
    finally:
        alembic("upgrade", "head")
    assert table_exists() and owner_query("SELECT version_num FROM alembic_version")[0][0] == "0043"
    assert owner_query("SELECT count(*), md5(string_agg(id::text || plan || status, ',' ORDER BY id::text)) FROM subscriptions")[0] == before
    assert biz.tenant_id
