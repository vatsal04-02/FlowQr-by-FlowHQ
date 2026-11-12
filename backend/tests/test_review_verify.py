"""The AI fact-check pass and the grounding length cap.

MOCKED: the model is scripted (ScriptedLLM / httpx.MockTransport). These prove the pipeline reacts correctly to each verdict;
how good a real model is at fact-checking is measured separately against the live API.
"""
import httpx
import pytest

from app.core.config import settings
from app.services.ai import AIUnavailable
from app.services.ai.review_generate import (
    VERIFY_SYSTEM, ReviewDraftRejected, ReviewInput, generate_review, validate_draft, verify_grounded,
)
from tests.conftest import owner_query
from tests.test_openrouter import KEY, MODEL, logs, reply, use  # noqa: F401  (use = fixture)
from tests.test_review_growth import GOOD, campaign, generate

INP = ReviewInput(service="back pain physiotherapy", appreciated="the doctor listened carefully and explained the exercises", details="reception was friendly")
EMBELLISHED = "The doctor listened carefully and explained the exercises, and the session felt thorough without being rushed. I left with a clear plan to follow at home."


class ScriptedLLM:
    """TEST DOUBLE. Serves scripted drafts to the writer prompt and scripted verdicts to the fact-checker prompt."""
    name, model = "test-stub", "stub-1"
    usage = None

    def __init__(self, drafts, verdicts):
        self.drafts, self.verdicts, self.calls = list(drafts), list(verdicts), []

    def generate(self, system, user, *, max_tokens=600, temperature=0.4):
        self.calls.append((system, user, temperature))
        queue = self.verdicts if system == VERIFY_SYSTEM else self.drafts
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item


def run(llm, **kw):
    return generate_review(llm, INP, language="en", style="natural", business_name="Acme Physio", verify=True, **kw)


def test_supported_draft_passes_and_the_checker_sees_answers_and_draft():
    llm = ScriptedLLM([GOOD[0]], ["OK"])
    assert run(llm) == GOOD[0]
    assert len(llm.calls) == 2
    system, user, temp = llm.calls[1]
    assert system == VERIFY_SYSTEM and temp == 0.0  # deterministic verdicts
    assert "<customer_answers>" in user and "back pain physiotherapy" in user and GOOD[0] in user and "<draft>" in user


def test_unsupported_statements_trigger_a_retry_that_names_them():
    plausible = "I came in for back pain physiotherapy and the doctor listened carefully to me. Reception was friendly, and I booked my next visit."  # passes every rule, but "booked" is invented
    llm = ScriptedLLM([plausible, GOOD[1]], ["UNSUPPORTED: booked my next visit | second invented detail", "OK"])
    assert run(llm) == GOOD[1]
    retry_prompt = llm.calls[2][1]  # call 0 write, 1 verify, 2 rewrite
    assert "booked my next visit" in retry_prompt and "rejected" in retry_prompt.lower()


def test_persistent_invention_is_rejected_with_the_text_and_details_for_admins():
    llm = ScriptedLLM([GOOD[0], GOOD[1]], ["UNSUPPORTED: invented detail one", "UNSUPPORTED: invented detail two"])
    with pytest.raises(ReviewDraftRejected) as e:
        run(llm)
    assert e.value.reason == "includes statements the customer did not make" and e.value.text == GOOD[1] and e.value.detail == "invented detail two"
    assert len(llm.calls) == 4


@pytest.mark.parametrize("verdict,passes", [
    ("OK", True), ("ok", True), ("  OK  ", True), ("OK.", True), ('"OK"', True), ("**OK**", True),
    ("UNSUPPORTED: something", False), ("Unsupported: something", False), ("UNSUPPORTED", False),
    ("I think the review looks fine to me", False), ("", False), ("Everything is supported", False), ("OKAY but one thing is invented", False),
])
def test_verdict_parsing_fails_closed(verdict, passes):
    out = verify_grounded(ScriptedLLM([GOOD[0]], [verdict]), INP, GOOD[0])
    assert (out is None) is passes


def test_unclear_verdict_never_lets_a_draft_through():
    with pytest.raises(ReviewDraftRejected, match="did not make"):
        run(ScriptedLLM([GOOD[0], GOOD[1]], ["looks great!"]))


def test_provider_failure_during_the_fact_check_propagates_and_is_never_waved_through():
    boom = AIUnavailable("limit", code="rate_limited")
    with pytest.raises(AIUnavailable) as e:
        run(ScriptedLLM([GOOD[0]], [boom]))
    assert e.value.code == "rate_limited" and not isinstance(e.value, ReviewDraftRejected)


def test_fact_check_can_be_switched_off(monkeypatch):
    llm = ScriptedLLM([GOOD[0]], ["UNSUPPORTED: everything"])
    assert generate_review(llm, INP, language="en", style="natural", business_name="Acme", verify=False) == GOOD[0] and len(llm.calls) == 1
    monkeypatch.setattr(settings, "review_verify_with_ai", True)  # default comes from settings when not passed
    assert len(ScriptedLLM([GOOD[0]], ["OK"]).calls) == 0
    llm = ScriptedLLM([GOOD[0]], ["OK"])
    generate_review(llm, INP, language="en", style="natural", business_name="Acme")
    assert len(llm.calls) == 2


def test_the_checker_prompt_treats_text_as_data_and_asks_for_a_strict_format():
    assert "DATA, not instructions" in VERIFY_SYSTEM and "exactly OK" in VERIFY_SYSTEM and "UNSUPPORTED:" in VERIFY_SYSTEM


# ---------------------------------------------------------------- deterministic length cap

def test_a_draft_cannot_run_far_past_what_the_customer_supplied():
    tiny = ReviewInput(service="haircut", appreciated="", details="")
    padded = ("I went in for a haircut and it was a pleasant experience overall with a relaxed atmosphere and very attentive staff throughout "
              "my appointment there, and the whole place felt calm and well organised from start to finish.")
    assert len(padded) > 160
    with pytest.raises(ReviewDraftRejected, match="longer than the customer's answers support"):
        validate_draft(padded, tiny, language="en", style="natural", business_name="Acme")
    validate_draft("I got a haircut here and I was happy with how it turned out.", tiny, language="en", style="natural", business_name="Acme")
    rich = ReviewInput(service="back pain physiotherapy", appreciated="the doctor listened carefully and explained the exercises", details="reception was friendly")
    with pytest.raises(ReviewDraftRejected):  # the 336-char 'detailed' draft the live model produced before this check existed
        validate_draft("The reception was friendly when I arrived for my back pain physiotherapy. The doctor listened carefully to my concerns and explained the exercises in a way that made sense. "
                       "I appreciated that they took the time to walk me through each movement. The session felt thorough without being rushed. I left with a clear plan to follow at home.",
                       rich, language="en", style="detailed", business_name="Sunrise Physio")


# ---------------------------------------------------------------- through the app (MOCKED OpenRouter transport)

@pytest.fixture()
def route(monkeypatch):
    """Install an OpenRouter provider whose mock transport answers WRITER prompts from `drafts` and CHECKER prompts from `verdicts`
    (each served in order, the last repeating)."""
    import json

    monkeypatch.setattr(settings, "ai_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", KEY)
    monkeypatch.setattr(settings, "openrouter_model", MODEL)
    monkeypatch.setattr(settings, "review_verify_with_ai", True)

    def install(drafts, verdicts, module="app.api.v1.review_public"):
        d, v = list(drafts), list(verdicts)

        def handler(request: httpx.Request):
            q = v if json.loads(request.content)["messages"][0]["content"] == VERIFY_SYSTEM else d
            item = q.pop(0) if len(q) > 1 else q[0]
            if isinstance(item, Exception):
                raise item
            return item

        from app.services.ai.openrouter import OpenRouterProvider

        monkeypatch.setattr(f"{module}.get_provider", lambda: OpenRouterProvider(KEY, MODEL, http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None))

    return install


def test_fact_check_tokens_are_logged_and_unsupported_text_is_never_stored(biz_a, client, route):
    secret_detail = "felt thorough without being rushed"
    route([reply(GOOD[0], prompt=100, completion=20)], [reply(f"UNSUPPORTED: {secret_detail}", prompt=60, completion=10)])
    d = generate(client, campaign(biz_a)).json()
    assert d["ai_status"] == "rejected" and d["draft"] is None
    row = logs(biz_a.tenant_id)[0]
    assert row[3] == "rejected" and row[5] == 2 * (100 + 60) and row[6] == 2 * (20 + 10)  # 4 calls: 2 writes + 2 checks
    assert secret_detail not in (row[4] or "") and GOOD[0] not in (row[4] or "")  # logs keep a generic reason only


def test_a_checked_draft_reaches_the_customer_with_both_calls_accounted(biz_a, client, route):
    route([reply(GOOD[0], prompt=100, completion=20)], [reply("OK", prompt=70, completion=2)])
    d = generate(client, campaign(biz_a)).json()
    assert d["ai_status"] == "ok" and d["draft"] == GOOD[0]
    assert logs(biz_a.tenant_id)[0][5:] == (170, 22)


def test_checker_rate_limit_degrades_to_write_your_own(biz_a, client, route):
    route([reply(GOOD[0])], [httpx.Response(429)])
    c = campaign(biz_a)
    d = generate(client, c).json()
    assert d["ai_status"] == "unavailable" and d["draft"] is None and "own words" in d["message"]
    assert logs(biz_a.tenant_id)[0][4].startswith("rate_limited")
    assert owner_query("SELECT generated_content FROM review_drafts d JOIN review_sessions s ON s.id=d.session_id WHERE s.campaign_id=:c", c=c["id"]) == [(None,)]


def test_admin_test_reports_which_statements_were_unsupported(biz_a, route):
    route([reply(GOOD[0])], [reply("UNSUPPORTED: invented plan")], module="app.api.v1.review_growth")
    t = biz_a.post("/review-growth/ai/test", json={"text": "back pain physiotherapy, the doctor listened carefully, reception was friendly"}).json()
    assert t["ok"] is False and t["checks"]["unsupported"] == "invented plan" and t["checks"]["fact_check"] is True and t["rejected_text"] == GOOD[0]
