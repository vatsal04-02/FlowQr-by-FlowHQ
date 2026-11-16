"""Google OAuth + Business Profile API access behind an interface.

`HttpGoogleProvider` talks to the real Google endpoints and needs valid OAuth credentials AND
Business Profile API access approved by Google for your Cloud project. Without those it raises
`GoogleNotConfigured` / Google's own error - it never simulates success.

Every URL, parameter, field and enum below was checked against Google's published reference on 2026-11-10
(docs/GOOGLE_API_AUDIT.md lists the page for each call). The request/response shapes are pinned by
tests/test_google_contract.py. None of it has been exercised against the live API yet: use
`python -m app.cli google-smoke` once credentials and approval exist.
"""
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.google.errors import (
    GoogleAPIError, GoogleApiNotApproved, GoogleAuthRevoked, GoogleNotConfigured, GoogleRateLimited, GoogleScopeMissing,
)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
INFO_URL = "https://mybusinessbusinessinformation.googleapis.com/v1"
REVIEWS_URL = "https://mybusiness.googleapis.com/v4"  # reviews, localPosts and media still live on the v4 surface
PERFORMANCE_URL = "https://businessprofileperformance.googleapis.com/v1"
UPLOAD_URL = "https://mybusiness.googleapis.com/upload/v1/media"  # byte upload target for media:startUpload references

BUSINESS_SCOPE = "https://www.googleapis.com/auth/business.manage"
LEGACY_BUSINESS_SCOPE = "https://www.googleapis.com/auth/plus.business.manage"  # deprecated alias Google still accepts
ERROR_INFO_TYPE = "type.googleapis.com/google.rpc.ErrorInfo"

STAR = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}  # STAR_RATING_UNSPECIFIED -> 0
# DailyMetric values that are current in the Performance API v1 reference. Deliberately absent:
#   BUSINESS_CONVERSATIONS (deprecated 2024-07-31, removal date 2026-01-31) and BUSINESS_FOOD_ORDERS (deprecated 2025-10-22).
# One unknown enum value fails the whole request, so retired metrics must not be sent.
PERFORMANCE_METRICS = [
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", "CALL_CLICKS", "WEBSITE_CLICKS", "BUSINESS_DIRECTION_REQUESTS",
    "MESSAGING_CLICKS", "BUSINESS_BOOKINGS", "BUSINESS_FOOD_MENU_CLICKS",
]
DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
MAX_POSTS = 100  # newest posts shown in the dashboard
REPLY_MAX_BYTES = 4096  # ReviewReply.comment limit (bytes, not characters)


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
    reply_state: str | None = None  # PENDING | REJECTED | APPROVED (Google's moderation of the owner reply), None if not sent
    reply_policy_violation: str | None = None  # only when reply_state == REJECTED


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
    def reply_to_review(self, access_token: str, account_name: str, location_name: str, review_id: str, comment: str) -> dict | None: ...
    def delete_reply(self, access_token: str, account_name: str, location_name: str, review_id: str) -> None: ...
    def revoke(self, token: str) -> None: ...
    # Business Profile management (only what Google's APIs and the business.manage scope allow)
    def get_location_details(self, access_token: str, location_name: str) -> dict: ...
    def update_location(self, access_token: str, location_name: str, changes: dict) -> dict: ...
    def search_categories(self, access_token: str, query: str, region: str = "IN", language: str = "en") -> list[dict]: ...
    def list_posts(self, access_token: str, account_name: str, location_name: str) -> list[dict]: ...
    def create_post(self, access_token: str, account_name: str, location_name: str, post: dict) -> dict: ...
    def update_post(self, access_token: str, post_name: str, post: dict) -> dict: ...
    def delete_post(self, access_token: str, post_name: str) -> None: ...
    def list_media(self, access_token: str, account_name: str, location_name: str) -> list[dict]: ...
    def add_media(self, access_token: str, account_name: str, location_name: str, source_url: str, category: str) -> dict: ...
    def delete_media(self, access_token: str, media_name: str) -> None: ...
    def fetch_performance(self, access_token: str, location_name: str, start: str, end: str, metrics: list[str]) -> dict: ...
    def upload_media_bytes(self, access_token: str, account_name: str, location_name: str, data: bytes, content_type: str, category: str, description: str | None = None) -> dict: ...
    def get_media(self, access_token: str, media_name: str) -> dict: ...
    def search_keywords(self, access_token: str, location_name: str, start_month: str, end_month: str, limit: int = 300) -> list[dict]: ...


def has_business_scope(scope: str | None) -> bool:
    """True if a token response's space-separated `scope` grants Business Profile access."""
    granted = set((scope or "").split())
    return BUSINESS_SCOPE in granted or LEGACY_BUSINESS_SCOPE in granted


def _hhmm(t: dict | None) -> str:
    t = t or {}  # proto3 JSON omits zero values, so midnight arrives as {} (documented on TimePeriod)
    return f"{int(t.get('hours', 0)):02d}:{int(t.get('minutes', 0)):02d}"


def _time(s: str) -> dict:
    h, m = s.split(":")
    return {"hours": int(h), "minutes": int(m)}


def parse_error(status: int, body) -> dict:
    """Normalise a Google error body (AIP-193: {"error": {code, message, status, details[]}}) into
    {message, status, reason, metadata}. `reason`/`metadata` come from the google.rpc.ErrorInfo detail when present."""
    out = {"message": "", "status": None, "reason": None, "metadata": {}}
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, str):  # OAuth-style {"error": "invalid_grant", "error_description": "..."}
        out["message"] = err
        return out
    if not isinstance(err, dict):
        return out
    out["message"], out["status"] = str(err.get("message") or ""), err.get("status")
    for d in err.get("details") or []:
        if isinstance(d, dict) and d.get("@type") == ERROR_INFO_TYPE:
            out["reason"] = d.get("reason")
            out["metadata"] = d.get("metadata") if isinstance(d.get("metadata"), dict) else {}
            break
    if out["reason"] is None:  # legacy shape: error.errors[].reason ("rateLimitExceeded", "accessNotConfigured", ...)
        legacy = [e.get("reason") for e in err.get("errors") or [] if isinstance(e, dict)]
        out["legacy_reason"] = legacy[0] if legacy else None
    return out


def classify_error(status: int, body, retry_after: str | None = None) -> Exception:
    """Map a Google error response to the exception the app acts on. Structured fields first, wording only as a fallback.

    What is documented and what is not:
      * SERVICE_DISABLED (ErrorInfo.reason, metadata.service)              documented -> API not enabled on the project
      * RATE_LIMIT_EXCEEDED / RESOURCE_QUOTA_EXCEEDED, HTTP 429            documented -> rate limited
      * ACCESS_TOKEN_SCOPE_INSUFFICIENT                                    documented -> reconnect with the scope
      * quota 0 QPM == "project not approved"                              documented (prereqs page), but Google does not
        document a field that says the limit is 0. `metadata.quota_limit_value == "0"` is honoured when present; otherwise a
        429 is reported as a rate limit and the *caller* decides (first-ever call on a connection -> probably unapproved).
    """
    info = parse_error(status, body)
    msg, reason, meta = info["message"], info["reason"], info["metadata"]
    legacy = info.get("legacy_reason")
    low = msg.lower()
    if reason == "SERVICE_DISABLED" or legacy == "accessNotConfigured" or (
            status == 403 and ("has not been used in project" in low or "it is disabled" in low)):
        return GoogleApiNotApproved(status, msg, why="service_disabled", service=meta.get("service"))
    quota = (status == 429 or reason in ("RATE_LIMIT_EXCEEDED", "RESOURCE_QUOTA_EXCEEDED") or info["status"] == "RESOURCE_EXHAUSTED"
             or legacy in ("rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"))
    if quota:
        if str(meta.get("quota_limit_value", "")) == "0":
            return GoogleApiNotApproved(status, msg, why="quota_zero", service=meta.get("service"))
        return GoogleRateLimited(int(retry_after) if retry_after and retry_after.isdigit() else None, quota_metric=meta.get("quota_metric"))
    if reason == "ACCESS_TOKEN_SCOPE_INSUFFICIENT" or (status == 403 and "insufficient authentication scopes" in low):
        return GoogleScopeMissing("The Google token does not include Business Profile access")
    if status == 401:
        return GoogleAuthRevoked("Google rejected the access token")
    return GoogleAPIError(status, msg, reason=reason, google_status=info["status"])


def _raise_for(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    try:
        body = r.json()
    except ValueError:
        body = None
    raise classify_error(r.status_code, body, r.headers.get("retry-after"))


class HttpGoogleProvider:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        if not settings.google_configured:
            raise GoogleNotConfigured("Google OAuth credentials are not configured")
        self._http = httpx.Client(timeout=20, transport=transport)  # transport is injected only by the contract tests

    # ---- OAuth ----
    def build_auth_url(self, state: str) -> str:
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": f"openid email {settings.google_scopes}",
            "access_type": "offline",  # refresh token
            "prompt": "consent",  # Google only returns a refresh token on the first consent unless consent is forced
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def _token_request(self, data: dict) -> TokenSet:
        try:
            r = self._http.post(TOKEN_URL, data={**data, "client_id": settings.google_client_id,
                                                  "client_secret": settings.google_client_secret})
        except httpx.HTTPError as exc:
            raise GoogleAPIError(503, "network error") from exc
        if r.status_code in (400, 401):
            body = {}
            try:
                body = r.json()
            except ValueError:
                pass
            if body.get("error") == "invalid_grant":
                raise GoogleAuthRevoked("Authorization was revoked or expired")
            raise GoogleAPIError(r.status_code, str(body.get("error", "token error")))
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
        return self._send("GET", USERINFO_URL, access_token)

    def revoke(self, token: str) -> None:
        try:
            self._http.post(REVOKE_URL, data={"token": token})
        except httpx.HTTPError:
            pass  # best effort

    # ---- transport ----
    def _send(self, method: str, url: str, access_token: str, *, params=None, json: dict | None = None) -> dict:
        try:
            r = self._http.request(method, url, params=params, json=json, headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as exc:
            raise GoogleAPIError(503, "network error") from exc
        _raise_for(r)
        if not r.content:
            return {}
        try:
            j = r.json()
        except ValueError as exc:  # a 2xx that is not JSON is not a success we can vouch for
            raise GoogleAPIError(502, "Google returned an unreadable response") from exc
        return j if isinstance(j, dict) else {}

    def _get(self, url: str, access_token: str, params: dict | None = None) -> dict:
        return self._send("GET", url, access_token, params=params)

    # ---- accounts / locations ----
    def list_accounts(self, access_token: str) -> list[GAccount]:
        out, token = [], None
        while True:
            j = self._get(ACCOUNTS_URL, access_token, {"pageSize": 20, **({"pageToken": token} if token else {})})  # 20 = default and max
            out += [GAccount(name=a["name"], title=a.get("accountName")) for a in j.get("accounts", [])]
            token = j.get("nextPageToken")
            if not token:
                return out

    def list_locations(self, access_token: str, account_name: str) -> list[GLocation]:
        out, token = [], None
        while True:
            params = {"readMask": "name,title,storefrontAddress,metadata", "pageSize": 100}  # readMask is required; 100 = max
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

    # ---- reviews ----
    def list_reviews(self, access_token: str, account_name: str, location_name: str, page_token: str | None = None) -> GReviewPage:
        params = {"pageSize": 50, "orderBy": "updateTime desc"}  # 50 = max; the sync relies on this ordering
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
                reply_state=_reply_state(reply), reply_policy_violation=reply.get("policyViolation"),
            ))
        return GReviewPage(reviews=reviews, next_page_token=j.get("nextPageToken"))

    def reply_to_review(self, access_token: str, account_name: str, location_name: str, review_id: str, comment: str) -> dict:
        """PUT .../reviews/{id}/reply. Returns Google's ReviewReply ({comment, updated_at, state, policy_violation}): a 200 means
        Google stored the reply, NOT that it is publicly visible - `state` can be PENDING or REJECTED."""
        if len(comment.encode("utf-8")) > REPLY_MAX_BYTES:
            raise GoogleAPIError(400, f"Reply is longer than Google's {REPLY_MAX_BYTES}-byte limit")
        url = f"{REVIEWS_URL}/{account_name}/{location_name}/reviews/{review_id}/reply"
        j = self._send("PUT", url, access_token, json={"comment": comment})
        return {"comment": j.get("comment"), "updated_at": j.get("updateTime"), "state": _reply_state(j),
                "policy_violation": j.get("policyViolation")}

    def delete_reply(self, access_token: str, account_name: str, location_name: str, review_id: str) -> None:
        """DELETE .../reviews/{id}/reply (reviews.deleteReply). Used by the controlled write test to clean up; the app itself never deletes replies."""
        self._send("DELETE", f"{REVIEWS_URL}/{account_name}/{location_name}/reviews/{review_id}/reply", access_token)

    # ================= Business Profile management =================
    def get_location_details(self, access_token, location_name):
        mask = "name,title,phoneNumbers,categories,storefrontAddress,websiteUri,regularHours,profile,metadata,specialHours,openInfo,serviceItems"
        j = self._send("GET", f"{INFO_URL}/{location_name}", access_token, params={"readMask": mask})  # readMask is required
        cats = j.get("categories") or {}
        periods = (j.get("regularHours") or {}).get("periods", [])
        return {
            "title": j.get("title"), "description": (j.get("profile") or {}).get("description"),
            "phone": (j.get("phoneNumbers") or {}).get("primaryPhone"), "website": j.get("websiteUri"),
            "primary_category": _cat(cats.get("primaryCategory")), "additional_categories": [_cat(c) for c in cats.get("additionalCategories", [])],
            "hours": [{"day": p.get("openDay"), "open": _hhmm(p.get("openTime")), "close": _hhmm(p.get("closeTime"))} for p in periods],
            "services": [s for s in (_service(x) for x in j.get("serviceItems") or []) if s],
            "special_hours": [{"date": _ymd(p.get("startDate")), "closed": bool(p.get("closed"))} for p in (j.get("specialHours") or {}).get("specialHourPeriods", [])],
            "open_status": (j.get("openInfo") or {}).get("status"),
        }

    def update_location(self, access_token, location_name, changes):
        """`changes` keys: description, hours, primary_category, additional_categories, phone, website.

        Google documents that `phoneNumbers` and `categories` cannot be updated one sub-field at a time: both sub-fields must be
        sent or the missing one is cleared. So the current values are read first and merged, and nothing the caller did not ask
        to change is ever dropped."""
        body: dict = {}
        mask: list[str] = []
        need_phone = "phone" in changes
        need_cats = "primary_category" in changes or "additional_categories" in changes
        current: dict = {}
        if need_phone or need_cats:
            read = ",".join(m for m, on in (("phoneNumbers", need_phone), ("categories", need_cats)) if on)
            current = self._send("GET", f"{INFO_URL}/{location_name}", access_token, params={"readMask": read})
        if "description" in changes:
            body["profile"] = {"description": changes["description"]}
            mask.append("profile")
        if "hours" in changes:
            body["regularHours"] = {"periods": [{"openDay": h["day"], "openTime": _time(h["open"]), "closeDay": h["day"], "closeTime": _time(h["close"])} for h in changes["hours"]]}
            mask.append("regularHours")
        if need_cats:
            now = current.get("categories") or {}
            primary = changes.get("primary_category") or (now.get("primaryCategory") or {}).get("name")
            if not primary:
                raise GoogleAPIError(400, "Google requires a primary category; choose one before changing additional categories")
            extra = (changes["additional_categories"] if changes.get("additional_categories") is not None
                     else [c.get("name") for c in now.get("additionalCategories") or []])
            body["categories"] = {"primaryCategory": {"name": primary}, "additionalCategories": [{"name": c} for c in extra if c and c != primary]}
            mask.append("categories")
        if need_phone:
            now = current.get("phoneNumbers") or {}
            body["phoneNumbers"] = {"primaryPhone": changes["phone"], "additionalPhones": now.get("additionalPhones") or []}
            mask.append("phoneNumbers")
        if "website" in changes:
            body["websiteUri"] = changes["website"]
            mask.append("websiteUri")
        self._send("PATCH", f"{INFO_URL}/{location_name}", access_token, params={"updateMask": ",".join(mask)}, json=body)
        return self.get_location_details(access_token, location_name)  # return what Google now holds, not what we sent

    def search_categories(self, access_token, query, region="IN", language="en"):
        # regionCode, languageCode and view are all required. The documented filter form is `displayName=foo` (prefix match on
        # the category name); '=' and quotes in the user's text would corrupt it, so they are stripped.
        q = "".join(ch for ch in query if ch.isalnum() or ch in " -&'").strip()
        j = self._send("GET", f"{INFO_URL}/categories", access_token,
                       params={"regionCode": region, "languageCode": language, "view": "BASIC", "pageSize": 20, "filter": f"displayName={q}"})
        return [_cat(c) for c in j.get("categories", [])]

    def list_posts(self, access_token, account_name, location_name):
        out, token = [], None
        while len(out) < MAX_POSTS:
            params = {"pageSize": 100, **({"pageToken": token} if token else {})}  # default 20, max 100
            j = self._send("GET", f"{REVIEWS_URL}/{account_name}/{location_name}/localPosts", access_token, params=params)
            out += [_post(p) for p in j.get("localPosts", [])]
            token = j.get("nextPageToken")
            if not token:
                break
        return out[:MAX_POSTS]

    def create_post(self, access_token, account_name, location_name, post):
        topic = post.get("topic_type") or "STANDARD"
        body = {"languageCode": post.get("language", "en"), "summary": post["summary"], "topicType": topic}  # topicType is required
        if topic in ("EVENT", "OFFER"):
            # `event` is required for EVENT and OFFER; its TimeInterval must contain all four fields (Google reference).
            s, e = post["event_start"], post["event_end"]  # naive local datetimes in the business's time zone
            body["event"] = {"title": post["event_title"], "schedule": {
                "startDate": {"year": s.year, "month": s.month, "day": s.day}, "startTime": {"hours": s.hour, "minutes": s.minute, "seconds": 0, "nanos": 0},
                "endDate": {"year": e.year, "month": e.month, "day": e.day}, "endTime": {"hours": e.hour, "minutes": e.minute, "seconds": 0, "nanos": 0}}}
        if topic == "OFFER":
            offer = {k: v for k, v in (("couponCode", post.get("offer_coupon")), ("redeemOnlineUrl", post.get("offer_url")), ("termsConditions", post.get("offer_terms"))) if v}
            if offer:
                body["offer"] = offer
        if post.get("cta_type") and topic != "OFFER":  # Google ignores callToAction on OFFER posts
            # CALL uses the profile's phone number: Google says `url` must be left unset for it.
            cta = {"actionType": post["cta_type"]}
            if post["cta_type"] != "CALL" and post.get("cta_url"):
                cta["url"] = post["cta_url"]
            body["callToAction"] = cta
        if post.get("photo_url"):
            body["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": post["photo_url"]}]  # sourceUrl is the only supported data field here
        return _post(self._send("POST", f"{REVIEWS_URL}/{account_name}/{location_name}/localPosts", access_token, json=body))

    def update_post(self, access_token, post_name, post):
        """PATCH v4 localPosts with an explicit updateMask (only summary and call-to-action are editable here).
        A masked field that is absent from the body is cleared, which is how the button is removed."""
        body, mask = {"summary": post["summary"]}, ["summary"]
        if "cta_type" in post:
            mask.append("callToAction")
            if post.get("cta_type"):
                cta = {"actionType": post["cta_type"]}
                if post["cta_type"] != "CALL" and post.get("cta_url"):
                    cta["url"] = post["cta_url"]
                body["callToAction"] = cta
        return _post(self._send("PATCH", f"{REVIEWS_URL}/{post_name}", access_token, params={"updateMask": ",".join(mask)}, json=body))

    def delete_post(self, access_token, post_name):
        self._send("DELETE", f"{REVIEWS_URL}/{post_name}", access_token)

    def list_media(self, access_token, account_name, location_name):
        j = self._send("GET", f"{REVIEWS_URL}/{account_name}/{location_name}/media", access_token, params={"pageSize": 100})
        return [_media(m) for m in j.get("mediaItems", [])]

    def add_media(self, access_token, account_name, location_name, source_url, category):
        category = "PROFILE" if category == "LOGO" else category  # LOGO is a deprecated alias for PROFILE
        body = {"mediaFormat": "PHOTO", "sourceUrl": source_url, "locationAssociation": {"category": category}}
        return _media(self._send("POST", f"{REVIEWS_URL}/{account_name}/{location_name}/media", access_token, json=body))

    def delete_media(self, access_token, media_name):
        self._send("DELETE", f"{REVIEWS_URL}/{media_name}", access_token)

    def upload_media_bytes(self, access_token, account_name, location_name, data, content_type, category, description=None):
        """Photo bytes straight to Google (no public URL needed), as documented for v4 media:
        1) media:startUpload -> resourceName, 2) POST the bytes to the upload endpoint, 3) media.create with dataRef + category.
        Returns the MediaItem Google created; `googleUrl` may be absent until Google finishes processing."""
        category = "PROFILE" if category == "LOGO" else category
        ref = self._send("POST", f"{REVIEWS_URL}/{account_name}/{location_name}/media:startUpload", access_token, json={})
        resource = ref.get("resourceName")
        if not resource:
            raise GoogleAPIError(502, "Google did not return an upload reference")
        try:
            r = self._http.request("POST", f"{UPLOAD_URL}/{resource}", params={"uploadType": "media"}, content=data,
                                   headers={"Authorization": f"Bearer {access_token}", "Content-Type": content_type})
        except httpx.HTTPError as exc:
            raise GoogleAPIError(503, "network error") from exc
        _raise_for(r)
        body = {"mediaFormat": "PHOTO", "locationAssociation": {"category": category}, "dataRef": {"resourceName": resource}}
        if description and category not in ("COVER", "PROFILE"):
            body["description"] = description[:300]
        return _media(self._send("POST", f"{REVIEWS_URL}/{account_name}/{location_name}/media", access_token, json=body))

    def get_media(self, access_token, media_name):
        return _media(self._send("GET", f"{REVIEWS_URL}/{media_name}", access_token))

    def search_keywords(self, access_token, location_name, start_month, end_month, limit=300):
        """Monthly search-keyword impressions (Performance API). Each count is either an exact `value` or, for small numbers, only a
        `threshold` Google says the real value is below; both are passed through as Google sent them, never guessed."""
        sy, sm = (int(x) for x in start_month.split("-"))
        ey, em = (int(x) for x in end_month.split("-"))
        out, token = [], None
        while len(out) < limit:
            params = [("monthlyRange.start_month.year", sy), ("monthlyRange.start_month.month", sm),
                      ("monthlyRange.end_month.year", ey), ("monthlyRange.end_month.month", em), ("pageSize", 100)]
            if token:
                params.append(("pageToken", token))
            j = self._send("GET", f"{PERFORMANCE_URL}/{location_name}/searchkeywords/impressions/monthly", access_token, params=params)
            for c in j.get("searchKeywordsCounts", []):
                iv = c.get("insightsValue") or {}
                out.append({"keyword": c.get("searchKeyword"), "value": int(iv["value"]) if iv.get("value") is not None else None,
                            "below": int(iv["threshold"]) if iv.get("threshold") is not None else None})
            token = j.get("nextPageToken")
            if not token:
                break
        return out[:limit]

    def fetch_performance(self, access_token, location_name, start, end, metrics):
        sy, sm, sd = (int(x) for x in start.split("-"))
        ey, em, ed = (int(x) for x in end.split("-"))
        # Parameter spelling follows the example request on Google's reference page (snake_case inside dailyRange).
        params = [("dailyMetrics", m) for m in metrics] + [
            ("dailyRange.start_date.year", sy), ("dailyRange.start_date.month", sm), ("dailyRange.start_date.day", sd),
            ("dailyRange.end_date.year", ey), ("dailyRange.end_date.month", em), ("dailyRange.end_date.day", ed)]
        j = self._send("GET", f"{PERFORMANCE_URL}/{location_name}:fetchMultiDailyMetricsTimeSeries", access_token, params=params)
        out: dict[str, dict[str, int]] = {}
        for multi in j.get("multiDailyMetricTimeSeries", []):
            for series in multi.get("dailyMetricTimeSeries", []):
                metric = series.get("dailyMetric")
                if not metric:
                    continue
                days = out.setdefault(metric, {})
                for dv in (series.get("timeSeries") or {}).get("datedValues", []):
                    d = dv.get("date") or {}
                    if not d.get("year") or not d.get("month") or not d.get("day"):
                        continue  # month-only datapoints are not daily values
                    key = f"{int(d['year']):04d}-{int(d['month']):02d}-{int(d['day']):02d}"
                    # `value` is an int64 sent as a string and omitted when zero. A metric can come back as several series
                    # (one per dailySubEntityType); they are summed into one daily total.
                    days[key] = days.get(key, 0) + int(dv.get("value") or 0)
        return {m: [{"date": k, "value": v} for k, v in sorted(days.items())] for m, days in out.items()}


def _reply_state(reply: dict | None) -> str | None:
    s = (reply or {}).get("reviewReplyState")
    return s if s in ("PENDING", "REJECTED", "APPROVED") else None


def _service(x: dict) -> str | None:
    """A service's display name: custom items carry a label; standard items only a Google service type id."""
    free = x.get("freeFormServiceItem") or {}
    if (free.get("label") or {}).get("displayName"):
        return free["label"]["displayName"]
    return (x.get("structuredServiceItem") or {}).get("serviceTypeId")


def _ymd(d: dict | None) -> str | None:
    return f"{int(d['year']):04d}-{int(d['month']):02d}-{int(d['day']):02d}" if d and d.get("year") and d.get("month") and d.get("day") else None


def _cat(c: dict | None) -> dict | None:
    return {"id": c.get("name"), "name": c.get("displayName")} if c else None


def _post(p: dict) -> dict:
    cta = p.get("callToAction") or {}
    media = [m.get("googleUrl") or m.get("sourceUrl") for m in p.get("media") or [] if isinstance(m, dict)]
    return {"name": p.get("name"), "summary": p.get("summary"), "state": p.get("state"), "created_at": p.get("createTime"),
            "updated_at": p.get("updateTime"), "topic_type": p.get("topicType"), "cta_type": cta.get("actionType"), "cta_url": cta.get("url"),
            "search_url": p.get("searchUrl"), "photo_url": next((m for m in media if m), None)}


def _media(m: dict) -> dict:
    dims = m.get("dimensions") or {}
    return {"name": m.get("name"), "category": (m.get("locationAssociation") or {}).get("category"), "url": m.get("googleUrl") or m.get("sourceUrl"),
            "google_url": m.get("googleUrl"), "thumbnail": m.get("thumbnailUrl"), "created_at": m.get("createTime"),
            "width": dims.get("widthPixels"), "height": dims.get("heightPixels"), "views": (m.get("insights") or {}).get("viewCount")}
