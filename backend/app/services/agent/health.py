"""Business Health Score (0-100) with a visible formula.

score = round(100 x sum(weight x value) / sum(weight))   over the components that have REAL data right now.

A component with no data (Google not connected, API refused, nothing synced) is listed as "no data" and left out of both sums, so the
score never improves or worsens because of something we cannot see. If the available components carry less than 30 of the 100
weight, no score is shown at all. Each component says exactly which numbers it used and how to improve it. Thresholds such as "4 posts
a month is full marks" are our own heuristics, stated on screen; they are not Google's rules and not a prediction of growth.
"""
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GbpSnapshot, GoogleConnection, GoogleConnectionStatus, GoogleLocation, HealthSnapshot, Review, ScheduledPost, Tenant
from app.models.base import utcnow
from app.services.agent.snapshots import profile_completeness

MIN_COVERAGE = 30
WEIGHTS = {"profile": 25, "reply_coverage": 25, "review_activity": 15, "posting": 15, "photos": 10, "engagement": 10}
FORMULA = ("Score = 100 × Σ(weight × value) ÷ Σ(weight), using only the measures that have real data. "
           "Measures: profile completeness 25, review reply coverage 25, review activity 15, posting consistency 15, photo freshness 10, engagement trend 10.")


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _component(key: str, label: str, value: float | None, detail: str, improve: str, no_data: str) -> dict:
    return {"key": key, "label": label, "weight": WEIGHTS[key], "available": value is not None,
            "value": None if value is None else round(max(0.0, min(1.0, value)), 3),
            "points": None if value is None else round(WEIGHTS[key] * max(0.0, min(1.0, value)), 1),
            "detail": detail if value is not None else no_data, "improve": improve}


def compute(db: Session, tenant: Tenant, *, location_ids: frozenset[uuid.UUID] | None = None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    glocs = list(db.scalars(select(GoogleLocation).join(GoogleConnection, GoogleConnection.id == GoogleLocation.connection_id).where(
        GoogleLocation.tenant_id == tenant.id, GoogleLocation.selected.is_(True), GoogleConnection.status == GoogleConnectionStatus.active)))
    if location_ids is not None:
        glocs = [g for g in glocs if g.location_id in location_ids]
    snaps = {s.google_location_id: s for s in db.scalars(select(GbpSnapshot).where(GbpSnapshot.google_location_id.in_([g.id for g in glocs])))} if glocs else {}
    comps: list[dict] = []

    # 1 profile completeness: average over locations whose profile Google has returned
    infos = [profile_completeness(s.info) for s in snaps.values() if s.info]
    if infos:
        pct = sum(i["percent"] for i in infos) / len(infos)
        miss = sorted({m["label"] for i in infos for m in i["missing"]})
        comps.append(_component("profile", "Profile completeness", pct / 100, f"{pct:.0f}% complete" + (f"; missing: {', '.join(miss)}" if miss else ""),
                                "Add the missing fields in Profile Manager.", ""))
    else:
        comps.append(_component("profile", "Profile completeness", None, "", "Add the missing fields in Profile Manager.", "No profile data from Google yet (not connected, or Google has not answered)."))

    # 2 + 3 reviews, from synced reviews of the (scoped) locations
    rq = select(Review).where(Review.tenant_id == tenant.id)
    if location_ids is not None:
        rq = rq.where(Review.location_id.in_(list(location_ids)))
    synced = [g for g in glocs if g.last_synced_at]
    recent = list(db.scalars(rq.where(Review.review_created_at >= now - timedelta(days=90))))
    if recent:
        replied = sum(1 for r in recent if r.google_reply_text is not None)
        comps.append(_component("reply_coverage", "Review reply coverage", replied / len(recent), f"{replied} of {len(recent)} reviews from the last 90 days have a reply",
                                "Reply to unanswered reviews in Reviews or the Daily Plan.", ""))
    else:
        comps.append(_component("reply_coverage", "Review reply coverage", None, "", "Reply to unanswered reviews.", "No reviews from the last 90 days have been synced."))
    if synced:
        n30 = sum(1 for r in recent if r.review_created_at >= now - timedelta(days=30))
        comps.append(_component("review_activity", "Review activity", min(1.0, n30 / 4), f"{n30} new review{'s' if n30 != 1 else ''} in the last 30 days (4 or more counts as full marks)",
                                "Share your review QR code with more customers.", ""))
    else:
        comps.append(_component("review_activity", "Review activity", None, "", "Share your review QR code.", "Reviews have not been synced from Google yet."))

    # 4 posting: posts Google lists + posts FlowQR published (de-duplicated by Google's post name)
    posted_known = any(s.posts is not None for s in snaps.values())
    ours = list(db.scalars(select(ScheduledPost).where(ScheduledPost.tenant_id == tenant.id, ScheduledPost.status == "published", ScheduledPost.published_at >= now - timedelta(days=30))))
    names: set[str] = set()
    n_posts = 0
    for s in snaps.values():
        for p in s.posts or []:
            c = _parse(p.get("created_at"))
            if c and c >= now - timedelta(days=30):
                n_posts += 1
                names.add(p.get("name") or "")
    n_posts += sum(1 for p in ours if (p.google_post_name or "") not in names)
    if posted_known or ours:
        comps.append(_component("posting", "Posting consistency", min(1.0, n_posts / 4), f"{n_posts} post{'s' if n_posts != 1 else ''} in the last 30 days (4 or more counts as full marks)",
                                "Approve a post in the Daily Plan.", ""))
    else:
        comps.append(_component("posting", "Posting consistency", None, "", "Approve a post in the Daily Plan.", "Google has not told us about your posts yet."))

    # 5 photo freshness: newest photo age
    media_known = [s for s in snaps.values() if s.media is not None]
    if media_known:
        newest = max((c for s in media_known for m in s.media or [] if (c := _parse(m.get("created_at")))), default=None)
        age = (now - newest).days if newest else None
        val = 0.0 if age is None else 1.0 if age <= 30 else 1 - 0.5 * (age - 30) / 60 if age <= 90 else 0.5 * (1 - (age - 90) / 90) if age <= 180 else 0.0
        comps.append(_component("photos", "Photo freshness", val, "no photos on the profile" if age is None else f"newest photo is {age} days old (≤30 days is full marks, 180+ days is zero)",
                                "Add a recent photo in Photos & Media.", ""))
    else:
        comps.append(_component("photos", "Photo freshness", None, "", "Add a recent photo.", "Google has not told us about your photos yet."))

    # 6 engagement: actions (calls, website, directions, bookings, messages) this 28 days vs the 28 before
    perfs = [s.performance for s in snaps.values() if s.performance]
    cur, prev = sum(p["current"] for p in perfs), sum(p["previous"] for p in perfs)
    if perfs and prev > 0:
        comps.append(_component("engagement", "Engagement trend", min(1.0, cur / prev), f"{cur} customer actions in the last 28 days vs {prev} in the 28 before (flat or up is full marks)",
                                "Keep your profile, photos and posts fresh.", ""))
    else:
        comps.append(_component("engagement", "Engagement trend", None, "", "Keep your profile, photos and posts fresh.",
                                "No earlier Google performance data to compare with yet." if perfs else "Google performance data is not available yet."))

    avail = [c for c in comps if c["available"]]
    covered = sum(c["weight"] for c in avail)
    score = round(100 * sum(c["weight"] * c["value"] for c in avail) / covered) if covered >= MIN_COVERAGE else None
    return {"score": score, "covered_weight": covered, "components": comps, "formula": FORMULA, "computed_at": now.isoformat(),
            "message": None if score is not None else f"Not enough real data yet ({covered} of 100 weight available; at least {MIN_COVERAGE} needed). Connect Google and let it sync."}


def record_and_explain(db: Session, tenant: Tenant, result: dict, *, today: date | None = None) -> dict:
    """Store today's score (once a day, keyed by date) and add what changed since the previous stored day."""
    today = today or utcnow().date()
    prev = db.scalar(select(HealthSnapshot).where(HealthSnapshot.tenant_id == tenant.id, HealthSnapshot.day < today).order_by(HealthSnapshot.day.desc()).limit(1))
    changes: list[str] = []
    if prev and result["score"] is not None and prev.score is not None:
        delta = result["score"] - prev.score
        changes.append(f"Score {'up' if delta > 0 else 'down' if delta < 0 else 'unchanged'}{'' if delta == 0 else f' {abs(delta)} point' + ('s' if abs(delta) != 1 else '')} since {prev.day.isoformat()}.")
        old = {c["key"]: c for c in prev.breakdown.get("components", [])}
        for c in result["components"]:
            o = old.get(c["key"])
            if o and o.get("points") is not None and c["points"] is not None and abs(c["points"] - o["points"]) >= 1:
                changes.append(f"{c['label']}: {o['points']:.0f} → {c['points']:.0f} of {c['weight']} points. {c['detail']}.")
    elif prev is None:
        changes.append("This is the first recorded score; changes will be explained from tomorrow.")
    row = db.scalar(select(HealthSnapshot).where(HealthSnapshot.tenant_id == tenant.id, HealthSnapshot.day == today))
    if row is None:
        row = HealthSnapshot(tenant_id=tenant.id, day=today, score=result["score"], breakdown=result)
        db.add(row)
    else:
        row.score, row.breakdown = result["score"], result
    db.flush()
    history = [{"day": h.day.isoformat(), "score": h.score} for h in db.scalars(
        select(HealthSnapshot).where(HealthSnapshot.tenant_id == tenant.id).order_by(HealthSnapshot.day.desc()).limit(30))]
    return {**result, "changes": changes, "history": list(reversed(history))}
