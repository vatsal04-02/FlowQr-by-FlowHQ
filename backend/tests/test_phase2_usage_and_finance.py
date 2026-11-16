"""Phase 2, milestones 2 and 8: one usage ledger, configurable prices (an unpriced call is never free), budgets, refusals on record, the cost dashboard, and honest revenue and
unit-economics figures (actual / estimated / missing).

MOCKED: Places is the FakePlaces test double, Razorpay is FakeRazorpay, the AI is a stub. The database, the ledgers, the budgets and the arithmetic are real. No figure here is
a measurement of what Google, Razorpay or Gemini really charge."""
import time
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.services import ai_usage, finance, usage
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_billing import KEY_SECRET, activate, rzp, sig, webhook  # noqa: F401
from tests.test_google_and_reviews import connected  # noqa: F401
from tests.test_phase15_geogrid import FakePlaces, env, fake, gid, new_grid, places, scan, set_geo  # noqa: F401
from tests.test_phase2_plans import SHIP, buy_cards  # noqa: F401


def rows(tenant_id, where="TRUE"):
    return owner_query(f"SELECT operation, feature, units, status, est_cost_usd, priced, idempotency_key, reason FROM api_usage_ledger WHERE tenant_id = :t AND {where} ORDER BY created_at, id", t=tenant_id)


@pytest.fixture(autouse=True)
def _prices(monkeypatch):
    monkeypatch.setattr(settings, "api_prices", {})
    monkeypatch.setattr(settings, "rank_cost_per_call_usd", 0.0)


# ============================================================================ Places usage is counted per real request

def test_a_single_rank_check_is_one_ledger_row_and_unpriced_is_never_free(env, monkeypatch):
    monkeypatch.setattr(settings, "rank_cost_per_call_usd", 0.0)  # this test is about an UNPRICED search (the shared fixture records a test price so maps can run)
    env.places.script(4)
    r = env.biz.post(f"/gbp/{env.gid}/rank/check", json={})
    assert r.status_code == 200
    got = rows(env.biz.tenant_id)
    assert [(g[0], g[1], g[2], g[3]) for g in got] == [("searchText", "rank_check", 1, "ok")]
    assert got[0][4] is None and got[0][5] is False  # no price configured: cost is NULL and priced is False, not 0


def test_a_configured_price_prices_the_call(env, monkeypatch):
    monkeypatch.setattr(settings, "api_prices", {"places.searchText": 0.032})
    env.places.script(4)
    env.biz.post(f"/gbp/{env.gid}/rank/check", json={})
    row = rows(env.biz.tenant_id)[0]
    assert row[4] == Decimal("0.032") and row[5] is True
    monkeypatch.setattr(settings, "api_prices", {})
    monkeypatch.setattr(settings, "rank_cost_per_call_usd", 0.05)  # the older single setting is still honoured for Places
    assert usage.price_for("places", "searchText") == Decimal("0.05") and usage.price_for("google_business", "locations.patch") is None


def test_a_map_scan_is_one_row_per_point_not_one_per_scan(env, monkeypatch):
    monkeypatch.setattr(settings, "api_prices", {"places.searchText": 0.01})
    g = new_grid(env)
    s = scan(env, g, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    got = rows(env.biz.tenant_id, "feature = 'rank_grid'")
    assert len(got) == 9 and sum(r[2] for r in got) == 9 and s["calls"] == 9 and all(r[3] == "ok" and r[5] for r in got)
    assert len({r[6] for r in got}) == 9 and all(r[6].startswith(f"grid:{s['id']}:") for r in got)  # each point has its own idempotency key


def test_a_retry_of_the_same_point_cannot_be_counted_twice(env):
    db = SessionLocal(); set_rls_context(db, bypass=True)
    tid = uuid.UUID(env.biz.tenant_id)
    first = usage.record(db, tenant_id=tid, provider="places", operation="searchText", feature="rank_grid", idempotency_key="grid:abc:0")
    again = usage.record(db, tenant_id=tid, provider="places", operation="searchText", feature="rank_grid", idempotency_key="grid:abc:0")
    db.commit()
    assert (first, again) == (True, False)
    assert usage.units_this_month(db, tid) == 1
    other = usage.record(db, tenant_id=uuid.uuid4(), provider="places", operation="searchText", feature="rank_grid", idempotency_key="grid:abc:0")  # the key is per business
    assert other is True
    db.rollback(); db.close()


def test_a_failed_search_is_recorded_as_an_error_and_still_counts_as_requested(env):
    from app.services.rank import RankError
    g = new_grid(env)
    env.places.errors = {2: RankError("Places is having trouble", 502)}
    scan(env, g, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    got = rows(env.biz.tenant_id, "feature = 'rank_grid'")
    assert [r[3] for r in got].count("error") == 1 and len(got) == 9
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert usage.units_this_month(db, uuid.UUID(env.biz.tenant_id)) == 9  # a failed request was still made, so it still counts toward the ceiling (and is reported as failed)
    db.close()


# ============================================================================ refusals are recorded

def test_a_refused_scan_leaves_a_refusal_row_and_spends_nothing(env):
    set_geo(env.biz.tenant_id, 2, 9, 5)  # 5 searches a month, a 9-point scan needs 9
    g = new_grid(env)
    env.places.script(1)
    r = env.biz.post(f"/gbp/{env.gid}/rank/grids/{g}/scan", json={"keyword_id": env.kid})
    assert r.status_code == 429 and env.places.calls == 0
    got = rows(env.biz.tenant_id)
    assert [(x[1], x[2], x[3], x[7]) for x in got] == [("rank_grid", 9, "refused", "plan monthly allowance")]
    assert got[0][4] is None and got[0][5] is False  # a refused call cost nothing and has no price


def test_a_business_level_ceiling_set_by_an_admin_applies_to_single_checks_and_maps_together(env, admin):
    tid = env.biz.tenant_id
    assert env.biz.put(f"/admin/tenants/{tid}/budgets", json={"places_monthly_cap": 5, "note": "x y z"}).status_code == 403  # a business owner cannot set their own ceiling
    r = admin.put(f"/admin/tenants/{tid}/budgets", json={"places_monthly_cap": 5, "note": "Pilot customer: limit Google spend"})
    assert r.status_code == 200 and r.json()["after"]["places_monthly_cap"] == 5
    g = new_grid(env)
    env.places.script(*([1] * 9))
    big = env.biz.post(f"/gbp/{env.gid}/rank/grids/{g}/scan", json={"keyword_id": env.kid})
    assert big.status_code == 429 and "limit of 5" in big.json()["detail"] and env.places.calls == 0
    for _ in range(5):
        env.places.script(3)
        assert env.biz.post(f"/gbp/{env.gid}/rank/check", json={}).status_code == 200
    env.places.script(3)
    sixth = env.biz.post(f"/gbp/{env.gid}/rank/check", json={})
    assert sixth.status_code == 429 and "limit of 5" in sixth.json()["detail"]
    assert [x[3] for x in rows(tid, "status = 'refused'")] == ["refused", "refused"]
    assert admin.get(f"/admin/tenants/{tid}/budgets").json()["places_used_this_month"] == 5
    assert owner_query("SELECT count(*) FROM audit_logs WHERE action = 'admin.budgets' AND tenant_id = :t", t=tid)[0][0] == 1
    admin.put(f"/admin/tenants/{tid}/budgets", json={"places_monthly_cap": None, "note": "Pilot over"})
    assert env.biz.get(f"/admin/tenants/{tid}/budgets").status_code == 403


# ============================================================================ AI ledger carries what a cost review needs

def test_every_ai_call_row_has_a_request_id_and_a_retry_count_and_the_actor():
    biz = make_business("Ledger Co")
    uid = owner_query("SELECT user_id FROM memberships WHERE tenant_id = :t", t=biz.tenant_id)[0][0]

    class Stub:
        name, model, usage = "stub", "m-1", None

        def generate(self, system, user, **kw):
            return "ok"

    db = SessionLocal(); set_rls_context(db, bypass=True)
    p = ai_usage.metered(Stub(), db, uuid.UUID(biz.tenant_id), "reply_draft", actor_user_id=uid)
    p.generate("s", "u"); p.generate("s", "u")  # a rewrite is a second call of the same task
    p2 = p.with_kind("review_risk"); p2.generate("s", "u")
    db.close()
    got = owner_query("SELECT kind, feature, retry_count, request_id IS NOT NULL, actor_user_id FROM ai_call_ledger WHERE tenant_id = :t ORDER BY created_at", t=biz.tenant_id)
    assert [(g[0], g[1], g[2], g[3]) for g in got] == [("reply_draft", "reply_draft", 0, True), ("reply_draft", "reply_draft", 1, True), ("review_risk", "review_risk", 0, True)]
    assert got[0][4] == uid
    assert len({r[0] for r in owner_query("SELECT request_id FROM ai_call_ledger WHERE tenant_id = :t", t=biz.tenant_id)}) == 3  # one id per call


# ============================================================================ the cost dashboard

def test_the_cost_dashboard_counts_unpriced_calls_instead_of_pricing_them_at_zero(env, admin, monkeypatch):
    monkeypatch.setattr(settings, "rank_cost_per_call_usd", 0.0)  # unpriced on purpose (the shared fixture records a test price so maps can run)
    env.places.script(2)
    env.biz.post(f"/gbp/{env.gid}/rank/check", json={})
    out = admin.get("/admin/costs", params={"top": 500}).json()
    assert out["api"]["unpriced_units"] >= 1 and out["complete"] is False and "NOT included" in out["note"]
    row = next(b for b in out["by_business"] if b["tenant_id"] == env.biz.tenant_id)
    assert row["api_units"] == 1 and row["api_usd"] == 0.0
    monkeypatch.setattr(settings, "api_prices", {"places.searchText": 0.032})
    env.places.script(2)
    env.biz.post(f"/gbp/{env.gid}/rank/check", json={})
    out2 = admin.get("/admin/costs", params={"top": 500}).json()
    row2 = next(b for b in out2["by_business"] if b["tenant_id"] == env.biz.tenant_id)
    assert row2["api_usd"] == pytest.approx(0.032, abs=1e-6) and out2["api"]["units"] >= 2
    op = next(o for o in out2["api"]["by_operation"] if o["operation"] == "searchText" and o["feature"] == "rank_check")
    assert op["units"] >= 1 and op["unpriced_units"] >= 1  # the earlier, unpriced search is still reported as unpriced


def test_the_cost_and_finance_views_are_for_platform_admins_only(env, admin, biz_a):
    for path in ("/admin/costs", "/admin/finance", "/admin/plans"):
        assert biz_a.get(path).status_code == 403 and admin.get(path).status_code == 200
    assert admin.get("/admin/costs?month=2026-13").status_code == 422 and admin.get("/admin/costs?month=banana").status_code == 422


def test_the_usage_ledger_is_tenant_isolated_and_append_only(env):
    a = env.biz.tenant_id
    env.places.script(1)
    env.biz.post(f"/gbp/{env.gid}/rank/check", json={})
    other = make_business("Isolated Usage Co")
    db = SessionLocal(); set_rls_context(db, tenant_id=uuid.UUID(other.tenant_id))
    assert db.execute(text("SELECT count(*) FROM api_usage_ledger WHERE tenant_id = :t"), {"t": a}).scalar() == 0
    db.close()
    db = SessionLocal(); set_rls_context(db, bypass=True)
    for sql in ("UPDATE api_usage_ledger SET units = 0", "DELETE FROM api_usage_ledger"):
        with pytest.raises(Exception) as exc:
            db.execute(text(sql + " WHERE tenant_id = :t"), {"t": a})
        assert "permission denied" in str(exc.value)
        db.rollback()
    db.close()


# ============================================================================ revenue: what counts as MRR, and what does not

def snapshot():
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        return finance.revenue(db)
    finally:
        db.close()


def test_only_paid_subscriptions_are_mrr_and_the_card_month_and_trials_are_not(rzp, client):
    before = snapshot()
    biz = make_business("Revenue Co")  # a trial: not revenue
    after_trial = snapshot()
    assert after_trial["mrr_paise"]["value"] == before["mrr_paise"]["value"]
    activate(biz, rzp, "growth")
    after_paid = snapshot()
    assert after_paid["mrr_paise"]["value"] - before["mrr_paise"]["value"] == 79900
    assert after_paid["arr_paise"]["value"] - before["arr_paise"]["value"] == 79900 * 12 and after_paid["arr_paise"]["status"] == "estimated"
    assert after_paid["paid_subscribers"]["value"] - before["paid_subscribers"]["value"] == 1
    buy_cards(biz, rzp, 2)  # ONE-TIME card revenue, plus a free Growth month
    after_card = snapshot()
    assert after_card["mrr_paise"]["value"] == after_paid["mrr_paise"]["value"]  # the card did not change MRR
    assert after_card["card_revenue_paise"]["value"] - after_paid["card_revenue_paise"]["value"] == 100000
    assert after_card["promotional_growth_activations"]["value"] - after_paid["promotional_growth_activations"]["value"] == 1
    assert "Never part of MRR" in after_card["card_revenue_paise"]["note"]


def test_a_comped_subscription_and_a_promo_only_business_are_not_revenue(rzp, admin):
    base = snapshot()
    biz = make_business("Comped Co")
    admin.post(f"/admin/tenants/{biz.tenant_id}/subscription", json={"plan": "pro", "status": "manual", "note": "Pilot customer, free"})
    promo = make_business("Promo Only Co")
    buy_cards(promo, rzp, 1)
    now = snapshot()
    assert now["mrr_paise"]["value"] == base["mrr_paise"]["value"]
    assert now["comped_subscriptions"]["value"] - base["comped_subscriptions"]["value"] == 1
    assert now["promotional_growth_active_now"]["value"] - base["promotional_growth_active_now"]["value"] == 1


def test_a_refund_reduces_card_revenue_and_a_cancellation_is_lost_mrr(rzp, client):
    biz = make_business("Refund Rev Co")
    _, oid, pay = buy_cards(biz, rzp, 1)
    gross = snapshot()["card_revenue_paise"]["value"]
    webhook(client, {"event": "refund.processed", "created_at": int(time.time()), "payload": {"refund": {"entity": {"id": "rfnd_rev", "payment_id": pay, "amount": 80000}}}}, event_id="ev_rev_1")
    assert snapshot()["card_revenue_paise"]["value"] == gross - 80000
    sid, _ = activate(biz, rzp, "growth")
    before = snapshot()["mrr_lost_paise"]["value"]
    assert biz.post("/billing/subscription/cancel", json={"at_cycle_end": False}).status_code == 200
    assert snapshot()["mrr_lost_paise"]["value"] - before == 79900


# ============================================================================ unit economics: nothing missing is treated as zero

def economics():
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        return finance.economics(db)
    finally:
        db.close()


def test_with_no_cost_inputs_the_margin_is_missing_and_says_what_to_provide(monkeypatch, admin):
    for k in ("usd_inr_rate", "payment_fee_pct", "card_unit_cost_inr", "card_fulfilment_per_order_inr", "hosting_monthly_inr", "support_monthly_inr", "marketing_spend_monthly_inr"):
        monkeypatch.setattr(settings, k, None)
    e = economics()["economics"]
    assert e["contribution_margin_inr"]["value"] is None and e["contribution_margin_inr"]["status"] == "missing"
    assert set(e["missing_variable_inputs"]) == {"ai_and_google_api", "payment_processing", "card_manufacturing", "card_fulfilment"}
    for k in ("customer_acquisition_cost_inr", "lifetime_value_inr", "ltv_to_cac", "cac_payback_months", "break_even_paid_businesses"):
        assert e[k]["value"] is None and e[k]["status"] == "missing", k
    assert e["cost_lines_inr"]["card_manufacturing"]["needs"].startswith("CARD_UNIT_COST_INR") and "not confirmed" in e["cost_lines_inr"]["card_manufacturing"]["needs"]
    assert admin.get("/admin/finance").json()["economics"]["contribution_margin_inr"]["value"] is None


def test_a_margin_exists_only_when_every_variable_cost_is_known(rzp, monkeypatch):
    biz = make_business("Margin Co")
    activate(biz, rzp, "growth")
    for k, v in (("usd_inr_rate", 83.0), ("payment_fee_pct", 2.0), ("card_unit_cost_inr", 75.0), ("card_fulfilment_per_order_inr", 40.0)):
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(settings, "api_prices", {"places.searchText": 0.032})
    monkeypatch.setattr(settings, "ai_price_in_per_mtok", 0.3)
    monkeypatch.setattr(settings, "ai_price_out_per_mtok", 2.5)
    e = economics()["economics"]
    assert e["missing_variable_inputs"] == [] and e["contribution_margin_inr"]["status"] == "estimated" and e["contribution_margin_inr"]["value"] is not None
    assert e["cost_lines_inr"]["card_manufacturing"]["status"] == "estimated" and "PROVISIONAL" in e["cost_lines_inr"]["card_manufacturing"]["note"]
    monkeypatch.setattr(settings, "payment_fee_pct", None)  # take one input away again
    e2 = economics()["economics"]
    assert e2["contribution_margin_inr"]["value"] is None and e2["missing_variable_inputs"] == ["payment_processing"]  # the margin disappears; it is not computed without it


def inputs(monkeypatch):
    for k, v in (("usd_inr_rate", 83.0), ("payment_fee_pct", 2.0), ("card_unit_cost_inr", 75.0), ("card_fulfilment_per_order_inr", 40.0), ("marketing_spend_monthly_inr", 10000.0),
                 ("hosting_monthly_inr", 5000.0), ("support_monthly_inr", 2000.0)):
        monkeypatch.setattr(settings, k, v)


def test_lifetime_value_is_missing_not_infinite_when_nobody_has_left(monkeypatch):
    inputs(monkeypatch)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    e = finance.economics(db, "2001-01")["economics"]  # a month in which nothing happened
    db.close()
    assert e["monthly_paid_churn"]["value"] == 0.0
    for k in ("lifetime_value_inr", "ltv_to_cac", "cac_payback_months"):
        assert e[k]["value"] is None and e[k]["status"] == "missing" and "churn" in e[k]["note"].lower(), k


def test_lifetime_value_is_finite_and_labelled_an_estimate_once_churn_is_observed(rzp, monkeypatch):
    import math
    inputs(monkeypatch)
    monkeypatch.setattr(settings, "api_prices", {"places.searchText": 0.032})
    biz = make_business("Churn Co")
    activate(biz, rzp, "growth")
    assert biz.post("/billing/subscription/cancel", json={"at_cycle_end": False}).status_code == 200  # one paid subscription lost this month
    other = make_business("Stays Co")
    activate(other, rzp, "growth")
    e = economics()["economics"]
    assert (e["monthly_paid_churn"]["value"] or 0) > 0
    ltv = e["lifetime_value_inr"]
    if e["contribution_margin_pct"]["value"] is not None and e["contribution_margin_pct"]["value"] > 0:
        assert ltv["status"] == "estimated" and math.isfinite(ltv["value"]) and ltv["value"] > 0 and "thin basis" in ltv["note"]
        assert e["customer_acquisition_cost_inr"]["status"] in ("estimated", "missing")
    else:
        assert ltv["value"] is None and ltv["status"] == "missing"  # a zero or negative margin has no lifetime value either


def test_a_free_business_costs_something_and_is_counted_in_the_per_business_cost(monkeypatch):
    monkeypatch.setattr(settings, "usd_inr_rate", 83.0)
    monkeypatch.setattr(settings, "api_prices", {"places.searchText": 0.032})
    e = economics()["economics"]
    assert e["variable_ai_api_cost_per_business_inr"]["status"] == "estimated" and "free ones cost too" in e["variable_ai_api_cost_per_business_inr"]["note"]
