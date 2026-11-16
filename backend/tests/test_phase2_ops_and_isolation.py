"""Phase 2: the onboarding checklist (computed from real records), readiness, the release-gate record, and tenant isolation of everything Phase 2 added.

MOCKED where Google or Razorpay appear (test doubles); the database, row-level security, roles and the computed checklist are real."""
import json
import uuid
from pathlib import Path

import pytest

from app.core.db import SessionLocal, set_rls_context
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_billing import activate, rzp  # noqa: F401
from tests.test_gbp import fake, gid  # noqa: F401
from tests.test_google_and_reviews import connected  # noqa: F401
from tests.test_location_permissions import invite
from tests.test_phase2_plans import SHIP, buy_cards  # noqa: F401


def checklist(biz):
    r = biz.get("/workspace/getting-started")
    assert r.status_code == 200, r.text
    return r.json(), {s["id"]: s for s in r.json()["steps"]}


# ============================================================================ getting started: only what exists in the database

def test_a_new_business_sees_what_is_really_left_and_nothing_is_pre_ticked():
    biz = make_business("Fresh Co", with_location=False)
    data, s = checklist(biz)
    # the test helper verifies the email and every new business is on a free trial; everything else is genuinely undone: no demo data, no pre-ticked step
    assert {k for k, v in s.items() if v["done"]} == {"verify_email", "plan"}
    assert data["complete"] is False and data["next"] == "location" and s["plan"]["why"].startswith("Your free trial has")
    assert s["google"]["optional"] is True and "business.google.com" in s["google"]["note"]  # a business with no Google profile is told what to do, not blocked
    assert s["card"]["optional"] is True and "order" in s["card"]["note"].lower()


def test_each_step_turns_done_only_when_its_real_record_exists(rzp):
    biz = make_business("Progress Co")
    _, s = checklist(biz)
    assert s["location"]["done"] is True  # make_business creates one with a review link
    assert s["review_link"]["done"] is True and s["campaign"]["done"] is False and s["card"]["done"] is False and s["plan"]["done"] is True  # a trial counts as "free period"
    assert "free trial" in s["plan"]["why"].lower() and "nothing is charged automatically" in s["plan"]["why"]
    biz.post("/review-growth/campaigns", json={"name": "Front desk", "location_id": biz.location_id})
    assert checklist(biz)[1]["campaign"]["done"] is True
    assert checklist(biz)[1]["notifications"]["done"] is False
    assert biz.put("/notifications/preferences", json={"email_new_review": True, "email_flagged_review": True, "email_sync_failed": True, "email_trial_ending": True}).status_code == 200
    assert checklist(biz)[1]["notifications"]["done"] is True
    activate(biz, rzp, "growth")
    assert "Growth" in checklist(biz)[1]["plan"]["why"] and checklist(biz)[1]["plan"]["done"] is True


def test_a_card_purchase_is_shown_as_a_free_period_that_ends_without_a_charge(rzp):
    biz = make_business("Card Month Co")
    owner_exec("UPDATE subscriptions SET status = 'expired', trial_ends_at = now() - interval '1 day' WHERE tenant_id = :t", t=biz.tenant_id)
    assert checklist(biz)[1]["plan"]["done"] is False  # an expired trial is not a plan
    buy_cards(biz, rzp, 1)
    plan = checklist(biz)[1]["plan"]
    assert plan["done"] is True and "free Growth month" in plan["why"] and "Nothing is charged when it ends" in plan["why"]


def test_a_step_the_plan_does_not_include_is_shown_locked_with_the_plan_that_adds_it():
    biz = make_business("Launch Co")
    from tests.test_phase2_plans import set_plan
    set_plan(biz.tenant_id, "starter")
    s = checklist(biz)[1]["autonomy"]
    assert s["locked"] == "Included in Growth and Scale" and s["optional"] is True
    set_plan(biz.tenant_id, "growth")
    assert checklist(biz)[1]["autonomy"]["locked"] is None


def test_the_checklist_is_per_business_and_readable_by_staff():
    a, b = make_business("Check A"), make_business("Check B")
    b.post("/review-growth/campaigns", json={"name": "B campaign", "location_id": b.location_id})
    assert checklist(a)[1]["campaign"]["done"] is False and checklist(b)[1]["campaign"]["done"] is True  # B's progress never shows on A
    assert invite(a, "staff").get("/workspace/getting-started").status_code == 200


def test_the_checklist_completes_when_every_required_step_is_done(rzp):
    biz = make_business("Complete Co")
    biz.post("/review-growth/campaigns", json={"name": "Desk", "location_id": biz.location_id})
    owner_exec("UPDATE users SET email_verified_at = now() WHERE id = (SELECT user_id FROM memberships WHERE tenant_id = :t LIMIT 1)", t=biz.tenant_id)
    data, s = checklist(biz)
    required = [k for k, v in s.items() if not v["optional"] and not v["locked"]]
    assert all(s[k]["done"] for k in required) and data["complete"] is True and data["required_done"] == data["required_total"]


# ============================================================================ readiness

def redis_up(monkeypatch):
    from app.services import ops
    monkeypatch.setattr(ops, "check_redis", lambda: ops.row("redis", "Redis", "ok", "Responding"))  # the test environment has no Redis container


def test_ready_is_200_when_the_instance_can_serve_and_says_only_statuses(client, monkeypatch):
    redis_up(monkeypatch)
    r = client.get("/api/ready")
    assert r.status_code == 200 and r.json() == {"ready": True, "checks": {"database": "ok", "redis": "ok", "migrations": "ok"}}


def test_ready_is_503_when_the_database_is_not_at_the_revision_the_code_expects(client, monkeypatch):
    from app.services import ops
    redis_up(monkeypatch)
    monkeypatch.setattr(ops, "check_migrations", lambda db: ops.row("migrations", "Database migrations", "critical", "Database is at 0001, code expects 0030"))
    r = client.get("/api/ready")
    assert r.status_code == 503 and r.json()["ready"] is False and r.json()["checks"]["migrations"] == "critical"
    assert "0001" not in r.text and "0030" not in r.text  # revisions are not disclosed to anonymous callers


def test_ready_is_503_when_redis_is_down_and_does_not_say_why(client):
    r = client.get("/api/ready")  # no Redis in the test environment: the endpoint says so, with a status only
    assert r.status_code == 503 and r.json()["checks"]["redis"] == "critical" and "container" not in r.text.lower()


def test_ready_does_not_depend_on_the_worker(client, monkeypatch):
    from app.services import ops
    redis_up(monkeypatch)
    monkeypatch.setattr(ops, "check_heartbeat", lambda: ops.row("worker", "Worker", "critical", "stopped"))
    assert client.get("/api/ready").status_code == 200  # a stopped worker must not take the website out of service


# ============================================================================ release gates: the ladder cannot be faked

GATES = Path(__file__).resolve().parents[1] / "app" / "release_gates.json"


def test_the_release_record_is_served_to_platform_admins_only(admin, biz_a):
    assert biz_a.get("/admin/release-gates").status_code == 403
    r = admin.get("/admin/release-gates").json()
    assert [g["id"] for g in r["gates"]] == ["unit_tested", "integration_doubles", "real_google", "real_places", "staging_validated", "production_approved"]


def test_a_rung_can_only_be_passed_with_dated_evidence_and_nothing_live_is_claimed_without_it():
    data = json.loads(GATES.read_text(encoding="utf-8"))
    by = {g["id"]: g for g in data["gates"]}
    for g in data["gates"]:
        assert g["status"] in ("passed", "not_done"), g["id"]
        if g["status"] == "passed":
            assert g["date"] and g["evidence"], f"{g['id']} is marked passed without a date and evidence"
        else:
            assert g["blocked_by"], f"{g['id']} is not done: say what blocks it"
    live = ("real_google", "real_places", "staging_validated", "production_approved")
    passed_live = [k for k in live if by[k]["status"] == "passed"]
    # today nothing live has been run; if someone later marks one passed they must also have filled the evidence (checked above) and updated the overall statement
    if len(passed_live) < len(live):
        assert "Production Ready" not in data["overall"]
    assert "External Validation Pending" in data["overall"] or len(passed_live) == len(live)


def test_the_test_doubles_can_never_be_the_evidence_for_a_live_rung():
    data = json.loads(GATES.read_text(encoding="utf-8"))
    by = {g["id"]: g for g in data["gates"]}
    for k in ("unit_tested", "integration_doubles"):
        assert by[k]["status"] == "passed"
    for k in ("real_google", "real_places"):
        ev = (by[k]["evidence"] or "").lower()
        assert by[k]["status"] == "not_done" or ("mock" not in ev and "double" not in ev)


# ============================================================================ tenant isolation of what Phase 2 added

def test_another_business_cannot_read_or_change_my_billing_usage_or_plan_data(rzp, biz_a, biz_b, admin):
    activate(biz_a, rzp, "growth")
    mine = {e["kind"] for e in biz_a.get("/billing/subscription/history").json()["events"]}
    theirs = {e["kind"] for e in biz_b.get("/billing/subscription/history").json()["events"]}
    assert "activated" in mine and theirs == {"trial_started"}
    assert biz_b.get("/billing/subscription").json()["source"] == "trial"
    for path in ("/admin/plans", "/admin/costs", "/admin/finance", "/admin/release-gates", f"/admin/tenants/{biz_a.tenant_id}/budgets"):
        assert biz_b.get(path).status_code == 403, path
    assert biz_b.put("/admin/plans/growth/limits", json={"geo": {"max_grids": 9, "max_points": 9, "monthly_points": 9}, "note": "attack"}).status_code == 403
    assert biz_b.put(f"/admin/tenants/{biz_a.tenant_id}/budgets", json={"places_monthly_cap": 0, "note": "attack"}).status_code == 403
    assert owner_query("SELECT limits->'geo'->>'monthly_points' FROM billing_plans WHERE code = 'growth'")[0][0] != "9"  # nothing changed


def test_promotional_grants_and_subscription_events_are_invisible_across_businesses(rzp):
    a, b = make_business("Promo Iso A"), make_business("Promo Iso B")
    buy_cards(a, rzp, 1)
    from sqlalchemy import text
    db = SessionLocal(); set_rls_context(db, tenant_id=uuid.UUID(b.tenant_id))
    for table in ("promotional_grants", "subscription_events", "api_usage_ledger"):
        assert db.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": a.tenant_id}).scalar() == 0, table
    db.close()
    assert b.get("/billing/subscription").json()["promo"] is None and a.get("/billing/subscription").json()["promo"] is not None


def test_one_business_cannot_use_anothers_free_month(rzp):
    a, b = make_business("Free Month A"), make_business("Free Month B")
    buy_cards(a, rzp, 1)
    from tests.test_phase2_plans import set_plan
    set_plan(b.tenant_id, "starter")
    assert "geo_ranking" not in set(b.get("/billing/subscription").json()["limits"]["features"])
    assert b.get("/agent/control-centre").status_code == 402  # B is on Launch: A's promotional Growth month does not apply to B


def test_a_card_order_of_another_business_cannot_be_verified_by_me(rzp):
    a, b = make_business("Order Iso A"), make_business("Order Iso B")
    _, oid, pay = buy_cards(a, rzp, 1)
    from tests.test_billing import KEY_SECRET, sig
    r = b.post("/billing/card-orders/verify", json={"razorpay_order_id": oid, "razorpay_payment_id": pay, "razorpay_signature": sig(KEY_SECRET, f"{oid}|{pay}")})
    assert r.status_code == 404  # B cannot touch A's order, even with a valid signature
    assert owner_query("SELECT count(*) FROM promotional_grants WHERE tenant_id = :t", t=b.tenant_id)[0][0] == 0


def test_the_public_readiness_endpoint_discloses_nothing_beyond_three_statuses(client, monkeypatch):
    """It is public on purpose (see PUBLIC_PREFIXES in test_security_audit.py), so what it may say is pinned: ready, and one status word per check. No revision, host, version or error text."""
    from app.services import ops
    redis_up(monkeypatch)
    monkeypatch.setattr(ops, "check_database", lambda db: ops.row("database", "Database", "critical", "connection to db.internal:5432 refused as flowqr_app"))
    r = client.get("/api/ready")
    assert r.status_code == 503 and set(r.json()) == {"ready", "checks"} and set(r.json()["checks"]) == {"database", "redis", "migrations"}
    assert all(v in ("ok", "warn", "critical", "unknown") for v in r.json()["checks"].values())
    assert "internal" not in r.text and "5432" not in r.text and "flowqr_app" not in r.text
