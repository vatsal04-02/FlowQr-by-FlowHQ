"""Phase 2: autonomous maintenance is a plan feature. A standing authorisation (autonomy switched on, or a pre-authorised type) is only honoured while the business's plan includes
`autonomy`. MOCKED: Google is the AutonomyGoogle test double of the Phase 1 tests; the database and the engine are real."""
import uuid

from sqlalchemy import select

from app.models import Subscription
from tests.conftest import owner_exec, owner_query
from tests.test_phase1_executor import autonomy, desc, env, fake, gid, run, st  # noqa: F401
from tests.test_google_and_reviews import connected  # noqa: F401


def drop_feature(tenant_id, feature):
    owner_exec("UPDATE subscriptions SET features = (features - CAST(:f AS text)) WHERE tenant_id = :t", f=feature, t=tenant_id)


def test_without_the_autonomy_feature_a_level_1_change_waits_for_a_person_even_with_autonomy_on(env):
    autonomy(env)
    drop_feature(env.biz.tenant_id, "autonomy")
    env.db.expire_all()
    a = desc(env)
    assert (a.policy_level, a.authorization, a.status) == (1, "owner", "pending_approval")
    assert owner_query("SELECT count(*) FROM agent_action_approvals WHERE action_id = :a", a=a.id)[0][0] == 0  # no standing authorisation was recorded


def test_a_downgrade_after_authorisation_stops_the_change_before_it_reaches_google(env):
    autonomy(env)
    a = desc(env)
    assert a.status == "approved"  # authorised by policy while the plan included autonomy
    drop_feature(env.biz.tenant_id, "autonomy")  # the business is downgraded before the job runs
    env.db.expire_all()
    r = run(env, a)
    assert r["status"] == "pending_approval" and r["reason"] == "autonomy_withdrawn" and env.fake.update_calls == 0
    assert st(a.id) == "pending_approval"  # back to a person, not lost and not executed


def test_a_change_a_person_approved_still_runs_after_a_downgrade(env):
    from app.services.agent import executor
    from app.models import Role
    a = desc(env)  # autonomy off: waits for a person
    executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=True)
    env.db.commit()
    drop_feature(env.biz.tenant_id, "autonomy")
    env.db.expire_all()
    assert run(env, a)["status"] == "executed" and env.fake.update_calls == 1  # a named person decided; the plan only governs STANDING authorisation


def test_a_profile_write_and_its_failure_are_recorded_in_the_usage_ledger_once_per_attempt(env):
    from app.services import google as g
    autonomy(env)
    a = desc(env)
    assert run(env, a)["status"] == "executed"
    ok = owner_query("SELECT operation, feature, status, units, est_cost_usd FROM api_usage_ledger WHERE tenant_id = :t AND provider = 'google_business'", t=env.biz.tenant_id)
    assert ok == [("locations.patch", "autonomy", "ok", 1, None)]  # one write, one row, and no price configured so no cost (never a made-up zero)
    env.fake.details["description"] = "Old"
    env.db.expire_all()
    b = desc(env, "At Gomti Physio in Lucknow our physiotherapists help people with back care and neck pain physiotherapy. Call the clinic to book a visit or ask us a question about services.")
    env.fake.fail_updates = [g.GoogleAPIError(403, "denied")]
    run(env, b)
    got = owner_query("SELECT status FROM api_usage_ledger WHERE tenant_id = :t AND provider = 'google_business' ORDER BY created_at", t=env.biz.tenant_id)
    assert got == [("ok",), ("error",)]
