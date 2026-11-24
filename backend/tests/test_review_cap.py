"""One customer visit gets at most 2 AI-written versions of their review, however they ask (first write, "New version", or a rewrite after changing picks). The AI is a labelled
test double; routes, counting and the database are real."""
import pytest

from app.core.config import settings
from app.services.ai.base import AIUnavailable
from tests.test_review_growth import GOOD, campaign, generate, llm, pub  # noqa: F401


@pytest.fixture(autouse=True)
def two_writes(monkeypatch):
    monkeypatch.setattr(settings, "review_max_ai_writes_per_session", 2)  # the production default (the rest of the suite runs with a much higher one)


def topic_of(client, c):
    return pub(client, "GET", c["public_id"]).json()["suggestions"][0]["id"]


def test_a_customer_gets_two_ai_versions_and_a_third_request_is_refused_before_the_ai_is_called(biz_a, client, llm):
    c = campaign(biz_a)
    page = pub(client, "GET", c["public_id"]).json()
    assert page["generator"]["max_drafts"] == 2  # the page is told the allowance
    first = generate(client, c).json()
    assert first["ai_status"] == "ok" and first["remaining_drafts"] == 1
    sid = first["session_id"]
    second = pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": sid}).json()
    assert second["ai_status"] == "ok" and second["remaining_drafts"] == 0 and second["draft"] != first["draft"]
    calls = len(llm.calls)
    r = pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": sid})
    assert r.status_code == 429 and "AI-written versions" in r.json()["detail"]
    r = pub(client, "POST", c["public_id"], "/refine", json={"session_id": sid, "rating": 4, "suggestions": [topic_of(client, c)], "text": "", "language": "en"})
    assert r.status_code == 429  # changing picks cannot get around it either
    assert len(llm.calls) == calls  # and no AI call (no cost) was made for either refusal


def test_changing_picks_counts_toward_the_same_two(biz_a, client, llm):
    c = campaign(biz_a)
    sid = generate(client, c).json()["session_id"]  # write 1
    topic = topic_of(client, c)
    r = pub(client, "POST", c["public_id"], "/refine", json={"session_id": sid, "rating": 5, "suggestions": [topic], "text": "", "language": "en"})  # write 2
    assert r.status_code == 200, r.text
    assert pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": sid}).status_code == 429


def test_every_customer_visit_has_its_own_two(biz_a, client, llm):
    c = campaign(biz_a)
    for _ in range(3):  # three different customers
        first = generate(client, c).json()
        assert first["ai_status"] == "ok" and first["remaining_drafts"] == 1


def test_a_failed_write_does_not_use_up_the_allowance(biz_a, client, monkeypatch):
    c = campaign(biz_a)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_data_terms_verified", True)
    state = {"n": 0}

    class Flaky:
        name, model, usage = "flaky", "m", None

        def generate(self, *a, **k):
            state["n"] += 1
            if state["n"] <= 1:  # only the very first call fails
                raise AIUnavailable("provider down", code="provider_error")
            return GOOD[0]

    monkeypatch.setattr("app.api.v1.review_public.get_provider", lambda: Flaky())
    down = generate(client, c).json()
    assert down["ai_status"] == "unavailable" and down["remaining_drafts"] == 2  # nothing was written, so nothing was used
    sid = down["session_id"]
    ok = pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": sid}).json()
    assert ok["ai_status"] == "ok" and ok["remaining_drafts"] == 1
