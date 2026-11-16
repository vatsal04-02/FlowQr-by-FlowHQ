"""Growth score: FlowQR's own 0-100 measure of how a business is doing on Google, always shown with its five parts (never a "Google score").

Each part is 0..1, then weighted. A part with no real data is left out and the others are re-weighted; the result is then marked partial. Below MIN_COVERAGE of the
weight, no score is given at all. Every part says the numbers it used, so the owner can see why. Weights and thresholds live here, in one place.
"""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GbpSnapshot, GoogleLocation, RankCheck, RankKeyword, Review
from app.services.agent.snapshots import profile_completeness

WEIGHTS = {"rating": 20, "reviews": 25, "replies": 15, "profile": 15, "rank": 25}
MIN_COVERAGE = 30
RATING_FLOOR, RATING_FULL = 4.0, 4.8      # rating at or below the floor scores 0, at or above "full" scores 1
REPLY_FAST_H, REPLY_SLOW_H = 24, 168      # replies within a day count fully; a week or slower counts half
GOAL_MIN, GOAL_GROWTH = 5, 1.1            # suggested goal when none is set: last month + 10%, at least 5
LABELS = {"rating": "Rating", "reviews": "Reviews", "replies": "Replies", "profile": "Profile", "rank": "Rank"}
LINKS = {"rating": "/gbp/reviews", "reviews": "/growth", "replies": "/gbp/reviews?state=none", "profile": "/seo/profile", "rank": "/seo/rankings"}


def rank_value(rank: int | None) -> float:
    """1-3 is full marks, 4-10 falls from 0.75 to 0.4, 11-20 from 0.3 to 0.05, not in the first 20 is 0."""
    if rank is None:
        return 0.0
    if rank <= 3:
        return 1.0
    if rank <= 10:
        return 0.75 - (rank - 4) * (0.35 / 6)
    if rank <= 20:
        return 0.3 - (rank - 11) * (0.25 / 9)
    return 0.0


def _month_bounds(today: date, tz: ZoneInfo):
    first = today.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    prev_first = (first - timedelta(days=1)).replace(day=1)
    utc = lambda d: datetime.combine(d, time.min, tzinfo=tz).astimezone(timezone.utc)  # noqa: E731
    return first, nxt, prev_first, utc(first), utc(nxt), utc(prev_first)


def compute(db: Session, *, tenant_id: uuid.UUID, tz_name: str, review_goal: int | None, scope, location_id: uuid.UUID | None = None,
            can_access=lambda _lid: True, today: date | None = None) -> dict:
    tz = ZoneInfo(tz_name)
    today = today or datetime.now(tz).date()
    first, nxt, prev_first, lo, hi, plo = _month_bounds(today, tz)

    def rq(*cols):
        q = select(*cols).where(Review.tenant_id == tenant_id, scope(Review.location_id))
        return q.where(Review.location_id == location_id) if location_id else q

    parts: dict[str, dict] = {}

    # rating: all-time average of Google reviews
    total, avg = db.execute(rq(func.count(), func.avg(Review.rating))).one()
    if total:
        v = max(0.0, min(1.0, (float(avg) - RATING_FLOOR) / (RATING_FULL - RATING_FLOOR)))
        parts["rating"] = {"value": v, "detail": f"{float(avg):.1f} from {total} reviews", "number": round(float(avg), 1)}

    # reviews: this calendar month against the goal (the business's own, else last month + 10%)
    month = db.scalar(rq(func.count()).where(Review.review_created_at >= lo, Review.review_created_at < hi)) or 0
    last = db.scalar(rq(func.count()).where(Review.review_created_at >= plo, Review.review_created_at < lo)) or 0
    goal = review_goal or max(GOAL_MIN, math.ceil(last * GOAL_GROWTH))
    days_left = (nxt - today).days - 1
    parts["reviews"] = {"value": min(1.0, month / goal), "detail": f"{month} of {goal} this month", "count": month, "goal": goal, "goal_set": bool(review_goal),
                        "days_left": days_left, "to_go": max(0, goal - month)}

    # replies: share of reviews answered, scaled down for slow replies (from a day to a week: full to half)
    if total:
        answered = db.scalar(rq(func.count()).where(Review.google_reply_text.is_not(None))) or 0
        hrs = db.scalar(rq(func.avg(func.extract("epoch", Review.google_reply_at - Review.review_created_at)))
                        .where(Review.google_reply_at.is_not(None), Review.google_reply_at >= Review.review_created_at))
        hrs = float(hrs) / 3600 if hrs is not None else None
        speed = 1.0 if hrs is None or hrs <= REPLY_FAST_H else max(0.5, 1 - 0.5 * (hrs - REPLY_FAST_H) / (REPLY_SLOW_H - REPLY_FAST_H))
        rate = answered / total
        parts["replies"] = {"value": rate * speed, "detail": f"{round(rate * 100)}% answered" + (f", about {round(hrs)} h to reply" if hrs is not None else ""),
                            "rate": round(rate, 3), "hours": round(hrs, 1) if hrs is not None else None}

    # Google locations the person may see
    gq = select(GoogleLocation).where(GoogleLocation.tenant_id == tenant_id, GoogleLocation.selected.is_(True))
    if location_id:
        gq = gq.where(GoogleLocation.location_id == location_id)
    glocs = [g for g in db.scalars(gq) if can_access(g.location_id)]
    gids = [g.id for g in glocs]

    # profile: the improve checklist, from the profile Google last returned
    if gids:
        infos = [profile_completeness(s.info) for s in db.scalars(select(GbpSnapshot).where(GbpSnapshot.google_location_id.in_(gids))) if s.info]
        if infos:
            pct = sum(i["percent"] for i in infos) / len(infos)
            parts["profile"] = {"value": pct / 100, "detail": f"{round(pct)}% complete", "percent": round(pct)}

    # rank: the latest successful check of every tracked word
    if gids:
        latest = []
        for k in db.scalars(select(RankKeyword).where(RankKeyword.tenant_id == tenant_id, RankKeyword.google_location_id.in_(gids))):
            c = db.scalar(select(RankCheck).where(RankCheck.keyword_id == k.id, RankCheck.status == "ok").order_by(RankCheck.checked_at.desc()).limit(1))
            if c is not None:
                latest.append(c.rank)
        if latest:
            top10 = sum(1 for r in latest if r and r <= 10)
            parts["rank"] = {"value": sum(rank_value(r) for r in latest) / len(latest), "detail": f"top 10 for {top10} of {len(latest)} words", "measured": len(latest), "top10": top10}

    covered = sum(WEIGHTS[k] for k in parts)
    score = round(100 * sum(WEIGHTS[k] * p["value"] for k, p in parts.items()) / covered) if covered >= MIN_COVERAGE else None
    out_parts = []
    for k in WEIGHTS:
        p = parts.get(k)
        out_parts.append({"key": k, "label": LABELS[k], "weight": WEIGHTS[k], "available": p is not None, "value": round(p["value"], 3) if p else None,
                          "detail": p["detail"] if p else None, "href": LINKS[k], **({kk: vv for kk, vv in p.items() if kk not in ("value", "detail")} if p else {})})
    avail = [p for p in out_parts if p["available"]]
    weakest = min(avail, key=lambda p: p["value"]) if avail else None
    return {"score": score, "partial": len(avail) < len(WEIGHTS), "covered_weight": covered, "parts": out_parts,
            "weakest": weakest["key"] if weakest and weakest["value"] < 0.9 else None, "weights": WEIGHTS,
            "note": "FlowQR's own measure of how you are doing on Google, from your rating, reviews against your goal, replies, profile and rank. Parts without data are left out."}
