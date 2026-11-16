"""LLM provider abstraction. Add a new provider by implementing `LLMProvider` and registering it in `get_provider`."""
from typing import Protocol

from app.core.config import settings


class AIUnavailable(Exception):
    """AI is not configured, timed out, or the provider failed.

    `code` is a stable machine-readable reason for logs and the admin test endpoint (never shown raw to customers):
    unavailable | not_configured | auth | forbidden | credits | quota_exhausted | rate_limited | timeout | tls | provider_error |
    bad_response | rejected | needs_more.
    """

    def __init__(self, message: str = "", *, code: str = "unavailable", retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class LLMProvider(Protocol):
    name: str
    model: str
    # Optional: providers that report token usage keep a running total for the life of the instance (one per request):
    # {"prompt_tokens": int, "completion_tokens": int, "calls": int, "model": str | None}.
    usage: dict | None

    def generate(self, system: str, user: str, *, max_tokens: int = 600, temperature: float = 0.4) -> str: ...


def configured_identity() -> tuple[str, str | None]:
    """(provider name, model) from settings, for logging when no provider instance exists (e.g. it is not configured)."""
    if settings.ai_provider == "openrouter":
        return "openrouter", settings.openrouter_model or None
    if settings.ai_provider == "gemini":
        return "gemini", settings.gemini_model or None
    if settings.ai_provider == "openai_compat":
        return settings.openai_compat_name, settings.openai_compat_model or None
    return settings.ai_provider, None


def get_provider() -> LLMProvider:
    if settings.ai_provider == "gemini":
        if not settings.gemini_api_key:
            raise AIUnavailable("AI provider is not configured", code="not_configured")
        from app.services.ai.gemini import GeminiProvider

        return GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model, timeout=settings.ai_timeout_seconds,
                              thinking_level=settings.gemini_thinking_level or None)
    if settings.ai_provider == "openrouter":
        if not settings.openrouter_api_key or not settings.openrouter_model:
            raise AIUnavailable("AI provider is not configured", code="not_configured")
        from app.services.ai.openrouter import OpenRouterProvider

        return OpenRouterProvider(api_key=settings.openrouter_api_key, model=settings.openrouter_model,
                                  timeout=settings.ai_timeout_seconds, referer=settings.frontend_url,
                                  extra_ca_bundle=settings.ai_extra_ca_bundle, disable_reasoning=settings.openrouter_disable_reasoning)
    if settings.ai_provider == "openai_compat":
        if not (settings.openai_compat_base_url and settings.openai_compat_api_key and settings.openai_compat_model):
            raise AIUnavailable("AI provider is not configured", code="not_configured")
        from app.services.ai.openrouter import OpenRouterProvider

        base = settings.openai_compat_base_url.rstrip("/")
        return OpenRouterProvider(api_key=settings.openai_compat_api_key, model=settings.openai_compat_model, timeout=settings.ai_timeout_seconds,
                                  extra_ca_bundle=settings.ai_extra_ca_bundle, disable_reasoning=False, endpoint=f"{base}/chat/completions",
                                  name=settings.openai_compat_name)
    raise AIUnavailable(f"Unknown AI provider '{settings.ai_provider}'", code="not_configured")
