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
    # --- Business Profile management (only what Google's APIs actually support) ---
    def get_location_details(self, access_token: str, location_name: str) -> dict: ...
    def update_location(self, access_token: str, location_name: str, changes: dict) -> dict: ...
    def search_categories(self, access_token: str, query: str, region: str = "IN", language: str = "en") -> list[dict]: ...
    def list_posts(self, access_token: str, account_name: str, location_name: str) -> list[dict]: ...
    def create_post(self, access_token: str, account_name: str, location_name: str, post: dict) -> dict: ...
    def delete_post(self, access_token: str, post_name: str) -> None: ...
    def list_media(self, access_token: str, account_name: str, location_name: str) -> list[dict]: ...
    def add_media(self, access_token: str, account_name: str, location_name: str, source_url: str, category: str) -> dict: ...
    def delete_media(self, access_token: str, media_name: str) -> None: ...
    def fetch_performance(self, access_token: str, location_name: str, start: str, end: str, metrics: list[str]) -> dict: ...


PERFORMANCE_URL = "https://businessprofileperformance.googleapis.com/v1"
PERFORMANCE_METRICS = [
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", "CALL_CLICKS", "WEBSITE_CLICKS", "BUSINESS_DIRECTION_REQUESTS",
    "BUSINESS_CONVERSATIONS", "BUSINESS_BOOKINGS",
]
DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]


def _hhmm(t: dict | None) -> str:
    t = t or {}
    return f"{int(t.get('hours', 0)):02d}:{int(t.get('minutes', 0)):02d}"


def _time(s: str) -> dict:
    h, m = s.split(":")
    return {"hours": int(h), "minutes": int(m)}


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

    # ================= Business Profile management =================
    def _send(self, method: str, url: str, access_token: str, *, params: dict | None = None, json: dict | None = None) -> dict:
        try:
            r = self._http.request(method, url, params=params, json=json, headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as exc:
            raise GoogleAPIError(503, "network error") from exc
        _raise_for(r)
        return r.json() if r.content else {}

    def get_location_details(self, access_token, location_name):
        mask = "name,title,phoneNumbers,categories,storefrontAddress,websiteUri,regularHours,profile,metadata"
        j = self._send("GET", f"{INFO_URL}/{location_name}", access_token, params={"readMask": mask})
        cats = j.get("categories") or {}
        periods = (j.get("regularHours") or {}).get("periods", [])
        return {
            "title": j.get("title"), "description": (j.get("profile") or {}).get("description"),
            "phone": (j.get("phoneNumbers") or {}).get("primaryPhone"), "website": j.get("websiteUri"),
            "primary_category": _cat(cats.get("primaryCategory")), "additional_categories": [_cat(c) for c in cats.get("additionalCategories", [])],
            "hours": [{"day": p.get("openDay"), "open": _hhmm(p.get("openTime")), "close": _hhmm(p.get("closeTime"))} for p in periods],
        }

    def update_location(self, access_token, location_name, changes):
        """`changes` keys: description, hours, primary_category, additional_categories, phone, website."""
        body: dict = {}
        mask: list[str] = []
        if "description" in changes:
            body["profile"] = {"description": changes["description"]}
            mask.append("profile")
        if "hours" in changes:
            body["regularHours"] = {"periods": [{"openDay": h["day"], "openTime": _time(h["open"]), "closeDay": h["day"], "closeTime": _time(h["close"])} for h in changes["hours"]]}
            mask.append("regularHours")
        if "primary_category" in changes or "additional_categories" in changes:
            cats: dict = {}
            if changes.get("primary_category"):
                cats["primaryCategory"] = {"name": changes["primary_category"]}
            if "additional_categories" in changes:
                cats["additionalCategories"] = [{"name": c} for c in changes["additional_categories"]]
            body["categories"] = cats
            mask.append("categories")
        if "phone" in changes:
            body["phoneNumbers"] = {"primaryPhone": changes["phone"]}
            mask.append("phoneNumbers")
        if "website" in changes:
            body["websiteUri"] = changes["website"]
            mask.append("websiteUri")
        self._send("PATCH", f"{INFO_URL}/{location_name}", access_token, params={"updateMask": ",".join(mask)}, json=body)
        return self.get_location_details(access_token, location_name)  # return what Google now holds, not what we sent

    def search_categories(self, access_token, query, region="IN", language="en"):
        j = self._send("GET", f"{INFO_URL}/categories", access_token,
                       params={"regionCode": region, "languageCode": language, "view": "BASIC", "pageSize": 20, "filter": f'displayName="{query}"'})
        return [_cat(c) for c in j.get("categories", [])]

    def list_posts(self, access_token, account_name, location_name):
        j = self._send("GET", f"{REVIEWS_URL}/{account_name}/{location_name}/localPosts", access_token, params={"pageSize": 20})
        return [_post(p) for p in j.get("localPosts", [])]

    def create_post(self, access_token, account_name, location_name, post):
        body = {"languageCode": post.get("language", "en"), "summary": post["summary"], "topicType": "STANDARD"}
        if post.get("cta_type"):
            body["callToAction"] = {"actionType": post["cta_type"], **({"url": post["cta_url"]} if post.get("cta_url") else {})}
        if post.get("photo_url"):
            body["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": post["photo_url"]}]
        return _post(self._send("POST", f"{REVIEWS_URL}/{account_name}/{location_name}/localPosts", access_token, json=body))

    def delete_post(self, access_token, post_name):
        self._send("DELETE", f"{REVIEWS_URL}/{post_name}", access_token)

    def list_media(self, access_token, account_name, location_name):
        j = self._send("GET", f"{REVIEWS_URL}/{account_name}/{location_name}/media", access_token, params={"pageSize": 50})
        return [_media(m) for m in j.get("mediaItems", [])]

    def add_media(self, access_token, account_name, location_name, source_url, category):
        body = {"mediaFormat": "PHOTO", "sourceUrl": source_url, "locationAssociation": {"category": category}}
        return _media(self._send("POST", f"{REVIEWS_URL}/{account_name}/{location_name}/media", access_token, json=body))

    def delete_media(self, access_token, media_name):
        self._send("DELETE", f"{REVIEWS_URL}/{media_name}", access_token)

    def fetch_performance(self, access_token, location_name, start, end, metrics):
        sy, sm, sd = (int(x) for x in start.split("-"))
        ey, em, ed = (int(x) for x in end.split("-"))
        params = [("dailyMetrics", m) for m in metrics] + [
            ("dailyRange.startDate.year", sy), ("dailyRange.startDate.month", sm), ("dailyRange.startDate.day", sd),
            ("dailyRange.endDate.year", ey), ("dailyRange.endDate.month", em), ("dailyRange.endDate.day", ed)]
        j = self._send("GET", f"{PERFORMANCE_URL}/{location_name}:fetchMultiDailyMetricsTimeSeries", access_token, params=params)  # type: ignore[arg-type]
        out: dict[str, list] = {}
        for multi in j.get("multiDailyMetricTimeSeries", []):
            for series in multi.get("dailyMetricTimeSeries", []):
                pts = []
                for dv in (series.get("timeSeries") or {}).get("datedValues", []):
                    d = dv.get("date", {})
                    pts.append({"date": f"{d.get('year')}-{int(d.get('month', 1)):02d}-{int(d.get('day', 1)):02d}", "value": int(dv.get("value", 0) or 0)})
                out[series.get("dailyMetric")] = pts
        return out


def _cat(c: dict | None) -> dict | None:
    return {"id": c.get("name"), "name": c.get("displayName")} if c else None


def _post(p: dict) -> dict:
    return {"name": p.get("name"), "summary": p.get("summary"), "state": p.get("state"), "created_at": p.get("createTime"),
            "cta_type": (p.get("callToAction") or {}).get("actionType"), "cta_url": (p.get("callToAction") or {}).get("url"),
            "search_url": p.get("searchUrl")}


def _media(m: dict) -> dict:
    return {"name": m.get("name"), "category": (m.get("locationAssociation") or {}).get("category"), "url": m.get("googleUrl") or m.get("sourceUrl"),
            "thumbnail": m.get("thumbnailUrl"), "created_at": m.get("createTime")}
