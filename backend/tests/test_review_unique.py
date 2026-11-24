"""Every review reads as its own. Two customers who tap the same stars and topics must not be handed the same paragraph, and the writer is told what other customers of the
location were recently given. The AI is a labelled test double; routes, guardrails and the database are real."""
import pytest

from app.services.ai.review_generate import CROSS_REVIEW_SIMILARITY, ReviewDraftRejected, ReviewInput, validate_draft
from tests.test_review_growth import campaign, llm, pub  # noqa: F401

A = "The staff were friendly and polite."
B = "I found the staff professional and attentive."
INP = ReviewInput(rating=5, topics=("Staff",), sentiment="good", topic_notes=("Staff: how the staff dealt with the customer.",), topic_ok=("friendly", "polite", "courteous", "professional", "attentive"))
KW = dict(language="en", style="natural", business_name="Acme Physio")


def test_a_draft_that_is_almost_another_customers_review_is_refused_and_a_different_one_passes():
    validate_draft(A, INP, **KW)  # fine on its own
    with pytest.raises(ReviewDraftRejected, match="another review"):
        validate_draft(A, INP, recent=(A,), **KW)
    with pytest.raises(ReviewDraftRejected, match="another review"):
        validate_draft(A.replace("polite", "courteous"), INP, recent=(A,), **KW)  # one swapped word is still the same paragraph
    validate_draft(B, INP, recent=(A,), **KW)  # genuinely different wording is accepted
    assert 0.5 < CROSS_REVIEW_SIMILARITY < 0.9


def gen(client, c, topic, rating=5):
    return pub(client, "POST", c["public_id"], "/generate", json={"mode": "ai", "rating": rating, "suggestions": [topic], "language": "en"})


def test_two_customers_with_the_same_picks_get_different_reviews_and_the_writer_sees_the_first(biz_a, client, llm):
    c = campaign(biz_a)
    topic = pub(client, "GET", c["public_id"]).json()["suggestions"][0]["id"]
    llm.texts = [A, A, B]  # the second customer's first attempt is a copy of the first customer's review
    first = gen(client, c, topic)
    assert first.status_code == 200 and first.json()["draft"] == A, first.text
    second = gen(client, c, topic)
    assert second.status_code == 200 and second.json()["ai_status"] == "ok", second.text
    assert second.json()["draft"] == B and second.json()["draft"] != first.json()["draft"]
    prompts = [u for _, u in llm.calls]
    assert "<other_review>" not in prompts[0]  # nobody before the first customer
    assert any(f"<other_review>{A}</other_review>" in p for p in prompts[1:])  # the second customer's writer was shown the first review as "do not repeat"
    assert "rejected" in prompts[-1] or "too similar" in prompts[-1]  # the retry says why


def test_a_draft_with_a_customers_own_typed_words_is_never_shown_to_another_customer(biz_a, client, llm):
    c = campaign(biz_a)
    topic = pub(client, "GET", c["public_id"]).json()["suggestions"][0]["id"]
    llm.texts = [A]
    mine = pub(client, "POST", c["public_id"], "/generate", json={"mode": "ai", "rating": 5, "suggestions": [topic], "text": "Dr Mehta was lovely, call me on 98xxxxxx12", "language": "en"})
    assert mine.status_code == 200
    llm.calls.clear()
    llm.texts = [B]
    gen(client, c, topic)
    assert not any("<other_review>" in u for _, u in llm.calls)  # that customer's text (and phone number) never reaches another customer's prompt


def test_another_business_never_supplies_examples(biz_a, biz_b, client, llm):
    ca, cb = campaign(biz_a), campaign(biz_b)
    ta = pub(client, "GET", ca["public_id"]).json()["suggestions"][0]["id"]
    tb = pub(client, "GET", cb["public_id"]).json()["suggestions"][0]["id"]
    llm.texts = [A]
    gen(client, ca, ta)
    llm.calls.clear()
    llm.texts = [B]
    gen(client, cb, tb)
    assert not any("<other_review>" in u for _, u in llm.calls)  # B's writer is shown only B's own location's reviews
