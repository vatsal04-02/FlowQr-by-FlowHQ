"""Migration 0061 (agency manager account): additive, protected, reversible, and every existing connection stays on its own token."""
from tests.conftest import head_revision, make_business, owner_query
from tests.test_migration_0037 import alembic


def cols(table):
    return {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = :t", t=table)}


def test_new_tables_columns_and_protections_exist():
    assert {"auth_mode", "agency_account_id", "agency_switched_at"} <= cols("google_connections")
    assert "client_google_account_name" in cols("google_locations")
    for t in ("google_agency_accounts", "google_agency_authorizations"):
        assert owner_query("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t", t=t)[0] == (True, True)
    assert owner_query("SELECT policyname FROM pg_policies WHERE tablename = 'google_agency_accounts'")[0][0] == "platform_only"
    assert owner_query("SELECT policyname FROM pg_policies WHERE tablename = 'google_agency_authorizations'")[0][0] == "tenant_isolation"
    # no token and no Google content on the per-client record
    banned = {"refresh_token_encrypted", "access_token_encrypted", "review_text", "reply_text", "comment", "summary", "metrics"}
    assert not (banned & cols("google_agency_authorizations"))


def test_an_agency_connection_must_name_its_account_and_the_mode_is_closed_set():
    cons = {r[0] for r in owner_query("SELECT conname FROM pg_constraint WHERE conrelid = 'google_connections'::regclass")}
    assert {"ck_gconn_auth_mode", "ck_gconn_agency_account", "fk_gconn_agency_account"} <= cons


def test_existing_connections_default_to_the_clients_own_token_and_downgrade_round_trips():
    make_business()
    assert owner_query("SELECT count(*) FROM google_connections WHERE auth_mode <> 'client_token' OR agency_account_id IS NOT NULL")[0][0] == 0
    alembic("downgrade", "0060")
    try:
        assert not ({"auth_mode", "agency_account_id", "agency_switched_at"} & cols("google_connections"))
        assert not owner_query("SELECT to_regclass('public.google_agency_authorizations')")[0][0]
        assert not owner_query("SELECT to_regclass('public.google_agency_accounts')")[0][0]
    finally:
        alembic("upgrade", "head")
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] == head_revision()
