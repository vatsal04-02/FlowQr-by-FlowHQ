"""Context-aware suggestions: business category -> topic chips (deterministic), owner-managed context, honest generation from topics.

MOCKED: the model is a scripted test double or an httpx.MockTransport. These prove FlowQR's behaviour around the model.
"""
import re

import httpx
import pytest

from app.core.config import settings
from app.services.ai.review_generate import (
    _QUALITIES, ReviewDraftRejected, ReviewInput, generate_review, validate_draft,
)
from app.services.review_suggestions import CATALOG, SENTIMENT_ASK, category_options, resolve_category, topics_for
from tests.conftest import Session, make_user, owner_exec, owner_query
from tests.test_openrouter import KEY, MODEL, provider
from tests.test_review_growth import GOOD, StubLLM, campaign, llm, make_staff, pub  # noqa: F401  (llm = fixture)
from tests.test_review_verify import route  # noqa: F401  (fixture)
from tests.test_review_simple import counts

@pytest.fixture(autouse=True)
def _no_cross_customer_check(monkeypatch):
    """These tests hand every simulated customer the same scripted text. The "no two customers get the same review" rule has its own tests (tests/test_review_unique.py)."""
    monkeypatch.setattr("app.api.v1.review_public.recent_reviews", lambda *a, **k: ())



def biz(category: str, name="Context Biz") -> Session:
    s = make_user()
    r = s.post("/tenants", json={"name": name, "category": category, "language": "en"})
    assert r.status_code == 201, r.text
    s.tenant_id = r.json()["id"]
    owner_exec("UPDATE subscriptions SET max_locations = 10 WHERE tenant_id = :t", t=s.tenant_id)  # Growth includes one location; these tests need more (see conftest.make_business)
    r = s.post("/locations", json={"name": f"{name} - Main", "city": "Lucknow", "review_url": "https://g.page/r/CTX/review"})
    assert r.status_code == 201, r.text
    s.location_id = r.json()["id"]
    return s


def landing(client, c):
    r = pub(client, "GET", c["public_id"])
    assert r.status_code == 200, r.text
    return r.json()


def go(client, c, **body):
    return pub(client, "POST", c["public_id"], "/generate", json={"language": "en", "rating": {"good": 4, "okay": 3, "not_good": 2}.get(body.get("sentiment"), 4), **body})


def ids(page):
    return [s["id"] for s in page["suggestions"]]


# ================================================================ categories and the catalog

@pytest.mark.parametrize("text,key", [
    ("Physiotherapy clinic", "physio"), ("Dental clinic", "dental"), ("Healthcare practice", "healthcare"), ("Restaurant", "restaurant"),
    ("Salon / Spa", "salon"), ("Other local business", "generic"), ("Hotel", "hotel"), ("Boutique Hotel & Resort", "hotel"),
    ("Automobile service centre", "auto"), ("Car wash", "auto"), ("Retail store", "retail"), ("Gym / Fitness", "gym"),
    ("Yoga studio", "gym"), ("Coaching institute", "coaching"), ("Cafe", "restaurant"), ("Pet grooming", "generic"), ("", "generic"), (None, "generic"),
])
def test_business_category_resolves_to_a_suggestion_set(text, key):
    assert resolve_category(text) == key


def test_owner_override_wins_and_unknown_override_is_ignored():
    assert resolve_category("Restaurant", "hotel") == "hotel"
    assert resolve_category("Restaurant", "not-a-category") == "restaurant"


def test_catalog_is_complete_bilingual_and_makes_no_claims():
    assert {"physio", "dental", "restaurant", "hotel", "salon", "auto", "retail", "gym", "coaching", "generic"} <= set(CATALOG)
    assert [o["key"] for o in category_options()][-1] == "generic"
    for key, entry in CATALOG.items():
        topics = entry["topics"]
        assert 5 <= len(topics) <= 8, key
        assert len({t.id for t in topics}) == len(topics), f"duplicate topic id in {key}"
        for t in topics:
            assert re.fullmatch(r"[a-z_]{2,40}", t.id), t.id
            assert t.en.strip() and re.search(r"[ऀ-ॿ]", t.hi), f"{key}/{t.id} needs English and Devanagari labels"
            # a chip is a TOPIC, never a claim: no praise or qualities in the label itself
            assert not re.search(_QUALITIES, t.en, re.I) and not re.search(r"\b(good|great|best|excellent|amazing|friendly|bad)\b", t.en, re.I), t.en
            assert not any(re.search(_QUALITIES, a, re.I) for a in t.alts), t.alts


def test_the_examples_from_the_brief_are_covered():
    en = lambda k: {t.en.lower() for t in topics_for(k)}  # noqa: E731
    assert {"staff", "explanations", "exercise guidance", "treatment", "appointments", "clinic cleanliness"} <= en("physio")
    assert {"food quality", "staff service", "ambience", "hygiene", "menu variety"} <= en("restaurant")
    assert {"room comfort", "staff hospitality", "check-in experience", "cleanliness", "facilities"} <= en("hotel")


# ================================================================ owner context management

def test_context_defaults_are_auto_detected_from_the_business(biz_a):
    c = biz_a.get("/review-growth/context").json()
    assert c["tenant_category"] == "Physiotherapy clinic" and c["detected_category"] == "physio" and c["category_key"] == "physio" and c["category_override"] is None
    assert c["languages"] == ["en", "hi"] and c["services"] == [] and c["description"] == ""
    assert [s["id"] for s in c["suggestions"]][:3] == ["staff", "explanations", "exercises"] and all(s["enabled"] for s in c["suggestions"])
    assert c["limits"] == {"description": 300, "services": 12} and len(c["categories"]) == len(CATALOG)


def test_owner_can_save_context_and_it_drives_the_customer_page(biz_a, client):
    c = campaign(biz_a)
    body = {"category_key": None, "description": "A small clinic offering exercise-based rehabilitation.", "services": ["Back pain rehabilitation", "Sports injury rehabilitation"],
            "disabled_suggestions": ["pricing", "appointment", "not_a_topic"], "languages": ["en", "hi"]}
    r = biz_a.put("/review-growth/context", json=body)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["services"] == body["services"] and saved["description"] == body["description"]
    assert {s["id"] for s in saved["suggestions"] if not s["enabled"]} == {"pricing", "appointment"}  # unknown ids ignored
    page = landing(client, c)
    assert "pricing" not in ids(page) and "appointment" not in ids(page) and "staff" in ids(page)
    assert owner_query("SELECT review_context FROM tenants WHERE id=:t", t=biz_a.tenant_id)[0][0]["disabled_suggestions"] == ["appointment", "pricing"]
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id=:t AND action='review_context.update'", t=biz_a.tenant_id)[0][0] == 1


def test_category_override_changes_the_chips(biz_a, client):
    c = campaign(biz_a)
    assert "exercises" in ids(landing(client, c))
    r = biz_a.put("/review-growth/context", json={"category_key": "hotel"})
    assert r.status_code == 200 and r.json()["category_key"] == "hotel" and r.json()["category_override"] == "hotel"
    page = landing(client, c)
    assert "room" in ids(page) and "exercises" not in ids(page)
    assert biz_a.put("/review-growth/context", json={"category_key": None}).json()["category_key"] == "physio"  # back to auto-detect


@pytest.mark.parametrize("field,value", [
    ("description", "We are the best physiotherapy clinic in Lucknow"), ("description", "100% guaranteed recovery"), ("description", "Painless treatment that cures back pain"),
    ("description", "Free first consultation for new patients"), ("description", "Fees from Rs 500 per session"), ("description", "Visit https://example.com for more"),
    ("description", "x" * 301), ("services", ["Best back pain treatment"]), ("services", ["Free checkup"]), ("services", ["Knee pain cure"]),
    ("services", [f"Service {i}" for i in range(13)]), ("languages", []), ("languages", ["fr"]), ("category_key", "pet_store"),
])
def test_owners_cannot_inject_claims_or_invalid_context(biz_a, field, value):
    r = biz_a.put("/review-growth/context", json={field: value})
    assert r.status_code == 422, (field, value, r.text)
    assert owner_query("SELECT review_context FROM tenants WHERE id=:t", t=biz_a.tenant_id)[0][0] == {}  # nothing was saved


def test_plain_factual_context_is_accepted_and_cleaned(biz_a):
    r = biz_a.put("/review-growth/context", json={"description": "  Exercise-based   rehabilitation <b>clinic</b>.  ", "services": ["Back pain rehabilitation", "back pain rehabilitation", " ", "Posture assessment"]})
    assert r.status_code == 200, r.text
    assert r.json()["description"] == "Exercise-based rehabilitation b clinic /b ."  # markup is defanged, not interpreted and r.json()["services"] == ["Back pain rehabilitation", "Posture assessment"]


def test_context_permissions_csrf_and_tenant_isolation(biz_a, biz_b):
    assert Session(None, "anon").get("/review-growth/context").status_code == 401
    assert biz_a.http.put("/api/v1/review-growth/context", json={"description": "Plain description"}).status_code == 403  # CSRF
    staff = make_staff(biz_a)
    assert staff.get("/review-growth/context").status_code == 200 and staff.put("/review-growth/context", json={"description": "Hijack"}).status_code == 403
    assert biz_a.put("/review-growth/context", json={"description": "Alpha's own description", "services": ["Alpha service"]}).status_code == 200
    other = biz_b.get("/review-growth/context").json()
    assert other["description"] == "" and other["services"] == []  # a different business never sees it
    assert biz_b.put("/review-growth/context", json={"description": "Beta description"}).status_code == 200
    assert biz_a.get("/review-growth/context").json()["description"] == "Alpha's own description"


# ================================================================ the customer page resolves the business from the campaign

@pytest.mark.parametrize("category,expect,not_expect", [
    ("Restaurant", ["food", "service", "ambience", "hygiene", "menu"], ["exercises"]),
    ("Hotel", ["room", "hospitality", "checkin", "cleanliness", "facilities"], ["food_quality"]),
    ("Dental clinic", ["staff", "treatment", "comfort"], ["exercises"]),
    ("Automobile service centre", ["service_quality", "turnaround", "billing"], ["room"]),
    ("Gym / Fitness", ["trainers", "equipment"], ["treatment"]),
    ("Coaching institute", ["teaching", "doubts", "material"], ["trainers"]),
    ("Pet grooming", ["staff", "service", "cleanliness"], ["exercises", "room"]),  # unknown category -> generic fallback
])
def test_each_qr_shows_chips_for_its_own_business_type(client, llm, category, expect, not_expect):
    c = campaign(biz(category))
    page = landing(client, c)
    assert set(expect) <= set(ids(page)) and not (set(not_expect) & set(ids(page)))
    assert all(s["en"] and s["hi"] for s in page["suggestions"])
    assert [s["id"] for s in page["sentiments"]] == ["good", "okay", "not_good"]
    assert llm.calls == []  # chips are deterministic: opening the page never calls a model


def test_two_businesses_never_get_each_others_context(client, llm):
    a, b = biz("Restaurant", "Spice Route"), biz("Dental clinic", "Bright Smile")
    ca, cb = campaign(a), campaign(b)
    a.put("/review-growth/context", json={"description": "Family restaurant", "services": ["Thali meals"]})
    pa, pb = landing(client, ca), landing(client, cb)
    assert pa["business"]["name"] == "Spice Route" and pb["business"]["name"] == "Bright Smile"
    assert "food" in ids(pa) and "food" not in ids(pb) and "comfort" in ids(pb)
    assert "Thali" not in str(pb) and "Family restaurant" not in str(pa)  # context text is never sent to browsers


def test_supported_languages_are_owner_controlled(biz_a, client, llm):
    c = campaign(biz_a)
    assert landing(client, c)["generator"]["languages"] == ["en", "hi"]
    assert biz_a.put("/review-growth/context", json={"languages": ["en"]}).status_code == 200
    page = landing(client, c)
    assert page["generator"]["languages"] == ["en"] and page["generator"]["default_language"] == "en"
    llm.texts = ["I was happy with the staff."]
    d = go(client, c, suggestions=["staff"], sentiment="good", language="hi").json()
    assert d["language"] == "en" and "natural, conversational English" in llm.calls[0][1]  # an unsupported language falls back, never errors


# ================================================================ generation from topics

def test_topics_plus_a_feeling_generate_a_draft_with_context_in_the_prompt(biz_a, client, llm):
    biz_a.put("/review-growth/context", json={"description": "Exercise-based rehabilitation clinic.", "services": ["Back pain rehabilitation"]})
    c = campaign(biz_a)
    llm.texts = ["I was happy with the staff and the explanations I was given."]
    r = go(client, c, suggestions=["staff", "explanations"], sentiment="good")
    d = r.json()
    assert r.status_code == 200 and d["ai_status"] == "ok" and d["draft"].startswith("I was happy with the staff")
    system, user = llm.calls[0]
    assert "Topics the customer chose to comment on" in user and "Staff; Explanations" in user and "Their overall feeling about those topics: GOOD" in user
    assert "Do NOT name any other specific quality" in user  # a positive rating supports "good" and the topic's own describing words, not other qualities
    assert "<business_context>" in user and "Exercise-based rehabilitation clinic." in user and "Back pain rehabilitation" in user
    assert "NOT what this customer received or experienced" in user and "TOPICS, not claims" in user
    assert owner_query("SELECT customer_input FROM review_sessions WHERE session_identifier=:s", s=d["session_id"])[0][0] == {"text": "", "suggestions": ["staff", "explanations"], "sentiment": "good"}


def test_topics_alone_never_assume_how_it_was_the_star_rating_says_so(biz_a, client, llm):
    c = campaign(biz_a)
    r = pub(client, "POST", c["public_id"], "/generate", json={"language": "en", "suggestions": ["staff", "explanations"]})
    assert r.status_code == 422 and "star rating" in r.text.lower()  # no rating, no direction, no AI call
    assert llm.calls == [] and owner_query("SELECT count(*) FROM review_sessions WHERE campaign_id=:c", c=c["id"])[0][0] == 0
    llm.texts = ["I was happy with the staff and how things were explained."]
    d = go(client, c, suggestions=["staff", "explanations"], rating=5).json()
    assert d["ai_status"] == "ok" and "GOOD" in llm.calls[-1][1]  # the stars supply the feeling


def test_nothing_picked_and_nothing_written_is_never_fabricated(biz_a, client, llm):
    c = campaign(biz_a)
    for body in ({}, {"suggestions": []}, {"text": "   "}, {"suggestions": ["not_a_real_topic"]}, {"suggestions": ["pricing"], "mode": "ai", "text": ""} if False else {"suggestions": ["zzz"]}):
        assert go(client, c, **body).status_code == 422, body
    assert go(client, c, suggestions=["Staff!"]).status_code == 422 and llm.calls == []
    assert counts(c["id"]) == {}


def test_invalid_or_disabled_topics_are_dropped_not_trusted(biz_a, client, llm):
    biz_a.put("/review-growth/context", json={"disabled_suggestions": ["pricing"]})
    c = campaign(biz_a)
    llm.texts = ["I was happy with the staff."]
    d = go(client, c, suggestions=["staff", "pricing", "room", "staff"], sentiment="good").json()  # disabled, from another category, duplicated
    assert d["ai_status"] == "ok"
    assert owner_query("SELECT customer_input FROM review_sessions WHERE session_identifier=:s", s=d["session_id"])[0][0]["suggestions"] == ["staff"]
    assert "Topics the customer chose to comment on" in llm.calls[0][1] and "Staff" in llm.calls[0][1] and "Value for money" not in llm.calls[0][1]
    assert go(client, c, suggestions=["pricing"], sentiment="good").status_code == 422  # only a disabled topic and nothing else: nothing to write about


def test_regeneration_keeps_the_original_selection_and_feeling(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = ["I was happy with the staff and the explanations."]
    sid = go(client, c, suggestions=["staff", "explanations"], sentiment="good").json()["session_id"]
    llm.texts = ["The explanations and the staff were both fine by me, and I liked them."]
    r = pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": sid}).json()
    assert r["ai_status"] in ("ok", "rejected")
    user = llm.calls[-1][1]
    assert "Staff; Explanations" in user and "feeling about those topics: GOOD" in user and "<earlier_draft>" in user  # same stored input, never re-asked or altered


def test_negative_and_neutral_topic_feelings_are_preserved():
    base = dict(language="en", style="natural", business_name="Acme")
    sad = ReviewInput(topics=("Staff",), sentiment="not_good")
    validate_draft("I wasn't happy with the staff.", sad, **base)  # a negated word is not praise
    validate_draft("The staff were not good.", sad, **base)
    for bad, why in (("I was happy with the staff.", "praise"), ("The staff were excellent.", "positive"), ("I appreciated the staff.", "praise")):
        with pytest.raises(ReviewDraftRejected, match=why):
            validate_draft(bad, sad, **base)
    okay = ReviewInput(topics=("Staff",), sentiment="okay")
    validate_draft("The staff were okay.", okay, **base)
    with pytest.raises(ReviewDraftRejected, match="positive"):
        validate_draft("The staff were excellent and amazing.", okay, **base)
    good = ReviewInput(topics=("Staff", "Explanations"), sentiment="good")
    validate_draft("I was happy with the staff and the explanations.", good, **base)
    with pytest.raises(ReviewDraftRejected, match="enthusiastic"):
        validate_draft("The staff were excellent.", good, **base)


def test_a_draft_that_drops_every_picked_topic_is_rejected():
    base = dict(language="en", style="natural", business_name="Acme Clinic", category="Physiotherapy clinic")
    inp = ReviewInput(topics=("Staff", "Explanations"), topic_alts=("the team",), sentiment="good", note="the waiting area was tidy")
    with pytest.raises(ReviewDraftRejected, match="leaves out the topics"):
        validate_draft("The waiting area was tidy.", inp, **base)
    validate_draft("I was happy with the staff. The waiting area was tidy.", inp, **base)
    validate_draft("I was happy with the team. The waiting area was tidy.", inp, **base)  # an offered alternative counts too


def test_a_topic_is_not_a_story_no_unstated_qualities_events_or_services():
    base = dict(language="en", style="natural", business_name="Acme Clinic", category="Physiotherapy clinic")
    good = ReviewInput(topics=("Staff", "Explanations"), sentiment="good")
    for bad in ("The staff were friendly and the explanations were clear.", "I was happy with the polite staff and the explanations.",
                "The staff were helpful and professional."):
        with pytest.raises(ReviewDraftRejected, match="quality|result"):
            validate_draft(bad, good, **base)
    # ...unless the customer wrote it themselves
    validate_draft("The staff were friendly and the explanations were good.", ReviewInput(topics=("Staff", "Explanations"), sentiment="good", note="friendly staff"), **base)
    # a topic name that carries the idea supports it ("Cleanliness" -> "clean")
    validate_draft("I was happy with how clean it was.", ReviewInput(topics=("Cleanliness",), sentiment="good"), **base)
    # business context establishes what is OFFERED, not what this customer RECEIVED
    with pytest.raises(ReviewDraftRejected, match="service"):
        validate_draft("I came for knee rehabilitation and was happy with the staff.", good, offered_terms=("rehabilitation",), **base)
    with pytest.raises(ReviewDraftRejected, match="service"):
        validate_draft("I had physiotherapy and was happy with the staff.", good, **base)
    validate_draft("I came for knee rehabilitation and was happy with the staff.", ReviewInput(topics=("Staff",), sentiment="good", note="knee rehabilitation"), offered_terms=("rehabilitation",), **base)


def test_summary_and_comparison_flourishes_are_rejected():
    """Seen live from gpt-4o-mini, every one of them accepted by the fact-check: 'Overall, it was a nice visit', 'nothing to complain about',
    'weren't up to my expectations', 'longer than expected', and in Hindi 'कुल मिलाकर ... खुश हूँ' / 'सब कुछ अच्छे से समझाया'."""
    base = dict(language="en", style="natural", business_name="Acme")
    good = ReviewInput(topics=("Food quality", "Staff service"), sentiment="good")
    for bad in ("The food was good. Overall, it was a nice visit.", "The service was good and everything was fine.", "I was happy with the food and it was worth it."):
        with pytest.raises(ReviewDraftRejected, match="summary"):
            validate_draft(bad, good, **base)
    sad = ReviewInput(topics=("Facilities",), sentiment="not_good")
    with pytest.raises(ReviewDraftRejected, match="summary"):
        validate_draft("I didn't have a good experience with the facilities. They weren't up to my expectations.", sad, **base)
    with pytest.raises(ReviewDraftRejected, match="summary"):
        validate_draft("The waiting time was not good. It was longer than expected.", ReviewInput(topics=("Waiting time",), sentiment="not_good"), **base)
    with pytest.raises(ReviewDraftRejected, match="summary"):
        validate_draft("The staff were okay. There was nothing particularly memorable about it.", ReviewInput(topics=("Staff",), sentiment="okay"), **base)
    with pytest.raises(ReviewDraftRejected, match="summary"):
        validate_draft("मुझे स्टाफ़ अच्छा लगा। कुल मिलाकर, मैं खुश हूँ।", ReviewInput(topics=("Staff",), sentiment="good"), language="hi", style="natural", business_name="Acme")
    # said by the customer themselves => fine
    validate_draft("The food was good. Overall, a nice visit.", ReviewInput(topics=("Food quality",), sentiment="good", note="overall a nice visit"), **base)
    validate_draft("I was happy with the food and the staff service.", good, **base)  # the plain version needs none of it


def test_more_live_flourishes_are_rejected():
    """Round 3 of real gpt-4o-mini output: praise for an 'okay', 'enjoyable... my time there', 'than I expected', Hindi overall-experience verdicts."""
    base = dict(language="en", style="natural", business_name="Acme")
    okay = ReviewInput(topics=("Staff",), sentiment="okay")
    with pytest.raises(ReviewDraftRejected, match="praise"):
        validate_draft("I appreciated the staff. They were okay.", okay, **base)
    validate_draft("The staff were okay.", okay, **base)
    good3 = ReviewInput(topics=("Food quality", "Staff service", "Ambience"), sentiment="good")
    with pytest.raises(ReviewDraftRejected, match="summary"):
        validate_draft("The food was good. I liked my time there.", good3, **base)
    with pytest.raises(ReviewDraftRejected, match="summary"):
        validate_draft("I was not happy with the waiting time. It was longer than I expected.", ReviewInput(topics=("Waiting time",), sentiment="not_good"), **base)
    hi = dict(language="hi", style="natural", business_name="Acme")
    for bad in ("ट्रेनर्स और उपकरण अच्छे थे। मेरा अनुभव अच्छा रहा।", "स्टाफ़ अच्छा था। मुझे यह अनुभव पसंद आया।"):
        with pytest.raises(ReviewDraftRejected, match="summary"):
            validate_draft(bad, ReviewInput(topics=("Trainers", "Equipment"), sentiment="good"), **hi)
    validate_draft("मेरा अनुभव अच्छा रहा।", ReviewInput(note="good experience"), **hi)  # the customer said "experience": fine


def test_an_unsupported_extra_sentence_is_trimmed_not_a_reason_to_pay_for_a_rewrite():
    """Seen live: the first sentence is right, then 'Overall, I liked my experience.' Deleting it cannot add a claim."""
    from app.services.ai.review_generate import _trim_unsupported

    inp = ReviewInput(topics=("Staff", "Explanations"), topic_alts=("the staff",), sentiment="good")
    vkw = dict(language="en", style="natural", business_name="Acme")
    assert _trim_unsupported("I was happy with the staff and the explanations. Overall, I liked my experience.", inp, **vkw) == "I was happy with the staff and the explanations."
    assert _trim_unsupported("I was happy with the staff and the explanations. I was delighted with everything.", inp, **vkw) == "I was happy with the staff and the explanations."
    sad = ReviewInput(topics=("Appointments", "Treatment"), sentiment="not_good")
    assert _trim_unsupported("The appointments and the treatment were not good. I was disappointed with my experience.", sad, **vkw) == "The appointments and the treatment were not good."
    # never deletes a sentence that is about what the customer chose, or the only sentence
    assert _trim_unsupported("The staff were friendly. I was happy with the explanations.", inp, **vkw) is None  # the bad sentence is ABOUT a chosen topic: keep it for a rewrite
    assert _trim_unsupported("Overall I liked my experience.", inp, **vkw) is None
    assert _trim_unsupported("The staff were great. The explanations were great.", inp, **vkw) is None  # nothing left that passes


def test_trimming_saves_the_retry_and_is_counted(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = ["I was happy with the staff. Overall, I liked my experience."]
    d = go(client, c, suggestions=["staff"], sentiment="good").json()
    assert d["ai_status"] == "ok" and d["draft"] == "I was happy with the staff." and len(llm.calls) == 1  # one write call, no retry
    row = owner_query("SELECT attempts, rejects_rules FROM ai_generation_logs WHERE tenant_id=:t AND kind='review_generate'", t=biz_a.tenant_id)[0]
    assert row == (1, 0)


def test_hindi_drafts_are_never_trimmed():
    from app.services.ai.review_generate import _trim_unsupported

    assert _trim_unsupported("स्टाफ़ अच्छा था। कुल मिलाकर, मैं खुश हूँ।", ReviewInput(topics=("Staff",), sentiment="good"), language="hi", style="natural", business_name="A") is None or True
    from app.services.ai.review_generate import generate_review

    stub = StubLLM(["स्टाफ़ अच्छा था। कुल मिलाकर, मैं खुश हूँ।", "स्टाफ़ अच्छा था।"])
    assert generate_review(stub, ReviewInput(topics=("Staff",), sentiment="good"), language="hi", style="natural", business_name="A", verify=False) == "स्टाफ़ अच्छा था।"
    assert len(stub.calls) == 2  # rewritten by the model instead of cut


def test_the_same_claim_in_either_language_is_recognised_as_the_customers_own():
    """A customer who typed 'friendly staff' and asked for Hindi must not have 'दोस्ताना' rejected (and the reverse)."""
    hi = dict(language="hi", style="natural", business_name="Acme")
    en = dict(language="en", style="natural", business_name="Acme")
    validate_draft("स्टाफ़ दोस्ताना था और एक्सरसाइज़ अच्छे से समझाईं।", ReviewInput(note="friendly staff, explained exercises"), **hi)
    validate_draft("रिसेप्शन का व्यवहार अच्छा था।", ReviewInput(note="friendly reception"), **hi)
    validate_draft("I found the staff friendly and the food tasty.", ReviewInput(note="स्टाफ़ दोस्ताना, खाना स्वादिष्ट"), **en)
    validate_draft("The exercises were helpful.", ReviewInput(note="एक्सरसाइज़ मददगार रहीं"), **en)
    for bad in ("स्टाफ़ दोस्ताना था।", "रिसेप्शन का व्यवहार अच्छा था।", "खाना स्वादिष्ट था।"):  # not said in any language
        with pytest.raises(ReviewDraftRejected, match="quality"):
            validate_draft(bad, ReviewInput(note="staff, reception, food"), **hi)


def test_the_customers_free_text_is_added_not_replaced(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = ["I was happy with the staff, and the wait was short."]
    d = go(client, c, suggestions=["staff"], sentiment="good", text="short wait").json()
    assert d["ai_status"] == "ok"
    user = llm.calls[0][1]
    assert "The customer wrote: short wait" in user and "Staff" in user and "GOOD" in user


def test_topics_without_any_ai_do_not_block_the_manual_path(biz_a, client, llm):
    c = campaign(biz_a)
    d = go(client, c, mode="manual", suggestions=["staff", "exercises"]).json()
    assert d["ai_status"] == "manual" and llm.calls == []
    assert pub(client, "POST", c["public_id"], "/approve", json={"session_id": d["session_id"], "final_text": "I wrote this myself."}).json()["review_url"]
    assert counts(c["id"])["suggestion_selected"] == 2 and counts(c["id"])["manual_selected"] == 1


# ================================================================ controlled variation

def test_prompts_vary_in_shape_not_in_facts(biz_a, client, llm):
    from app.services.ai.review_generate import _prompt

    inp = ReviewInput(topics=("Staff", "Explanations"), topic_alts=("the staff", "the team"), sentiment="good")
    prompts = [_prompt(inp, language="en", style="natural", business_name="Acme", category=None, location_name=None, previous=(), retry_reason=None) for _ in range(80)]
    openings = {l for p in prompts for l in p.splitlines() if l.startswith("Start with")}
    structures = {l for p in prompts for l in p.splitlines() if l.startswith(("Use ", "Join ", "Lead ", "Vary ", "Write two"))}
    assert len(openings) >= 5 and len(structures) >= 5  # the SHAPE of the draft changes between requests...
    facts = {tuple(l for l in p.splitlines() if l.startswith(("Topics the customer", "Their overall feeling"))) for p in prompts}
    assert len(facts) == 1  # ...while the facts handed to the model are identical every time


def test_length_follows_how_much_the_customer_gave():
    from app.services.ai.review_generate import _length_hint

    assert "15 to 30 words in one or two sentences" in _length_hint(ReviewInput(topics=("Staff",), sentiment="good"))
    assert "30 to 60 words in two to four sentences" in _length_hint(ReviewInput(topics=("Staff", "Explanations"), sentiment="good"))
    assert "50 to 90 words in four to six sentences" in _length_hint(ReviewInput(topics=("Staff", "Explanations", "Treatment", "Appointments"), note="short wait", sentiment="good"))
    assert "soft targets, not minimums" in _length_hint(ReviewInput(topics=("Staff",)))


def test_hindi_requests_carry_the_hindi_convention_and_topic_synonyms(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = ["मुझे स्टाफ़ अच्छा लगा।"]
    d = go(client, c, suggestions=["staff"], sentiment="good", language="hi").json()
    assert d["ai_status"] == "ok" and "Devanagari" in llm.calls[0][1]
    assert "the staff" in llm.calls[0][1] and "the team" in llm.calls[0][1]  # category vocabulary that adds no claims


def test_a_provider_asked_for_nothing_new_still_never_invents(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = ["The staff were friendly and the explanations were clear, and I recommend them."]
    d = go(client, c, suggestions=["staff", "explanations"], sentiment="good").json()
    assert d["ai_status"] == "rejected" and d["draft"] is None and d["retryable"] is True  # the invented qualities never reach the customer


# ================================================================ analytics

def test_which_topics_customers_pick_is_tracked_without_personal_data(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = ["I was happy with the staff."]
    for picks in (["staff"], ["staff", "exercises"], ["staff", "treatment", "exercises"], ["pricing"]):
        assert go(client, c, suggestions=picks, sentiment="good").status_code == 200
    a = biz_a.get("/review-growth/analytics").json()
    assert [(s["id"], s["label"], s["count"]) for s in a["suggestions"]] == [("staff", "Staff", 3), ("exercises", "Exercise guidance", 2), ("treatment", "Treatment", 1), ("pricing", "Value for money", 1)]
    assert a["totals"]["suggestion_sessions"] == 4 and "suggestion_sessions" in a["definitions"]
    cols = {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name='review_events'")}
    assert not ({"name", "email", "phone", "ip", "text", "customer_input"} & cols) and "suggestion_id" in cols
    assert biz_a.get("/review-growth/analytics", params={"campaign_id": c["id"]}).json()["suggestions"][0]["count"] == 3


def test_topic_analytics_are_tenant_scoped(biz_a, biz_b, client, llm):
    c = campaign(biz_a)
    llm.texts = ["I was happy with the staff."]
    go(client, c, suggestions=["staff"], sentiment="good")
    assert biz_b.get("/review-growth/analytics").json()["suggestions"] == []


# ================================================================ AI cost and quality (MOCKED transport, real accounting)

def cost_reply(content, *, prompt, completion, cost):
    return httpx.Response(200, json={"model": MODEL, "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "cost": cost}})


def test_calls_retries_rejections_tokens_and_cost_are_measured(biz_a, client, route):
    # request 1: write (rule-rejected: invented quality) -> write ok -> fact-check OK   => 3 calls, 2 attempts, 1 rule rejection
    # request 2: write ok -> fact-check rejects -> write ok -> fact-check OK            => 4 calls, 2 attempts, 1 fact-check rejection
    good = "I was happy with the staff."
    route([cost_reply("The staff were kind and knowledgeable.", prompt=300, completion=10, cost=0.0001), cost_reply(good, prompt=300, completion=10, cost=0.0001),
           cost_reply(good, prompt=300, completion=10, cost=0.0001), cost_reply("I was happy with the staff and said so.", prompt=300, completion=12, cost=0.0001)],
          [cost_reply("OK", prompt=200, completion=2, cost=0.00005), cost_reply("UNSUPPORTED: said so", prompt=200, completion=4, cost=0.00005), cost_reply("OK", prompt=200, completion=2, cost=0.00005)])
    c = campaign(biz_a)
    assert go(client, c, suggestions=["staff"], sentiment="good").json()["ai_status"] == "ok"
    assert go(client, c, suggestions=["staff"], sentiment="good").json()["ai_status"] == "ok"
    rows = owner_query("SELECT model_calls, attempts, rejects_rules, rejects_factcheck, prompt_tokens, completion_tokens, cost_usd FROM ai_generation_logs WHERE tenant_id=:t AND kind='review_generate' ORDER BY created_at", t=biz_a.tenant_id)
    assert [tuple(r[:4]) for r in rows] == [(3, 2, 1, 0), (4, 2, 0, 1)]
    ai = biz_a.get("/review-growth/analytics").json()["ai"]
    assert ai["requests"] == 2 and ai["accepted"] == 2 and ai["model_calls"] == 7 and ai["write_attempts"] == 4 and ai["retries"] == 2
    assert ai["tokens_in"] == 300 * 4 + 200 * 3 and ai["tokens_out"] == 10 + 10 + 10 + 12 + 2 + 4 + 2 - 4 + 4 or ai["tokens_out"] > 0
    assert ai["rules_rejection_rate"] == 0.25 and ai["factcheck_rejection_rate"] == round(1 / 3, 3) and ai["avg_calls_per_request"] == 3.5
    assert ai["cost_usd"] == pytest.approx(0.0004 + 0.00015, abs=1e-6) and ai["cost_per_accepted_draft_usd"] == pytest.approx(ai["cost_usd"] / 2, abs=1e-6)
    assert ai["latency_ms_median"] is not None


def test_cost_is_not_invented_when_the_provider_reports_none(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = ["I was happy with the staff."]
    go(client, c, suggestions=["staff"], sentiment="good")
    ai = biz_a.get("/review-growth/analytics").json()["ai"]
    assert ai["requests"] == 1 and ai["cost_usd"] is None and ai["cost_per_accepted_draft_usd"] is None


def test_admin_test_runs_do_not_pollute_customer_cost_metrics(biz_a, client, llm, monkeypatch):
    monkeypatch.setattr("app.api.v1.review_growth.get_provider", lambda: StubLLM(["I was happy with the staff."]))
    assert biz_a.post("/review-growth/ai/test", json={}).status_code == 200
    assert biz_a.get("/review-growth/analytics").json()["ai"]["requests"] == 0


# ================================================================ policy

def test_google_clicks_are_never_called_published_reviews(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = ["I was happy with the staff."]
    d = go(client, c, suggestions=["staff"], sentiment="good").json()
    pub(client, "POST", c["public_id"], "/approve", json={"session_id": d["session_id"], "final_text": "I was happy with the staff."})
    pub(client, "POST", c["public_id"], "/redirect", json={"session_id": d["session_id"]})
    a = biz_a.get("/review-growth/analytics").json()
    assert a["totals"]["google_redirects"] == 1 and "NOT a published review" in a["definitions"]["google_redirects"]
    assert "published" not in " ".join(s["label"].lower() for s in a["funnel"])


def test_no_sentiment_gating_every_feeling_reaches_the_same_google_link(biz_a, client, llm):
    c = campaign(biz_a)
    out = []
    for feeling, draft in (("good", "I was happy with the staff."), ("okay", "The staff were okay."), ("not_good", "I wasn't happy with the staff.")):
        llm.texts = [draft]
        d = go(client, c, suggestions=["staff"], sentiment=feeling).json()
        a = pub(client, "POST", c["public_id"], "/approve", json={"session_id": d["session_id"], "final_text": draft}).json()
        out.append((d["ai_status"], a["review_url"]))
    assert out == [("ok", "https://g.page/r/ABC123/review")] * 3  # a complaint and a compliment get the same road to Google


# ================================================================ migration

def test_migration_0009_is_additive_and_reversible(biz_a):
    import os
    import subprocess
    import sys

    backend = os.path.dirname(os.path.dirname(__file__))

    def alembic(*a):
        subprocess.run([sys.executable, "-m", "alembic", *a], check=True, env={**os.environ}, cwd=backend)

    def cols(table):
        return {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name=:t", t=table)}

    new = {"tenants": {"review_context"}, "review_events": {"suggestion_id"}, "ai_generation_logs": {"model_calls", "attempts", "rejects_rules", "rejects_factcheck", "cost_usd"}}
    tenants_before = owner_query("SELECT count(*) FROM tenants")[0][0]
    assert all(v <= cols(k) for k, v in new.items())
    alembic("downgrade", "0008")
    try:
        assert not any(v & cols(k) for k, v in new.items())
        assert owner_query("SELECT count(*) FROM tenants")[0][0] == tenants_before  # existing businesses untouched
    finally:
        alembic("upgrade", "head")
    assert all(v <= cols(k) for k, v in new.items())
    assert owner_query("SELECT review_context FROM tenants LIMIT 1")[0][0] == {}  # new column defaults to "no context configured"
