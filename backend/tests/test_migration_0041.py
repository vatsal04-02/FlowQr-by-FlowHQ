"""Migration 0041 (temporary prepaid price overrides): additive, tenant-isolated, reversible, no existing row touched."""
from tests.conftest import make_business, owner_query
from tests.test_migration_0037 import alembic


def exists() -> bool:
    return bool(owner_query("SELECT to_regclass('public.prepaid_price_overrides')")[0][0])


def test_the_table_is_isolated_and_can_only_lower_a_price():
    assert exists()
    assert owner_query("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'prepaid_price_overrides'")[0] == (True, True)
    cons = {r[0] for r in owner_query("SELECT conname FROM pg_constraint WHERE conrelid = 'prepaid_price_overrides'::regclass")}
    assert {"ck_prepaid_override_amount", "ck_prepaid_override_cheaper", "ck_prepaid_override_months"} <= cons
    privs = {r[0] for r in owner_query("SELECT privilege_type FROM information_schema.role_table_grants WHERE table_name = 'prepaid_price_overrides' AND grantee = 'flowqr_app'")}
    assert privs == {"SELECT", "INSERT", "UPDATE"}


def test_downgrade_removes_only_the_new_pieces_and_keeps_every_order():
    biz = make_business()
    before = owner_query("SELECT count(*) FROM prepaid_orders")[0][0]
    alembic("downgrade", "0040")
    try:
        assert not exists()
        assert not owner_query("SELECT 1 FROM information_schema.columns WHERE table_name = 'prepaid_orders' AND column_name IN ('list_price_paise', 'override_id')")
        assert owner_query("SELECT count(*) FROM prepaid_orders")[0][0] == before
    finally:
        alembic("upgrade", "head")
    assert exists() and owner_query("SELECT version_num FROM alembic_version")[0][0] == "0058"
    assert biz.tenant_id
