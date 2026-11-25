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


# ---------------------------------------------------------------------------------------------------------------- a named business can be given more, for testing
TEN = [  # ten genuinely different reviews, so the app's own "no repeats" rule is not what stops the test
    "I came in for back pain physiotherapy and the doctor listened carefully to me. The reception staff were friendly as well.",
    "Friendly reception, and a doctor who really listened. I went for back pain physiotherapy.",
    "Visited with a stiff back; physiotherapy helped and the doctor took time to hear me out. Welcoming front desk too.",
    "Warm welcome at reception, a patient doctor, and real relief from my back pain after physiotherapy sessions here.",
    "My back pain was explained clearly by a doctor who listened. The physiotherapy plan made sense and the staff were kind.",
    "Kind people at the desk, careful listening from the doctor, and useful physiotherapy for my aching back.",
    "Booked physiotherapy for back trouble. Reception was courteous and the doctor never rushed me, which I appreciated.",
    "A calm clinic where the doctor heard my whole story about back pain before starting physiotherapy. Staff were pleasant.",
    "Good physiotherapy for my back; the doctor paid attention, and the girls at reception were lovely and helpful.",
    "Back pain finally eased. The doctor listened without hurry, physiotherapy was well explained, reception was friendly.",
]


def test_a_business_named_in_the_override_setting_gets_more_versions_and_others_do_not(biz_a, biz_b, client, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_data_terms_verified", True)
    seq = {"i": 0}

    class Ten:
        name, model, usage = "ten", "m", None

        def generate(self, *a, **k):
            seq["i"] += 1
            return TEN[(seq["i"] - 1) % len(TEN)]

    monkeypatch.setattr("app.api.v1.review_public.get_provider", lambda: Ten())
    monkeypatch.setattr("app.services.ai.review_generate.validate_draft", lambda *a, **k: None)  # this test is about the COUNT; the faithfulness checks have their own tests and would reject invented wording
    ca, cb = campaign(biz_a), campaign(biz_b)
    monkeypatch.setattr(settings, "review_ai_writes_overrides", f"{biz_a.tenant_id}:10")
    page = pub(client, "GET", ca["public_id"]).json()
    assert page["generator"]["max_drafts"] == 10  # the page is told this business's allowance
    assert pub(client, "GET", cb["public_id"]).json()["generator"]["max_drafts"] == 2  # another business is untouched
    first = generate(client, ca).json()
    assert first["ai_status"] == "ok" and first["remaining_drafts"] == 9
    sid = first["session_id"]
    left = 9
    for _ in range(9):  # drafts 2..10 (the old 5-draft limit does not stop a business with the allowance)
        r = pub(client, "POST", ca["public_id"], "/regenerate", json={"session_id": sid}).json()
        assert r["ai_status"] == "ok", (seq["i"], r.get("message"))
        left -= 1
        assert r["remaining_drafts"] == left
    assert pub(client, "POST", ca["public_id"], "/regenerate", json={"session_id": sid}).status_code == 429  # the 11th is refused
    seq["i"] = 0
    other = generate(client, cb).json()
    assert other["ai_status"] == "ok" and other["remaining_drafts"] == 1  # the other business still gets 2 in total


def test_bad_override_entries_are_ignored_and_the_ceiling_holds(monkeypatch):
    import uuid

    from app.services.review_limits import MAX_OVERRIDE, ai_write_limit, draft_limit
    t = uuid.uuid4()
    monkeypatch.setattr(settings, "review_ai_writes_overrides", f"nonsense, {t}:abc, {t}:0, {t}:{MAX_OVERRIDE + 1}, not-a-uuid:5")
    assert ai_write_limit(t) == 2 and draft_limit(t) == 5  # nothing valid: the defaults
    monkeypatch.setattr(settings, "review_ai_writes_overrides", f"{t}:{MAX_OVERRIDE}")
    assert ai_write_limit(t) == MAX_OVERRIDE and draft_limit(t) == MAX_OVERRIDE
    assert ai_write_limit(None) == 2 and ai_write_limit("garbage") == 2
