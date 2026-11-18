"""What may be sent to an AI provider, and what is removed first (docs/PRIVACY_COMPLIANCE_AUDIT.md, finding 26).

Review text, replies and what a customer types into the review assistant are personal data. The data-use terms that apply to this project's Gemini key have NOT been confirmed (they depend on
the account's tier), so nothing here claims they are acceptable. Two settings decide what happens, and the DEFAULT IS SAFE (blocked):

  GEMINI_DATA_TERMS_VERIFIED   false (default)  review data is NOT sent to Gemini: the AI feature reports "unavailable" and the product carries on without it (a person writes the reply or the
                                                review; the review risk check treats an unchecked 3-star review as needing a person). Set to true ONLY when the owner holds written evidence that
                                                the key's terms do not allow the provider to train on or retain prompts. Setting it is the owner's statement, not a fix.
  AI_REVIEW_DATA_KILL_SWITCH   false (default)  true stops review data going to ANY provider immediately, whatever else is set.

Neither switch touches AI that works only from the owner's own business facts (Google post drafts and ideas, which are not review data). Other providers (OpenRouter, an OpenAI-compatible
endpoint) are not covered by the Gemini rule: they were not part of the finding, are off unless configured, and their terms are for the owner to check before use.

Separately from the switches, `redact` removes what is not needed to answer a review from what IS sent: e-mail addresses, phone numbers and links are replaced by a placeholder, and the reviewer's
name is no longer sent at all (the reply is written without addressing them by name).
"""
from __future__ import annotations

import re

from app.core.config import settings
from app.services.ai.base import AIUnavailable

BLOCKED_MESSAGE = "AI help with reviews is switched off until the AI provider's data-use terms have been confirmed."


def block_reason(provider_name: str | None) -> str | None:
    """None when review data may be sent to this provider, otherwise a stable code."""
    if settings.ai_review_data_kill_switch:
        return "kill_switch"
    if (provider_name or "").lower() == "gemini" and not settings.gemini_data_terms_verified:
        return "data_terms_unverified"
    return None


def blocked_now() -> str | None:
    """The same decision for the provider the server is configured to use, for pages that must not offer an AI feature that would only fail."""
    return block_reason(settings.ai_provider)


def ensure_review_data_allowed(provider) -> None:
    """Call before building a prompt that contains review text or a customer's words. Raises AIUnavailable (an error every caller already handles) when it is not allowed."""
    reason = block_reason(getattr(provider, "name", None))
    if reason:
        raise AIUnavailable(BLOCKED_MESSAGE, code=reason)


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_NUMBERISH = re.compile(r"(?<![\w])[+(]?\d[\d\s().-]{7,}\d(?![\w])")


def _phone(m: re.Match) -> str:
    return "[phone number]" if sum(c.isdigit() for c in m.group(0)) >= 9 else m.group(0)  # a date or a price is left alone


def redact(text: str | None) -> str:
    """Replace e-mail addresses, links and phone numbers with a neutral placeholder. Names inside free text cannot be found reliably and are not claimed to be removed."""
    if not text:
        return text or ""
    out = _EMAIL.sub("[email address]", text)
    out = _URL.sub("[link]", out)
    return _NUMBERISH.sub(_phone, out)
