"""Any OpenAI-compatible endpoint (Groq, Mistral, ...) through the existing provider. The HTTP layer is an httpx.MockTransport: these tests prove
how FlowQR talks to such a server (URL, headers, body, errors), not what any model says."""
import json

import httpx
import pytest

from app.core.config import settings
from app.services.ai import AIUnavailable, get_provider
from app.services.ai.base import configured_identity

KEY = "sk-test-compat-key-0000"


@pytest.fixture()
def compat(monkeypatch):
    for k, v in {"ai_provider": "openai_compat", "openai_compat_base_url": "https://api.example-llm.test/openai/v1/", "openai_compat_api_key": KEY,
                 "openai_compat_model": "llama-test-8b", "openai_compat_name": "examplellm"}.items():
        monkeypatch.setattr(settings, k, v)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"model": "llama-test-8b", "choices": [{"message": {"content": "A fine draft."}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 12, "completion_tokens": 4}})

    monkeypatch.setattr("app.services.ai.openrouter.build_client", lambda timeout, extra="": httpx.Client(transport=httpx.MockTransport(handler)))
    return seen


def test_requests_go_to_the_configured_base_url_with_the_key_only_in_a_header(compat):
    p = get_provider()
    assert p.name == "examplellm" and p.model == "llama-test-8b"
    assert p.generate("system text", "user text", max_tokens=50, temperature=0.2) == "A fine draft."
    req = compat[0]
    assert str(req.url) == "https://api.example-llm.test/openai/v1/chat/completions"  # trailing slash on the base URL is tolerated
    assert req.headers["authorization"] == f"Bearer {KEY}" and KEY not in str(req.url) and KEY.encode() not in req.content
    body = json.loads(req.content)
    assert body["model"] == "llama-test-8b" and body["messages"][0] == {"role": "system", "content": "system text"} and body["max_tokens"] == 50
    assert "reasoning" not in body  # other servers may reject OpenRouter's extension field
    assert p.usage["prompt_tokens"] == 12 and p.usage["completion_tokens"] == 4 and p.usage["calls"] == 1


def test_openrouter_itself_is_unchanged(monkeypatch):
    for k, v in {"ai_provider": "openrouter", "openrouter_api_key": KEY, "openrouter_model": "openai/gpt-4o-mini"}.items():
        monkeypatch.setattr(settings, k, v)
    p = get_provider()
    assert p.name == "openrouter" and p._endpoint == "https://openrouter.ai/api/v1/chat/completions"


@pytest.mark.parametrize("missing", ["openai_compat_base_url", "openai_compat_api_key", "openai_compat_model"])
def test_incomplete_configuration_is_not_configured_never_a_crash(compat, monkeypatch, missing):
    monkeypatch.setattr(settings, missing, "")
    assert settings.ai_configured is False
    with pytest.raises(AIUnavailable) as e:
        get_provider()
    assert e.value.code == "not_configured"


def test_complete_configuration_is_reported_configured_with_its_label(compat):
    assert settings.ai_configured is True
    assert configured_identity() == ("examplellm", "llama-test-8b")


@pytest.mark.parametrize("status,code", [(401, "auth"), (402, "credits"), (403, "forbidden"), (500, "provider_error")])
def test_errors_map_to_stable_codes_without_leaking_the_key(compat, monkeypatch, status, code):
    monkeypatch.setattr("app.services.ai.openrouter.build_client",
                        lambda timeout, extra="": httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={"error": {"message": f"secret {KEY}"}}))))
    with pytest.raises(AIUnavailable) as e:
        get_provider().generate("s", "u")
    assert e.value.code == code and KEY not in str(e.value)
