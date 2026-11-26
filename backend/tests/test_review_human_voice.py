"""A suggested review must read like a person typed it, not like an AI wrote it. The prompt asks for plain phone-typed wording; on top of that, the marks that give machine text away (long dashes, semicolons,
exclamation pile-ups, brochure words such as "seamless" or "truly", the three-item list with a comma before "and", the "not only ... but" turn) are refused like any other faithfulness failure, and the
draft is rewritten. The AI is a labelled test double; the routes, the engine and the database are real."""
import re

import pytest

from app.core.config import settings
from app.services.ai.review_generate import (STYLE_GUIDE, SYSTEM, ReviewDraftRejected, ReviewInput, ai_tell, validate_draft)
from tests.test_review_growth import campaign, llm, pub  # noqa: F401

INP = ReviewInput(rating=5, topics=("Staff",), sentiment="good", topic_notes=("Staff: how the staff dealt with the customer.",), topic_ok=("friendly", "polite", "courteous", "professional", "attentive"),
                  topic_alts=("the staff", "the team"))
KW = dict(language="en", style="natural", business_name="Acme Physio")


@pytest.mark.parametrize("text,why", [
    ("The staff were friendly — and polite.", "long dash"),
    ("The staff were friendly – and polite.", "long dash"),
    ("The staff were friendly; they were polite.", "semicolon"),
    ("The staff were friendly! They were polite! Loved it.", "exclamation"),
    ("The staff were seamless and polite.", "seamless"),
    ("The staff were truly friendly.", "truly"),
    ("The staff were genuinely polite.", "genuinely"),
    ("The staff went above and beyond.", "above and beyond"),
    ("I would like to say the staff were polite.", "i would like to"),
    ("The staff were friendly, polite, and attentive.", "comma before"),
    ("The staff were not only friendly but also polite.", "not only"),
    ("The staff were a testament to good manners.", "testament"),
])
def test_the_marks_of_machine_written_text_are_refused(text, why):
    assert why in (ai_tell(text) or "").lower()  # the detector names the tell
    with pytest.raises(ReviewDraftRejected):  # and the draft is refused (some words are caught by an older rule first, as an invented quality: either way it never reaches the customer)
        validate_draft(text, INP, **KW)


@pytest.mark.parametrize("text", [
    "The staff were friendly and polite.",
    "I found the staff professional and attentive.",
    "Staff were friendly. Polite too.",
    "The team was polite and professional with me.",
    "The staff were polite, and the team was friendly.",
])
def test_plain_everyday_wording_is_accepted(text):
    assert ai_tell(text) is None
    validate_draft(text, INP, **KW)


def test_hinglish_is_held_to_the_same_standard():
    assert ai_tell("Staff bahut friendly tha — aur polite bhi.") == "uses a long dash"
    assert ai_tell("Staff bahut friendly tha aur polite bhi.") is None
    with pytest.raises(ReviewDraftRejected, match="sounds like AI-written text"):
        validate_draft("Staff truly bahut friendly tha aur polite bhi.", INP, language="hinglish", style="natural", business_name="Acme Physio")


def test_a_draft_with_an_ai_tell_is_rewritten_and_the_customer_only_ever_sees_the_plain_one(biz_a, client, llm):
    c = campaign(biz_a)
    topic = pub(client, "GET", c["public_id"]).json()["suggestions"][0]["id"]
    llm.texts = ["The staff were friendly — and polite.", "The staff were friendly and polite."]  # the first attempt has a long dash, the retry is plain
    r = pub(client, "POST", c["public_id"], "/generate", json={"mode": "ai", "rating": 5, "suggestions": [topic], "language": "en"}).json()
    assert r["ai_status"] == "ok" and r["draft"] == "The staff were friendly and polite." and "—" not in str(r["suggestions"])
    assert "sounds like AI-written text" in llm.calls[1][1]  # the retry told the writer what was wrong


def test_if_the_writer_keeps_producing_ai_sounding_text_the_customer_gets_nothing_rather_than_that_text(biz_a, client, llm):
    c = campaign(biz_a)
    topic = pub(client, "GET", c["public_id"]).json()["suggestions"][0]["id"]
    llm.texts = ["The staff were truly seamless and polite."]
    r = pub(client, "POST", c["public_id"], "/generate", json={"mode": "ai", "rating": 5, "suggestions": [topic], "language": "en"}).json()
    assert r["ai_status"] == "rejected" and r["draft"] is None  # they can write it themselves; an AI-sounding draft is never put in their box


def test_the_writer_is_told_to_sound_like_a_person_and_given_a_list_of_what_to_avoid(biz_a, client, llm):
    c = campaign(biz_a)
    topic = pub(client, "GET", c["public_id"]).json()["suggestions"][0]["id"]
    llm.texts = ["The staff were friendly and polite."]
    pub(client, "POST", c["public_id"], "/generate", json={"mode": "ai", "rating": 5, "suggestions": [topic], "language": "en"})
    system = llm.calls[0][0]
    assert "SOUND LIKE A PERSON TYPING ON THEIR PHONE, NOT LIKE AN AI" in system
    for avoid in ("em dashes", "semicolons", "seamless", "genuinely", "not only ... but also", "contractions"):
        assert avoid in system


def test_nothing_in_the_instructions_or_examples_teaches_the_formal_voice():
    assert "appreciated the way" not in SYSTEM and "I appreciated how" not in SYSTEM  # the examples are what a model copies
    assert "polished" not in " ".join(STYLE_GUIDE.values()).lower() and "gratitude" not in " ".join(STYLE_GUIDE.values()).lower()
    examples = SYSTEM.split("EXAMPLES of the right level of faithfulness")[1]
    for line in re.findall(r"->\s+(.+)", examples):
        assert ai_tell(line) is None or "Hindi" in line or "ड" in line, line  # every English example passes the same check the drafts must
