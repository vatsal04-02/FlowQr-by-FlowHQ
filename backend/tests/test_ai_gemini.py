"""Gemini provider: request shape, thinking level, and stable error codes. `httpx.post` is replaced by a scripted double: these tests prove how
FlowQR talks to the API and reacts to its limits, not what the model says."""
import json

import httpx
import pytest

from app.services.ai import AIUnavailable
from app.services.ai.gemini import GeminiProvider

KEY = "AQ.test-gemini-key-0000"


def ok(text="A draft.", prompt=10, out=3):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}], "usageMetadata": {"promptTokenCount": prompt, "candidatesTokenCount": out}})


def quota(kind="PerMinute", delay="2s"):
    return httpx.Response(429, json={"error": {"code": 429, "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": f"GenerateRequests{kind}PerProjectPerModel-FreeTier"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}})


@pytest.fixture()
def script(monkeypatch):
    calls, queue, sleeps = [], [], []

    def post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "body": json, "headers": headers})
        r = queue.pop(0) if len(queue) > 1 else queue[0]
        return r

    monkeypatch.setattr("app.services.ai.gemini.httpx.post", post)
    return calls, queue, sleeps


def provider(sleeps, **kw):
    return GeminiProvider(api_key=KEY, model="gemini-3.5-flash", sleep=sleeps.append, **kw)


def test_key_is_only_in_a_header_and_thinking_level_is_sent(script):
    calls, queue, sleeps = script
    queue.append(ok("Hello"))
    p = provider(sleeps, thinking_level="minimal")
    assert p.generate("sys", "usr", max_tokens=300, temperature=0.3) == "Hello"
    c = calls[0]
    assert c["url"].endswith("/models/gemini-3.5-flash:generateContent") and KEY not in c["url"] and c["headers"] == {"x-goog-api-key": KEY}
    assert c["body"]["generationConfig"] == {"temperature": 0.3, "maxOutputTokens": 300, "thinkingConfig": {"thinkingLevel": "minimal"}}
    assert c["body"]["systemInstruction"]["parts"][0]["text"] == "sys" and p.usage["prompt_tokens"] == 10 and p.usage["completion_tokens"] == 3


def test_thinking_config_is_omitted_when_not_set(script):
    calls, queue, sleeps = script
    queue.append(ok())
    provider(sleeps).generate("s", "u")
    assert "thinkingConfig" not in calls[0]["body"]["generationConfig"]


def test_a_per_minute_limit_is_retried_once_after_the_suggested_wait(script):
    calls, queue, sleeps = script
    queue.extend([quota("PerMinute", "2.4s"), ok("Second try")])
    assert provider(sleeps).generate("s", "u") == "Second try" and len(calls) == 2 and sleeps == [3.0]


def test_a_persistent_per_minute_limit_is_rate_limited_not_a_pause(script):
    calls, queue, sleeps = script
    queue.append(quota("PerMinute", "2s"))
    with pytest.raises(AIUnavailable) as e:
        provider(sleeps).generate("s", "u")
    assert e.value.code == "rate_limited" and e.value.retry_after == 3 and len(calls) == 2


def test_a_daily_quota_is_not_retried_and_pauses_ai(script):
    calls, queue, sleeps = script
    queue.append(quota("PerDay", "40s"))
    with pytest.raises(AIUnavailable) as e:
        provider(sleeps).generate("s", "u")
    assert e.value.code == "quota_exhausted" and len(calls) == 1 and sleeps == []


@pytest.mark.parametrize("status,code", [(401, "auth"), (403, "forbidden"), (404, "forbidden"), (400, "provider_error")])
def test_other_failures_map_to_stable_codes(script, status, code):
    calls, queue, sleeps = script
    queue.append(httpx.Response(status, json={"error": {"message": f"secret {KEY}"}}))
    with pytest.raises(AIUnavailable) as e:
        provider(sleeps).generate("s", "u")
    assert e.value.code == code and KEY not in str(e.value)


def test_server_errors_get_one_retry_then_provider_error(script):
    calls, queue, sleeps = script
    queue.append(httpx.Response(503, json={}))
    with pytest.raises(AIUnavailable) as e:
        provider(sleeps).generate("s", "u")
    assert e.value.code == "provider_error" and len(calls) == 2


def test_empty_or_malformed_replies_are_bad_responses(script):
    calls, queue, sleeps = script
    queue.append(httpx.Response(200, json={"candidates": [{"content": {}, "finishReason": "MAX_TOKENS"}]}))
    with pytest.raises(AIUnavailable) as e:
        provider(sleeps).generate("s", "u")
    assert e.value.code == "bad_response"
