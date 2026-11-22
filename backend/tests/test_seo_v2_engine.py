"""Local SEO engine V2, part 3: the whole lifecycle against a real database, with Google as a TEST DOUBLE.

detect -> recommend -> approval required -> approved -> validated (dry run) -> executing -> verified (read back), and failed / blocked / superseded / rejected, plus the customer-write policy gate,
concurrent scans, tenant isolation and owner changes made outside FlowQR.

MOCKED: Google is `V2Google` below (it can accept, refuse, half-apply or lose a write). The database, row-level security, state machines, policy and gate are real. A pass proves FlowQR's own logic; it is
NOT evidence about how Google behaves, and nothing here ran against a real profile. docs/LOCAL_SEO_ENGINE_V2_TEST_MATRIX.md says exactly what has and has not been proven live."""
import uuid
from contextlib import closing
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import Settings, config_problems, settings
from app.core.db import SessionLocal, set_rls_context
from app.models import AgentAction, GbpSnapshot, GoogleLocation, Role, Tenant
from app.models.base import utcnow
from app.services import consent as consent_svc
from app.services import google as g
from app.services.agent import autonomy_policy as pol
from app.services.agent import controls, executor, seo_engine
from app.services.agent.v2 import fields as v2f
from app.services.agent.v2 import gate as v2gate
from app.services.agent.v2 import overview, owner
from app.services.agent.v2 import scan as v2_scan
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_gbp import gid  # noqa: F401
from tests.test_google_and_reviews import connected  # noqa: F401
from tests.test_phase1_executor import DESC, AutonomyGoogle, desc, env, evs, put_kb, refresh, run, st  # noqa: F401

PRIMARY = "categories/gcid:physiotherapist"
TYPES = {PRIMARY: [{"id": "job_type_id:back_care", "name": "Back care"}, {"id": "job_type_id:dry_needling", "name": "Dry needling"}]}
ATTR_META = {"attributes/wi_fi": {"valueType": "ENUM", "displayName": "Wi-Fi", "valueMetadata": [{"value": "free_wifi", "displayName": "Free"}, {"value": "paid_wifi", "displayName": "Paid"}]},
             "attributes/has_wheelchair_accessible_entrance": {"valueType": "BOOL", "displayName": "Wheelchair accessible entrance"},
             "attributes/old": {"valueType": "BOOL", "displayName": "Old", "deprecated": True}}
KB = {"description": "Physiotherapy for back and neck pain in Lucknow.", "services": ["Back care", "Neck pain physiotherapy", "Sports injury rehab"], "offers": [], "faqs": [], "prohibited_claims": []}


class V2Google(AutonomyGoogle):
    """TEST DOUBLE of Google's profile API including the V2 surfaces: complete-list services, special hours, service area, category sets, attributes, dry-run validation, getGoogleUpdated."""

    def __init__(self):
        super().__init__()
        self.details.update({"service_items": v2f.canon_services([{"k": "s", "id": "job_type_id:dry_needling"}]), "special_hours_periods": v2f.canon_special_hours([{"start": "2099-12-25", "closed": True}]),
                             "service_area": None, "has_regular_hours": True, "can_modify_service_list": True, "storefront_address": True, "language_code": "en"})
        self.attrs = v2f.canon_attributes([{"name": "wi_fi", "type": "ENUM", "value": "free_wifi"}])
        self.validate_calls, self.validate_error, self.attr_calls, self.diff_mask = [], None, [], ""
        self.category_results = [{"id": "categories/gcid:sports_injury_clinic", "name": "Sports injury clinic"}, {"id": "categories/gcid:pizza_restaurant", "name": "Pizza restaurant"}]
        self.apply_v2 = True

    # ---- reads
    def get_attributes_normalized(self, at, loc):
        self._maybe()
        return [dict(a) for a in self.attrs]

    def attribute_metadata_for_location(self, at, loc):
        return {k: dict(v) for k, v in ATTR_META.items()}

    def get_category_service_types(self, at, ids, region="IN", language="en"):
        return {i: TYPES.get(i, []) for i in ids}

    def search_categories(self, at, q, region="IN", language="en"):
        return list(self.category_results)

    def get_google_updated(self, at, loc, mask):
        return {"location": {}, "diff_mask": self.diff_mask, "pending_mask": ""}

    # ---- dry run and writes
    def validate_changes(self, at, loc, changes):
        self.validate_calls.append(dict(changes))
        if self.validate_error:
            raise self.validate_error
        return {}

    def update_location(self, at, loc, changes):
        v2 = {k: v for k, v in changes.items() if k in ("services", "special_hours", "service_area", "categories")}
        if not v2:
            return super().update_location(at, loc, changes)
        self.update_calls += 1
        if self.fail_updates:
            raise self.fail_updates.pop(0)
        if self.apply and self.apply_v2:
            if "services" in v2:
                self.details["service_items"] = v2f.canon_services(v2["services"])
            if "special_hours" in v2:
                self.details["special_hours_periods"] = v2f.canon_special_hours(v2["special_hours"])
            if "service_area" in v2:
                self.details["service_area"] = v2f.canon_service_area(v2["service_area"])
            if "categories" in v2:
                c = v2f.canon_categories(v2["categories"])
                self.details["primary_category"] = {"id": c["primary"], "name": c["primary"].split(":")[-1]}
                self.details["additional_categories"] = [{"id": x, "name": x.split(":")[-1]} for x in c["additional"]]
            self.writes.append(("update", dict(changes)))
        return dict(self.details)

    def update_attributes(self, at, loc, send, delete):
        self.attr_calls.append((list(send), list(delete)))
        if self.fail_updates:
            raise self.fail_updates.pop(0)
        if self.apply and self.apply_v2:
            cur = {a["name"]: a for a in self.attrs}
            cur.update({a["name"]: a for a in send})
            for n in delete:
                cur.pop(n, None)
            self.attrs = sorted(cur.values(), key=lambda a: a["name"])
        return {}


@pytest.fixture()
def fake(monkeypatch):
    f = V2Google()
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    return f


@pytest.fixture()
def tp(env, monkeypatch):  # noqa: F811
    """The location is a DEDICATED TEST profile: the policy gate is open for it (and only it)."""
    monkeypatch.setattr(settings, "seo_v2_test_location_names", env.gloc.google_location_name)
    return env


@pytest.fixture()
def closed(env, monkeypatch):  # noqa: F811
    """A CUSTOMER profile with the policy gate closed (the production default)."""
    monkeypatch.setattr(settings, "seo_v2_test_location_names", "")
    monkeypatch.setattr(settings, "seo_v2_customer_writes_enabled", False)
    return env


def scan(env_):
    out = v2_scan.scan_location_v2(env_.db, env_.tenant, env_.gloc)
    env_.db.commit()
    return out


def actions(env_, atype=None):
    q = select(AgentAction).where(AgentAction.google_location_id == env_.gloc.id)
    if atype:
        q = q.where(AgentAction.action_type == atype)
    env_.db.expire_all()
    return list(env_.db.scalars(q.order_by(AgentAction.created_at)))


def approve(env_, a, role=Role.owner):
    executor.decide(env_.db, a, user_id=env_.uid, role=role, approve=True)
    env_.db.commit()


def info(env_):
    env_.db.expire_all()
    return env_.db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == env_.gloc.id)).info


def service_names(env_):
    return {v2f.service_label(x, {t["id"]: t["name"] for t in TYPES[PRIMARY]}) for x in env_.fake.details["service_items"]}


# ============================================================================ 0. the snapshot carries what V2 needs
def test_the_snapshot_reads_services_attributes_and_googles_reference_catalog(env):
    i = info(env)
    assert i["service_items"] == env.fake.details["service_items"] and i["attributes"] == env.fake.attrs
    cat = i["catalog"]
    assert cat["service_types"][PRIMARY][0]["id"] == "job_type_id:back_care" and "attributes/wi_fi" in cat["attribute_metadata"]
    assert {c["id"] for c in cat["categories"]["candidates"]} >= {"categories/gcid:sports_injury_clinic"}
    assert cat["google_updated"]["diff_mask"] == ""


def test_a_catalog_failure_never_costs_the_owner_the_snapshot(env):
    env.fake.attribute_metadata_for_location = lambda at, loc: (_ for _ in ()).throw(g.GoogleAPIError(500, "boom"))
    refresh(env)
    i = info(env)
    assert i["description"] == env.fake.details["description"] and "attribute_metadata" not in i["catalog"] and i["catalog"]["errors"]


# ============================================================================ 1. services: the complete list, end to end
def test_services_flow_detect_recommend_approve_validate_execute_verify(tp):
    out = scan(tp)
    assert len(out["proposed"]) >= 1 and out["recommended"] == []
    (a,) = actions(tp, "service_update")
    assert (a.status, a.policy_level, a.authorization, a.risk_level, a.field_key) == ("pending_approval", 2, "owner", "medium", "services")
    before = {v2f.service_key(x) for x in tp.fake.details["service_items"]}
    after = {v2f.service_key(x) for x in a.proposed_value["canonical"]}
    assert before <= after and len(after) == 3  # every existing service kept; the two verified services in the Business Brain (Back care, Neck pain physiotherapy) added
    assert a.evidence["kept"] == 1 and a.evidence["from"] == "the services in your Business Brain"
    assert tp.fake.update_calls == 0 and tp.fake.validate_calls == []  # nothing happens before a person approves
    approve(tp, a)
    r = run(tp, a)
    assert r == {"status": "executed", "verified": True}
    assert len(tp.fake.validate_calls) == 1 and tp.fake.update_calls == 1
    assert set(tp.fake.validate_calls[0]) == {"services"} and len(tp.fake.validate_calls[0]["services"]) == 3  # the dry run saw the COMPLETE list
    assert before <= {v2f.service_key(x) for x in tp.fake.details["service_items"]}  # Dry needling is still there
    tp.db.expire_all()
    a = tp.db.get(AgentAction, a.id)
    assert a.status == "executed" and a.verified_at and a.validation_status == "validated" and a.verification["matched"] is True
    order = [e for e in evs(a.id) if e != "baseline_measured"]  # the ranking baseline is part of every rank-relevant change
    assert order == ["proposed", "policy_classified", "approved", "validated", "executing", "google_write", "read_back", "verified", "followups_scheduled"] or         order[:8] == ["proposed", "policy_classified", "approved", "validated", "executing", "google_write", "read_back", "verified"]  # the dry run comes BEFORE the claim and the write


def test_a_partial_service_list_is_never_sent_and_dropping_a_service_needs_the_owner(tp):
    cur = tp.fake.details["service_items"]
    only_new = v2f.canon_services([{"k": "c", "n": "Back care", "c": PRIMARY}])  # what a careless caller might send: just the new one
    a = executor.propose(tp.db, tp.tenant, tp.gloc, "service_update", proposed=only_new, source={"kind": "owner_input", "user_id": str(tp.uid)}, trigger="owner_request",
                         problem="x", reason="y", proposed_by="user", user_id=tp.uid)
    tp.db.commit()
    assert (a.policy_level, a.effective_type, a.status) == (3, "significant_removal", "pending_approval")  # it would drop Dry needling: an owner decision, flagged as a removal
    assert "drops a service" in " ".join(a.policy_reasons)
    with pytest.raises(executor.ActionError) as e:  # an admin cannot approve a removal
        executor.decide(tp.db, a, user_id=tp.uid, role=Role.admin, approve=True)
    assert e.value.status == 403
    assert tp.fake.update_calls == 0 and tp.fake.details["service_items"] == cur


def test_the_scan_never_proposes_removing_anything(tp):
    scan(tp)
    for a in actions(tp):
        d = pol.classify(a.action_type, field_key=a.field_key, current=a.current_value["value"], proposed=a.proposed_value["canonical"], kb=KB)
        assert d.effective_type != "significant_removal", a.action_type


def test_a_locked_service_list_gets_no_proposal_and_says_so(tp):
    tp.fake.details["can_modify_service_list"] = False
    refresh(tp)
    out = scan(tp)
    assert actions(tp, "service_update") == [] and out["detected"]["services"]["editable"] is False
    a = owner.propose_services(tp.db, tp.tenant, tp.gloc, user_id=tp.uid, names=["Posture assessment"])
    tp.db.commit()
    assert a.status == "blocked" and "cannot be edited" in a.last_error and tp.fake.update_calls == 0 and tp.fake.validate_calls == []
    area = next(x for x in overview.build(tp.db, tp.tenant, [tp.gloc])["locations"][0]["areas"] if x["key"] == "services")
    assert area["state"] == "improve" and area["fix"]["mode"] == "unavailable_via_api" and "cannot be edited" in area["summary"]


def test_an_unknown_eligibility_flag_is_not_assumed_editable(tp):
    tp.fake.details["can_modify_service_list"] = None
    refresh(tp)
    scan(tp)
    assert actions(tp, "service_update") == []


def test_an_unread_service_list_proposes_nothing_instead_of_replacing_everything(tp):
    snap = tp.db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == tp.gloc.id))
    snap.info = {k: v for k, v in snap.info.items() if k != "service_items"}
    tp.db.commit()
    out = scan(tp)
    assert actions(tp, "service_update") == [] and out["proposed"] == []
    with pytest.raises(executor.ActionError):
        owner.propose_services(tp.db, tp.tenant, tp.gloc, user_id=tp.uid, names=["x"])


# ============================================================================ 2. the dry run
def test_google_refusing_the_dry_run_blocks_the_change_and_nothing_is_written(tp):
    scan(tp)
    (a,) = actions(tp, "service_update")
    approve(tp, a)
    tp.fake.validate_error = g.GoogleAPIError(400, "serviceItems[2].freeFormServiceItem.category is invalid")
    r = run(tp, a)
    assert r["status"] == "blocked" and r["reason"] == "validation_failed"
    tp.db.expire_all()
    a = tp.db.get(AgentAction, a.id)
    assert a.validation_status == "rejected" and "category is invalid" in a.last_error and a.validation["method"] == "validateOnly"
    assert tp.fake.update_calls == 0 and "validation_failed" in evs(a.id)
    assert owner_query("SELECT autonomy_failure_streak FROM agent_settings WHERE tenant_id = :t", t=tp.tenant.id)[0][0] == 0  # Google's verdict on a value is not a write failure


def test_a_transient_dry_run_error_is_retried_not_treated_as_a_verdict(tp):
    scan(tp)
    (a,) = actions(tp, "service_update")
    approve(tp, a)
    tp.fake.validate_error = g.GoogleAPIError(503, "try later")
    r = run(tp, a)
    assert r["status"] == "approved" and r["reason"] == "retry" and tp.fake.update_calls == 0
    tp.fake.validate_error = None
    r2 = executor.execute(tp.db, a.id, provider=tp.fake, sleep=lambda s: None, now=utcnow() + timedelta(hours=1))
    assert r2["status"] == "executed"


def test_a_provider_that_cannot_dry_run_never_gets_an_unvalidated_v2_write(tp):
    scan(tp)
    (a,) = actions(tp, "service_update")
    approve(tp, a)
    class NoDryRun(V2Google):
        def __getattribute__(self, n):
            if n == "validate_changes":
                raise AttributeError(n)  # hasattr() is False: this provider has no dry run at all
            return super().__getattribute__(n)

    nd = NoDryRun()
    nd.details = tp.fake.details
    r = executor.execute(tp.db, a.id, provider=nd, sleep=lambda s: None)
    assert r["status"] == "blocked" and r["reason"] == "validation_failed" and nd.update_calls == 0 and tp.fake.update_calls == 0


# ============================================================================ 3. failure, retry, read-back
def test_a_failed_write_is_retried_then_succeeds_without_a_second_edit(tp):
    scan(tp)
    (a,) = actions(tp, "service_update")
    approve(tp, a)
    tp.fake.fail_updates = [g.GoogleAPIError(503, "unavailable")]
    r = run(tp, a)
    assert r["status"] == "approved" and r["reason"] == "retry" and tp.fake.details["service_items"] == v2f.canon_services([{"k": "s", "id": "job_type_id:dry_needling"}])
    r2 = executor.execute(tp.db, a.id, provider=tp.fake, sleep=lambda s: None, now=utcnow() + timedelta(hours=1))
    assert r2["status"] == "executed" and len([w for w in tp.fake.writes if "services" in w[1]]) == 1


def test_a_write_google_accepts_but_does_not_apply_is_a_failure_never_a_success(tp):
    scan(tp)
    (a,) = actions(tp, "service_update")
    approve(tp, a)
    tp.fake.apply_v2 = False
    r = run(tp, a)
    assert r["status"] == "failed" and r["reason"] == "read_back_mismatch"
    tp.db.expire_all()
    a = tp.db.get(AgentAction, a.id)
    assert a.status == "failed" and a.verified_at is None and a.verification["matched"] is False and "does not show" in a.last_error


def test_a_lost_response_is_resolved_by_reading_google_never_by_writing_again(tp):
    scan(tp)
    (a,) = actions(tp, "service_update")
    approve(tp, a)
    tp.fake.raise_after_apply = g.GoogleAPIError(504, "timeout")
    # the write landed on Google but the answer was lost: simulate the interrupted state the recovery job handles
    tp.fake.details["service_items"] = v2f.canon_services(a.proposed_value["canonical"])
    owner_exec("UPDATE agent_actions SET status = 'executing', claimed_at = now() - interval '30 minutes', attempts = 1 WHERE id = :a", a=a.id)
    out = executor.recover_stuck(tp.db, provider=tp.fake)
    assert out["verified"] == 1 and tp.fake.update_calls == 0 and st(a.id) == "executed"


# ============================================================================ 4. the policy gate
def test_with_the_gate_closed_v2_drafts_and_recommends_but_never_touches_a_customer_profile(closed):
    out = scan(closed)
    assert out["proposed"] == [] and len(out["recommended"]) >= 1
    (a,) = actions(closed, "service_update")
    assert a.status == "recommended" and a.authorization == "owner" and "not made by FlowQr" in " ".join(a.policy_reasons).replace("FlowQR", "FlowQr")
    assert a.proposed_value["canonical"] and a.current_value["value"] is not None  # the exact before and after are drafted
    assert closed.fake.update_calls == 0 and closed.fake.validate_calls == [] and closed.fake.attr_calls == []
    assert "recommended" in evs(a.id)
    with pytest.raises(executor.ActionError) as e:  # an approval button does not open the gate
        executor.decide(closed.db, a, user_id=closed.uid, role=Role.owner, approve=True)
    assert e.value.status == 409 and "Google" in str(e.value)
    # even a row forced into 'approved' by something else is held, not executed, and not failed
    owner_exec("UPDATE agent_actions SET status = 'approved' WHERE id = :a", a=a.id)
    r = run(closed, a)
    assert r["status"] == "held" and r["reason"] == "policy_gate" and closed.fake.update_calls == 0 and closed.fake.validate_calls == []
    assert st(a.id) == "approved"


def test_the_owner_can_dismiss_a_recommendation_and_it_is_not_proposed_again(closed):
    scan(closed)
    (a,) = actions(closed, "service_update")
    executor.decide(closed.db, a, user_id=closed.uid, role=Role.owner, approve=False, reason="we do not offer these yet")
    closed.db.commit()
    assert st(a.id) == "rejected"
    out = scan(closed)
    assert out["recommended"] == [] and any("rejected" in s for s in out["skipped"])
    assert len(actions(closed, "service_update")) == 1


def test_a_recommendation_can_be_promoted_once_the_gate_opens(closed, monkeypatch):
    scan(closed)
    (a,) = actions(closed, "service_update")
    monkeypatch.setattr(settings, "seo_v2_test_location_names", closed.gloc.google_location_name)
    executor.decide(closed.db, a, user_id=closed.uid, role=Role.owner, approve=True)  # the gate is open for this profile now: it is promoted and approved like any change
    closed.db.commit()
    assert st(a.id) == "approved" and "promoted" in evs(a.id)
    assert run(closed, a)["status"] == "executed"


def test_the_gate_is_open_only_for_test_profiles_or_with_a_recorded_google_answer(monkeypatch):
    gl = GoogleLocation(google_location_name="locations/1", tenant_id=uuid.uuid4())
    monkeypatch.setattr(settings, "seo_v2_test_location_names", "")
    monkeypatch.setattr(settings, "seo_v2_customer_writes_enabled", False)
    assert v2gate.check(gl)["allowed"] is False and v2gate.check(gl)["reason"]
    monkeypatch.setattr(settings, "seo_v2_test_location_names", "locations/1, locations/9")
    assert v2gate.check(gl) == {"allowed": True, "test_profile": True, "customer_writes": False, "reason": None}
    assert v2gate.check(GoogleLocation(google_location_name="locations/2", tenant_id=uuid.uuid4()))["allowed"] is False  # a different profile stays closed
    monkeypatch.setattr(settings, "seo_v2_test_location_names", "")
    monkeypatch.setattr(settings, "seo_v2_customer_writes_enabled", True)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "seo_v2_policy_reference", "")
    assert v2gate.check(gl)["allowed"] is False  # production without a recorded answer: closed even if the switch is on (fails closed at run time too)
    monkeypatch.setattr(settings, "seo_v2_policy_reference", "case-123")
    assert v2gate.check(gl)["allowed"] is True
    assert v2gate.status_for(gl, "description")["applies"] is False  # a legacy field is never held by this gate


def test_the_start_up_guard_refuses_customer_writes_without_a_recorded_answer():
    def prod(**over):
        base = dict(app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True, public_card_base_url="https://go.flowqr.co.in",
                    frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in", database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr",
                    platform_admin_emails="ops@flowhq.in", smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
                    card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback", google_client_id="id", google_client_secret="secret")
        base.update(over)
        return Settings(_env_file=None, **base)
    assert config_problems(prod()) == []  # the default: off, and that is a valid production configuration
    assert any("SEO_V2_POLICY_REFERENCE" in p for p in config_problems(prod(seo_v2_customer_writes_enabled=True)))
    assert config_problems(prod(seo_v2_customer_writes_enabled=True, seo_v2_policy_reference="case-123")) == []
    assert any("together with the decision" in p for p in config_problems(prod(seo_v2_policy_reference="case-123")))  # a reference without the decision is a mistake too


def test_v2_changes_can_never_be_pre_authorised_or_consented_to():
    v2 = ("service_update", "special_hours_update", "attribute_change", "category_set_update", "service_area_change")
    assert not set(v2) & set(consent_svc.scopes())
    for t in v2:
        assert pol.validate_permissions({t: "auto"}), t
        assert pol.authorization_for(pol.classify(t, field_key=pol.SPECS[t].field, current=None, proposed=None, kb=KB), autonomy_enabled=True, suspended=False, permissions={t: "auto"}) == "owner"


def test_the_legacy_description_path_is_not_held_by_the_v2_gate(closed):
    a = desc(closed)
    approve(closed, a, role=Role.owner)
    assert run(closed, a)["status"] == "executed" and closed.fake.details["description"] == DESC


def test_the_platform_emergency_stop_holds_v2_execution_too(tp):
    scan(tp)
    (a,) = actions(tp, "service_update")
    approve(tp, a)
    controls.set_emergency_stop(tp.db, on=True, user_id=None, reason="test")
    tp.db.commit()
    r = run(tp, a)
    owner_exec("DELETE FROM platform_controls")
    assert r["status"] == "held" and r["reason"] == "emergency_stop" and tp.fake.update_calls == 0 and tp.fake.validate_calls == []


# ============================================================================ 5. special hours, attributes, categories, contacts, service area
def test_special_hours_are_added_to_what_is_on_google_and_verified(tp):
    a = owner.propose_special_hours(tp.db, tp.tenant, tp.gloc, user_id=tp.uid, entries=[{"start": "2099-12-31", "open": "09:00", "close": "14:00"}])
    tp.db.commit()
    assert (a.status, a.policy_level, a.source["kind"]) == ("pending_approval", 2, "owner_input")
    assert {p["start"] for p in a.proposed_value["canonical"]} == {"2099-12-25", "2099-12-31"}  # the existing holiday is kept
    approve(tp, a)
    assert run(tp, a)["status"] == "executed"
    assert {p["start"] for p in tp.fake.details["special_hours_periods"]} == {"2099-12-25", "2099-12-31"}
    assert tp.fake.validate_calls[0]["special_hours"][0]["start"] == "2099-12-25"


def test_a_clashing_date_is_a_conflict_the_owner_resolves_not_an_overwrite(tp):
    with pytest.raises(executor.ActionError) as e:
        owner.propose_special_hours(tp.db, tp.tenant, tp.gloc, user_id=tp.uid, entries=[{"start": "2099-12-25", "open": "10:00", "close": "12:00"}])
    assert e.value.status == 409 and "2099-12-25" in str(e.value) and tp.fake.update_calls == 0


def test_special_hours_need_regular_hours_first(tp):
    tp.fake.details["has_regular_hours"] = False
    tp.fake.details["hours"] = []
    refresh(tp)
    a = owner.propose_special_hours(tp.db, tp.tenant, tp.gloc, user_id=tp.uid, entries=[{"start": "2099-12-31", "closed": True}])
    tp.db.commit()
    assert a.status == "blocked" and "regular opening hours" in a.last_error


def test_invalid_special_hours_are_refused_with_a_reason(tp):
    with pytest.raises(pol.PolicyError):
        owner.propose_special_hours(tp.db, tp.tenant, tp.gloc, user_id=tp.uid, entries=[{"start": "31-12-2099", "closed": True}])
    a = owner.propose_special_hours(tp.db, tp.tenant, tp.gloc, user_id=tp.uid, entries=[{"start": "2099-12-31", "open": "14:00", "close": "09:00"}])
    tp.db.commit()
    assert a.status == "blocked" and "after the opening time" in a.last_error


def test_attributes_come_only_from_the_owners_answers_and_are_checked_against_googles_metadata(tp):
    a = owner.propose_attributes(tp.db, tp.tenant, tp.gloc, user_id=tp.uid, answers=[{"name": "has_wheelchair_accessible_entrance", "value": True}])
    tp.db.commit()
    assert (a.status, a.policy_level, a.field_key) == ("pending_approval", 2, "attributes")
    assert {x["name"] for x in a.proposed_value["canonical"]} == {"attributes/wi_fi", "attributes/has_wheelchair_accessible_entrance"}  # the existing answer is kept
    approve(tp, a)
    assert run(tp, a)["status"] == "executed"
    send, gone = tp.fake.attr_calls[0]
    assert [x["name"] for x in send] == ["attributes/has_wheelchair_accessible_entrance"] and gone == []  # only what changed is sent
    assert {x["name"] for x in tp.fake.attrs} == {"attributes/wi_fi", "attributes/has_wheelchair_accessible_entrance"}
    assert tp.fake.update_calls == 0  # attributes are a separate resource: no location patch


def test_attributes_googles_metadata_refuses_are_refused_before_a_proposal_exists(tp):
    for bad in ({"name": "wi_fi", "value": "gold"}, {"name": "made_up", "value": True}, {"name": "old", "value": True}, {"name": "has_wheelchair_accessible_entrance", "value": "yes"}):
        with pytest.raises(pol.PolicyError):
            owner.propose_attributes(tp.db, tp.tenant, tp.gloc, user_id=tp.uid, answers=[bad])
    assert actions(tp, "attribute_change") == []


def test_the_scan_never_proposes_an_attribute_it_only_asks(tp):
    scan(tp)
    assert actions(tp, "attribute_change") == []
    area = next(x for x in overview.build(tp.db, tp.tenant, [tp.gloc])["locations"][0]["areas"] if x["key"] == "attributes")
    assert area["fix"]["mode"] == "owner_input_needed" and {q["name"] for q in area["questions"]} == {"attributes/has_wheelchair_accessible_entrance"}


def test_a_category_set_is_proposed_only_with_evidence_needs_the_owner_and_keeps_the_primary(tp):
    put_kb(tp, KB)  # the owner lists "Sports injury rehab": that is the evidence for the Sports injury clinic category
    scan(tp)
    (a,) = actions(tp, "category_set_update")
    assert (a.policy_level, a.status, a.authorization) == (3, "pending_approval", "owner")
    c = a.proposed_value["canonical"]
    assert c["primary"] == PRIMARY and c["additional"] == ["categories/gcid:sports_injury_clinic"]  # Pizza restaurant: nothing the owner said supports it
    assert a.source["category_matches"] == {"categories/gcid:sports_injury_clinic": "Sports injury rehab"}
    with pytest.raises(executor.ActionError) as e:
        executor.decide(tp.db, a, user_id=tp.uid, role=Role.admin, approve=True)
    assert e.value.status == 403
    approve(tp, a, role=Role.owner)
    assert run(tp, a)["status"] == "executed"
    assert tp.fake.details["primary_category"]["id"] == PRIMARY and [x["id"] for x in tp.fake.details["additional_categories"]] == ["categories/gcid:sports_injury_clinic"]
    assert set(tp.fake.validate_calls[-1]) == {"categories"}  # primary and additional travelled together


def test_a_different_phone_in_the_record_is_flagged_for_the_owner_never_applied(tp):
    owner_exec("UPDATE tenants SET phone = '+91 90000 00000' WHERE id = :t", t=tp.tenant.id)
    tp.db.expire_all()
    scan(tp)
    (a,) = actions(tp, "primary_contact_change")
    assert (a.field_key, a.policy_level, a.status) == ("phone", 3, "pending_approval") and tp.fake.details["phone"] == "+91 98765 43210"


def test_service_area_changes_keep_the_business_type_and_always_need_the_owner(tp):
    with pytest.raises(executor.ActionError):  # no area on Google: nothing to keep, so nothing to invent
        owner.propose_service_area(tp.db, tp.tenant, tp.gloc, user_id=tp.uid, places=[{"name": "Lucknow", "place_id": "p1"}])
    tp.fake.details["service_area"] = v2f.canon_service_area({"business_type": "CUSTOMER_LOCATION_ONLY", "region": "IN", "places": [{"name": "Lucknow", "place_id": "p1"}]})
    refresh(tp)
    a = owner.propose_service_area(tp.db, tp.tenant, tp.gloc, user_id=tp.uid, places=[{"name": "Lucknow", "place_id": "p1"}, {"name": "Unnao", "place_id": "p2"}])
    tp.db.commit()
    assert (a.status, a.policy_level) == ("pending_approval", 3)
    approve(tp, a, role=Role.owner)
    assert run(tp, a)["status"] == "executed" and len(tp.fake.details["service_area"]["places"]) == 2


# ============================================================================ 6. repeat, concurrent and outside changes
def test_scanning_twice_never_duplicates_a_proposal(tp):
    scan(tp)
    n = len(actions(tp))
    scan(tp)
    scan(tp)
    assert len(actions(tp)) == n and len({a.idempotency_key for a in actions(tp) if a.status in ("pending_approval", "recommended")}) == n


def test_two_simultaneous_scans_of_one_location_cannot_both_propose(tp):
    assert v2_scan._lock(tp.db, tp.gloc) is True  # scan A holds the location's lock
    db2 = SessionLocal()
    set_rls_context(db2, bypass=True)
    try:
        out = v2_scan.scan_location_v2(db2, db2.get(Tenant, tp.tenant.id), db2.get(GoogleLocation, tp.gloc.id))
        db2.commit()
    finally:
        db2.close()
    assert out["proposed"] == [] and out["recommended"] == [] and any("another scan" in s for s in out["skipped"])
    tp.db.rollback()  # A finishes: the lock is released
    out2 = scan(tp)
    assert len(out2["proposed"]) >= 1


def test_the_owner_changing_services_in_google_supersedes_the_draft_and_a_fresh_one_fits(tp):
    scan(tp)
    (a,) = actions(tp, "service_update")
    tp.fake.details["service_items"] = v2f.canon_services(tp.fake.details["service_items"] + [{"k": "c", "n": "Posture assessment", "c": PRIMARY}])  # edited in Google, outside FlowQR
    refresh(tp)
    out = scan(tp)
    assert str(a.id) in out["superseded"] and st(a.id) == "superseded"
    assert "superseded" in evs(a.id)
    live = [x for x in actions(tp, "service_update") if x.status == "pending_approval"]
    assert len(live) == 1 and live[0].id != a.id
    assert any(v2f.key_of(x.get("n", "")) == "posture assessment" for x in live[0].proposed_value["canonical"])  # the owner's own addition is kept


def test_a_change_that_google_already_shows_is_recorded_as_superseded_not_applied_twice(tp):
    scan(tp)
    (a,) = actions(tp, "service_update")
    tp.fake.details["service_items"] = v2f.canon_services(a.proposed_value["canonical"])
    refresh(tp)
    scan(tp)
    tp.db.expire_all()
    a = tp.db.get(AgentAction, a.id)
    assert a.status == "superseded" and "already shows" in a.last_error and tp.fake.update_calls == 0


def test_fields_google_reports_as_changed_are_not_proposed_over_and_never_reverted(tp):
    tp.fake.diff_mask = "serviceItems,categories"
    refresh(tp)
    out = scan(tp)
    assert out["detected"]["google_changed"] == ["categories", "services"]
    assert actions(tp, "service_update") == [] and actions(tp, "category_set_update") == []
    assert any("Google has changed" in s for s in out["skipped"]) and tp.fake.update_calls == 0


def test_the_existing_scan_still_runs_and_the_v2_scan_cannot_break_it(tp, monkeypatch):
    out = seo_engine.scan_tenant(tp.db, tp.tenant)
    tp.db.commit()
    assert out["locations"] == 1 and out["proposed"] >= 1 and "recommended" in out
    monkeypatch.setattr(v2_scan, "scan_location_v2", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out2 = seo_engine.scan_tenant(tp.db, tp.tenant)
    assert out2["locations"] == 1 and any("V2 scan could not run" in s for s in out2["skipped"])


# ============================================================================ 7. isolation
def test_one_business_cannot_propose_on_anothers_profile_or_see_its_v2_data(tp):
    other = make_business("Other Physio")
    with pytest.raises(pol.PolicyError):
        # the location belongs to the first business: the second business's tenant record is refused
        executor.propose(tp.db, tp.db.get(Tenant, uuid.UUID(other.tenant_id)), tp.gloc, "service_update", proposed=[{"k": "s", "id": "x"}], source={"kind": "owner_input", "user_id": "u"},
                         trigger="t", problem="p", reason="r", proposed_by="user", user_id=tp.uid)
    scan(tp)
    assert other.get("/seo/v2/overview").json()["locations"] == [] and other.get("/agent/actions").json() == {"actions": []}
    assert other.post("/seo/v2/special-hours", json={"google_location_id": tp.gid, "entries": [{"start": "2099-12-31", "closed": True}]}).status_code == 404
    mine = SessionLocal()
    set_rls_context(mine, tenant_id=uuid.UUID(other.tenant_id))
    try:
        assert mine.scalar(select(AgentAction.id).where(AgentAction.field_key == "services")) is None
    finally:
        mine.close()


# ============================================================================ 8. the dashboard and its API
def test_the_overview_reports_only_what_exists_and_how_each_fix_is_made(closed):
    put_kb(closed, KB)
    scan(closed)
    out = closed.biz.get("/seo/v2/overview").json()
    loc = out["locations"][0]
    assert loc["profile_read"] is True and loc["gate"]["allowed"] is False and loc["gate"]["reason"]
    areas = {a["key"]: a for a in loc["areas"]}
    assert areas["services"]["fix"]["mode"] == "recommended_only" and areas["categories"]["fix"]["mode"] == "recommended_only"
    assert areas["attributes"]["fix"]["mode"] == "owner_input_needed" and areas["description"]["state"] in ("ok", "improve", "missing")
    t = out["totals"]
    assert t["recommended_only"] == len(loc["actions"]["recommended"]) >= 2 and t["verified_on_google"] == 0 and t["pending_approvals"] == 0 and t["failed"] == 0
    row = loc["actions"]["recommended"][0]
    assert row["diff"]["added"] and row["before"] is not None and row["after"] is not None and row["status"] == "recommended" and row["v2"] is True
    assert out["health"] is None or isinstance(out["health"]["score"], (int, type(None)))  # never a fabricated score
    assert loc["opportunities"] and all(o["evidence"] for o in loc["opportunities"])
    assert "volume" not in repr(loc["opportunities"]).lower()


def test_the_overview_counts_a_verified_change_only_after_the_read_back(tp):
    scan(tp)
    (a,) = actions(tp, "service_update")
    approve(tp, a)
    assert tp.biz.get("/seo/v2/overview").json()["totals"]["verified_on_google"] == 0  # approved is not verified
    run(tp, a)
    t = tp.biz.get("/seo/v2/overview").json()["totals"]
    assert t["verified_on_google"] == 1 and t["verified_last_90_days"] == 1


def test_an_unread_profile_shows_nothing_scored(env):
    owner_exec("UPDATE gbp_snapshots SET info = NULL WHERE google_location_id = :g", g=env.gid)
    loc = env.biz.get("/seo/v2/overview").json()["locations"][0]
    assert loc["profile_read"] is False and loc["areas"] == [] and "not read" in loc["note"]


def test_the_special_hours_endpoint_creates_a_recommendation_or_a_proposal_by_gate(closed, monkeypatch):
    r = closed.biz.post("/seo/v2/special-hours", json={"google_location_id": closed.gid, "entries": [{"start": "2099-12-31", "closed": True}]})
    assert r.status_code == 201 and r.json()["status"] == "recommended" and r.json()["v2"] is True
    monkeypatch.setattr(settings, "seo_v2_test_location_names", closed.gloc.google_location_name)
    r2 = closed.biz.post("/seo/v2/special-hours", json={"google_location_id": closed.gid, "entries": [{"start": "2099-11-30", "closed": True}]})
    assert r2.status_code == 201 and r2.json()["status"] == "pending_approval"
    bad = closed.biz.post("/seo/v2/special-hours", json={"google_location_id": closed.gid, "entries": [{"start": "bad", "closed": True}]})
    assert bad.status_code == 422 and closed.biz.post("/seo/v2/attributes", json={"google_location_id": closed.gid, "answers": [{"name": "nope", "value": True}]}).status_code == 422
    assert closed.fake.update_calls == 0 and closed.fake.validate_calls == []  # an API request alone never reaches Google


def test_approving_through_the_api_on_a_closed_gate_is_refused_with_the_reason(closed):
    r = closed.biz.post("/seo/v2/special-hours", json={"google_location_id": closed.gid, "entries": [{"start": "2099-12-31", "closed": True}]}).json()
    resp = closed.biz.post(f"/agent/actions/{r['id']}/approve", json={})
    assert resp.status_code == 409 and "Google" in resp.json()["detail"]
    assert closed.biz.post(f"/agent/actions/{r['id']}/reject", json={"reason": "not now"}).status_code == 200


# ============================================================================ 9. the separate notice
def test_a_verified_change_sends_a_separate_notice_to_the_person_who_approved_it(tp):
    from app.services import mailer
    mailer.OUTBOX.clear()
    scan(tp)
    (a,) = actions(tp, "service_update")
    approve(tp, a)
    assert mailer.OUTBOX == []  # nothing is sent before the change is on Google
    assert run(tp, a)["status"] == "executed"
    mails = [m for m in mailer.OUTBOX if "changed services" in m["subject"].lower() or "service" in m["subject"].lower()]
    assert len(mails) == 1
    body = mails[0]["body"]
    assert "separate notice from FlowQR, not from Google" in body and "read your profile back" in body and "never undoes" in body and "disconnect" in body
    assert "+ Back care" in body and "Activity history" in body
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'email.sent' AND metadata->>'kind' = 'seo_v2_change_notice'", t=tp.tenant.id)[0][0] == 1


def test_no_notice_is_sent_for_a_change_that_failed_or_was_never_approved(tp):
    from app.services import mailer
    mailer.OUTBOX.clear()
    scan(tp)
    (a,) = actions(tp, "service_update")
    approve(tp, a)
    tp.fake.apply_v2 = False
    assert run(tp, a)["status"] == "failed"
    assert mailer.OUTBOX == []


# ============================================================================ 10. plain-language diff everywhere an action is shown
def test_every_screen_that_lists_actions_gets_a_plain_diff_for_v2_changes_never_raw_json(tp):
    scan(tp)
    rows = tp.biz.get("/agent/actions").json()["actions"]
    svc = next(r for r in rows if r["field"] == "services")
    assert svc["diff"]["added"] and svc["diff"]["removed"] == [] and all(isinstance(x, str) for x in svc["diff"]["after"])
    assert "{" not in " ".join(svc["diff"]["before"] + svc["diff"]["after"])  # no JSON object text reaches a person
    assert "diff" in tp.biz.get(f"/agent/actions/{svc['id']}").json()
    legacy = next((r for r in rows if r["field"] not in ("services", "categories", "special_hours", "attributes", "service_area")), None)
    assert legacy is None or "diff" not in legacy  # legacy fields keep their existing presentation
