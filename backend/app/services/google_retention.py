"""Retention of content that came from the Google Business Profile APIs (docs/audits/GOOGLE_RETENTION_ARCHITECTURE.md).

WHY: Google's API policy says content provided through the Business Profile APIs may be stored only temporarily ("no more than 30 calendar days"), securely, and not manipulated or aggregated. Whether and how that
applies to FlowQR's service (reviews the owner asked FlowQR to show and answer) is NOT settled by any written Google answer (docs/audits/GOOGLE_AGENCY_POLICY_STATUS.md, R-1). This module is the MECHANISM, so that
the answer can be applied the day it arrives. Nothing here decides compliance, and a person must switch it on.

OFF BY DEFAULT: the scheduled task (`flowqr.google_content_retention`, daily) does nothing unless GOOGLE_CONTENT_RETENTION_ENABLED=true, so deploying this code deletes nothing. `google-retention-report` (CLI)
counts what a run would do without changing anything. A row exactly `days` old is KEPT; only rows strictly older than the cutoff go. Every step is independent (one failing leaves the others to run, and is
reported), repeatable (a second run finds nothing), and counted, never described, in the audit log: the log holds counts and settings, never review text, names or Google content.

What "age" means: the last time the content was RE-FETCHED from Google (`reviews.google_fetched_at`, `gbp_snapshots.fetched_at`, `gbp_metric_daily.fetched_at`), not when the customer wrote it. While a location
is connected and syncing, review sync re-fetches everything within half the retention period (see sync.py), so content that still exists at Google stays; content that Google removed, that stopped syncing, or
that belongs to a disconnected location ages out.

Actions for reviews (GOOGLE_CONTENT_RETENTION_ACTION): `redact` (default) clears the review text, the reviewer's name and Google's copy of the reply and marks the row expired, keeping only the rating, dates and
ids so counts over time still work; `delete` removes the row (its reply drafts go with it).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, null, or_, select, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import GbpMetricDaily, GbpSnapshot, GoogleLocation, ReplyDraft, ReplyStatus, Review
from app.models.base import utcnow
from app.services.audit import audit

log = logging.getLogger("flowqr.retention.google")

# What is Google content, and what happens to it (the same table as the document). Used by tests so a new store cannot be added silently.
CLASSIFICATION = {
    "reviews.text / reviewer_name / google_reply_text": "google_content: redacted or deleted after the retention period",
    "reviews.rating / dates / ids": "operational metadata: kept on redact (counts over time), removed on delete",
    "gbp_snapshots.info / posts / media / performance": "google_content: cleared after the retention period",
    "gbp_metric_daily": "google_content: deleted after the retention period",
    "reply_drafts (unpublished)": "derived from review text: deleted after the retention period",
    "agent_tasks.title / evidence (reply_review)": "carries the reviewer's name and a snippet: scrubbed after the retention period",
    "notifications": "not stored: built from reviews on request, so they follow the reviews",
    "audit_logs": "counts and ids only, never Google content: not subject to expiry here",
}


def _cut(now: datetime) -> datetime:
    return now - timedelta(days=settings.google_content_retention_days)


def _review_age():
    return func.coalesce(Review.google_fetched_at, Review.first_seen_at)


def reviews_step(db: Session, now: datetime, dry_run: bool) -> int:
    cut = _cut(now)
    if settings.google_content_retention_action == "delete":
        cond = _review_age() < cut
        if dry_run:
            return db.scalar(select(func.count()).select_from(Review).where(cond)) or 0
        return db.execute(delete(Review).where(cond)).rowcount or 0
    cond = (_review_age() < cut) & Review.google_content_expired_at.is_(None)
    if dry_run:
        return db.scalar(select(func.count()).select_from(Review).where(cond)) or 0
    return db.execute(update(Review).where(cond).values(text=None, reviewer_name=None, google_reply_text=None, google_content_expired_at=now)).rowcount or 0


def snapshots_step(db: Session, now: datetime, dry_run: bool) -> int:
    cond = (GbpSnapshot.fetched_at < _cut(now)) & or_(GbpSnapshot.info.is_not(None), GbpSnapshot.posts.is_not(None), GbpSnapshot.media.is_not(None), GbpSnapshot.performance.is_not(None))
    if dry_run:
        return db.scalar(select(func.count()).select_from(GbpSnapshot).where(cond)) or 0
    return db.execute(update(GbpSnapshot).where(cond).values(info=null(), posts=null(), media=null(), performance=null(), error="Expired under the Google content retention period")).rowcount or 0


def metrics_step(db: Session, now: datetime, dry_run: bool) -> int:
    cond = GbpMetricDaily.fetched_at < _cut(now)
    if dry_run:
        return db.scalar(select(func.count()).select_from(GbpMetricDaily).where(cond)) or 0
    return db.execute(delete(GbpMetricDaily).where(cond)).rowcount or 0


def drafts_step(db: Session, now: datetime, dry_run: bool) -> int:
    """Unpublished drafts are derived from review text. A published reply is the business's own words, already public on Google, and is kept."""
    cond = ReplyDraft.created_at < _cut(now)
    cond = cond & ReplyDraft.status.in_((ReplyStatus.draft, ReplyStatus.approved, ReplyStatus.failed, ReplyStatus.rejected))
    if dry_run:
        return db.scalar(select(func.count()).select_from(ReplyDraft).where(cond)) or 0
    return db.execute(delete(ReplyDraft).where(cond)).rowcount or 0


_TASKS_COUNT = text("SELECT count(*) FROM agent_tasks WHERE kind = 'reply_review' AND created_at < :cut AND (evidence ? 'reviewer' OR evidence ? 'snippet' OR title LIKE '% from %')")
_TASKS_SCRUB = text("UPDATE agent_tasks SET evidence = (evidence - 'reviewer') - 'snippet', title = regexp_replace(title, ' from .*$', '') "
                    "WHERE kind = 'reply_review' AND created_at < :cut AND (evidence ? 'reviewer' OR evidence ? 'snippet' OR title LIKE '% from %')")


def agent_tasks_step(db: Session, now: datetime, dry_run: bool) -> int:
    if dry_run:
        return db.execute(_TASKS_COUNT, {"cut": _cut(now)}).scalar() or 0
    return db.execute(_TASKS_SCRUB, {"cut": _cut(now)}).rowcount or 0


STEPS = (("reviews", reviews_step), ("snapshots", snapshots_step), ("metrics", metrics_step), ("drafts", drafts_step), ("agent_tasks", agent_tasks_step))


def run(db: Session, *, now: datetime | None = None, dry_run: bool = False) -> dict:
    """Needs a bypass-RLS session (the job's). Returns {"enabled", "dry_run", "counts": {step: n}, "errors": [step, ...]}."""
    now = now or utcnow()
    if not settings.google_content_retention_enabled and not dry_run:
        return {"enabled": False, "dry_run": False, "counts": {}, "errors": []}
    counts: dict[str, int] = {}
    errors: list[str] = []
    for name, step in STEPS:
        try:
            counts[name] = step(db, now, dry_run)
            if not dry_run:
                db.commit()
        except Exception as exc:  # noqa: BLE001 - one failing step must not stop the others; it is reported and tried again tomorrow
            db.rollback()
            errors.append(name)
            log.error("google content retention step %s failed: %s", name, type(exc).__name__)
    if not dry_run and (any(counts.values()) or errors):
        audit(db, action="retention.google_content_run", entity_type="retention",
              meta={"counts": counts, "errors": errors, "days": settings.google_content_retention_days, "action": settings.google_content_retention_action})
        db.commit()
    log.info("google content retention (dry_run=%s): %s errors=%s", dry_run, counts, errors)
    return {"enabled": bool(settings.google_content_retention_enabled), "dry_run": dry_run, "counts": counts, "errors": errors}


def purge_connection(db: Session, connection_id: uuid.UUID, *, tenant_id: uuid.UUID | None = None) -> dict:
    """Remove EVERYTHING taken from Google for one connection's locations, now (used when a connection is disconnected and GOOGLE_CONTENT_DELETE_ON_DISCONNECT is on).
    Keeps the connection and location rows (they are ids the product needs), keeps published reply text the business wrote, and writes a counts-only audit entry. The caller commits."""
    ids = list(db.scalars(select(GoogleLocation.id).where(GoogleLocation.connection_id == connection_id)))
    if not ids:
        return {"reviews": 0, "snapshots": 0, "metrics": 0}
    out = {
        "reviews": db.execute(delete(Review).where(Review.google_location_id.in_(ids))).rowcount or 0,
        "snapshots": db.execute(delete(GbpSnapshot).where(GbpSnapshot.google_location_id.in_(ids))).rowcount or 0,
        "metrics": db.execute(delete(GbpMetricDaily).where(GbpMetricDaily.google_location_id.in_(ids))).rowcount or 0,
    }
    audit(db, action="retention.google_content_purged", tenant_id=tenant_id, entity_type="google_connection", entity_id=connection_id, meta=out)
    return out
