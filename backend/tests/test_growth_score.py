"""Growth score: formula, partial scores, isolation. Google and Places are test doubles; reviews and checks are inserted directly so the arithmetic is exact."""
import pytest

from app.services import growth_score as gs
from tests.conftest import owner_exec, owner_query
from tests.test_google_and_reviews import connected, fake, sync_select  # noqa: F401
from tests.test_google_business_agent import gid  # noqa: F401
from tests.test_location_permissions import invite


def add_reviews(gid, ratings, *, replied=0, days_ago=1, reply_hours=2):
    for i, r in enumerate(ratings):
        rep = i < replied
        owner_exec(
            "insert into reviews (id, tenant_id, location_id, google_location_id, external_id, rating, review_created_at, first_seen_at, update_count, google_reply_text, google_reply_at, created_at, updated_at) "
            "select gen_random_uuid(), tenant_id, location_id, id, :ext, :r, now() - make_interval(days => :d), now(), 0, :txt, "
            "case when :rep then now() - make_interval(days => :d) + make_interval(hours => :h) end, now(), now() from google_locations where id = :g",
            ext=f"gs-{days_ago}-{i}-{r}", r=r, d=days_ago, txt="Thanks" if rep else None, rep=rep, h=reply_hours, g=gid)


def part(j, k):
    return next(p for p in j["parts"] if p["key"] == k)


def test_rank_values_follow_the_published_steps():
    assert gs.rank_value(1) == 1 and gs.rank_value(3) == 1
    assert gs.rank_value(4) == pytest.approx(0.75) and gs.rank_value(10) == pytest.approx(0.40)
    assert gs.rank_value(11) == pytest.approx(0.30) and gs.rank_value(20) == pytest.approx(0.05)
    assert gs.rank_value(None) == 0 and gs.rank_value(25) == 0
    assert sum(gs.WEIGHTS.values()) == 100


def test_no_data_gives_no_score_but_still_lists_every_part(connected):  # noqa: F811
    j = connected.get("/analytics/growth-score").json()
    assert j["score"] is None and j["partial"] is True and len(j["parts"]) == 5
    assert part(j, "rating")["available"] is False and part(j, "reviews")["available"] is True  # the goal part is always measurable (0 reviews of a goal)


def test_score_is_the_weighted_mean_of_the_parts_with_data(connected, fake, gid):  # noqa: F811
    owner_exec("update tenants set review_goal = 4 where id = :t", t=connected.tenant_id)
    add_reviews(gid, [5, 5, 4, 4], replied=4, days_ago=0)  # avg 4.5, 4 this month (goal 4), all answered within 2 h
    j = connected.get("/analytics/growth-score").json()
    rating, reviews, replies = part(j, "rating"), part(j, "reviews"), part(j, "replies")
    assert rating["value"] == pytest.approx((4.5 - 4.0) / 0.8, abs=1e-3)
    assert reviews["value"] == 1 and reviews["count"] == 4 and reviews["goal"] == 4 and reviews["goal_set"] is True and reviews["to_go"] == 0
    assert replies["value"] == pytest.approx(1.0) and replies["rate"] == 1
    expected = round(100 * (20 * rating["value"] + 25 * 1 + 15 * 1) / 60)
    assert j["score"] == expected and j["partial"] is True and j["covered_weight"] == 60
    assert part(j, "profile")["available"] is False and part(j, "rank")["available"] is False  # no profile or rank data yet: left out, not zero
    assert j["weakest"] == "rating"


def test_slow_replies_count_less_and_missing_replies_count_nothing(connected, fake, gid):  # noqa: F811
    add_reviews(gid, [5, 5], replied=1, days_ago=10, reply_hours=168)
    r = part(connected.get("/analytics/growth-score").json(), "replies")
    assert r["rate"] == 0.5 and r["value"] == pytest.approx(0.25, abs=0.01)  # half answered, a week to reply = half credit


def test_without_a_goal_the_suggestion_is_last_month_plus_ten_percent(connected, fake, gid):  # noqa: F811
    owner_exec("update tenants set review_goal = null where id = :t", t=connected.tenant_id)
    j = part(connected.get("/analytics/growth-score").json(), "reviews")
    assert j["goal"] >= gs.GOAL_MIN and j["goal_set"] is False


def test_profile_and_rank_join_when_their_data_exists(connected, fake, gid):  # noqa: F811
    add_reviews(gid, [5], replied=1)
    owner_exec("insert into gbp_snapshots (id, tenant_id, google_location_id, info, fetched_at, created_at, updated_at) select gen_random_uuid(), tenant_id, id, "
               "'{\"description\": \"x\", \"hours\": [1], \"phone\": \"1\", \"website\": \"w\", \"primary_category\": {\"name\": \"Dentist\"}}'::jsonb, now(), now(), now() from google_locations where id = :g", g=gid)
    owner_exec("insert into rank_keywords (id, tenant_id, google_location_id, keyword, created_at, updated_at) select gen_random_uuid(), tenant_id, id, 'dentist', now(), now() from google_locations where id = :g", g=gid)
    owner_exec("insert into rank_checks (id, tenant_id, keyword_id, google_location_id, checked_at, status, rank, results_seen, top_results, source) "
               "select gen_random_uuid(), k.tenant_id, k.id, k.google_location_id, now(), 'ok', 2, 20, '[]'::jsonb, 'auto' from rank_keywords k where k.google_location_id = :g", g=gid)
    j = connected.get("/analytics/growth-score").json()
    assert part(j, "profile")["percent"] == 70 and part(j, "rank")["value"] == 1 and part(j, "rank")["top10"] == 1
    assert j["partial"] is False and j["covered_weight"] == 100


def test_another_business_and_restricted_staff_see_only_their_own(connected, fake, gid, biz_b):  # noqa: F811
    add_reviews(gid, [5, 5, 5])
    assert part(biz_b.get("/analytics/growth-score").json(), "rating")["available"] is False
    other = connected.post("/locations", json={"name": "Other branch", "city": "Lucknow", "review_url": "https://g.page/r/ABC/review"}).json()["id"]
    staff = invite(connected, location_ids=[other])
    assert part(staff.get("/analytics/growth-score").json(), "rating")["available"] is False
    assert staff.get("/analytics/growth-score", params={"location_id": connected.location_id}).status_code == 404
    assert owner_query("select count(*) from reviews where tenant_id = :t", t=connected.tenant_id)[0][0] >= 3
