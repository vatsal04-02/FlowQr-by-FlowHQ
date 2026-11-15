"""The intervention history: an append-only, hash-chained record of everything that happens to an autonomy action.

Each event stores the hash of the previous event of the same action, so an edited, removed, inserted or reordered row is detectable (`verify`), on top of the
database refusing UPDATE and DELETE on the table (migration 0027: no privilege for the app role + a trigger for everyone). The hash covers the action, the
sequence number, the event type, who did it, the data and the time."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentAction, AgentInterventionEvent
from app.models.base import utcnow

GENESIS = "0" * 64


def _clean(data: dict | None) -> dict:
    """JSON-safe copy (UUIDs, datetimes, Decimals become strings) so what is hashed is exactly what is stored."""
    return json.loads(json.dumps(data or {}, default=str, sort_keys=True))


def _stamp(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _digest(prev: str, action_id, seq: int, event_type: str, actor: str, user_id, data: dict, created_at: datetime) -> str:
    body = json.dumps({"prev": prev, "action": str(action_id), "seq": seq, "type": event_type, "actor": actor, "user": str(user_id) if user_id else None,
                       "data": data, "at": _stamp(created_at)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def record(db: Session, action: AgentAction, event_type: str, *, actor: str, user_id: uuid.UUID | None = None, data: dict | None = None,
           now: datetime | None = None) -> AgentInterventionEvent:
    """Append one event (in the caller's transaction). The action row is locked first so two writers cannot both take the same sequence number."""
    db.execute(select(AgentAction.id).where(AgentAction.id == action.id).with_for_update())
    last = db.scalar(select(AgentInterventionEvent).where(AgentInterventionEvent.action_id == action.id).order_by(AgentInterventionEvent.seq.desc()).limit(1))
    seq, prev = (last.seq + 1, last.hash) if last else (1, GENESIS)
    created, clean = now or utcnow(), _clean(data)
    ev = AgentInterventionEvent(tenant_id=action.tenant_id, action_id=action.id, seq=seq, event_type=event_type, actor=actor, user_id=user_id, data=clean,
                                prev_hash=prev, hash=_digest(prev, action.id, seq, event_type, actor, user_id, clean, created), created_at=created)
    db.add(ev)
    db.flush()
    return ev


def verify(db: Session, action_id: uuid.UUID) -> dict:
    """Recompute the chain. {"ok": bool, "events": n, "broken_at": seq | None, "reason": str | None}. Any change to any stored event breaks it from that point on."""
    rows = list(db.scalars(select(AgentInterventionEvent).where(AgentInterventionEvent.action_id == action_id).order_by(AgentInterventionEvent.seq)))
    prev = GENESIS
    for i, ev in enumerate(rows, 1):
        if ev.seq != i:
            return {"ok": False, "events": len(rows), "broken_at": i, "reason": "an event is missing or out of order"}
        if ev.prev_hash != prev:
            return {"ok": False, "events": len(rows), "broken_at": ev.seq, "reason": "the link to the previous event does not match"}
        if _digest(prev, ev.action_id, ev.seq, ev.event_type, ev.actor, ev.user_id, ev.data, ev.created_at) != ev.hash:
            return {"ok": False, "events": len(rows), "broken_at": ev.seq, "reason": "the event content does not match its hash"}
        prev = ev.hash
    return {"ok": True, "events": len(rows), "broken_at": None, "reason": None}


def timeline(db: Session, action_id: uuid.UUID) -> list[dict]:
    return [{"seq": e.seq, "type": e.event_type, "actor": e.actor, "user_id": str(e.user_id) if e.user_id else None, "data": e.data, "at": e.created_at.isoformat()}
            for e in db.scalars(select(AgentInterventionEvent).where(AgentInterventionEvent.action_id == action_id).order_by(AgentInterventionEvent.seq))]
