"""Dashboard analytics. Scans, landing visits, Google clicks and submitted reviews are kept strictly separate:
we can count the first three, but a click on 'Continue to Google' is NOT proof a review was posted."""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Date, cast, func, select

from app.core.deps import TenantContext, get_tenant_context
from app.models import (
    AIGenerationLog, GoogleLocation, Location, QRCard, ReplyDraft, ReplyStatus, Review, ReviewCampaign, ScanEvent, ScanEventType, Subscription,
)
from app.services import entitlements as ent
from app.services import insights as insights_svc
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
    if location_id and (not ctx.can_access_location(location_id) or not db.scalar(select(Location.id).where(Location.id == location_id, Location.tenant_id == t))):
        raise HTTPException(status_code=404, detail="Location not found")

    # ---------- Reviews ----------
    rq = select(Review).where(Review.tenant_id == t, ctx.scope(Review.location_id))  # restricted staff: their locations only
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
    # low_count = 1-3 star reviews that day, so the dashboard can split the trend by rating without a second query
    r_rows = db.execute(select(day, func.count(), func.avg(base.c.rating), func.count().filter(base.c.rating <= 3)).where(in_range).group_by(day)).all()
    review_series = _fill(start, end, {d: {"count": c, "avg_rating": round(float(a), 2) if a else 0, "low_count": lo_n} for d, c, a, lo_n in r_rows},
                          ["count", "avg_rating", "low_count"])
    dist = dict(db.execute(select(base.c.rating, func.count()).group_by(base.c.rating)).all())

    # ---------- Card engagement (bots excluded) ----------
    eq = select(ScanEvent).where(ScanEvent.tenant_id == t, ScanEvent.is_bot.is_(False), ScanEvent.created_at >= lo, ScanEvent.created_at < hi, ctx.scope(ScanEvent.location_id))
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

    # The same card through its two doors. QR and NFC resolve to one card identity; only the way in is recorded.
    by_channel: dict = {k: {"scans": 0, "unique_visitors": 0, "landing_views": 0, "google_clicks": 0} for k in ("qr", "nfc", "untracked")}
    for ch, et, n, u in db.execute(select(ev.c.channel, ev.c.event_type, func.count(), func.count(func.distinct(ev.c.visitor_hash))).group_by(ev.c.channel, ev.c.event_type)):
        slot = by_channel[ch or "untracked"]
        if et == ET.scan:
            slot["scans"], slot["unique_visitors"] = n, u
        elif et == ET.landing_view:
            slot["landing_views"] = n
        elif et == ET.google_click:
            slot["google_clicks"] = n

    # per card
    card_rows = db.execute(select(ev.c.card_id, ev.c.event_type, func.count()).group_by(ev.c.card_id, ev.c.event_type)).all()
    per_card: dict = {}
    for cid, et, c in card_rows:
        per_card.setdefault(cid, {})[et.value] = c
    card_ch: dict = {}
    for cid, ch, n in db.execute(select(ev.c.card_id, ev.c.channel, func.count()).where(ev.c.event_type == ET.scan).group_by(ev.c.card_id, ev.c.channel)):
        card_ch.setdefault(cid, {})[ch or "untracked"] = n
    card_uniq = dict(db.execute(select(ev.c.card_id, func.count(func.distinct(ev.c.visitor_hash))).where(ev.c.event_type == ET.scan).group_by(ev.c.card_id)).all())
    card_last = dict(db.execute(select(ev.c.card_id, func.max(ev.c.created_at)).group_by(ev.c.card_id)).all())
    camp_names = {c.id: c.name for c in db.scalars(select(ReviewCampaign).where(ReviewCampaign.tenant_id == t))}
    cards = {c.id: c for c in db.scalars(select(QRCard).where(QRCard.tenant_id == t, ctx.scope(QRCard.location_id)))}
    locs = {l.id: l.name for l in db.scalars(select(Location).where(Location.tenant_id == t, ctx.scope(Location.id)))}
    card_perf = []
    for cid, c in cards.items():
        if location_id and c.location_id != location_id:
            continue
        s = per_card.get(cid, {})
        ch = card_ch.get(cid, {})
        card_perf.append({"card_code": c.card_code, "label": c.label, "location": locs.get(c.location_id), "status": c.status.value,
                          "campaign": camp_names.get(c.campaign_id),
                          "scans": s.get("scan", 0), "qr_scans": ch.get("qr", 0), "nfc_taps": ch.get("nfc", 0),
                          "unique_visitors": card_uniq.get(cid, 0), "last_activity": card_last.get(cid),
                          "landing_views": s.get("landing_view", 0),
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
        AIGenerationLog.status == "ok", ctx.scope(AIGenerationLog.location_id)).group_by(AIGenerationLog.kind)).all())
    sync = [{"title": g.title, "location": locs.get(g.location_id), "last_synced_at": g.last_synced_at, "status": g.last_sync_status,
             "error": g.last_sync_error} for g in db.scalars(select(GoogleLocation).where(GoogleLocation.tenant_id == t, GoogleLocation.selected.is_(True), ctx.scope(GoogleLocation.location_id)))]
    pending_drafts = db.scalar(select(func.count()).select_from(ReplyDraft).join(Review, Review.id == ReplyDraft.review_id).where(
        ReplyDraft.tenant_id == t, ReplyDraft.status == ReplyStatus.draft, ctx.scope(Review.location_id)))

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
            "by_channel": by_channel,
            "series": engagement_series,
            "definitions": {
                "scans": "Times a QR code was scanned or an NFC card tapped (bots and rapid refreshes excluded).",
                "channels": "QR scans and NFC taps open the same card; the way in is recorded separately. Visits before channel tracking began are shown as 'untracked'.",
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


@router.get("/insights")
def insights(
    ctx: TenantContext = Depends(get_tenant_context),
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    location_id: uuid.UUID | None = None,
):
    """Sentiment mix and recurring topics across synced reviews (plan feature: insights)."""
    ent.require_feature(ctx.db, ctx.tenant_id, "insights")
    start, end, lo, hi, tz = _range(ctx, start, end)
    if location_id and (not ctx.can_access_location(location_id) or not ctx.db.scalar(select(Location.id).where(Location.id == location_id, Location.tenant_id == ctx.tenant_id))):
        raise HTTPException(status_code=404, detail="Location not found")

    def fetch(a, b):
        q = select(Review.rating, Review.text).where(Review.tenant_id == ctx.tenant_id, Review.review_created_at >= a, Review.review_created_at < b,
                                                     ctx.scope(Review.location_id))
        if location_id:
            q = q.where(Review.location_id == location_id)
        return [(r, t) for r, t in ctx.db.execute(q).all()]

    span = hi - lo
    result = insights_svc.analyse(fetch(lo, hi), fetch(lo - span, lo))
    result["range"] = {"from": start.isoformat(), "to": end.isoformat()}
    return result


@router.get("/google-metrics")
def google_metrics(start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"), location_id: uuid.UUID | None = None,
                   ctx: TenantContext = Depends(get_tenant_context)):
    """Google Business Profile metrics FlowQR has stored from the Performance API (see services/gbp_metrics.py), for this period and the same-length period before it.

    `availability.state` is "ok" only when stored rows exist; otherwise it is the reason Google's numbers are unavailable and every figure is null. A metric Google did not return is
    null, a real zero is 0. Days Google has not reported yet (it runs a few days late) are left out of BOTH periods so the comparison is like for like. Nothing is estimated."""
    from app.api.v1.seo import _glocs
    from app.services import gbp_metrics as gm

    glocs = _glocs(ctx, location_id)
    start, end, *_ = _range(ctx, start, end)
    end = min(end, datetime.now(ZoneInfo(ctx.tenant.timezone)).date() - timedelta(days=gm.LAG_DAYS))
    avail = gm.availability(ctx.db, ctx.tenant_id, glocs)
    out: dict = {"availability": avail, "source": "google", "range": {"from": start.isoformat(), "to": end.isoformat()}, "current": None, "previous": None, "series": {}, "by_location": [],
                 "days_with_data": 0,
                 "note": "Reported by Google Business Profile, a few days late, and collected once a day. Not the same as FlowQR card scans. Google does not report ranking positions here."}
    if avail["state"] != "ok" or start > end:
        return out
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    cur, prev = gm.history(ctx.db, ctx.tenant_id, glocs, start, end), gm.history(ctx.db, ctx.tenant_id, glocs, prev_start, prev_end)
    out.update(current=gm.summary(cur["totals"]), previous=gm.summary(prev["totals"]) if prev["days_with_data"] else None, series=cur["series"], days_with_data=cur["days_with_data"],
               range_days=span, previous_range={"from": prev_start.isoformat(), "to": prev_end.isoformat(), "days_with_data": prev["days_with_data"]})
    for g in glocs:
        h = gm.history(ctx.db, ctx.tenant_id, [g], start, end)
        out["by_location"].append({"id": str(g.id), "title": g.title, "days_with_data": h["days_with_data"], "totals": gm.summary(h["totals"]) if h["days_with_data"] else None})
    return out
