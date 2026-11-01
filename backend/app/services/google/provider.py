"""Google OAuth + Business Profile API access behind an interface.

`HttpGoogleProvider` talks to the real Google endpoints and needs valid OAuth credentials AND
Business Profile API access approved by Google for your Cloud project. Without those it raises
`GoogleNotConfigured` / Google's own 403 - it never simulates success.
"""
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.google.errors import GoogleAPIError, GoogleAuthRevoked, GoogleNotConfigured, GoogleRateLimited

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
INFO_URL = "https://mybusinessbusinessinformation.googleapis.com/v1"
REVIEWS_URL = "https://mybusiness.googleapis.com/v4"

STAR = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


@dataclass
class TokenSet:
    access_token: str
    expires_in: int
    refresh_token: str | None = None
    scope: str | None = None


@dataclass
class GAccount:
    name: str  # accounts/123
    title: str | None = None


@dataclass
class GLocation:
    account_name: str
    name: str  # locations/456
    title: str | None = None
    address: str | None = None
    place_id: str | None = None
    review_url: str | None = None


@dataclass
class GReview:
    external_id: str
    rating: int
    text: str | None
    reviewer_name: str | None
    created_at: str
    updated_at: str | None
    reply_text: str | None = None
    reply_updated_at: str | None = None


@dataclass
class GReviewPage:
    reviews: list[GReview] = field(default_factory=list)
    next_page_token: str | None = None


class GoogleBusinessProvider(Protocol):
    def build_auth_url(self, state: str) -> str: ...
    def exchange_code(self, code: str) -> TokenSet: ...
    def refresh_access_token(self, refresh_token: str) -> TokenSet: ...
    def get_userinfo(self, access_token: str) -> dict: ...
    def list_accounts(self, access_token: str) -> list[GAccount]: ...
    def list_locations(self, access_token: str, account_name: str) -> list[GLocation]: ...
    def list_reviews(self, access_token: str, account_name: str, location_name: str, page_token: str | None = None) -> GReviewPage: ...
    def reply_to_review(self, access_token: str, account_name: str, location_name: str, review_id: str, comment: str) -> None: ...
    def revoke(self, token: str) -> None: ...


def _raise_for(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    if r.status_code == 429:
        ra = r.headers.get("retry-after")
        raise GoogleRateLimited(int(ra) if ra and ra.isdigit() else None)
    if r.status_code == 401:
        raise GoogleAuthRevoked("Google rejected the access token")
    msg = ""
    try:
        err = r.json().get("error", {})
        msg = err.get("message", "") if isinstance(err, dict) else str(err)
        if r.status_code == 403 and "RATE_LIMIT" in r.text.upper():
            raise GoogleRateLimited(None)
    except ValueError:
        pass
    raise GoogleAPIError(r.status_code, msg)


class HttpGoogleProvider:
    def __init__(self):
        if not settings.google_configured:
            raise GoogleNotConfigured("Google OAuth credentials are not configured")
        self._http = httpx.Client(timeout=20)

    # ---- OAuth ----
    def build_auth_url(self, state: str) -> str:
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": f"openid email {settings.google_scopes}",
            "access_type": "offline",  # refresh token
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def _token_request(self, data: dict) -> TokenSet:
        r = self._http.post(TOKEN_URL, data={**data, "client_id": settings.google_client_id,
                                              "client_secret": settings.google_client_secret})
        if r.status_code in (400, 401):
            body = {}
            try:
                body = r.json()
            except ValueError:
                pass
            if body.get("error") == "invalid_grant":
                raise GoogleAuthRevoked("Authorization was revoked or expired")
            raise GoogleAPIError(r.status_code, body.get("error", "token error"))
        _raise_for(r)
        j = r.json()
        return TokenSet(access_token=j["access_token"], expires_in=int(j.get("expires_in", 3600)),
                        refresh_token=j.get("refresh_token"), scope=j.get("scope"))

    def exchange_code(self, code: str) -> TokenSet:
        return self._token_request({"code": code, "grant_type": "authorization_code",
                                    "redirect_uri": settings.google_redirect_uri})

    def refresh_access_token(self, refresh_token: str) -> TokenSet:
        return self._token_request({"refresh_token": refresh_token, "grant_type": "refresh_token"})

    def get_userinfo(self, access_token: str) -> dict:
        r = self._http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        _raise_for(r)
        return r.json()

    def revoke(self, token: str) -> None:
        try:
            self._http.post(REVOKE_URL, data={"token": token})
        except httpx.HTTPError:
            pass  # best effort

    # ---- Business Profile ----
    def _get(self, url: str, access_token: str, params: dict | None = None) -> dict:
        try:
            r = self._http.get(url, params=params, headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as exc:
            raise GoogleAPIError(503, "network error") from exc
        _raise_for(r)
        return r.json()

    def list_accounts(self, access_token: str) -> list[GAccount]:
        out, token = [], None
        while True:
            j = self._get(ACCOUNTS_URL, access_token, {"pageSize": 20, **({"pageToken": token} if token else {})})
            out += [GAccount(name=a["name"], title=a.get("accountName")) for a in j.get("accounts", [])]
            token = j.get("nextPageToken")
            if not token:
                return out

    def list_locations(self, access_token: str, account_name: str) -> list[GLocation]:
        out, token = [], None
        while True:
            params = {"readMask": "name,title,storefrontAddress,metadata", "pageSize": 100}
            if token:
                params["pageToken"] = token
            j = self._get(f"{INFO_URL}/{account_name}/locations", access_token, params)
            for loc in j.get("locations", []):
                addr = loc.get("storefrontAddress") or {}
                parts = (addr.get("addressLines") or []) + [addr.get("locality", ""), addr.get("administrativeArea", "")]
                meta = loc.get("metadata") or {}
                out.append(GLocation(
                    account_name=account_name, name=loc["name"], title=loc.get("title"),
                    address=", ".join(p for p in parts if p) or None,
                    place_id=meta.get("placeId"), review_url=meta.get("newReviewUri"),
                ))
            token = j.get("nextPageToken")
            if not token:
                return out

    def list_reviews(self, access_token: str, account_name: str, location_name: str, page_token: str | None = None) -> GReviewPage:
        params = {"pageSize": 50, "orderBy": "updateTime desc"}
        if page_token:
            params["pageToken"] = page_token
        j = self._get(f"{REVIEWS_URL}/{account_name}/{location_name}/reviews", access_token, params)
        reviews = []
        for rv in j.get("reviews", []):
            reviewer = rv.get("reviewer") or {}
            reply = rv.get("reviewReply") or {}
            reviews.append(GReview(
                external_id=rv.get("reviewId") or rv["name"].rsplit("/", 1)[-1],
                rating=STAR.get(rv.get("starRating", ""), 0),
                text=rv.get("comment"),
                reviewer_name=None if reviewer.get("isAnonymous") else reviewer.get("displayName"),
                created_at=rv["createTime"], updated_at=rv.get("updateTime"),
                reply_text=reply.get("comment"), reply_updated_at=reply.get("updateTime"),
            ))
        return GReviewPage(reviews=reviews, next_page_token=j.get("nextPageToken"))

    def reply_to_review(self, access_token: str, account_name: str, location_name: str, review_id: str, comment: str) -> None:
        url = f"{REVIEWS_URL}/{account_name}/{location_name}/reviews/{review_id}/reply"
        try:
            r = self._http.put(url, json={"comment": comment}, headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as exc:
            raise GoogleAPIError(503, "network error") from exc
        _raise_for(r)
