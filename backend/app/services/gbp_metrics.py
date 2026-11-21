"""Google Business Profile metrics history: store what Google reported, read it back, and say plainly when there is nothing to show.

Rules (the UI repeats them):
* Rows come ONLY from a successful Performance API response (`record`). Nothing is back-filled, estimated or derived from the latest-only GbpSnapshot summary.
* A metric Google did not return for a day has no row: "no row" means "Google did not tell us", never zero. A real 0 from Google is stored as 0.
* `availability` is the explicit unavailable state: it is "ok" only when at least one stored row exists for the locations in view. Until live Google Business Profile access
  has actually returned data, every Google number in the product shows "unavailable", with the reason (not connected, API not enabled, awaiting Google approval, not yet fetched).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import GbpMetricDaily, GoogleConnection, GoogleConnectionStatus, GoogleLocation
from app.models.base import utcnow
from app.models.metrics import SOURCE_PERFORMANCE_API
from app.services import google_retention

SEARCH = ("BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", "BUSINESS_IMPRESSIONS_MOBILE_SEARCH")
MAPS = ("BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_MOBILE_MAPS")
ACTIONS = {"calls": "CALL_CLICKS", "website": "WEBSITE_CLICKS", "directions": "BUSINESS_DIRECTION_REQUESTS", "bookings": "BUSINESS_BOOKINGS", "messages": "MESSAGING_CLICKS"}
LAG_DAYS = 3  # Google reports a few days late: the most recent days are not expected to exist yet

REASONS = {
    "no_location": "Choose a Google location to see Google's numbers.",
    "not_connected": "Connect Google to see how customers find and use your profile.",
    "api_disabled": "Google's Business Profile APIs are not enabled for FlowQR yet, so Google has not shared these numbers.",
    "awaiting_approval": "Google has not approved FlowQR's Business Profile API access yet, so these numbers are not available.",
    "not_fetched": "FlowQR has not received these numbers from Google yet. They are collected once a day.",
}


def record(db: Session, gloc: GoogleLocation, series: dict[str, list[dict]], *, fetched_at: datetime | None = None) -> int:
    """Upsert the daily points of one successful Performance API response. Returns the number of rows written. A day already stored is updated (Google revises recent days)."""
    now = fetched_at or utcnow()
    rows = []
    floor = google_retention.earliest_metric_day()  # None unless Google content retention is on: then days older than the period are not stored
    for metric, points in (series or {}).items():
        for pt in points or []:
            try:
                day, value = date.fromisoformat(str(pt["date"])[:10]), int(pt["value"])
            except (KeyError, TypeError, ValueError):
                continue  # a malformed point is skipped, never guessed
            if value < 0:
                continue
            if floor is not None and day < floor:
                continue  # older than the retention period: storing it would only mean deleting it tomorrow, and fetching it again must not restart its clock
            rows.append({"id": uuid.uuid4(), "tenant_id": gloc.tenant_id, "google_location_id": gloc.id, "metric": str(metric)[:48], "day": day, "value": value,
                         "source": SOURCE_PERFORMANCE_API, "first_fetched_at": now, "fetched_at": now})
    if not rows:
        return 0
    stmt = insert(GbpMetricDaily).values(rows)
    stmt = stmt.on_conflict_do_update(constraint="uq_gbp_metric_daily", set_={"value": stmt.excluded.value, "fetched_at": stmt.excluded.fetched_at, "source": stmt.excluded.source})
    db.execute(stmt)
    return len(rows)


def availability(db: Session, tenant_id: uuid.UUID, glocs: list[GoogleLocation]) -> dict:
    """{state: 'ok' | reason code, reason: str|None, last_fetched_at, locations_with_data}. Never 'ok' without stored rows."""
    if not glocs:
        return {"state": "no_location", "reason": REASONS["no_location"], "last_fetched_at": None, "locations_with_data": 0}
    ids = [g.id for g in glocs]
    last, with_data = db.execute(select(func.max(GbpMetricDaily.fetched_at), func.count(func.distinct(GbpMetricDaily.google_location_id)))
                                 .where(GbpMetricDaily.tenant_id == tenant_id, GbpMetricDaily.google_location_id.in_(ids))).one()
    if with_data:
        return {"state": "ok", "reason": None, "last_fetched_at": last.isoformat() if last else None, "locations_with_data": int(with_data)}
    conns = {c.id: c for c in db.scalars(select(GoogleConnection).where(GoogleConnection.id.in_({g.connection_id for g in glocs})))}
    states = {(conns.get(g.connection_id).api_access if conns.get(g.connection_id) else "unknown") for g in glocs}
    if all(conns.get(g.connection_id) is None or conns[g.connection_id].status != GoogleConnectionStatus.active for g in glocs):
        state = "not_connected"
    elif "api_disabled" in states:
        state = "api_disabled"
    elif "awaiting_approval" in states:
        state = "awaiting_approval"
    else:
        state = "not_fetched"
    return {"state": state, "reason": REASONS[state], "last_fetched_at": None, "locations_with_data": 0}


def history(db: Session, tenant_id: uuid.UUID, glocs: list[GoogleLocation], start: date, end: date) -> dict:
    """Stored daily values for the locations in view, summed per metric per day. `days_missing` lists days in range with no stored value for any location (Google lag, outages)."""
    ids = [g.id for g in glocs]
    if not ids:
        return {"series": {}, "totals": {}, "days_with_data": 0, "range_days": (end - start).days + 1}
    q = (select(GbpMetricDaily.metric, GbpMetricDaily.day, func.sum(GbpMetricDaily.value))
         .where(GbpMetricDaily.tenant_id == tenant_id, GbpMetricDaily.google_location_id.in_(ids), GbpMetricDaily.day >= start, GbpMetricDaily.day <= end)
         .group_by(GbpMetricDaily.metric, GbpMetricDaily.day).order_by(GbpMetricDaily.day))
    series: dict[str, list[dict]] = {}
    days: set[date] = set()
    for metric, day, total in db.execute(q).all():
        series.setdefault(metric, []).append({"date": day.isoformat(), "value": int(total)})
        days.add(day)
    totals = {m: sum(p["value"] for p in pts) for m, pts in series.items()}
    return {"series": series, "totals": totals, "days_with_data": len(days), "range_days": (end - start).days + 1}


def summary(totals: dict[str, int]) -> dict:
    """The named numbers the overview shows, each None when Google returned no row for it (None is 'unavailable', 0 is a real zero)."""
    def pick(metrics) -> int | None:
        got = [totals[m] for m in metrics if m in totals]
        return sum(got) if got else None
    out = {"search_views": pick(SEARCH), "maps_views": pick(MAPS)}
    out.update({k: pick((m,)) for k, m in ACTIONS.items()})
    return out
