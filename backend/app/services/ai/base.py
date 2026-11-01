"""LLM provider abstraction. Add a new provider by implementing `LLMProvider` and registering it in `get_provider`."""
from typing import Protocol

from app.core.config import settings


class AIUnavailable(Exception):
    """AI is not configured, timed out, or the provider failed."""


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(self, system: str, user: str, *, max_tokens: int = 600, temperature: float = 0.4) -> str: ...


def get_provider() -> LLMProvider:
    if settings.ai_provider == "gemini":
        if not settings.gemini_api_key:
            raise AIUnavailable("AI provider is not configured")
        from app.services.ai.gemini import GeminiProvider

        return GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model, timeout=settings.ai_timeout_seconds)
    raise AIUnavailable(f"Unknown AI provider '{settings.ai_provider}'")
