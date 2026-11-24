"""Migration 0067 (agency self-service onboarding): three additive columns on google_agency_authorizations, sitting on 0066 (Local SEO V2) in a single chain. Reversible, and no existing row changes."""
import uuid
from contextlib import closing

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.db import system_session
from app.models import GoogleAgencyAuthorization as Auth
from tests.conftest import head_revision, make_business, owner_exec, owner_query
from tests.test_migration_0037 import alembic

COLS = ("consent_actions", "notices_sent", "initial_sync_enqueued_at")


def _cols():
    return {r[0]: (r[1], r[2]) for r in owner_query("SELECT column_name, is_nullable, column_default FROM information_schema.columns WHERE table_name = 'google_agency_authorizations'")}


def test_there_is_one_head_and_0067_sits_directly_on_0066_seo_v2():
    sd = ScriptDirectory.from_config(Config("alembic.ini"))
    assert sd.get_heads() == [head_revision()]
    assert sd.get_revision("0067").down_revision == "0066" and sd.get_revision("0066").down_revision == "0065"
    chain = [r.revision for r in sd.walk_revisions()]
    assert chain[chain.index("0067"):chain.index("0067") + 3] == ["0067", "0066", "0065"] and len(chain) == len(set(chain))  # one linear chain, no revision id used twice


def test_the_three_columns_exist_and_the_only_required_one_has_a_default():
    c = _cols()
    assert all(k in c for k in COLS)
    assert c["consent_actions"][0] == "YES" and c["initial_sync_enqueued_at"][0] == "YES"
    assert c["notices_sent"][0] == "NO" and c["notices_sent"][1].startswith("'{}'")


def test_downgrade_drops_exactly_those_columns_keeps_the_rows_and_the_upgrade_restores_them():
    biz = make_business("Migration 0067 Clinic")
    gid, cid, aid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    owner_exec("INSERT INTO google_connections (id, tenant_id, google_sub, status, auth_mode, created_at, updated_at) VALUES (:c, :t, 'm67', 'active', 'client_token', now(), now())", c=str(cid), t=biz.tenant_id)
    owner_exec("INSERT INTO google_locations (id, tenant_id, connection_id, google_account_name, google_location_name, title, selected, consecutive_failures, created_at, updated_at) "
               "VALUES (:g, :t, :c, 'accounts/1', 'locations/67', 'M', true, 0, now(), now())", g=str(gid), t=biz.tenant_id, c=str(cid))
    owner_exec("INSERT INTO google_agency_authorizations (id, tenant_id, connection_id, google_location_id, status, consent_version, consent_text_sha256, consented_at, target_type, created_at, updated_at) "
               "VALUES (:a, :t, :c, :g, 'consented', 'v', :h, now(), 'individual_agency_user', now(), now())", a=str(aid), t=biz.tenant_id, c=str(cid), g=str(gid), h="0" * 64)
    before = owner_query("SELECT status, consent_version FROM google_agency_authorizations WHERE id = :a", a=str(aid))
    try:
        alembic("downgrade", "0066")
        assert not any(k in _cols() for k in COLS)  # exactly the three are gone
        assert owner_query("SELECT status, consent_version FROM google_agency_authorizations WHERE id = :a", a=str(aid)) == before  # the row and its data survived
        assert owner_query("SELECT version_num FROM alembic_version")[0][0] == "0066"
    finally:
        alembic("upgrade", "head")
    assert all(k in _cols() for k in COLS) and owner_query("SELECT version_num FROM alembic_version")[0][0] == head_revision()
    row = owner_query("SELECT consent_actions, notices_sent, initial_sync_enqueued_at FROM google_agency_authorizations WHERE id = :a", a=str(aid))[0]
    assert row[0] is None and row[1] == {} and row[2] is None  # an older row means "recorded under the earlier wording", nothing invented
    with closing(system_session()) as db:  # and the application model reads it
        assert db.get(Auth, aid).consent_actions is None
    owner_exec("DELETE FROM google_connections WHERE id = :c", c=str(cid))
