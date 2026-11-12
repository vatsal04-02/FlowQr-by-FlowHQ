"""OpenRouter provider (OpenAI-compatible chat completions). The API key stays on the server; it is sent only in a header.

Failure handling is explicit so callers (and the admin test endpoint) can tell *why* a call failed:
  401/403 -> auth, 402 -> credits, 429 -> rate_limited (one short retry), 408/5xx -> provider_error (one short retry),
  timeouts -> timeout, unparseable/empty/truncated replies -> bad_response.
Messages never include the key, the request body or the provider's raw error text beyond a short code.
"""
import ssl
import time

import certifi
import httpx

from app.services.ai.base import AIUnavailable

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
RETRY_STATUSES = {429, 502, 503, 504}
MAX_RETRY_WAIT_SECONDS = 2.0


def build_client(timeout: float, extra_ca_bundle: str = "") -> httpx.Client:
    """Normal certificate verification (certifi). `extra_ca_bundle` ADDS trusted roots for networks whose proxy or antivirus
    re-signs HTTPS (e.g. a developer machine). It never disables verification; leave it empty in production."""
    if not extra_ca_bundle:
        return httpx.Client(timeout=timeout)
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(cafile=extra_ca_bundle)
    return httpx.Client(timeout=timeout, verify=ctx)


class OpenRouterProvider:
    """Also serves any other OpenAI-compatible chat-completions endpoint (Groq, Mistral, Cerebras...): pass `endpoint` and `name`, and turn
    `disable_reasoning` off for servers that reject OpenRouter's `reasoning` field."""
    name = "openrouter"

    def __init__(self, api_key: str, model: str, timeout: int = 25, referer: str | None = None,
                 http: httpx.Client | None = None, sleep=time.sleep, extra_ca_bundle: str = "", disable_reasoning: bool = True,
                 endpoint: str = ENDPOINT, name: str = "openrouter"):
        self.name = name
        self._endpoint = endpoint
        self._key = api_key
        self.model = model
        # Short drafts don't need hidden chain-of-thought. Reasoning models otherwise spend most of max_tokens "thinking"
        # (and can return null content). Models that can't switch reasoning off simply ignore the flag.
        self._disable_reasoning = disable_reasoning
        self._timeout = timeout
        self._referer = referer
        self._http = http or build_client(timeout, extra_ca_bundle)
        self._sleep = sleep
        self.usage: dict = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "cost": 0.0, "model": None}

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json", "X-Title": "FlowQR by FlowHQ"}
        if self._referer:
            h["HTTP-Referer"] = self._referer
        return h

    def _post(self, body: dict) -> httpx.Response:
        try:
            return self._http.post(self._endpoint, json=body, headers=self._headers(), timeout=self._timeout)
        except httpx.TimeoutException as exc:
            raise AIUnavailable("AI service timed out", code="timeout") from exc
        except httpx.HTTPError as exc:
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                raise AIUnavailable("TLS certificate check failed. A proxy or antivirus may be re-signing HTTPS traffic; see AI_EXTRA_CA_BUNDLE.", code="tls") from exc
            raise AIUnavailable("AI service unreachable", code="provider_error") from exc

    @staticmethod
    def _daily_cap(r: httpx.Response) -> int | None:
        """If a 429 is OpenRouter's per-DAY cap (free-tier accounts get 50 free-model requests/day), return seconds until it resets,
        else None. Retrying such a 429 is pointless: it will not clear for hours."""
        try:
            err = r.json().get("error") or {}
            meta = err.get("metadata") or {}
        except (ValueError, AttributeError):
            return None
        if "daily" not in str(meta.get("limit_source", "")) and "per-day" not in str(err.get("message", "")):
            return None
        try:
            reset_ms = int((meta.get("headers") or {}).get("X-RateLimit-Reset") or r.headers.get("x-ratelimit-reset"))
            return max(0, int(reset_ms / 1000 - time.time()))
        except (TypeError, ValueError):
            return 3600

    @staticmethod
    def _raise_for_status(r: httpx.Response) -> None:
        s = r.status_code
        if s == 429 and (reset_in := OpenRouterProvider._daily_cap(r)) is not None:
            raise AIUnavailable("AI service daily request limit reached", code="quota_exhausted", retry_after=reset_in)
        if s == 401:
            raise AIUnavailable("AI service rejected the API credentials", code="auth")
        if s == 403:  # e.g. a model that is not available to this account/app, or a moderation block: not a credentials problem
            raise AIUnavailable("AI service refused this request for the selected model", code="forbidden")
        if s == 402:
            raise AIUnavailable("AI service account has no remaining credits", code="credits")
        if s == 429:
            ra = r.headers.get("retry-after")
            raise AIUnavailable("AI service is rate limiting requests", code="rate_limited", retry_after=int(ra) if ra and ra.isdigit() else None)
        if s >= 400:
            raise AIUnavailable(f"AI service error ({s})", code="provider_error")

    def generate(self, system: str, user: str, *, max_tokens: int = 600, temperature: float = 0.4) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if self._disable_reasoning:
            body["reasoning"] = {"enabled": False}
        r = self._post(body)
        if r.status_code in RETRY_STATUSES and self._daily_cap(r) is None:  # one short retry for transient upstream trouble
            ra = r.headers.get("retry-after")
            self._sleep(min(float(ra) if ra and ra.replace(".", "", 1).isdigit() else 1.0, MAX_RETRY_WAIT_SECONDS))
            r = self._post(body)
        self._raise_for_status(r)

        try:
            data = r.json()
        except ValueError as exc:
            raise AIUnavailable("AI returned an unreadable response", code="bad_response") from exc
        if not isinstance(data, dict):
            raise AIUnavailable("AI returned an unexpected response", code="bad_response")
        err = data.get("error")
        if err:  # OpenRouter can report upstream failures inside a 200 body
            code = err.get("code") if isinstance(err, dict) else None
            raise AIUnavailable(f"AI service error ({code})" if code else "AI service error",
                                code="rate_limited" if code == 429 else "auth" if code == 401 else "forbidden" if code == 403 else "credits" if code == 402 else "provider_error")
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIUnavailable("AI returned an unexpected response", code="bad_response") from exc

        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        self.usage["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        try:  # OpenRouter reports the real charge per call in USD
            self.usage["cost"] += float(usage.get("cost") or 0)
        except (TypeError, ValueError):
            pass
        self.usage["model"] = data.get("model") or self.model

        if isinstance(content, list):  # some providers return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str) or not content.strip():
            raise AIUnavailable("AI returned an empty response", code="bad_response")
        if choice.get("finish_reason") == "length":
            raise AIUnavailable("AI response was cut off", code="bad_response")
        return content.strip()
