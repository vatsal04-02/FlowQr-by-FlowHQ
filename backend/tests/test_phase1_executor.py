"""Balanced Autonomy, part 2: proposals, approvals, the controlled executor, emergency controls, tenant isolation, history integrity and the ranking feedback loop.

MOCKED, ALL OF IT: Google is a TEST DOUBLE (AutonomyGoogle, which can apply, refuse, drop or half-apply a write) and ranking is a TEST DOUBLE (FakePlaces). The database,
PostgreSQL row-level security, the append-only trigger, the state machines and the policy are real. A pass here proves FlowQR's own logic; it is NOT evidence that
the real Google API behaves this way. No autonomous write has been verified against Google (see docs/AGENT_AUDIT.md, "Live Google execution evidence")."""
import threading
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.models import AgentAction, GbpSnapshot, GoogleLocation, RankKeyword, Role, Tenant
from app.models.base import utcnow
from app.services import google as g
from app.services import rank as rank_svc
from app.services.agent import autonomy_policy as pol
from app.services.agent import controls, executor, history, learning, optimizer, seo_engine
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_agent import Scripted, add_review  # noqa: F401
from tests.test_phase0_ai_cost import seed
from tests.test_gbp import FakeGbpProvider, gid  # noqa: F401
from tests.test_google_and_reviews import connected  # noqa: F401
from tests.test_location_permissions import invite

DESC = "Gomti Physio is a physiotherapy clinic in Lucknow offering back care and neck pain physiotherapy. Call the clinic to book a visit or to ask a question about our services."
DESC2 = "At Gomti Physio in Lucknow our physiotherapists help people with back care and neck pain physiotherapy. Call the clinic to book a visit or ask us a question about services."
LONG_DESC = ("Gomti Physio is a physiotherapy clinic in Lucknow that helps people deal with back pain and neck pain. Our physiotherapists assess each person carefully, explain what is going on in plain words and build a plan of back care and neck pain physiotherapy that fits daily life. Whether your pain is recent or has lasted for months, we work with you step by step. Call the clinic to book a visit or to ask a question about our services.")
LONG_OK = "A friendly clinic in Lucknow with parking and a calm waiting room, open six days a week for appointments and enquiries from local families."
BIZ = {"kind": "business_knowledge", "refs": ["description", "services"]}
KB_BODY = {"description": "Physiotherapy for back and neck pain in Lucknow.", "services": ["Back care", "Neck pain physiotherapy"], "offers": [], "faqs": [], "prohibited_claims": []}
HOURS_OK = [{"day": "MONDAY", "open": "09:00", "close": "18:00"}, {"day": "TUESDAY", "open": "10:00", "close": "17:30"}]


class AutonomyGoogle(FakeGbpProvider):
    """TEST DOUBLE of Google's profile API. `apply=False` accepts a write but changes nothing (a 200 that is not real); `fail_updates` raises on the next writes;
    `raise_after_apply` applies the write and then raises (a lost response); `hold` pauses inside the write so concurrency can be tested."""

    def __init__(self):
        super().__init__()
        self.update_calls, self.fail_updates, self.apply, self.raise_after_apply = 0, [], True, None
        self.hold = self.entered = None

    def update_location(self, at, loc, changes):
        self.update_calls += 1
        if self.entered:
            self.entered.set()
        if self.hold:
            self.hold.wait(15)
        if self.fail_updates:
            raise self.fail_updates.pop(0)
        if self.apply:
            for k, v in changes.items():
                if k in ("description", "website", "phone", "hours"):
                    self.details[k] = v
                elif k == "additional_categories":
                    self.details["additional_categories"] = [{"id": c, "name": c.split(":")[-1].title()} for c in v]
                elif k == "primary_category":
                    self.details["primary_category"] = {"id": v, "name": v.split(":")[-1].title()}
            self.writes.append(("update", dict(changes)))
        if self.raise_after_apply:
            raise self.raise_after_apply
        return dict(self.details)


class FakePlaces:
    """TEST DOUBLE of the Places client: `positions[keyword]` is the rank (1-20) or None for not found; `error` makes every search fail."""

    def __init__(self):
        self.positions, self.calls, self.error = {}, 0, None

    def place_location(self, place_id):
        return 26.85, 80.95

    def search(self, query, lat, lng, radius_m):
        self.calls += 1
        if self.error:
            raise self.error
        results = [{"place_id": f"other{i}", "name": f"Other {i}", "rating": 4.0, "reviews": 10} for i in range(1, 21)]
        rank = self.positions.get(query)
        if rank:
            results[rank - 1] = {"place_id": "PID", "name": "Us", "rating": 4.5, "reviews": 20}
        return results


@pytest.fixture()
def fake(monkeypatch):
    f = AutonomyGoogle()
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    return f


@pytest.fixture()
def env(connected, fake, gid):  # noqa: F811
    owner_exec("DELETE FROM platform_controls")
    # the test database is shared by the whole session: leave nothing from earlier tests that a platform-wide job could pick up
    owner_exec("UPDATE agent_actions SET status = 'canceled' WHERE status IN ('pending_approval', 'approved', 'executing')")
    owner_exec("UPDATE agent_rank_followups SET status = 'skipped' WHERE status IN ('pending', 'deferred')")
    owner_exec("UPDATE agent_settings SET autonomy_enabled = false")
    connected.put("/agent/knowledge", json=KB_BODY)
    assert connected.post("/agent/google/refresh").json()["locations"][0]["ok"] is True
    db = SessionLocal(); set_rls_context(db, bypass=True)
    uid = owner_query("SELECT user_id FROM memberships WHERE tenant_id = :t LIMIT 1", t=uuid.UUID(connected.tenant_id))[0][0]
    e = SimpleNamespace(biz=connected, fake=fake, db=db, gid=gid, uid=uid, tenant=db.get(Tenant, uuid.UUID(connected.tenant_id)), gloc=db.get(GoogleLocation, uuid.UUID(gid)))
    # Autonomy is ON by default since migration 0031 (owner decision 2026-11-15). These tests exercise the policy mechanics from a known baseline, so each starts with it OFF; the tests that
    # need it on call autonomy(env). The default itself is tested in tests/test_template_auto_replies.py.
    connected.get("/agent/autonomy-settings")  # creates the settings row through the API (it is created lazily); this session's identity map stays untouched
    owner_exec("UPDATE agent_settings SET autonomy_enabled = false WHERE tenant_id = :t", t=connected.tenant_id)
    yield e
    db.close()
    # the test database is shared: do not leave measurements behind for tests that assert there are none
    owner_exec("DELETE FROM rank_checks WHERE tenant_id = :t", t=uuid.UUID(connected.tenant_id))


def refresh(env):
    assert env.biz.post("/agent/google/refresh").json()["locations"][0]["ok"] is True
    env.db.expire_all()


def put_kb(env, body):
    assert env.biz.put("/agent/knowledge", json=body).status_code == 200
    env.db.expire_all()  # this session is long-lived: drop what it cached about the business


def kw_row(env, term=None):
    q = select(RankKeyword).where(RankKeyword.google_location_id == env.gloc.id)
    if term:
        q = q.where(RankKeyword.keyword == term)
    return env.db.scalars(q).first()


def descs(env, out):
    return [x for x in (env.db.get(AgentAction, uuid.UUID(i)) for i in out["proposed"]) if x.action_type == "description_improve"]


def autonomy(env, enabled=True, perms=None, limit=None):
    s = executor.get_settings(env.db, env.tenant.id)
    s.autonomy_enabled = enabled
    if perms is not None:
        s.autonomy_permissions = perms
    if limit is not None:
        s.autonomy_daily_limit = limit
    env.db.commit()
    return s


def desc(env, text_=DESC, **kw):
    a = executor.propose(env.db, env.tenant, env.gloc, "description_improve", proposed=text_, source=BIZ, trigger="optimizer:description", problem="The description is weak.",
                         reason="Write a fuller description from verified facts.", **kw)
    env.db.commit()
    return a


def run(env, a, **kw):
    return executor.execute(env.db, a.id, provider=env.fake, sleep=lambda s: None, **kw)


def st(aid):
    return owner_query("SELECT status FROM agent_actions WHERE id = :a", a=aid)[0][0]


def evs(aid):
    return [e for (e,) in owner_query("SELECT event_type FROM agent_intervention_events WHERE action_id = :a ORDER BY seq", a=aid)]


def tracked(env, *words):
    owner_exec("UPDATE google_locations SET lat = 26.85, lng = 80.95, place_id = 'PID' WHERE id = :g", g=env.gid)
    env.db.refresh(env.gloc)
    for w in words:
        env.db.add(RankKeyword(tenant_id=env.tenant.id, google_location_id=env.gloc.id, keyword=w))
    env.db.commit()


# ============================================================================ 1. proposing and authorising

def test_level_1_waits_for_a_person_while_autonomy_is_off_and_writes_nothing(env):
    a = desc(env)
    assert (a.policy_level, a.authorization, a.status, a.risk_level) == (1, "owner", "pending_approval", "low")
    assert run(env, a)["reason"] == "not_approved" and env.fake.update_calls == 0 and env.fake.details["description"] == "Old"
    assert evs(a.id) == ["proposed", "policy_classified"]


def test_level_1_is_authorised_by_policy_when_the_owner_turned_autonomy_on(env):
    autonomy(env)
    a = desc(env)
    assert (a.authorization, a.status) == ("policy", "approved")
    ap = owner_query("SELECT decision, basis, expires_at IS NOT NULL FROM agent_action_approvals WHERE action_id = :a", a=a.id)[0]
    assert ap == ("auto_authorized", "level1_policy", True)
    assert evs(a.id) == ["proposed", "policy_classified", "auto_authorized"]


def test_level_2_needs_a_preauthorisation_for_exactly_that_type(env):
    def hours(env_):
        a = executor.propose(env_.db, env_.tenant, env_.gloc, "hours_update", proposed=HOURS_OK, source={"kind": "owner_input", "user_id": "u"}, trigger="owner_request",
                             problem="Tuesday hours are missing.", reason="You told us the Tuesday hours.", proposed_by="user", user_id=env.uid)
        env_.db.commit()
        return a
    autonomy(env)
    a = hours(env)
    assert (a.policy_level, a.authorization, a.status) == (2, "owner", "pending_approval")  # autonomy is on but nothing was pre-authorised
    owner_exec("UPDATE agent_actions SET status = 'canceled' WHERE id = :a", a=a.id)
    autonomy(env, perms={"service_update": "auto"})  # a pre-authorisation for a DIFFERENT type
    a = hours(env)
    assert a.status == "pending_approval"
    owner_exec("UPDATE agent_actions SET status = 'canceled' WHERE id = :a", a=a.id)
    autonomy(env, perms={"hours_update": "auto"})
    a = hours(env)
    assert (a.authorization, a.status) == ("preauthorized", "approved")
    assert owner_query("SELECT basis FROM agent_action_approvals WHERE action_id = :a", a=a.id)[0][0] == "preauthorization"


def test_level_3_always_waits_for_the_owner_even_if_the_data_says_auto(env):
    autonomy(env, perms={"primary_category_change": "auto"})  # written straight into the table, bypassing the API's validation
    a = executor.propose(env.db, env.tenant, env.gloc, "primary_category_change", proposed="categories/gcid:chiropractor", source={"kind": "owner_input", "user_id": "u"},
                         trigger="owner_request", problem="p", reason="r", proposed_by="user", user_id=env.uid)
    env.db.commit()
    assert (a.policy_level, a.risk_level, a.authorization, a.status) == (3, "high", "owner", "pending_approval")


def test_missing_evidence_blocks_the_proposal_and_nothing_can_execute_it(env):
    put_kb(env, {"description": "", "services": [], "offers": [], "faqs": [], "prohibited_claims": []})
    a = executor.propose(env.db, env.tenant, env.gloc, "description_improve", proposed=DESC, source={"kind": "business_knowledge", "refs": ["description", "services"]},
                         trigger="t", problem="p", reason="r")
    env.db.commit()
    assert a.status == "blocked" and "empty" in a.last_error and evs(a.id)[-1] == "blocked"
    assert run(env, a)["reason"] == "not_approved" and env.fake.update_calls == 0


def test_conflicting_facts_block_it(env):
    owner_exec("UPDATE tenants SET website = 'https://gomti.example.com' WHERE id = :t", t=env.tenant.id)
    env.db.refresh(env.tenant)
    env.fake.details["website"] = None
    refresh(env)
    a = executor.propose(env.db, env.tenant, env.gloc, "contact_update", field_key="website", proposed="https://somewhere-else.example", source={"kind": "tenant_record", "refs": ["website"]},
                         trigger="t", problem="p", reason="r")
    env.db.commit()
    assert a.status == "blocked" and "does not match the website in the business record" in a.last_error


def test_an_unsupported_field_is_recorded_and_left_to_a_person(env):
    a = executor.propose(env.db, env.tenant, env.gloc, "business_name_change", proposed="Gomti Physio Best Clinic", source={"kind": "owner_input", "user_id": "u"}, trigger="owner_request",
                         problem="p", reason="r", proposed_by="user", user_id=env.uid)
    env.db.commit()
    assert a.policy_level == 3 and a.status == "blocked" and "cannot write" in a.last_error and "Google Business Profile" in a.last_error


def test_a_type_the_owner_switched_off_is_not_proposed(env):
    autonomy(env, perms={"description_improve": "off"})
    a = desc(env)
    assert a.status == "blocked" and "switched off" in a.last_error


def test_the_same_proposal_is_never_created_twice(env):
    a, b = desc(env), desc(env)
    assert a.id == b.id and owner_query("SELECT count(*) FROM agent_actions WHERE tenant_id = :t", t=env.tenant.id)[0][0] == 1
    c = desc(env, DESC2)  # a different value is a different action
    assert c.id != a.id
    env.fake.details["description"] = "Something someone typed in Google."
    refresh(env)
    assert desc(env).id not in (a.id, b.id, c.id)  # the same value against a NEW Google value is a new question


# ============================================================================ 2. approvals

def test_admins_approve_level_1_and_2_but_only_the_owner_approves_level_3(env):
    a = desc(env)
    executor.decide(env.db, a, user_id=env.uid, role=Role.admin, approve=True)
    assert a.status == "approved"
    p3 = executor.propose(env.db, env.tenant, env.gloc, "primary_category_change", proposed="categories/gcid:chiropractor", source={"kind": "owner_input", "user_id": "u"}, trigger="t",
                          problem="p", reason="r", proposed_by="user", user_id=env.uid)
    env.db.commit()
    with pytest.raises(executor.ActionError) as exc:
        executor.decide(env.db, p3, user_id=env.uid, role=Role.admin, approve=True)
    assert exc.value.status == 403 and "owner" in str(exc.value)
    with pytest.raises(executor.ActionError):
        executor.decide(env.db, p3, user_id=env.uid, role=Role.staff, approve=True)
    executor.decide(env.db, p3, user_id=env.uid, role=Role.owner, approve=True)
    assert p3.status == "approved"


def test_an_approval_records_who_when_what_and_the_before_and_after(env):
    a = desc(env)
    uid = env.uid
    executor.decide(env.db, a, user_id=uid, role=Role.owner, approve=True, reason="Looks right")
    env.db.commit()
    ap = owner_query("SELECT decision, basis, authorized_by, reason, expires_at > now(), scope->>'value_hash', scope_hash FROM agent_action_approvals WHERE action_id = :a", a=a.id)[0]
    assert (ap[0], ap[1], ap[2], ap[3], ap[4]) == ("approved", "owner", uid, "Looks right", True) and ap[5] == a.value_hash and len(ap[6]) == 64
    data = owner_query("SELECT data FROM agent_intervention_events WHERE action_id = :a AND event_type = 'approved'", a=a.id)[0][0]
    assert data["comparison"] == {"before": "Old", "after": pol.canon("description", DESC)} and data["scope"]["facts_fingerprint"] == a.facts_fingerprint


def test_a_rejection_needs_a_reason_and_is_final(env):
    a = desc(env)
    with pytest.raises(executor.ActionError) as exc:
        executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=False, reason=" ")
    assert exc.value.status == 422
    executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=False, reason="We do not want this wording")
    env.db.commit()
    assert a.status == "rejected" and evs(a.id)[-1] == "rejected"
    with pytest.raises(executor.ActionError):
        executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=True)  # a rejected action cannot be approved afterwards
    assert run(env, a)["reason"] == "not_approved" and env.fake.update_calls == 0


def test_an_expired_approval_is_never_executed(env):
    a = desc(env)
    executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=True)
    env.db.commit()
    owner_exec("UPDATE agent_action_approvals SET expires_at = now() - interval '1 minute' WHERE action_id = :a", a=a.id)
    r = run(env, a)
    assert r["status"] == "expired" and st(a.id) == "expired" and env.fake.update_calls == 0 and evs(a.id)[-1] == "expired"


def test_expiry_job_expires_old_proposals_and_unused_authorisations(env):
    a, b = desc(env), desc(env, DESC2)
    executor.decide(env.db, b, user_id=env.uid, role=Role.owner, approve=True)
    env.db.commit()
    owner_exec("UPDATE agent_actions SET expires_at = now() - interval '1 hour' WHERE id = :a", a=a.id)
    owner_exec("UPDATE agent_action_approvals SET expires_at = now() - interval '1 hour' WHERE action_id = :a", a=b.id)
    assert executor.expire_due(env.db) == {"proposals": 1, "approvals": 1}
    assert (st(a.id), st(b.id)) == ("expired", "expired")
    with pytest.raises(executor.ActionError):
        executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=True)  # an expired proposal cannot be approved


def test_a_google_value_that_changed_after_approval_invalidates_it(env):
    a = desc(env)
    executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=True)
    env.db.commit()
    env.fake.details["description"] = "Someone edited the description in Google after we proposed this."
    r = run(env, a)
    assert r["status"] == "invalidated" and r["reason"] == "google_value_changed" and env.fake.update_calls == 0
    assert owner_query("SELECT invalidated_at IS NOT NULL FROM agent_action_approvals WHERE action_id = :a", a=a.id)[0][0] is True
    assert evs(a.id)[-1] == "google_value_changed"


def test_a_change_to_the_verified_facts_after_approval_invalidates_it(env):
    a = desc(env)
    executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=True)
    env.db.commit()
    put_kb(env, {**KB_BODY, "services": ["Back care", "Sports injury rehabilitation"]})  # the owner edited the facts this relied on
    r = run(env, a)
    assert r["status"] == "invalidated" and r["reason"] == "facts_changed" and env.fake.update_calls == 0


def test_approving_after_the_google_profile_changed_is_refused_and_recorded(env):
    a = desc(env)
    env.fake.details["description"] = "A newer description typed in Google."
    refresh(env)
    with pytest.raises(executor.ActionError) as exc:
        executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=True)
    assert "re-evaluated" in str(exc.value) and st(a.id) == "invalidated"


def test_an_approval_authorises_that_exact_value_and_nothing_else(env):
    a = desc(env)
    executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=True)
    env.db.commit()
    owner_exec("UPDATE agent_actions SET proposed_value = jsonb_build_object('value', CAST(:v AS text), 'canonical', CAST(:v AS text)), value_hash = 'f' || substr(value_hash, 2) WHERE id = :a", a=a.id, v="A different text slipped in after approval.")
    r = run(env, a)
    assert r["status"] == "invalidated" and "no longer matches what was authorised" in r["detail"] and env.fake.update_calls == 0


def test_approving_one_action_does_not_authorise_another(env):
    a, b = desc(env), desc(env, DESC2)
    executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=True)
    env.db.commit()
    assert run(env, b)["reason"] == "not_approved" and env.fake.update_calls == 0 and st(b.id) == "pending_approval"
    assert run(env, a)["status"] == "executed" and env.fake.update_calls == 1


# ============================================================================ 3. the execution engine

def test_a_verified_execution_is_recorded_end_to_end(env):
    a = desc(env)
    executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=True)
    env.db.commit()
    assert run(env, a) == {"status": "executed", "verified": True}
    assert env.fake.update_calls == 1 and env.fake.details["description"] == DESC
    e = evs(a.id)
    assert e[:3] == ["proposed", "policy_classified", "approved"] and [x for x in e if x in ("executing", "google_write", "read_back", "verified")] == ["executing", "google_write", "read_back", "verified"]
    assert e.index("baseline_measured") < e.index("executing")
    row = owner_query("SELECT status, attempts, executed_at IS NOT NULL, verified_at IS NOT NULL, verification->>'matched', google_result->>'accepted' FROM agent_actions WHERE id = :a", a=a.id)[0]
    assert row == ("executed", 1, True, True, "true", "true")
    assert history.verify(env.db, a.id) == {"ok": True, "events": len(e), "broken_at": None, "reason": None}


def test_a_request_google_accepted_but_did_not_apply_is_a_failure_never_a_success(env):
    env.fake.apply = False  # a 200 that changes nothing
    autonomy(env)
    a = desc(env)
    r = run(env, a)
    assert r["status"] == "failed" and r["reason"] == "read_back_mismatch" and "does not show the new description" in r["detail"]
    row = owner_query("SELECT status, executed_at, verified_at, verification->>'matched' FROM agent_actions WHERE id = :a", a=a.id)[0]
    assert row == ("failed", None, None, "false") and evs(a.id)[-3:] == ["google_write", "read_back", "failed"]
    assert executor.get_settings(env.db, env.tenant.id).autonomy_failure_streak == 1


def test_a_temporary_google_error_is_retried_and_writes_once(env):
    autonomy(env)
    a = desc(env)
    env.fake.fail_updates = [g.GoogleAPIError(503, "Google is busy")]
    r = run(env, a)
    assert r["status"] == "approved" and r["reason"] == "retry" and st(a.id) == "approved"
    assert run(env, a)["reason"] == "not_due"  # backing off: not retried immediately
    assert run(env, a, now=utcnow() + timedelta(minutes=30))["status"] == "executed"
    assert env.fake.update_calls == 2 and len(env.fake.writes) == 1 and "retry_scheduled" in evs(a.id)


def test_a_lost_response_is_adopted_on_retry_not_written_again(env):
    """Google applied the write but the answer never arrived. The retry reads the profile first and finds the value already there."""
    autonomy(env)
    a = desc(env)
    env.fake.raise_after_apply = g.GoogleAPIError(503, "response lost")
    assert run(env, a)["reason"] == "retry"
    env.fake.raise_after_apply = None
    r = run(env, a, now=utcnow() + timedelta(minutes=30))
    assert r["status"] == "executed" and env.fake.update_calls == 1  # ONE write in total
    assert owner_query("SELECT verification->>'note' FROM agent_actions WHERE id = :a", a=a.id)[0][0] == "an earlier attempt had already applied it"


def test_a_permanent_google_refusal_is_failed_at_once_and_not_retried(env):
    autonomy(env)
    a = desc(env)
    env.fake.fail_updates = [g.GoogleAPIError(403, "denied")]
    assert run(env, a)["status"] == "failed" and st(a.id) == "failed"
    assert executor.run_due(env.db, provider=env.fake)  == {"stopped": False}  # nothing left to run
    assert env.fake.update_calls == 1


def test_a_google_read_failure_before_the_write_means_nothing_was_written(env):
    autonomy(env)
    a = desc(env)
    env.fake.error = g.GoogleAPIError(503, "Google is down")
    r = run(env, a)
    assert r["status"] == "approved" and r["reason"] == "retry" and env.fake.update_calls == 0


def test_a_value_google_already_shows_is_not_written_again(env):
    autonomy(env)
    a = desc(env)
    env.fake.details["description"] = DESC  # someone already put exactly this on the profile
    r = run(env, a)
    assert r["status"] == "invalidated" and r["reason"] == "already_applied" and env.fake.update_calls == 0


def test_repeated_failures_suspend_autonomy_automatically_and_stop_what_is_pending(env):
    env.fake.apply = False
    autonomy(env)
    texts = [DESC, DESC2, DESC.replace("visit", "consultation")]
    actions = [desc(env, t) for t in texts]
    spare = desc(env, DESC.replace("clinic", "centre"))  # authorised, waiting its turn
    for a in actions:
        assert run(env, a)["status"] == "failed"
    s = executor.get_settings(env.db, env.tenant.id)
    assert s.autonomy_failure_streak == 3 and s.autonomy_suspended_at is not None and "suspended automatically" in s.autonomy_suspended_reason
    assert "autonomy_suspended" in evs(actions[-1].id) and owner_query("SELECT count(*) FROM audit_logs WHERE action = 'autonomy.suspended' AND tenant_id = :t", t=env.tenant.id)[0][0] == 1
    r = run(env, spare)  # suspended: the pending autonomous action is returned to a person, not executed
    assert r["status"] == "pending_approval" and r["reason"] == "autonomy_withdrawn" and env.fake.update_calls == 3
    assert desc(env, DESC.replace("book", "reserve"), proposed_by="user", user_id=env.uid).status == "pending_approval"  # a person's own request waits for a person
    assert desc(env, DESC.replace("book", "arrange")).status == "blocked"  # and the agent stops proposing in a place that keeps failing


def test_the_owner_can_resume_a_suspended_business(env):
    s = executor.get_settings(env.db, env.tenant.id)
    s.autonomy_enabled, s.autonomy_suspended_at, s.autonomy_failure_streak = True, utcnow(), 3
    env.db.commit()
    r = env.biz.post("/agent/autonomy-settings/resume")
    assert r.status_code == 200 and r.json()["suspended"] is False and r.json()["failure_streak"] == 0
    assert invite(env.biz, "admin").post("/agent/autonomy-settings/resume").status_code == 403


# ============================================================================ 4. concurrency and duplicates

def _in_thread(env, a, results, name):
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        results[name] = executor.execute(db, a.id, provider=env.fake, sleep=lambda s: None)
    finally:
        db.close()


def test_two_executions_of_one_action_write_once(env):
    autonomy(env)
    a = desc(env)
    env.fake.hold, env.fake.entered = threading.Event(), threading.Event()
    results: dict = {}
    t = threading.Thread(target=_in_thread, args=(env, a, results, "first"))
    t.start()
    assert env.fake.entered.wait(15)  # the first execution is inside Google, with its claim committed
    _in_thread(env, a, results, "second")  # a second worker picks up the same action
    env.fake.hold.set()
    t.join(20)
    assert results["second"] == {"status": "executing", "reason": "not_approved"}
    assert results["first"]["status"] == "executed" and env.fake.update_calls == 1


def test_an_executed_action_is_never_executed_again(env):
    autonomy(env)
    a = desc(env)
    assert run(env, a)["status"] == "executed"
    assert run(env, a) == {"status": "executed", "reason": "not_approved"} and env.fake.update_calls == 1
    assert executor.run_due(env.db, provider=env.fake) == {"stopped": False} and env.fake.update_calls == 1


def test_only_one_write_per_location_and_field_can_be_in_flight(env):
    autonomy(env)
    a, b = desc(env), desc(env, DESC2)  # two authorised changes to the same field
    env.fake.hold, env.fake.entered = threading.Event(), threading.Event()
    results: dict = {}
    t = threading.Thread(target=_in_thread, args=(env, a, results, "first"))
    t.start()
    assert env.fake.entered.wait(15)
    _in_thread(env, b, results, "second")
    assert results["second"] == {"status": "approved", "reason": "location_field_busy"} and st(b.id) == "approved"
    env.fake.hold.set()
    t.join(20)
    assert results["first"]["status"] == "executed"
    later = run(env, b, now=utcnow() + timedelta(minutes=3))  # the first one changed the field: the second no longer matches what it was proposed against
    assert later["status"] == "invalidated" and later["reason"] == "google_value_changed" and env.fake.update_calls == 1


def test_the_scheduled_job_executes_what_is_due_and_isolates_failures(env):
    autonomy(env)
    a, b = desc(env), desc(env, DESC2)
    out = executor.run_due(env.db, provider=env.fake)
    assert out["stopped"] is False and out.get("executed") == 1 and out.get("invalidated") == 1  # the second one's premise changed once the first landed
    assert (st(a.id), st(b.id)) == ("executed", "invalidated")


# ============================================================================ 5. emergency controls, limits, budgets

def test_the_platform_emergency_stop_holds_execution_without_losing_anything(env, monkeypatch):
    autonomy(env)
    a = desc(env)
    monkeypatch.setattr(settings, "autonomy_emergency_stop", True)
    out = executor.run_due(env.db, provider=env.fake)
    assert out["stopped"] is True and out["executed"] == 0 and "AUTONOMY_EMERGENCY_STOP" in out["reason"]
    assert run(env, a) == {"status": "held", "reason": "emergency_stop", "detail": "AUTONOMY_EMERGENCY_STOP is set on this server."}
    assert st(a.id) == "approved" and env.fake.update_calls == 0  # held, not failed
    monkeypatch.setattr(settings, "autonomy_emergency_stop", False)
    assert executor.run_due(env.db, provider=env.fake)["executed"] == 1 and st(a.id) == "executed"


def test_the_runtime_emergency_stop_is_flipped_by_a_platform_admin_and_holds_the_publishers_too(env, admin):
    autonomy(env)
    a = desc(env)
    assert env.biz.put("/admin/autonomy/emergency-stop", json={"on": True, "reason": "x"}).status_code == 403  # a business owner is not a platform admin
    assert admin.put("/admin/autonomy/emergency-stop", json={"on": True}).status_code == 422  # a reason is required
    assert admin.put("/admin/autonomy/emergency-stop", json={"on": True, "reason": "Google changed its API"}).json()["stop"]["reason"] == "Google changed its API"
    assert admin.get("/admin/autonomy/emergency-stop").json()["stop"]["on"] is True
    from app.workers import tasks
    assert tasks.autonomy_execute.run()["stopped"] is True and st(a.id) == "approved"
    assert tasks.publish_due_posts.run()["stopped"] is True and tasks.publish_due_media.run()["stopped"] is True and tasks.retry_failed_replies.run()["stopped"] is True
    assert env.biz.get("/agent/autonomy-settings").json()["platform_emergency_stop"] is True
    assert owner_query("SELECT count(*) FROM audit_logs WHERE action = 'autonomy.emergency_stop_on'")[0][0] >= 1
    admin.put("/admin/autonomy/emergency-stop", json={"on": False})
    assert tasks.autonomy_execute.run().get("executed") == 1  # lifted: the held action runs


def test_switching_autonomy_off_stops_pending_jobs_and_new_actions(env):
    autonomy(env)
    a = desc(env)
    assert a.status == "approved"
    assert env.biz.put("/agent/autonomy-settings", json={"enabled": False}).json()["enabled"] is False  # the owner switches it off before the job runs
    r = executor.run_due(env.db, provider=env.fake)
    assert r.get("pending_approval") == 1 and st(a.id) == "pending_approval" and env.fake.update_calls == 0
    assert owner_query("SELECT invalidated_reason FROM agent_action_approvals WHERE action_id = :a", a=a.id)[0][0].startswith("autonomy was switched off")
    assert "autonomy_withdrawn" in evs(a.id)
    b = desc(env, DESC2)  # a newly scheduled action no longer runs on its own either
    assert b.status == "pending_approval"


def test_narrowing_a_permission_after_authorisation_withdraws_it(env):
    autonomy(env)
    a = desc(env)
    autonomy(env, perms={"description_improve": "ask"})
    assert run(env, a)["reason"] == "autonomy_withdrawn" and env.fake.update_calls == 0


def test_a_person_approved_action_still_runs_when_autonomy_is_off(env):
    a = desc(env)  # autonomy is off by default
    executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=True)
    env.db.commit()
    assert run(env, a)["status"] == "executed"  # a human decision does not depend on the autonomy switch


def test_the_daily_limit_on_autonomous_changes_is_per_business(env):
    owner_exec("UPDATE tenants SET website = 'https://gomti.example.com' WHERE id = :t", t=env.tenant.id)
    env.db.refresh(env.tenant)
    env.fake.details["website"] = None
    refresh(env)
    autonomy(env, perms={"contact_update": "auto"}, limit=1)
    a = desc(env)
    b = executor.propose(env.db, env.tenant, env.gloc, "contact_update", field_key="website", proposed="https://gomti.example.com", source={"kind": "tenant_record", "refs": ["website"]},
                         trigger="optimizer:website", problem="p", reason="r")
    env.db.commit()
    assert (a.status, b.status) == ("approved", "approved")
    assert run(env, a)["status"] == "executed"
    r = run(env, b)
    assert r == {"status": "held", "reason": "daily_limit"} and env.fake.details["website"] is None
    assert owner_query("SELECT next_attempt_at > now() FROM agent_actions WHERE id = :a", a=b.id)[0][0] is True


def test_an_action_whose_pieces_belong_to_different_businesses_is_blocked(env):
    other = make_business("Other Physio")
    autonomy(env)
    a = desc(env)
    owner_exec("UPDATE agent_actions SET tenant_id = :o WHERE id = :a", a=a.id, o=other.tenant_id)
    env.db.expire_all()
    r = run(env, a)
    assert r["status"] == "blocked" and r["reason"] == "tenant_mismatch" and env.fake.update_calls == 0


def test_the_ai_budget_stops_the_scan_before_any_model_call(env, monkeypatch):
    from app.services.ai_usage import metered
    monkeypatch.setattr(settings, "ai_price_in_per_mtok", 1.0)
    monkeypatch.setattr(settings, "ai_price_out_per_mtok", 4.0)
    owner_exec("UPDATE tenants SET ai_monthly_budget_usd = 0.01 WHERE id = :t", t=env.tenant.id)
    seed(env.tenant.id, usd=0.0099)  # already spent: less than one draft's worst case is left
    stub = Scripted(DESC)
    out = seo_engine.scan_location(env.db, env.tenant, env.gloc, provider=metered(stub, env.db, env.tenant.id, "agent_draft"))
    assert descs(env, out) == [] and any("budget_tenant" in s for s in out["skipped"]) and stub.prompts == []
    assert owner_query("SELECT count(*) FROM agent_actions WHERE tenant_id = :t AND action_type = 'description_improve'", t=env.tenant.id)[0][0] == 0


# ============================================================================ 6. tenant isolation

def test_one_business_cannot_see_or_decide_anothers_actions(env):
    a = desc(env)
    other = make_business("Isolated Physio")
    assert other.get("/agent/actions").json() == {"actions": []}
    assert other.get(f"/agent/actions/{a.id}").status_code == 404
    assert other.post(f"/agent/actions/{a.id}/approve", json={}).status_code == 404
    assert other.post(f"/agent/actions/{a.id}/reject", json={"reason": "nope"}).status_code == 404
    assert other.post(f"/agent/actions/{a.id}/cancel").status_code == 404
    assert st(a.id) == "pending_approval"
    assert [x["id"] for x in env.biz.get("/agent/actions").json()["actions"]] == [str(a.id)]


def test_row_level_security_hides_actions_approvals_history_and_followups_from_other_businesses(env):
    autonomy(env)
    a = desc(env)
    other = make_business("RLS Physio")
    db = SessionLocal(); set_rls_context(db, tenant_id=uuid.UUID(other.tenant_id))
    for table in ("agent_actions", "agent_action_approvals", "agent_intervention_events", "agent_rank_followups"):
        assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table
    db.close()
    mine = SessionLocal(); set_rls_context(mine, tenant_id=env.tenant.id)
    assert mine.execute(text("SELECT count(*) FROM agent_intervention_events WHERE action_id = :a"), {"a": a.id}).scalar() == 3
    mine.close()


def test_what_the_feedback_loop_learned_about_one_business_never_affects_another(env):
    a = desc(env)
    owner_exec("UPDATE agent_actions SET status = 'failed' WHERE id = :a", a=a.id)
    b = desc(env, DESC2)
    owner_exec("UPDATE agent_actions SET status = 'failed' WHERE id = :a", a=b.id)
    assert learning.suppression(env.db, env.tenant.id, env.gloc.id, "description_improve", "description")  # two failures: paused HERE
    assert learning.suppression(env.db, uuid.uuid4(), uuid.uuid4(), "description_improve", "description") is None  # ...and nowhere else
    assert learning.priority_modifier(env.db, uuid.uuid4(), "description_improve") == 0


# ============================================================================ 7. the intervention history cannot be altered

def test_the_database_refuses_to_change_or_delete_history_even_for_the_owner_role(env):
    autonomy(env)
    a = desc(env)
    for sql in ("UPDATE agent_intervention_events SET data = '{}' WHERE action_id = :a", "DELETE FROM agent_intervention_events WHERE action_id = :a", "TRUNCATE agent_intervention_events"):
        with pytest.raises(Exception) as exc:
            owner_exec(sql, a=a.id)
        assert "append-only" in str(exc.value)
    app_db = SessionLocal(); set_rls_context(app_db, bypass=True)  # the application's own role has no UPDATE or DELETE privilege at all
    with pytest.raises(Exception) as exc2:
        app_db.execute(text("UPDATE agent_intervention_events SET data = '{}' WHERE action_id = :a"), {"a": a.id})
    assert "permission denied" in str(exc2.value)
    app_db.close()
    assert history.verify(env.db, a.id)["ok"] is True


def test_tampering_that_bypasses_the_trigger_is_still_detected_by_the_chain(env):
    autonomy(env)
    a = desc(env)
    assert run(env, a)["status"] == "executed"
    assert history.verify(env.db, a.id)["ok"] is True
    owner_exec("ALTER TABLE agent_intervention_events DISABLE TRIGGER agent_events_no_change")
    try:
        owner_exec("UPDATE agent_intervention_events SET data = jsonb_set(data, '{matched}', 'false') WHERE action_id = :a AND event_type = 'verified'", a=a.id)
        broken = history.verify(env.db, a.id)
        seq_v = owner_query("SELECT seq FROM agent_intervention_events WHERE action_id = :a AND event_type = 'verified'", a=a.id)[0][0]
        assert broken["ok"] is False and broken["reason"] == "the event content does not match its hash" and broken["broken_at"] == seq_v
        owner_exec("UPDATE agent_intervention_events SET data = jsonb_set(data, '{matched}', 'true') WHERE action_id = :a AND event_type = 'verified'", a=a.id)
        assert history.verify(env.db, a.id)["ok"] is True  # restoring the exact content restores the chain: it checks content, not flags
        owner_exec("DELETE FROM agent_intervention_events WHERE action_id = :a AND seq = 3", a=a.id)
        gap = history.verify(env.db, a.id)
        assert gap["ok"] is False and gap["reason"] == "an event is missing or out of order"
    finally:
        owner_exec("ALTER TABLE agent_intervention_events ENABLE TRIGGER agent_events_no_change")


def test_the_action_detail_shows_everything_that_happened_with_an_integrity_check(env):
    autonomy(env)
    a = desc(env)
    run(env, a)
    d = env.biz.get(f"/agent/actions/{a.id}").json()
    assert d["status"] == "executed" and d["policy"] == "Level 1: autonomous" and d["before"] == "Old" and d["after"] == pol.canon("description", DESC)
    assert d["source"]["kind"] == "business_knowledge" and d["problem"] and d["reason"] and "visibility" in d["expected_outcome"].lower() and "never claims" in d["expected_outcome"] and d["verification"]["matched"] is True
    assert [h["type"] for h in d["history"] if h["type"] in ("google_write", "read_back", "verified")] == ["google_write", "read_back", "verified"] and d["history_integrity"]["ok"] is True
    assert d["approvals"][0]["basis"] == "level1_policy"


def test_deleting_a_business_erases_its_history_and_nothing_else_can(env):
    from app.services.account import delete_tenant
    autonomy(env)
    a = desc(env)
    run(env, a)
    assert owner_query("SELECT count(*) FROM agent_intervention_events WHERE action_id = :a", a=a.id)[0][0] > 0
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert delete_tenant(db, env.tenant.id, provider=env.fake)["deleted"] is True
    db.close()
    assert owner_query("SELECT count(*) FROM agent_intervention_events WHERE action_id = :a", a=a.id)[0][0] == 0
    assert owner_query("SELECT count(*) FROM agent_actions WHERE tenant_id = :t", t=env.tenant.id)[0][0] == 0


# ============================================================================ 8. the ranking feedback loop

@pytest.fixture()
def places(monkeypatch):
    p = FakePlaces()
    monkeypatch.setattr(rank_svc, "get_client", lambda: p)
    monkeypatch.setattr(rank_svc, "enabled", lambda: True)
    return p


def test_ranking_is_measured_before_the_change_and_followups_are_scheduled(env, places):
    autonomy(env)
    tracked(env, "neck pain physiotherapy", "back care clinic")
    places.positions = {"neck pain physiotherapy": 8, "back care clinic": None}
    a = desc(env)
    now = utcnow()
    assert run(env, a, now=now)["status"] == "executed"
    env.db.refresh(a)
    ks = {k["keyword"]: k for k in a.baseline["keywords"]}
    assert (ks["neck pain physiotherapy"]["rank"], ks["neck pain physiotherapy"]["source"]) == (8, "fresh_measurement") and ks["back care clinic"]["rank"] is None and ks["back care clinic"]["status"] == "ok"
    assert a.baseline["usable"] == 2 and "not proof" in a.baseline["note"] and "guaranteed" in a.baseline["note"]
    assert owner_query("SELECT count(*) FROM rank_checks WHERE tenant_id = :t AND source = 'learn'", t=env.tenant.id)[0][0] == 2
    fu = owner_query("SELECT day_offset, status, due_at FROM agent_rank_followups WHERE action_id = :a ORDER BY day_offset", a=a.id)
    assert [(d, s) for d, s, _ in fu] == [(7, "pending"), (14, "pending"), (28, "pending")]
    assert [round((due - now).total_seconds() / 86400) for _, _, due in fu] == [7, 14, 28]
    assert evs(a.id).index("baseline_measured") < evs(a.id).index("google_write") and "followups_scheduled" in evs(a.id)  # measured BEFORE the write


def test_a_recent_measurement_is_reused_so_it_costs_nothing(env, places):
    autonomy(env)
    tracked(env, "neck pain physiotherapy")
    places.positions = {"neck pain physiotherapy": 5}
    rank_svc.check_keyword(env.db, env.gloc, kw_row(env), source="manual", client=places)
    env.db.commit()
    calls = places.calls
    a = desc(env)
    run(env, a)
    env.db.refresh(a)
    assert places.calls == calls and a.baseline["keywords"][0]["source"] == "recent_measurement"


def test_followups_compare_with_the_baseline_and_never_claim_a_cause(env, places):
    autonomy(env)
    tracked(env, "neck pain physiotherapy", "back care clinic", "spine specialist")
    places.positions = {"neck pain physiotherapy": 8, "back care clinic": None, "spine specialist": 6}
    a = desc(env)
    t0 = utcnow()
    run(env, a, now=t0)
    assert learning.run_due_followups(env.db, now=t0 + timedelta(days=3), client=places) == {"done": 0, "deferred": 0, "skipped": 0}  # not due yet
    places.positions = {"neck pain physiotherapy": 3, "back care clinic": 12, "spine specialist": 8}  # +5 (improved), found (improved), -2 (noise: unchanged)
    assert learning.run_due_followups(env.db, now=t0 + timedelta(days=8), client=places)["done"] == 1
    fu = owner_query("SELECT result FROM agent_rank_followups WHERE action_id = :a AND day_offset = 7", a=a.id)[0][0]
    verdicts = {k["keyword"]: k["verdict"] for k in fu["keywords"]}
    assert verdicts == {"neck pain physiotherapy": "improved", "back care clinic": "improved", "spine specialist": "unchanged"} and fu["overall"] == "improved"
    assert "not proof" in fu["note"] and "caused" not in fu["note"].replace("caused it", "").replace("cause", "")
    out = learning.run_due_followups(env.db, now=t0 + timedelta(days=30), client=places)
    assert out["done"] == 2
    env.db.refresh(a)
    assert a.outcome["label"] == "improved" and a.outcome["day"] == 28 and "not proof" in a.outcome["note"]
    types = evs(a.id)
    assert types.count("followup_measured") == 3 and types[-1] == "evaluated"
    assert history.verify(env.db, a.id)["ok"] is True


def test_a_failed_measurement_is_unknown_not_a_rank_and_not_found_is_a_real_result(env, places):
    autonomy(env)
    tracked(env, "neck pain physiotherapy")
    places.positions = {"neck pain physiotherapy": 4}
    a = desc(env)
    t0 = utcnow()
    run(env, a, now=t0)
    places.error = rank_svc.RankError("Google Places could not be reached.", 502)
    assert learning.run_due_followups(env.db, now=t0 + timedelta(days=8), client=places) == {"done": 0, "deferred": 1, "skipped": 0}  # an API failure: nothing is concluded
    fu = owner_query("SELECT status, attempts, result->>'overall' FROM agent_rank_followups WHERE action_id = :a AND day_offset = 7", a=a.id)[0]
    assert fu == ("deferred", 1, "insufficient_data")
    places.error, places.positions = None, {}  # the business is now genuinely not in the first 20
    assert learning.run_due_followups(env.db, now=t0 + timedelta(days=10), client=places)["done"] == 1
    res = owner_query("SELECT result->'keywords'->0->>'verdict', result->>'overall' FROM agent_rank_followups WHERE action_id = :a AND day_offset = 7", a=a.id)[0]
    assert res == ("declined", "declined")  # not found after being found at 4: a measured decline, distinct from the earlier failure


def test_a_followup_that_can_never_be_measured_is_given_up_not_invented(env, places):
    autonomy(env)
    tracked(env, "neck pain physiotherapy")
    places.positions = {"neck pain physiotherapy": 4}
    a = desc(env)
    t0 = utcnow()
    run(env, a, now=t0)
    places.error = rank_svc.RankError("down", 502)
    for d in (8, 10, 12):
        learning.run_due_followups(env.db, now=t0 + timedelta(days=d), client=places)
    assert owner_query("SELECT status FROM agent_rank_followups WHERE action_id = :a AND day_offset = 7", a=a.id)[0][0] == "skipped" and "followup_skipped" in evs(a.id)


def test_when_the_places_allowance_is_used_up_the_action_still_runs_with_no_baseline(env, places, monkeypatch):
    autonomy(env)
    tracked(env, "neck pain physiotherapy")
    monkeypatch.setattr(settings, "rank_monthly_check_cap", 0)  # the business's monthly Places allowance is gone
    a = desc(env)
    assert run(env, a)["status"] == "executed" and places.calls == 0
    env.db.refresh(a)
    assert a.baseline["usable"] == 0 and "limit" in a.baseline["unavailable_reason"] and a.baseline["keywords"][0]["status"] == "unavailable"
    assert "followups_skipped" in evs(a.id) and owner_query("SELECT count(*) FROM agent_rank_followups WHERE action_id = :a", a=a.id)[0][0] == 0


def test_with_nothing_tracked_there_is_nothing_to_measure_and_the_action_still_runs(env):
    autonomy(env)
    a = desc(env)
    assert run(env, a)["status"] == "executed"
    env.db.refresh(a)
    assert a.baseline["usable"] == 0 and "No search terms are tracked" in a.baseline["unavailable_reason"]


def test_actions_that_cannot_affect_visibility_are_not_measured(env):
    autonomy(env, perms={"hours_update": "auto"})
    a = executor.propose(env.db, env.tenant, env.gloc, "hours_update", proposed=HOURS_OK, source={"kind": "owner_input", "user_id": "u"}, trigger="owner_request", problem="p", reason="r",
                         proposed_by="user", user_id=env.uid)
    env.db.commit()
    assert a.status == "approved" and run(env, a)["status"] == "executed"
    env.db.refresh(a)
    assert a.baseline is None and owner_query("SELECT count(*) FROM agent_rank_followups WHERE action_id = :a", a=a.id)[0][0] == 0
    assert env.fake.details["hours"] == HOURS_OK


# ---- what the loop learned changes what is proposed next

def done_action(env, label, text_=DESC, days_ago=2):
    a = desc(env, text_)
    executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=True)
    env.db.commit()
    assert run(env, a)["status"] == "executed"
    owner_exec("UPDATE agent_actions SET outcome = jsonb_build_object('label', CAST(:l AS text)), executed_at = now() - make_interval(days => CAST(:d AS int)) WHERE id = :a", a=a.id, l=label, d=days_ago)
    env.fake.details["description"] = "Old"  # the profile is back to how it was, so the same kind of change can be asked again
    refresh(env)
    return a


def test_a_change_observed_to_coincide_with_a_decline_is_not_repeated(env):
    done_action(env, "declined")
    why = learning.suppression(env.db, env.tenant.id, env.gloc.id, "description_improve", "description")
    assert why and "move down" in why and "not proof it caused" in why
    assert desc(env, DESC2).status == "blocked"  # the agent's own re-proposal is blocked...
    p = executor.propose(env.db, env.tenant, env.gloc, "description_improve", proposed=DESC2, source=BIZ, trigger="owner_request", problem="p", reason="r", proposed_by="user", user_id=env.uid)
    assert p.status == "pending_approval"  # ...but a person can still ask for it
    assert any("Paused" in s for s in seo_engine.scan_location(env.db, env.tenant, env.gloc, provider=Scripted(DESC2))["skipped"])


def test_two_changes_with_no_observed_effect_pause_that_kind_of_change(env):
    done_action(env, "unchanged", DESC)
    assert learning.suppression(env.db, env.tenant.id, env.gloc.id, "description_improve", "description") is None  # one is not yet a pattern
    done_action(env, "unchanged", DESC2)
    assert "no observed movement" in learning.suppression(env.db, env.tenant.id, env.gloc.id, "description_improve", "description")


def test_a_rejection_and_repeated_failures_pause_proposals_for_a_while(env):
    a = desc(env)
    executor.decide(env.db, a, user_id=env.uid, role=Role.owner, approve=False, reason="Not now")
    env.db.commit()
    assert "rejected this kind of change recently" in learning.suppression(env.db, env.tenant.id, env.gloc.id, "description_improve", "description")
    assert learning.suppression(env.db, env.tenant.id, env.gloc.id, "description_improve", "description", now=utcnow() + timedelta(days=15)) is None  # the pause ends


def test_the_priority_of_a_kind_of_change_follows_how_it_turned_out(env):
    assert learning.priority_modifier(env.db, env.tenant.id, "description_improve") == 0
    a = done_action(env, "improved")
    assert learning.priority_modifier(env.db, env.tenant.id, "description_improve") == -5
    owner_exec("UPDATE agent_actions SET outcome = '{\"label\": \"unchanged\"}' WHERE id = :a", a=a.id)
    env.db.expire_all()
    assert learning.priority_modifier(env.db, env.tenant.id, "description_improve") == 10


# ---- ranking data really changes what the optimizer, the plan, the health score and the engine do

def _weak_rank(env, places, term="neck pain physiotherapy", rank=None):
    tracked(env, term)
    places.positions = {term: rank}
    rank_svc.check_keyword(env.db, env.gloc, kw_row(env, term), source="manual", client=places)
    env.db.commit()


def test_ranking_data_adds_a_visibility_check_to_the_optimizer_and_only_when_it_exists(env, places):
    snap = env.db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == env.gloc.id))
    kb = {"services": [], "description": ""}
    assert "visibility" not in [c["key"] for c in optimizer.checks(snap, kb)]
    assert "visibility" not in [c["key"] for c in optimizer.checks(snap, kb, rank=learning.rank_summary(env.db, env.gloc.id))]  # nothing measured: no such check
    _weak_rank(env, places, rank=None)
    c = next(c for c in optimizer.checks(snap, kb, rank=learning.rank_summary(env.db, env.gloc.id)) if c["key"] == "visibility")
    assert c["state"] == "improve" and "not in the first 20" in c["detail"] and "not a guaranteed Google Maps ranking" in c["detail"]
    places.positions = {"neck pain physiotherapy": 2}
    rank_svc.check_keyword(env.db, env.gloc, kw_row(env), source="manual", client=places)
    env.db.commit()
    assert next(c for c in optimizer.checks(snap, kb, rank=learning.rank_summary(env.db, env.gloc.id)) if c["key"] == "visibility")["state"] == "ok"


def test_ranking_data_adds_a_plan_task_and_a_health_component_only_when_measured(env, places):
    env.biz.post("/agent/plan/run")
    assert not [t for t in env.biz.get("/agent/tasks").json()["tasks"] if (t["evidence"] or {}).get("field") == "visibility"]
    assert "visibility" not in [c["key"] for c in env.biz.get("/agent/health").json()["components"]]
    _weak_rank(env, places, rank=None)
    env.biz.post("/agent/plan/run")
    t = next(t for t in env.biz.get("/agent/tasks").json()["tasks"] if (t["evidence"] or {}).get("field") == "visibility")
    assert "not showing for 1 of your 1 tracked search terms" in t["title"] and "not a guaranteed Google Maps ranking" in t["why"]
    comp = next(c for c in env.biz.get("/agent/health").json()["components"] if c["key"] == "visibility")
    assert comp["available"] is True and comp["value"] == 0.0 and comp["weight"] == 10


def test_ranking_data_decides_whether_the_engine_proposes_a_description_change(env, places):
    env.fake.details["description"] = LONG_OK  # a healthy description: the optimizer alone finds nothing to fix
    refresh(env)
    stub = Scripted(LONG_DESC)
    out = seo_engine.scan_location(env.db, env.tenant, env.gloc, provider=stub)
    assert descs(env, out) == [] and stub.prompts == []  # no ranking data: no proposal, and no AI call was paid for
    _weak_rank(env, places, rank=None)  # the business is not shown for a term that genuinely describes it
    out = seo_engine.scan_location(env.db, env.tenant, env.gloc, provider=stub)
    assert len(descs(env, out)) == 1 and len(stub.prompts) == 1 and "neck pain physiotherapy" in stub.prompts[0]
    a = descs(env, out)[0]
    assert a.trigger == "rank:weak_visibility" and a.evidence["rank"]["weak_terms"][0]["keyword"] == "neck pain physiotherapy" and a.evidence["ai"]["quality"] is not None
    assert (a.policy_level, a.status) == (1, "pending_approval")  # autonomy is off: it waits for a person
    assert "Rankings" not in a.reason and "guarantee" not in a.expected_outcome.lower()


def test_a_term_the_business_has_no_verified_basis_for_is_never_added(env, places):
    env.fake.details["description"] = LONG_OK
    refresh(env)
    _weak_rank(env, places, term="emergency dental surgery", rank=None)
    stub = Scripted(DESC)
    out = seo_engine.scan_location(env.db, env.tenant, env.gloc, provider=stub)
    assert out["proposed"] == [] and stub.prompts == []  # a physiotherapy clinic's facts say nothing about dental surgery


def test_the_scan_fills_a_missing_website_from_the_business_record_without_any_ai(env):
    owner_exec("UPDATE tenants SET website = 'https://gomti.example.com' WHERE id = :t", t=env.tenant.id)
    env.db.refresh(env.tenant)
    env.fake.details["website"] = None
    env.fake.details["description"] = LONG_OK
    refresh(env)
    stub = Scripted(DESC)
    out = seo_engine.scan_location(env.db, env.tenant, env.gloc, provider=stub)
    a = env.db.get(AgentAction, uuid.UUID(out["proposed"][0]))
    assert a.action_type == "contact_update" and a.policy_level == 2 and a.status == "pending_approval" and a.source == {"kind": "tenant_record", "refs": ["website"]} and stub.prompts == []
    assert seo_engine.scan_location(env.db, env.tenant, env.gloc, provider=stub)["proposed"] == [str(a.id)]  # scanning again finds the same action, not a second one


def test_an_unattended_cycle_proposes_executes_and_verifies_a_description_when_the_owner_enabled_autonomy(env, monkeypatch):
    """The whole loop, mocked: scan -> policy (Level 1, autonomy on) -> executor -> read-back. This is NOT evidence of live Google execution."""
    from app.workers import tasks
    autonomy(env)
    monkeypatch.setattr("app.services.ai.get_provider", lambda: Scripted(DESC))
    tasks_out = tasks.autonomy_scan.run()
    assert tasks_out["tenants"] >= 1 and tasks_out["proposed"] >= 1
    a = env.db.scalar(select(AgentAction).where(AgentAction.tenant_id == env.tenant.id, AgentAction.action_type == "description_improve"))
    assert a is not None and a.status == "approved" and env.fake.update_calls == 0  # proposed and authorised by policy; not yet written
    assert tasks.autonomy_execute.run().get("executed", 0) >= 1
    env.db.expire_all()
    a = env.db.get(AgentAction, a.id)
    assert a.status == "executed" and a.verification["matched"] is True and env.fake.details["description"] == DESC and env.fake.update_calls == 1


# ============================================================================ 9. the API

def test_autonomy_settings_are_the_owners_alone_and_validated(env):
    s = env.biz.get("/agent/autonomy-settings").json()
    assert s["enabled"] is False and s["executing_now"] is False and any(p["type"] == "description_improve" and p["mode"] == "auto" for p in s["permissions"])
    admin_ = invite(env.biz, "admin")
    staff = invite(env.biz, "staff")
    assert admin_.put("/agent/autonomy-settings", json={"enabled": True}).status_code == 403 and staff.put("/agent/autonomy-settings", json={"enabled": True}).status_code == 403
    assert admin_.get("/agent/autonomy-settings").status_code == 200
    bad = env.biz.put("/agent/autonomy-settings", json={"permissions": {"primary_category_change": "auto", "made_up": "auto"}})
    assert bad.status_code == 422 and len(bad.json()["detail"]["problems"]) == 2
    assert env.biz.put("/agent/autonomy-settings", json={"permissions": {"hours_update": "auto"}, "enabled": True, "daily_limit": 2}).json()["executing_now"] is True
    assert env.biz.put("/agent/autonomy-settings", json={"level": 1}).status_code == 422 and env.biz.put("/agent/autonomy-settings", json={"daily_limit": 500}).status_code == 422
    out = env.biz.get("/agent/autonomy-settings").json()
    assert next(p for p in out["permissions"] if p["type"] == "hours_update")["mode"] == "auto" and out["permissions_set_at"] and out["daily_limit"] == 2
    assert owner_query("SELECT count(*) FROM audit_logs WHERE action = 'autonomy.settings' AND tenant_id = :t", t=env.tenant.id)[0][0] == 1  # the refused requests changed nothing and are not logged as changes


def test_a_request_cannot_choose_its_own_level_or_authorisation(env):
    body = {"google_location_id": env.gid, "action_type": "description_improve", "proposed": DESC, "source_kind": "business_knowledge", "source_refs": ["description", "services"],
            "problem": "weak", "reason": "better"}
    for extra in ({"level": 1}, {"policy_level": 1}, {"authorization": "policy"}, {"status": "approved"}, {"risk": "low"}):
        assert env.biz.post("/agent/actions", json={**body, **extra}).status_code == 422, extra
    assert env.biz.post("/agent/actions", json={**body, "action_type": "delete_profile"}).status_code == 422
    assert invite(env.biz, "staff").post("/agent/actions", json=body).status_code == 403
    r = env.biz.post("/agent/actions", json={**body, "action_type": "primary_category_change", "proposed": "categories/gcid:chiropractor", "source_kind": "owner_input", "source_refs": []})
    assert r.status_code == 201 and r.json()["policy_level"] == 3 and r.json()["status"] == "pending_approval"  # the server decided: asking for "description_improve" semantics changes nothing


def test_the_api_runs_a_level_3_change_only_when_the_owner_approves_it(env):
    body = {"google_location_id": env.gid, "action_type": "primary_category_change", "proposed": "categories/gcid:chiropractor", "source_kind": "owner_input",
            "problem": "The main category is wrong.", "reason": "We are a chiropractic clinic."}
    a = env.biz.post("/agent/actions", json=body).json()
    admin_ = invite(env.biz, "admin")
    assert admin_.post(f"/agent/actions/{a['id']}/approve", json={}).status_code == 403 and env.fake.update_calls == 0
    r = env.biz.post(f"/agent/actions/{a['id']}/approve", json={"reason": "Yes, change it"})
    assert r.status_code == 200 and r.json()["execution"] == {"status": "executed", "verified": True} and r.json()["status"] == "executed"
    assert env.fake.details["primary_category"]["id"] == "categories/gcid:chiropractor" and r.json()["history_integrity"]["ok"] is True
    assert env.biz.post(f"/agent/actions/{a['id']}/approve", json={}).status_code == 409  # an action is approved once


def test_a_level_2_change_goes_through_the_api_with_a_before_and_after(env):
    body = {"google_location_id": env.gid, "action_type": "hours_update", "proposed": HOURS_OK, "source_kind": "owner_input", "problem": "Tuesday hours are missing.", "reason": "We open on Tuesdays."}
    a = env.biz.post("/agent/actions", json=body).json()
    assert a["policy_level"] == 2 and a["status"] == "pending_approval" and a["before"] == [["MONDAY", "09:00", "18:00"]] and a["after"] == [["MONDAY", "09:00", "18:00"], ["TUESDAY", "10:00", "17:30"]]
    ok = invite(env.biz, "admin").post(f"/agent/actions/{a['id']}/approve", json={}).json()  # an admin may approve Level 2
    assert ok["status"] == "executed" and env.fake.details["hours"] == HOURS_OK


def test_reject_and_cancel_through_the_api(env):
    body = {"google_location_id": env.gid, "action_type": "description_improve", "proposed": DESC, "source_kind": "business_knowledge", "source_refs": ["description", "services"], "problem": "weak", "reason": "better"}
    a = env.biz.post("/agent/actions", json=body).json()
    assert env.biz.post(f"/agent/actions/{a['id']}/reject", json={"reason": "x"}).status_code == 422  # too short a reason
    assert env.biz.post(f"/agent/actions/{a['id']}/reject", json={"reason": "I prefer my own words"}).json()["status"] == "rejected"
    b = env.biz.post("/agent/actions", json={**body, "proposed": DESC2}).json()
    assert env.biz.post(f"/agent/actions/{b['id']}/cancel").json()["status"] == "canceled" and env.biz.post(f"/agent/actions/{b['id']}/cancel").status_code == 409
    assert {x["status"] for x in env.biz.get("/agent/actions").json()["actions"]} == {"rejected", "canceled"}
    assert [x["status"] for x in env.biz.get("/agent/actions", params={"status": "rejected"}).json()["actions"]] == ["rejected"]


def test_the_policy_endpoint_publishes_the_same_table_the_code_enforces(env):
    p = env.biz.get("/agent/policy").json()
    levels = {a["type"]: a["level"] for a in p["actions"]}
    assert levels == {k: s.level for k, s in pol.SPECS.items()} and levels["primary_category_change"] == 3 and levels["hours_update"] == 2 and levels["description_improve"] == 1
    assert not any(a["can_be_preauthorised"] for a in p["actions"] if a["level"] == 3) and any("ranking" in r.lower() for r in p["rules"])


def test_the_autonomy_matrix_endpoint_says_posts_photos_and_ai_drafted_replies_need_a_person_and_template_replies_do_not(env):
    m = env.biz.get("/agent/autonomy").json()
    assert m["auto_publish"] is False and m["balanced_autonomy"]["default"] == "on" and "always need a person" in m["rule"]
