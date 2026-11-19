"""Migration 0046 (admin-managed businesses): additive, tenant-isolated, reversible, no existing row changed."""
from tests.conftest import make_business, owner_query
from tests.test_migration_0037 import alembic


def cols(table):
    return {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = :t", t=table)}


def test_new_columns_table_and_protections_exist():
    assert {"contact_name", "origin", "created_by", "updated_by"} <= cols("tenants")
    assert owner_query("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'tenant_agreements'")[0] == (True, True)
    cons = {r[0] for r in owner_query("SELECT conname FROM pg_constraint WHERE conrelid = 'tenant_agreements'::regclass")}
    assert "ck_tenant_agreements_method" in cons
    assert "ck_tenants_origin" in {r[0] for r in owner_query("SELECT conname FROM pg_constraint WHERE conrelid = 'tenants'::regclass")}


def test_every_existing_business_stays_self_service_and_downgrade_round_trips_without_touching_a_row():
    biz = make_business()
    before = owner_query("SELECT count(*), md5(string_agg(id::text || name || slug, ',' ORDER BY id::text)) FROM tenants")[0]
    alembic("downgrade", "0045")
    try:
        assert not ({"contact_name", "origin", "created_by", "updated_by"} & cols("tenants"))
        assert not owner_query("SELECT to_regclass('public.tenant_agreements')")[0][0]
        assert owner_query("SELECT count(*), md5(string_agg(id::text || name || slug, ',' ORDER BY id::text)) FROM tenants")[0] == before
    finally:
        alembic("upgrade", "head")
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] == "0053"
    assert owner_query("SELECT count(*) FROM tenants WHERE origin <> 'self_service'")[0][0] == 0  # none of the pre-existing businesses was marked admin-created
    assert biz.tenant_id


def test_the_chain_is_one_linear_line_ending_at_0053_and_0046_hangs_off_0045():
    """Numbering and dependencies: exactly one head, no branch, every revision has exactly one parent, and 0046 follows 0045 directly."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["0053"]
    revs = list(script.walk_revisions())
    assert all(isinstance(r.down_revision, (str, type(None))) for r in revs), "a merge or branch point appeared"
    assert sum(1 for r in revs if r.down_revision is None) == 1  # a single base
    assert script.get_revision("0046").down_revision == "0045" and script.get_revision("0047").down_revision == "0046" and script.get_revision("0048").down_revision == "0047" and script.get_revision("0049").down_revision == "0048" and script.get_revision("0053").down_revision == "0052" and script.get_revision("0052").down_revision == "0051" and script.get_revision("0051").down_revision == "0050" and script.get_revision("0050").down_revision == "0049"
    ids = [r.revision for r in revs]
    assert len(ids) == len(set(ids))  # no revision number is used twice


def test_new_tables_and_the_invitation_link_exist_and_leave_with_a_downgrade():
    assert "allowlist_entry_id" in cols("invitations")
    assert {"requester_name", "status", "verification_method", "eligible_at", "business_name"} <= cols("data_requests")
    assert {"request_id", "action", "actor_id"} <= cols("data_request_events")
    assert owner_query("SELECT count(*) FROM pg_indexes WHERE indexname = 'uq_data_requests_open'")[0][0] == 1
    biz = make_business()
    before = owner_query("SELECT count(*), md5(string_agg(id::text || email, ',' ORDER BY id::text)) FROM invitations")[0]
    alembic("downgrade", "0045")
    try:
        assert "allowlist_entry_id" not in cols("invitations")
        assert not owner_query("SELECT to_regclass('public.data_requests')")[0][0] and not owner_query("SELECT to_regclass('public.data_request_events')")[0][0]
        assert owner_query("SELECT count(*), md5(string_agg(id::text || email, ',' ORDER BY id::text)) FROM invitations")[0] == before  # existing invitations are untouched
    finally:
        alembic("upgrade", "head")
    assert "allowlist_entry_id" in cols("invitations") and biz.tenant_id
