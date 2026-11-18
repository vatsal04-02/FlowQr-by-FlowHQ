"""The single-input review journey: type a few words -> "Help me write" (or "I'll write it myself") -> edit -> confirm -> Google.

MOCKED: the model is a scripted test double (StubLLM) or an httpx.MockTransport. These prove FlowQR's behaviour around the model.
Real-model behaviour is measured separately against the live provider and reported as such.
"""
import time

import httpx
import pytest

from app.core.config import settings
from app.services.ai import health
from app.services.ai.review_generate import CLARIFY, ReviewDraftRejected, ReviewInput, is_too_vague, validate_draft
from tests.conftest import Session, make_business, owner_query
from tests.test_openrouter import KEY, MODEL, provider, reply, use  # noqa: F401  (use = fixture)
from tests.test_review_growth import GOOD, UA, StubLLM, campaign, llm, pub  # noqa: F401  (llm = fixture)

KEYWORDS = "back pain, friendly staff, explained exercises clearly"
EN_DRAFT = "I visited the clinic for back pain. The staff were friendly and explained the exercises clearly."
HI_DRAFT = "मैं पीठ दर्द के लिए क्लिनिक गया था। स्टाफ़ दोस्ताना था और उन्होंने एक्सरसाइज़ अच्छे से समझाईं।"


def go(client, c, text, **over):
    return pub(client, "POST", c["public_id"], "/generate", json={"text": text, "language": "en", "rating": {"good": 4, "okay": 3, "not_good": 2}.get(over.get("sentiment"), 4), **over})


def counts(campaign_id):
    return dict(owner_query("SELECT event_type, count(*) FROM review_events WHERE campaign_id=:c GROUP BY event_type", c=campaign_id))


# ================================================================ 1-3. keywords -> natural draft, per language

def test_english_keywords_become_a_natural_english_draft(biz_a, client, llm):
    llm.texts = [EN_DRAFT]
    r = go(client, campaign(biz_a), KEYWORDS)
    d = r.json()
    assert r.status_code == 200 and d["ai_status"] == "ok" and d["draft"] == EN_DRAFT and d["retryable"] is False
    system, user = llm.calls[0]
    assert f"The customer wrote: {KEYWORDS}" in user and "natural, conversational English" in user
    assert "keywords or fragments" in system and "NEEDS_MORE" in system and "Do not assume the visit was positive" in system
    stored = owner_query("SELECT customer_input FROM review_sessions ORDER BY created_at DESC LIMIT 1")[0][0]
    assert stored == {"text": KEYWORDS}  # one free-text field, nothing else collected


def test_hindi_keywords_become_a_hindi_draft(biz_a, client, llm):
    llm.texts = [HI_DRAFT]
    d = go(client, campaign(biz_a), "पीठ दर्द, स्टाफ़ दोस्ताना, एक्सरसाइज़ अच्छे से समझाईं", language="hi").json()
    assert d["ai_status"] == "ok" and d["draft"] == HI_DRAFT and d["language"] == "hi"
    assert "Devanagari" in llm.calls[0][1]


def test_mixed_language_input_follows_the_selected_language(biz_a, client, llm):
    mixed = "back pain, staff bahut friendly tha, exercises acche se samjhaye"
    c = campaign(biz_a)
    llm.texts = [HI_DRAFT]
    assert go(client, c, mixed, language="hi").json()["draft"] == HI_DRAFT
    en_mixed = "I visited the clinic for back pain. The staff were friendly and explained the exercises."  # no quality the customer did not state
    llm.texts = [en_mixed]
    assert go(client, c, mixed, language="en").json()["draft"] == en_mixed
    llm.texts = [EN_DRAFT]  # English text although Hindi was selected: rejected, never shown
    assert go(client, c, mixed, language="hi").json()["ai_status"] == "rejected"
    llm.texts = [HI_DRAFT]  # Hindi script in an English review: rejected
    assert go(client, c, mixed, language="en").json()["ai_status"] == "rejected"


def test_a_full_review_typed_by_the_customer_is_accepted_and_tidied(biz_a, client, llm):
    own = "I came for back pain. The staff were friendly and they explained every exercise clearly so I could do them at home."
    llm.texts = ["I came in for back pain. The staff were friendly and explained each exercise clearly so I could do them at home."]
    assert go(client, campaign(biz_a), own).json()["ai_status"] == "ok"


def test_default_style_is_used_and_no_style_choice_is_needed(biz_a, client, llm):
    c = campaign(biz_a, default_style="short", allowed_styles=["short"])
    llm.texts = [EN_DRAFT]
    d = go(client, c, KEYWORDS).json()  # the page sends no style
    assert d["style"] == "short" and "under 35 words" in llm.calls[0][1]


# ================================================================ 4-5. sentiment follows the customer's words

NEG = "waited an hour, nobody explained the charges"
NEUTRAL = "service was okay, nothing special"


@pytest.mark.parametrize("words,bad", [
    (NEG, "I waited an hour and nobody explained the charges, but overall I appreciated the care."),
    (NEG, "An excellent visit. I waited an hour and nobody explained the charges."),
    (NEG, "Great service despite the wait. Nobody explained the charges."),
    (NEUTRAL, "An excellent experience, the service was okay and nothing special."),
    (NEUTRAL, "Highly recommended. The service was okay and nothing special."),
])
def test_spun_positive_drafts_are_rejected(words, bad):
    with pytest.raises(ReviewDraftRejected) as e:
        validate_draft(bad, ReviewInput(note=words), language="en", style="natural", business_name="Acme")
    assert any(w in e.value.reason for w in ("positive", "praise", "recommendation"))


def test_feelings_the_customer_did_not_express_are_rejected():
    """Seen live from gpt-4o-mini: 'waited an hour' became 'I felt frustrated... uncertain' and (Hindi) 'this caused me some trouble'."""
    inp = ReviewInput(note=NEG)
    for bad in ("I felt frustrated after waiting an hour and nobody explained the charges.",
                "I waited an hour and nobody explained the charges, which left me feeling uncertain."):
        with pytest.raises(ReviewDraftRejected, match="feeling"):
            validate_draft(bad, inp, language="en", style="natural", business_name="Acme")
    with pytest.raises(ReviewDraftRejected, match="feeling"):
        validate_draft("मुझे एक घंटा इंतज़ार करना पड़ा और किसी ने चार्ज नहीं समझाए। इससे मुझे थोड़ी परेशानी हुई।",
                       ReviewInput(note="एक घंटा इंतज़ार करना पड़ा, किसी ने चार्ज नहीं समझाए"), language="hi", style="natural", business_name="Acme")
    # stated by the customer => allowed, including other word forms of the same stem
    validate_draft("I was frustrated: I waited an hour and nobody explained the charges.", ReviewInput(note="waited an hour, nobody explained the charges, very frustrating"),
                   language="en", style="natural", business_name="Acme")
    validate_draft("I waited an hour and nobody explained the charges.", inp, language="en", style="natural", business_name="Acme")


def test_results_and_services_the_customer_never_mentioned_are_rejected():
    """Seen live from gpt-4o-mini: 'explained the exercises' became '...which helped with my back pain'; 'waited an hour' became
    'I received physiotherapy' (read from the business type)."""
    inp = ReviewInput(note=KEYWORDS)
    with pytest.raises(ReviewDraftRejected, match="result"):
        validate_draft("The staff were friendly and explained the exercises clearly, which helped with my back pain.", inp, language="en", style="natural", business_name="Sunrise Physio")
    with pytest.raises(ReviewDraftRejected, match="result"):
        validate_draft("मेरे पीठ दर्द के लिए स्टाफ़ दोस्ताना था और एक्सरसाइज़ अच्छे से समझाईं, जो मददगार रहीं।", ReviewInput(note="पीठ दर्द, स्टाफ़ दोस्ताना, एक्सरसाइज़ अच्छे से समझाईं"),
                       language="hi", style="natural", business_name="Acme")
    with pytest.raises(ReviewDraftRejected, match="service"):
        validate_draft("I received physiotherapy but waited an hour and nobody explained the charges.", ReviewInput(note=NEG), language="en", style="natural",
                       business_name="Sunrise Clinic", category="Physiotherapy clinic")
    # stated by the customer, or simply the business's own name => allowed
    validate_draft("The exercises helped my back pain and the staff were friendly.", ReviewInput(note="exercises helped my back pain, friendly staff"), language="en", style="natural", business_name="Acme")
    validate_draft("I waited an hour at Sunrise Physiotherapy and nobody explained the charges.", ReviewInput(note=NEG), language="en", style="natural",
                   business_name="Sunrise Physiotherapy", category="Physiotherapy clinic")
    validate_draft("I came for physiotherapy; the staff were friendly and explained the exercises.", ReviewInput(note="physiotherapy, friendly staff, explained exercises"),
                   language="en", style="natural", business_name="Acme", category="Physiotherapy clinic")


def test_untranslated_hindi_words_in_an_english_review_are_rejected():
    """Seen live: Hinglish in, 'The staff was bahut friendly tha and they explained the exercises acche se' out."""
    inp = ReviewInput(note="back pain, staff bahut friendly tha, exercises acche se samjhaye")
    with pytest.raises(ReviewDraftRejected, match="untranslated"):
        validate_draft("I went for back pain. The staff was bahut friendly tha and they explained the exercises acche se.", inp, language="en", style="natural", business_name="Acme")
    validate_draft("I went for back pain. The staff were very friendly and explained the exercises well.", inp, language="en", style="natural", business_name="Acme")


def test_the_retry_tells_the_model_what_to_do_and_the_prompt_carries_worked_examples(biz_a, client, llm):
    llm.texts = ["I felt frustrated because I waited an hour and nobody explained the charges.", "I waited an hour and nobody explained the charges."]
    d = go(client, campaign(biz_a), NEG).json()
    assert d["ai_status"] == "ok" and d["draft"] == "I waited an hour and nobody explained the charges."
    system, retry_user = llm.calls[0][0], llm.calls[1][1]
    assert "EXAMPLES of the right level of faithfulness" in system and "waited an hour, nobody explained the charges" in system
    assert "adds a feeling" in retry_user and "No feelings, no praise, no results" in retry_user  # an instruction, not just a complaint


def test_a_third_attempt_recovers_a_draft_that_failed_twice(biz_a, client, llm, monkeypatch):
    """Seen live: ~1 in 12 requests had both attempts add 'helped...'. A third attempt, told what to do, recovers those."""
    monkeypatch.setattr(settings, "review_max_attempts", 3)
    llm.texts = ["The staff were friendly and explained the exercises, which helped my back pain.",
                 "Back pain: the friendly staff explained the exercises clearly, and it helped a lot.", EN_DRAFT]
    d = go(client, campaign(biz_a), KEYWORDS).json()
    assert d["ai_status"] == "ok" and d["draft"] == EN_DRAFT and len(llm.calls) == 3
    assert "claims a result" in llm.calls[2][1] and "No feelings, no praise, no results" in llm.calls[2][1]
    monkeypatch.setattr(settings, "review_max_attempts", 2)
    llm.calls.clear(); llm.texts = ["It helped my back pain a lot."]
    assert go(client, campaign(biz_a, "Two tries"), KEYWORDS).json()["ai_status"] == "rejected" and len(llm.calls) == 2  # the cap is honoured


def test_the_prompt_withholds_the_business_type_and_forbids_guessing_it(biz_a, client, llm):
    llm.texts = [EN_DRAFT]
    go(client, campaign(biz_a), KEYWORDS)
    system, user = llm.calls[0]
    assert "<business_context>" in user and "Business type: Physiotherapy." in user  # the type is now sent, clearly labelled as background only
    assert "NOT what this customer received or experienced" in user and "Never say or imply the customer used, ate, bought or was treated with anything" in user
    assert "Never state or imply what service, treatment, dish or product the customer used" in system and "unless they used that feeling" in system
    with pytest.raises(ReviewDraftRejected, match="service"):  # ...and the deterministic guard still stops a draft stating it as THIS customer's experience
        validate_draft("I went for physiotherapy and the staff were friendly.", ReviewInput(note="friendly staff"), language="en", style="natural",
                       business_name="Acme", category="Physiotherapy clinic", offered_terms=("physiotherapy",))


def test_negative_and_neutral_sentiment_survive_the_whole_flow(biz_a, client, llm):
    c = campaign(biz_a)
    honest_neg = "I waited an hour and nobody explained the charges to me."
    llm.texts = [honest_neg]
    d = go(client, c, NEG, rating=2).json()
    assert d["ai_status"] == "ok" and d["draft"] == honest_neg and "rated their visit 2 out of 5" in llm.calls[0][1] and "not good" in llm.calls[0][1].lower()
    assert pub(client, "POST", c["public_id"], "/approve", json={"session_id": d["session_id"], "final_text": honest_neg}).json()["review_url"]  # same road to Google
    honest_neu = "The service was okay, nothing special."
    llm.texts = [honest_neu]
    assert go(client, c, NEUTRAL, rating=3).json()["draft"] == honest_neu


def test_a_positive_customer_keeps_their_praise():
    validate_draft("The staff were excellent and explained everything clearly.", ReviewInput(note="excellent staff, explained everything clearly"),
                   language="en", style="natural", business_name="Acme")


# ================================================================ 6. vague input -> one small question, never a guess

@pytest.mark.parametrize("vague", ["good", "nice", "ok", "very good service", "great experience!", "nice place", "Good.", "bahut accha", "अच्छा", "  ok  "])
def test_vague_words_are_recognised(vague):
    assert is_too_vague(vague)


@pytest.mark.parametrize("concrete", ["back pain", "friendly staff", "nice doctor", "wait was long", "डॉक्टर ने ध्यान से सुना", "haircut"])
def test_concrete_words_are_not_vague(concrete):
    assert not is_too_vague(concrete)


def test_vague_input_asks_for_detail_without_an_ai_call_or_stored_session(biz_a, client, llm):
    c = campaign(biz_a)
    r = go(client, c, "good")
    d = r.json()
    assert r.status_code == 200 and d["ai_status"] == "needs_more" and d["session_id"] is None and d["draft"] is None
    assert d["message"] == CLARIFY["en"] and "?" in d["message"]
    assert llm.calls == [] and owner_query("SELECT count(*) FROM review_sessions WHERE campaign_id=:c", c=c["id"])[0][0] == 0
    hi = go(client, c, "अच्छा", language="hi").json()
    assert hi["ai_status"] == "needs_more" and hi["message"] == CLARIFY["hi"] and "क्या आप" in hi["message"]
    assert counts(c["id"]) == {"ai_requested": 2, "needs_more": 2}


def test_model_can_also_decline_a_thin_input_and_nothing_is_fabricated(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = ["NEEDS_MORE"]
    d = go(client, c, "went there yesterday").json()  # has a concrete-looking word, but the model judges it too thin
    assert d["ai_status"] == "needs_more" and d["draft"] is None and d["message"] == CLARIFY["en"] and d["session_id"]
    assert owner_query("SELECT d.generated_content FROM review_drafts d JOIN review_sessions s ON s.id=d.session_id WHERE s.campaign_id=:c", c=c["id"]) == [(None,)]
    assert counts(c["id"]).get("needs_more") == 1 and "generation_failed" not in counts(c["id"])  # a question, not a failure
    assert owner_query("SELECT status FROM ai_generation_logs WHERE tenant_id=:t", t=biz_a.tenant_id) == [("needs_more",)]


def test_empty_input_never_generates(biz_a, client, llm):
    c = campaign(biz_a)
    for body in ({}, {"text": ""}, {"text": "   \n "}, {"text": "<>"}, {"language": "en"}):
        assert pub(client, "POST", c["public_id"], "/generate", json=body).status_code == 422, body
    assert llm.calls == [] and owner_query("SELECT count(*) FROM review_sessions WHERE campaign_id=:c", c=c["id"])[0][0] == 0
    assert counts(c["id"]) == {}  # not even an "AI requested" event for an empty box


# ================================================================ 7-8. failures never trap the customer

def test_transient_provider_failure_is_retryable_and_manual_still_completes(biz_a, client, use):
    use(httpx.Response(429, headers={"retry-after": "1"}, json={}))
    c = campaign(biz_a)
    d = go(client, c, KEYWORDS).json()
    assert d["ai_status"] == "unavailable" and d["retryable"] is True and d["session_id"] and d["draft"] is None
    assert "openrouter" not in str(d).lower() and "429" not in str(d) and KEY not in str(d)
    ok = pub(client, "POST", c["public_id"], "/approve", json={"session_id": d["session_id"], "final_text": "I had back pain and the staff were friendly."})
    assert ok.status_code == 200 and ok.json()["review_url"] == "https://g.page/r/ABC123/review"
    assert pub(client, "POST", c["public_id"], "/redirect", json={"session_id": d["session_id"]}).status_code == 200


def test_retry_after_a_transient_failure_reuses_the_same_words(biz_a, client, use):
    use(httpx.Response(503), reply(EN_DRAFT))  # fails (and fails its own single retry? no: 503 then success)
    c = campaign(biz_a)
    d = go(client, c, KEYWORDS).json()
    assert d["ai_status"] == "ok" and d["draft"] == EN_DRAFT  # the provider's own one-shot retry already recovered it


def test_try_again_button_path_regenerate_after_failure(biz_a, client, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "k")
    seq = [StubLLM([""]), StubLLM([EN_DRAFT])]  # first call fails (empty), then works
    from app.services.ai import AIUnavailable

    class Flaky:
        name, model, usage = "flaky", "f", None
        calls = 0

        def generate(self, system, user, **kw):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise AIUnavailable("blip", code="timeout")
            return EN_DRAFT

    monkeypatch.setattr("app.api.v1.review_public.get_provider", lambda: Flaky())
    monkeypatch.setattr(settings, "review_verify_with_ai", False)
    c = campaign(biz_a)
    d = go(client, c, KEYWORDS).json()
    assert d["ai_status"] == "unavailable" and d["retryable"] is True
    r = pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": d["session_id"]}).json()  # what "Try again" calls
    assert r["ai_status"] == "ok" and r["draft"] == EN_DRAFT
    assert counts(c["id"])["draft_generated"] == 1  # counted as the first successful draft, not a "rewrite"


DAILY_CAP = {"error": {"message": "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day", "code": 429,
                       "metadata": {"headers": {"X-RateLimit-Limit": "50", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int((time.time() + 5 * 3600) * 1000))},
                                    "limit_source": "openrouter_free_tier_daily"}}}


def test_daily_cap_is_not_retried_and_pauses_ai_so_customers_stop_waiting(biz_a, client, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", KEY)
    monkeypatch.setattr(settings, "openrouter_model", MODEL)
    calls: list = []
    monkeypatch.setattr("app.api.v1.review_public.get_provider", lambda: provider(httpx.Response(429, json=DAILY_CAP), calls=calls))
    c = campaign(biz_a)
    assert pub(client, "GET", c["public_id"]).json()["ai_available"] is True
    d = go(client, c, KEYWORDS).json()
    assert d["ai_status"] == "unavailable" and d["retryable"] is False  # no "Try again" offered: it would not help for hours
    assert len(calls) == 1  # the daily cap is never retried
    paused = health.current()
    assert paused["code"] == "quota_exhausted" and "daily" in paused["message"]
    assert pub(client, "GET", c["public_id"]).json()["ai_available"] is False  # the page now opens in plain write-it-yourself mode
    d2 = go(client, c, KEYWORDS).json()  # a stale page that still asks: answered instantly, provider untouched
    assert d2["ai_status"] == "unavailable" and d2["retryable"] is False and len(calls) == 1
    st = biz_a.get("/review-growth/settings").json()["ai"]
    assert st["degraded"]["code"] == "quota_exhausted" and st["degraded"]["until"] > time.time()
    errors = owner_query("SELECT error FROM ai_generation_logs WHERE tenant_id=:t ORDER BY created_at", t=biz_a.tenant_id)
    assert errors[0][0].startswith("quota_exhausted") and errors[1][0].startswith("paused: quota_exhausted")


def test_admin_model_test_reports_the_cap_and_a_success_lifts_the_pause(biz_a, monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", KEY)
    monkeypatch.setattr(settings, "openrouter_model", MODEL)
    monkeypatch.setattr(settings, "review_verify_with_ai", False)
    responses = [httpx.Response(429, json=DAILY_CAP), reply(EN_DRAFT)]
    monkeypatch.setattr("app.api.v1.review_growth.get_provider", lambda: provider(responses.pop(0)))
    t = biz_a.post("/review-growth/ai/test", json={}).json()
    assert t["ok"] is False and t["error"]["code"] == "quota_exhausted" and health.current()
    t = biz_a.post("/review-growth/ai/test", json={}).json()  # e.g. after the owner added credits
    assert t["ok"] is True and health.current() is None
    assert biz_a.get("/review-growth/settings").json()["ai"]["degraded"] is None


@pytest.mark.parametrize("code", ["credits", "auth", "forbidden"])
def test_other_permanent_provider_problems_also_pause_ai(biz_a, client, monkeypatch, code):
    from app.services.ai import AIUnavailable

    class Down:
        name, model, usage = "down", "d", None

        def generate(self, *a, **k):
            raise AIUnavailable("x", code=code)

    monkeypatch.setattr(settings, "gemini_api_key", "k")
    monkeypatch.setattr("app.api.v1.review_public.get_provider", lambda: Down())
    d = go(client, campaign(biz_a), KEYWORDS).json()
    assert d["ai_status"] == "unavailable" and d["retryable"] is False and health.current()["code"] == code


def test_pause_expires_on_its_own(monkeypatch):
    health.mark_down("quota_exhausted", retry_after=60)
    assert health.current()
    monkeypatch.setattr(time, "time", lambda t=time.time(): t + 3700)
    assert health.current() is None
    health.mark_down("rate_limited")  # transient codes never pause AI
    assert health.current() is None


def test_fact_check_rejection_is_safe_retryable_and_keeps_the_customer_moving(biz_a, client, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "k")
    monkeypatch.setattr(settings, "review_verify_with_ai", True)
    from tests.test_review_verify import ScriptedLLM

    stub = ScriptedLLM([EN_DRAFT, EN_DRAFT], ["UNSUPPORTED: invented detail", "UNSUPPORTED: invented detail"])
    monkeypatch.setattr("app.api.v1.review_public.get_provider", lambda: stub)
    c = campaign(biz_a)
    d = go(client, c, KEYWORDS).json()
    assert d["ai_status"] == "rejected" and d["retryable"] is True and d["draft"] is None and d["session_id"]
    assert "invented" not in str(d) and "faithful" in d["message"]
    stub.verdicts = ["OK"]
    r = pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": d["session_id"]}).json()
    assert r["ai_status"] == "ok" and r["draft"] == EN_DRAFT


# ================================================================ 9. edits are preserved

def test_regeneration_keeps_the_original_words_and_never_touches_the_customers_text(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [EN_DRAFT]
    sid = go(client, c, KEYWORDS).json()["session_id"]
    llm.texts = ["I went in with back pain and the friendly staff took the time to explain the exercises clearly."]
    r = pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": sid, "language": "en"}).json()
    assert r["ai_status"] == "ok" and r["draft"] != EN_DRAFT and r["generation_count"] == 2
    assert f"The customer wrote: {KEYWORDS}" in llm.calls[-1][1] and "<earlier_draft>" in llm.calls[-1][1]  # same original input, no new facts
    assert owner_query("SELECT customer_input FROM review_sessions WHERE session_identifier=:s", s=sid)[0][0] == {"text": KEYWORDS}


def test_customer_edits_are_stored_verbatim_and_beat_the_ai_text(biz_a, client, llm):
    c = campaign(biz_a)
    llm.texts = [EN_DRAFT]
    sid = go(client, c, KEYWORDS).json()["session_id"]
    mine = "I went in for my back pain. Friendly staff, and the exercises were explained clearly. Would go again."
    a = pub(client, "POST", c["public_id"], "/approve", json={"session_id": sid, "final_text": mine}).json()
    assert a["final_text"] == mine
    row = owner_query("SELECT d.generated_content, d.final_content, d.ai_assisted FROM review_drafts d JOIN review_sessions s ON s.id=d.session_id WHERE s.session_identifier=:s", s=sid)[0]
    assert row == (EN_DRAFT, mine, True)  # AI draft and the customer's own final text are both kept, never mixed
    assert pub(client, "POST", c["public_id"], "/regenerate", json={"session_id": sid}).status_code == 409  # a confirmed review is never rewritten


# ================================================================ 10. manual path: no AI at all

def test_manual_path_makes_no_ai_call_and_completes(biz_a, client, llm):
    c = campaign(biz_a)
    r = go(client, c, "back pain, friendly staff", mode="manual")
    d = r.json()
    assert r.status_code == 200 and d["ai_status"] == "manual" and d["draft"] is None and d["session_id"] and d["retryable"] is False
    assert llm.calls == []
    assert owner_query("SELECT count(*) FROM ai_generation_logs WHERE tenant_id=:t", t=biz_a.tenant_id)[0][0] == 0
    mine = "My own words: friendly staff and the exercises were clear."
    a = pub(client, "POST", c["public_id"], "/approve", json={"session_id": d["session_id"], "final_text": mine}).json()
    assert a["review_url"] == "https://g.page/r/ABC123/review"
    assert pub(client, "POST", c["public_id"], "/redirect", json={"session_id": d["session_id"]}).json()["review_url"]
    assert owner_query("SELECT d.ai_assisted, d.generated_content FROM review_drafts d JOIN review_sessions s ON s.id=d.session_id WHERE s.session_identifier=:s", s=d["session_id"])[0] == (False, None)
    assert llm.calls == []


def test_manual_with_nothing_typed_is_allowed_and_still_no_ai(biz_a, client, llm):
    c = campaign(biz_a)
    d = pub(client, "POST", c["public_id"], "/generate", json={"mode": "manual", "language": "hi"}).json()
    assert d["ai_status"] == "manual" and d["language"] == "hi" and llm.calls == []
    assert owner_query("SELECT customer_input FROM review_sessions WHERE session_identifier=:s", s=d["session_id"])[0][0] == {"text": ""}


def test_manual_path_works_when_ai_is_not_configured_at_all(biz_a, client):
    c = campaign(biz_a)
    assert pub(client, "GET", c["public_id"]).json()["ai_available"] is False  # gemini key empty in tests
    d = pub(client, "POST", c["public_id"], "/generate", json={"mode": "manual"}).json()
    assert pub(client, "POST", c["public_id"], "/approve", json={"session_id": d["session_id"], "final_text": "Wrote this myself, thank you."}).status_code == 200


def test_manual_sessions_are_bot_blocked_and_rate_limited(biz_a, client):
    c = campaign(biz_a)
    assert client.post(f"/api/v1/public/reviews/{c['public_id']}/generate", json={"mode": "manual"}, headers={"user-agent": "curl/8"}).status_code == 403
    codes = [pub(client, "POST", c["public_id"], "/generate", json={"mode": "manual"}).status_code for _ in range(23)]
    assert codes[:20] == [200] * 20 and 429 in codes[20:]


# ================================================================ 11. the right Google destination

def test_every_campaign_sends_customers_to_its_own_location_link(biz_a, biz_b, client, llm):
    r = biz_a.post("/locations", json={"name": "Branch B", "city": "Agra", "review_url": "https://g.page/r/BRANCHB/review"})
    assert r.status_code == 201
    c1 = campaign(biz_a, "Main desk")
    c2 = biz_a.post("/review-growth/campaigns", json={"name": "Branch desk", "location_id": r.json()["id"]}).json()
    cb = campaign(biz_b, "Other business")
    owner_query("SELECT 1")
    urls = {}
    for key, c in (("main", c1), ("branch", c2), ("other", cb)):
        d = pub(client, "POST", c["public_id"], "/generate", json={"mode": "manual"}).json()
        a = pub(client, "POST", c["public_id"], "/approve", json={"session_id": d["session_id"], "final_text": "My honest experience, in my own words."}).json()
        urls[key] = (a["review_url"], pub(client, "POST", c["public_id"], "/redirect", json={"session_id": d["session_id"]}).json()["review_url"])
    assert urls["main"] == ("https://g.page/r/ABC123/review",) * 2
    assert urls["branch"] == ("https://g.page/r/BRANCHB/review",) * 2
    assert urls["other"] == ("https://g.page/r/ABC123/review",) * 2  # biz_b's own link, never biz_a's
    assert pub(client, "POST", c1["public_id"], "/approve", json={"session_id": "x" * 22, "final_text": "Not my session."}).status_code == 404


# ================================================================ 8 (analytics). tracked steps, honest labels

def test_every_step_is_tracked_and_google_clicks_are_never_called_reviews(biz_a, client, llm):
    c = campaign(biz_a, "Tracked")
    pub(client, "GET", c["public_id"])  # page opened
    llm.texts = [EN_DRAFT]
    ai = go(client, c, KEYWORDS).json()  # AI requested + draft generated
    man = pub(client, "POST", c["public_id"], "/generate", json={"mode": "manual", "text": "own words"}).json()  # manual selected
    go(client, c, "ok")  # needs_more
    for s in (ai, man):
        pub(client, "POST", c["public_id"], "/approve", json={"session_id": s["session_id"], "final_text": "A review in my own words."})
    pub(client, "POST", c["public_id"], "/redirect", json={"session_id": ai["session_id"]})
    t = biz_a.get("/review-growth/analytics").json()
    assert t["totals"]["scans"] == 1 and t["totals"]["ai_requested"] == 2 and t["totals"]["manual_selected"] == 1 and t["totals"]["needs_more"] == 1
    assert t["totals"]["drafts_generated"] == 1 and t["totals"]["drafts_approved"] == 2 and t["totals"]["google_redirects"] == 1
    assert {s["key"]: s["count"] for s in t["funnel"]} == {"scans": 1, "feedback_submitted": 2, "drafts_approved": 2, "google_redirects": 1}
    assert [s["label"] for s in t["funnel"]][-1] == "Continued to Google" and "published" not in str(t["funnel"]).lower()
    assert "NOT a published review" in t["definitions"]["google_redirects"]
    row = t["campaigns"][0]
    assert (row["ai_requested"], row["manual_selected"], row["drafts_generated"]) == (2, 1, 1)
    stats = biz_a.get(f"/review-growth/campaigns/{c['id']}").json()["stats"]
    assert (stats["ai_requested"], stats["manual_selected"], stats["drafts_generated"], stats["google_redirects"]) == (2, 1, 1, 1)


# ================================================================ provider: daily cap detection

def test_provider_daily_cap_detection_is_precise():
    from app.services.ai.openrouter import OpenRouterProvider

    # The reset time is stamped NOW, not when the module was imported: DAILY_CAP's is fixed at collection time, so a suite that takes over ~1000 s to reach this test would see less than 17000 s left.
    fresh = {"error": {**DAILY_CAP["error"], "metadata": {**DAILY_CAP["error"]["metadata"], "headers": {**DAILY_CAP["error"]["metadata"]["headers"], "X-RateLimit-Reset": str(int((time.time() + 5 * 3600) * 1000))}}}}
    cap = httpx.Response(429, json=fresh)
    assert 17000 < OpenRouterProvider._daily_cap(cap) <= 18000  # ~5h until the reset header
    assert OpenRouterProvider._daily_cap(httpx.Response(429, json={"error": {"message": "temporarily rate-limited upstream", "metadata": {"limit_source": "upstream_provider_shared_pool"}}})) is None
    assert OpenRouterProvider._daily_cap(httpx.Response(429, content=b"<html>")) is None
    assert OpenRouterProvider._daily_cap(httpx.Response(429, json={})) is None
    p = provider(httpx.Response(429, json=DAILY_CAP))
    from app.services.ai import AIUnavailable

    with pytest.raises(AIUnavailable) as e:
        p.generate("s", "u")
    assert e.value.code == "quota_exhausted" and e.value.retry_after > 0 and KEY not in str(e.value)
