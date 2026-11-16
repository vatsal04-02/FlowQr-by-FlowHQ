"""Phase 2, milestone 1: the commercial plans, the separate review-generation and reply allowances, plan gating of every paid area, subscription history,
promotional access from a card purchase, refunds, and the map allowances that stay OFF until the owner approves them.

MOCKED: Razorpay is a TEST DOUBLE (FakeRazorpay, real HMAC signatures) and the AI is a stub. The database, the plan rows, the migrations, the entitlement engine and the
state machines are real. Nothing here shows how Razorpay or Google really behave."""
import json
import time
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.models import PromotionalGrant, Subscription, SubscriptionEvent
from app.models.base import utcnow
from app.services import billing as billing_svc
from app.services import entitlements as ent
from app.services import plans
from app.services.ai_usage import log_generation, quota_exceeded, usage_this_month
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_billing import KEY_SECRET, activate, db_sub, rzp, sig, webhook  # noqa: F401
from tests.test_gbp import fake, gid  # noqa: F401
from tests.test_google_and_reviews import StubReplyAI, connected  # noqa: F401
from tests.test_location_permissions import invite

SHIP = {"name": "Dr Geeta", "phone": "9876543210", "address_line": "12 Hazratganj", "city": "Lucknow", "state": "Uttar Pradesh", "postal_code": "226001"}


def set_plan(tenant_id, code):
    """Put a business on a plan the way a subscription does: the plan's allowances and features are copied onto its subscription."""
    db, sub = db_sub(tenant_id)
    from app.models import BillingPlan
    billing_svc.apply_plan(sub, db.get(BillingPlan, code))
    sub.status, sub.source = "active", "manual"
    db.commit()
    db.close()


def generation(tenant_id, kind, status="ok"):
    db = SessionLocal(); set_rls_context(db, bypass=True)
    log_generation(db, tenant_id=uuid.UUID(tenant_id), kind=kind, provider="stub", model="m", language="en", input_chars=1, output_chars=1, status=status, started=time.monotonic())
    db.commit(); db.close()


def exceeded(tenant_id, kind):
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        return quota_exceeded(db, uuid.UUID(tenant_id), kind)
    finally:
        db.close()


def buy_cards(biz, rzp_, qty):
    r = biz.post("/billing/card-orders", json={"quantity": qty, "shipping": SHIP})
    assert r.status_code == 201, r.text
    oid, pay = r.json()["order_id"], f"pay_{uuid.uuid4().hex[:10]}"
    rzp_.orders[oid].update(status="paid", amount_paid=rzp_.orders[oid]["amount"])
    ok = biz.post("/billing/card-orders/verify", json={"razorpay_order_id": oid, "razorpay_payment_id": pay, "razorpay_signature": sig(KEY_SECRET, f"{oid}|{pay}")})
    assert ok.status_code == 200 and ok.json()["status"] == "paid", ok.text
    return r.json(), oid, pay


def grants(tenant_id):
    return owner_query("SELECT status, plan, ends_at - starts_at FROM promotional_grants WHERE tenant_id = :t ORDER BY created_at", t=tenant_id)


def kinds(tenant_id):
    return [k for (k,) in owner_query("SELECT kind FROM subscription_events WHERE tenant_id = :t ORDER BY created_at, id", t=tenant_id)]


# ============================================================================ the catalogue

def test_the_seeded_plans_are_exactly_the_confirmed_commercial_plans(client):
    r = client.get("/api/v1/billing/plans").json()
    assert [(p["code"], p["name"], p["price_paise"]) for p in r["plans"]] == [("starter", "Starter", 49900), ("growth", "Growth", 79900), ("pro", "Pro", 149900)]
    for p in r["plans"]:
        spec = plans.PLANS[p["code"]]
        assert (p["review_generations"], p["review_replies"]) == (spec["review_generations"], spec["review_replies"]) and set(p["features"]) == set(spec["features"])
    assert {c: (g, rp) for c, g, rp in ((p["code"], p["review_generations"], p["review_replies"]) for p in r["plans"])} == {"starter": (200, 200), "growth": (400, 400), "pro": (800, 800)}
    # the database matches the specification module (the two cannot drift apart)
    for code, spec in plans.PLANS.items():
        row = owner_query("SELECT price_paise, max_locations, max_staff, review_generations, review_replies, monthly_ai_generations FROM billing_plans WHERE code = :c", c=code)[0]
        assert row == (spec["price_paise"], spec["max_locations"], spec["max_staff"], spec["review_generations"], spec["review_replies"], spec["monthly_ai_generations"])


def test_retired_plans_are_kept_for_existing_subscribers_and_never_offered(client):
    assert owner_query("SELECT code, is_active FROM billing_plans WHERE code IN ('essential', 'multi') ORDER BY code") == [("essential", False), ("multi", False)]
    assert {p["code"] for p in client.get("/api/v1/billing/plans").json()["plans"]} == {"starter", "growth", "pro"}


@pytest.mark.parametrize("code,has,lacks", [
    ("starter", ("review_sync", "ai_replies", "review_generation", "qr_campaigns", "review_analytics", "gbp_connection", "gbp_info"),
     ("local_seo", "keyword_tracking", "geo_ranking", "autonomy", "ai_posts", "gbp_posts", "profile_optimizer", "growth_agent", "multi_location")),
    ("growth", plans.CORE + plans.GROWTH_ADD, ("multi_location",)),
    ("pro", plans.ALL_FEATURES, ()),
])
def test_each_plan_includes_exactly_what_the_commercial_table_says(code, has, lacks):
    f = set(owner_query("SELECT features FROM billing_plans WHERE code = :c", c=code)[0][0])
    assert set(has) <= f and not (set(lacks) & f)


def test_growth_includes_one_location_and_pro_ten():
    biz = make_business("Plan Cap Co", location_cap=None)  # the plan's real cap, not the test helper's
    assert owner_query("SELECT max_locations FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 1
    r = biz.post("/locations", json={"name": "Second branch"})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_limit"
    set_plan(biz.tenant_id, "pro")
    assert biz.post("/locations", json={"name": "Second branch"}).status_code == 201


def test_map_allowances_ship_unconfigured_on_every_plan():
    for code in ("starter", "growth", "pro"):
        lim = owner_query("SELECT limits FROM billing_plans WHERE code = :c", c=code)[0][0]
        assert plans.geo_limits(lim) is None and plans.pending_limits(lim) == ["limits.geo.max_grids", "limits.geo.max_points", "limits.geo.monthly_points"]
    assert plans.geo_limits({"geo": {"max_grids": 2, "max_points": 9, "monthly_points": None}}) is None  # half-configured is unconfigured
    assert plans.geo_limits({"geo": {"max_grids": 2, "max_points": 9, "monthly_points": 0}}) is None
    assert plans.geo_limits({"geo": {"max_grids": 2, "max_points": 9, "monthly_points": True}}) is None
    assert plans.geo_limits({"geo": {"max_grids": 2, "max_points": 9, "monthly_points": 5}}) == {"max_grids": 2, "max_points": 9, "monthly_points": 5}


# ============================================================================ separate allowances

def test_review_generations_and_replies_are_separate_allowances_not_a_shared_pool():
    biz = make_business("Quota Co")
    owner_exec("UPDATE subscriptions SET review_generations = 2, review_replies = 3 WHERE tenant_id = :t", t=biz.tenant_id)  # 5 operations in total
    generation(biz.tenant_id, "review_assist"); generation(biz.tenant_id, "review_generate")
    assert exceeded(biz.tenant_id, "review_assist") and exceeded(biz.tenant_id, "review_generate")  # generations used up...
    assert not exceeded(biz.tenant_id, "reply_draft")  # ...replies are untouched
    for _ in range(3):
        generation(biz.tenant_id, "reply_draft")
    assert exceeded(biz.tenant_id, "reply_draft")
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert (usage_this_month(db, uuid.UUID(biz.tenant_id), "review_generations"), usage_this_month(db, uuid.UUID(biz.tenant_id), "review_replies"), usage_this_month(db, uuid.UUID(biz.tenant_id))) == (2, 3, 5)
    db.close()


def test_a_reply_does_not_use_a_review_generation_and_the_other_way_round():
    biz = make_business("Quota Co 2")
    owner_exec("UPDATE subscriptions SET review_generations = 1, review_replies = 1 WHERE tenant_id = :t", t=biz.tenant_id)
    generation(biz.tenant_id, "reply_draft")
    assert exceeded(biz.tenant_id, "reply_draft") and not exceeded(biz.tenant_id, "review_assist")
    generation(biz.tenant_id, "review_assist")
    assert exceeded(biz.tenant_id, "review_assist")


def test_other_ai_work_draws_on_neither_allowance():
    biz = make_business("Quota Co 3")
    owner_exec("UPDATE subscriptions SET review_generations = 1, review_replies = 1 WHERE tenant_id = :t", t=biz.tenant_id)
    for k in ("post_draft", "post_ideas", "agent_draft", "description", "review_risk", "review_test"):
        generation(biz.tenant_id, k)
    assert not exceeded(biz.tenant_id, "reply_draft") and not exceeded(biz.tenant_id, "review_assist")
    assert not exceeded(biz.tenant_id, "post_draft")  # no per-plan count: limited by the plan feature and the USD budgets instead


def test_a_failed_generation_does_not_use_the_customers_allowance():
    biz = make_business("Quota Co 4")
    owner_exec("UPDATE subscriptions SET review_replies = 1 WHERE tenant_id = :t", t=biz.tenant_id)
    generation(biz.tenant_id, "reply_draft", status="error")
    assert not exceeded(biz.tenant_id, "reply_draft")
    generation(biz.tenant_id, "reply_draft")
    assert exceeded(biz.tenant_id, "reply_draft")


def test_an_inactive_subscription_stops_every_kind():
    biz = make_business("Quota Co 5")
    owner_exec("UPDATE subscriptions SET status = 'expired' WHERE tenant_id = :t", t=biz.tenant_id)
    assert all(exceeded(biz.tenant_id, k) for k in ("reply_draft", "review_assist", "post_draft", "agent_draft", None))


def test_the_allowance_resets_each_calendar_month():
    biz = make_business("Quota Co 6")
    owner_exec("UPDATE subscriptions SET review_replies = 1 WHERE tenant_id = :t", t=biz.tenant_id)
    generation(biz.tenant_id, "reply_draft")
    assert exceeded(biz.tenant_id, "reply_draft")
    owner_exec("UPDATE ai_generation_logs SET created_at = now() - interval '40 days' WHERE tenant_id = :t", t=biz.tenant_id)
    assert not exceeded(biz.tenant_id, "reply_draft")


def test_the_reply_endpoint_enforces_the_reply_allowance_on_the_backend(connected, fake, gid, monkeypatch):  # noqa: F811
    from tests.test_agent import add_review
    monkeypatch.setattr("app.api.v1.reviews.get_provider", lambda: StubReplyAI())
    owner_exec("UPDATE subscriptions SET review_replies = 1, review_generations = 5 WHERE tenant_id = :t", t=connected.tenant_id)
    r1, r2 = add_review(connected, gid), add_review(connected, gid)
    first = connected.post(f"/reviews/{r1}/drafts/generate")
    assert first.status_code in (200, 201), first.text
    second = connected.post(f"/reviews/{r2}/drafts/generate")
    assert second.status_code == 402 and second.json()["detail"]["code"] == "reply_quota_reached" and "yourself" in second.json()["detail"]["message"]
    s = connected.get("/billing/subscription").json()
    assert (s["limits"]["review_generations"], s["limits"]["review_replies"], s["usage"]["review_replies"], s["usage"]["review_generations"]) == (5, 1, 1, 0)


# ============================================================================ plan gating

def routes_for(gid_):
    return [("get", f"/gbp/{gid_}/rank", "keyword_tracking"), ("get", f"/gbp/{gid_}/rank/grids", "geo_ranking"), ("get", "/agent/control-centre", "autonomy"),
            ("get", "/agent/autonomy-settings", "autonomy"), ("get", "/agent/health", "growth_agent"), ("get", "/agent/tasks", "growth_agent"),
            ("post", "/agent/plan/run", "growth_agent"), ("get", f"/agent/profile/{gid_}/optimize", "profile_optimizer"), ("get", f"/gbp/{gid_}/posts", "gbp_posts"),
            ("get", f"/gbp/{gid_}/performance?from=2025-01-01&to=2025-01-31", "gbp_performance")]


def test_a_starter_business_cannot_reach_any_growth_feature_through_the_api(connected, fake, gid):  # noqa: F811
    set_plan(connected.tenant_id, "starter")
    for method, path, feature in routes_for(gid):
        r = getattr(connected, method)(path)
        assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_upgrade_required" and r.json()["detail"]["feature"] == feature, (path, r.status_code, r.text[:200])
        assert plans.FEATURE_LABELS[feature] in r.json()["detail"]["message"]  # names what to upgrade for, not "this feature"
    assert connected.put("/agent/autonomy-settings", json={"enabled": True}).status_code == 402  # cannot be switched on
    assert connected.put("/agent/autonomy-settings", json={"enabled": False}).status_code == 200  # switching off always works
    assert connected.post("/agent/autonomy-settings/stop").status_code == 200  # the owner's emergency stop never needs a feature
    assert connected.get("/reviews").status_code == 200 and connected.get(f"/gbp/{gid}/info").status_code == 200  # what Starter includes still works


def test_a_growth_business_reaches_them_and_pro_adds_only_multi_location(connected, fake, gid):  # noqa: F811
    set_plan(connected.tenant_id, "growth")
    for method, path, feature in routes_for(gid):
        assert getattr(connected, method)(path).status_code != 402, path
    assert "multi_location" not in set(owner_query("SELECT features FROM subscriptions WHERE tenant_id = :t", t=connected.tenant_id)[0][0])


def test_the_background_jobs_honour_the_plan_features(connected, fake, gid, monkeypatch):  # noqa: F811
    from app.workers import tasks
    def autonomy_on():
        from app.services.agent import executor
        db = SessionLocal(); set_rls_context(db, bypass=True)
        executor.get_settings(db, uuid.UUID(connected.tenant_id)).autonomy_enabled = True
        db.commit(); db.close()

    set_plan(connected.tenant_id, "starter")
    autonomy_on()
    assert owner_query("SELECT autonomy_enabled FROM agent_settings WHERE tenant_id = :t", t=connected.tenant_id) == [(True,)]  # the switch really is on, so only the plan can stop it
    seen = []
    monkeypatch.setattr("app.services.agent.seo_engine.scan_tenant", lambda db, t, **k: seen.append(t.id) or {"locations": 0, "proposed": 0, "skipped": []})
    tasks.autonomy_scan.run()
    assert connected.tenant_id not in {str(x) for x in seen}  # Starter is never scanned for autonomous maintenance
    set_plan(connected.tenant_id, "growth")
    tasks.autonomy_scan.run()
    assert connected.tenant_id in {str(x) for x in seen}


# ============================================================================ downgrade and cancellation never delete data

def test_downgrading_removes_access_not_data(connected, fake, gid):  # noqa: F811
    from tests.test_agent import add_review
    add_review(connected, gid)
    from app.models import ScheduledPost
    db = SessionLocal(); set_rls_context(db, bypass=True)
    db.add(ScheduledPost(tenant_id=uuid.UUID(connected.tenant_id), google_location_id=uuid.UUID(gid), summary="A post written while on Growth", status="draft"))
    db.commit(); db.close()
    before = {t: owner_query(f"SELECT count(*) FROM {t} WHERE tenant_id = :t", t=connected.tenant_id)[0][0] for t in ("reviews", "scheduled_posts", "google_locations", "locations")}
    set_plan(connected.tenant_id, "starter")
    assert connected.get(f"/gbp/{gid}/posts").status_code == 402  # the feature is off...
    after = {t: owner_query(f"SELECT count(*) FROM {t} WHERE tenant_id = :t", t=connected.tenant_id)[0][0] for t in before}
    assert after == before and after["scheduled_posts"] == 1  # ...and nothing was deleted
    set_plan(connected.tenant_id, "growth")
    assert connected.get(f"/gbp/{gid}/posts").status_code == 200  # upgrading again brings everything back


def test_an_expired_or_cancelled_business_keeps_its_data_and_can_still_read(rzp, connected, fake, gid):  # noqa: F811
    owner_exec("UPDATE subscriptions SET status = 'canceled', current_period_end = now() - interval '1 day' WHERE tenant_id = :t", t=connected.tenant_id)
    assert connected.get("/billing/subscription").json()["active"] is False
    assert connected.get("/locations").status_code == 200  # read access is kept
    assert owner_query("SELECT count(*) FROM google_locations WHERE tenant_id = :t", t=connected.tenant_id)[0][0] >= 1
    assert connected.post("/billing/subscription/checkout", json={"plan": "growth"}).status_code == 200  # and they can pay to come back


# ============================================================================ subscription history

def test_every_change_of_a_subscription_leaves_a_history_row(rzp, client):
    biz = make_business("History Co")
    assert kinds(biz.tenant_id) == ["trial_started"]
    sid, _ = activate(biz, rzp, "growth")
    assert kinds(biz.tenant_id)[-1] == "activated"
    webhook(client, {"event": "subscription.pending", "created_at": int(time.time()) + 5, "payload": {"subscription": {"entity": {"id": sid, "status": "pending"}}}}, event_id="ev_h1")
    assert kinds(biz.tenant_id)[-1] == "past_due"
    assert biz.post("/billing/subscription/cancel", json={"at_cycle_end": True}).status_code == 200
    assert kinds(biz.tenant_id)[-1] == "cancel_requested"
    rows = biz.get("/billing/subscription/history").json()["events"]
    assert [r["kind"] for r in rows][-1] == "trial_started" and rows[0]["kind"] == "cancel_requested" and rows[0]["source"] == "user"
    a = next(r for r in rows if r["kind"] == "activated")
    assert (a["from_status"], a["to_status"], a["to_plan"]) == ("trialing", "active", "growth")


def test_a_plan_change_and_an_admin_override_are_recorded_with_who_and_why(rzp, admin):
    biz = make_business("History Co 2")
    activate(biz, rzp, "starter")
    assert biz.post("/billing/subscription/change-plan", json={"plan": "pro"}).status_code == 200
    assert "plan_changed" in kinds(biz.tenant_id)
    admin.post(f"/admin/tenants/{biz.tenant_id}/subscription", json={"plan": "growth", "note": "Goodwill downgrade"})
    row = owner_query("SELECT source, from_plan, to_plan, metadata->>'note' FROM subscription_events WHERE tenant_id = :t AND kind = 'admin_override'", t=biz.tenant_id)[0]
    assert row == ("admin", "pro", "growth", "Goodwill downgrade")


def test_the_history_is_for_owners_and_admins_only_and_never_crosses_businesses(rzp):
    a, b = make_business("History A"), make_business("History B")
    assert invite(a, "staff").get("/billing/subscription/history").status_code == 403
    mine = {r["kind"] for r in a.get("/billing/subscription/history").json()["events"]}
    db = SessionLocal(); set_rls_context(db, tenant_id=uuid.UUID(b.tenant_id))
    assert db.execute(text("SELECT count(*) FROM subscription_events WHERE tenant_id = :t"), {"t": a.tenant_id}).scalar() == 0  # row-level security
    db.close()
    assert mine == {"trial_started"}


def test_the_history_cannot_be_edited_or_deleted_by_the_application():
    biz = make_business("History Co 3")
    db = SessionLocal(); set_rls_context(db, bypass=True)
    for sql in ("UPDATE subscription_events SET kind = 'x'", "DELETE FROM subscription_events"):
        with pytest.raises(Exception) as exc:
            db.execute(text(sql + " WHERE tenant_id = :t"), {"t": biz.tenant_id})
        assert "permission denied" in str(exc.value)
        db.rollback()
    db.close()


# ============================================================================ card bundles and the promotional Growth month

def test_the_card_offers_are_priced_as_bundles_and_are_one_time_revenue(rzp, biz_a):
    one, two = biz_a.post("/billing/card-orders", json={"quantity": 1, "shipping": SHIP}), biz_a.post("/billing/card-orders", json={"quantity": 2, "shipping": SHIP})
    assert (one.json()["amount_paise"], two.json()["amount_paise"]) == (80000, 100000)  # not 2 x 800
    assert owner_query("SELECT offer_code, unit_price_paise FROM card_orders WHERE tenant_id = :t ORDER BY quantity", t=biz_a.tenant_id) == [("one", 80000), ("two", 50000)]
    assert biz_a.post("/billing/card-orders", json={"quantity": 3, "shipping": SHIP}).status_code == 422
    plans_out = biz_a.get("/billing/plans").json()
    assert [(o["quantity"], o["price_paise"]) for o in plans_out["card_offers"]] == [(1, 80000), (2, 100000)] and "one-time" in plans_out["card_offer_note"]


def test_a_paid_card_order_grants_one_promotional_growth_month_and_it_is_not_a_subscription(rzp):
    biz = make_business("Card Buyer")
    activate(biz, rzp, "starter")
    assert "multi_location" not in ent_features(biz) and "geo_ranking" not in ent_features(biz)
    buy_cards(biz, rzp, 1)
    assert grants(biz.tenant_id) == [("active", "growth", timedelta(days=30))]
    s = biz.get("/billing/subscription").json()
    assert s["plan"] == "starter" and s["source"] == "razorpay" and s["promo"]["plan"] == "growth" and "nothing is charged" in s["promo"]["note"]  # the subscription row is untouched
    assert {"geo_ranking", "growth_agent", "autonomy", "gbp_posts"} <= set(s["limits"]["features"])  # the month gives Growth's features
    assert s["limits"]["review_generations"] == 400 and s["limits"]["review_replies"] == 400
    assert owner_query("SELECT plan, status, source FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id) == [("starter", "active", "razorpay")]
    assert kinds(biz.tenant_id)[-1] == "promo_granted"


def ent_features(biz):
    return set(biz.get("/billing/subscription").json()["limits"]["features"])


def test_the_promotional_month_works_for_a_business_with_no_subscription_and_ends_on_its_own(rzp):
    biz = make_business("Card Buyer 2")
    owner_exec("UPDATE subscriptions SET status = 'expired', trial_ends_at = now() - interval '1 day' WHERE tenant_id = :t", t=biz.tenant_id)
    assert biz.get("/billing/subscription").json()["active"] is False
    buy_cards(biz, rzp, 2)
    s = biz.get("/billing/subscription").json()
    assert s["active"] is True and s["promo"] and s["source"] == "trial"
    owner_exec("UPDATE promotional_grants SET ends_at = now() - interval '1 minute' WHERE tenant_id = :t", t=biz.tenant_id)
    s = biz.get("/billing/subscription").json()
    assert s["active"] is False and s["promo"] is None  # it simply stops applying; nothing was charged and nothing was deleted
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert billing_svc.end_expired_grants(db) == 1
    db.commit(); db.close()
    assert grants(biz.tenant_id)[0][0] == "ended" and kinds(biz.tenant_id)[-1] == "promo_ended"
    assert owner_query("SELECT count(*) FROM payments WHERE tenant_id = :t AND kind = 'subscription'", t=biz.tenant_id)[0][0] == 0


def test_the_same_card_payment_arriving_twice_grants_once(rzp, client):
    biz = make_business("Card Buyer 3")
    _, oid, pay = buy_cards(biz, rzp, 1)
    ev = {"event": "payment.captured", "created_at": int(time.time()), "payload": {"payment": {"entity": {"id": pay, "amount": 80000, "currency": "INR", "status": "captured", "order_id": oid}}}}
    assert webhook(client, ev, event_id="ev_dup_1").status_code == 200
    assert webhook(client, ev, event_id="ev_dup_2").status_code == 200  # a different delivery of the same payment
    biz.post("/billing/card-orders/verify", json={"razorpay_order_id": oid, "razorpay_payment_id": pay, "razorpay_signature": sig(KEY_SECRET, f"{oid}|{pay}")})
    assert len(grants(biz.tenant_id)) == 1


def test_a_second_card_order_does_not_earn_a_second_free_month_unless_the_owner_allows_it(rzp, monkeypatch):
    biz = make_business("Card Buyer 4")
    buy_cards(biz, rzp, 1)
    buy_cards(biz, rzp, 2)
    assert len(grants(biz.tenant_id)) == 1 and "promo_denied" in kinds(biz.tenant_id)
    monkeypatch.setattr(settings, "promo_max_grants_per_business", 2)
    buy_cards(biz, rzp, 1)
    assert len(grants(biz.tenant_id)) == 2


def test_choosing_a_plan_during_the_free_month_does_not_charge_until_it_ends(rzp):
    biz = make_business("Card Buyer 5")
    buy_cards(biz, rzp, 1)
    ends = owner_query("SELECT ends_at FROM promotional_grants WHERE tenant_id = :t", t=biz.tenant_id)[0][0]
    assert biz.post("/billing/subscription/checkout", json={"plan": "starter"}).status_code == 200  # the customer's own, explicit choice
    start_at = next(c[2] for c in rzp.calls if c[0] == "create_subscription")
    assert abs(start_at - int(ends.timestamp())) < 5  # the first charge is the day the free month ends, not today
    assert owner_query("SELECT count(*) FROM payments WHERE tenant_id = :t AND kind = 'subscription'", t=biz.tenant_id)[0][0] == 0


def test_a_refunded_card_order_ends_the_promotional_month_and_never_touches_data(rzp, client):
    biz = make_business("Card Buyer 6")
    _, oid, pay = buy_cards(biz, rzp, 1)
    assert biz.get("/billing/subscription").json()["promo"]
    ref = {"event": "refund.processed", "created_at": int(time.time()), "payload": {"refund": {"entity": {"id": "rfnd_1", "payment_id": pay, "amount": 80000}}, "payment": {"entity": {"id": pay}}}}
    assert webhook(client, ref, event_id="ev_ref_1").status_code == 200
    assert webhook(client, ref, event_id="ev_ref_2").status_code == 200  # redelivery changes nothing
    assert owner_query("SELECT status FROM payments WHERE razorpay_payment_id = :p", p=pay)[0][0] == "refunded"
    assert owner_query("SELECT status FROM card_orders WHERE razorpay_order_id = :o", o=oid)[0][0] == "refunded"
    assert grants(biz.tenant_id)[0][0] == "revoked" and biz.get("/billing/subscription").json()["promo"] is None
    assert kinds(biz.tenant_id).count("refunded") == 1 and "promo_revoked" in kinds(biz.tenant_id)  # the same refund delivered twice is one history row
    assert owner_query("SELECT count(*) FROM locations WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 1


def test_a_partial_refund_is_recorded_without_cancelling_anything(rzp, client):
    biz = make_business("Card Buyer 7")
    _, oid, pay = buy_cards(biz, rzp, 1)
    ref = {"event": "refund.processed", "created_at": int(time.time()), "payload": {"refund": {"entity": {"id": "rfnd_p", "payment_id": pay, "amount": 20000}}}}
    webhook(client, ref, event_id="ev_ref_p")
    assert owner_query("SELECT status FROM payments WHERE razorpay_payment_id = :p", p=pay)[0][0] == "captured"
    assert grants(biz.tenant_id)[0][0] == "active"


def test_refunding_a_subscription_payment_never_cancels_or_downgrades_by_itself(rzp, client):
    biz = make_business("Refund Co")
    sid, _ = activate(biz, rzp, "growth")
    webhook(client, {"event": "subscription.charged", "created_at": int(time.time()), "payload": {"subscription": {"entity": {"id": sid, "status": "active", "plan_id": rzp.subs[sid]["plan_id"]}},
            "payment": {"entity": {"id": "pay_sub_ref", "amount": 79900, "status": "captured"}}}}, event_id="ev_sc_1")
    webhook(client, {"event": "refund.processed", "created_at": int(time.time()), "payload": {"refund": {"entity": {"id": "rfnd_s", "payment_id": "pay_sub_ref", "amount": 79900}}}}, event_id="ev_sc_2")
    assert owner_query("SELECT status FROM payments WHERE razorpay_payment_id = 'pay_sub_ref'")[0][0] == "refunded"
    assert owner_query("SELECT status, plan FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id) == [("active", "growth")]  # a person decides what a refund means for access
    assert "refunded" in kinds(biz.tenant_id)


def test_a_tampered_webhook_changes_nothing(rzp, client):
    biz = make_business("Tamper Co")
    _, oid, pay = buy_cards(biz, rzp, 1)
    n = len(kinds(biz.tenant_id))
    ev = {"event": "refund.processed", "created_at": int(time.time()), "payload": {"refund": {"entity": {"id": "rfnd_t", "payment_id": pay, "amount": 80000}}}}
    assert webhook(client, ev, event_id="ev_t1", secret="wrong-secret").status_code in (400, 401, 403)
    assert len(kinds(biz.tenant_id)) == n and owner_query("SELECT status FROM payments WHERE razorpay_payment_id = :p", p=pay)[0][0] == "captured"


# ============================================================================ map allowances: off until approved, set by a platform admin

def test_maps_stay_off_on_a_plan_that_includes_them_until_the_owner_approves_the_numbers(connected, fake, gid, monkeypatch):  # noqa: F811
    # the platform guards are satisfied here (TEST values): this test is about the per-plan allowances, which still fail closed
    monkeypatch.setattr(settings, "rank_grid_enabled", True)
    monkeypatch.setattr(settings, "rank_platform_daily_cap", 100000)
    monkeypatch.setattr(settings, "rank_cost_per_call_usd", 0.001)
    owner_exec("UPDATE subscriptions SET limits = '{}'::jsonb WHERE tenant_id = :t", t=connected.tenant_id)
    ov = connected.get(f"/gbp/{gid}/rank/grids").json()
    assert ov["allowance"]["enabled"] is False and ov["allowance"]["reason"] == "not_configured"
    r = connected.post(f"/gbp/{gid}/rank/grids", json={"name": "Main map", "mode": "square", "size": 3, "spacing_m": 1000})
    assert r.status_code == 402 and "not been set yet" in r.json()["detail"]
    owner_exec("UPDATE subscriptions SET features = (features - 'geo_ranking') WHERE tenant_id = :t", t=connected.tenant_id)
    assert connected.get(f"/gbp/{gid}/rank/grids").status_code == 402  # not in the plan at all: a different answer


def test_an_admin_sets_and_reviews_the_plan_limits_and_sees_what_is_still_pending(admin, biz_a):
    r = admin.get("/admin/plans").json()
    g = next(p for p in r["plans"] if p["code"] == "growth")
    assert g["pending_owner_configuration"] == ["limits.geo.max_grids", "limits.geo.max_points", "limits.geo.monthly_points"] and g["price_paise"] == 79900
    assert any("Growth includes one location" in a for a in r["assumptions"])
    assert biz_a.get("/admin/plans").status_code == 403  # a business owner is not a platform admin
    bad = admin.put("/admin/plans/growth/limits", json={"geo": {"max_grids": 3, "max_points": 25}, "note": "partial"})
    assert bad.status_code == 422  # all three, or none
    ok = admin.put("/admin/plans/growth/limits", json={"geo": {"max_grids": 3, "max_points": 25, "monthly_points": 400}, "apply_to_existing": True, "note": "Approved by the owner on 2026-11-15"})
    assert ok.status_code == 200 and ok.json()["pending_owner_configuration"] == []
    assert owner_query("SELECT limits->'geo'->>'monthly_points' FROM subscriptions WHERE tenant_id = :t", t=biz_a.tenant_id)[0][0] == "400"  # existing Growth-feature subscribers get it
    log = owner_query("SELECT metadata->>'note' FROM audit_logs WHERE action = 'admin.plan_limits' ORDER BY created_at DESC LIMIT 1")
    assert log == [("Approved by the owner on 2026-11-15",)]
    admin.put("/admin/plans/growth/limits", json={"geo": {"max_grids": None, "max_points": None, "monthly_points": None}, "apply_to_existing": True, "note": "reset for tests"})
