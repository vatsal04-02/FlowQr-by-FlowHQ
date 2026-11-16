"""Local rank tracking through Google's official Places API (New): where a business appears for a search term near its location.

What a number means (and the UI says the same): the 1-based position of the business among the first 20 results Google Places returns for
the search text, biased to a circle around the location. It is a measured, repeatable signal. It is NOT the exact order a person sees in
Google Maps, which varies by device, exact spot and personalisation. If the business is not among the 20 results the rank is "not found",
never a made-up number.

Cost control: every check is one billed Places call. Each tenant has a monthly cap (settings.rank_monthly_check_cap); the key never leaves
the server and is sent as a header only. FlowQr never scrapes Google."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import GoogleLocation, RankCheck, RankKeyword
from app.models.base import utcnow
from app.services import usage as api_usage

PLACES_URL = "https://places.googleapis.com/v1"
SEARCH_FIELDS = "places.id,places.displayName,places.rating,places.userRatingCount"
PAGE_SIZE = 20


def max_keywords() -> int:
    """Search terms one location may track. A platform setting (RANK_MAX_KEYWORDS_PER_LOCATION), not a plan feature: the per-plan number is an owner decision that has not been made."""
    return max(1, settings.rank_max_keywords_per_location)


TOP_KEPT = 10
NOTE = ("Position among the first 20 results Google Places returns for this search around your location. It is measured, not estimated, "
        "but Google Maps itself can order results differently by device, exact spot and person.")


class RankError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def clean_keyword(raw: str) -> str:
    k = re.sub(r"\s+", " ", (raw or "").strip())
    if not 2 <= len(k) <= 80 or any(ord(c) < 32 for c in k):
        raise RankError("Use 2 to 80 characters, for example “dentist near me” or “root canal”.", 422)
    return k


class PlacesClient:
    """Thin client over Places API (New). The transport is injected only by tests; the key is sent in a header, never in a URL or a log."""

    def __init__(self, key: str, transport: httpx.BaseTransport | None = None):
        self._key = key
        self._http = httpx.Client(timeout=15, transport=transport)

    def _request(self, method: str, url: str, fields: str, json: dict | None = None) -> dict:
        try:
            r = self._http.request(method, url, json=json, headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": fields, "Content-Type": "application/json"})
        except httpx.HTTPError:
            raise RankError("Google Places could not be reached. Try again in a few minutes.", 502)
        if r.status_code == 200:
            return r.json()
        status = ""
        try:
            status = (r.json().get("error") or {}).get("status", "")
        except ValueError:
            pass
        if r.status_code in (401, 403) or status in ("PERMISSION_DENIED", "REQUEST_DENIED", "UNAUTHENTICATED"):
            raise RankError("Google rejected the Places key. Check that Places API (New) is enabled, billing is linked and the key's restrictions allow this server.", 503)
        if r.status_code == 429 or status == "RESOURCE_EXHAUSTED":
            raise RankError("Google's Places quota is used up for now. It resets on its own; try again later.", 429)
        if r.status_code == 404:
            raise RankError("Google doesn't know this place ID any more. Re-sync the location from Google.", 422)
        if r.status_code >= 500:
            raise RankError("Google Places is having trouble. Try again shortly.", 502)
        raise RankError(f"Google Places refused the request ({r.status_code} {status or 'error'}).", 502)

    def place_location(self, place_id: str) -> tuple[float, float]:
        data = self._request("GET", f"{PLACES_URL}/places/{place_id}", "location")
        loc = data.get("location") or {}
        if "latitude" not in loc or "longitude" not in loc:
            raise RankError("Google has no map position for this place yet.", 422)
        return float(loc["latitude"]), float(loc["longitude"])

    def search(self, query: str, lat: float, lng: float, radius_m: int) -> list[dict]:
        body = {"textQuery": query, "pageSize": PAGE_SIZE, "languageCode": "en",
                "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": float(radius_m)}}}
        data = self._request("POST", f"{PLACES_URL}/places:searchText", SEARCH_FIELDS, body)
        return [{"place_id": p.get("id"), "name": (p.get("displayName") or {}).get("text") or "", "rating": p.get("rating"), "reviews": p.get("userRatingCount")}
                for p in data.get("places", []) if p.get("id")]


def enabled() -> bool:
    return settings.rank_provider == "google_places" and bool(settings.rank_provider_key)


def get_client() -> PlacesClient | None:
    return PlacesClient(settings.rank_provider_key) if enabled() else None


def month_start(now: datetime | None = None) -> datetime:
    n = now or utcnow()
    return datetime(n.year, n.month, 1, tzinfo=timezone.utc)


def next_month_start(now: datetime | None = None) -> datetime:
    s = month_start(now)
    return datetime(s.year + (s.month == 12), 1 if s.month == 12 else s.month + 1, 1, tzinfo=timezone.utc)


def used_this_month(db: Session, tenant_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(RankCheck).where(RankCheck.tenant_id == tenant_id, RankCheck.checked_at >= month_start())) or 0


def usage(db: Session, tenant_id: uuid.UUID) -> dict:
    return {"used": used_this_month(db, tenant_id), "cap": settings.rank_monthly_check_cap, "resets_on": next_month_start().date().isoformat()}


def _ensure_center(db: Session, client: PlacesClient, gl: GoogleLocation) -> tuple[float, float]:
    if gl.lat is None or gl.lng is None:
        if not gl.place_id:
            raise RankError("This location has no Google place ID yet. Sync it from Google first.", 422)
        try:
            gl.lat, gl.lng = client.place_location(gl.place_id)
        except RankError:
            api_usage.record(db, tenant_id=gl.tenant_id, provider=api_usage.PLACES, operation="getPlace", feature="rank_check", status="error", location_id=gl.id)
            raise
        api_usage.record(db, tenant_id=gl.tenant_id, provider=api_usage.PLACES, operation="getPlace", feature="rank_check", location_id=gl.id)
        db.flush()
    return gl.lat, gl.lng


def check_keyword(db: Session, gl: GoogleLocation, kw: RankKeyword, *, source: str = "manual", client: PlacesClient | None = None) -> RankCheck:
    """One measurement: one billed Places search (plus a one-time position lookup). Writes exactly one RankCheck, ok or error, so a failed
    check is visible in the history and never looks like a rank. Raises RankError only when nothing was attempted (cap, not configured)."""
    client = client or get_client()
    if client is None:
        raise RankError("Local rank tracking isn't set up on this server (RANK_PROVIDER / RANK_PROVIDER_KEY).", 503)
    if used_this_month(db, gl.tenant_id) >= settings.rank_monthly_check_cap:
        api_usage.refused(gl.tenant_id, "rank_check", "monthly rank-check cap", location_id=gl.id)
        raise RankError(f"This month's limit of {settings.rank_monthly_check_cap} rank checks is used up. It resets on {next_month_start().date().isoformat()}.", 429)
    if (why := api_usage.places_budget_problem(db, gl.tenant_id, 1, feature="rank_check", location_id=gl.id)):
        raise RankError(why, 429)
    row = RankCheck(tenant_id=gl.tenant_id, keyword_id=kw.id, google_location_id=gl.id, status="error", source=source, top_results=[])
    results: list[dict] = []
    try:
        lat, lng = _ensure_center(db, client, gl)
        row.center_lat, row.center_lng = lat, lng
        try:
            results = client.search(kw.keyword, lat, lng, settings.rank_radius_m)
        except RankError:
            api_usage.record(db, tenant_id=gl.tenant_id, provider=api_usage.PLACES, operation="searchText", feature="rank_check", status="error", location_id=gl.id, meta={"source": source})
            raise
        api_usage.record(db, tenant_id=gl.tenant_id, provider=api_usage.PLACES, operation="searchText", feature="rank_check", location_id=gl.id, meta={"source": source})
        mine = next((i for i, p in enumerate(results, 1) if p["place_id"] == gl.place_id), None)
        row.status, row.rank, row.results_seen = "ok", mine, len(results)
        row.top_results = [{**p, "is_you": p["place_id"] == gl.place_id} for p in results[:TOP_KEPT]]
        if mine and mine > TOP_KEPT:  # always show where you are, even below the top list
            row.top_results.append({**results[mine - 1], "is_you": True, "position": mine})
    except RankError as exc:
        row.error = str(exc)
    db.add(row)
    db.flush()
    if row.status == "ok":
        from app.services import competitors as competitors_svc  # snapshots for followed competitors, from the results just received (no extra Google call)
        competitors_svc.record_from_check(db, gl, kw, row, results)
    return row


def latest_two(db: Session, keyword_id: uuid.UUID) -> list[RankCheck]:
    return list(db.scalars(select(RankCheck).where(RankCheck.keyword_id == keyword_id).order_by(RankCheck.checked_at.desc()).limit(2)))


def check_out(c: RankCheck | None) -> dict | None:
    if c is None:
        return None
    return {"id": str(c.id), "status": c.status, "rank": c.rank, "results_seen": c.results_seen, "error": c.error, "checked_at": c.checked_at, "source": c.source,
            "top_results": [{"name": p.get("name"), "rating": p.get("rating"), "reviews": p.get("reviews"), "is_you": bool(p.get("is_you")),
                             "position": p.get("position")} for p in (c.top_results or [])]}


def keyword_out(db: Session, kw: RankKeyword) -> dict:
    latest = next(iter(latest_two(db, kw.id)), None)
    ok = list(db.scalars(select(RankCheck).where(RankCheck.keyword_id == kw.id, RankCheck.status == "ok").order_by(RankCheck.checked_at.desc()).limit(2)))
    change = None
    if len(ok) == 2 and ok[0].rank and ok[1].rank:
        change = ok[1].rank - ok[0].rank  # positive = moved up
    return {"id": str(kw.id), "keyword": kw.keyword, "latest": check_out(latest), "previous_rank": ok[1].rank if len(ok) == 2 else None, "change": change}


def due_keywords(db: Session, limit: int) -> list[tuple[RankKeyword, GoogleLocation]]:
    """Keywords not measured within settings.rank_auto_check_days, oldest first (system session; the caller applies each tenant's cap and plan)."""
    from datetime import timedelta
    cutoff = utcnow() - timedelta(days=settings.rank_auto_check_days)
    last = select(RankCheck.keyword_id, func.max(RankCheck.checked_at).label("last")).group_by(RankCheck.keyword_id).subquery()
    q = (select(RankKeyword, GoogleLocation).join(GoogleLocation, GoogleLocation.id == RankKeyword.google_location_id)
         .outerjoin(last, last.c.keyword_id == RankKeyword.id)
         .where(GoogleLocation.selected.is_(True), (last.c.last.is_(None)) | (last.c.last < cutoff))
         .order_by(last.c.last.asc().nullsfirst()).limit(limit))
    return [(k, g) for k, g in db.execute(q).all()]
