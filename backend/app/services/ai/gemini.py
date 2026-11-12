import re
import time

import httpx

from app.services.ai.base import AIUnavailable

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_RETRY_WAIT_SECONDS = 8.0


def _retry_info(r: httpx.Response) -> tuple[bool, int | None]:
    """(is_daily_quota, seconds_to_wait) from a Gemini 429 body. Free tiers have per-minute AND per-day limits: only the per-minute one clears by itself soon."""
    try:
        details = (r.json().get("error") or {}).get("details") or []
    except (ValueError, AttributeError):
        return False, None
    daily, wait = False, None
    for d in details:
        if not isinstance(d, dict):
            continue
        for v in d.get("violations") or []:
            if "PerDay" in str(v.get("quotaId", "")):
                daily = True
        if str(d.get("@type", "")).endswith("RetryInfo"):
            m = re.match(r"(\d+(?:\.\d+)?)s", str(d.get("retryDelay", "")))
            wait = int(float(m.group(1))) + 1 if m else None
    return daily, wait


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: int = 25, thinking_level: str | None = None, sleep=time.sleep):
        # Gemini 3 models "think" before answering and bill that against maxOutputTokens: a 500-token draft can come back empty. Short drafts need none.
        self._thinking_level = thinking_level
        self._key = api_key
        self.model = model
        self._timeout = timeout
        self._sleep = sleep
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "model": model}

    def _post(self, body: dict) -> httpx.Response:
        try:
            # API key goes in a header (never in the URL, so it can't leak into access logs).
            return httpx.post(ENDPOINT.format(model=self.model), json=body, headers={"x-goog-api-key": self._key}, timeout=self._timeout)
        except httpx.TimeoutException as exc:
            raise AIUnavailable("AI service timed out", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise AIUnavailable("AI service unreachable", code="provider_error") from exc

    def generate(self, system: str, user: str, *, max_tokens: int = 600, temperature: float = 0.4) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if self._thinking_level:
            body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": self._thinking_level}
        r = self._post(body)
        if r.status_code in (429, 500, 502, 503, 504):  # one short retry: a per-minute limit or a blip usually clears in seconds
            daily, wait = _retry_info(r) if r.status_code == 429 else (False, None)
            if not daily and (wait is None or wait <= MAX_RETRY_WAIT_SECONDS):
                self._sleep(min(float(wait or 2), MAX_RETRY_WAIT_SECONDS))
                r = self._post(body)
        s = r.status_code
        if s != 200:
            if s == 429:
                daily, wait = _retry_info(r)
                if daily:
                    raise AIUnavailable("AI service daily request limit reached", code="quota_exhausted", retry_after=3600)
                raise AIUnavailable("AI service is rate limiting requests", code="rate_limited", retry_after=wait)
            if s == 401 or (s == 400 and "API key" in r.text[:400]):
                raise AIUnavailable("AI service rejected the API credentials", code="auth")
            if s in (403, 404):  # a model closed to this key, or a permission problem: pause and tell the owner
                raise AIUnavailable("AI service refused this request for the selected model", code="forbidden")
            raise AIUnavailable(f"AI service error ({s})", code="provider_error")
        try:
            meta = r.json().get("usageMetadata") or {}
            self.usage["calls"] += 1
            self.usage["prompt_tokens"] += int(meta.get("promptTokenCount") or 0)
            self.usage["completion_tokens"] += int(meta.get("candidatesTokenCount") or 0)
        except (ValueError, AttributeError, TypeError):
            pass
        try:
            parts = r.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, ValueError) as exc:
            raise AIUnavailable("AI returned an unexpected response", code="bad_response") from exc
        if not text:
            raise AIUnavailable("AI returned an empty response", code="bad_response")
        return text
