import httpx

from app.services.ai.base import AIUnavailable

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: int = 25):
        self._key = api_key
        self.model = model
        self._timeout = timeout

    def generate(self, system: str, user: str, *, max_tokens: int = 600, temperature: float = 0.4) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        try:
            # API key goes in a header (never in the URL, so it can't leak into access logs).
            r = httpx.post(ENDPOINT.format(model=self.model), json=body,
                           headers={"x-goog-api-key": self._key}, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise AIUnavailable("AI service unreachable") from exc
        if r.status_code != 200:
            raise AIUnavailable(f"AI service error ({r.status_code})")
        try:
            parts = r.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, ValueError) as exc:
            raise AIUnavailable("AI returned an unexpected response") from exc
        if not text:
            raise AIUnavailable("AI returned an empty response")
        return text
