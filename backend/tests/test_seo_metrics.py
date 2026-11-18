"""Phase 2: gbp_metric_daily (history of what Google reported), the explicit unavailable states, SEO overview, competitor observations and profile health.

Google and Places are test doubles here. These tests prove FlowQR stores, isolates and labels data correctly; they do not prove Google's real answers."""
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.config import settings
from app.core.db import system_session
from app.models import GoogleLocation
from app.models.base import utcnow
from app.services import gbp_metrics as gm
from app.services import rank as rank_svc
from tests.conftest import owner_exec, owner_query
from tests.test_google_and_reviews import connected, fake, sync_select  # noqa: F401
from tests.test_google_business_agent import gid  # noqa: F401
from tests.test_location_permissions import invite
from tests.test_rank_tracker import FakePlaces, KEY, PLACE, add, loc, on  # noqa: F401

TODAY = utcnow().date()  # the product works in UTC; date.today() is local time and disagrees between 00:00 and 05:30 IST


def series(metric_values: dict[str, list[int]], end: date):
    """{metric: [{date, value}...]} ending at `end`, oldest first, exactly as the provider returns it."""
    out = {}
    for m, vals in metric_values.items():
        n = len(vals)
        out[m] = [{"date": (end - timedelta(days=n - 1 - i)).isoformat(), "value": v} for i, v in enumerate(vals)]
    return out


def record_for(gl_id, data, fetched=None):
    db = system_session()
    try:
        gl = db.get(GoogleLocation, uuid.UUID(str(gl_id)))
        n = gm.record(db, gl, data, fetched_at=fetched)
        db.commit()
        return n
    finally:
        db.close()


# ------------------------------------------------------------------------------------------------ migration shape + isolation (RLS)
def test_table_has_forced_rls_a_tenant_policy_and_no_delete_for_the_app_role():
    rows = owner_query("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'gbp_metric_daily'")
    assert rows and rows[0][0] is True and rows[0][1] is True
    assert owner_query("select count(*) from pg_policies where tablename = 'gbp_metric_daily' and policyname = 'tenant_isolation'")[0][0] == 1
    privs = {r[0] for r in owner_query("select privilege_type from information_schema.role_table_grants where table_name = 'gbp_metric_daily' and grantee = 'flowqr_app'")}
    assert {"SELECT", "INSERT", "UPDATE"} <= privs and "DELETE" not in privs


def test_one_row_per_location_metric_and_day_and_values_are_never_negative(connected, fake, gid):  # noqa: F811
    record_for(gid, series({"CALL_CLICKS": [3, 4]}, TODAY - timedelta(days=5)))
    record_for(gid, series({"CALL_CLICKS": [3, 9]}, TODAY - timedelta(days=5)))  # Google revised the latest day
    rows = owner_query("select day, value from gbp_metric_daily where google_location_id = :i order by day", i=gid)
    assert [r[1] for r in rows] == [3, 9] and len(rows) == 2
    with pytest.raises(Exception):
        owner_exec("insert into gbp_metric_daily (id, tenant_id, google_location_id, metric, day, value, first_fetched_at, fetched_at) "
                   "select gen_random_uuid(), tenant_id, id, 'CALL_CLICKS', current_date, -1, now(), now() from google_locations where id = :i", i=gid)


def test_record_keeps_source_metric_location_and_fetch_time_and_skips_bad_points(connected, fake, gid):  # noqa: F811
    from app.models.base import utcnow
    when = utcnow() - timedelta(hours=2)
    n = record_for(gid, {"CALL_CLICKS": [{"date": "2026-11-01", "value": "7"}, {"date": "garbage", "value": 1}, {"date": "2026-11-02", "value": -4}, {"date": "2026-11-03"}]}, fetched=when)
    assert n == 1  # only the one well-formed, non-negative point
    r = owner_query("select metric, day, value, source, fetched_at, first_fetched_at from gbp_metric_daily where google_location_id = :i", i=gid)[0]
    assert r[0] == "CALL_CLICKS" and str(r[1]) == "2026-11-01" and r[2] == 7 and r[3] == "gbp_performance_api" and r[4] == when and r[5] == when


def test_a_revised_day_keeps_the_first_fetch_time_and_updates_the_latest(connected, fake, gid):  # noqa: F811
    from app.models.base import utcnow
    t1, t2 = utcnow() - timedelta(days=1), utcnow()
    record_for(gid, {"CALL_CLICKS": [{"date": "2026-11-01", "value": 2}]}, fetched=t1)
    record_for(gid, {"CALL_CLICKS": [{"date": "2026-11-01", "value": 5}]}, fetched=t2)
    v, first, last = owner_query("select value, first_fetched_at, fetched_at from gbp_metric_daily where google_location_id = :i", i=gid)[0]
    assert v == 5 and first == t1 and last == t2


# ------------------------------------------------------------------------------------------------ unavailable states
def test_without_stored_rows_google_numbers_are_unavailable_with_a_reason_and_no_zeros(connected, fake, gid):  # noqa: F811
    r = connected.get("/analytics/google-metrics")
    assert r.status_code == 200
    j = r.json()
    assert j["availability"]["state"] != "ok" and j["availability"]["reason"]
    assert j["current"] is None and j["previous"] is None and j["series"] == {}


def test_unavailable_reason_follows_the_connection_state(connected, fake, gid):  # noqa: F811
    owner_exec("update google_connections set api_access = 'api_disabled' where id = :c", c=connected.conn_id)
    assert connected.get("/analytics/google-metrics").json()["availability"]["state"] == "api_disabled"
    owner_exec("update google_connections set api_access = 'awaiting_approval' where id = :c", c=connected.conn_id)
    assert connected.get("/analytics/google-metrics").json()["availability"]["state"] == "awaiting_approval"


def test_nothing_is_back_filled_from_the_latest_only_snapshot(connected, fake, gid):  # noqa: F811
    owner_exec("insert into gbp_snapshots (id, tenant_id, google_location_id, performance, fetched_at, created_at, updated_at) "
               "select gen_random_uuid(), tenant_id, id, '{\"current\": 120, \"previous\": 100, \"window_days\": 28}'::jsonb, now(), now(), now() from google_locations where id = :i", i=gid)
    assert owner_query("select count(*) from gbp_metric_daily where google_location_id = :i", i=gid)[0][0] == 0
    assert connected.get("/analytics/google-metrics").json()["availability"]["state"] != "ok"


# ------------------------------------------------------------------------------------------------ data correctness
def test_summary_splits_search_and_maps_and_distinguishes_zero_from_missing(connected, fake, gid):  # noqa: F811
    end = TODAY - timedelta(days=6)
    data = series({"BUSINESS_IMPRESSIONS_MOBILE_SEARCH": [10, 20], "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": [1, 2], "BUSINESS_IMPRESSIONS_MOBILE_MAPS": [5, 5],
                   "CALL_CLICKS": [0, 0], "WEBSITE_CLICKS": [3, 4]}, end)
    record_for(gid, data)
    j = connected.get("/analytics/google-metrics", params={"from": (end - timedelta(days=1)).isoformat(), "to": end.isoformat()}).json()
    assert j["availability"]["state"] == "ok" and j["source"] == "google"
    c = j["current"]
    assert c["search_views"] == 33 and c["maps_views"] == 10 and c["website"] == 7
    assert c["calls"] == 0  # Google said zero: a real zero
    assert c["directions"] is None and c["bookings"] is None  # Google did not return it: unavailable, not zero
    assert j["previous"] is None  # no earlier stored days: no comparison is invented
    assert j["by_location"][0]["totals"]["search_views"] == 33


def test_previous_period_comparison_uses_only_stored_days_and_leaves_google_lag_out(connected, fake, gid):  # noqa: F811
    end = datetime.now(ZoneInfo("Asia/Kolkata")).date() - timedelta(days=gm.LAG_DAYS)  # the endpoint clips to the BUSINESS's own date (its timezone, India by default), which is not UTC between 18:30 and 24:00 UTC
    record_for(gid, series({"CALL_CLICKS": [1] * 14}, end))  # 14 stored days
    j = connected.get("/analytics/google-metrics", params={"from": (end - timedelta(days=6)).isoformat(), "to": TODAY.isoformat()}).json()
    assert j["range"]["to"] == end.isoformat()  # clipped: today's and the last 2 days are not reported by Google yet
    assert j["current"]["calls"] == 7 and j["previous"]["calls"] == 7
    assert j["previous_range"]["days_with_data"] == 7


# ------------------------------------------------------------------------------------------------ tenant isolation + location scope
def test_another_business_sees_nothing(connected, fake, gid, biz_b):  # noqa: F811
    record_for(gid, series({"CALL_CLICKS": [4, 4]}, TODAY - timedelta(days=5)))
    j = biz_b.get("/analytics/google-metrics").json()
    assert j["availability"]["state"] == "no_location" and j["current"] is None and j["by_location"] == []
    assert biz_b.get("/seo/overview").json()["state"] == "no_location"
    assert biz_b.get("/seo/competitors").json()["state"] == "no_location"
    assert biz_b.get("/seo/profile-health").json()["state"] == "no_location"


def test_row_level_security_hides_another_tenants_rows_from_the_app_role(connected, fake, gid, biz_b):  # noqa: F811
    record_for(gid, series({"CALL_CLICKS": [4]}, TODAY - timedelta(days=5)))
    from app.core.db import SessionLocal, set_rls_context
    from sqlalchemy import text
    other = uuid.UUID(biz_b.tenant_id)  # a business that has no metric rows of its own
    mine = owner_query("select tenant_id from google_locations where id = :i", i=gid)[0][0]
    assert other != mine
    db = SessionLocal()
    try:
        set_rls_context(db, tenant_id=other)
        assert db.execute(text("select count(*) from gbp_metric_daily")).scalar() == 0
        set_rls_context(db, tenant_id=mine)
        db.commit()
        assert db.execute(text("select count(*) from gbp_metric_daily")).scalar() >= 1  # the owner of the rows does see them
    finally:
        db.close()


def test_restricted_staff_only_see_their_locations_metrics(connected, fake, gid):  # noqa: F811
    record_for(gid, series({"CALL_CLICKS": [4, 4]}, TODAY - timedelta(days=5)))
    other = connected.post("/locations", json={"name": "Other branch", "city": "Lucknow", "review_url": "https://g.page/r/ABC/review"}).json()["id"]
    staff = invite(connected, location_ids=[other])
    j = staff.get("/analytics/google-metrics").json()
    assert j["availability"]["state"] == "no_location" and j["current"] is None
    assert staff.get("/seo/overview").json()["state"] == "no_location"
    assert connected.get("/analytics/google-metrics").json()["availability"]["state"] == "ok"


# ------------------------------------------------------------------------------------------------ SEO overview / competitors / profile health
def test_seo_overview_summarises_measured_positions_and_labels_the_source(connected, fake, loc, on):  # noqa: F811
    add(connected, loc, "dentist near me")
    add(connected, loc, "root canal")
    on.order = ["x1", "x2", PLACE]
    connected.post(f"/gbp/{loc}/rank/check", json={})
    j = connected.get("/seo/overview").json()
    assert j["state"] == "ok" and j["provider_configured"] is True
    s = j["summary"]
    assert s["tracked"] == 2 and s["measured"] == 2 and s["top3"] == 2 and s["top10"] == 2 and s["source"] == "places"
    assert "not what" in s["note"].lower() or "not estimated" in s["note"].lower() or "measured" in s["note"].lower()
    assert j["google_terms"] is None  # Google has not given us search terms: unavailable, never invented
    assert len(j["trend"]) == 1 and j["trend"][0]["measured"] == 2


def test_not_found_and_failed_checks_need_attention_and_are_never_a_rank(connected, fake, loc, on):  # noqa: F811
    add(connected, loc, "one")
    on.order = ["x1", "x2"]
    connected.post(f"/gbp/{loc}/rank/check", json={})
    j = connected.get("/seo/overview").json()
    assert j["summary"]["not_found"] == 1 and j["summary"]["top20"] == 0
    assert [a["kind"] for a in j["attention"]] == ["not_found"]
    on.fail = "Google rejected the Places key."
    connected.post(f"/gbp/{loc}/rank/check", json={})
    j = connected.get("/seo/overview").json()
    assert j["keywords"][0]["status"] == "error" and j["keywords"][0]["rank"] is None
    assert KEY not in str(j)


def test_google_search_terms_are_reported_separately_from_rank(connected, fake, gid, loc, on):  # noqa: F811
    add(connected, loc, "dentist near me")
    owner_exec("insert into gbp_snapshots (id, tenant_id, google_location_id, performance, fetched_at, created_at, updated_at) "
               "select gen_random_uuid(), tenant_id, id, '{\"keywords\": [{\"keyword\": \"Dentist near me\", \"value\": 90}, {\"keyword\": \"braces cost\", \"value\": 40}, {\"keyword\": \"tiny\", \"value\": null}], "
               "\"keywords_months\": [\"2026-10\"]}'::jsonb, now(), now(), now() from google_locations where id = :i", i=gid)
    j = connected.get("/seo/overview").json()
    t = {x["keyword"]: x for x in j["google_terms"]["terms"]}
    assert t["Dentist near me"]["tracked"] is True and t["braces cost"]["tracked"] is False and t["tiny"]["value"] is None and t["tiny"]["small"] is True
    assert j["google_terms"]["source"] == "google" and "not a ranking position" in j["google_terms"]["note"]
    assert any(a["kind"] == "untracked_term" and a["keyword"] == "braces cost" for a in j["attention"])


def test_competitors_are_observed_from_stored_results_with_dates_and_real_changes(connected, fake, loc, on):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    on.order = ["rival-1", PLACE, "rival-2"]
    connected.post(f"/gbp/{loc}/rank/check", json={"keyword_id": kid})
    calls = len(on.calls)
    # an earlier observation of the same rival with fewer reviews: only stored data is compared
    owner_exec("update rank_checks set checked_at = now() - interval '30 days' where keyword_id = :k", k=kid)
    on.order = ["rival-1", PLACE]
    connected.post(f"/gbp/{loc}/rank/check", json={"keyword_id": kid})
    owner_exec("update rank_checks set top_results = (select jsonb_agg(case when e->>'place_id' = 'rival-1' then jsonb_set(e, '{reviews}', '5') else e end) from jsonb_array_elements(top_results) e) "
               "where keyword_id = :k and checked_at < now() - interval '1 day'", k=kid)
    j = connected.get("/seo/competitors").json()
    assert j["state"] == "ok" and j["stage"] == 2 and j["source"] == "places"
    r1 = next(c for c in j["competitors"] if c["place_id"] == "rival-1")
    assert r1["observations"] == 2 and r1["change"]["reviews_change"] == r1["reviews"] - 5 and r1["observed_at"] and r1["first_observed_at"] < r1["observed_at"]
    assert r1["keywords"][0]["best_position"] == 1 and r1["keywords"][0]["ahead_of_you"] == 2  # above you at both checks
    r2 = next(c for c in j["competitors"] if c["place_id"] == "rival-2")
    assert r2["change"] is None  # one observation is not a change
    assert j["you"]["reviews"] is not None
    assert len(on.calls) == calls + 1  # reading competitors made no Places call
    assert "do not provide competitor data" in j["note"]


def test_competitors_before_any_check_say_so(connected, fake, loc, on):  # noqa: F811
    add(connected, loc)
    assert connected.get("/seo/competitors").json()["state"] == "no_observations"


def test_profile_health_is_unavailable_until_google_shares_the_profile(connected, fake, gid):  # noqa: F811
    j = connected.get("/seo/profile-health").json()
    assert j["locations"][0]["state"] == "unavailable" and j["locations"][0]["checks"] == []


def test_profile_health_checks_come_from_the_stored_profile(connected, fake, gid):  # noqa: F811
    owner_exec("insert into gbp_snapshots (id, tenant_id, google_location_id, info, media, posts, fetched_at, created_at, updated_at) select gen_random_uuid(), tenant_id, id, "
               "'{\"description\": \"short\", \"hours\": null, \"phone\": \"+91 99999 99999\", \"website\": null, \"primary_category\": {\"name\": \"Dentist\"}, \"additional_categories\": [], \"services\": []}'::jsonb, "
               "'[]'::jsonb, '[]'::jsonb, now(), now(), now() from google_locations where id = :i", i=gid)
    j = connected.get("/seo/profile-health").json()
    loc0 = j["locations"][0]
    by = {c["key"]: c for c in loc0["checks"]}
    assert by["description"]["status"] == "warn" and by["hours"]["status"] == "missing" and by["phone"]["status"] == "ok" and by["website"]["status"] == "missing"
    assert by["services"]["status"] == "warn" and by["photos"]["status"] == "missing" and by["posts"]["status"] == "warn"
    assert loc0["completeness"] == 30  # phone 15 + category 15; the 5-character description does not count
    assert j["health"]["formula"]

