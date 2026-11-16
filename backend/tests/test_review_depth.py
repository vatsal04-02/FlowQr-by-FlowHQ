"""Richer, still honest drafts: level of detail, topic expansion (describing words), follow-up question, prompt structure and the guards that keep
expansion from becoming invention. Test doubles stand in for the model; the real-model measurements are in docs/REVIEW_GROWTH.md."""
import re

import pytest

from app.core.config import settings
from app.services.ai.review_generate import (
    RATING_SENTIMENT, ReviewDraftRejected, ReviewInput, _prompt, _repair, detail_level, generate_review, validate_draft, word_count,
)
from app.services.review_suggestions import CATALOG, MEANING, VOICE, follow_up_for, merged_context
from tests.test_review_growth import StubLLM, campaign, llm, pub  # noqa: F401  (llm = fixture)
from tests.test_review_context import biz  # noqa: F401

BASE = dict(language="en", style="natural", business_name="Acme Clinic", category="Physiotherapy clinic")
OK_STAFF = ("friendly", "polite", "courteous", "professional", "attentive")
OK_EXPL = ("clear", "clearly", "simple", "easy to understand", "easy to follow")


def inp(topics=("Staff", "Explanations"), rating=5, ok=OK_STAFF + OK_EXPL, note="", **kw):
    return ReviewInput(topics=topics, topic_alts=tuple(f"the {t.lower()}" for t in topics), rating=rating, sentiment=RATING_SENTIMENT[rating], topic_ok=ok if rating != 3 else (), note=note, **kw)


# ---------------------------------------------------------------- level of detail follows what the customer gave (soft targets)

@pytest.mark.parametrize("topics,note,name,lo,hi", [
    (("Staff",), "", "brief", 15, 30),
    (("Staff", "Explanations"), "", "standard", 30, 60),
    (("Staff", "Explanations", "Exercises"), "", "standard", 30, 60),
    (("Staff", "Explanations", "Exercises"), "the exercises were shown step by step", "rich", 50, 90),
    (("Staff", "Explanations"), "we came on a busy morning and the room was tidy and well lit", "rich", 50, 90),
])
def test_detail_level_matches_the_spec(topics, note, name, lo, hi):
    assert detail_level(ReviewInput(topics=topics, note=note)) == (name, lo, hi)


def test_text_only_input_is_roughly_as_long_as_what_they_wrote():
    name, lo, hi = detail_level(ReviewInput(note="waited an hour, nobody explained the charges"))
    assert name == "own words" and lo <= 8 and 30 <= hi <= 110


def test_length_is_a_soft_target_with_a_hard_ceiling_never_a_minimum():
    short = "The staff were polite and I appreciated how clearly things were explained."
    validate_draft(short, inp(), **BASE)  # shorter than 30 words is fine: never padded
    long = " ".join(["I appreciated how the staff dealt with me and things were explained clearly."] * 8)
    with pytest.raises(ReviewDraftRejected, match="longer than"):
        validate_draft(long, inp(), **BASE)


def test_hindi_words_are_counted_by_spaces_not_by_vowel_signs():
    assert word_count("स्टाफ़ का व्यवहार अच्छा लगा।") == 5 and word_count("The staff were polite.") == 4


# ---------------------------------------------------------------- expansion uses describing words, in the direction of the rating, and nothing else

def test_describing_words_for_a_picked_topic_are_allowed_when_the_rating_is_positive():
    validate_draft("The staff were polite and attentive, and I appreciated how clearly things were explained.", inp(), **BASE)
    plain = ReviewInput(topics=("Staff",), sentiment="good", rating=5)  # no topic words supplied (e.g. an older client): the strict rules still apply
    with pytest.raises(ReviewDraftRejected, match="quality"):
        validate_draft("The staff were polite and attentive.", plain, **BASE)


def test_only_the_listed_words_are_allowed_other_qualities_are_still_invented():
    with pytest.raises(ReviewDraftRejected, match="quality|result"):
        validate_draft("The staff were kind and knowledgeable, and things were explained clearly.", inp(), **BASE)


def test_a_negative_rating_cannot_use_describing_words_positively():
    neg = inp(rating=2)
    validate_draft("The staff were not polite and things were not explained clearly.", neg, **BASE)
    validate_draft("The explanations fell short of being clear.", inp(topics=("Explanations",), rating=1, ok=OK_EXPL), **BASE)
    with pytest.raises(ReviewDraftRejected):
        validate_draft("The staff were polite and attentive, but I was not satisfied with the explanations.", neg, **BASE)


def test_a_neutral_rating_uses_no_describing_words():
    neutral = inp(rating=3)
    validate_draft("The staff and the explanations were both okay.", neutral, **BASE)
    with pytest.raises(ReviewDraftRejected):
        validate_draft("The staff were polite and the explanations were clear.", neutral, **BASE)


@pytest.mark.parametrize("bad", [
    "The staff were polite and I was fully recovered within a week.", "The explanations were clear and my pain was reduced.",
    "The staff were polite and attentive, and the session started on time.", "The staff were polite. I didn't have any issues with timing.",
    "The staff were polite because they answered all my questions.", "The staff were polite; I felt relieved and reassured.",
    "The staff were polite and I would recommend them to everyone.",
])
def test_expansion_never_becomes_a_result_event_reason_feeling_or_recommendation(bad):
    with pytest.raises(ReviewDraftRejected):
        validate_draft(bad, inp(), **BASE)


def test_business_services_are_never_proof_of_what_the_customer_received():
    with pytest.raises(ReviewDraftRejected, match="service"):
        validate_draft("The staff were polite and the sports injury rehabilitation was explained clearly.", inp(), offered_terms=("rehabilitation",), **BASE)


def test_everything_is_repaired_not_retried():
    i = inp()
    assert _repair("I appreciated how clearly everything was explained.", i) == "I appreciated how clearly things were explained."
    assert _repair("They explained everything.", i) == "They explained things."
    assert _repair("everything was great", inp(note="everything was great")) == "everything was great"  # the customer's own word stays


def test_generic_openings_and_a_single_overworked_adjective_are_rejected():
    for bad in ("I had a good experience. The staff were polite.", "I recently visited and the staff were polite.", "Overall, the staff were polite and things were explained clearly."):
        with pytest.raises(ReviewDraftRejected):
            validate_draft(bad, inp(), **BASE)
    with pytest.raises(ReviewDraftRejected, match="adjective"):
        validate_draft("The staff were good, the explanations were good and the booking was good.", inp(), **BASE)


# ---------------------------------------------------------------- a draft that is honest but too thin gets one more try, then is kept as is

class Seq:
    name, model = "seq", "seq-1"

    def __init__(self, *texts):
        self.texts, self.calls = list(texts), 0

    def generate(self, system, user, **kw):
        self.calls += 1
        return self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]


def run(provider, i, **kw):
    stats = {}
    return generate_review(provider, i, language="en", style="natural", business_name="Acme Clinic", category="Physiotherapy clinic", verify=False, stats=stats, **kw), stats


def test_a_one_line_draft_for_several_topics_is_asked_to_expand_once(monkeypatch):
    monkeypatch.setattr(settings, "review_max_attempts", 3)
    thin = "The staff and explanations were good."
    full = "I appreciated how the staff dealt with me, and things were explained in a way that was easy to follow. The exercise guidance was clear as well."
    p = Seq(thin, full)
    out, stats = run(p, inp(topics=("Staff", "Explanations", "Exercise guidance"), ok=OK_STAFF + OK_EXPL))
    assert out == full and p.calls == 2 and stats["too_short"] == 1


def test_a_short_draft_that_passed_every_check_is_kept_not_rejected(monkeypatch):
    monkeypatch.setattr(settings, "review_max_attempts", 2)
    thin = "The staff and explanations were good."
    out, _ = run(Seq(thin), inp())
    assert out == thin  # never padded, never turned into an error


def test_one_topic_is_not_asked_to_expand():
    p = Seq("The staff were polite.")
    out, stats = run(p, inp(topics=("Staff",)))
    assert p.calls == 1 and "too_short" not in stats


# ---------------------------------------------------------------- the prompt: structured context, soft length, topic meaning, rating tone

def test_the_prompt_has_business_customer_and_control_sections():
    i = ReviewInput(topics=("Staff", "Explanations"), rating=5, sentiment="good", topic_notes=("Staff: how the staff dealt with the customer. Describing words that fit: polite.",),
                    topic_hi=("स्टाफ़", "समझाने का तरीका"))
    en = _prompt(i, language="en", style="natural", business_name="Acme Clinic", category="Physiotherapy clinic", location_name="Lucknow", previous=(), retry_reason=None,
                 context_text="Business type: Physiotherapy.\nServices/products the business offers: Back pain rehabilitation.")
    assert en.index("BUSINESS CONTEXT") < en.index("GENERATION CONTROLS") < en.index("CUSTOMER CONTEXT")
    assert "Back pain rehabilitation" in en.split("GENERATION CONTROLS")[0] and "Back pain rehabilitation" not in en.split("CUSTOMER CONTEXT")[1]  # offered, not experienced
    assert "Detail level: standard" in en and "30 to 60 words" in en and "never add an unsupported detail" in en
    assert "Describing words that fit: polite" in en and "5 out of 5" in en and "Hindi names" in en
    hi = _prompt(i, language="hi", style="natural", business_name="Acme", category=None, location_name=None, previous=(), retry_reason=None)
    assert "idiomatic Hindi" in hi and "word-for-word" in hi


def test_opening_hints_fit_the_direction_of_the_rating():
    for _ in range(40):
        neg = _prompt(inp(rating=1), language="en", style="natural", business_name="A", category=None, location_name=None, previous=(), retry_reason=None)
        assert "What I liked about" not in neg and "was happy with" not in neg.split("GENERATION CONTROLS")[1].split("CUSTOMER CONTEXT")[0].replace("wasn't happy with", "")


def test_the_business_context_block_carries_category_voice_but_no_claims():
    class T:
        name, category, review_context = "Acme Physio", "Physiotherapy clinic", {"description": "Exercise-based rehabilitation clinic.", "services": ["Back pain rehabilitation"]}

    block = merged_context(T()).prompt_block()
    assert VOICE["physio"] in block and "NOT what this customer received" in block


# ---------------------------------------------------------------- catalog integrity for the new meaning data

def test_every_catalog_topic_has_a_meaning_with_an_english_and_hindi_follow_up():
    ids = {t.id for entry in CATALOG.values() for t in entry["topics"]}
    assert ids <= set(MEANING), ids - set(MEANING)
    for tid, m in MEANING.items():
        assert m.about and m.ask_en.endswith("?") and re.search(r"[ऀ-ॿ]", m.ask_hi) and m.ask_hi.endswith("?"), tid


def test_describing_words_never_smuggle_in_results_events_or_feelings():
    banned = re.compile(r"help|improv|better|relie|recover|cure|heal|on time|punctual|prompt|fresh|delicious|best|amazing|excellent|perfect|welcom(?!ing)|reassur|felt", re.I)
    for tid, m in MEANING.items():
        assert not [w for w in m.words if banned.search(w)], (tid, m.words)
    assert all(v for v in VOICE.values()) and set(VOICE) >= set(CATALOG)


# ---------------------------------------------------------------- the optional follow-up question

@pytest.mark.parametrize("ids,rating,lang,typed,expected", [
    (["staff"], 5, "en", "", "What did you appreciate most about the staff?"),
    (["explanations"], 4, "en", "", "Was there something that was explained especially well?"),
    (["staff", "explanations"], 5, "en", "", None),                 # enough already
    (["staff"], 5, "en", "they listened", None),                    # they gave details
    ([], 5, "en", "", None),
])
def test_follow_up_only_when_the_customer_gave_very_little(ids, rating, lang, typed, expected):
    assert follow_up_for(ids, rating, lang, typed) == expected


def test_follow_up_fits_the_rating_and_the_language():
    assert follow_up_for(["staff"], 2, "en", "") == "Is there anything specific you would like to add?"  # never "what did you appreciate" on a low rating
    assert re.search(r"[ऀ-ॿ]", follow_up_for(["staff"], 5, "hi", ""))
    assert follow_up_for(["not_a_topic"], 5, "en", "") is None


def test_the_api_returns_one_optional_follow_up_only_for_a_lone_topic(client, llm):
    c = campaign(biz("Physiotherapy clinic", "Depth Biz"))
    llm.texts = ["The staff were polite."]
    one = pub(client, "POST", c["public_id"], "/generate", json={"language": "en", "rating": 5, "suggestions": ["staff"]}).json()
    assert one["ai_status"] == "ok" and one["follow_up"] == "What did you appreciate most about the staff?" and one["draft"]
    llm.texts = ["I appreciated how the staff dealt with me, and things were explained clearly."]
    two = pub(client, "POST", c["public_id"], "/generate", json={"language": "en", "rating": 5, "suggestions": ["staff", "explanations"]}).json()
    assert two["ai_status"] == "ok" and two["follow_up"] is None


def test_the_api_passes_topic_meaning_and_hindi_names_to_the_model(client, llm):
    c = campaign(biz("Physiotherapy clinic", "Depth Biz 2"))
    llm.texts = ["I appreciated how the staff dealt with me, and things were explained clearly."]
    assert pub(client, "POST", c["public_id"], "/generate", json={"language": "en", "rating": 5, "suggestions": ["staff", "explanations"]}).json()["ai_status"] == "ok"
    prompt = llm.calls[-1][1]
    assert "how the staff dealt with the customer" in prompt and "how well things were explained" in prompt and "Describing words that fit" in prompt and "स्टाफ़" in prompt
    llm.texts = ["The staff and the explanations were both okay."]
    pub(client, "POST", c["public_id"], "/generate", json={"language": "en", "rating": 3, "suggestions": ["staff", "explanations"]})
    assert "Describing words" not in llm.calls[-1][1] and "NO describing words" in llm.calls[-1][1]  # neutral: none offered
