"""Suggestions while a new business is being set up: find the business or the address on Google as the owner types, then fill the forms from the chosen place.

* Uses Places API (New) with the same key as local ranking (RANK_PROVIDER=google_places + RANK_PROVIDER_KEY). Without a key nothing is called and the forms stay manual.
* The key never leaves the server. The browser only sees suggestions and the chosen place's details.
* Cost is bounded two ways: a per-user daily ceiling and a platform monthly ceiling (settings below). Every Google call is one row in the usage ledger
  (feature "onboarding_suggest"), refusals included, so the spend shows up next to the other Places spend.
* Autocomplete and the Details call share one session token, which is how Google bills a typed search plus one pick as a single session.
* A PIN-code lookup (India Post's public directory) fills city and state when there is no Places key, or for a typed address.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.models import ApiUsage
from app.models.base import utcnow
from app.services import usage as api_usage

log = logging.getLogger("flowqr.places_suggest")
PLACES_URL = "https://places.googleapis.com/v1"
FEATURE = "onboarding_suggest"
PIN_URL = "https://api.postalpincode.in/pincode"
DETAIL_FIELDS = "id,displayName,formattedAddress,addressComponents,nationalPhoneNumber,websiteUri,primaryType,types"
ADDRESS_TYPES = ["street_address", "route", "premise", "sublocality", "neighborhood"]  # Google allows at most five
REVIEW_LINK = "https://search.google.com/local/writereview?placeid={place_id}"  # Google's documented "write a review" link for a place


class SuggestError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def enabled() -> bool:
    return bool(settings.places_suggest_enabled and settings.rank_provider == "google_places" and settings.rank_provider_key)


# ---------------------------------------------------------------- category mapping (Google place type -> FlowQR's own list)
_EXACT = {
    "physiotherapist": "Physiotherapy clinic", "dentist": "Dental clinic", "dental_clinic": "Dental clinic",
    "doctor": "Healthcare practice", "hospital": "Healthcare practice", "medical_lab": "Healthcare practice", "medical_clinic": "Healthcare practice",
    "health": "Healthcare practice", "pharmacy": "Healthcare practice", "drugstore": "Healthcare practice", "wellness_center": "Healthcare practice",
    "lodging": "Hotel", "hotel": "Hotel", "guest_house": "Hotel", "resort_hotel": "Hotel", "bed_and_breakfast": "Hotel", "hostel": "Hotel", "motel": "Hotel",
    "beauty_salon": "Salon / Spa", "hair_salon": "Salon / Spa", "hair_care": "Salon / Spa", "barber_shop": "Salon / Spa", "spa": "Salon / Spa", "nail_salon": "Salon / Spa",
    "car_repair": "Automobile service centre", "car_dealer": "Automobile service centre", "car_wash": "Automobile service centre", "auto_parts_store": "Automobile service centre",
    "gym": "Gym / Fitness", "fitness_center": "Gym / Fitness", "yoga_studio": "Gym / Fitness", "sports_club": "Gym / Fitness",
    "school": "Coaching institute", "tutoring_service": "Coaching institute", "educational_institution": "Coaching institute", "training_center": "Coaching institute",
}
_FOOD = {"restaurant", "cafe", "coffee_shop", "bakery", "bar", "meal_takeaway", "meal_delivery", "food", "confectionery", "dessert_shop", "sweet_shop", "ice_cream_shop",
         "kebab_shop", "pizza_restaurant", "fast_food_restaurant", "tea_house", "juice_shop", "sandwich_shop"}


def map_category(primary: str | None, types: list[str] | None) -> str | None:
    """The FlowQR category that best matches a Google place, or None when nothing fits well (the owner then picks)."""
    ordered = [t for t in ([primary] if primary else []) + list(types or []) if t]
    for t in ordered:
        if t in _EXACT:
            return _EXACT[t]
        if t in _FOOD or t.endswith("_restaurant"):
            return "Restaurant"
        if t.endswith("_store") or t in {"shopping_mall", "supermarket", "market", "grocery_store"}:
            return "Retail store"
    return None


# ---------------------------------------------------------------- budget
def _isolated():
    db = SessionLocal()
    set_rls_context(db, bypass=True)
    return db


def _month_start(now: datetime | None = None) -> datetime:
    n = now or utcnow()
    return datetime(n.year, n.month, 1, tzinfo=timezone.utc)


def budget_problem(user_id) -> str | None:
    """Why one more Google call may not be made right now, or None. Counts this feature's ledger rows; the caller records refusals."""
    db = _isolated()
    try:
        day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        mine = db.scalar(select(func.count()).select_from(ApiUsage).where(ApiUsage.feature == FEATURE, ApiUsage.user_id == user_id,
                                                                            ApiUsage.status == "ok", ApiUsage.created_at >= day_start)) or 0
        if settings.places_suggest_user_daily_cap and mine >= settings.places_suggest_user_daily_cap:
            return "You have used today's address suggestions. You can type the details by hand."
        if settings.places_suggest_monthly_cap:
            total = db.scalar(select(func.count()).select_from(ApiUsage).where(ApiUsage.feature == FEATURE, ApiUsage.status == "ok",
                                                                                 ApiUsage.created_at >= _month_start())) or 0
            if total >= settings.places_suggest_monthly_cap:
                return "Suggestions are paused for this month. You can type the details by hand."
        return None
    finally:
        db.close()


def _record(user_id, operation: str, status: str = "ok", reason: str | None = None) -> None:
    api_usage.record_isolated(tenant_id=None, provider=api_usage.PLACES, operation=operation, feature=FEATURE, status=status, user_id=user_id, reason=reason)


# ---------------------------------------------------------------- Google client
class Client:
    """Thin client over Places API (New). The transport is injected only by tests; the key goes in a header, never in a URL or a log."""

    def __init__(self, key: str, transport: httpx.BaseTransport | None = None):
        self._key = key
        self._http = httpx.Client(timeout=8, transport=transport)

    def _call(self, method: str, url: str, fields: str | None = None, json: dict | None = None, params: dict | None = None) -> dict:
        headers = {"X-Goog-Api-Key": self._key, "Content-Type": "application/json"}
        if fields:
            headers["X-Goog-FieldMask"] = fields
        try:
            r = self._http.request(method, url, json=json, params=params, headers=headers)
        except httpx.HTTPError:
            raise SuggestError("Google could not be reached. You can type the details by hand.", 502)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (401, 403):
            log.warning("Places rejected the key for suggestions (%s)", r.status_code)
            raise SuggestError("Suggestions are not available right now. You can type the details by hand.", 503)
        if r.status_code == 429:
            raise SuggestError("Suggestions are busy. Try again in a moment, or type the details by hand.", 429)
        if r.status_code == 404:
            raise SuggestError("Google no longer has that place. Pick another or type it by hand.", 404)
        raise SuggestError("Suggestions are not available right now. You can type the details by hand.", 502)

    def autocomplete(self, text: str, kind: str, session: str) -> list[dict]:
        body: dict = {"input": text, "includedRegionCodes": ["in"], "languageCode": "en", "sessionToken": session}
        if kind == "address":
            body["includedPrimaryTypes"] = ADDRESS_TYPES
        data = self._call("POST", f"{PLACES_URL}/places:autocomplete", json=body)
        out = []
        for s in data.get("suggestions", []):
            p = s.get("placePrediction") or {}
            pid = p.get("placeId")
            if not pid:
                continue
            fmt = p.get("structuredFormat") or {}
            title = (fmt.get("mainText") or {}).get("text") or (p.get("text") or {}).get("text") or ""
            out.append({"place_id": pid, "title": title, "subtitle": (fmt.get("secondaryText") or {}).get("text") or "", "types": (p.get("types") or [])[:4]})
        return out[:6]

    def details(self, place_id: str, session: str) -> dict:
        return self._call("GET", f"{PLACES_URL}/places/{place_id}", fields=DETAIL_FIELDS, params={"sessionToken": session, "languageCode": "en"})


def get_client() -> Client | None:
    return Client(settings.rank_provider_key) if enabled() else None


# ---------------------------------------------------------------- shaping Google's answer for the forms
def _component(components: list[dict], *wanted: str, largest: bool = False) -> str | None:
    """The first component of the first wanted type. Google lists the same type from smallest to largest area, so `largest` takes the last one."""
    for w in wanted:
        hits = [c.get("longText") for c in components if w in (c.get("types") or [])]
        if hits:
            return hits[-1] if largest else hits[0]
    return None


def indian_mobile(raw: str | None) -> str | None:
    """A 10-digit Indian mobile number from Google's phone text, or None (landlines and foreign numbers are left for the owner to type)."""
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return f"{d[:5]} {d[5:]}" if len(d) == 10 and d[0] in "6789" else None


def shape_details(g: dict) -> dict:
    comps = g.get("addressComponents") or []
    street = " ".join(x for x in (_component(comps, "street_number"), _component(comps, "route")) if x)
    parts: list[str] = []
    for p in (street, _component(comps, "premise"), _component(comps, "neighborhood"), _component(comps, "sublocality_level_2"), _component(comps, "sublocality_level_1", "sublocality")):
        if p and p not in parts:
            parts.append(p)
    pid = g.get("id") or ""
    website = g.get("websiteUri") or None
    return {
        "place_id": pid,
        "name": (g.get("displayName") or {}).get("text") or "",
        "formatted_address": g.get("formattedAddress") or "",
        "address_line": ", ".join(parts) or (g.get("formattedAddress") or "").split(",")[0],
        "area": _component(comps, "sublocality_level_1", "sublocality", "neighborhood"),
        "city": _component(comps, "locality", "administrative_area_level_3", "administrative_area_level_2", largest=True),
        "state": _component(comps, "administrative_area_level_1"),
        "postal_code": _component(comps, "postal_code"),
        "phone": indian_mobile(g.get("nationalPhoneNumber")),
        "website": website,
        "category": map_category(g.get("primaryType"), g.get("types")),
        "review_url": REVIEW_LINK.format(place_id=pid) if pid else None,
    }


# ---------------------------------------------------------------- India PIN codes
_pin_cache: dict[str, tuple[float, dict | None]] = {}
PIN_TTL = 24 * 3600


def lookup_pincode(pin: str, transport: httpx.BaseTransport | None = None) -> dict | None:
    """City, state and the post-office areas for a six-digit Indian PIN code, or None when it does not exist. Only the PIN leaves this server."""
    if not re.fullmatch(r"[1-9]\d{5}", pin or ""):
        raise SuggestError("A PIN code has six digits.", 422)
    hit = _pin_cache.get(pin)
    if hit and time.time() - hit[0] < PIN_TTL:
        return hit[1]
    try:
        r = httpx.Client(timeout=5, transport=transport).get(f"{PIN_URL}/{pin}")
        data = r.json()[0] if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError, IndexError):
        raise SuggestError("The PIN directory is not reachable right now. You can type the city and state.", 502)
    offices = (data or {}).get("PostOffice") or []
    result = None
    if data and data.get("Status") == "Success" and offices:
        result = {"postal_code": pin, "city": offices[0].get("District") or offices[0].get("Block"), "state": offices[0].get("State"),
                  "areas": sorted({(o.get("Name") or "").split(" (")[0] for o in offices if o.get("Name")})[:8]}
    _pin_cache[pin] = (time.time(), result)
    return result
