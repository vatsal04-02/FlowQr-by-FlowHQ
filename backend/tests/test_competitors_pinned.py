"""Competitor Analysis stage 2: following competitors costs no Google call, snapshots come only from real stored or newly received Places results, and tenants stay isolated.

Places is a test double. These tests prove FlowQR stores and isolates correctly, not what Google would return."""
import pytest

from tests.conftest import owner_exec, owner_query
from tests.test_google_and_reviews import connected, fake, sync_select  # noqa: F401
from tests.test_google_business_agent import gid  # noqa: F401
from tests.test_location_permissions import invite
from tests.test_rank_tracker import PLACE, add, loc, on  # noqa: F401


def check(biz, loc, kid):
    r = biz.post(f"/gbp/{loc}/rank/check", json={"keyword_id": kid})
    assert r.status_code == 200, r.text


def pin(biz, loc, place):
    return biz.post("/seo/competitors/pinned", json={"google_location_id": loc, "place_id": place})


def test_the_new_tables_have_forced_rls_a_tenant_policy_and_append_only_snapshots():
    for t in ("pinned_competitors", "competitor_snapshots"):
        rows = owner_query("select relrowsecurity, relforcerowsecurity from pg_class where relname = :t", t=t)
        assert rows and rows[0][0] is True and rows[0][1] is True
        assert owner_query("select count(*) from pg_policies where tablename = :t and policyname = 'tenant_isolation'", t=t)[0][0] == 1
    privs = {r[0] for r in owner_query("select privilege_type from information_schema.role_table_grants where table_name = 'competitor_snapshots' and grantee = 'flowqr_app'")}
    assert privs == {"SELECT", "INSERT"}


def test_pinning_uses_only_stored_observations_and_makes_no_google_call(connected, fake, loc, on):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    on.order = ["rival-1", PLACE, "rival-2"]
    check(connected, loc, kid)
    on.order = ["rival-2", "rival-1", PLACE]
    check(connected, loc, kid)
    calls = len(on.calls)
    r = pin(connected, loc, "rival-1")
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["observations"] == 2 and j["name"] and j["source"] == "rank_check"
    assert j["visibility"]["appeared_in"] == 2 and j["visibility"]["of_checks"] == 2 and j["visibility"]["in_top10"] == 2
    assert len(on.calls) == calls  # no Places search was made
    assert connected.get("/seo/competitors").json()["pinned"][0]["place_id"] == "rival-1"


def test_a_place_that_never_appeared_your_own_business_and_duplicates_are_refused(connected, fake, loc, on):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    on.order = ["rival-1", PLACE]
    check(connected, loc, kid)
    assert pin(connected, loc, "never-seen").status_code == 404
    assert pin(connected, loc, PLACE).status_code == 422
    assert pin(connected, loc, "rival-1").status_code == 201
    assert pin(connected, loc, "rival-1").status_code == 409


def test_at_most_five_competitors_per_location(connected, fake, loc, on):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    on.order = [f"r{i}" for i in range(7)] + [PLACE]
    check(connected, loc, kid)
    for i in range(5):
        assert pin(connected, loc, f"r{i}").status_code == 201
    r = pin(connected, loc, "r5")
    assert r.status_code == 409 and "up to 5" in r.text


def test_a_new_check_adds_a_snapshot_for_a_followed_competitor_with_its_position_even_below_the_top_ten(connected, fake, loc, on):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    on.order = ["rival-1", PLACE]
    check(connected, loc, kid)
    pid = pin(connected, loc, "rival-1").json()["id"]
    on.order = [f"x{i}" for i in range(11)] + ["rival-1", PLACE]  # rival-1 is 12th, you are 13th
    check(connected, loc, kid)
    p = connected.get("/seo/competitors").json()["pinned"][0]
    assert p["observations"] == 2
    assert p["series"][-1]["position"] == 12  # recorded from the full result list, not only the stored top 10
    rows = owner_query("select position, your_position from competitor_snapshots where competitor_id = :p order by observed_at", p=pid)
    assert rows == [(1, 2), (12, 13)]


def test_a_check_where_the_competitor_did_not_appear_adds_nothing_absence_is_not_a_rank(connected, fake, loc, on):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    on.order = ["rival-1", PLACE]
    check(connected, loc, kid)
    pin(connected, loc, "rival-1")
    on.order = ["x1", PLACE]
    check(connected, loc, kid)
    p = connected.get("/seo/competitors").json()["pinned"][0]
    assert p["observations"] == 1 and p["visibility"]["appeared_in"] == 1 and p["visibility"]["of_checks"] == 2


def test_change_needs_two_observations_on_different_days_and_is_the_real_difference(connected, fake, loc, on):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    on.order = ["rival-1", PLACE]
    check(connected, loc, kid)
    pin(connected, loc, "rival-1")
    p = connected.get("/seo/competitors").json()["pinned"][0]
    assert p["change"] is None  # one observation
    owner_exec("update competitor_snapshots set observed_at = now() - interval '20 days', reviews = 5, rating = 4.0")
    check(connected, loc, kid)
    p = connected.get("/seo/competitors").json()["pinned"][0]
    assert p["observations"] == 2 and p["change"]["reviews_change"] == p["reviews"] - 5 and p["change"]["rating_change"] == pytest.approx(p["rating"] - 4.0, abs=0.1)


def test_unfollowing_removes_the_competitor_and_its_snapshots(connected, fake, loc, on):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    on.order = ["rival-1", PLACE]
    check(connected, loc, kid)
    pid = pin(connected, loc, "rival-1").json()["id"]
    assert owner_query("select count(*) from competitor_snapshots where competitor_id = :p", p=pid)[0][0] == 1
    assert connected.delete(f"/seo/competitors/pinned/{pid}").status_code == 204
    assert connected.get("/seo/competitors").json()["pinned"] == []
    assert owner_query("select count(*) from competitor_snapshots where competitor_id = :p", p=pid)[0][0] == 0


def test_only_owners_and_admins_can_follow_and_other_businesses_cannot_touch_it(connected, fake, loc, on, biz_b):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    on.order = ["rival-1", PLACE]
    check(connected, loc, kid)
    staff = invite(connected)
    assert pin(staff, loc, "rival-1").status_code == 403
    pid = pin(connected, loc, "rival-1").json()["id"]
    assert staff.delete(f"/seo/competitors/pinned/{pid}").status_code == 403
    assert biz_b.delete(f"/seo/competitors/pinned/{pid}").status_code == 404  # another business: not found, not forbidden
    assert pin(biz_b, loc, "rival-1").status_code == 404
    assert biz_b.get("/seo/competitors").json()["pinned"] == []
    assert connected.get("/seo/competitors").json()["pinned"][0]["id"] == pid


def test_restricted_staff_cannot_see_another_locations_competitor(connected, fake, loc, on):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    on.order = ["rival-1", PLACE]
    check(connected, loc, kid)
    pid = pin(connected, loc, "rival-1").json()["id"]
    other = connected.post("/locations", json={"name": "Other branch", "city": "Lucknow", "review_url": "https://g.page/r/ABC/review"}).json()["id"]
    staff = invite(connected, location_ids=[other])  # only staff can be limited to locations; owners and admins see every location
    assert staff.get("/seo/competitors").json()["pinned"] == []
    assert staff.delete(f"/seo/competitors/pinned/{pid}").status_code == 403  # and staff cannot follow or unfollow at all
