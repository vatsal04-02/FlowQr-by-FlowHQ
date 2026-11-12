"""Shared "AI is down" flag.

When the provider says something that will not fix itself in seconds (daily cap reached, no credits, bad key, model refused), every
customer would otherwise wait for a request that is certain to fail. Instead we remember it for a few minutes: the public page then
opens in plain "write your review" mode, the owner sees the real reason on the dashboard, and one probe per cooldown re-checks.
Stored in Redis when reachable (shared by all API workers), else in process memory.
"""
import json
import time

from app.core import rate_limit

KEY = "flowqr:ai:down"
COOLDOWN_SECONDS = 600
# Codes that justify pausing AI for everyone. Transient ones (rate_limited, timeout, provider_error) deliberately do not.
PAUSING = {"quota_exhausted", "credits", "auth", "forbidden"}
EXPLANATION = {
    "quota_exhausted": "The AI provider's daily request limit has been reached (free accounts are capped per day). Add credits to the provider account or choose another model.",
    "credits": "The AI provider account has no credits left for this model.",
    "auth": "The AI provider rejected the API key. Check the API key for the configured AI_PROVIDER.",
    "forbidden": "The AI provider refused the selected model for this account. Choose another model.",
}
_memory: dict | None = None


def reset() -> None:
    global _memory
    _memory = None


def mark_down(code: str, retry_after: int | None = None) -> None:
    """Pause AI for `COOLDOWN_SECONDS` (shorter if the provider said it resets sooner). No-op for non-pausing codes."""
    global _memory
    if code not in PAUSING:
        return
    seconds = max(60, min(COOLDOWN_SECONDS, retry_after)) if retry_after else COOLDOWN_SECONDS
    state = {"code": code, "message": EXPLANATION[code], "until": time.time() + seconds}
    client = rate_limit._get_redis()
    if client is not None:
        try:
            client.set(KEY, json.dumps(state), ex=seconds)
            return
        except Exception:
            pass
    _memory = state


def clear() -> None:
    global _memory
    _memory = None
    client = rate_limit._get_redis()
    if client is not None:
        try:
            client.delete(KEY)
        except Exception:
            pass


def current() -> dict | None:
    """{"code", "message", "until"} while AI is paused, else None."""
    client = rate_limit._get_redis()
    if client is not None:
        try:
            raw = client.get(KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    if _memory and _memory["until"] > time.time():
        return _memory
    return None
