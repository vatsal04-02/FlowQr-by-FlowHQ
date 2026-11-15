"""Geo-grid ranking: where a business appears for a search term from several points around it, measured through Google's official Places API (New), never scraped.

What a number means (and the UI says the same): each grid point is one Places text search biased to a circle around THAT coordinate; the rank is the 1-based position
of the business among the first 20 results. It is a repeatable measurement, not what every person sees in Google Maps (which varies by device, exact spot and
personalisation). "Not found" is a real result (the business was not in the first 20 there); an API error is an error and is never read as a rank.

Cost control (every point is one billed Places search):
  * the plan decides how many grids, points per grid and points per month a business may use (billing_plans.limits, copied to the subscription). Until the owner has
    approved ALL THREE numbers the plan has no map allowance and maps stay off (fail closed);
  * a scan is refused up front if the whole scan does not fit the monthly allowance (no half-bought maps), and also stops if Google reports its quota is gone;
  * an optional platform-wide monthly cap (settings.rank_platform_monthly_cap) bounds the total across every business;
  * automatic re-scans run only when the whole scan fits, at most one scan per grid and keyword per rank_grid_auto_days.
The Places key never leaves the server."""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import GoogleLocation, RankCheck, RankGrid, RankGridPoint, RankGridScan, RankKeyword, Subscription
from app.models.base import utcnow
from app.services import rank as rank_svc
from app.services import usage
from app.services.agent.learning import compare as compare_rank
from app.services.rank import RankError

SIZES = (3, 5, 7)
MAX_CUSTOM_RADIUS_M = 50_000  # a custom point further than this from the location is a typo, not a neighbourhood
M_PER_DEG_LAT = 111_320.0
MIN_COMPARABLE_OK = 0.8  # a scan with fewer measured points than this is not compared with another
SIGNIFICANT_SOLV = 15.0  # percentage points of top-3 coverage
SIGNIFICANT_ARP = 2.0  # average positions
SIGNIFICANT_MOVED = 0.30  # share of compared points that moved meaningfully (3+ positions, or found/not found)
NOTE = ("Each circle is one Google Places search from that spot: the position of your business among the first 20 results. It is measured, not estimated, "
        "but Google Maps itself can order results differently by device and person.")
BUCKETS = (("top3", "In the top 3"), ("top10", "Positions 4 to 10"), ("top20", "Positions 11 to 20"), ("none", "Not in the first 20"), ("error", "Could not be measured"))


# ---------------------------------------------------------------------------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------------------------------------------------------------------------
def _offset(lat: float, lng: float, north_m: float, east_m: float) -> tuple[float, float]:
    dlat = north_m / M_PER_DEG_LAT
    dlng = east_m / (M_PER_DEG_LAT * max(0.01, math.cos(math.radians(lat))))
    return round(lat + dlat, 6), round(lng + dlng, 6)


def square_points(lat: float, lng: float, size: int, spacing_m: int) -> list[dict]:
    """size x size points, `spacing_m` apart, centred on (lat, lng), numbered row by row from the north-west."""
    half = (size - 1) / 2
    out = []
    for r in range(size):
        for c in range(size):
            la, lo = _offset(lat, lng, (half - r) * spacing_m, (c - half) * spacing_m)
            out.append({"i": r * size + c, "lat": la, "lng": lo, "label": f"{'N' if r < half else 'S' if r > half else ''}{'W' if c < half else 'E' if c > half else ''}" or "Centre"})
    return out


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def clean_custom(points: list[dict], centre: tuple[float, float]) -> list[dict]:
    """Validate owner-chosen coordinates: real, distinct, and near the business."""
    out, seen = [], set()
    for raw in points or []:
        try:
            la, lo = round(float(raw["lat"]), 6), round(float(raw["lng"]), 6)
        except (KeyError, TypeError, ValueError):
            raise RankError("Each point needs a latitude and a longitude.", 422)
        if not (-90 <= la <= 90 and -180 <= lo <= 180):
            raise RankError("A point is not a real map position.", 422)
        if (la, lo) in seen:
            continue
        if distance_m(centre, (la, lo)) > MAX_CUSTOM_RADIUS_M:
            raise RankError(f"A point is more than {MAX_CUSTOM_RADIUS_M // 1000} km from this business. Check the coordinates.", 422)
        seen.add((la, lo))
        out.append({"i": len(out), "lat": la, "lng": lo, "label": re.sub(r"\s+", " ", str(raw.get("label") or "")).strip()[:40] or f"Point {len(out) + 1}"})
    if not out:
        raise RankError("Add at least one point.", 422)
    return out


def hash_points(points: list[dict]) -> str:
    return hashlib.sha256(json.dumps([[p["lat"], p["lng"]] for p in points], separators=(",", ":")).encode()).hexdigest()


# ---------------------------------------------------------------------------------------------------------------------------------------------
# plan limits and cost
# ---------------------------------------------------------------------------------------------------------------------------------------------
def availability(db: Session, tenant_id: uuid.UUID) -> tuple[dict | None, str | None]:
    """(allowances, None) when maps can be used; (None, reason) otherwise. reason = "not_in_plan" (the plan does not include maps) or "not_configured" (it does, but the
    owner has not approved the allowances yet: maps stay OFF rather than running on a guess)."""
    from app.services import entitlements as ent
    from app.services import plans

    e = ent.for_tenant(db, tenant_id)
    if not (e.active and "geo_ranking" in e.features):
        return None, "not_in_plan"
    lim = plans.geo_limits(e.limits)
    return (lim, None) if lim else (None, "not_configured")


def tenant_limits(db: Session, tenant_id: uuid.UUID) -> dict | None:
    return availability(db, tenant_id)[0]


def _points_since(db: Session, tenant_id: uuid.UUID | None, since: datetime) -> int:
    q = select(func.count()).select_from(RankGridPoint).where(RankGridPoint.checked_at >= since)
    if tenant_id is not None:
        q = q.where(RankGridPoint.tenant_id == tenant_id)
    return db.scalar(q) or 0


def platform_used_this_month(db: Session) -> int:
    """Every Places search of the month, grid or single-point, across all businesses (the platform cap's meter)."""
    since = rank_svc.month_start()
    return _points_since(db, None, since) + (db.scalar(select(func.count()).select_from(RankCheck).where(RankCheck.checked_at >= since)) or 0)


def allowance(db: Session, tenant_id: uuid.UUID) -> dict:
    lim, why = availability(db, tenant_id)
    used = _points_since(db, tenant_id, rank_svc.month_start())
    cap = lim["monthly_points"] if lim else 0
    platform_cap = settings.rank_platform_monthly_cap
    platform_left = max(0, platform_cap - platform_used_this_month(db)) if platform_cap > 0 else None
    remaining = max(0, cap - used)
    if platform_left is not None:
        remaining = min(remaining, platform_left)
    price = settings.rank_cost_per_call_usd
    return {"enabled": bool(lim), "reason": why, "limits": lim, "used": used, "cap": cap, "remaining": remaining, "resets_on": rank_svc.next_month_start().date().isoformat(),
            "platform_capped": platform_left is not None and platform_left <= 0, "cost_per_call_usd": price or None,
            "estimated_spend_usd": round(used * price, 2) if price > 0 else None}


# ---------------------------------------------------------------------------------------------------------------------------------------------
# grids
# ---------------------------------------------------------------------------------------------------------------------------------------------
def location_centre(db: Session, gl: GoogleLocation, client=None) -> tuple[float, float]:
    if gl.lat is None or gl.lng is None:
        client = client or rank_svc.get_client()
        if client is None:
            raise RankError("Local rank tracking isn't set up on this server (RANK_PROVIDER / RANK_PROVIDER_KEY).", 503)
        rank_svc._ensure_center(db, client, gl)
    return gl.lat, gl.lng


def create_grid(db: Session, gl: GoogleLocation, *, name: str, mode: str = "square", size: int | None = None, spacing_m: int | None = None, centre: tuple[float, float] | None = None,
                points: list[dict] | None = None, user_id: uuid.UUID | None = None, client=None) -> RankGrid:
    lim, why = availability(db, gl.tenant_id)
    if not lim:
        raise RankError("Geo-grid ranking is not included in your current plan." if why == "not_in_plan" else "Maps are part of your plan, but their allowances have not been set yet, so they are switched off for now.", 402)
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not 2 <= len(name) <= 60:
        raise RankError("Give the grid a name of 2 to 60 characters, for example “Main map” or “North side”.", 422)
    n = db.scalar(select(func.count()).select_from(RankGrid).where(RankGrid.google_location_id == gl.id)) or 0
    if n >= lim["max_grids"]:
        raise RankError(f"Your plan allows {lim['max_grids']} grids per location. Remove one first.", 409)
    if db.scalar(select(RankGrid.id).where(RankGrid.google_location_id == gl.id, func.lower(RankGrid.name) == name.lower())):
        raise RankError("You already have a grid with that name.", 409)
    base = centre or location_centre(db, gl, client)
    if mode == "square":
        if size not in SIZES:
            raise RankError("A grid is 3 x 3, 5 x 5 or 7 x 7 points.", 422)
        if not spacing_m or not settings.rank_grid_min_spacing_m <= spacing_m <= settings.rank_grid_max_spacing_m:
            raise RankError(f"Space the points {settings.rank_grid_min_spacing_m} to {settings.rank_grid_max_spacing_m} metres apart.", 422)
        pts = square_points(base[0], base[1], size, spacing_m)
    elif mode == "custom":
        pts = clean_custom(points or [], base)
    else:
        raise RankError("Choose a square grid or your own points.", 422)
    if len(pts) > lim["max_points"]:
        raise RankError(f"Your plan allows up to {lim['max_points']} points per grid; this has {len(pts)}.", 409)
    g = RankGrid(tenant_id=gl.tenant_id, google_location_id=gl.id, name=name, mode=mode, center_lat=centre[0] if centre else None, center_lng=centre[1] if centre else None,
                 size=size if mode == "square" else None, spacing_m=spacing_m if mode == "square" else None, points=pts, points_hash=hash_points(pts), created_by=user_id)
    db.add(g)
    db.flush()
    return g


def grid_out(g: RankGrid) -> dict:
    return {"id": str(g.id), "name": g.name, "mode": g.mode, "size": g.size, "spacing_m": g.spacing_m, "points": g.points, "point_count": len(g.points or []), "active": g.active,
            "custom_centre": [g.center_lat, g.center_lng] if g.center_lat is not None else None, "created_at": g.created_at}


# ---------------------------------------------------------------------------------------------------------------------------------------------
# scanning
# ---------------------------------------------------------------------------------------------------------------------------------------------
def _radius(spacing_m: int | None) -> int:
    """Each point searches the area around itself; wide enough to see what a person standing there would be offered, narrow enough not to blur neighbouring points."""
    return max(1000, min(5000, int(spacing_m or settings.rank_radius_m)))


def preflight(db: Session, gl: GoogleLocation, grid: RankGrid) -> dict:
    """Can this scan run, and what will it cost? Raises RankError (no Places call has been made) if not."""
    a = allowance(db, gl.tenant_id)
    if not a["enabled"]:
        raise RankError("Geo-grid ranking is not included in your current plan." if a["reason"] == "not_in_plan" else "Maps are part of your plan, but their allowances have not been set yet, so they are switched off for now.", 402)
    need = len(grid.points or [])
    if a["platform_capped"]:
        usage.refused(gl.tenant_id, "rank_grid", "platform monthly cap", units=need, location_id=gl.id)
        raise RankError("FlowQR's Google Places allowance for this month is used up, so no more scans can run until it resets.", 429)
    if (why := usage.places_budget_problem(db, gl.tenant_id, need, feature="rank_grid", location_id=gl.id)):
        raise RankError(why, 429)
    if need > a["remaining"]:
        usage.refused(gl.tenant_id, "rank_grid", "plan monthly allowance", units=need, location_id=gl.id)
        raise RankError(f"This scan needs {need} Google searches and {a['remaining']} are left this month (resets {a['resets_on']}). Nothing was spent.", 429)
    return {"points": need, "estimated_usd": round(need * settings.rank_cost_per_call_usd, 2) if settings.rank_cost_per_call_usd > 0 else None, "remaining_after": a["remaining"] - need}


def _aggregate(scan: RankGridScan, pts: list[RankGridPoint]) -> None:
    ok = [p for p in pts if p.status == "ok"]
    found = [p for p in ok if p.rank]
    scan.points_total, scan.points_ok, scan.points_found = len(pts), len(ok), len(found)
    scan.arp = round(sum((p.rank or 21) for p in ok) / len(ok), 2) if ok else None
    scan.atrp = round(sum(p.rank for p in found) / len(found), 2) if found else None
    scan.solv = round(100 * sum(1 for p in ok if p.rank and p.rank <= 3) / len(ok), 1) if ok else None
    scan.coverage = round(100 * len(found) / len(ok), 1) if ok else None


def scan(db: Session, gl: GoogleLocation, grid: RankGrid, kw: RankKeyword, *, source: str = "manual", client=None, now: datetime | None = None) -> RankGridScan:
    """Run one keyword over one grid: one billed Places search per point, each saved as it completes. Raises RankError only when nothing was attempted."""
    client = client or rank_svc.get_client()
    if client is None:
        raise RankError("Local rank tracking isn't set up on this server (RANK_PROVIDER / RANK_PROVIDER_KEY).", 503)
    if grid.google_location_id != gl.id or kw.google_location_id != gl.id or grid.tenant_id != gl.tenant_id or kw.tenant_id != gl.tenant_id:
        raise RankError("That grid and search term do not belong to this location.", 404)
    if not gl.place_id:
        raise RankError("This location has no Google place ID yet. Sync it from Google first.", 422)
    preflight(db, gl, grid)
    now = now or utcnow()
    sc = RankGridScan(tenant_id=gl.tenant_id, google_location_id=gl.id, grid_id=grid.id, keyword_id=kw.id, points_hash=grid.points_hash, source=source, status="running", started_at=now)
    db.add(sc)
    db.flush()
    db.commit()  # visible as "running" while it works; each point below is committed as it completes, so the cost is on record even if the process dies
    radius, stopped = _radius(grid.spacing_m), None
    rows: list[RankGridPoint] = []
    for p in grid.points:
        row = RankGridPoint(tenant_id=gl.tenant_id, scan_id=sc.id, point_index=p["i"], lat=p["lat"], lng=p["lng"], status="error", checked_at=utcnow())
        sc.calls += 1
        try:
            results = client.search(kw.keyword, p["lat"], p["lng"], radius)
            usage.record(db, tenant_id=gl.tenant_id, provider=usage.PLACES, operation="searchText", feature="rank_grid", location_id=gl.id, idempotency_key=f"grid:{sc.id}:{p['i']}",
                         meta={"scan": str(sc.id), "keyword": kw.keyword[:40]})
            mine = next((i for i, r in enumerate(results, 1) if r["place_id"] == gl.place_id), None)
            row.status, row.rank, row.results_seen = "ok", mine, len(results)
        except RankError as exc:
            usage.record(db, tenant_id=gl.tenant_id, provider=usage.PLACES, operation="searchText", feature="rank_grid", status="error", location_id=gl.id,
                         idempotency_key=f"grid:{sc.id}:{p['i']}", reason=str(exc)[:150], meta={"scan": str(sc.id)})
            row.error = str(exc)[:300]
            if exc.status in (429, 503):  # quota or key trouble: the remaining points would fail the same way and cost the same
                stopped = str(exc)
                db.add(row)
                rows.append(row)
                break
        db.add(row)
        rows.append(row)
        db.flush()
        db.commit()
    _aggregate(sc, rows)
    sc.finished_at = utcnow()
    sc.status = "failed" if not sc.points_ok else ("done" if sc.points_ok == len(grid.points) else "partial")
    sc.error = stopped or (f"{len(rows) - sc.points_ok} of {len(grid.points)} points could not be measured." if sc.status == "partial" else None)
    sc.change = change_for(db, sc)
    db.flush()
    return sc


# ---------------------------------------------------------------------------------------------------------------------------------------------
# change detection
# ---------------------------------------------------------------------------------------------------------------------------------------------
def _points(db: Session, scan_id: uuid.UUID) -> dict[int, RankGridPoint]:
    return {p.point_index: p for p in db.scalars(select(RankGridPoint).where(RankGridPoint.scan_id == scan_id))}


def previous_comparable(db: Session, sc: RankGridScan) -> RankGridScan | None:
    q = (select(RankGridScan).where(RankGridScan.grid_id == sc.grid_id, RankGridScan.keyword_id == sc.keyword_id, RankGridScan.id != sc.id, RankGridScan.points_hash == sc.points_hash,
                                    RankGridScan.status.in_(("done", "partial")), RankGridScan.started_at < sc.started_at)
         .order_by(RankGridScan.started_at.desc()).limit(1))
    return db.scalar(q)


def compare(prev: RankGridScan, cur: RankGridScan, prev_pts: dict[int, RankGridPoint], cur_pts: dict[int, RankGridPoint]) -> dict:
    """What moved between two scans of the SAME points. Observed, never a claim about why. A point that failed in either scan is `unknown`, not a change."""
    verdicts = {"improved": 0, "declined": 0, "unchanged": 0, "unknown": 0}
    for i, c in cur_pts.items():
        p = prev_pts.get(i)
        v = "unknown" if p is None or p.status != "ok" or c.status != "ok" else compare_rank(p.rank, c.rank, c.status)
        verdicts[v] += 1
    d = lambda a, b: round(a - b, 2) if a is not None and b is not None else None  # noqa: E731
    d_solv, d_arp, d_cov = d(cur.solv, prev.solv), d(cur.arp, prev.arp), d(cur.coverage, prev.coverage)
    known = verdicts["improved"] + verdicts["declined"] + verdicts["unchanged"]
    moved = (verdicts["improved"] + verdicts["declined"]) / known if known else 0
    significant = bool(known) and (abs(d_solv or 0) >= SIGNIFICANT_SOLV or abs(d_arp or 0) >= SIGNIFICANT_ARP or moved >= SIGNIFICANT_MOVED)
    net = verdicts["improved"] - verdicts["declined"]
    direction = "unchanged" if not significant else "improved" if net > 0 else "declined" if net < 0 else ("improved" if (d_solv or 0) > 0 else "declined" if (d_solv or 0) < 0 else "mixed")
    return {"comparable": True, "previous_scan_id": str(prev.id), "previous_at": prev.started_at.isoformat(), "delta_solv": d_solv, "delta_arp": d_arp, "delta_coverage": d_cov,
            "points": verdicts, "significant": significant, "direction": direction,
            "summary": (f"Observed since {prev.started_at.date().isoformat()}: {verdicts['improved']} points moved up, {verdicts['declined']} moved down, {verdicts['unchanged']} are about the same"
                        + (f", {verdicts['unknown']} could not be compared" if verdicts["unknown"] else "") + ". This is what was measured, not proof of why it changed.")}


def change_for(db: Session, sc: RankGridScan) -> dict:
    if sc.status not in ("done", "partial") or sc.points_ok < MIN_COMPARABLE_OK * max(1, sc.points_total):
        return {"comparable": False, "reason": "Too few points could be measured in this scan to compare it with another."}
    prev = previous_comparable(db, sc)
    if prev is None:
        return {"comparable": False, "reason": "This is the first scan of these points, so there is nothing to compare it with yet."}
    if prev.points_ok < MIN_COMPARABLE_OK * max(1, prev.points_total):
        return {"comparable": False, "reason": "The previous scan measured too few points to compare."}
    return compare(prev, sc, _points(db, prev.id), _points(db, sc.id))


# ---------------------------------------------------------------------------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------------------------------------------------------------------------
def bucket(status: str, rank: int | None) -> str:
    if status != "ok":
        return "error"
    if rank is None:
        return "none"
    return "top3" if rank <= 3 else "top10" if rank <= 10 else "top20"


def scan_out(sc: RankGridScan) -> dict:
    return {"id": str(sc.id), "grid_id": str(sc.grid_id), "keyword_id": str(sc.keyword_id), "status": sc.status, "source": sc.source, "started_at": sc.started_at, "finished_at": sc.finished_at,
            "points_total": sc.points_total, "points_ok": sc.points_ok, "points_found": sc.points_found, "arp": sc.arp, "atrp": sc.atrp, "solv": sc.solv, "coverage": sc.coverage,
            "calls": sc.calls, "change": sc.change, "error": sc.error}


def latest_scan(db: Session, grid_id: uuid.UUID, keyword_id: uuid.UUID, scan_id: uuid.UUID | None = None) -> RankGridScan | None:
    q = select(RankGridScan).where(RankGridScan.grid_id == grid_id, RankGridScan.keyword_id == keyword_id)
    q = q.where(RankGridScan.id == scan_id) if scan_id else q.where(RankGridScan.status.in_(("done", "partial", "failed"))).order_by(RankGridScan.started_at.desc()).limit(1)
    return db.scalar(q)


def heatmap(db: Session, grid: RankGrid, kw: RankKeyword, scan_id: uuid.UUID | None = None) -> dict:
    """Everything the screen needs to draw the map: one cell per point with its measured rank and colour bucket, the bounds, the legend and the change since last time."""
    sc = latest_scan(db, grid.id, kw.id, scan_id)
    base = {"grid": grid_out(grid), "keyword": {"id": str(kw.id), "keyword": kw.keyword}, "note": NOTE, "legend": [{"key": k, "label": l} for k, l in BUCKETS]}
    lats = [p["lat"] for p in grid.points]
    lngs = [p["lng"] for p in grid.points]
    base["bounds"] = {"south": min(lats), "north": max(lats), "west": min(lngs), "east": max(lngs)} if grid.points else None
    if sc is None:
        return {**base, "scan": None, "cells": [{"i": p["i"], "lat": p["lat"], "lng": p["lng"], "label": p.get("label"), "rank": None, "status": "unmeasured", "bucket": "unmeasured"} for p in grid.points]}
    got = _points(db, sc.id)
    cells = []
    for p in grid.points:
        r = got.get(p["i"]) if sc.points_hash == grid.points_hash else None
        cells.append({"i": p["i"], "lat": p["lat"], "lng": p["lng"], "label": p.get("label"), "rank": r.rank if r else None, "status": r.status if r else "unmeasured",
                      "error": r.error if r and r.status == "error" else None, "bucket": bucket(r.status, r.rank) if r else "unmeasured"})
    return {**base, "scan": scan_out(sc), "cells": cells, "stale_grid": sc.points_hash != grid.points_hash}


def history(db: Session, grid_id: uuid.UUID, keyword_id: uuid.UUID, limit: int = 30) -> list[dict]:
    rows = db.scalars(select(RankGridScan).where(RankGridScan.grid_id == grid_id, RankGridScan.keyword_id == keyword_id).order_by(RankGridScan.started_at.desc()).limit(limit)).all()
    return [scan_out(s) for s in rows]


def geo_summary(db: Session, google_location_id: uuid.UUID) -> dict | None:
    """The latest finished scan per grid and keyword of one location, for the optimizer and the follow-up comparison. None when nothing has been scanned."""
    out = []
    for g in db.scalars(select(RankGrid).where(RankGrid.google_location_id == google_location_id, RankGrid.active.is_(True))):
        for kw in db.scalars(select(RankKeyword).where(RankKeyword.google_location_id == google_location_id)):
            sc = db.scalar(select(RankGridScan).where(RankGridScan.grid_id == g.id, RankGridScan.keyword_id == kw.id, RankGridScan.status.in_(("done", "partial")))
                           .order_by(RankGridScan.started_at.desc()).limit(1))
            if sc is not None:
                out.append({"grid": g.name, "keyword": kw.keyword, "scan_id": str(sc.id), "at": sc.started_at.isoformat(), "solv": sc.solv, "arp": sc.arp, "coverage": sc.coverage,
                            "points_ok": sc.points_ok, "points_total": sc.points_total})
    return {"scans": out} if out else None


def due_scans(db: Session, limit: int = 20, now: datetime | None = None) -> list[tuple[RankGrid, RankKeyword, GoogleLocation]]:
    """Active grids x tracked keywords not scanned within rank_grid_auto_days, oldest first (system session; the caller applies each business's allowance)."""
    now = now or utcnow()
    cutoff = now - timedelta(days=settings.rank_grid_auto_days)
    last = select(RankGridScan.grid_id, RankGridScan.keyword_id, func.max(RankGridScan.started_at).label("last")).group_by(RankGridScan.grid_id, RankGridScan.keyword_id).subquery()
    q = (select(RankGrid, RankKeyword, GoogleLocation).join(GoogleLocation, GoogleLocation.id == RankGrid.google_location_id)
         .join(RankKeyword, RankKeyword.google_location_id == RankGrid.google_location_id)
         .outerjoin(last, (last.c.grid_id == RankGrid.id) & (last.c.keyword_id == RankKeyword.id))
         .where(RankGrid.active.is_(True), GoogleLocation.selected.is_(True), (last.c.last.is_(None)) | (last.c.last < cutoff))
         .order_by(last.c.last.asc().nullsfirst()).limit(limit))
    return [(g, k, gl) for g, k, gl in db.execute(q).all()]
