"""Retention of four kinds of personal data that nothing used to expire (docs/PRIVACY_COMPLIANCE_AUDIT.md, D).

PROVISIONAL. The periods are the owner's operating settings of 2026-11-18 and are PENDING LEGAL REVIEW: they are not a statement that FlowQR complies with any law, and they do not decide
what must be kept for accounting, security or legal reasons (nothing here touches payments, invoices, subscriptions or the autonomy history, which have their own rules in
docs/DATA_RETENTION.md and services/agent/retention.py). The numbers are settings, 0 = keep.

  ended login sessions        deleted `session_retention_days` after they ENDED (signed out, or expired, whichever came first). They hold an IP address and a browser string.
  password-reset tokens       deleted `password_reset_token_retention_days` after they were CREATED, used or not (they stop working after minutes; this removes the rows).
  audit-log IP addresses      the IP alone is set to NULL `audit_ip_retention_days` after the entry was written. The entry (who, what, when) stays: the database only lets the IP column change
                              (migration 0039, trigger `audit_logs_ip_only`).
  demo-request leads          deleted `lead_retention_days` after they were received.

How it behaves: one scheduled task (`flowqr.privacy_retention`, daily, on the existing beat) that does NOTHING unless PRIVACY_RETENTION_ENABLED=true. `dry_run=True` (CLI `privacy-retention-report`)
only counts. Every step is independent (one failing leaves the others to run, and the error is reported, not hidden), repeatable (a second run finds nothing left to do), and counted, never
described, in the audit log. A row exactly `days` old is KEPT: only rows strictly older than the cutoff go. All times are UTC (timezone-aware columns).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AuditLog, AuthSession, Lead, PasswordResetToken
from app.models.base import utcnow
from app.services.audit import audit

log = logging.getLogger("flowqr.retention.privacy")
IP_BATCH = 5000


def _cutoff(now: datetime, days: int) -> datetime | None:
    return now - timedelta(days=days) if days and days > 0 else None


def _ended_at():
    """When a session stopped being usable: the sign-out, or the expiry if that came first."""
    return func.least(func.coalesce(AuthSession.revoked_at, AuthSession.expires_at), AuthSession.expires_at)


def ended_sessions(db: Session, now: datetime, dry_run: bool) -> int:
    cut = _cutoff(now, settings.session_retention_days)
    if cut is None:
        return 0
    cond = _ended_at() < cut
    if dry_run:
        return db.scalar(select(func.count()).select_from(AuthSession).where(cond)) or 0
    return db.execute(delete(AuthSession).where(cond)).rowcount or 0


def reset_tokens(db: Session, now: datetime, dry_run: bool) -> int:
    cut = _cutoff(now, settings.password_reset_token_retention_days)
    if cut is None:
        return 0
    cond = PasswordResetToken.created_at < cut
    if dry_run:
        return db.scalar(select(func.count()).select_from(PasswordResetToken).where(cond)) or 0
    return db.execute(delete(PasswordResetToken).where(cond)).rowcount or 0


def audit_ips(db: Session, now: datetime, dry_run: bool) -> int:
    cut = _cutoff(now, settings.audit_ip_retention_days)
    if cut is None:
        return 0
    cond = (AuditLog.ip.is_not(None), AuditLog.created_at < cut)
    if dry_run:
        return db.scalar(select(func.count()).select_from(AuditLog).where(*cond)) or 0
    total = 0
    while True:  # in batches, so one run never holds a long lock on a large table
        ids = select(AuditLog.id).where(*cond).limit(IP_BATCH)
        n = db.execute(update(AuditLog).where(AuditLog.id.in_(ids)).values(ip=None)).rowcount or 0
        db.commit()
        total += n
        if n < IP_BATCH:
            return total


def old_leads(db: Session, now: datetime, dry_run: bool) -> int:
    cut = _cutoff(now, settings.lead_retention_days)
    if cut is None:
        return 0
    if dry_run:
        return db.scalar(select(func.count()).select_from(Lead).where(Lead.created_at < cut)) or 0
    return db.execute(delete(Lead).where(Lead.created_at < cut)).rowcount or 0


STEPS = (("ended_sessions", ended_sessions), ("reset_tokens", reset_tokens), ("audit_ips", audit_ips), ("leads", old_leads))


def run(db: Session, *, now: datetime | None = None, dry_run: bool = False) -> dict:
    """Needs a bypass-RLS session (the job's). Returns {"enabled", "dry_run", "counts": {step: n}, "errors": [step, ...]}."""
    now = now or utcnow()
    if not dry_run and not settings.privacy_retention_enabled:
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
            log.error("privacy retention step %s failed: %s", name, type(exc).__name__)
    if not dry_run and (any(counts.values()) or errors):
        audit(db, action="retention.privacy_run", entity_type="retention", meta={"counts": counts, "errors": errors, "provisional": True,
                                                                               "days": {"sessions": settings.session_retention_days, "reset_tokens": settings.password_reset_token_retention_days,
                                                                                        "audit_ips": settings.audit_ip_retention_days, "leads": settings.lead_retention_days}})
        db.commit()
    log.info("privacy retention (dry_run=%s): %s errors=%s", dry_run, counts, errors)
    return {"enabled": True, "dry_run": dry_run, "counts": counts, "errors": errors}
