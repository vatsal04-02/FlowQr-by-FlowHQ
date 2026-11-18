"""Consent for automation (Local SEO Milestone 2, decision D2; services/consent.py, migration 0038).

MOCKED GOOGLE: the profile API is the AutonomyGoogle test double of the Phase 1 tests. The database (PostgreSQL, row-level security, the consent trigger), the policy, the
executor, the auto-reply rule and the HTTP API are real. Nothing here says anything about what real Google does."""
import uuid

import pytest
from sqlalchemy import text

from app.models import AgentSettings, ConsentGrant
from app.services import consent as consent_svc
from app.services.agent import autonomy_policy as pol
from app.services.agent import controls, executor
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_phase1_executor import DESC, desc, env, evs, run, st  # noqa: F401  (env: a connected business, a Google test double, autonomy OFF)
from tests.test_location_permissions import invite
from tests.test_gbp import gid  # noqa: F401
from tests.test_google_and_reviews import connected  # noqa: F401
from tests.test_phase1_executor import fake  # noqa: F401

V = consent_svc.WORDING_VERSION


def give(env, scope="description_improve", version=V, who=None):
    return (who or env.biz).post("/agent/consents", json={"location_id": env.gid, "scope": scope, "wording_version": version})


def switch_on(env, scope="description_improve"):
    """Autonomy ON with a pre-authorisation for the type (the owner's existing two settings), WITHOUT consent."""
    executor.get_settings(env.db, env.tenant.id)
    env.db.commit()
    r = env.biz.put("/agent/autonomy-settings", json={"enabled": True, "permissions": {scope: "auto"}})
    assert r.status_code == 200, r.text
    env.db.expire_all()


def active_rows(env):
    return owner_query("SELECT scope, revoked_at IS NULL FROM consent_grants WHERE google_location_id = :g ORDER BY granted_at", g=uuid.UUID(env.gid))


# ------------------------------------------------------------------------------------------------------------------------ defaults: nothing is on
def test_a_new_business_has_automation_off_and_no_consent(env):
    row = owner_query("SELECT autonomy_enabled, auto_reply_enabled FROM agent_settings WHERE tenant_id = :t", t=uuid.UUID(env.biz.tenant_id))
    assert row == [(False, False)]
    assert env.biz.get("/agent/consents").json()["grants"] == []
    fresh = make_business()  # a second, brand-new business
    assert fresh.get("/agent/autonomy-settings").status_code in (200, 402)
    assert owner_query("SELECT autonomy_enabled, auto_reply_enabled FROM agent_settings WHERE tenant_id = :t", t=uuid.UUID(fresh.tenant_id)) in ([(False, False)], [])


def test_the_model_defaults_are_off():
    assert AgentSettings.autonomy_enabled.default.arg is False and AgentSettings.auto_reply_enabled.default.arg is False


# ------------------------------------------------------------------------------------------------------------------------ who may grant, and what
def test_only_the_owner_can_grant_or_revoke(env):
    admin, staff = invite(env.biz, "admin"), invite(env.biz, "staff")
    assert give(env, who=admin).status_code == 403 and give(env, who=staff).status_code == 403
    r = give(env)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert admin.post(f"/agent/consents/{cid}/revoke", json={}).status_code == 403
    assert staff.post("/agent/consents/revoke-all", json={}).status_code == 403
    assert env.biz.post(f"/agent/consents/{cid}/revoke", json={}).status_code == 200


def test_level_3_and_public_content_can_never_be_consented_to(env):
    for scope in ("business_name_change", "primary_category_change", "address_change", "service_area_change", "primary_contact_change", "significant_removal", "sensitive_claim",
                  "publish_content", "upload_photo", "reply_publish", "content_edit", "content_delete", "rank_monitoring", "service_update", "made_up"):
        r = give(env, scope=scope)
        assert r.status_code == 422, (scope, r.status_code, r.text)
    assert active_rows(env) == []
    assert set(consent_svc.scopes()) == {"description_improve", "text_correction", "hours_update", "contact_update", "secondary_category_update", consent_svc.REPLY_SCOPE}


def test_every_grantable_scope_is_level_1_or_2_and_writable():
    for key, sc in consent_svc.scopes().items():
        if key == consent_svc.REPLY_SCOPE:
            continue
        s = pol.SPECS[key]
        assert s.level in (1, 2) and s.writable and not s.person_only and not s.internal


def test_consent_is_refused_against_wording_the_owner_did_not_see(env):
    r = give(env, version="1999-01-01.0")
    assert r.status_code == 409 and active_rows(env) == []


def test_the_exact_wording_and_the_person_are_recorded_and_granting_twice_is_one_row(env):
    a, b = give(env), give(env)
    assert a.status_code == b.status_code == 201 and a.json()["id"] == b.json()["id"] and b.json()["created"] is False
    row = owner_query("SELECT wording_version, wording_text, granted_by FROM consent_grants WHERE google_location_id = :g", g=uuid.UUID(env.gid))
    assert len(row) == 1 and row[0][0] == V and "without asking you each time" in row[0][1] and row[0][2] == env.uid
    assert owner_query("SELECT count(*) FROM audit_logs WHERE action = 'consent.granted' AND tenant_id = :t", t=uuid.UUID(env.biz.tenant_id))[0][0] >= 1


# ------------------------------------------------------------------------------------------------------------------------ consent gates execution
def test_a_preauthorised_type_without_consent_still_needs_a_person(env):
    switch_on(env)
    a = desc(env)
    assert a.authorization == "owner" and a.status == "pending_approval"  # autonomy on and the type set to auto, but no consent for this location
    assert env.fake.update_calls == 0


def test_with_consent_the_same_action_is_authorised_and_runs(env):
    switch_on(env)
    assert give(env).status_code == 201
    a = desc(env)
    assert a.authorization == "policy" and a.status == "approved"
    out = run(env, a)
    assert out["status"] == "executed" and out["verified"] is True and env.fake.update_calls == 1


def test_consent_for_one_action_type_does_not_cover_another(env):
    switch_on(env)
    env.biz.put("/agent/autonomy-settings", json={"permissions": {"hours_update": "auto"}})
    assert give(env, scope="hours_update").status_code == 201
    a = desc(env)  # description_improve: no consent of its own
    assert a.authorization == "owner" and a.status == "pending_approval"


def test_consent_for_one_location_does_not_cover_another(env):
    switch_on(env)
    other = uuid.uuid4()
    r = env.biz.post("/agent/consents", json={"location_id": str(other), "scope": "description_improve", "wording_version": V})
    assert r.status_code == 404  # a location that is not this business's cannot be consented to
    assert consent_svc.has_active(env.db, env.tenant.id, other, "description_improve") is False
    assert give(env).status_code == 201
    assert consent_svc.has_active(env.db, env.tenant.id, other, "description_improve") is False  # and the real grant does not leak to any other id


def test_revoking_stops_future_execution_and_pulls_back_queued_work(env):
    switch_on(env)
    cid = give(env).json()["id"]
    a = desc(env)
    assert a.status == "approved"
    r = env.biz.post(f"/agent/consents/{cid}/revoke", json={"reason": "changed my mind"})
    assert r.status_code == 200 and r.json()["active"] is False and r.json()["withdrawn"] == 1
    assert st(a.id) == "pending_approval"
    env.db.expire_all()
    assert run(env, a)["status"] in ("pending_approval", "approved") and env.fake.update_calls == 0  # nothing was written
    b = desc(env, text_=DESC + " We also see families.")
    assert b.authorization == "owner" and b.status == "pending_approval"


def test_a_revoked_consent_cannot_be_used_by_a_job_that_was_already_queued(env):
    """The row is approved and due; consent is withdrawn directly in the database a moment before the executor runs. The executor re-checks at the moment it would write."""
    switch_on(env)
    give(env)
    a = desc(env)
    assert a.status == "approved"
    owner_exec("ALTER TABLE consent_grants DISABLE TRIGGER consent_grants_no_edit")
    try:
        owner_exec("UPDATE consent_grants SET revoked_at = now() WHERE google_location_id = :g", g=uuid.UUID(env.gid))
    finally:
        owner_exec("ALTER TABLE consent_grants ENABLE TRIGGER consent_grants_no_edit")
    env.db.expire_all()
    out = run(env, a)
    assert env.fake.update_calls == 0 and out["status"] != "executed"
    assert "autonomy_withdrawn" in evs(a.id)


def test_the_emergency_stop_holds_even_a_fully_consented_action(env):
    switch_on(env)
    give(env)
    a = desc(env)
    controls.set_emergency_stop(env.db, on=True, user_id=None, reason="test")
    env.db.commit()
    try:
        out = run(env, a)
        assert out["status"] == "held" and out["reason"] == "emergency_stop" and env.fake.update_calls == 0
    finally:
        owner_exec("DELETE FROM platform_controls")


def test_switching_autonomy_off_beats_consent(env):
    switch_on(env)
    give(env)
    a = desc(env)
    env.biz.put("/agent/autonomy-settings", json={"enabled": False})
    env.db.expire_all()
    run(env, a)
    assert env.fake.update_calls == 0


# ------------------------------------------------------------------------------------------------------------------------ the record itself
def test_the_consent_record_cannot_be_edited_or_deleted(env):
    give(env)
    for sql in ("UPDATE consent_grants SET wording_text = 'something else'", "UPDATE consent_grants SET granted_at = now() - interval '1 year'", "DELETE FROM consent_grants"):
        with pytest.raises(Exception) as e:
            owner_exec(sql)
        assert "consent" in str(e.value).lower(), sql
    assert owner_query("SELECT count(*) FROM consent_grants WHERE google_location_id = :g", g=uuid.UUID(env.gid))[0][0] == 1


def test_a_revoked_grant_is_frozen_and_a_new_grant_is_a_new_row(env):
    cid = give(env).json()["id"]
    env.biz.post(f"/agent/consents/{cid}/revoke", json={})
    with pytest.raises(Exception):
        owner_exec("UPDATE consent_grants SET revoked_reason = 'rewritten' WHERE id = :i", i=uuid.UUID(cid))
    assert give(env).json()["id"] != cid
    assert [r[1] for r in active_rows(env)] == [False, True]  # the full history: one withdrawn, one active


def test_revoke_is_idempotent_and_recorded(env):
    cid = give(env).json()["id"]
    assert env.biz.post(f"/agent/consents/{cid}/revoke", json={}).json()["revoked"] is True
    assert env.biz.post(f"/agent/consents/{cid}/revoke", json={}).json()["revoked"] is False
    assert owner_query("SELECT count(*) FROM audit_logs WHERE action = 'consent.revoked' AND tenant_id = :t", t=uuid.UUID(env.biz.tenant_id))[0][0] == 1


def test_revoke_all_for_a_location_and_for_the_business(env):
    give(env)
    give(env, scope="hours_update")
    assert env.biz.post("/agent/consents/revoke-all", json={"location_id": env.gid}).json()["revoked"] == 2
    assert all(not r[1] for r in active_rows(env))
    assert env.biz.post("/agent/consents/revoke-all", json={}).json()["revoked"] == 0


def test_other_businesses_cannot_see_or_revoke_my_consent(env):
    cid = give(env).json()["id"]
    other = make_business()
    assert other.post(f"/agent/consents/{cid}/revoke", json={}).status_code in (403, 404)
    assert other.get("/agent/consents").json()["grants"] == [] if other.get("/agent/consents").status_code == 200 else True
    assert owner_query("SELECT revoked_at IS NULL FROM consent_grants WHERE id = :i", i=uuid.UUID(cid)) == [(True,)]


def test_consent_is_in_the_owners_data_export():
    from app.services.account import TABLES
    assert ConsentGrant in TABLES


def test_the_consent_endpoint_lists_scopes_wording_and_the_never_list(env):
    j = env.biz.get("/agent/consents").json()
    assert j["wording_version"] == V and any(s["scope"] == "description_improve" for s in j["scopes"]) and "primary category" in j["never_grantable"]
    assert all(s["wording"] and "withdraw" in s["wording"] for s in j["scopes"])


def test_the_database_defaults_themselves_are_off():
    """Not only the ORM: a row inserted by any other path (a script, a migration, SQL) also starts with automation off."""
    d = dict(owner_query("SELECT column_name, column_default FROM information_schema.columns WHERE table_name = 'agent_settings' AND column_name IN ('autonomy_enabled', 'auto_reply_enabled')"))
    assert d == {"autonomy_enabled": "false", "auto_reply_enabled": "false"}
