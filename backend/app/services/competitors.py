"""Pinned competitors: pick a few businesses to follow, and keep what Google Places showed for them on each date.

Everything stored here comes from results FlowQR already received for the business's own rank checks, so pinning and following cost no extra Google calls. A place can only be pinned if
it has actually appeared in this location's stored results (nothing is pinned from a guessed id). A snapshot says "on this date, in this search, Google returned this rating and review
count and this position". Changes are the difference between two real observations on different days, and a competitor that did not appear in a check has no snapshot for it (absence is
not a zero)."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CompetitorSnapshot, GoogleLocation, PinnedCompetitor, RankCheck, RankKeyword
from app.models.base import utcnow
from app.models.competitors import PIN_LIMIT_PER_LOCATION
from app.services.rank import RankError

BACKFILL_DAYS = 400  # how far back stored rank checks are read when a competitor is pinned


def record_from_check(db: Session, gl: GoogleLocation, kw: RankKeyword, check: RankCheck, results: list[dict]) -> int:
    """Called right after a successful rank check, with the full list Google returned (up to 20). One snapshot per pinned competitor that appeared. No Google call."""
    if check.status != "ok" or not results:
        return 0
    pinned = list(db.scalars(select(PinnedCompetitor).where(PinnedCompetitor.google_location_id == gl.id)))
    if not pinned:
        return 0
    by_place = {p.get("place_id"): (i, p) for i, p in enumerate(results, 1) if p.get("place_id")}
    n = 0
    for c in pinned:
        hit = by_place.get(c.place_id)
        if not hit:
            continue
        pos, p = hit
        db.add(CompetitorSnapshot(tenant_id=c.tenant_id, competitor_id=c.id, rank_check_id=check.id, keyword_id=kw.id, observed_at=check.checked_at, rating=p.get("rating"),
                                  reviews=p.get("reviews"), position=pos, your_position=check.rank, source="rank_check"))
        n += 1
    return n


def _observed(db: Session, gl: GoogleLocation, place_id: str, since) -> list[tuple[RankCheck, int, dict]]:
    out = []
    for c in db.scalars(select(RankCheck).where(RankCheck.google_location_id == gl.id, RankCheck.status == "ok", RankCheck.checked_at >= since).order_by(RankCheck.checked_at)):
        others = [p for p in (c.top_results or []) if not p.get("is_you")]
        for i, p in enumerate(others, 1):
            if p.get("place_id") == place_id:
                out.append((c, i, p))
                break
    return out


def pin(db: Session, gl: GoogleLocation, place_id: str, *, user_id: uuid.UUID | None) -> PinnedCompetitor:
    place_id = (place_id or "").strip()
    if not place_id or len(place_id) > 200:
        raise RankError("Choose a business from the list.", 422)
    if place_id == gl.place_id:
        raise RankError("That is your own business.", 422)
    if db.scalar(select(PinnedCompetitor.id).where(PinnedCompetitor.google_location_id == gl.id, PinnedCompetitor.place_id == place_id)):
        raise RankError("You already follow this business.", 409)
    n = db.scalar(select(func.count()).select_from(PinnedCompetitor).where(PinnedCompetitor.google_location_id == gl.id)) or 0
    if n >= PIN_LIMIT_PER_LOCATION:
        raise RankError(f"You can follow up to {PIN_LIMIT_PER_LOCATION} competitors per location. Unpin one first.", 409)
    seen = _observed(db, gl, place_id, utcnow() - timedelta(days=BACKFILL_DAYS))
    if not seen:
        raise RankError("That business has not appeared in your stored search results, so it cannot be followed yet.", 404)
    name = next((p.get("name") for _, _, p in reversed(seen) if p.get("name")), "Unnamed place")
    row = PinnedCompetitor(tenant_id=gl.tenant_id, google_location_id=gl.id, place_id=place_id, name=name[:300], created_by=user_id)
    db.add(row)
    db.flush()
    for c, pos, p in seen:  # the observations FlowQR already holds become this competitor's first snapshots, with their original dates
        db.add(CompetitorSnapshot(tenant_id=gl.tenant_id, competitor_id=row.id, rank_check_id=c.id, keyword_id=c.keyword_id, observed_at=c.checked_at, rating=p.get("rating"), reviews=p.get("reviews"),
                                  position=pos, your_position=c.rank, source="rank_check"))
    db.flush()
    return row


def unpin(db: Session, row: PinnedCompetitor) -> None:
    db.delete(row)  # its snapshots go with it (cascade)
    db.flush()


def out(db: Session, row: PinnedCompetitor, *, days: int = 400) -> dict:
    since = utcnow() - timedelta(days=days)
    snaps = list(db.scalars(select(CompetitorSnapshot).where(CompetitorSnapshot.competitor_id == row.id, CompetitorSnapshot.observed_at >= since).order_by(CompetitorSnapshot.observed_at)))
    checks = db.scalar(select(func.count()).select_from(RankCheck).where(RankCheck.google_location_id == row.google_location_id, RankCheck.status == "ok", RankCheck.checked_at >= since)) or 0
    series = [{"at": s.observed_at.isoformat(), "date": s.observed_at.date().isoformat(), "rating": s.rating, "reviews": s.reviews, "position": s.position} for s in snaps]
    reviews = [s for s in snaps if s.reviews is not None]
    ratings = [s for s in snaps if s.rating is not None]
    change = None
    if len(reviews) >= 2 and reviews[0].observed_at.date() != reviews[-1].observed_at.date():
        change = {"reviews_change": reviews[-1].reviews - reviews[0].reviews, "from": reviews[0].observed_at.isoformat(), "to": reviews[-1].observed_at.isoformat(),
                  "rating_change": round(ratings[-1].rating - ratings[0].rating, 1) if len(ratings) >= 2 else None}
    top10 = sum(1 for s in snaps if s.position and s.position <= 10)
    ahead = sum(1 for s in snaps if s.position and (s.your_position is None or s.position < s.your_position))
    last = snaps[-1] if snaps else None
    return {"id": str(row.id), "google_location_id": str(row.google_location_id), "place_id": row.place_id, "name": row.name, "pinned_at": row.created_at.isoformat(),
            "observations": len(snaps), "first_observed_at": snaps[0].observed_at.isoformat() if snaps else None, "observed_at": last.observed_at.isoformat() if last else None,
            "rating": last.rating if last else None, "reviews": last.reviews if last else None, "change": change, "series": series[-60:],
            "visibility": {"appeared_in": len(snaps), "of_checks": checks, "in_top10": top10, "ahead_of_you": ahead,
                           "note": "Counted over your stored checks. A check where this business did not appear in the first 20 results has no snapshot, so absence is counted as 'did not appear', never as a rank."},
            "source": "rank_check"}
