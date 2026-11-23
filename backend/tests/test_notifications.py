"""Dashboard redesign backend (PRD §6.5, §9): the bell, email notification preferences, command-palette search, the monthly review goal
and the brand-voice sample. All read existing data; all stay inside the tenant."""
from app.services import mailer
from tests.conftest import make_business
from tests.test_google_and_reviews import FakeGoogleProvider, StubReplyAI, greview, sync_select, connected, fake  # noqa: F401


def test_bell_lists_new_and_flagged_reviews_and_marks_them_read(connected, fake, biz_b):  # noqa: F811
    fake.reviews = [greview(1, 5, "Lovely staff"), greview(2, 1, "I will take you to court over this")]
    sync_select(connected, fake)

    data = connected.get("/notifications").json()
    kinds = {i["kind"] for i in data["items"]}
    assert {"new_review", "flagged_review"} <= kinds
    assert data["unread"] == len(data["items"]) >= 2
    flagged = next(i for i in data["items"] if i["kind"] == "flagged_review")
    assert flagged["href"].startswith("/gbp/reviews/") and flagged["tone"] == "warn"

    assert connected.post("/notifications/seen").status_code == 200
    assert connected.get("/notifications").json()["unread"] == 0
    # another business sees none of it
    assert biz_b.get("/notifications").json()["items"] == []


def test_email_digest_follows_preferences_and_never_mails_the_past(connected, fake):  # noqa: F811
    from app.workers.tasks import notify_by_email

    fake.reviews = [greview(1, 5, "Lovely staff")]
    sync_select(connected, fake)
    mailer.OUTBOX.clear()
    notify_by_email()  # first run only starts the watermark
    assert not [m for m in mailer.OUTBOX if m["to"] == connected.email]

    prefs = connected.get("/notifications/preferences").json()
    assert prefs["email_new_review"] is False and prefs["email_flagged_review"] is True and prefs["email"] == connected.email
    fake.reviews = [greview(1, 5, "Lovely staff"), greview(2, 1, "I will take you to court"), greview(3, 4, "Good")]
    assert connected.post("/google/sync").status_code == 200

    notify_by_email()
    mine = [m for m in mailer.OUTBOX if m["to"] == connected.email]
    assert len(mine) == 1, mine
    assert "needs you personally" in mine[0]["body"] and "New 4-star review" not in mine[0]["body"]  # plain reviews are off by default
    assert "/settings/notifications" in mine[0]["body"]
    notify_by_email()  # nothing new: nothing sent twice
    assert len([m for m in mailer.OUTBOX if m["to"] == connected.email]) == 1

    r = connected.put("/notifications/preferences", json={"email_new_review": True, "email_flagged_review": False, "email_sync_failed": True, "email_trial_ending": True})
    assert r.status_code == 200 and r.json()["email_new_review"] is True


def test_search_is_scoped_to_the_business(connected, fake, biz_b):  # noqa: F811
    fake.reviews = [greview(7, 5, "The physiotherapist was wonderful")]
    sync_select(connected, fake)
    hits = connected.get("/search", params={"q": "wonderful"}).json()
    assert len(hits["reviews"]) == 1 and hits["reviews"][0]["href"].startswith("/gbp/reviews/")
    assert connected.get("/search", params={"q": "Reviewer 7"}).json()["reviews"]
    assert biz_b.get("/search", params={"q": "wonderful"}).json() == {"reviews": [], "locations": [], "cards": []}
    assert connected.get("/search", params={"q": "a"}).status_code == 422


def test_monthly_review_goal_is_saved_and_validated():
    biz = make_business("Goal Clinic")
    assert biz.get("/tenant").json()["review_goal"] is None
    assert biz.patch("/tenant", json={"review_goal": 40}).json()["review_goal"] == 40
    assert biz.patch("/tenant", json={"review_goal": 0}).status_code == 422
    assert biz.patch("/tenant", json={"review_goal": None}).json()["review_goal"] is None


def test_voice_preview_uses_unsaved_text_and_saves_nothing(monkeypatch):
    biz = make_business("Voice Clinic")
    biz.patch("/tenant", json={"brand_tone": "formal"})
    monkeypatch.setattr("app.services.ai.get_provider", lambda: StubReplyAI())
    r = biz.post("/tenant/voice-preview", json={"rating": 5, "brand_tone": "cheerful", "ai_instructions": "Sign off as Team Voice"})
    assert r.status_code == 200, r.text
    assert r.json()["body"] and "review" in r.json()
    t = biz.get("/tenant").json()
    assert t["brand_tone"] == "formal" and t["ai_instructions"] is None  # the edited text was only used for the sample


def test_notification_email_has_a_working_unsubscribe_link(connected, fake):  # noqa: F811
    import re
    import uuid

    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import notifications as nsvc
    from app.workers.tasks import notify_by_email

    fake.reviews = [greview(1, 5, "Lovely staff")]
    sync_select(connected, fake)
    notify_by_email()  # starts the watermark
    fake.reviews = [greview(1, 5, "Lovely staff"), greview(2, 1, "I will take you to court")]
    assert connected.post("/google/sync").status_code == 200
    mailer.OUTBOX.clear()
    notify_by_email()
    mine = [m for m in mailer.OUTBOX if m["to"] == connected.email]
    assert len(mine) == 1
    token = re.search(r"/unsubscribe\?t=(\S+)", mine[0]["body"]).group(1)

    anon = TestClient(app)  # no session, no CSRF token: the signed link is the proof
    assert anon.post("/api/v1/notifications/unsubscribe", params={"t": token + "x"}).status_code == 400
    assert anon.post("/api/v1/notifications/unsubscribe", params={"t": "unsub:" + str(uuid.uuid4()) + ":" + str(uuid.uuid4())}).status_code == 400
    assert anon.post("/api/v1/notifications/unsubscribe", params={"t": token}).json() == {"unsubscribed": True}
    assert anon.post("/api/v1/notifications/unsubscribe", params={"t": token}).status_code == 200  # safe to repeat
    prefs = connected.get("/notifications/preferences").json()
    assert not any(prefs[k] for k in nsvc.DEFAULTS)

    mailer.OUTBOX.clear()
    fake.reviews = fake.reviews + [greview(3, 1, "my lawyer will sue")]
    assert connected.post("/google/sync").status_code == 200
    notify_by_email()
    assert not [m for m in mailer.OUTBOX if m["to"] == connected.email]


def test_unsubscribe_headers_are_one_click():
    import uuid

    from app.services import notifications as nsvc

    h = nsvc.unsubscribe_headers(uuid.uuid4(), uuid.uuid4(), "https://api.example.com/")
    assert h["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert h["List-Unsubscribe"].startswith("<https://api.example.com/api/v1/notifications/unsubscribe?t=unsub:")
