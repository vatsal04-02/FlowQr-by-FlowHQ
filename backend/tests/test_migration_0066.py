"""Migration 0066 (Local SEO engine V2): two more action statuses, a recorded validation step, an idempotency index that covers `recommended`. Additive and reversible."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import make_business, owner_exec, owner_query
from tests.test_migration_0037 import alembic


def _action(tenant_id, loc_id, status, key):
    owner_exec("""INSERT INTO agent_actions (id, tenant_id, google_location_id, action_type, field_key, trigger, problem, reason, expected_outcome, evidence, source, current_value, proposed_value,
                  base_fingerprint, value_hash, facts_fingerprint, idempotency_key, policy_level, effective_type, risk_level, policy_reasons, "authorization", status, proposed_by, attempts)
                  VALUES (:id, :t, :g, 'service_update', 'services', 't', 'p', 'r', 'e', '{}', '{}', '{}', '{}', 'b', 'v', 'f', :k, 2, 'service_update', 'medium', '[]', 'owner', :s, 'agent', 0)""",
               id=uuid.uuid4(), t=tenant_id, g=loc_id, k=key, s=status)


def _location(biz):
    conn, gl = uuid.uuid4(), uuid.uuid4()
    owner_exec("INSERT INTO google_connections (id, tenant_id, status, google_email, access_token_encrypted, refresh_token_encrypted, scopes, created_at, updated_at) "
               "VALUES (:c, :t, 'active', 'x@y.z', 'x', 'x', 'x', now(), now())", c=conn, t=biz.tenant_id)
    owner_exec("INSERT INTO google_locations (id, tenant_id, connection_id, google_account_name, google_location_name, selected, consecutive_failures, created_at, updated_at) VALUES (:g, :t, :c, 'accounts/1', :n, true, 0, now(), now())",
               g=gl, t=biz.tenant_id, c=conn, n=f"locations/{gl.int % 10**9}")
    return gl


def test_the_new_columns_and_statuses_exist_and_a_recommendation_owns_its_idempotency_key():
    biz = make_business("V2 Migration Clinic")
    gl = _location(biz)
    cols = {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = 'agent_actions'")}
    assert {"validation_status", "validation"} <= cols
    _action(biz.tenant_id, gl, "recommended", "k1")
    with pytest.raises(IntegrityError):  # the same change cannot be recommended twice
        _action(biz.tenant_id, gl, "recommended", "k1")
    _action(biz.tenant_id, gl, "superseded", "k1")  # a superseded one frees the key
    with pytest.raises(IntegrityError):
        _action(biz.tenant_id, gl, "not_a_status", "k2")


def test_the_downgrade_cancels_the_new_statuses_removes_the_columns_and_the_upgrade_restores_them():
    biz = make_business("V2 Downgrade Clinic")
    gl = _location(biz)
    _action(biz.tenant_id, gl, "recommended", "d1")
    _action(biz.tenant_id, gl, "superseded", "d2")
    _action(biz.tenant_id, gl, "pending_approval", "d3")
    alembic("downgrade", "0065")
    try:
        cols = {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = 'agent_actions'")}
        assert not {"validation_status", "validation"} & cols
        st = dict(owner_query("SELECT idempotency_key, status FROM agent_actions WHERE tenant_id = :t", t=biz.tenant_id))
        assert st == {"d1": "canceled", "d2": "canceled", "d3": "pending_approval"}  # nothing deleted; only the statuses the old schema cannot hold were changed
    finally:
        alembic("upgrade", "head")
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] == "0067"
    assert {"validation_status", "validation"} <= {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = 'agent_actions'")}
