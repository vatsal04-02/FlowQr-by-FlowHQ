"""Dashboard analytics. Scans, landing visits, Google clicks and submitted reviews are kept strictly separate:
we can count the first three, but a click on 'Continue to Google' is NOT proof a review was posted."""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Date, cast, func, select

from app.core.deps import TenantContext, get_tenant_context
from app.models import (
    AIGenerationLog, GoogleLocation, Location, QRCard, ReplyDraft, ReplyStatus, Review, ScanEvent, ScanEventType, Subscription,
)
from app.services.ai_usage import month_start, usage_this_month

router = APIRouter(prefix="/analytics", tags=["analytics"])
ET = ScanEventType


def _range(ctx: TenantContext, start: date | None, end: date | None):
    tz = ZoneInfo(ctx.tenant.timezone)
    end = end or datetime.now(tz).date()
    start = start or end - timedelta(days=29)
    if start > end:
        raise HTTPException(status_code=422, detail="Start date must be before end date")
    if (end - start).days > 366:
        raise HTTPException(status_code=422, detail="Date range is limited to 366 days")
    lo = datetime.combine(start, time.min, tzinfo=tz).astimezone(timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    return start, end, lo, hi, ctx.tenant.timezone


def _fill(start: date, end: date, rows: dict, keys: list[str]) -> list[dict]:
    out, d = [], start
    while d <= end:
        row = rows.get(d, {})
        out.append({"date": d.isoformat(), **{k: row.get(k, 0) for k in keys}})
        d += timedelta(days=1)
    return out


@router.get("/overview")
def overview(
    ctx: TenantContext = Depends(get_tenant_context),
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    location_id: uuid.UUID | None = None,
):
    start, end, lo, hi, tz = _range(ctx, start, end)
    t = ctx.tenant_id
    db = ctx.db
    if location_id and not db.scalar(select(Location.id).where(Location.id == location_id, Location.tenant_id == t)):
        raise HTTPException(status_code=404, detail="Location not found")

    # ---------- Reviews ----------
    rq = select(Review).where(Review.tenant_id == t)
    if location_id:
        rq = rq.where(Review.location_id == location_id)
    base = rq.subquery()
    total_all, avg_all = db.execute(select(func.count(), func.avg(base.c.rating))).one()
    in_range = (base.c.review_created_at >= lo) & (base.c.review_created_at < hi)
    new_in_range, avg_in_range = db.execute(select(func.count(), func.avg(base.c.rating)).where(in_range)).one()
    replied_in_range = db.scalar(select(func.count()).where(in_range, base.c.google_reply_text.is_not(None)))
    awaiting = db.scalar(select(func.count()).where(base.c.google_reply_text.is_(None)))
    avg_resp = db.scalar(select(func.avg(func.extract("epoch", base.c.google_reply_at - base.c.review_created_at)))
                         .where(base.c.google_reply_at.is_not(None), base.c.google_reply_at >= base.c.review_created_at, in_range))
    day = cast(func.timezone(tz, base.c.review_created_at), Date)
    r_rows = db.execute(select(day, func.count(), func.avg(base.c.rating)).where(in_range).group_by(day)).all()
    review_series = _fill(start, end, {d: {"count": c, "avg_rating": round(float(a), 2) if a else 0} for d, c, a in r_rows}, ["count", "avg_rating"])
    dist = dict(db.execute(select(base.c.rating, func.count()).group_by(base.c.rating)).all())

    # ---------- Card engagement (bots excluded) ----------
    eq = select(ScanEvent).where(ScanEvent.tenant_id == t, ScanEvent.is_bot.is_(False), ScanEvent.created_at >= lo, ScanEvent.created_at < hi)
    if location_id:
        eq = eq.where(ScanEvent.location_id == location_id)
    ev = eq.subquery()
    totals = {k.value: v for k, v in db.execute(select(ev.c.event_type, func.count()).group_by(ev.c.event_type)).all()}
    eday = cast(func.timezone(tz, ev.c.created_at), Date)
    e_rows = db.execute(select(eday, ev.c.event_type, func.count()).group_by(eday, ev.c.event_type)).all()
    series_map: dict[date, dict] = {}
    for d, et, c in e_rows:
        series_map.setdefault(d, {})[et.value] = c
    engagement_series = _fill(start, end, series_map, ["scan", "landing_view", "google_click", "ai_assist"])

    # per card
    card_rows = db.execute(select(ev.c.card_id, ev.c.event_type, func.count()).group_by(ev.c.card_id, ev.c.event_type)).all()
    per_card: dict = {}
    for cid, et, c in card_rows:
        per_card.setdefault(cid, {})[et.value] = c
    cards = {c.id: c for c in db.scalars(select(QRCard).where(QRCard.tenant_id == t))}
    locs = {l.id: l.name for l in db.scalars(select(Location).where(Location.tenant_id == t))}
    card_perf = []
    for cid, c in cards.items():
        if location_id and c.location_id != location_id:
            continue
        s = per_card.get(cid, {})
        card_perf.append({"card_code": c.card_code, "label": c.label, "location": locs.get(c.location_id), "status": c.status.value,
                          "scans": s.get("scan", 0), "landing_views": s.get("landing_view", 0),
                          "google_clicks": s.get("google_click", 0), "ai_assists": s.get("ai_assist", 0)})
    card_perf.sort(key=lambda r: r["scans"], reverse=True)

    # per location
    loc_rows = db.execute(select(ev.c.location_id, ev.c.event_type, func.count()).group_by(ev.c.location_id, ev.c.event_type)).all()
    per_loc: dict = {}
    for lid, et, c in loc_rows:
        per_loc.setdefault(lid, {})[et.value] = c
    rev_by_loc = {lid: (n, a) for lid, n, a in db.execute(select(base.c.location_id, func.count(), func.avg(base.c.rating)).where(in_range).group_by(base.c.location_id))}
    loc_perf = []
    for lid, name in locs.items():
        if location_id and lid != location_id:
            continue
        s = per_loc.get(lid, {})
        n, a = rev_by_loc.get(lid, (0, None))
        loc_perf.append({"location": name, "scans": s.get("scan", 0), "landing_views": s.get("landing_view", 0),
                         "google_clicks": s.get("google_click", 0), "new_reviews": n, "avg_rating": round(float(a), 2) if a else None})

    # ---------- AI + sync ----------
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == t))
    ai_by_kind = dict(db.execute(select(AIGenerationLog.kind, func.count()).where(
        AIGenerationLog.tenant_id == t, AIGenerationLog.created_at >= lo, AIGenerationLog.created_at < hi,
        AIGenerationLog.status == "ok").group_by(AIGenerationLog.kind)).all())
    sync = [{"title": g.title, "location": locs.get(g.location_id), "last_synced_at": g.last_synced_at, "status": g.last_sync_status,
             "error": g.last_sync_error} for g in db.scalars(select(GoogleLocation).where(GoogleLocation.tenant_id == t, GoogleLocation.selected.is_(True)))]
    pending_drafts = db.scalar(select(func.count()).select_from(ReplyDraft).where(ReplyDraft.tenant_id == t, ReplyDraft.status == ReplyStatus.draft))

    scans, views, clicks = totals.get("scan", 0), totals.get("landing_view", 0), totals.get("google_click", 0)
    return {
        "range": {"from": start.isoformat(), "to": end.isoformat(), "timezone": tz},
        "reviews": {
            "total_synced": total_all, "average_rating_all_time": round(float(avg_all), 2) if avg_all else None,
            "new_in_range": new_in_range, "average_rating_in_range": round(float(avg_in_range), 2) if avg_in_range else None,
            "awaiting_reply": awaiting, "drafts_pending_approval": pending_drafts,
            "reply_rate_in_range": round(replied_in_range / new_in_range, 3) if new_in_range else None,
            "avg_response_hours": round(float(avg_resp) / 3600, 1) if avg_resp else None,
            "rating_distribution": {str(i): dist.get(i, 0) for i in range(1, 6)},
            "series": review_series,
        },
        "engagement": {
            "scans": scans, "landing_views": views, "google_clicks": clicks, "ai_assists": totals.get("ai_assist", 0),
            "click_through_rate": round(clicks / views, 3) if views else None,
            "series": engagement_series,
            "definitions": {
                "scans": "Times a QR code was scanned or an NFC card tapped (bots and rapid refreshes excluded).",
                "landing_views": "Times the review page actually loaded in a customer's browser.",
                "google_clicks": "Taps on 'Continue to Google'. This does NOT mean a review was submitted.",
                "submitted_reviews": "Only measurable for connected Google locations, from synced reviews. We cannot attribute a review to a specific scan.",
            },
        },
        "cards": card_perf, "locations": loc_perf,
        "ai": {"used_this_month": usage_this_month(db, t), "monthly_limit": sub.monthly_ai_generations if sub else None,
               "in_range_by_kind": ai_by_kind, "month_started": month_start().isoformat()},
        "sync": sync,
    }
