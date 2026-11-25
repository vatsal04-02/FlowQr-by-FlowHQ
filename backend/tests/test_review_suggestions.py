"""One AI round shows a customer 1-2 genuinely different suggestions to start from (never one fixed paragraph, never auto-submitted). Each is written by the existing engine, so each passes the same
grounding checks as a single draft: no invented events, numbers, names or qualities. The second is sometimes Hinglish (Hindi in English letters), which always gets the AI fact-check too, because the
English-only rules cannot police it. Uniqueness is checked deterministically: the same opening words, a reused five-word phrase or near-identical text are all refused. The AI is a labelled test double;
routes, guardrails and the database are real."""
import pytest

from app.core.config import settings
from app.services.ai.review_generate import (CROSS_REVIEW_SIMILARITY, SAME_VISIT_SIMILARITY, STRUCTURE_HINTS, STYLE_GUIDE, VARIATION_HINTS, VARIATION_POSITIVE, sameness)
from tests.conftest import owner_exec, owner_query
from tests.test_review_growth import campaign, llm, pub  # noqa: F401

# Genuinely different English reviews of the same visit (staff, rated 5). Each uses only the describing words the Staff keyword allows, and none opens like another.
A = "The staff were friendly and polite."
B = "I found the staff professional and attentive."
C = "I appreciated how courteous the staff were with me."
D = "The team was polite and professional with me."
E = "Attentive staff who were also friendly."
H1 = "Staff bahut friendly tha aur polite bhi."
H2 = "Team ke log courteous the aur mujhe unka attentive hona pasand aaya."


class Scripted:
    """A labelled test double with two jobs, like the real provider: write reviews (popping scripted texts) and answer the fact-check ("OK" unless told otherwise)."""
    name, model, usage = "scripted", "m", None

    def __init__(self, texts, verdict="OK"):
        self.texts, self.verdict, self.calls, self.checks = list(texts), verdict, [], 0

    def generate(self, system, user, **kw):
        if system.startswith("You are a strict fact-checker"):
            self.checks += 1
            return self.verdict
        self.calls.append(user)
        return self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]


@pytest.fixture(autouse=True)
def two_per_round(monkeypatch):
    monkeypatch.setattr(settings, "review_suggestions_per_round", 2)  # production default (the older suite runs with 1)
    monkeypatch.setattr(settings, "review_hinglish_chance", 0.0)  # tests that want Hinglish switch it on
    monkeypatch.setattr(settings, "review_max_ai_writes_per_session", 2)


def hinglish_in(monkeypatch, slot):
    """Make Hinglish certain and pin which suggestion of the round it is (0 = first, 1 = second)."""
    monkeypatch.setattr(settings, "review_hinglish_chance", 1.0)
    monkeypatch.setattr("app.api.v1.review_public._hinglish_slot", lambda n: slot)


def script(monkeypatch, texts, verdict="OK"):
    p = Scripted(texts, verdict)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_data_terms_verified", True)
    monkeypatch.setattr("app.api.v1.review_public.get_provider", lambda: p)
    return p


def topic_of(client, c):
    return pub(client, "GET", c["public_id"]).json()["suggestions"][0]["id"]


def gen(client, c, topic=None, **extra):
    return pub(client, "POST", c["public_id"], "/generate", json={"mode": "ai", "rating": 5, "suggestions": [topic or topic_of(client, c)], "language": "en", **extra})


# ================================================================================================================ one round: two different suggestions
def test_one_round_shows_two_different_suggestions_each_in_its_own_style_and_shape(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [A, B]
    r = gen(client, c).json()
    assert r["ai_status"] == "ok" and r["suggestions"] == [A, B] and r["draft"] == A  # "draft" is still the first one, for older clients
    assert r["suggestion_languages"] == ["en", "en"] and len(llm.calls) == 2
    prompts = [u for _, u in llm.calls]
    styles = [next(name for name, guide in STYLE_GUIDE.items() if f"Style: {guide}" in p) for p in prompts]
    assert len(set(styles)) == 2  # two different tones and lengths
    used = [tuple(h for h in (*VARIATION_HINTS, *VARIATION_POSITIVE, *STRUCTURE_HINTS) if h in p) for p in prompts]
    assert len(set(used)) == 2  # and the two are told to open and build their sentences differently
    assert f"<earlier_draft>{A}</earlier_draft>" in prompts[1]  # the second knows what the first already says


def test_every_suggestion_is_told_to_be_specific_to_this_business_and_to_invent_nothing(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [A, B]
    gen(client, c)
    assert all("Make it specific to THIS business" in u and "never add a fact about this visit" in u for _, u in llm.calls)


def test_a_suggestion_that_would_invent_something_never_reaches_the_customer(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [A, "I found the staff friendly and I waited 20 minutes for the doctor.", "I found the staff friendly and I waited 20 minutes for the doctor."]
    r = gen(client, c).json()
    assert r["ai_status"] == "ok" and r["suggestions"] == [A]  # the invented wait and number were refused by the same checks as before; the customer just sees one
    assert "20" not in r["draft"] and "waited" not in r["draft"]


def test_the_extra_suggestion_never_turns_into_an_error(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [A]  # every further call repeats A, which is refused as a copy
    r = gen(client, c).json()
    assert r["ai_status"] == "ok" and r["suggestions"] == [A] and r["draft"] == A  # one good suggestion is a normal result


def test_a_round_counts_as_one_ai_version_and_a_new_round_never_repeats_the_first(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [A, B, C, E]
    first = gen(client, c).json()
    assert first["suggestions"] == [A, B] and first["remaining_drafts"] == 1  # two suggestions, ONE of the visit's two rounds
    sid = first["session_id"]
    second = pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": sid}).json()
    assert second["ai_status"] == "ok" and second["suggestions"] == [C, E] and second["remaining_drafts"] == 0
    assert not set(first["suggestions"]) & set(second["suggestions"])
    assert pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": sid}).status_code == 429  # the visit's allowance is unchanged: two rounds


def test_one_per_round_is_exactly_the_old_single_draft(biz_a, client, llm, monkeypatch):
    monkeypatch.setattr(settings, "review_suggestions_per_round", 1)
    c = campaign(biz_a)
    llm.texts = [A, B]
    r = gen(client, c).json()
    assert r["suggestions"] == [A] and len(llm.calls) == 1


def test_asking_for_more_than_two_still_shows_two(biz_a, client, llm, monkeypatch):
    monkeypatch.setattr(settings, "review_suggestions_per_round", 5)
    c = campaign(biz_a)
    llm.texts = [A, B, C, D]
    assert len(gen(client, c).json()["suggestions"]) == 2


# ================================================================================================================ Hinglish
def test_a_suggestion_can_be_hinglish_and_is_fact_checked_by_the_ai_even_when_that_check_is_off(biz_a, client, monkeypatch):
    hinglish_in(monkeypatch, 1)
    monkeypatch.setattr(settings, "review_verify_with_ai", False)  # the English suggestion is not fact-checked by the model here...
    p = script(monkeypatch, [A, H1])
    r = gen(client, campaign(biz_a)).json()
    assert r["suggestions"] == [A, H1] and r["suggestion_languages"] == ["en", "hinglish"]
    assert p.checks == 1  # ...but the Hinglish one always is: the English-only rules cannot police it
    assert "Hindi (Roman" not in p.calls[0] and "Hinglish" in p.calls[1] and "No Devanagari" in p.calls[1]


def test_hinglish_that_the_fact_check_does_not_support_is_dropped(biz_a, client, monkeypatch):
    hinglish_in(monkeypatch, 1)
    script(monkeypatch, [A, H1], verdict="UNSUPPORTED: staff ne unhe chai pilayi")
    r = gen(client, campaign(biz_a)).json()
    assert r["ai_status"] == "ok" and r["suggestions"] == [A]  # the customer just sees the English one


@pytest.mark.parametrize("bad", ["स्टाफ़ बहुत अच्छा था और विनम्र भी।", "The staff were friendly and polite to me.", "Staff ne mujhse 20 minute baat ki aur wo bahut friendly the."])
def test_hinglish_must_really_be_hinglish_without_devanagari_or_invented_numbers(biz_a, client, monkeypatch, bad):
    hinglish_in(monkeypatch, 1)
    script(monkeypatch, [A, bad])
    assert gen(client, campaign(biz_a)).json()["suggestions"] == [A]


def test_hinglish_is_never_offered_when_the_business_does_not_offer_hindi(biz_a, client, monkeypatch):
    hinglish_in(monkeypatch, 1)
    assert biz_a.put("/review-growth/context", json={"languages": ["en"]}).status_code == 200
    p = script(monkeypatch, [A, H1, B])
    r = gen(client, campaign(biz_a)).json()
    assert r["suggestion_languages"] == ["en", "en"] and all("Hinglish" not in u for u in p.calls)


def test_with_hinglish_switched_off_both_suggestions_are_in_the_customers_language(biz_a, client, monkeypatch):
    p = script(monkeypatch, [A, B])
    r = gen(client, campaign(biz_a)).json()
    assert r["suggestion_languages"] == ["en", "en"] and p.checks == 0


def test_hinglish_appears_only_sometimes_in_either_place_and_never_in_every_suggestion(biz_a, client, monkeypatch):
    monkeypatch.setattr(settings, "review_hinglish_chance", 0.4)
    from app.api.v1.review_public import round_languages
    rounds = [round_languages("en", ("en", "hi"), 2) for _ in range(600)]
    with_hinglish = [r for r in rounds if "hinglish" in r]
    assert 0.3 < len(with_hinglish) / 600 < 0.5  # sometimes, not always
    assert any(r[0] == "hinglish" for r in with_hinglish) and any(r[1] == "hinglish" for r in with_hinglish)  # the first suggestion too, not only the second
    assert all(r.count("hinglish") == 1 for r in with_hinglish)  # a round never turns out all Hinglish
    assert all(r == ["en", "en"] for r in rounds if "hinglish" not in r)


def test_the_first_suggestion_can_be_the_hinglish_one(biz_a, client, monkeypatch):
    hinglish_in(monkeypatch, 0)
    monkeypatch.setattr(settings, "review_verify_with_ai", False)
    p = script(monkeypatch, [H1, A])
    r = gen(client, campaign(biz_a)).json()
    assert r["suggestions"] == [H1, A] and r["suggestion_languages"] == ["hinglish", "en"] and r["draft"] == H1  # the box starts with the Hinglish one
    assert p.checks == 1 and "Hinglish" in p.calls[0] and "Hinglish" not in p.calls[1]


def test_a_hinglish_first_suggestion_that_fails_its_checks_is_replaced_by_one_in_the_customers_language_never_by_an_error(biz_a, client, monkeypatch):
    hinglish_in(monkeypatch, 0)
    monkeypatch.setattr(settings, "review_verify_with_ai", False)
    script(monkeypatch, [H1, H1, A, B], verdict="UNSUPPORTED: staff ne unhe chai pilayi")  # both Hinglish attempts fail the fact-check; the English ones are not fact-checked here
    r = gen(client, campaign(biz_a)).json()
    assert r["ai_status"] == "ok" and r["suggestions"] == [A, B] and r["suggestion_languages"] == ["en", "en"]


# ================================================================================================================ real uniqueness
def test_sameness_catches_the_same_opening_a_reused_phrase_and_near_identical_text():
    assert sameness("The staff were friendly and polite.", "The staff were courteous at all times.", 0.9) == "same opening words"
    assert sameness("I liked how the reception staff were friendly and polite.", "Honestly the reception staff were friendly and polite too.", 0.99) == "reuses a five-word phrase"
    assert sameness("Friendly staff, quick service.", "Friendly staff, quick service!", 0.9) in ("same opening words", "almost the same text")
    assert sameness("The staff were friendly and polite.", "I found the staff professional and attentive.", 0.62) is None
    assert sameness("I liked how the reception staff were friendly.", "Honestly the reception staff were friendly too.", 0.99, phrases=False) is None  # one visit's facts may repeat
    assert 0.5 < CROSS_REVIEW_SIMILARITY <= SAME_VISIT_SIMILARITY < 0.9


def test_two_customers_with_the_same_picks_never_open_the_same_way_or_share_a_phrase(biz_a, client, llm):
    c = campaign(biz_a)
    topic = topic_of(client, c)
    llm.texts = [A, B]
    first = gen(client, c, topic).json()
    llm.calls.clear()
    llm.texts = ["The staff were courteous and polite.", D, "Attentive staff who were also polite."]
    second = gen(client, c, topic).json()  # the first attempt opens like A's "The staff were ..." and is refused; the retry writes something different
    assert second["ai_status"] == "ok" and second["suggestions"][0] == D
    assert not set(second["suggestions"]) & set(first["suggestions"])
    assert any(f"<other_review>{A}</other_review>" in u for _, u in llm.calls)  # the writer was shown what the business already has


def test_when_a_first_suggestion_cannot_be_made_different_it_is_still_shown_but_a_copy_of_the_customers_own_draft_never_is(biz_a, client, llm):
    c = campaign(biz_a)
    topic = topic_of(client, c)
    llm.texts = [A]
    gen(client, c, topic)  # another customer already has A
    llm.texts = ["The staff were courteous and polite."]  # same opening as A on every attempt, but faithful
    mine = gen(client, c, topic).json()
    assert mine["ai_status"] == "ok" and mine["suggestions"] == ["The staff were courteous and polite."]  # uniqueness softens on the last attempt; faithfulness never does
    llm.texts = ["The staff were courteous and polite."]
    again = pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": mine["session_id"]}).json()
    assert again["ai_status"] == "rejected" and again["draft"] == "The staff were courteous and polite."  # an identical redo of the customer's OWN draft is never accepted


def test_other_customers_suggestions_are_shown_to_the_writer_including_the_second_one(biz_a, client, llm):
    c = campaign(biz_a)
    topic = topic_of(client, c)
    llm.texts = [A, B]
    gen(client, c, topic)
    llm.calls.clear()
    llm.texts = [C, D]
    r = gen(client, c, topic).json()
    assert r["suggestions"] == [C, D]
    assert all(f"<other_review>{x}</other_review>" in llm.calls[0][1] for x in (A, B))  # both the previous customer saw, not just the first


# ================================================================================================================ isolation, consent, knowledge
def test_another_business_never_supplies_examples_or_context(biz_a, biz_b, client, llm):
    ca, cb = campaign(biz_a), campaign(biz_b)
    llm.texts = [A, B]
    gen(client, ca)
    llm.calls.clear()
    llm.texts = [C, E]
    r = gen(client, cb).json()
    assert r["suggestions"] == [C, E]
    assert not any("<other_review>" in u for _, u in llm.calls)
    assert not any(x in u for _, u in llm.calls for x in (A, B))  # the first business's suggestions never reach the second's writer


def test_nothing_is_submitted_or_approved_by_generating_suggestions(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [A, B]
    sid = gen(client, c).json()["session_id"]
    row = owner_query("SELECT final_content, approved_at FROM review_drafts d JOIN review_sessions s ON s.id = d.session_id WHERE s.session_identifier = :s", s=sid)[0]
    assert tuple(row) == (None, None)  # only the customer's own tap can confirm a review
    events = {e[0] for e in owner_query("SELECT event_type FROM review_events WHERE tenant_id = :t", t=biz_a.tenant_id)}
    assert not events & {"review_copied", "redirect_clicked", "review_submitted", "approved"}


def test_with_no_services_recorded_the_suggestions_still_come_from_the_standard_keywords(biz_a, client, llm):
    assert biz_a.put("/review-growth/context", json={"services": [], "description": ""}).status_code == 200  # nothing known about the business
    c = campaign(biz_a)
    llm.texts = [A, B]
    r = gen(client, c).json()
    assert r["ai_status"] == "ok" and len(r["suggestions"]) == 2
    assert "Services/products the business offers" not in llm.calls[0][1]  # nothing about the business is invented or assumed


def test_when_services_are_recorded_every_suggestion_is_written_with_that_knowledge(biz_a, client, llm):
    assert biz_a.put("/review-growth/context", json={"services": ["Back pain rehabilitation"], "description": "An exercise-based rehabilitation clinic."}).status_code == 200
    c = campaign(biz_a)
    topic = next(s["id"] for s in pub(client, "GET", c["public_id"]).json()["suggestions"] if s["id"] == "staff")
    llm.texts = [A, B]
    gen(client, c, topic)
    assert all("Back pain rehabilitation" in u and "An exercise-based rehabilitation clinic." in u for _, u in llm.calls)  # both get the business's own context
    assert all("never evidence of what this customer received" in u for _, u in llm.calls)  # and are told it is background, not what the customer experienced


# ================================================================================================================ no review is ever the same as one the business already has
def test_an_identical_or_near_identical_review_is_never_accepted_not_even_on_the_last_attempt(biz_a, client, llm, monkeypatch):
    c = campaign(biz_a)
    topic = topic_of(client, c)
    llm.texts = [A, B]
    first = gen(client, c, topic).json()
    assert first["suggestions"] == [A, B]
    # a different customer: every attempt comes back as A, or as A with one word changed. Opening-word and phrase overlap may soften on the last attempt, but being THE SAME review never does.
    for repeat in ("The staff were friendly and polite.", "The staff were friendly and polite!", "the staff were friendly and polite"):
        llm.texts = [repeat]
        r = gen(client, c, topic).json()
        assert r["ai_status"] == "rejected" and r["draft"] is None, repeat


def test_a_text_a_customer_actually_posted_is_also_never_repeated(biz_a, client, llm):
    c = campaign(biz_a)
    topic = topic_of(client, c)
    llm.texts = [A, B]
    sid = gen(client, c, topic).json()["session_id"]
    owner_exec("UPDATE review_drafts SET suggestions = NULL, generated_content = NULL, final_content = :t WHERE session_id = (SELECT id FROM review_sessions WHERE session_identifier = :s)", t=C, s=sid)
    llm.texts = [C]  # the posted text comes back word for word for the next customer
    assert gen(client, c, topic).json()["ai_status"] == "rejected"
    llm.texts = [D, E]
    assert gen(client, c, topic).json()["suggestions"][0] == D  # a genuinely different one is fine


def test_the_duplicate_check_looks_far_beyond_the_last_dozen_reviews_and_never_sends_those_texts_to_the_ai(biz_a, client, llm):
    from app.api.v1.review_public import avoid_texts, recent_reviews
    from app.core.db import SessionLocal, set_rls_context
    from app.models import ReviewCampaign, ReviewSession, Tenant
    c = campaign(biz_a)
    topic = topic_of(client, c)
    llm.texts = [A, B]
    first = gen(client, c, topic).json()
    for i in range(15):  # fifteen later customers (inserted directly): the first customer's texts are now far outside the "last 12"
        owner_exec("WITH s AS (INSERT INTO review_sessions (id, tenant_id, campaign_id, session_identifier, language, style, customer_input, created_at) "
                   "SELECT gen_random_uuid(), tenant_id, id, :i, 'en', 'natural', '{}'::jsonb, now() FROM review_campaigns WHERE public_id = :p RETURNING id, tenant_id) "
                   "INSERT INTO review_drafts (id, tenant_id, session_id, generated_content, generation_count, ai_assisted, created_at, updated_at) "
                   "SELECT gen_random_uuid(), tenant_id, id, :t, 1, true, now() + make_interval(secs => :n), now() + make_interval(secs => :n) FROM s",
                   i=f"filler-session-{i:03d}-abcdefgh", p=c["public_id"], t=f"Filler review number {i} about nothing in particular.", n=i + 1)
    db = SessionLocal()
    set_rls_context(db, bypass=True)
    try:
        camp = db.query(ReviewCampaign).filter(ReviewCampaign.public_id == c["public_id"]).one()
        tenant = db.get(Tenant, camp.tenant_id)
        me = ReviewSession(tenant_id=tenant.id, campaign_id=camp.id, session_identifier="me-" + "x" * 20, language="en", style="natural", customer_input={})
        pool, shown_to_ai = avoid_texts(db, tenant, camp, me), recent_reviews(db, tenant, camp, me)
    finally:
        db.close()
    assert A in pool and B in pool  # the duplicate check still knows them
    assert A not in shown_to_ai and len(shown_to_ai) <= 12  # while the AI is only shown the latest few examples
    assert first["suggestions"] == [A, B]
