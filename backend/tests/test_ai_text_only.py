"""The app's AI is text only, and it is one model. With AI_PROVIDER=openai_compat the only thing FlowQR ever sends is a text chat-completions request for the configured model (gpt-4o-mini in
production); nothing in the code asks any provider for an image, audio or any other kind of output, and every model call goes through get_provider(). These tests pin that. No network."""
import json
import re
from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.services.ai import base, get_provider

APP = Path(__file__).resolve().parent.parent / "app"


def _provider(monkeypatch, seen):
    monkeypatch.setattr(settings, "ai_provider", "openai_compat")
    monkeypatch.setattr(settings, "openai_compat_base_url", "https://api.openai.com/v1")
    monkeypatch.setattr(settings, "openai_compat_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_compat_model", "gpt-4o-mini")
    monkeypatch.setattr(settings, "openai_compat_name", "openai")

    def handler(req: httpx.Request):
        seen.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={"choices": [{"message": {"content": "A short reply."}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    real = httpx.Client
    monkeypatch.setattr("app.services.ai.openrouter.build_client", lambda timeout, extra="": real(transport=httpx.MockTransport(handler), timeout=timeout))
    return get_provider()


def test_the_only_request_is_a_text_chat_completion_for_gpt_4o_mini(monkeypatch):
    seen: list = []
    p = _provider(monkeypatch, seen)
    assert (p.name, p.model) == ("openai", "gpt-4o-mini")
    assert p.generate("You write short replies.", "Say hello.", max_tokens=20) == "A short reply."
    (url, body), = seen
    assert url == "https://api.openai.com/v1/chat/completions"  # chat completions only: not /images, /audio, /embeddings, /responses
    assert body["model"] == "gpt-4o-mini"
    assert set(body) <= {"model", "messages", "max_tokens", "temperature"}  # no "modalities", "audio", "tools", "response_format" asking for anything but text
    assert all(isinstance(m["content"], str) for m in body["messages"])  # every message is plain text: no image parts are ever sent to the model


def test_the_provider_is_chosen_by_one_setting_with_no_fallback(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "openai_compat")
    monkeypatch.setattr(settings, "openai_compat_base_url", "")  # not configured
    monkeypatch.setattr(settings, "gemini_api_key", "a-key-that-must-never-be-used")
    monkeypatch.setattr(settings, "openrouter_api_key", "another-key-that-must-never-be-used")
    with pytest.raises(base.AIUnavailable):
        get_provider()  # it does not quietly fall back to Gemini or OpenRouter: AI is simply unavailable and the page carries on without it


def test_no_code_asks_any_provider_for_an_image_or_other_media():
    pattern = re.compile(r"images/generations|images/edits|/v1/images|gpt-image|dall-?e|imagen|stable-?diffusion|text-to-image|audio/speech|audio/transcriptions|images\.generate|generate_image", re.I)
    offenders = [f"{p.relative_to(APP)}:{i + 1}" for p in APP.rglob("*.py") for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()) if pattern.search(line)]
    assert offenders == [], "image or audio generation must not exist in the app: " + ", ".join(offenders)


def test_model_providers_are_only_built_by_get_provider_outside_the_offline_evaluation_tool():
    ctor = re.compile(r"\b(GeminiProvider|OpenRouterProvider)\(")
    offenders = []
    for p in APP.rglob("*.py"):
        rel = p.relative_to(APP).as_posix()
        if rel in ("services/ai/base.py", "services/ai/gemini.py", "services/ai/openrouter.py") or rel.startswith("ai_eval/"):
            continue  # get_provider itself, the provider classes, and the offline evaluation command (never served to customers)
        offenders += [f"{rel}:{i + 1}" for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()) if ctor.search(line)]
    assert offenders == [], "build providers through services.ai.get_provider() only: " + ", ".join(offenders)
