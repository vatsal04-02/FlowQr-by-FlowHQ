"""One AI round shows a customer 2-3 genuinely different suggestions to start from (never one fixed paragraph, never auto-submitted). Each is written by the existing engine, so each passes the same
grounding checks as a single draft: no invented events, numbers, names or qualities. The AI is a labelled test double; routes, guardrails and the database are real."""
import pytest

from app.core.config import settings
from app.services.ai.review_generate import STRUCTURE_HINTS, STYLE_GUIDE, VARIATION_HINTS, VARIATION_POSITIVE
from tests.conftest import owner_query
from tests.test_review_growth import campaign, llm, pub  # noqa: F401

# Six genuinely different reviews of the same visit (staff, rated 5). Each uses only the describing words the Staff keyword allows.
A = "The staff were friendly and polite."
B = "I found the staff professional and attentive."
C = "I appreciated how courteous the staff were with me."
D = "The team was polite and professional with me."
E = "Attentive staff who were also friendly."
F = "The staff were courteous, and I appreciated that."


@pytest.fixture(autouse=True)
def three_per_round(monkeypatch):
    monkeypatch.setattr(settings, "review_suggestions_per_round", 3)  # production default (the older suite runs with 1)
    monkeypatch.setattr(settings, "review_max_ai_writes_per_session", 2)


def topic_of(client, c):
    return pub(client, "GET", c["public_id"]).json()["suggestions"][0]["id"]


def gen(client, c, topic=None, **extra):
    return pub(client, "POST", c["public_id"], "/generate", json={"mode": "ai", "rating": 5, "suggestions": [topic or topic_of(client, c)], "language": "en", **extra})


def test_one_round_shows_three_different_suggestions_each_written_in_its_own_style_and_shape(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [A, B, C]
    r = gen(client, c).json()
    assert r["ai_status"] == "ok" and r["suggestions"] == [A, B, C] and r["draft"] == A  # "draft" is still the first one, for older clients
    assert len(llm.calls) == 3
    prompts = [u for _, u in llm.calls]
    styles = [next(name for name, guide in STYLE_GUIDE.items() if f"Style: {guide}" in p) for p in prompts]
    assert len(set(styles)) == 3  # three different tones and lengths
    used = [tuple(h for h in (*VARIATION_HINTS, *VARIATION_POSITIVE, *STRUCTURE_HINTS) if h in p) for p in prompts]
    assert len(set(used)) == 3  # and no two are told to open and build their sentences the same way
    assert f"<earlier_draft>{A}</earlier_draft>" in prompts[1] and f"<earlier_draft>{B}</earlier_draft>" in prompts[2]  # each knows what the others already say


def test_a_suggestion_that_would_invent_something_never_reaches_the_customer(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [A, "The staff were friendly and I waited 20 minutes for the doctor.", "The staff were friendly and I waited 20 minutes for the doctor.", B]
    r = gen(client, c).json()
    assert r["ai_status"] == "ok" and r["suggestions"] == [A, B]  # the invented wait and number were refused by the same checks as before; the customer just sees two
    assert all("20" not in s and "waited" not in s for s in r["suggestions"])


def test_extra_suggestions_that_cannot_be_written_faithfully_never_turn_into_an_error(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [A]  # every further call repeats A, which is refused as a copy
    r = gen(client, c).json()
    assert r["ai_status"] == "ok" and r["suggestions"] == [A] and r["draft"] == A  # one good suggestion is a normal result


def test_a_round_counts_as_one_ai_version_and_a_new_round_never_repeats_the_first(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [A, B, C, D, E, F]
    first = gen(client, c).json()
    assert first["suggestions"] == [A, B, C] and first["remaining_drafts"] == 1  # three suggestions, ONE of the visit's two rounds
    sid = first["session_id"]
    second = pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": sid}).json()
    assert second["ai_status"] == "ok" and second["suggestions"] == [D, E, F] and second["remaining_drafts"] == 0
    assert not set(first["suggestions"]) & set(second["suggestions"])
    assert pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": sid}).status_code == 429  # the visit's allowance is unchanged: two rounds


def test_one_per_round_is_exactly_the_old_single_draft(biz_a, client, llm, monkeypatch):
    monkeypatch.setattr(settings, "review_suggestions_per_round", 1)
    c = campaign(biz_a)
    llm.texts = [A, B, C]
    r = gen(client, c).json()
    assert r["suggestions"] == [A] and len(llm.calls) == 1


def test_other_customers_suggestions_are_shown_to_the_writer_so_the_business_does_not_repeat_itself(biz_a, client, llm):
    c = campaign(biz_a)
    topic = topic_of(client, c)
    llm.texts = [A, B, C]
    gen(client, c, topic)
    llm.calls.clear()
    llm.texts = [D, E, F]
    r = gen(client, c, topic).json()
    assert r["suggestions"] == [D, E, F]
    first_prompt = llm.calls[0][1]
    assert all(f"<other_review>{x}</other_review>" in first_prompt for x in (A, B, C))  # all three the previous customer saw, not just the first


def test_another_business_never_supplies_examples_or_context(biz_a, biz_b, client, llm):
    ca, cb = campaign(biz_a), campaign(biz_b)
    llm.texts = [A, B, C]
    gen(client, ca)
    llm.calls.clear()
    llm.texts = [D, E, F]
    r = gen(client, cb).json()
    assert r["suggestions"] == [D, E, F]
    assert not any("<other_review>" in u for _, u in llm.calls)
    assert not any(x in u for _, u in llm.calls for x in (A, B, C))  # the first business's suggestions never reach the second's writer


def test_nothing_is_submitted_or_approved_by_generating_suggestions(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [A, B, C]
    sid = gen(client, c).json()["session_id"]
    row = owner_query("SELECT final_content, approved_at FROM review_drafts d JOIN review_sessions s ON s.id = d.session_id WHERE s.session_identifier = :s", s=sid)[0]
    assert tuple(row) == (None, None)  # only the customer's own tap can confirm a review
    events = {e[0] for e in owner_query("SELECT event_type FROM review_events WHERE tenant_id = :t", t=biz_a.tenant_id)}
    assert not events & {"review_copied", "redirect_clicked", "review_submitted", "approved"}


def test_with_no_services_recorded_the_suggestions_still_come_from_the_standard_keywords(biz_a, client, llm):
    assert biz_a.put("/review-growth/context", json={"services": [], "description": ""}).status_code == 200  # nothing known about the business
    c = campaign(biz_a)
    llm.texts = [A, B, C]
    r = gen(client, c).json()
    assert r["ai_status"] == "ok" and len(r["suggestions"]) == 3
    assert "Services/products the business offers" not in llm.calls[0][1]  # nothing about the business is invented or assumed


def test_when_services_are_recorded_every_suggestion_is_written_with_that_knowledge(biz_a, client, llm):
    assert biz_a.put("/review-growth/context", json={"services": ["Back pain rehabilitation"], "description": "An exercise-based rehabilitation clinic."}).status_code == 200
    c = campaign(biz_a)
    topic = next(s["id"] for s in pub(client, "GET", c["public_id"]).json()["suggestions"] if s["id"] == "staff")
    llm.texts = [A, B, C]
    gen(client, c, topic)
    assert all("Back pain rehabilitation" in u and "An exercise-based rehabilitation clinic." in u for _, u in llm.calls)  # all three get the business's own context
    assert all("never evidence of what this customer received" in u for _, u in llm.calls)  # and are told it is background, not what the customer experienced
