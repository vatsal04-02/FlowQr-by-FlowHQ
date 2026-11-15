"""The ranking feedback loop for autonomy actions.

For an eligible action (one whose action type can plausibly affect local visibility):
  1. BASELINE  before the Google write, the tracked search terms are measured (a recent measurement is reused; otherwise a fresh Places check is made, inside the
     business's monthly Places allowance).
  2. FOLLOW-UPS  the same terms are re-measured 7, 14 and 28 days after the change was verified on Google.
  3. EVALUATION  each term is compared with its baseline; at day 28 the action gets an overall observed label.
  4. PRIORITIES  an action type that failed repeatedly, was rejected, declined or showed no change is not proposed again for a cooling-off period.

What this is NOT: proof. Rankings move for many reasons (competitors, seasons, Google's own changes, the person and place of the search). Every result here
says "observed after the change", the label is never worded as a cause, and a Places measurement is the position among the first 20 Places results around
one point, not a guaranteed Google Maps ranking. A failed measurement is "unknown", never a rank."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AgentAction, AgentRankFollowup, GoogleLocation, RankCheck, RankKeyword
from app.models.base import utcnow
from app.services import rank as rank_svc
from app.services.agent import history

log = logging.getLogger("flowqr.learning")
FOLLOWUP_DAYS = (7, 14, 28)
MEANINGFUL = 3  # positions: a smaller move is "unchanged" (rank noise)
BASELINE_MAX_AGE = timedelta(days=7)
MAX_FOLLOWUP_ATTEMPTS = 3
NOTE = ("Observed after the change, not proof that the change caused it: rankings also move with competitors, seasons, the searcher's place and Google's own updates. "
        "Positions are among the first 20 Google Places results around one point, not a guaranteed Google Maps ranking.")


def tracked(db: Session, google_location_id: uuid.UUID) -> list[RankKeyword]:
    return list(db.scalars(select(RankKeyword).where(RankKeyword.google_location_id == google_location_id).order_by(RankKeyword.created_at).limit(rank_svc.max_keywords())))


def _latest(db: Session, keyword_id: uuid.UUID, ok_only: bool = False) -> RankCheck | None:
    q = select(RankCheck).where(RankCheck.keyword_id == keyword_id)
    if ok_only:
        q = q.where(RankCheck.status == "ok")
    return db.scalar(q.order_by(RankCheck.checked_at.desc()).limit(1))


def rank_summary(db: Session, google_location_id: uuid.UUID) -> dict | None:
    """What the latest measurements say, per tracked search term. None when nothing has been measured (so callers never act on data that does not exist)."""
    items = []
    for kw in tracked(db, google_location_id):
        c = _latest(db, kw.id)
        if c is not None:
            items.append({"keyword_id": str(kw.id), "keyword": kw.keyword, "status": c.status, "rank": c.rank, "checked_at": c.checked_at.isoformat(), "results_seen": c.results_seen})
    if not items:
        return None
    ok = [i for i in items if i["status"] == "ok"]
    weak = [i for i in ok if i["rank"] is None or i["rank"] > 10]
    return {"keywords": items, "measured": len(ok), "failed": len(items) - len(ok), "not_found": [i for i in ok if i["rank"] is None], "weak": weak,
            "note": "Measured from Google Places results (first 20) around one point; not a guaranteed Google Maps ranking."}


def compare(base_rank: int | None, new_rank: int | None, new_status: str) -> str:
    """improved | declined | unchanged | unknown. Not found (None) is a real result; a failed check is unknown."""
    if new_status != "ok":
        return "unknown"
    if base_rank is None and new_rank is None:
        return "unchanged"
    if base_rank is None:
        return "improved"  # found now, was not in the first 20
    if new_rank is None:
        return "declined"
    delta = base_rank - new_rank
    return "improved" if delta >= MEANINGFUL else "declined" if delta <= -MEANINGFUL else "unchanged"


def measure_baseline(db: Session, action: AgentAction, gloc: GoogleLocation, now: datetime | None = None, client=None) -> dict:
    """Measure the tracked terms BEFORE the Google write and store them on the action. A recent check is reused (no cost); otherwise one Places call per term,
    inside the business's monthly allowance. Whatever cannot be measured is recorded as unavailable, with the reason. Never blocks the action."""
    now = now or utcnow()
    kws = tracked(db, gloc.id)
    out: list[dict] = []
    reason = None
    if not kws:
        reason = "No search terms are tracked for this location, so there is nothing to measure before or after."
    else:
        client = client or rank_svc.get_client()
        for kw in kws:
            prior = _latest(db, kw.id, ok_only=True)
            if prior is not None and prior.checked_at >= now - BASELINE_MAX_AGE:
                out.append({"keyword_id": str(kw.id), "keyword": kw.keyword, "status": "ok", "rank": prior.rank, "checked_at": prior.checked_at.isoformat(), "source": "recent_measurement"})
                continue
            try:
                row = rank_svc.check_keyword(db, gloc, kw, source="learn", client=client)
            except rank_svc.RankError as exc:  # not configured, or the monthly allowance is used: record why, move on
                out.append({"keyword_id": str(kw.id), "keyword": kw.keyword, "status": "unavailable", "rank": None, "error": str(exc)[:200], "source": "none"})
                reason = reason or str(exc)[:200]
                continue
            out.append({"keyword_id": str(kw.id), "keyword": kw.keyword, "status": row.status, "rank": row.rank, "checked_at": row.checked_at.isoformat(),
                        "source": "fresh_measurement", **({"error": (row.error or "")[:200]} if row.status != "ok" else {})})
    action.baseline = {"measured_at": now.isoformat(), "keywords": out, "usable": sum(1 for k in out if k["status"] == "ok"), "unavailable_reason": reason, "note": NOTE}
    history.record(db, action, "baseline_measured", actor="system", data={"usable": action.baseline["usable"], "keywords": [{k: v for k, v in x.items() if k != "keyword_id"} for x in out],
                                                                         "unavailable_reason": reason}, now=now)
    return action.baseline


def schedule_followups(db: Session, action: AgentAction, anchor: datetime) -> int:
    """Queue the re-measurements (once). Only when there is a usable baseline to compare with."""
    usable = (action.baseline or {}).get("usable", 0)
    if not usable:
        history.record(db, action, "followups_skipped", actor="system", data={"reason": "no usable ranking baseline, so a before/after comparison is not possible"}, now=anchor)
        return 0
    made = 0
    for d in FOLLOWUP_DAYS:
        if db.scalar(select(AgentRankFollowup.id).where(AgentRankFollowup.action_id == action.id, AgentRankFollowup.day_offset == d)) is None:
            db.add(AgentRankFollowup(tenant_id=action.tenant_id, action_id=action.id, google_location_id=action.google_location_id, day_offset=d, due_at=anchor + timedelta(days=d)))
            made += 1
    db.flush()
    history.record(db, action, "followups_scheduled", actor="system", data={"days": list(FOLLOWUP_DAYS), "from": anchor.isoformat()}, now=anchor)
    return made


def overall(results: list[dict]) -> str:
    c = {k: sum(1 for r in results if r["verdict"] == k) for k in ("improved", "declined", "unchanged", "unknown")}
    if c["improved"] + c["declined"] + c["unchanged"] == 0:
        return "insufficient_data"
    if c["improved"] and c["declined"]:
        return "mixed"
    return "improved" if c["improved"] else "declined" if c["declined"] else "unchanged"


def run_due_followups(db: Session, *, now: datetime | None = None, client=None, limit: int = 20) -> dict:
    """Re-measure what is due. Each follow-up is its own transaction and row-locked. A term that cannot be measured (quota, error) is "unknown"; a follow-up where
    nothing could be measured is retried the next day, then given up: an unmeasured result is never turned into a number."""
    now = now or utcnow()
    out = {"done": 0, "deferred": 0, "skipped": 0}
    ids = list(db.scalars(select(AgentRankFollowup.id).where(AgentRankFollowup.status.in_(("pending", "deferred")), AgentRankFollowup.due_at <= now).order_by(AgentRankFollowup.due_at).limit(limit)))
    for fid in ids:
        fu = db.scalar(select(AgentRankFollowup).where(AgentRankFollowup.id == fid, AgentRankFollowup.status.in_(("pending", "deferred"))).with_for_update(skip_locked=True))
        if fu is None:
            continue
        a, gl = db.get(AgentAction, fu.action_id), db.get(GoogleLocation, fu.google_location_id)
        if a is None or gl is None or not gl.selected or a.tenant_id != fu.tenant_id:
            fu.status, fu.result = "skipped", {"reason": "the action or location is no longer available"}
            out["skipped"] += 1
            db.commit()
            continue
        client = client or rank_svc.get_client()
        results = []
        for b in (a.baseline or {}).get("keywords", []):
            kw = db.get(RankKeyword, uuid.UUID(b["keyword_id"])) if b.get("status") == "ok" else None
            if kw is None:
                results.append({"keyword": b.get("keyword"), "baseline_rank": b.get("rank"), "rank": None, "verdict": "unknown", "reason": "no usable baseline or the term was removed"})
                continue
            try:
                row = rank_svc.check_keyword(db, gl, kw, source="learn", client=client)
            except rank_svc.RankError as exc:
                results.append({"keyword": kw.keyword, "baseline_rank": b["rank"], "rank": None, "verdict": "unknown", "reason": str(exc)[:160]})
                continue
            results.append({"keyword": kw.keyword, "baseline_rank": b["rank"], "rank": row.rank, "verdict": compare(b["rank"], row.rank, row.status),
                            **({"reason": (row.error or "check failed")[:160]} if row.status != "ok" else {}), "checked_at": row.checked_at.isoformat()})
        label = overall(results)
        if label == "insufficient_data":
            fu.attempts += 1
            fu.status = "deferred" if fu.attempts < MAX_FOLLOWUP_ATTEMPTS else "skipped"
            fu.due_at = now + timedelta(days=1)
            fu.result = {"day": fu.day_offset, "overall": label, "keywords": results, "note": NOTE}
            out["deferred" if fu.status == "deferred" else "skipped"] += 1
            if fu.status == "skipped":
                history.record(db, a, "followup_skipped", actor="system", data={"day": fu.day_offset, "reason": "could not measure (quota or errors)", "keywords": results}, now=now)
            db.commit()
            continue
        fu.status, fu.measured_at, fu.result = "done", now, {"day": fu.day_offset, "overall": label, "keywords": results, "note": NOTE}
        out["done"] += 1
        history.record(db, a, "followup_measured", actor="system", data={"day": fu.day_offset, "overall": label, "keywords": results, "note": NOTE}, now=now)
        if fu.day_offset == max(FOLLOWUP_DAYS):
            a.outcome = {"label": label, "day": fu.day_offset, "evaluated_at": now.isoformat(), "keywords": results, "note": NOTE}
            history.record(db, a, "evaluated", actor="system", data={"label": label, "note": NOTE}, now=now)
        db.commit()
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------------
# priorities: do not keep applying what did not work
# ---------------------------------------------------------------------------------------------------------------------------------------------
def suppression(db: Session, tenant_id: uuid.UUID, google_location_id: uuid.UUID, action_type: str, field_key: str, now: datetime | None = None) -> str | None:
    """Why this kind of change should NOT be proposed again right now, or None. Scoped to ONE business and ONE location: nothing learned about another business is used."""
    now = now or utcnow()
    base = [AgentAction.tenant_id == tenant_id, AgentAction.google_location_id == google_location_id, AgentAction.action_type == action_type, AgentAction.field_key == field_key]
    failed = list(db.scalars(select(AgentAction).where(*base, AgentAction.status == "failed", AgentAction.updated_at >= now - timedelta(days=30)).order_by(AgentAction.updated_at.desc())))
    if len(failed) >= 2 and failed[0].updated_at >= now - timedelta(days=14):
        return f"Paused: this change failed {len(failed)} times in the last 30 days. FlowQR will not retry it automatically until the cause is fixed or 14 days pass."
    if db.scalar(select(func.count()).select_from(AgentAction).where(*base, AgentAction.status == "rejected", AgentAction.updated_at >= now - timedelta(days=14))):
        return "Paused: you rejected this kind of change recently."
    done = list(db.scalars(select(AgentAction).where(*base, AgentAction.status == "executed", AgentAction.outcome.is_not(None)).order_by(AgentAction.executed_at.desc()).limit(2)))
    if done and done[0].outcome["label"] == "declined" and done[0].executed_at >= now - timedelta(days=45):
        return "Paused: after the last change of this kind, the tracked search terms were observed to move down. FlowQR will not repeat it for 45 days (this is not proof it caused that)."
    if len(done) == 2 and all(d.outcome["label"] == "unchanged" for d in done) and done[0].executed_at >= now - timedelta(days=60):
        return "Paused: the last two changes of this kind showed no observed movement, so repeating it is unlikely to help. Paused for 60 days."
    return None


def priority_modifier(db: Session, tenant_id: uuid.UUID, action_type: str) -> int:
    """Added to a task's priority number (LOWER = more urgent): what worked before is promoted, what did not is demoted. One business's own history only."""
    last = db.scalar(select(AgentAction).where(AgentAction.tenant_id == tenant_id, AgentAction.action_type == action_type, AgentAction.outcome.is_not(None)).order_by(AgentAction.executed_at.desc()).limit(1))
    return {"improved": -5, "unchanged": 10, "declined": 20}.get(last.outcome["label"], 0) if last else 0
