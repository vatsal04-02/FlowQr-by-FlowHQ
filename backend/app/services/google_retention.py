"""Retention of content taken from the Google Business Profile APIs (docs/audits/GOOGLE_RETENTION_ARCHITECTURE.md).

WHY: Google's API policy says content provided through the Business Profile APIs may be stored only temporarily ("no more than 30 calendar days"), securely, and not manipulated or aggregated. Whether the
text reaches FlowQR's service in exactly this way is still to be confirmed in writing (docs/audits/GOOGLE_QUESTIONS_TO_SUBMIT.md), so this applies the strictest reading that keeps the product working: free text,
names and reply copy are removed 30 days after FlowQR FIRST STORED them.

THE CLOCK STARTS WHEN FLOWQR FIRST STORED A RECORD AND NEVER MOVES. A later sync cannot extend it, and an expired record is never filled in again (sync.py skips a review whose content was expired), so fetching the
same content again cannot reset an obligation. New content that Google returns later is a new record with its own clock.

OFF BY DEFAULT in code (GOOGLE_CONTENT_RETENTION_ENABLED); the scheduled task (`flowqr.google_content_retention`, daily) does nothing unless it is on. `google-retention-report` counts what a run would do (optionally N days
ahead) without changing anything. A record exactly `days` old is KEPT; only strictly older goes. Every step is independent (one failing leaves the others to run and is reported), repeatable (a second run finds
nothing), tenant-neutral (it works on age alone, never on who owns a row, and never touches a row younger than the cutoff) and counted, never described, in the audit log: the log holds counts and settings, never
review text, names or Google content. A run writes one audit entry every day it runs, so a missing entry is how the operations check notices a scheduler that stopped.

What "redact" keeps for a review: its rating, dates and ids (so counts and the sync's de-duplication work). Whether those too must go is one of the questions for Google; nothing here decides it.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, null, or_, select, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AIOutput, GbpMetricDaily, GbpSnapshot, GoogleLocation, ReplyDraft, ReplyStatus, Review
from app.models.base import utcnow
from app.services.audit import audit

log = logging.getLogger("flowqr.retention.google")

# What is Google content, and what happens to it (the same table as the document). Used by tests so a new store cannot be added silently.
CLASSIFICATION = {
    "reviews.text / reviewer_name / google_reply_text": "google_content: cleared when the record is older than the period (age = first stored, never extended)",
    "reviews.rating / dates / ids": "operational metadata: kept (counts over time, de-duplication); whether it must go is a question for Google",
    "gbp_snapshots.info / posts / media / performance": "google_content: cleared when the last refresh is older than the period (a snapshot is replaced by each refresh, never accumulated)",
    "gbp_metric_daily": "google_content: deleted when first stored longer ago than the period; days older than the period are not stored at all",
    "reply_drafts (unpublished)": "derived from review text: deleted after the period",
    "ai_outputs (kind reply)": "the AI's reply text, derived from review text: text cleared after the period (scores and decisions kept)",
    "agent_tasks.title / evidence (reply_review)": "carries the reviewer's name and a snippet: scrubbed after the period",
    "notifications": "not stored: built from reviews on request, so they follow the reviews",
    "audit_logs": "counts and ids only, never Google content: not subject to expiry here",
}


def enabled() -> bool:
    return bool(settings.google_content_retention_enabled)


def _cut(now: datetime) -> datetime:
    return now - timedelta(days=settings.google_content_retention_days)


def earliest_metric_day(today: date | None = None) -> date | None:
    """While retention is on, a daily metric older than the period is not stored (it would be deleted at once, and fetching it again must not restart its clock). None = no limit (retention off)."""
    if not enabled():
        return None
    return (today or utcnow().date()) - timedelta(days=settings.google_content_retention_days)


def reviews_step(db: Session, now: datetime, dry_run: bool) -> int:
    cond = (Review.first_seen_at < _cut(now)) & Review.google_content_expired_at.is_(None)
    if dry_run:
        return db.scalar(select(func.count()).select_from(Review).where(cond)) or 0
    return db.execute(update(Review).where(cond).values(text=None, reviewer_name=None, google_reply_text=None, google_content_expired_at=now)).rowcount or 0


def snapshots_step(db: Session, now: datetime, dry_run: bool) -> int:
    cond = (GbpSnapshot.fetched_at < _cut(now)) & or_(GbpSnapshot.info.is_not(None), GbpSnapshot.posts.is_not(None), GbpSnapshot.media.is_not(None), GbpSnapshot.performance.is_not(None))
    if dry_run:
        return db.scalar(select(func.count()).select_from(GbpSnapshot).where(cond)) or 0
    return db.execute(update(GbpSnapshot).where(cond).values(info=null(), posts=null(), media=null(), performance=null(), error="Expired under the Google content retention period")).rowcount or 0


def metrics_step(db: Session, now: datetime, dry_run: bool) -> int:
    cond = GbpMetricDaily.first_fetched_at < _cut(now)
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


def ai_outputs_step(db: Session, now: datetime, dry_run: bool) -> int:
    """The AI's original reply text was written from a review. Its score, decision and edit ratio (no Google content) stay."""
    cond = (AIOutput.kind == "reply") & (AIOutput.created_at < _cut(now)) & (AIOutput.original_text != "")
    if dry_run:
        return db.scalar(select(func.count()).select_from(AIOutput).where(cond)) or 0
    return db.execute(update(AIOutput).where(cond).values(original_text="")).rowcount or 0


_TASKS_COUNT = text("SELECT count(*) FROM agent_tasks WHERE kind = 'reply_review' AND created_at < :cut AND (evidence ? 'reviewer' OR evidence ? 'snippet' OR title LIKE '% from %')")
_TASKS_SCRUB = text("UPDATE agent_tasks SET evidence = (evidence - 'reviewer') - 'snippet', title = regexp_replace(title, ' from .*$', '') "
                    "WHERE kind = 'reply_review' AND created_at < :cut AND (evidence ? 'reviewer' OR evidence ? 'snippet' OR title LIKE '% from %')")


def agent_tasks_step(db: Session, now: datetime, dry_run: bool) -> int:
    if dry_run:
        return db.execute(_TASKS_COUNT, {"cut": _cut(now)}).scalar() or 0
    return db.execute(_TASKS_SCRUB, {"cut": _cut(now)}).rowcount or 0


STEPS = (("reviews", reviews_step), ("snapshots", snapshots_step), ("metrics", metrics_step), ("drafts", drafts_step), ("ai_outputs", ai_outputs_step), ("agent_tasks", agent_tasks_step))


def run(db: Session, *, now: datetime | None = None, dry_run: bool = False) -> dict:
    """Needs a bypass-RLS session (the job's). Returns {"enabled", "dry_run", "counts": {step: n}, "errors": [step, ...]}. `now` lets a report look ahead."""
    now = now or utcnow()
    if not enabled() and not dry_run:
        return {"enabled": False, "dry_run": False, "counts": {}, "errors": []}
    counts: dict[str, int] = {}
    errors: list[str] = []
    for name, step in STEPS:
        try:
            counts[name] = step(db, now, dry_run)
            if not dry_run:
                db.commit()
        except Exception as exc:  # noqa: BLE001 - one failing step must not stop the others; it is reported and retried
            db.rollback()
            errors.append(name)
            log.error("google content retention step %s failed: %s", name, type(exc).__name__)
    if not dry_run:
        audit(db, action="retention.google_content_run", entity_type="retention",
              meta={"counts": counts, "errors": errors, "days": settings.google_content_retention_days, "action": settings.google_content_retention_action})
        db.commit()
    log.info("google content retention (dry_run=%s): %s errors=%s", dry_run, counts, errors)
    return {"enabled": enabled(), "dry_run": dry_run, "counts": counts, "errors": errors}


def last_run_at(db: Session) -> datetime | None:
    """When the job last wrote its audit entry (the operations check uses this to see that the scheduler is alive)."""
    from app.models import AuditLog

    return db.scalar(select(func.max(AuditLog.created_at)).where(AuditLog.action == "retention.google_content_run"))


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
