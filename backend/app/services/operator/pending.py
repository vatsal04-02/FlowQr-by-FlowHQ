"""One list of everything waiting for a person, read from the tables that already hold it. NOTHING here is stored a second time and nothing here writes.

Sources (each item keeps its own id and its own approval endpoint, so approving here is exactly approving there):
  * `agent_actions`      profile changes the engine drafted (`pending_approval`, and `recommended` while the customer-write policy gate is closed), plus failed or blocked ones
  * `reply_drafts`       review replies waiting for approval
  * `scheduled_posts`    Google posts waiting for approval (Marketing Studio campaigns land here too)
  * `agent_tasks`        the older "profile_fix" description drafts

Every item says what the operations on it are (`operations`), so the screen never guesses an endpoint and never offers a button the server would refuse. An operation that is not
available says why (`reason`); a button is never shown dead."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentAction, AgentTask, GbpSnapshot, GoogleLocation, ReplyDraft, ReplyStatus, Review, ScheduledPost
from app.services.agent import executor
from app.services.agent import knowledge as kbs
from app.services.agent import posts as posts_svc
from app.services.agent.safety import check_text
from app.services.agent.v2 import gate as v2gate
from app.services.agent.v2 import present  # noqa: F401  (kept for callers that format a diff themselves)

CATEGORIES = {"profile": "Profile improvements", "business_info": "Business information", "reviews": "Reviews", "posts": "Posts and campaigns", "other": "Other"}
FIELD_CATEGORY = {"description": "profile", "categories": "profile", "additional_categories": "profile", "primary_category": "profile", "services": "profile", "attributes": "profile",
                  "hours": "business_info", "special_hours": "business_info", "website": "business_info", "phone": "business_info", "service_area": "business_info"}
EDITABLE_ACTION_FIELDS = frozenset({"description"})  # the only action text a person can reword before approving: every other field is a structured list the engine validates
STATUS_WORDS = {"pending_approval": "Waiting for your approval", "recommended": "Drafted: not applied by FlowQR yet", "approved": "Approved: being applied", "executing": "Being applied now",
                "executed": "Applied and confirmed on Google", "failed": "Failed", "blocked": "Blocked", "invalidated": "Out of date", "awaiting_approval": "Waiting for your approval",
                "draft": "Waiting for your approval"}


def _op(method: str, path: str, *, body: dict | None = None, then: dict | None = None, ok: bool = True, reason: str | None = None) -> dict:
    return {"available": ok, "method": method, "path": path, "body": body or {}, "then": then, "reason": reason}


def _off(reason: str) -> dict:
    return {"available": False, "method": None, "path": None, "body": {}, "then": None, "reason": reason}


def _category_for(field: str | None) -> str:
    return FIELD_CATEGORY.get(field or "", "other")


def _lines(xs: list[str] | None) -> str:
    return "\n".join(xs or [])


def _action_item(db: Session, a: AgentAction, gloc: GoogleLocation) -> dict:
    row = executor.action_out(db, a)
    diff = row.get("diff")  # lists of objects (services, hours, categories, attributes) are shown as plain lines; a description is just text
    before = _lines(diff["before"]) if diff else (row["before"] or "")
    after = _lines(diff["after"]) if diff else (row["after"] or "")
    gate = v2gate.status_for(gloc, a.field_key)
    held = a.status == "recommended"
    gate_open = not (gate["applies"] and not gate["allowed"])
    ops: dict[str, dict] = {}
    if a.status == "pending_approval" or (held and gate_open):
        ops["approve"] = _op("POST", f"/agent/actions/{a.id}/approve", body={})
    else:
        ops["approve"] = _off(gate["reason"] or "FlowQR does not make this kind of change on this profile yet. You can make it in Google Business Profile." if held
                              else f"This change is {STATUS_WORDS.get(a.status, a.status).lower()}.")
    if a.status in ("pending_approval", "recommended"):
        ops["reject"] = _op("POST", f"/agent/actions/{a.id}/reject", body={"reason": "Not wanted"})
    else:
        ops["reject"] = _off("Only a change that is waiting can be rejected.")
    if a.field_key in EDITABLE_ACTION_FIELDS and a.status in ("pending_approval", "recommended"):
        ops["edit"] = _op("POST", f"/operator/changes/{a.id}/edit", body={"text": ""})
        ops["regenerate"] = _op("POST", f"/operator/changes/{a.id}/regenerate")
    else:
        why = "Services, hours, categories and attributes are checked against Google's own lists, so they are changed by approving or rejecting the whole draft."
        ops["edit"] = _off(why if a.field_key not in EDITABLE_ACTION_FIELDS else "Only a waiting change can be edited.")
        ops["regenerate"] = _off("A new version can be prepared for the description. The other fields are rebuilt from your answers and your Business Brain on the next scan.")
    ai = (a.evidence or {}).get("ai") or {}
    return {"key": f"action:{a.id}", "kind": "action", "id": str(a.id), "category": _category_for(a.field_key), "title": row["label"], "field": a.field_key,
            "status": a.status, "status_label": STATUS_WORDS.get(a.status, a.status), "risk": a.risk_level, "level": a.policy_level,
            "google_location_id": str(a.google_location_id), "location_title": gloc.title, "before": before, "after": after, "diff": diff,
            "problem": a.problem, "reason": a.reason, "expected_outcome": a.expected_outcome, "source": (a.source or {}).get("kind"), "quality_score": ai.get("quality"),
            "model": ai.get("model"), "last_error": a.last_error, "created_at": a.created_at, "verified_at": a.verified_at, "operations": ops,
            "blocked_note": gate["reason"] if held else None}


def action_item(db: Session, a: AgentAction, gloc: GoogleLocation) -> dict:
    """One proposal as a pending-work item (public: the API and the operator show a change the moment it is prepared)."""
    return _action_item(db, a, gloc)


def _reply_item(d: ReplyDraft, r: Review, gloc: GoogleLocation | None, kb: dict) -> dict:
    violations = [v.as_dict() for v in check_text(d.body, kb=kb, kind="reply")]
    flagged = bool(d.requires_human_handling)
    ops = {"approve": _op("POST", f"/reply-drafts/{d.id}/approve", body={"acknowledge_flags": flagged}, then=_op("POST", f"/reply-drafts/{d.id}/publish")),
           "reject": _op("DELETE", f"/reply-drafts/{d.id}"), "edit": _op("PATCH", f"/reply-drafts/{d.id}", body={"body": d.body}),
           "regenerate": _op("POST", f"/reviews/{r.id}/drafts/generate", body={})}
    return {"key": f"reply:{d.id}", "kind": "reply", "id": str(d.id), "category": "reviews", "title": f"Reply to a {r.rating}-star review", "field": "reply", "status": "draft",
            "status_label": STATUS_WORDS["draft"], "risk": d.risk_level or "low", "level": 2, "google_location_id": str(r.google_location_id), "location_title": gloc.title if gloc else None,
            "before": (r.text or "")[:600], "before_label": f"{r.reviewer_name or 'A customer'} wrote", "after": d.body, "diff": None, "problem": "This review has no reply.",
            "reason": "Customers read replies, and an answered review shows you pay attention." if not flagged else "This review needs you to read it yourself before replying.",
            "expected_outcome": "The reply is published on Google and read back from the profile.", "source": "ai" if d.generated_by_ai else "owner", "quality_score": None, "model": None,
            "last_error": None, "created_at": d.created_at, "verified_at": None, "operations": ops, "flags": d.flag_reasons or [], "violations": violations, "needs_acknowledgement": flagged,
            "review_id": str(r.id)}


def _post_item(p: ScheduledPost, gloc: GoogleLocation | None, kb: dict) -> dict:
    ops = {"approve": _op("POST", f"/posts/{p.id}/approve", body={}), "reject": _op("POST", f"/posts/{p.id}/reject"),
           "edit": _off("Open the post to change its wording, photo or time."), "regenerate": _off("Ask the operator for a new version, or open the post.")}
    return {"key": f"post:{p.id}", "kind": "post", "id": str(p.id), "category": "posts", "title": {"OFFER": "Offer post", "EVENT": "Event post"}.get(p.topic_type or "", "Google post"), "field": "post",
            "status": "awaiting_approval", "status_label": STATUS_WORDS["awaiting_approval"], "risk": "medium", "level": 2, "google_location_id": str(p.google_location_id),
            "location_title": gloc.title if gloc else None, "before": "", "after": p.summary, "diff": None, "problem": "No recent post on your profile.",
            "reason": "Fresh posts show customers you are open and active.", "expected_outcome": "The post is published on Google and its status is read back.",
            "source": "ai" if p.generated_by_ai else "owner", "quality_score": None, "model": None, "last_error": None, "created_at": p.created_at, "verified_at": None, "operations": ops,
            "violations": posts_svc.validate_content(p, kb), "scheduled_for": p.scheduled_for}


def _profile_task_item(db: Session, t: AgentTask, kb: dict) -> dict:
    desc = (t.draft or {}).get("description", "")
    gid = (t.evidence or {}).get("google_location_id")
    gloc, current = None, ""
    if gid:
        try:
            gloc = db.get(GoogleLocation, uuid.UUID(gid))
            snap = db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gloc.id)) if gloc else None
            current = ((snap.info or {}).get("description") or "") if snap else ""
        except ValueError:
            gloc = None
    ops = {"approve": _op("POST", f"/agent/tasks/{t.id}/approve"), "reject": _op("POST", f"/agent/tasks/{t.id}/dismiss"), "edit": _op("PATCH", f"/agent/tasks/{t.id}/draft", body={"description": desc}),
           "regenerate": _op("POST", f"/agent/tasks/{t.id}/draft")}
    return {"key": f"task:{t.id}", "kind": "profile_task", "id": str(t.id), "category": "profile", "title": "Business description", "field": "description", "status": "awaiting_approval",
            "status_label": STATUS_WORDS["awaiting_approval"], "risk": "low", "level": 1, "google_location_id": gid, "location_title": gloc.title if gloc else None, "before": current, "after": desc,
            "diff": None, "problem": "The description can say more about what you do.", "reason": "Written only from the facts in your Business Brain, then checked against its rules.",
            "expected_outcome": "The description is written to Google and read back.", "source": "ai", "quality_score": None, "model": None, "last_error": None, "created_at": t.created_at,
            "verified_at": None, "operations": ops, "violations": [v.as_dict() for v in check_text(desc, kb=kb, kind="profile")]}


def list_pending(db: Session, tenant, ctx: Any, *, category: str | None = None, include_attention: bool = True, limit: int = 100) -> dict:
    """`ctx` is the request's TenantContext (it supplies the location scope). Returns {items, counts, categories}."""
    kb = kbs.context(db, tenant)
    items: list[dict] = []
    glocs = {g.id: g for g in db.scalars(select(GoogleLocation).where(GoogleLocation.tenant_id == tenant.id))}
    statuses = ("pending_approval", "recommended") + (("failed", "blocked") if include_attention else ())
    for a in db.scalars(select(AgentAction).where(AgentAction.tenant_id == tenant.id, AgentAction.status.in_(statuses), AgentAction.subject_type.is_(None))
                        .order_by(AgentAction.updated_at.desc()).limit(limit)):
        g = glocs.get(a.google_location_id)
        if g is not None and ctx.can_access_location(g.location_id):
            items.append(_action_item(db, a, g))
    for d, r in db.execute(select(ReplyDraft, Review).join(Review, Review.id == ReplyDraft.review_id).where(
            ReplyDraft.tenant_id == tenant.id, ReplyDraft.status == ReplyStatus.draft, Review.google_reply_text.is_(None), ctx.scope(Review.location_id))
            .order_by(ReplyDraft.created_at.desc()).limit(limit)).all():
        items.append(_reply_item(d, r, glocs.get(r.google_location_id), kb))
    for p in db.scalars(select(ScheduledPost).join(GoogleLocation, GoogleLocation.id == ScheduledPost.google_location_id).where(
            ScheduledPost.tenant_id == tenant.id, ScheduledPost.status == "awaiting_approval", ctx.scope(GoogleLocation.location_id)).order_by(ScheduledPost.created_at.desc()).limit(limit)):
        items.append(_post_item(p, glocs.get(p.google_location_id), kb))
    for t in db.scalars(select(AgentTask).where(AgentTask.tenant_id == tenant.id, AgentTask.kind == "profile_fix", AgentTask.status == "awaiting_approval",
                                                ctx.scope(AgentTask.location_id) if ctx.restricted else AgentTask.tenant_id == tenant.id).limit(20)):
        items.append(_profile_task_item(db, t, kb))
    counts = {k: 0 for k in CATEGORIES}
    for i in items:
        counts[i["category"]] += 1
    if category:
        items = [i for i in items if i["category"] == category]
    items.sort(key=lambda i: str(i["created_at"] or ""), reverse=True)  # newest first, then what is waiting for a person ahead of what is only drafted or has failed
    items.sort(key=lambda i: i["status"] not in ("pending_approval", "awaiting_approval", "draft"))
    return {"items": items, "counts": counts, "total": sum(counts.values()), "categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()]}
