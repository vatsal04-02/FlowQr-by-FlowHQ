"""The Meta Graph API client for WhatsApp (official Cloud API only). Thin on purpose: one method per Meta call FlowQR makes in Phase 1.

* Every request goes to settings.whatsapp_graph_base_url (tests and local development point it at a mock; production uses graph.facebook.com).
* The app secret and every access token are redacted from anything that could reach a log or an API response (`redact`). Errors carry Meta's short message and code, never the request.
* A network failure or a 5xx/429 is `retryable`; a 4xx from Meta is final.
"""
import logging
import re

import httpx

from app.core.config import settings

log = logging.getLogger("flowqr.whatsapp.meta")
_TOKEN = re.compile(r"\bEA[A-Za-z0-9]{12,}\b")


def redact(text: str) -> str:
    out = _TOKEN.sub("[token]", str(text))
    for secret in (settings.meta_app_secret, settings.whatsapp_webhook_verify_token):
        if secret and len(secret) >= 8:
            out = out.replace(secret, "[secret]")
    return out[:300]


class MetaError(Exception):
    def __init__(self, message: str, *, code: int | None = None, status: int = 0, retryable: bool = False):
        super().__init__(redact(message))
        self.message = redact(message)
        self.code = code
        self.status = status
        self.retryable = retryable


class MetaClient:
    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=15)

    def _url(self, path: str) -> str:
        return f"{settings.whatsapp_graph_base_url.rstrip('/')}/{settings.whatsapp_graph_version}/{path.lstrip('/')}"

    def _call(self, method: str, path: str, *, token: str | None = None, params: dict | None = None, data: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            r = self._http.request(method, self._url(path), params=params, data=data, headers=headers)
        except httpx.HTTPError as exc:  # never include the request (it can carry a secret)
            raise MetaError(f"Could not reach Meta ({type(exc).__name__})", retryable=True) from None
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 400:
            err = body.get("error", {}) if isinstance(body, dict) else {}
            raise MetaError(err.get("message") or f"Meta answered {r.status_code}", code=err.get("code"), status=r.status_code, retryable=r.status_code >= 500 or r.status_code == 429)
        return body if isinstance(body, dict) else {}

    # ---- Embedded Signup
    def exchange_code(self, code: str) -> str:
        """The one-time code the Embedded Signup popup returns -> a business access token."""
        body = self._call("GET", "oauth/access_token", params={"client_id": settings.meta_app_id, "client_secret": settings.meta_app_secret, "code": code})
        token = body.get("access_token")
        if not token:
            raise MetaError("Meta did not return an access token")
        return token

    def debug_token(self, token: str) -> dict:
        """Is the token valid, when does it expire, which assets was it granted? (app-token call; the app secret never leaves the server)"""
        body = self._call("GET", "debug_token", params={"input_token": token, "access_token": f"{settings.meta_app_id}|{settings.meta_app_secret}"})
        return body.get("data", {}) if isinstance(body.get("data"), dict) else {}

    def phone_number(self, token: str, phone_number_id: str) -> dict:
        return self._call("GET", phone_number_id, token=token, params={"fields": "display_phone_number,verified_name,quality_rating,code_verification_status"})

    def subscribe_app(self, token: str, waba_id: str) -> None:
        self._call("POST", f"{waba_id}/subscribed_apps", token=token)

    def unsubscribe_app(self, token: str, waba_id: str) -> None:
        self._call("DELETE", f"{waba_id}/subscribed_apps", token=token)


_client: MetaClient | None = None


def get_meta_client() -> MetaClient:
    global _client
    if _client is None:
        _client = MetaClient()
    return _client


def set_meta_client(c: MetaClient | None) -> None:
    """Tests and local development install a client whose transport is a mock."""
    global _client
    _client = c
