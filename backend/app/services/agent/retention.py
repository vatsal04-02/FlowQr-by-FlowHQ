"""Retention of the autonomy records (see docs/DATA_RETENTION.md).

The intervention history is append-only and tamper-evident (history.py), which is the right default for an audit trail and the wrong default for personal data that is
not needed any more. So there are exactly two ways it ever leaves the database, both deliberate and both audited:
  1. the whole business is deleted (account.delete_tenant): everything of that business is erased, no exceptions;
  2. this module: finished actions older than `autonomy_history_retention_days` are erased as WHOLE records (the action, its approvals, its history and its follow-ups
     together), never edited. An erased record leaves only a count in the audit log (tenant, number, cutoff), no content.
Live work (waiting, approved, executing) and actions with ranking follow-ups still due are never touched."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AgentAction, AgentRankFollowup, RankGridScan
from app.models.base import utcnow
from app.services.audit import audit

log = logging.getLogger("flowqr.retention")
FINISHED = ("executed", "failed", "rejected", "expired", "invalidated", "blocked", "canceled")


def purge_old_history(db: Session, *, now: datetime | None = None) -> dict:
    """Erase finished autonomy records past retention. Needs a bypass-RLS session (the scheduled job's). Returns {"actions": n, "tenants": k, "grid_scans": m}."""
    now = now or utcnow()
    out = {"actions": 0, "tenants": 0, "grid_scans": 0}
    days = settings.autonomy_history_retention_days
    if days > 0:
        cutoff = now - timedelta(days=days)
        pending_followup = select(AgentRankFollowup.action_id).where(AgentRankFollowup.status.in_(("pending", "deferred")))
        db.execute(text("SELECT set_config('app.history_purge', 'on', true)"))  # transaction-local: only this statement may erase history
        rows = db.execute(delete(AgentAction).where(AgentAction.status.in_(FINISHED), AgentAction.created_at < cutoff, AgentAction.id.not_in(pending_followup))
                          .returning(AgentAction.tenant_id)).all()
        per: dict = {}
        for (tid,) in rows:
            per[tid] = per.get(tid, 0) + 1
        for tid, n in per.items():
            audit(db, action="autonomy.history_purged", tenant_id=tid, entity_type="agent_actions", meta={"records": n, "older_than": cutoff.date().isoformat(), "retention_days": days})
        out["actions"], out["tenants"] = len(rows), len(per)
    gdays = settings.rank_grid_retention_days
    if gdays > 0:
        gc = now - timedelta(days=gdays)
        n = db.scalar(select(func.count()).select_from(RankGridScan).where(RankGridScan.started_at < gc)) or 0
        if n:
            db.execute(delete(RankGridScan).where(RankGridScan.started_at < gc))  # its points go with it (cascade)
        out["grid_scans"] = n
    db.commit()
    return out
