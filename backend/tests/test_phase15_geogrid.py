"""Phase 1.5: geo-grid ranking. MOCKED: the Places client is a TEST DOUBLE (FakePlaces) that returns whatever rank a test scripts for each point, in the order the points are
searched. The database, row-level security, the plan limits, the cost controls and the change detection are real. A pass proves FlowQR's own logic; it is NOT evidence
about what Google Places returns for a real business."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.models.base import utcnow
from app.services import rank as rank_svc
from app.services import rank_grid as rg
from app.services.rank import RankError
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_gbp import FakeGbpProvider, fake, gid  # noqa: F401
from tests.test_google_and_reviews import connected  # noqa: F401
from tests.test_location_permissions import invite


def set_geo(tenant_id, max_grids, max_points, monthly_points):
    """Give the test business map allowances, the way an admin does by approving them on its plan."""
    import json
    owner_exec("UPDATE subscriptions SET limits = CAST(:l AS jsonb) WHERE tenant_id = :t",
               l=json.dumps({"geo": {"max_grids": max_grids, "max_points": max_points, "monthly_points": monthly_points}}), t=tenant_id)


class FakePlaces:
    """TEST DOUBLE of the Places client. `queue` = the rank for each successive search (None = not in the first 20); `errors` = {search number: RankError}."""

    def __init__(self):
        self.queue, self.errors, self.calls, self.radii, self.coords = [], {}, 0, [], []

    def place_location(self, place_id):
        return 26.85, 80.95

    def search(self, query, lat, lng, radius_m):
        self.calls += 1
        self.radii.append(radius_m)
        self.coords.append((lat, lng))
        if self.calls in self.errors:
            raise self.errors[self.calls]
        rank = self.queue.pop(0) if self.queue else None
        res = [{"place_id": f"other{i}", "name": f"Other {i}", "rating": 4.0, "reviews": 10} for i in range(1, 21)]
        if rank:
            res[rank - 1] = {"place_id": "PID", "name": "Us", "rating": 4.5, "reviews": 20}
        return res

    def script(self, *ranks):
        self.queue, self.calls = list(ranks), 0


@pytest.fixture()
def places(monkeypatch):
    p = FakePlaces()
    monkeypatch.setattr(rank_svc, "get_client", lambda: p)
    monkeypatch.setattr(rank_svc, "enabled", lambda: True)
    return p


@pytest.fixture()
def env(connected, gid, places, monkeypatch):  # noqa: F811
    owner_exec("UPDATE google_locations SET lat = 26.85, lng = 80.95, place_id = 'PID' WHERE id = :g", g=gid)
    # the test database is shared by the whole session: start with no earlier searches counted against the platform cap
    owner_exec("DELETE FROM rank_grids")
    owner_exec("DELETE FROM rank_checks")
    monkeypatch.setattr(settings, "rank_platform_monthly_cap", 0)
    set_geo(connected.tenant_id, 2, 9, 150)  # the allowances a plan carries once the owner has approved them (the real plans ship with none: maps stay off)
    # the owner's three platform decisions, as TEST values (not real prices or limits): the master switch, a platform cap, and a recorded price per search
    monkeypatch.setattr(settings, "rank_grid_enabled", True)
    monkeypatch.setattr(settings, "rank_platform_daily_cap", 100000)
    monkeypatch.setattr(settings, "rank_cost_per_call_usd", 0.001)
    kw = connected.post(f"/gbp/{gid}/rank/keywords", json={"keyword": "physiotherapist near me"})
    assert kw.status_code in (201, 409)
    kid = connected.get(f"/gbp/{gid}/rank").json()["keywords"][0]["id"]
    yield type("E", (), {"biz": connected, "gid": gid, "kid": kid, "places": places})()
    owner_exec("DELETE FROM rank_grids WHERE tenant_id = :t", t=connected.tenant_id)
    owner_exec("DELETE FROM rank_checks WHERE tenant_id = :t", t=connected.tenant_id)
    owner_exec("DELETE FROM rank_keywords WHERE tenant_id = :t", t=connected.tenant_id)  # leave no tracked terms behind for tests of the scheduled single-point check


def new_grid(env, name="Main map", size=3, spacing=1000, **kw):
    r = env.biz.post(f"/gbp/{env.gid}/rank/grids", json={"name": name, "mode": "square", "size": size, "spacing_m": spacing, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def scan(env, grid, *ranks):
    env.places.script(*ranks)
    r = env.biz.post(f"/gbp/{env.gid}/rank/grids/{grid}/scan", json={"keyword_id": env.kid})
    assert r.status_code == 200, r.text
    return r.json()["scan"]


def heat(env, grid, **params):
    return env.biz.get(f"/gbp/{env.gid}/rank/grids/{grid}/heatmap", params={"keyword_id": env.kid, **params}).json()


# ============================================================================ geometry

def test_a_square_grid_is_centred_evenly_spaced_and_numbered():
    pts = rg.square_points(26.85, 80.95, 3, 1000)
    assert len(pts) == 9 and [p["i"] for p in pts] == list(range(9))
    assert (pts[4]["lat"], pts[4]["lng"]) == (26.85, 80.95) and pts[4]["label"] == "Centre" and pts[0]["label"] == "NW" and pts[8]["label"] == "SE"
    for a, b in ((0, 1), (1, 2), (0, 3), (3, 6)):  # neighbours are one spacing apart, east-west and north-south alike
        assert rg.distance_m((pts[a]["lat"], pts[a]["lng"]), (pts[b]["lat"], pts[b]["lng"])) == pytest.approx(1000, rel=0.02)
    assert rg.hash_points(pts) == rg.hash_points(rg.square_points(26.85, 80.95, 3, 1000)) != rg.hash_points(rg.square_points(26.85, 80.95, 3, 2000))


def test_custom_points_are_validated_not_trusted():
    ok = rg.clean_custom([{"lat": 26.86, "lng": 80.96, "label": "  North  side "}, {"lat": 26.86, "lng": 80.96}, {"lat": "26.80", "lng": "80.90"}], (26.85, 80.95))
    assert [p["label"] for p in ok] == ["North side", "Point 2"] and len(ok) == 2  # a duplicate is dropped
    for bad in ([{"lat": 91, "lng": 0}], [{"lat": 26.85}], [{"lat": 40.0, "lng": 80.95}], []):
        with pytest.raises(RankError):
            rg.clean_custom(bad, (26.85, 80.95))


# ============================================================================ plan limits

def test_plan_limits_decide_how_many_maps_and_points(env):
    assert env.biz.post(f"/gbp/{env.gid}/rank/grids", json={"name": "Big", "mode": "square", "size": 5, "spacing_m": 1000}).status_code == 409  # 25 > the trial's 9
    a = new_grid(env, "One")
    new_grid(env, "Two")
    assert env.biz.post(f"/gbp/{env.gid}/rank/grids", json={"name": "Three", "mode": "square", "size": 3, "spacing_m": 1000}).status_code == 409  # 2 maps per location
    assert env.biz.post(f"/gbp/{env.gid}/rank/grids", json={"name": "one", "mode": "square", "size": 3, "spacing_m": 1000}).status_code == 409  # same name
    assert env.biz.delete(f"/gbp/{env.gid}/rank/grids/{a}").status_code == 204
    new_grid(env, "Three")  # a freed slot is usable
    ov = env.biz.get(f"/gbp/{env.gid}/rank/grids").json()
    assert ov["allowance"]["limits"] == {"max_grids": 2, "max_points": 9, "monthly_points": 150} and len(ov["grids"]) == 2


def test_a_plan_without_the_map_feature_is_refused_clearly(env, monkeypatch):
    owner_exec("UPDATE subscriptions SET features = (features - 'geo_ranking') WHERE tenant_id = :t", t=env.biz.tenant_id)
    r = env.biz.post(f"/gbp/{env.gid}/rank/grids", json={"name": "Main", "mode": "square", "size": 3, "spacing_m": 1000})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_upgrade_required" and r.json()["detail"]["feature"] == "geo_ranking"
    g = env.biz.get(f"/gbp/{env.gid}/rank/grids")
    assert g.status_code == 402 and g.json()["detail"]["feature"] == "geo_ranking"  # the whole area is closed, not just the buttons
    owner_exec("UPDATE subscriptions SET features = features || '[\"geo_ranking\"]'::jsonb WHERE tenant_id = :t", t=env.biz.tenant_id)


def test_only_owners_and_admins_create_scan_or_remove_maps(env):
    g = new_grid(env)
    staff = invite(env.biz, "staff")
    assert staff.post(f"/gbp/{env.gid}/rank/grids", json={"name": "S", "mode": "square", "size": 3, "spacing_m": 1000}).status_code == 403
    assert staff.post(f"/gbp/{env.gid}/rank/grids/{g}/scan", json={"keyword_id": env.kid}).status_code == 403
    assert staff.delete(f"/gbp/{env.gid}/rank/grids/{g}").status_code == 403
    assert staff.get(f"/gbp/{env.gid}/rank/grids").status_code == 200  # reading is for everyone who can see the location
    r = env.biz.post(f"/gbp/{env.gid}/rank/grids", json={"name": "Own", "mode": "custom", "points": [{"lat": 26.86, "lng": 80.96, "label": "A"}, {"lat": 26.84, "lng": 80.94}]})
    assert r.status_code == 201 and r.json()["point_count"] == 2 and r.json()["mode"] == "custom"
    assert env.biz.delete(f"/gbp/{env.gid}/rank/grids/{r.json()['id']}").status_code == 204  # free a slot so the next requests are judged on their own merits
    assert env.biz.post(f"/gbp/{env.gid}/rank/grids", json={"name": "Far", "mode": "custom", "points": [{"lat": 40, "lng": 80.9}]}).status_code == 422
    assert env.biz.post(f"/gbp/{env.gid}/rank/grids", json={"name": "Sneaky", "mode": "square", "size": 3, "spacing_m": 1000, "tenant_id": str(uuid.uuid4())}).status_code == 422


# ============================================================================ scanning and the map

def test_a_scan_measures_every_point_and_builds_the_heat_map(env):
    g = new_grid(env)
    s = scan(env, g, 1, 2, 5, None, 12, 3, None, 8, 1)
    assert (s["status"], s["points_total"], s["points_ok"], s["points_found"], s["calls"]) == ("done", 9, 9, 7, 9)
    assert s["arp"] == pytest.approx(74 / 9, abs=0.01) and s["atrp"] == pytest.approx(32 / 7, abs=0.01) and s["solv"] == pytest.approx(44.4, abs=0.1) and s["coverage"] == pytest.approx(77.8, abs=0.1)
    h = heat(env, g)
    assert [c["bucket"] for c in h["cells"]] == ["top3", "top3", "top10", "none", "top20", "top3", "none", "top10", "top3"]
    assert [c["rank"] for c in h["cells"]] == [1, 2, 5, None, 12, 3, None, 8, 1] and h["bounds"]["north"] > h["bounds"]["south"]
    assert [x["key"] for x in h["legend"]] == ["top3", "top10", "top20", "none", "error"] and "not estimated" in h["note"]
    assert env.places.calls == 9 and all(r == 1000 for r in env.places.radii) and len(set(env.places.coords)) == 9  # nine different spots were searched


def test_a_point_that_could_not_be_measured_is_an_error_never_a_rank(env):
    g = new_grid(env)
    env.places.errors = {2: RankError("Google Places is having trouble.", 502), 5: RankError("Google Places is having trouble.", 502)}
    s = scan(env, g, 1, 1, 1, 1, 1, 1, 1)
    assert s["status"] == "partial" and (s["points_ok"], s["points_found"]) == (7, 7) and s["solv"] == 100.0 and "2 of 9" in s["error"]
    cells = heat(env, g)["cells"]
    assert [c["bucket"] for c in cells].count("error") == 2 and cells[1]["rank"] is None and cells[1]["status"] == "error" and "trouble" in cells[1]["error"]


def test_a_quota_error_stops_the_scan_instead_of_paying_for_the_rest(env):
    g = new_grid(env)
    env.places.errors = {4: RankError("Google's Places quota is used up for now.", 429)}
    s = scan(env, g, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    assert s["status"] == "partial" and s["calls"] == 4 and env.places.calls == 4 and "quota" in s["error"]
    assert owner_query("SELECT count(*) FROM rank_grid_points WHERE scan_id = :s", s=s["id"])[0][0] == 4  # the three unsearched points were never bought


def test_every_point_failing_is_a_failed_scan_with_no_numbers(env):
    g = new_grid(env)
    env.places.errors = {i: RankError("down", 502) for i in range(1, 10)}
    s = scan(env, g)
    assert s["status"] == "failed" and s["points_ok"] == 0 and s["arp"] is None and s["solv"] is None and s["coverage"] is None


def test_before_any_scan_the_map_is_empty_not_invented(env):
    g = new_grid(env)
    h = heat(env, g)
    assert h["scan"] is None and len(h["cells"]) == 9 and {c["bucket"] for c in h["cells"]} == {"unmeasured"}


# ============================================================================ cost controls

def test_a_scan_that_does_not_fit_the_allowance_is_refused_before_any_search(env, monkeypatch):
    set_geo(env.biz.tenant_id, 2, 9, 8)
    g = new_grid(env)
    env.places.script(1)
    r = env.biz.post(f"/gbp/{env.gid}/rank/grids/{g}/scan", json={"keyword_id": env.kid})
    assert r.status_code == 429 and "needs 9" in r.json()["detail"] and "8 are left" in r.json()["detail"] and "Nothing was spent" in r.json()["detail"]
    assert env.places.calls == 0 and owner_query("SELECT count(*) FROM rank_grid_scans WHERE tenant_id = :t", t=env.biz.tenant_id)[0][0] == 0
    est = env.biz.get(f"/gbp/{env.gid}/rank/grids/{g}/estimate").json()
    assert est["points"] == 9 and est["fits"] is False and est["allowance"]["remaining"] == 8


def test_the_monthly_allowance_is_counted_across_scans_and_estimated_in_money(env, monkeypatch):
    set_geo(env.biz.tenant_id, 2, 9, 15)
    monkeypatch.setattr(settings, "rank_cost_per_call_usd", 0.032)
    g = new_grid(env)
    scan(env, g, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    a = env.biz.get(f"/gbp/{env.gid}/rank/grids").json()["allowance"]
    assert (a["used"], a["remaining"], a["cap"]) == (9, 6, 15) and a["estimated_spend_usd"] == pytest.approx(0.29, abs=0.01)
    env.places.script(1)
    r = env.biz.post(f"/gbp/{env.gid}/rank/grids/{g}/scan", json={"keyword_id": env.kid})
    assert r.status_code == 429 and env.places.calls == 0
    owner_exec("UPDATE rank_grid_points SET checked_at = now() - interval '40 days' WHERE tenant_id = :t", t=env.biz.tenant_id)  # last month's searches do not count
    assert env.biz.get(f"/gbp/{env.gid}/rank/grids").json()["allowance"]["used"] == 0


def test_the_platform_wide_cap_stops_every_business(env, monkeypatch):
    monkeypatch.setattr(settings, "rank_platform_monthly_cap", 5)
    g = new_grid(env)
    env.places.script(1)
    r = env.biz.post(f"/gbp/{env.gid}/rank/grids/{g}/scan", json={"keyword_id": env.kid})
    assert r.status_code == 429 and env.places.calls == 0
    ov = env.biz.get(f"/gbp/{env.gid}/rank/grids").json()["allowance"]
    assert ov["remaining"] == 5  # the tighter of the business's allowance and what the platform has left
    monkeypatch.setattr(settings, "rank_platform_monthly_cap", 9)
    assert scan(env, g, 1, 1, 1, 1, 1, 1, 1, 1, 1)["status"] == "done"
    monkeypatch.setattr(settings, "rank_platform_monthly_cap", 9)
    assert env.biz.get(f"/gbp/{env.gid}/rank/grids").json()["allowance"]["platform_capped"] is True


def test_scans_are_rate_limited_and_need_the_server_to_be_configured(env, monkeypatch):
    g = new_grid(env)
    monkeypatch.setattr(rank_svc, "enabled", lambda: False)
    assert env.biz.post(f"/gbp/{env.gid}/rank/grids/{g}/scan", json={"keyword_id": env.kid}).status_code == 503
    monkeypatch.setattr(rank_svc, "enabled", lambda: True)
    for _ in range(6):
        env.places.script(1)
        assert env.biz.post(f"/gbp/{env.gid}/rank/grids/{g}/scan", json={"keyword_id": env.kid}).status_code == 200
    assert env.biz.post(f"/gbp/{env.gid}/rank/grids/{g}/scan", json={"keyword_id": env.kid}).status_code == 429


def test_the_places_key_never_appears_in_any_response(env, monkeypatch):
    monkeypatch.setattr(settings, "rank_provider_key", "SECRET-PLACES-KEY-123")
    g = new_grid(env)
    scan(env, g, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    for path in ("", f"/{g}/heatmap?keyword_id={env.kid}", f"/{g}/history?keyword_id={env.kid}", f"/{g}/estimate"):
        assert "SECRET-PLACES-KEY" not in env.biz.get(f"/gbp/{env.gid}/rank/grids{path}").text


# ============================================================================ change detection

def test_the_first_scan_has_nothing_to_be_compared_with(env):
    g = new_grid(env)
    s = scan(env, g, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    assert s["change"]["comparable"] is False and "first scan" in s["change"]["reason"]


def test_a_large_move_is_flagged_as_significant_and_described_as_observed(env):
    g = new_grid(env)
    scan(env, g, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    s = scan(env, g, None, None, 15, None, None, 14, None, None, None)  # visibility collapsed
    c = s["change"]
    assert c["comparable"] and c["significant"] and c["direction"] == "declined" and c["points"]["declined"] == 9 and c["delta_solv"] < -15 and c["delta_arp"] > 2
    assert "not proof of why" in c["summary"] and "caused" not in c["summary"].replace("not proof of why it changed", "")
    better = scan(env, g, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    assert better["change"]["direction"] == "improved" and better["change"]["significant"]


def test_small_moves_are_noise_not_a_change(env):
    g = new_grid(env)
    scan(env, g, 4, 5, 6, 7, 8, 9, 10, 11, 12)
    s = scan(env, g, 5, 5, 5, 8, 8, 8, 9, 12, 12)  # every point moved by at most 2 positions
    assert s["change"]["significant"] is False and s["change"]["direction"] == "unchanged" and s["change"]["points"] == {"improved": 0, "declined": 0, "unchanged": 9, "unknown": 0}


def test_a_point_that_failed_is_unknown_in_the_comparison_not_a_decline(env):
    g = new_grid(env)
    scan(env, g, 3, 3, 3, 3, 3, 3, 3, 3, 3)
    env.places.errors = {1: RankError("down", 502)}
    s = scan(env, g, 3, 3, 3, 3, 3, 3, 3, 3, 3)
    assert s["change"]["points"]["unknown"] == 1 and s["change"]["points"]["declined"] == 0 and s["change"]["significant"] is False


def test_a_scan_with_too_few_measured_points_is_not_compared(env):
    g = new_grid(env)
    scan(env, g, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    env.places.errors = {i: RankError("down", 502) for i in range(1, 6)}  # 5 of 9 failed: under 80% measured
    s = scan(env, g, 1, 1, 1, 1)
    assert s["change"]["comparable"] is False and "too few" in s["change"]["reason"].lower()


def test_scans_of_different_maps_are_never_compared(env):
    a, b = new_grid(env, "Map A"), new_grid(env, "Map B", spacing=2000)
    scan(env, a, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    s = scan(env, b, 20, 20, 20, 20, 20, 20, 20, 20, 20)
    assert s["change"]["comparable"] is False  # a different set of points: not a "decline"


def test_history_lists_scans_newest_first_and_a_past_scan_can_be_drawn(env):
    g = new_grid(env)
    first = scan(env, g, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    second = scan(env, g, 9, 9, 9, 9, 9, 9, 9, 9, 9)
    h = env.biz.get(f"/gbp/{env.gid}/rank/grids/{g}/history", params={"keyword_id": env.kid}).json()
    assert [x["id"] for x in h["scans"]] == [second["id"], first["id"]] and h["grid"] == "Main map"
    assert {c["rank"] for c in heat(env, g)["cells"]} == {9}
    assert {c["rank"] for c in heat(env, g, scan_id=first["id"])["cells"]} == {1}


# ============================================================================ isolation

def test_another_business_cannot_see_or_run_these_maps(env):
    g = new_grid(env)
    scan(env, g, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    other = make_business("Isolated Clinic")
    for method, path, body in (("get", f"/gbp/{env.gid}/rank/grids", None), ("get", f"/gbp/{env.gid}/rank/grids/{g}/heatmap?keyword_id={env.kid}", None),
                               ("post", f"/gbp/{env.gid}/rank/grids/{g}/scan", {"keyword_id": env.kid}), ("delete", f"/gbp/{env.gid}/rank/grids/{g}", None)):
        r = getattr(other, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 404, (method, path)
    db = SessionLocal(); set_rls_context(db, tenant_id=uuid.UUID(other.tenant_id))
    for table in ("rank_grids", "rank_grid_scans", "rank_grid_points"):
        assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table
    db.close()


def test_a_scan_refuses_a_grid_and_keyword_from_different_locations(env):
    g = new_grid(env)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    from app.models import GoogleLocation, RankGrid, RankKeyword
    gl, grid, kw = db.get(GoogleLocation, uuid.UUID(env.gid)), db.get(RankGrid, uuid.UUID(g)), db.get(RankKeyword, uuid.UUID(env.kid))
    kw.google_location_id = uuid.uuid4()
    with pytest.raises(RankError) as exc:
        rg.scan(db, gl, grid, kw, client=env.places)
    assert exc.value.status == 404 and env.places.calls == 0
    db.rollback(); db.close()


# ============================================================================ the scheduled scan

def test_the_scheduled_scan_runs_due_maps_once_and_never_overspends(env, monkeypatch):
    from app.workers import tasks
    g = new_grid(env)
    env.places.script(*([2] * 9))
    out = tasks.check_rank_grids.run()
    assert out["scanned"] == 1 and out["skipped"] == 0 and env.places.calls == 9
    assert owner_query("SELECT source FROM rank_grid_scans WHERE grid_id = :g", g=g)[0][0] == "auto"
    assert tasks.check_rank_grids.run()["scanned"] == 0 and env.places.calls == 9  # scanned within the interval: not due
    owner_exec("UPDATE rank_grid_scans SET started_at = now() - interval '8 days' WHERE grid_id = :g", g=g)
    set_geo(env.biz.tenant_id, 2, 9, 12)  # 9 used, 3 left: a whole scan does not fit
    out = tasks.check_rank_grids.run()
    assert out["scanned"] == 0 and out["skipped"] == 1 and env.places.calls == 9  # skipped whole, not half-bought


def test_the_scheduled_scan_does_nothing_without_the_server_key(env, monkeypatch):
    from app.workers import tasks
    new_grid(env)
    monkeypatch.setattr(rank_svc, "enabled", lambda: False)
    assert tasks.check_rank_grids.run() == {"skipped": "not configured"} and env.places.calls == 0


def test_the_scheduled_scan_is_in_the_beat_schedule():
    from app.workers.celery_app import celery_app
    e = celery_app.conf.beat_schedule["check-rank-grids"]
    assert e["task"] == "flowqr.check_rank_grids" and e["schedule"] <= 21600


def test_a_stopped_map_is_not_scanned_automatically(env):
    from app.workers import tasks
    g = new_grid(env)
    assert env.biz.patch(f"/gbp/{env.gid}/rank/grids/{g}", json={"active": False}).json()["active"] is False
    assert tasks.check_rank_grids.run()["scanned"] == 0 and env.places.calls == 0
    assert env.biz.patch(f"/gbp/{env.gid}/rank/grids/{g}", json={"active": True}).json()["active"] is True


def test_deleting_a_map_removes_its_scans_and_points(env):
    g = new_grid(env)
    scan(env, g, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    assert env.biz.delete(f"/gbp/{env.gid}/rank/grids/{g}").status_code == 204
    assert owner_query("SELECT count(*) FROM rank_grid_scans WHERE tenant_id = :t", t=env.biz.tenant_id)[0][0] == 0
    assert owner_query("SELECT count(*) FROM rank_grid_points WHERE tenant_id = :t", t=env.biz.tenant_id)[0][0] == 0
