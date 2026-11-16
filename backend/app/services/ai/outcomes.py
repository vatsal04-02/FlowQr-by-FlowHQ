"""AI Output Acceptance Rate: how often owners keep what the AI wrote.

An output is ACCEPTED when the owner approves it and the text they approved is within ACCEPT_EDIT_RATIO of what the AI wrote, i.e. no substantial
rewriting. This is the main quality number for the AI, tracked separately for review replies, Google Posts, profile descriptions and customer review
drafts. It is a count of decisions, not of generations: a platform that generates 10,000 posts nobody uses scores near zero.

  * replies, posts, descriptions: the AI's original text is recorded when it is generated (`ai_outputs`), and compared with the approved text;
  * customer review drafts: measured from review_drafts (generated_content vs the customer's final_content); the customer's text is never copied.

Recording never blocks the owner's action: a failure here is swallowed (savepoint) and logged."""
from __future__ import annotations

import difflib
import logging
import statistics
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AIOutput
from app.models.base import utcnow

log = logging.getLogger("flowqr.ai.outcomes")
ACCEPT_EDIT_RATIO = 0.25  # approved with at most a quarter of the words changed
KINDS = ("reply", "post", "description")
LABEL = {"reply": "Review replies", "post": "Google Posts", "description": "Profile descriptions", "review_draft": "Customer review drafts"}


def edit_ratio(original: str, final: str) -> float:
    """0 = identical, 1 = nothing in common. Word-level, so a changed sentence counts in proportion, not as a total rewrite."""
    a, b = (original or "").split(), (final or "").split()
    if not a and not b:
        return 0.0
    return round(1 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 3)


def record_generated(db: Session, tenant_id: uuid.UUID, kind: str, ref_id: uuid.UUID, text: str, *, model: str | None = None, language: str | None = None,
                     score: float | None = None, replaces: uuid.UUID | None = None) -> None:
    """Call right after an AI draft is created. `replaces` = an earlier AI draft for the same thing that is now superseded (a regeneration)."""
    try:
        with db.begin_nested():
            if replaces:
                prev = db.scalar(select(AIOutput).where(AIOutput.kind == kind, AIOutput.ref_id == replaces, AIOutput.decision.is_(None)))
                if prev:
                    prev.decision, prev.decided_at, prev.reject_reason = "replaced", utcnow(), "regenerated"
            db.add(AIOutput(tenant_id=tenant_id, kind=kind, ref_id=ref_id, model=model, language=language, original_text=text, quality_score=score))
            db.flush()
    except Exception:  # noqa: BLE001
        log.warning("could not record AI output (%s)", kind, exc_info=True)


def record_decision(db: Session, kind: str, ref_id: uuid.UUID, decision: str, *, final_text: str | None = None, reason: str | None = None) -> None:
    """approved (with the exact approved text) | rejected. Only the first decision counts."""
    try:
        with db.begin_nested():
            o = db.scalar(select(AIOutput).where(AIOutput.kind == kind, AIOutput.ref_id == ref_id))
            if o is None or o.decision in ("approved", "rejected") and decision != "approved":
                return
            if o.decision == "approved":
                return
            o.decision, o.decided_at, o.reject_reason = decision, utcnow(), (reason or None)
            if decision == "approved" and final_text is not None:
                o.edit_ratio = edit_ratio(o.original_text, final_text)
            db.flush()
    except Exception:  # noqa: BLE001
        log.warning("could not record AI decision (%s)", kind, exc_info=True)


def summary(db: Session, tenant_id: uuid.UUID | None = None, days: int = 90) -> dict:
    """{kind: {generated, decided, approved, accepted, acceptance_rate, median_edit_ratio, rejected, regenerated, top_reject_reasons, avg_quality}}.
    acceptance_rate = accepted / decided (None until something has been decided). `tenant_id=None` is the platform-wide view (admin only; caller must bypass RLS)."""
    since = utcnow() - timedelta(days=days)
    out: dict[str, dict] = {}
    for kind in KINDS:
        q = select(AIOutput).where(AIOutput.kind == kind, AIOutput.created_at >= since)
        if tenant_id:
            q = q.where(AIOutput.tenant_id == tenant_id)
        rows = db.scalars(q).all()
        decided = [r for r in rows if r.decision in ("approved", "rejected", "replaced")]
        approved = [r for r in decided if r.decision == "approved"]
        accepted = [r for r in approved if (r.edit_ratio if r.edit_ratio is not None else 1.0) <= ACCEPT_EDIT_RATIO]
        reasons: dict[str, int] = {}
        for r in decided:
            if r.decision in ("rejected", "replaced"):
                reasons[r.reject_reason or "no reason given"] = reasons.get(r.reject_reason or "no reason given", 0) + 1
        scores = [r.quality_score for r in rows if r.quality_score is not None]
        out[kind] = {
            "label": LABEL[kind], "generated": len(rows), "decided": len(decided), "approved": len(approved), "accepted": len(accepted),
            "acceptance_rate": round(len(accepted) / len(decided), 3) if decided else None,
            "median_edit_ratio": round(statistics.median([r.edit_ratio for r in approved if r.edit_ratio is not None]), 3) if any(r.edit_ratio is not None for r in approved) else None,
            "rejected": sum(1 for r in decided if r.decision == "rejected"), "regenerated": sum(1 for r in decided if r.decision == "replaced"),
            "top_reject_reasons": sorted(reasons.items(), key=lambda kv: -kv[1])[:3], "avg_quality": round(sum(scores) / len(scores), 3) if scores else None,
        }
    out["review_draft"] = review_draft_summary(db, tenant_id, since)
    return out


def review_draft_summary(db: Session, tenant_id: uuid.UUID | None, since) -> dict:
    """Customer review assistant: a draft counts as decided when the customer approved their text. Accepted = their final text is within the edit limit of the AI draft."""
    from app.models import ReviewDraft
    q = select(ReviewDraft).where(ReviewDraft.generated_content.is_not(None), ReviewDraft.created_at >= since)
    if tenant_id:
        q = q.where(ReviewDraft.tenant_id == tenant_id)
    rows = db.scalars(q).all()
    decided = [r for r in rows if r.approved_at and r.final_content]
    ratios = [edit_ratio(r.generated_content, r.final_content) for r in decided]
    accepted = [x for x in ratios if x <= ACCEPT_EDIT_RATIO]
    regen = sum(max(0, (r.generation_count or 1) - 1) for r in rows)
    return {"label": LABEL["review_draft"], "generated": len(rows), "decided": len(decided), "approved": len(decided), "accepted": len(accepted),
            "acceptance_rate": round(len(accepted) / len(decided), 3) if decided else None, "median_edit_ratio": round(statistics.median(ratios), 3) if ratios else None,
            "rejected": len(rows) - len(decided), "regenerated": regen, "top_reject_reasons": [], "avg_quality": None,
            "note": "Measured from the customer's own edits; the customer's text is not copied anywhere else."}
