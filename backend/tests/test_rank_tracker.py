"""Local rank tracking (GBP Manager > Local ranking). The Places client is tested against Google's documented request/response shapes with an
httpx MockTransport (no network); the service and API are tested with a fake client. Nothing here proves Google's real answers: the live check
is done separately with a real key."""
import json

import httpx
import uuid

import pytest

from app.core.config import settings
from app.services import rank as rank_svc
from tests.conftest import owner_exec, owner_query
from tests.test_google_and_reviews import connected, fake, sync_select  # noqa: F401
from tests.test_google_business_agent import gid  # noqa: F401
from tests.test_location_permissions import invite

KEY = "AIza-test-key-should-never-leak"
PLACE = "ChIJ-our-place"


class FakePlaces:
    def __init__(self, order=None, fail=None):
        self.order, self.fail, self.calls, self.details = order or [], fail, [], 0

    def place_location(self, place_id):
        self.details += 1
        return 26.85, 80.95

    def search(self, query, lat, lng, radius_m):
        self.calls.append((query, lat, lng, radius_m))
        if self.fail:
            raise rank_svc.RankError(self.fail, 503)
        return [{"place_id": p, "name": f"Place {i}", "rating": 4.5, "reviews": 10 + i} for i, p in enumerate(self.order, 1)]


@pytest.fixture()
def on(monkeypatch):
    monkeypatch.setattr(settings, "rank_provider", "google_places")
    monkeypatch.setattr(settings, "rank_provider_key", KEY)
    monkeypatch.setattr(settings, "rank_monthly_check_cap", 300)
    c = FakePlaces(order=["x1", "x2", PLACE, "x4"])
    monkeypatch.setattr(rank_svc, "get_client", lambda: c)
    return c


@pytest.fixture()
def loc(connected, fake, gid):  # noqa: F811
    owner_exec("UPDATE google_locations SET place_id = :p, lat = NULL, lng = NULL WHERE id = :i", p=PLACE, i=gid)
    return gid


def add(biz, gid, word="dentist near me"):
    return biz.post(f"/gbp/{gid}/rank/keywords", json={"keyword": word})


# ------------------------------------------------------------------------ Places client (request shape + error mapping)
def _client(handler):
    return rank_svc.PlacesClient(KEY, transport=httpx.MockTransport(handler))


def test_search_request_matches_places_api_new_and_keeps_the_key_in_a_header():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(url=str(req.url), headers=req.headers, body=json.loads(req.content))
        return httpx.Response(200, json={"places": [{"id": "a", "displayName": {"text": "A Dental"}, "rating": 4.8, "userRatingCount": 120}, {"id": PLACE}]})

    out = _client(handler).search("dentist", 26.8, 80.9, 3000)
    assert seen["url"] == "https://places.googleapis.com/v1/places:searchText" and KEY not in seen["url"]
    assert seen["headers"]["x-goog-api-key"] == KEY and "places.id" in seen["headers"]["x-goog-fieldmask"]
    assert seen["body"]["textQuery"] == "dentist" and seen["body"]["pageSize"] == 20
    assert seen["body"]["locationBias"]["circle"] == {"center": {"latitude": 26.8, "longitude": 80.9}, "radius": 3000.0}
    assert [p["place_id"] for p in out] == ["a", PLACE] and out[0]["name"] == "A Dental" and out[0]["reviews"] == 120


@pytest.mark.parametrize("code,status,fragment", [(403, "PERMISSION_DENIED", "rejected the Places key"), (429, "RESOURCE_EXHAUSTED", "quota"),
                                                  (404, "NOT_FOUND", "place ID"), (503, "UNAVAILABLE", "trouble")])
def test_google_errors_become_clear_messages_without_the_key(code, status, fragment):
    c = _client(lambda req: httpx.Response(code, json={"error": {"status": status, "message": f"secret {KEY} detail"}}))
    with pytest.raises(rank_svc.RankError) as e:
        c.search("x", 1, 1, 1000)
    assert fragment in str(e.value) and KEY not in str(e.value)


def test_network_failure_is_a_clean_error():
    def boom(req):
        raise httpx.ConnectError("down")
    with pytest.raises(rank_svc.RankError, match="could not be reached"):
        _client(boom).place_location("p")


# ------------------------------------------------------------------------ service + API
def test_status_says_not_configured_and_checks_are_refused_without_a_key(connected, fake, loc, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "rank_provider", ""), monkeypatch.setattr(settings, "rank_provider_key", "")
    assert connected.get(f"/gbp/{loc}/rank").json()["configured"] is False
    assert add(connected, loc).status_code == 201
    r = connected.post(f"/gbp/{loc}/rank/check", json={})
    assert r.status_code == 503 and "set up" in r.json()["detail"]
    assert owner_query("select count(*) from rank_checks where tenant_id = :t", t=uuid.UUID(connected.tenant_id))[0][0] == 0  # nothing measured for THIS business, nothing invented (the table is shared with other tests)


def test_check_measures_the_real_position_and_reports_movement(connected, fake, loc, on):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    r = connected.post(f"/gbp/{loc}/rank/check", json={"keyword_id": kid})
    assert r.status_code == 200, r.text
    k = r.json()["keywords"][0]
    assert k["latest"]["status"] == "ok" and k["latest"]["rank"] == 3 and k["latest"]["results_seen"] == 4 and k["change"] is None
    assert [p["is_you"] for p in k["latest"]["top_results"]] == [False, False, True, False]
    assert on.calls[0][0] == "dentist near me" and on.calls[0][3] == settings.rank_radius_m
    on.order = [PLACE, "x1"]
    k = connected.post(f"/gbp/{loc}/rank/check", json={"keyword_id": kid}).json()["keywords"][0]
    assert k["latest"]["rank"] == 1 and k["previous_rank"] == 3 and k["change"] == 2  # moved up two places
    assert on.details == 1  # the position was looked up once and cached
    assert connected.get(f"/gbp/{loc}/rank/keywords/{kid}/history").json()["checks"][0]["rank"] == 1


def test_not_found_is_not_found_never_a_made_up_number(connected, fake, loc, on):  # noqa: F811
    on.order = ["x1", "x2"]
    add(connected, loc)
    k = connected.post(f"/gbp/{loc}/rank/check", json={}).json()["keywords"][0]
    assert k["latest"]["status"] == "ok" and k["latest"]["rank"] is None and k["latest"]["results_seen"] == 2


def test_a_google_failure_is_recorded_as_a_failed_check_not_a_rank(connected, fake, loc, on):  # noqa: F811
    on.fail = "Google rejected the Places key."
    add(connected, loc)
    r = connected.post(f"/gbp/{loc}/rank/check", json={})
    assert r.status_code == 200 and r.json()["failed"] == 1
    k = connected.get(f"/gbp/{loc}/rank").json()["keywords"][0]
    assert k["latest"]["status"] == "error" and k["latest"]["rank"] is None and "rejected" in k["latest"]["error"]


def test_monthly_allowance_stops_spending(connected, fake, loc, on, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "rank_monthly_check_cap", 2)
    for w in ("one", "two", "three"):
        assert add(connected, loc, w).status_code == 201
    r = connected.post(f"/gbp/{loc}/rank/check", json={})
    assert r.status_code == 200 and r.json()["checked"] == 2 and "limit" in r.json()["stopped"] and len(on.calls) == 2
    again = connected.post(f"/gbp/{loc}/rank/check", json={})
    assert again.status_code == 429 and len(on.calls) == 2  # no further Google call
    assert connected.get(f"/gbp/{loc}/rank").json()["usage"] == {"used": 2, "cap": 2, "resets_on": rank_svc.next_month_start().date().isoformat()}


def test_keyword_rules(connected, fake, loc, on):  # noqa: F811
    assert add(connected, loc, " Root   canal ").json()["keyword"] == "Root canal"
    assert add(connected, loc, "root canal").status_code == 409  # duplicate, case-insensitive
    assert add(connected, loc, "x").status_code == 422
    assert add(connected, loc, "bad\x00word").status_code == 422
    for i in range(9):
        assert add(connected, loc, f"term number {i}").status_code == 201
    assert add(connected, loc, "one too many").status_code == 409


def test_the_key_never_appears_in_any_response(connected, fake, loc, on):  # noqa: F811
    add(connected, loc)
    blobs = [connected.get(f"/gbp/{loc}/rank").text, connected.post(f"/gbp/{loc}/rank/check", json={}).text, connected.get("/workspace/integrations").text]
    assert all(KEY not in b for b in blobs)
    assert next(i for i in connected.get("/workspace/integrations").json()["integrations"] if i["id"] == "rank_provider")["status"] == "connected"


def test_staff_can_read_but_not_change_or_spend(connected, fake, loc, on):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    staff = invite(connected)
    assert staff.get(f"/gbp/{loc}/rank").status_code == 200
    assert staff.post(f"/gbp/{loc}/rank/keywords", json={"keyword": "nope"}).status_code == 403
    assert staff.post(f"/gbp/{loc}/rank/check", json={}).status_code == 403
    assert staff.delete(f"/gbp/{loc}/rank/keywords/{kid}").status_code == 403
    assert on.calls == []


def test_another_business_cannot_see_spend_or_delete(connected, fake, loc, on, biz_b):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    connected.post(f"/gbp/{loc}/rank/check", json={})
    for method, url, kw in [("GET", f"/gbp/{loc}/rank", {}), ("POST", f"/gbp/{loc}/rank/keywords", {"json": {"keyword": "sneaky"}}),
                            ("POST", f"/gbp/{loc}/rank/check", {"json": {}}), ("DELETE", f"/gbp/{loc}/rank/keywords/{kid}", {}),
                            ("GET", f"/gbp/{loc}/rank/keywords/{kid}/history", {})]:
        assert biz_b.request(method, url, **kw).status_code in (403, 404), (method, url)
    assert len(on.calls) == 1  # B's attempts never reached Google
    assert owner_query("select count(*) from rank_keywords where tenant_id = :t", t=connected.tenant_id)[0][0] == 1
    assert owner_query("select count(*) from rank_keywords where tenant_id = :t", t=biz_b.tenant_id)[0][0] == 0


def test_delete_removes_history(connected, fake, loc, on):  # noqa: F811
    kid = add(connected, loc).json()["id"]
    connected.post(f"/gbp/{loc}/rank/check", json={})
    assert connected.delete(f"/gbp/{loc}/rank/keywords/{kid}").status_code == 204
    assert owner_query("select count(*) from rank_checks where tenant_id = :t", t=connected.tenant_id)[0][0] == 0


def test_scheduled_task_checks_only_what_is_due(connected, fake, loc, on):  # noqa: F811
    from app.workers import tasks
    add(connected, loc, "first"), add(connected, loc, "second")
    mine = "select count(*) from rank_checks where tenant_id = :t and source = 'auto'"
    tasks.check_ranks()
    assert owner_query(mine, t=connected.tenant_id)[0][0] == 2
    tasks.check_ranks()  # checked a moment ago: nothing for this business is due again
    assert owner_query(mine, t=connected.tenant_id)[0][0] == 2
    owner_exec("UPDATE rank_checks SET checked_at = now() - interval '9 days' WHERE tenant_id = :t", t=connected.tenant_id)
    tasks.check_ranks()
    assert owner_query(mine, t=connected.tenant_id)[0][0] == 4


def test_scheduled_task_does_nothing_without_a_key(connected, fake, loc, monkeypatch):  # noqa: F811
    from app.workers import tasks
    monkeypatch.setattr(settings, "rank_provider_key", "")
    assert tasks.check_ranks() == {"skipped": "not configured"}


def test_the_keyword_limit_is_a_setting_not_a_hardcoded_number(connected, fake, loc, on, monkeypatch):  # noqa: F811
    """Phase 2: the number of search terms per location is an owner decision that has not been made, so it must be changeable without a code change."""
    monkeypatch.setattr(settings, "rank_max_keywords_per_location", 2)
    assert add(connected, loc, "first term").status_code == 201
    assert add(connected, loc, "second term").status_code == 201
    r = add(connected, loc, "third term")
    assert r.status_code == 409 and "up to 2 search terms" in r.json()["detail"]
    monkeypatch.setattr(settings, "rank_max_keywords_per_location", 3)
    assert add(connected, loc, "third term").status_code == 201
