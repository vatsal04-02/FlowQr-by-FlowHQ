"""Geo-grid spend controls (Phase 2, section E): maps are OFF until the owner's platform decisions are explicitly set, and every one of them can switch maps off again.

The numbers used here are TEST values, not real prices or limits."""
from app.core.config import settings
from app.core.db import system_session
from app.services import ops
from app.services import rank_grid as rg
from tests.test_phase15_geogrid import env, new_grid, places, scan  # noqa: F401
from tests.test_google_and_reviews import connected, fake, sync_select  # noqa: F401
from tests.test_google_business_agent import gid  # noqa: F401


def allowance(env):
    return env.biz.get(f"/gbp/{env.gid}/rank/grids").json()["allowance"]


def test_the_shipped_defaults_keep_maps_off():
    fresh = type(settings)(_env_file=None)
    assert fresh.rank_grid_enabled is False and fresh.rank_platform_daily_cap == 0 and fresh.rank_cost_per_call_usd == 0.0
    assert rg.platform_guard() == "switched_off"  # with the shipped defaults, maps cannot run


def test_the_master_switch_alone_overrides_a_plan_that_allows_maps(env, monkeypatch):
    assert allowance(env)["enabled"] is True
    monkeypatch.setattr(settings, "rank_grid_enabled", False)
    a = allowance(env)
    assert a["enabled"] is False and a["reason"] == "switched_off"
    r = env.biz.post(f"/gbp/{env.gid}/rank/grids", json={"name": "Nope", "mode": "square", "size": 3, "spacing_m": 1000})
    assert r.status_code == 402 and "switched off" in r.text
    assert env.places.calls == 0


def test_an_existing_grid_cannot_be_scanned_once_the_switch_is_off_and_no_search_is_spent(env, monkeypatch):
    grid = new_grid(env)
    monkeypatch.setattr(settings, "rank_grid_enabled", False)
    before = env.places.calls
    r = env.biz.post(f"/gbp/{env.gid}/rank/grids/{grid}/scan", json={"keyword_id": env.kid})
    assert r.status_code == 402 and env.places.calls == before


def test_maps_stay_off_without_a_platform_spending_cap(env, monkeypatch):
    monkeypatch.setattr(settings, "rank_platform_daily_cap", 0)
    monkeypatch.setattr(settings, "rank_platform_monthly_cap", 0)
    a = allowance(env)
    assert a["enabled"] is False and a["reason"] == "caps_missing"
    assert env.biz.post(f"/gbp/{env.gid}/rank/grids", json={"name": "Nope", "mode": "square", "size": 3, "spacing_m": 1000}).status_code == 402


def test_maps_stay_off_until_the_price_of_a_search_is_recorded(env, monkeypatch):
    monkeypatch.setattr(settings, "rank_cost_per_call_usd", 0.0)
    a = allowance(env)
    assert a["enabled"] is False and a["reason"] == "unpriced"


def test_a_monthly_cap_alone_satisfies_the_guard(env, monkeypatch):
    monkeypatch.setattr(settings, "rank_platform_daily_cap", 0)
    monkeypatch.setattr(settings, "rank_platform_monthly_cap", 1000)
    assert allowance(env)["enabled"] is True


def test_the_platform_daily_cap_refuses_a_scan_that_does_not_fit_and_spends_nothing(env, monkeypatch):
    grid = new_grid(env)  # 9 points
    monkeypatch.setattr(settings, "rank_platform_daily_cap", 5)
    assert allowance(env)["remaining"] == 5 and allowance(env)["daily_remaining"] == 5
    before = env.places.calls
    r = env.biz.post(f"/gbp/{env.gid}/rank/grids/{grid}/scan", json={"keyword_id": env.kid})
    assert r.status_code == 429 and "9 Google searches" in r.text and env.places.calls == before


def test_the_daily_cap_counts_what_was_spent_today_and_stops_when_it_is_used_up(env, monkeypatch):
    grid = new_grid(env)
    scan(env, grid, *([2] * 9))  # spends 9 searches today
    monkeypatch.setattr(settings, "rank_platform_daily_cap", 9)
    a = allowance(env)
    assert a["platform_daily_capped"] is True and a["daily_remaining"] == 0
    r = env.biz.post(f"/gbp/{env.gid}/rank/grids/{grid}/scan", json={"keyword_id": env.kid})
    assert r.status_code == 429 and "today is used up" in r.text


def test_operations_reports_maps_off_as_healthy_and_warns_before_a_cap_is_hit(env, monkeypatch):
    db = system_session()
    try:
        monkeypatch.setattr(settings, "rank_grid_enabled", False)
        assert ops.check_geo_grid(db)["status"] == "ok"
        monkeypatch.setattr(settings, "rank_grid_enabled", True)
        monkeypatch.setattr(settings, "rank_platform_daily_cap", 0)
        monkeypatch.setattr(settings, "rank_platform_monthly_cap", 0)
        assert ops.check_geo_grid(db)["status"] == "critical"  # on, but nothing bounds the spend
        monkeypatch.setattr(settings, "rank_platform_daily_cap", 100000)
        monkeypatch.setattr(settings, "rank_cost_per_call_usd", 0.001)
        assert ops.check_geo_grid(db)["status"] == "ok"
    finally:
        db.close()
    grid = new_grid(env)
    scan(env, grid, *([2] * 9))
    monkeypatch.setattr(settings, "rank_platform_daily_cap", 10)  # 9 of 10 used: 90%
    db = system_session()
    try:
        assert ops.check_geo_grid(db)["status"] == "warn"
        monkeypatch.setattr(settings, "rank_platform_daily_cap", 9)
        assert ops.check_geo_grid(db)["status"] == "critical"
    finally:
        db.close()
