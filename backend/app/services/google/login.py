"""Sign in with Google (OpenID Connect authorization-code flow + PKCE).

Deliberately independent of provider.py (Business Profile): its own OAuth client, only the `openid email profile`
scopes, and no Google tokens are kept - we use the ID token once to learn who the user is, then discard everything.
"""
import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import settings
from app.core.security import constant_time_equals

log = logging.getLogger("flowqr.google.login")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SCOPES = "openid email profile"
JWKS_TTL_SECONDS = 3600
CLOCK_LEEWAY_SECONDS = 60

_jwks_cache: dict = {"keys": {}, "fetched_at": 0.0}


def clear_jwks_cache() -> None:
    _jwks_cache.update(keys={}, fetched_at=0.0)


class GoogleLoginError(Exception):
    """`code` is a stable machine-readable reason the callback maps onto a user-facing message."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str | None
    email_verified: bool
    name: str | None


def pkce_challenge(verifier: str) -> str:
    """RFC 7636 S256: BASE64URL(SHA256(verifier)) without padding."""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _truthy(v) -> bool:
    return v is True or (isinstance(v, str) and v.lower() == "true")


class HttpGoogleLoginProvider:
    def __init__(self, http: httpx.Client | None = None):
        if not settings.google_login_configured:
            raise GoogleLoginError("not_configured", "GOOGLE_LOGIN_CLIENT_ID / GOOGLE_LOGIN_CLIENT_SECRET are not set")
        self._http = http or httpx.Client(timeout=15)

    def build_auth_url(self, state: str, nonce: str, code_challenge: str) -> str:
        return AUTH_URL + "?" + urlencode({
            "client_id": settings.google_login_client_id,
            "redirect_uri": settings.google_login_redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        })

    def exchange_and_verify(self, code: str, code_verifier: str, nonce: str) -> GoogleIdentity:
        id_token = self._exchange(code, code_verifier)
        return self._verify(id_token, nonce)

    def _exchange(self, code: str, code_verifier: str) -> str:
        try:
            r = self._http.post(TOKEN_URL, data={
                "code": code,
                "client_id": settings.google_login_client_id,
                "client_secret": settings.google_login_client_secret,
                "redirect_uri": settings.google_login_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            })
        except httpx.HTTPError as exc:
            raise GoogleLoginError("exchange_failed", "network error") from exc
        if r.status_code != 200:
            reason = ""
            try:
                reason = str(r.json().get("error", ""))
            except ValueError:
                pass
            raise GoogleLoginError("exchange_failed", f"HTTP {r.status_code} {reason}".strip())
        try:
            token = r.json().get("id_token")
        except ValueError:
            token = None
        if not token or not isinstance(token, str):
            raise GoogleLoginError("invalid_token", "no id_token in token response")
        return token

    # ---- ID token validation: signature, issuer, audience, expiry, nonce ----
    def _signing_key(self, kid: str):
        now = time.time()
        stale = now - _jwks_cache["fetched_at"] > JWKS_TTL_SECONDS
        if kid not in _jwks_cache["keys"] or stale:
            try:
                r = self._http.get(JWKS_URL)
                r.raise_for_status()
                jwks = r.json().get("keys", [])
            except (httpx.HTTPError, ValueError) as exc:
                raise GoogleLoginError("exchange_failed", "could not fetch Google signing keys") from exc
            _jwks_cache["keys"] = {k["kid"]: k for k in jwks if k.get("kid")}
            _jwks_cache["fetched_at"] = now
        jwk = _jwks_cache["keys"].get(kid)
        if jwk is None:
            raise GoogleLoginError("invalid_token", "unknown signing key")
        return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))

    def _verify(self, id_token: str, nonce: str) -> GoogleIdentity:
        try:
            header = jwt.get_unverified_header(id_token)
            if header.get("alg") != "RS256":  # never accept "none" / HMAC tokens
                raise GoogleLoginError("invalid_token", "unexpected signing algorithm")
            key = self._signing_key(str(header.get("kid") or ""))
            claims = jwt.decode(
                id_token, key, algorithms=["RS256"], audience=settings.google_login_client_id,
                leeway=CLOCK_LEEWAY_SECONDS, options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except GoogleLoginError:
            raise
        except jwt.PyJWTError as exc:
            raise GoogleLoginError("invalid_token", type(exc).__name__) from exc
        if claims.get("iss") not in ISSUERS:
            raise GoogleLoginError("invalid_token", "wrong issuer")
        got = claims.get("nonce")
        if not isinstance(got, str) or not constant_time_equals(got, nonce):
            raise GoogleLoginError("invalid_nonce")
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise GoogleLoginError("invalid_token", "missing subject")
        email = claims.get("email")
        return GoogleIdentity(
            sub=sub,
            email=email.strip().lower() if isinstance(email, str) and email.strip() else None,
            email_verified=_truthy(claims.get("email_verified")),
            name=claims.get("name") if isinstance(claims.get("name"), str) else None,
        )


def get_google_login_provider() -> HttpGoogleLoginProvider:
    """Factory; tests swap in a provider whose HTTP client is a local mock transport."""
    return HttpGoogleLoginProvider()
