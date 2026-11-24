"""Star rating on the customer review page: required for an AI draft, optional for writing it yourself; it sets the direction of the review
(1-2 negative, 3 neutral/mixed, 4-5 positive) and is counted separately from Google ratings. Test doubles stand in for the model."""
import pytest

from tests.conftest import owner_query
from tests.test_review_growth import StubLLM, campaign, llm, pub  # noqa: F401  (llm = fixture)
from tests.test_review_context import biz  # noqa: F401

@pytest.fixture(autouse=True)
def _no_cross_customer_check(monkeypatch):
    """These tests hand every simulated customer the same scripted text. The "no two customers get the same review" rule has its own tests (tests/test_review_unique.py)."""
    monkeypatch.setattr("app.api.v1.review_public.recent_reviews", lambda *a, **k: ())



def go(client, c, **body):
    return pub(client, "POST", c["public_id"], "/generate", json={"language": "en", **body})


def physio():
    return biz("Physiotherapy clinic", "Rating Biz")


# ---------------------------------------------------------------- required for AI, optional for manual

def test_ai_draft_needs_a_rating_but_writing_yourself_does_not(client, llm):
    c = campaign(physio())
    r = go(client, c, suggestions=["staff"], mode="ai")
    assert r.status_code == 422 and "star rating" in r.text.lower() and llm.calls == []  # no AI call
    assert go(client, c, mode="manual").status_code == 200
    assert go(client, c, mode="manual", rating=2, text="my own words").status_code == 200
    for bad in (0, 6, "five"):
        assert go(client, c, suggestions=["staff"], rating=bad).status_code == 422


def test_a_rating_alone_never_produces_a_review(client, llm):
    c = campaign(physio())
    assert go(client, c, rating=5).status_code == 422 and llm.calls == []  # stars say how it was, not what happened


# ---------------------------------------------------------------- the rating sets the direction, all five values

DRAFTS = {
    1: "The treatment and the appointments were not good.", 2: "The treatment and the appointments were not good.",
    3: "The treatment and the appointments were okay.", 4: "I was happy with the treatment and the appointments.",
    5: "I was happy with the treatment and the appointments.",
}


@pytest.mark.parametrize("rating,sentiment,tone", [(1, "not_good", "1 star"), (2, "not_good", "2 stars"), (3, "okay", "neutral or mixed"), (4, "good", "positive"), (5, "good", "very positive")])
def test_each_rating_maps_to_a_direction_and_is_stored(client, llm, rating, sentiment, tone):
    llm.texts = [DRAFTS[rating]]
    c = campaign(physio())
    d = go(client, c, suggestions=["treatment", "appointment"], rating=rating).json()
    assert d["ai_status"] == "ok", d
    prompt = llm.calls[-1][1]
    assert f"rated their visit {rating} out of 5" in prompt and tone in prompt and "Never write the number" in prompt
    assert {"good": "GOOD", "okay": "OKAY", "not_good": "NOT GOOD"}[sentiment] in prompt
    assert owner_query("SELECT rating, customer_input->>'sentiment' FROM review_sessions ORDER BY created_at DESC LIMIT 1")[0] == (rating, sentiment)
    assert owner_query("SELECT rating FROM review_events WHERE event_type='feedback_submitted' ORDER BY created_at DESC LIMIT 1")[0][0] == rating


def test_a_draft_that_contradicts_the_rating_is_rejected(client, llm):
    c = campaign(physio())
    llm.texts = ["I was happy with the staff and the treatment."]  # praise on a 1-star rating
    assert go(client, c, suggestions=["staff", "treatment"], rating=1).json()["ai_status"] == "rejected"
    c2 = campaign(physio())
    llm.texts = ["The treatment was not good and the staff were not good either."]  # a complaint on a 5-star rating
    assert go(client, c2, suggestions=["staff", "treatment"], rating=5).json()["ai_status"] == "rejected"


def test_the_rating_never_becomes_a_reason(client, llm):
    """Stars say how it was, not why: an invented reason is rejected like any other invention."""
    c = campaign(physio())
    llm.texts = ["The appointments were not good because we waited a long time."]
    assert go(client, c, suggestions=["appointment"], rating=1).json()["ai_status"] == "rejected"


# ---------------------------------------------------------------- regeneration and editing keep the rating

def test_regenerating_keeps_the_rating(client, llm):
    llm.texts = ["The treatment was not good and I wasn't satisfied with how the appointments were handled. I would say both areas fell short.",
                "I wasn't happy with the appointments, and the treatment was not good either. Neither area was up to the mark for me."]
    c = campaign(physio())
    d = go(client, c, suggestions=["treatment", "appointment"], rating=2).json()
    again = pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": d["session_id"], "language": "en"}).json()
    assert again["ai_status"] == "ok" and again["draft"] != d["draft"]
    assert "rated their visit 2 out of 5" in llm.calls[-1][1]
    assert owner_query("SELECT rating FROM review_sessions ORDER BY created_at DESC LIMIT 1")[0][0] == 2


# ---------------------------------------------------------------- the Google link is never restricted by rating

@pytest.mark.parametrize("rating", [1, 2, 3, 4, 5])
def test_every_rating_reaches_the_google_link(client, llm, rating):
    llm.texts = [DRAFTS[rating]]
    c = campaign(physio())
    d = go(client, c, suggestions=["treatment", "appointment"], rating=rating).json()
    assert pub(client, "GET", c["public_id"]).json()["google_ready"] is True
    r = pub(client, "POST", c["public_id"], "/approve", json={"session_id": d["session_id"], "final_text": d["draft"]}).json()
    assert r["review_url"] == "https://g.page/r/CTX/review" and r["google_ready"] is True
    assert pub(client, "POST", c["public_id"], "/redirect", json={"session_id": d["session_id"]}).status_code == 200


# ---------------------------------------------------------------- analytics: separate from Google ratings

def test_rating_distribution_in_analytics_is_labelled_and_separate(client, llm):
    b = physio()
    c = campaign(b)
    for r in (1, 5, 5, 3):
        llm.texts = [DRAFTS[r]]
        assert go(client, c, suggestions=["treatment", "appointment"], rating=r).json()["ai_status"] == "ok"
    go(client, c, mode="manual", text="written myself")  # no rating
    a = b.get("/review-growth/analytics").json()["ratings"]
    assert a["distribution"] == {"1": 1, "2": 0, "3": 1, "4": 0, "5": 2} and a["rated"] == 4 and a["unrated"] == 1 and a["average"] == 3.5
    assert "Not your Google rating" in a["source"]
    assert "Google rating" in b.get("/review-growth/analytics").json()["definitions"]["ratings"]


def test_rating_distribution_survives_the_retention_purge(client, llm):
    """The customer's words are deleted after the retention period; the bare star count stays (like every other event)."""
    from app.services.review_growth import purge_expired
    from app.core.db import SessionLocal, set_rls_context

    b = physio()
    c = campaign(b)
    llm.texts = [DRAFTS[4]]
    go(client, c, suggestions=["treatment", "appointment"], rating=4)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert purge_expired(db, days=-1) >= 1
    db.close()
    assert b.get("/review-growth/analytics").json()["ratings"]["distribution"]["4"] == 1


def test_analytics_ratings_are_tenant_isolated(client, llm):
    a, other = physio(), biz("Restaurant", "Other Biz")
    llm.texts = [DRAFTS[5]]
    go(client, campaign(a), suggestions=["treatment", "appointment"], rating=5)
    assert other.get("/review-growth/analytics").json()["ratings"]["rated"] == 0
    assert a.get("/review-growth/analytics").json()["ratings"]["rated"] == 1


def test_migration_0010_is_additive_and_reversible(biz_a):
    import os
    import subprocess
    import sys

    backend = os.path.dirname(os.path.dirname(__file__))

    def alembic(*a):
        subprocess.run([sys.executable, "-m", "alembic", *a], check=True, env={**os.environ}, cwd=backend)

    def has():
        return bool(owner_query("SELECT 1 FROM information_schema.columns WHERE table_name='review_events' AND column_name='rating'"))

    assert has()
    alembic("downgrade", "0009")
    try:
        assert not has()
    finally:
        alembic("upgrade", "head")
    assert has()
    assert owner_query("SELECT 1 FROM pg_constraint WHERE conname='ck_review_events_rating'")  # out-of-range ratings are refused by the database itself
