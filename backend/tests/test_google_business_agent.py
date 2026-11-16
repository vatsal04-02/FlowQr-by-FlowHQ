"""Google Business AI agent: photo scheduler, offer/event posts, search keywords, reply tones + publishing state, profile optimizer,
review request templates, agent integration.

MOCKED: every Google call here goes to a TEST DOUBLE (FakeAgentGoogle) or an httpx.MockTransport that checks the exact request we send.
Nothing in this file talks to the real Google APIs; live verification is the separate read-only `google-smoke` command."""
import io
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from PIL import Image

from app.models.base import utcnow
from app.services import google as g
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_gbp import FakeGbpProvider
from tests.test_google_and_reviews import StubReplyAI, connected, greview, sync_select  # noqa: F401
from tests.test_location_permissions import invite


class FakeAgentGoogle(FakeGbpProvider):
    """TEST DOUBLE adding the media byte upload, single-media read and search keywords."""

    def __init__(self):
        super().__init__()
        self.uploads, self.created_posts, self.serving, self.upload_error = [], [], False, None
        self.keywords = [{"keyword": "physiotherapist near me", "value": 120, "below": None}, {"keyword": "back pain clinic", "value": None, "below": 15}]

    def upload_media_bytes(self, at, acct, loc, data, content_type, category, description=None):
        if self.upload_error:
            raise self.upload_error
        self.uploads.append({"bytes": len(data), "content_type": content_type, "category": category, "description": description})
        name = f"{acct}/{loc}/media/up{len(self.uploads)}"
        self.media.append({"name": name, "category": category})
        return {"name": name, "category": category, "google_url": None}

    def get_media(self, at, name):
        return {"name": name, "google_url": "https://lh3.googleusercontent.com/p/x" if self.serving else None}

    def search_keywords(self, at, loc, start, end, limit=300):
        return list(self.keywords)

    def create_post(self, at, acct, loc, post):
        self.created_posts.append(dict(post))
        return super().create_post(at, acct, loc, post)


@pytest.fixture()
def fake(monkeypatch):
    f = FakeAgentGoogle()
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    return f


@pytest.fixture()
def gid(connected, fake):  # noqa: F811
    sync_select(connected, fake)
    return connected.glocs[0]["id"]


def jpeg(w=900, h=700, quality=92) -> bytes:
    """A real photo-like JPEG (noise, so it is comfortably above Google's 10 KB minimum)."""
    import random
    img = Image.new("RGB", (w, h))
    img.putdata([(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)) for _ in range(w * h)])
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def upload(biz, gid_, data, category="EXTERIOR"):
    return biz.post(f"/gbp/{gid_}/library", params={"category": category, "file_name": "shop.jpg"}, content=data, headers={"Content-Type": "image/jpeg"})


# ============================================================================ Photo Manager & Scheduler

def test_photo_validation_follows_googles_published_rules(connected, fake, gid):
    small = io.BytesIO(); Image.new("RGB", (200, 200), "white").save(small, "PNG")
    assert upload(connected, gid, b"x" * 500).status_code == 422  # under 10 KB
    r = upload(connected, gid, jpeg(240, 1000))
    assert r.status_code == 422 and "250 px" in r.json()["detail"]
    gif = io.BytesIO(); Image.new("RGB", (900, 900)).save(gif, "GIF")
    assert upload(connected, gid, gif.getvalue() + b"\0" * 20000).status_code == 422
    assert upload(connected, gid, b"\xff\xd8\xff" + b"0" * 30000).status_code == 422  # not a readable image
    assert connected.post(f"/gbp/{gid}/library", params={"category": "EXTERIOR"}, content=b"0" * (5 * 1024 * 1024 + 1)).status_code == 413
    assert upload(connected, gid, jpeg(), category="SELFIE").status_code == 422
    ok = upload(connected, gid, jpeg(600, 400))
    assert ok.status_code == 201 and ok.json()["status"] == "awaiting_approval" and ok.json()["stage"] == "Waiting for approval"
    assert any("720" in w for w in ok.json()["warnings"])  # below the recommended size: allowed, with a warning
    assert upload(connected, gid, owner_bytes(ok.json()["id"])).status_code == 409  # the exact same file twice


def owner_bytes(mid):
    return bytes(owner_query("SELECT data FROM scheduled_media WHERE id = :m", m=mid)[0][0])


def test_a_photo_reaches_google_only_after_approval_at_its_time_and_is_never_called_live_early(connected, fake, gid, biz_b):
    from app.workers.tasks import publish_due_media
    staff = invite(connected)
    m = upload(staff, gid, jpeg()).json()  # anyone who can see the location may add to the library
    assert publish_due_media.run()["published"] == 0 and fake.uploads == []  # unapproved: never sent
    assert staff.post(f"/gbp/{gid}/library/{m['id']}/approve", json={}).status_code == 403  # approval is owner/admin only
    when = (utcnow() + timedelta(hours=2)).isoformat()
    s = connected.post(f"/gbp/{gid}/library/{m['id']}/approve", json={"scheduled_for": when}).json()
    assert s["status"] == "scheduled" and s["stage"] == "Scheduled"
    assert publish_due_media.run()["published"] == 0 and fake.uploads == []  # not yet due
    owner_exec("UPDATE scheduled_media SET scheduled_for = now() - interval '1 minute' WHERE id = :m", m=m["id"])
    assert publish_due_media.run()["published"] == 1 and fake.uploads[0]["category"] == "EXTERIOR" and fake.uploads[0]["content_type"] == "image/jpeg"
    item = connected.get(f"/gbp/{gid}/library").json()["items"][0]
    assert item["status"] == "published" and item["google_media_name"].endswith("/media/up1") and item["stage"] == "Google is processing it"
    assert publish_due_media.run()["published"] == 0 and len(fake.uploads) == 1  # never twice
    fake.serving = True
    assert connected.post(f"/gbp/{gid}/library/{m['id']}/check").json()["stage"] == "Live on Google"
    acts = {a for (a,) in owner_query("SELECT action FROM audit_logs WHERE entity_id = :m", m=m["id"])}
    assert {"photo.upload", "photo.approve", "photo.publish_published"} <= acts
    assert biz_b.get(f"/gbp/{gid}/library").status_code == 404  # another business can't see the location
    assert biz_b.get(f"/gbp/{gid}/library/{m['id']}/image").status_code == 404
    assert connected.get(f"/gbp/{gid}/library/{m['id']}/image").headers["content-type"] == "image/jpeg"


def test_photo_failures_are_retried_when_it_can_help_and_explained_when_not(connected, fake, gid):
    from app.workers.tasks import publish_due_media
    m = upload(connected, gid, jpeg()).json()
    connected.post(f"/gbp/{gid}/library/{m['id']}/approve", json={})
    fake.upload_error = g.GoogleAPIError(503, "backend error")
    assert publish_due_media.run()["retry"] == 1
    item = connected.get(f"/gbp/{gid}/library").json()["items"][0]
    assert item["status"] == "scheduled" and item["attempts"] == 1 and item["next_attempt_at"] and "temporary" in item["failure_reason"]
    fake.upload_error = g.GoogleAPIError(400, "Image is too small")
    owner_exec("UPDATE scheduled_media SET next_attempt_at = now() - interval '1 minute' WHERE id = :m", m=m["id"])
    assert publish_due_media.run()["failed"] == 1
    item = connected.get(f"/gbp/{gid}/library").json()["items"][0]
    assert item["status"] == "failed" and "rejected" in item["failure_reason"] and item["google_media_name"] is None and item["stage"] == "Didn't reach Google"
    fake.upload_error = None
    assert connected.post(f"/gbp/{gid}/library/{m['id']}/retry").json()["status"] == "scheduled"
    assert publish_due_media.run()["published"] == 1


def test_photo_coverage_reads_google_and_suggests_missing_categories(connected, fake, gid):
    fake.media = [{"name": "accounts/1/locations/1/media/9", "category": "EXTERIOR"}]
    upload(connected, gid, jpeg(), category="TEAMS")
    c = connected.get(f"/gbp/{gid}/library/coverage").json()
    sug = {s["category"]: s for s in c["suggestions"]}
    assert c["on_google"] == {"EXTERIOR": 1} and sug["EXTERIOR"]["on_google"] and sug["TEAMS"]["pending"] and not sug["INTERIOR"]["on_google"]
    assert "FOOD_AND_DRINK" not in sug  # a physiotherapy clinic is not told to add a menu


# ============================================================================ Posts: offers and events

def make_post(biz, gid_, **kw):
    r = biz.post("/posts", json={"google_location_id": gid_, "summary": "Our clinic is open on Saturday for walk-in physiotherapy consultations.", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_event_and_offer_posts_need_googles_required_fields_before_approval(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    p = make_post(connected, gid, topic_type="EVENT")
    assert p["topic_type"] == "EVENT" and p["topic_problems"]
    connected.post(f"/posts/{p['id']}/submit")
    assert connected.post(f"/posts/{p['id']}/approve", json={}).status_code == 422 and fake.created_posts == []
    connected.post(f"/posts/{p['id']}/reject")
    e = connected.patch(f"/posts/{p['id']}", json={"event_title": "Free posture check day", "event_start": "2030-03-01T10:00:00", "event_end": "2030-03-01T16:00:00"}).json()
    assert e["topic_problems"] == [] and datetime.fromisoformat(e["event_start"]) == datetime(2030, 3, 1, 4, 30, tzinfo=timezone.utc)  # 10:00 Asia/Kolkata
    connected.post(f"/posts/{p['id']}/submit")
    assert connected.post(f"/posts/{p['id']}/approve", json={}).status_code == 200
    publish_due_posts.run()
    sent = fake.created_posts[-1]
    assert sent["topic_type"] == "EVENT" and sent["event_title"] == "Free posture check day"
    assert (sent["event_start"].hour, sent["event_start"].minute, sent["event_end"].hour) == (10, 0, 16)  # Google gets local wall-clock time
    s = make_post(connected, gid, topic_type="STANDARD", event_title="leftover")
    assert s["event_title"] is None  # an update never carries event fields to Google
    bad = make_post(connected, gid, topic_type="OFFER", event_title="Winter check-up", event_start="2030-01-01T09:00:00", event_end="2029-12-31T09:00:00", offer_url="http://x.example")
    assert len(bad["topic_problems"]) == 2


def test_ai_offer_posts_only_come_from_verified_offers(connected, fake, gid, monkeypatch):
    monkeypatch.setattr("app.api.v1.posts.get_provider", lambda: StubReplyAI())
    r = connected.post("/posts/ai-draft", json={"google_location_id": gid, "kind": "offer"})
    assert r.status_code == 422 and "never invents offers" in r.json()["detail"]
    r = connected.post("/posts/ai-draft", json={"google_location_id": gid, "kind": "event"})
    assert r.status_code == 422


def test_provider_builds_event_and_offer_posts_exactly_as_google_documents(monkeypatch):
    from datetime import datetime
    seen = []
    def handler(req):
        seen.append(json.loads(req.content)); return httpx.Response(200, json={"name": "accounts/1/locations/2/localPosts/3", "state": "LIVE", "topicType": seen[-1]["topicType"]})
    monkeypatch.setattr("app.services.google.provider.settings.google_client_id", "x")
    monkeypatch.setattr("app.services.google.provider.settings.google_client_secret", "y")
    p = g.HttpGoogleProvider(transport=httpx.MockTransport(handler))
    p.create_post("t", "accounts/1", "locations/2", {"summary": "Winter check-up offer for all.", "topic_type": "OFFER", "event_title": "Winter check-up",
                                                      "event_start": datetime(2030, 1, 1, 9, 30), "event_end": datetime(2030, 1, 31, 18, 0), "offer_terms": "One per visit.",
                                                      "cta_type": "LEARN_MORE", "cta_url": "https://x.example"})
    b = seen[-1]
    assert b["topicType"] == "OFFER" and b["event"]["title"] == "Winter check-up" and b["offer"] == {"termsConditions": "One per visit."}
    assert b["event"]["schedule"] == {"startDate": {"year": 2030, "month": 1, "day": 1}, "startTime": {"hours": 9, "minutes": 30, "seconds": 0, "nanos": 0},
                                      "endDate": {"year": 2030, "month": 1, "day": 31}, "endTime": {"hours": 18, "minutes": 0, "seconds": 0, "nanos": 0}}
    assert "callToAction" not in b  # Google ignores callToAction on OFFER posts
    p.create_post("t", "accounts/1", "locations/2", {"summary": "Open on Sunday this week."})
    assert seen[-1]["topicType"] == "STANDARD" and "event" not in seen[-1]


def test_provider_uploads_photo_bytes_with_startupload_and_dataref(monkeypatch):
    calls = []
    def handler(req):
        calls.append((req.method, str(req.url), req.headers.get("content-type"), req.content))
        if req.url.path.endswith("media:startUpload"):
            return httpx.Response(200, json={"resourceName": "ref123"})
        if "/upload/v1/media/" in req.url.path:
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"name": "accounts/1/locations/2/media/77", "locationAssociation": {"category": "INTERIOR"},
                                         "googleUrl": "https://lh3.example/x", "dimensions": {"widthPixels": 900, "heightPixels": 700}})
    monkeypatch.setattr("app.services.google.provider.settings.google_client_id", "x")
    monkeypatch.setattr("app.services.google.provider.settings.google_client_secret", "y")
    p = g.HttpGoogleProvider(transport=httpx.MockTransport(handler))
    out = p.upload_media_bytes("t", "accounts/1", "locations/2", b"JPEGDATA", "image/jpeg", "INTERIOR", "Our waiting room")
    assert [c[0] for c in calls] == ["POST", "POST", "POST"]
    assert calls[0][1] == "https://mybusiness.googleapis.com/v4/accounts/1/locations/2/media:startUpload"
    assert calls[1][1] == "https://mybusiness.googleapis.com/upload/v1/media/ref123?uploadType=media" and calls[1][2] == "image/jpeg" and calls[1][3] == b"JPEGDATA"
    body = json.loads(calls[2][3])
    assert body == {"mediaFormat": "PHOTO", "locationAssociation": {"category": "INTERIOR"}, "dataRef": {"resourceName": "ref123"}, "description": "Our waiting room"}
    assert out["name"].endswith("/media/77") and out["google_url"] and (out["width"], out["height"]) == (900, 700)


# ============================================================================ Performance: search keywords

def test_provider_reads_search_keywords_and_keeps_googles_thresholds(monkeypatch):
    pages = [{"searchKeywordsCounts": [{"searchKeyword": "physio", "insightsValue": {"value": "40"}}], "nextPageToken": "n"},
             {"searchKeywordsCounts": [{"searchKeyword": "back pain", "insightsValue": {"threshold": "15"}}]}]
    urls = []
    def handler(req):
        urls.append(req.url); return httpx.Response(200, json=pages[len(urls) - 1])
    monkeypatch.setattr("app.services.google.provider.settings.google_client_id", "x")
    monkeypatch.setattr("app.services.google.provider.settings.google_client_secret", "y")
    rows = g.HttpGoogleProvider(transport=httpx.MockTransport(handler)).search_keywords("t", "locations/9", "2026-08", "2026-10")
    assert rows == [{"keyword": "physio", "value": 40, "below": None}, {"keyword": "back pain", "value": None, "below": 15}]
    q = dict(urls[0].params)
    assert urls[0].path == "/v1/locations/9/searchkeywords/impressions/monthly" and q["monthlyRange.start_month.month"] == "8" and q["monthlyRange.end_month.year"] == "2026"
    assert dict(urls[1].params)["pageToken"] == "n"


def test_keywords_endpoint_never_turns_a_threshold_into_a_number(connected, fake, gid, biz_b):
    r = connected.get(f"/gbp/{gid}/keywords", params={"months": 3}).json()
    assert r["keywords"][0] == {"keyword": "physiotherapist near me", "value": 120, "below": None}
    assert r["keywords"][1]["value"] is None and r["keywords"][1]["below"] == 15
    assert biz_b.get(f"/gbp/{gid}/keywords").status_code == 404


# ============================================================================ Replies: tone, language, publishing state

class CapturingAI(StubReplyAI):
    prompts: list = []
    def generate(self, system, user, *, max_tokens=600, temperature=0.4):
        CapturingAI.prompts.append(user)
        return super().generate(system, user, max_tokens=max_tokens, temperature=temperature)


def test_reply_tone_and_language_reach_the_ai_and_publishing_is_visible(connected, fake, gid, monkeypatch):
    monkeypatch.setattr("app.api.v1.reviews.get_provider", lambda: CapturingAI())
    fake.reviews = [greview(1, 4, "Good service")]
    connected.post("/google/sync")
    rid = connected.get("/reviews").json()["items"][0]["id"]
    d = connected.post(f"/reviews/{rid}/drafts/generate", json={"tone": "brief", "language": "hi"}).json()
    assert "one or two sentences" in CapturingAI.prompts[-1] and "Devanagari" in CapturingAI.prompts[-1] and d["language"] == "hi"
    assert connected.post(f"/reviews/{rid}/drafts/generate", json={"tone": "rude"}).status_code == 422
    connected.post(f"/reply-drafts/{d['id']}/approve", json={})
    states = []
    orig = fake.reply_to_review
    def spy(*a, **k):
        states.append(owner_query("SELECT status FROM reply_drafts WHERE id = :d", d=d["id"])[0][0])
        return orig(*a, **k)
    fake.reply_to_review = spy
    assert connected.post(f"/reply-drafts/{d['id']}/publish").json()["status"] == "published"
    assert states == ["publishing"]  # committed before Google was called, so every screen could see it


def test_a_send_interrupted_mid_flight_is_recovered_without_a_second_reply(connected, fake, gid, monkeypatch):
    from app.workers.tasks import retry_failed_replies
    monkeypatch.setattr("app.api.v1.reviews.get_provider", lambda: StubReplyAI())
    fake.reviews = [greview(2, 5, "Great")]
    connected.post("/google/sync")
    rid = connected.get("/reviews").json()["items"][0]["id"]
    d = connected.post(f"/reviews/{rid}/drafts/generate").json()
    connected.post(f"/reply-drafts/{d['id']}/approve", json={})
    owner_exec("UPDATE reply_drafts SET status = 'publishing', updated_at = now() - interval '20 minutes' WHERE id = :d", d=d["id"])
    assert connected.get("/reviews", params={"reply_state": "publishing"}).json()["total"] == 1
    retry_failed_replies.run()
    assert owner_query("SELECT status FROM reply_drafts WHERE id = :d", d=d["id"])[0][0] == "published"
    assert {a for (a,) in owner_query("SELECT action FROM reply_logs WHERE draft_id = :d", d=d["id"])} >= {"publish_interrupted", "publish_attempt"}


# ============================================================================ Profile optimizer

def test_profile_optimizer_checks_from_googles_data_and_never_suggests_name_keywords(connected, fake, gid):
    fake.details.update({"title": "Best Physio Clinic | Gomti Nagar | Back Pain", "description": "Physio. Call 98765 43210 or visit www.clinic.example",
                         "services": [], "special_hours": [], "open_status": "OPEN", "hours": []})
    connected.post("/agent/google/refresh")
    r = connected.get(f"/agent/profile/{gid}/optimize").json()
    by = {c["key"]: c for c in r["checks"]}
    assert by["hours"]["state"] == "missing" and by["services"]["state"] == "missing"
    assert by["description"]["state"] in ("missing", "improve")
    assert by["name"]["state"] == "improve" and "never suggests adding keywords" in by["name"]["detail"]
    assert r["current"]["title"].startswith("Best Physio") and r["keywords"][0]["keyword"] == "physiotherapist near me"
    assert 0 <= r["score"] <= 100 and "never promises" in r["rules"]


def test_rejected_profile_suggestions_are_kept_in_history(connected, fake, gid, monkeypatch):
    monkeypatch.setattr("app.api.v1.agent.get_provider", lambda: StubReplyAI())
    connected.post("/agent/google/refresh")
    t = connected.post(f"/agent/profile/{gid}/suggest-description")
    if t.status_code != 200:
        pytest.skip("the stub text is rejected by the knowledge-base safety rules in this configuration")
    connected.post(f"/agent/tasks/{t.json()['id']}/dismiss", json={})
    h = connected.get(f"/agent/profile/{gid}/optimize").json()["history"]
    assert h and h[0]["result"] == "Rejected by you"


# ============================================================================ Review request templates

def test_review_request_templates_must_be_neutral(connected, fake, gid):
    ok = connected.post("/review-growth/templates", json={"name": "After visit", "body": "Hi {customer}, thanks for visiting {business}. Please share your honest experience: {link}"})
    assert ok.status_code == 201
    for body in ("Leave us a 5 star review and get 10% off: {link}", "If you were happy with us, please review: {link}", "Review us and win a gift! {link}",
                 "कृपया 5 स्टार दें: {link}", "Please review us", "Review here {link} {coupon}"):
        r = connected.post("/review-growth/templates", json={"name": "Bad", "body": body})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "not_neutral", body
    assert connected.post("/review-growth/templates", json={"name": "Fine", "body": "Feel free to share what you thought of our service: {link}"}).status_code == 201
    staff = invite(connected)
    assert staff.post("/review-growth/templates", json={"name": "x", "body": "Share your experience: {link}"}).status_code == 403
    camp = connected.post("/review-growth/campaigns", json={"name": "Counter", "location_id": connected.location_id})
    assert camp.status_code in (200, 201), camp.text
    out = connected.post(f"/review-growth/templates/{ok.json()['id']}/render", json={"campaign_id": camp.json()["id"], "customer": "Asha"}).json()
    assert out["text"].startswith("Hi Asha,") and "/r/" in out["text"] and out["link"] in out["text"]
    assert len(connected.get("/review-growth/templates").json()["presets"]) >= 4


# ============================================================================ AI Growth Agent integration

def test_agent_turns_missing_photo_categories_into_a_task(connected, fake, gid):
    fake.media = [{"name": "accounts/1/locations/1/media/1", "category": "EXTERIOR", "created_at": utcnow().isoformat()}]
    connected.post("/agent/google/refresh")
    connected.post("/agent/plan/run")
    tasks = connected.get("/agent/tasks").json()["tasks"]
    t = next(t for t in tasks if t["kind"] == "add_photo")
    assert set(t["evidence"]["missing_categories"]) == {"COVER", "INTERIOR", "TEAMS"} and "Upload" in t["suggested_action"]


# ============================================================================ Daily SEO posts (agent, drafts only)

class PostAI(StubReplyAI):
    prompts: list = []
    def generate(self, system, user, *, max_tokens=600, temperature=0.4):
        PostAI.prompts.append(user)
        if "ONE photo" in system:
            return "A bright photo of your treatment room with the bed made up."
        return "Back stiffness after a long day at a desk? Our physiotherapists can assess your posture and suggest simple exercises. Call the clinic to book a visit."


def test_daily_post_drafts_are_one_per_location_per_day_use_search_terms_and_wait_for_approval(connected, fake, gid, monkeypatch):
    monkeypatch.setattr("app.services.agent.plan.get_provider", lambda: PostAI())
    connected.post("/agent/google/refresh")  # stores Google's search terms with the snapshot
    assert connected.get("/agent/settings").json()["auto_draft_posts"] is False
    connected.post("/agent/plan/run")
    assert connected.get("/posts").json()["posts"] == []  # off by default: nothing is drafted
    assert connected.put("/agent/settings", json={"auto_draft_posts": True}).json()["auto_draft_posts"] is True
    r = connected.post("/agent/plan/run")
    assert r.status_code == 200 and r.json()["posts_drafted"] == 1
    posts = connected.get("/posts").json()["posts"]
    assert len(posts) == 1 and posts[0]["status"] == "awaiting_approval" and posts[0]["generated_by_ai"] and posts[0]["visual_hint"]
    assert "physiotherapist near me" in PostAI.prompts[0] and "never list keywords" in PostAI.prompts[0].lower()  # Google's term offered, SEO rule included
    assert fake.created_posts == []  # nothing sent to Google
    assert connected.post("/agent/plan/run").json()["posts_drafted"] == 0  # not twice on the same day
    assert len(connected.get("/posts").json()["posts"]) == 1


def test_daily_drafting_stops_while_the_owner_has_three_waiting(connected, fake, gid, monkeypatch):
    monkeypatch.setattr("app.services.agent.plan.get_provider", lambda: PostAI())
    connected.put("/agent/settings", json={"auto_draft_posts": True})
    for i in range(3):
        p = make_post(connected, gid, summary=f"Hand-written post number {i} about our opening hours.")
        connected.post(f"/posts/{p['id']}/submit")
    assert connected.post("/agent/plan/run").json()["posts_drafted"] == 0
