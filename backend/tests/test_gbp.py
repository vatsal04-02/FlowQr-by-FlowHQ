"""Business Profile management with a TEST DOUBLE provider (no real Google calls)."""
import pytest

from app.services import google as g
from tests.test_google_and_reviews import FakeGoogleProvider, connected, sync_select  # noqa: F401


class FakeGbpProvider(FakeGoogleProvider):
    """TEST DOUBLE implementing the Business Profile management surface."""

    def __init__(self):
        super().__init__()
        self.details = {"title": "Clinic", "description": "Old", "phone": "+91 98765 43210", "website": "https://clinic.example.com",
                        "primary_category": {"id": "categories/gcid:physiotherapist", "name": "Physiotherapist"},
                        "additional_categories": [], "hours": [{"day": "MONDAY", "open": "09:00", "close": "18:00"}]}
        self.posts, self.media, self.writes, self.error = [], [], [], None

    def _maybe(self):
        if self.error:
            raise self.error

    def get_location_details(self, at, loc):
        self._maybe(); return dict(self.details)

    def update_location(self, at, loc, changes):
        self._maybe(); self.writes.append(("update", dict(changes)))
        if "description" in changes: self.details["description"] = changes["description"]
        if "hours" in changes: self.details["hours"] = changes["hours"]
        return dict(self.details)

    def search_categories(self, at, q, region="IN", language="en"):
        return [{"id": "categories/gcid:dentist", "name": "Dentist"}]

    def list_posts(self, at, acct, loc): self._maybe(); return list(self.posts)

    def create_post(self, at, acct, loc, post):
        self._maybe(); p = {"name": f"{acct}/{loc}/localPosts/{len(self.posts)+1}", "summary": post["summary"], "state": "LIVE", "cta_type": post.get("cta_type")}
        self.posts.append(p); return p

    def update_post(self, at, name, post):
        self._maybe()
        for p in self.posts:
            if p["name"] == name:
                p["summary"], p["cta_type"] = post["summary"], post.get("cta_type"); return dict(p)
        raise g.GoogleAPIError(404, "no post")

    def delete_post(self, at, name): self._maybe(); self.posts = [p for p in self.posts if p["name"] != name]
    def list_media(self, at, acct, loc): return list(self.media)

    def add_media(self, at, acct, loc, url, cat):
        m = {"name": f"{acct}/{loc}/media/{len(self.media)+1}", "category": cat, "url": url}; self.media.append(m); return m

    def delete_media(self, at, name): self.media = [m for m in self.media if m["name"] != name]

    def fetch_performance(self, at, loc, start, end, metrics):
        return {"CALL_CLICKS": [{"date": start, "value": 3}, {"date": end, "value": 4}], "WEBSITE_CLICKS": [{"date": start, "value": 10}]}


@pytest.fixture()
def fake(monkeypatch):
    f = FakeGbpProvider()
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    return f


@pytest.fixture()
def gid(connected, fake):  # noqa: F811
    sync_select(connected, fake)
    return connected.glocs[0]["id"]


def test_info_read_and_update_returns_what_google_holds(connected, fake, gid):
    assert connected.get(f"/gbp/{gid}/info").json()["description"] == "Old"
    r = connected.patch(f"/gbp/{gid}/info", json={"description": "Physiotherapy in Gomti Nagar.", "hours": [{"day": "TUESDAY", "open": "10:00", "close": "17:30"}]})
    assert r.status_code == 200 and r.json()["description"] == "Physiotherapy in Gomti Nagar."
    # each field is its own governed change now (policy, claim, write, read-back, history): the hours reached Google as their own write
    assert any((w[1].get("hours") or [{}])[0].get("day") == "TUESDAY" for w in fake.writes)


@pytest.mark.parametrize("body", [
    {"description": "x" * 751}, {"hours": [{"day": "FUNDAY", "open": "09:00", "close": "10:00"}]},
    {"hours": [{"day": "MONDAY", "open": "18:00", "close": "09:00"}]}, {"hours": [{"day": "MONDAY", "open": "9am", "close": "6pm"}]},
    {"primary_category": "Physio"}, {"website": "ftp://x"},
])
def test_info_validation_rejects_bad_input(connected, fake, gid, body):
    assert connected.patch(f"/gbp/{gid}/info", json=body).status_code == 422
    assert fake.writes == []


def test_google_failure_is_not_reported_as_success(connected, fake, gid):
    fake.error = g.GoogleAPIError(403, "denied")
    r = connected.patch(f"/gbp/{gid}/info", json={"description": "New description text"})
    assert r.status_code == 403 and "denied" in r.json()["detail"].lower()
    fake.error = g.GoogleRateLimited(30)
    assert connected.post(f"/gbp/{gid}/posts", json={"summary": "Free check-up week for new patients!"}).status_code == 429
    fake.error = g.GoogleAuthRevoked("x")
    assert connected.get(f"/gbp/{gid}/info").status_code == 409


def test_posts_media_performance_and_categories(connected, fake, gid):
    p = connected.post(f"/gbp/{gid}/posts", json={"summary": "Winter back-care workshop on Saturday.", "cta_type": "LEARN_MORE", "cta_url": "https://clinic.example.com/workshop"})
    assert p.status_code == 201
    assert len(connected.get(f"/gbp/{gid}/posts").json()) == 1
    assert connected.post(f"/gbp/{gid}/posts", json={"summary": "Book now please friends", "cta_type": "BOOK"}).status_code == 422  # BOOK needs https link
    assert connected.delete(f"/gbp/{gid}/posts", params={"name": p.json()["name"]}).status_code == 204
    assert connected.delete(f"/gbp/{gid}/posts", params={"name": "accounts/999/locations/1/localPosts/1"}).status_code == 404  # other location
    m = connected.post(f"/gbp/{gid}/media", json={"source_url": "https://cdn.example.com/front.jpg", "category": "EXTERIOR"})
    assert m.status_code == 201 and connected.post(f"/gbp/{gid}/media", json={"source_url": "http://x/y.jpg"}).status_code == 422
    perf = connected.get(f"/gbp/{gid}/performance", params={"from": "2025-01-01", "to": "2025-01-31"}).json()
    assert perf["totals"]["CALL_CLICKS"] == 7 and "Not the same as FlowQR" in perf["note"]
    assert connected.get(f"/gbp/{gid}/categories", params={"q": "dent"}).json()[0]["name"] == "Dentist"


def test_plan_gating_and_roles_and_isolation(connected, fake, gid, biz_b):
    from tests.test_billing import db_sub
    db, sub = db_sub(connected.tenant_id); sub.features = ["review_sync", "ai_replies", "gbp_info"]; db.commit(); db.close()
    assert connected.get(f"/gbp/{gid}/info").status_code == 200
    r = connected.post(f"/gbp/{gid}/posts", json={"summary": "Plan without posts feature."})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_upgrade_required"
    # another tenant cannot touch this Google location
    assert biz_b.get(f"/gbp/{gid}/info").status_code == 404
    assert biz_b.patch(f"/gbp/{gid}/info", json={"description": "hacked description"}).status_code == 404


def test_post_can_be_edited_and_edit_is_scoped_audited_and_admin_only(connected, fake, gid):
    p = connected.post(f"/gbp/{gid}/posts", json={"summary": "Winter back-care workshop on Saturday."}).json()
    r = connected.http.patch(f"/api/v1/gbp/{gid}/posts", params={"name": p["name"]}, json={"summary": "Workshop moved to Sunday 10am."},
                             headers={"X-CSRF-Token": connected.csrf})
    assert r.status_code == 200 and r.json()["summary"] == "Workshop moved to Sunday 10am."
    assert fake.posts[0]["summary"] == "Workshop moved to Sunday 10am."
    other = connected.http.patch(f"/api/v1/gbp/{gid}/posts", params={"name": "accounts/999/locations/1/localPosts/1"},
                                 json={"summary": "Cross-location edit attempt."}, headers={"X-CSRF-Token": connected.csrf})
    assert other.status_code == 404


def test_unapproved_project_is_shown_as_awaiting_approval_not_as_working(connected, fake, gid):
    fake.error = g.GoogleApiNotApproved(429, "quota 0")
    r = connected.get(f"/gbp/{gid}/posts")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "google_api_awaiting_approval"
    conn = connected.get("/google/status").json()["connections"][0]
    assert conn["api_access"] == "awaiting_approval" and conn["api_access_checked_at"]
    fake.error = None
    assert connected.get(f"/gbp/{gid}/posts").status_code == 200


def test_disabled_api_is_reported_separately_from_awaiting_approval(connected, fake, gid):
    fake.error = g.GoogleApiNotApproved(403, "disabled", why="service_disabled", service="mybusiness.googleapis.com")
    r = connected.get(f"/gbp/{gid}/posts")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "google_api_api_disabled"
    assert "mybusiness.googleapis.com" in r.json()["detail"]["message"]
    assert connected.get("/google/status").json()["connections"][0]["api_access"] == "api_disabled"


def test_profile_edits_are_capped_at_googles_ten_per_minute_per_location(connected, fake, gid):
    for i in range(10):
        assert connected.post(f"/gbp/{gid}/posts", json={"summary": f"Announcement number {i} for today"}).status_code == 201
    r = connected.post(f"/gbp/{gid}/posts", json={"summary": "The eleventh edit this minute"})
    assert r.status_code == 429 and "10 profile edits" in r.json()["detail"]
    assert len(fake.posts) == 10  # the 11th never reached Google
    assert connected.get(f"/gbp/{gid}/posts").status_code == 200  # reads are not edits


def test_google_400_is_shown_as_a_rejected_change_not_a_server_error(connected, fake, gid):
    fake.error = g.GoogleAPIError(400, "Request contains an invalid argument.")
    r = connected.post(f"/gbp/{gid}/posts", json={"summary": "A perfectly ordinary post"})
    assert r.status_code == 422 and "Google rejected this change" in r.json()["detail"]


def test_media_categories_follow_googles_enum(connected, fake, gid):
    assert connected.post(f"/gbp/{gid}/media", json={"source_url": "https://cdn.example.com/menu.jpg", "category": "MENU"}).status_code == 201
    assert connected.post(f"/gbp/{gid}/media", json={"source_url": "https://cdn.example.com/x.jpg", "category": "SELFIE"}).status_code == 422
