"""The operator's tool registry: the ONLY things the AI can do. Every tool is a thin, typed wrapper around a service FlowQR already has.

Rules the registry enforces for every call, whatever the model says:
  * the tool must be registered (a made-up name is refused) and its arguments must validate against its schema (unknown fields are refused);
  * the caller's role must meet the tool's minimum; location access is the caller's own (`ctx.can_access_location`), and a location id from the model is looked up inside THIS tenant only;
  * a tool never receives the database session as a model-controlled value, never approves, publishes or writes to Google. Tools PREPARE: they create a proposal or a draft that waits for a
    person. Approval and execution stay behind the existing endpoints and the executor's own checks (policy level, consent, the customer-write gate, claim, read-back);
  * tool output is data for the model, never instructions: it is clipped, and review text is redacted and withheld when the AI data policy says so.

Model independence: this module knows nothing about any model or provider. `specs()` renders the tools as plain JSON schemas that either a native function-calling API or the JSON protocol in
`orchestrator.py` can use."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.core.deps import TenantContext
from app.models import GoogleConnection, GoogleConnectionStatus, GoogleLocation, Review, Role
from app.models.tenancy import ROLE_RANK
from app.services.ai import privacy
from app.services.operator import pending as pending_svc
from app.services.operator import prepare as prepare_svc
from app.services.operator.context import business_context

MAX_RESULT_CHARS = 6000
AREAS = Literal["description", "categories", "services", "hours", "special_hours", "attributes", "contacts", "service_area"]


class ToolError(Exception):
    """A refusal or failure the model is told about in plain words. Never carries a stack trace or a secret."""


@dataclass
class ToolContext:
    ctx: TenantContext
    request: Request | None
    provider_name: str | None = None


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocationArg(_Args):
    location_id: uuid.UUID | None = Field(default=None, description="The Google location id. Leave empty when the business has a single connected location.")


class PendingArgs(_Args):
    category: Literal["profile", "business_info", "reviews", "posts", "other"] | None = Field(default=None, description="Only changes of this kind.")


class PrepareArgs(LocationArg):
    area: AREAS = Field(description="The part of the profile to improve. FlowQR drafts the complete change and stores it for the owner's approval.")


class ReviewsArgs(LocationArg):
    limit: int = Field(default=5, ge=1, le=10)


class ReplyArgs(_Args):
    review_id: uuid.UUID = Field(description="The id of a review from list_reviews_needing_reply.")


class PostArgs(LocationArg):
    topic: str | None = Field(default=None, max_length=200, description="What the post should be about, in the owner's words. Offers and events are only made from verified facts.")
    kind: Literal["update", "offer", "event"] = "update"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Callable[[ToolContext, Any], dict]
    prepares: bool  # True = creates a proposal or a draft (never writes to Google); False = read-only
    min_role: Role = Role.staff


def _gloc(tc: ToolContext, location_id: uuid.UUID | None) -> GoogleLocation:
    db, ctx = tc.ctx.db, tc.ctx
    base = select(GoogleLocation).join(GoogleConnection, GoogleConnection.id == GoogleLocation.connection_id).where(
        GoogleLocation.tenant_id == ctx.tenant_id, GoogleLocation.selected.is_(True), GoogleConnection.status == GoogleConnectionStatus.active)
    rows = [g for g in db.scalars(base) if ctx.can_access_location(g.location_id)]
    if location_id is not None:
        hit = next((g for g in rows if g.id == location_id), None)
        if hit is None:
            raise ToolError("That location is not one of this business's connected locations.")
        return hit
    if not rows:
        raise ToolError("No Google location is connected yet. Connect Google first.")
    if len(rows) > 1:
        raise ToolError("This business has several locations. Say which one: " + ", ".join(f"{g.title} ({g.id})" for g in rows[:6]))
    return rows[0]


def _need(tc: ToolContext, role: Role) -> None:
    if ROLE_RANK[tc.ctx.role] < ROLE_RANK[role]:
        raise ToolError("Only an owner or admin can ask for this.")


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _get_business_context(tc: ToolContext, a: LocationArg) -> dict:
    g = _gloc(tc, a.location_id)
    out = business_context(tc.ctx.db, tc.ctx.tenant, g, tc.ctx)
    if privacy.block_reason(tc.provider_name):  # review wording is personal data: counts stay, wording is withheld
        out["reviews"]["latest_unanswered"] = []
        out["reviews"]["note"] = "Review wording is withheld from the AI by the data policy."
    else:
        for r in out["reviews"]["latest_unanswered"]:
            r["text"] = privacy.redact(r["text"])
    return out


def _audit_profile(tc: ToolContext, a: LocationArg) -> dict:
    from app.services.agent.v2 import overview

    g = _gloc(tc, a.location_id)
    loc = overview.build(tc.ctx.db, tc.ctx.tenant, [g])["locations"][0]
    if not loc["profile_read"]:
        return {"profile_read": False, "message": loc.get("note")}
    return {"profile_read": True, "issues_found": loc.get("issues_detected", 0),
            "areas": [{"area": x["key"], "label": x["label"], "state": x["state"], "summary": x["summary"], "how_it_would_be_fixed": (x["fix"] or {}).get("mode")} for x in loc["areas"]],
            "write_gate": loc["gate"], "note": "States: ok, improve, missing, unknown. Use prepare_change to have a fix drafted for the owner."}


def _get_pending_changes(tc: ToolContext, a: PendingArgs) -> dict:
    res = pending_svc.list_pending(tc.ctx.db, tc.ctx.tenant, tc.ctx, category=a.category, include_attention=False, limit=40)
    return {"total": res["total"], "counts": res["counts"], "items": [{"id": i["key"], "kind": i["kind"], "category": i["category"], "title": i["title"], "status": i["status_label"],
                                                                        "risk": i["risk"], "preview": (i["after"] or "")[:200]} for i in res["items"][:15]]}


def _prepare_change(tc: ToolContext, a: PrepareArgs) -> dict:
    _need(tc, Role.admin)
    g = _gloc(tc, a.location_id)
    r = prepare_svc.prepare(tc.ctx.db, tc.ctx.tenant, g, a.area)
    out = {"status": r["status"], "message": r["message"], "reasons": r["reasons"][:4]}
    if r["action_id"]:
        item = next((i for i in pending_svc.list_pending(tc.ctx.db, tc.ctx.tenant, tc.ctx, limit=100)["items"] if i["id"] == r["action_id"]), None)
        if item:
            out["change"] = {"id": item["key"], "title": item["title"], "before": item["before"][:600], "after": item["after"][:800], "reason": item["reason"], "risk": item["risk"],
                             "status": item["status_label"], "can_approve": item["operations"]["approve"]["available"], "why_not": item["operations"]["approve"]["reason"]}
    return out


def _reviews_needing_reply(tc: ToolContext, a: ReviewsArgs) -> dict:
    g = _gloc(tc, a.location_id)
    if (why := privacy.block_reason(tc.provider_name)):
        return {"available": False, "message": privacy.BLOCKED_MESSAGE, "code": why}
    rows = tc.ctx.db.scalars(select(Review).where(Review.tenant_id == tc.ctx.tenant_id, Review.google_location_id == g.id, Review.google_reply_text.is_(None))
                             .order_by(Review.review_created_at.desc()).limit(a.limit)).all()
    return {"count": len(rows), "reviews": [{"review_id": str(r.id), "rating": r.rating, "text": privacy.redact((r.text or "")[:400]), "date": r.review_created_at.date().isoformat()} for r in rows]}


def _draft_review_reply(tc: ToolContext, a: ReplyArgs) -> dict:
    _need(tc, Role.admin)
    from app.api.v1 import reviews as reviews_api

    if privacy.block_reason(tc.provider_name):
        raise ToolError(privacy.BLOCKED_MESSAGE)
    try:
        d = reviews_api.generate_draft(a.review_id, tc.request, None, tc.ctx)
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc
    return {"status": "drafted", "message": "The reply is drafted and waits for the owner's approval. Nothing was published.", "draft": {"id": str(d.id), "body": d.body, "flags": d.flag_reasons, "needs_human": d.requires_human_handling}}


def _draft_google_post(tc: ToolContext, a: PostArgs) -> dict:
    _need(tc, Role.admin)
    from app.api.v1 import posts as posts_api

    g = _gloc(tc, a.location_id)
    try:
        out = posts_api.ai_draft(posts_api.AiDraftIn(google_location_id=g.id, topic=a.topic, kind=a.kind), tc.request, tc.ctx)
    except HTTPException as exc:
        raise ToolError(_detail(exc)) from exc
    return {"status": "drafted", "message": "The post is drafted and waits for the owner's approval. Nothing was published.", "post": {"id": str(out["id"]) if isinstance(out, dict) and "id" in out else None,
                                                                                                                                       "summary": (out.get("summary") if isinstance(out, dict) else None)}}


def _detail(exc: HTTPException) -> str:
    d = exc.detail
    return d if isinstance(d, str) else (d.get("message") if isinstance(d, dict) and d.get("message") else "That could not be done.")


TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("get_business_context", "Read what FlowQR verifiably knows about the business: its facts, its Google profile, reviews, recent posts and past decisions, and what is unknown.", LocationArg, _get_business_context, False),
    Tool("audit_profile", "Check the Google profile area by area (description, categories, services, hours, attributes, contacts...) and say which need improving and how each would be fixed.", LocationArg, _audit_profile, False),
    Tool("get_pending_changes", "List the changes, replies and posts that are waiting for the owner.", PendingArgs, _get_pending_changes, False),
    Tool("prepare_change", "Have FlowQR DRAFT the complete improvement for one profile area (for example a better description) and store it for the owner to review and approve. Nothing is published.", PrepareArgs, _prepare_change, True, Role.admin),
    Tool("list_reviews_needing_reply", "List recent reviews that have no reply yet.", ReviewsArgs, _reviews_needing_reply, False),
    Tool("draft_review_reply", "Draft a reply to one review for the owner to approve. Nothing is published.", ReplyArgs, _draft_review_reply, True, Role.admin),
    Tool("draft_google_post", "Draft a Google post for the owner to approve. Offers and events are only made from verified facts. Nothing is published.", PostArgs, _draft_google_post, True, Role.admin),
)}


def specs() -> list[dict]:
    """The tools as provider-neutral JSON schemas: {name, description, parameters}."""
    out = []
    for t in TOOLS.values():
        schema = t.args.model_json_schema()
        schema.pop("title", None)
        out.append({"name": t.name, "description": t.description, "parameters": schema, "prepares": t.prepares})
    return out


def run_tool(tc: ToolContext, name: str, raw_args: dict | None) -> dict:
    """Validate and run one tool. Returns {"ok": True, "result": ...} or {"ok": False, "error": ...}. Never raises for a model mistake."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"ok": False, "error": f"There is no tool called '{name}'. Available: {', '.join(TOOLS)}."}
    if ROLE_RANK[tc.ctx.role] < ROLE_RANK[tool.min_role]:
        return {"ok": False, "error": "Only an owner or admin can ask for this."}
    try:
        args = tool.args.model_validate(raw_args or {})
    except ValidationError as exc:
        return {"ok": False, "error": "Invalid arguments: " + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:4])}
    try:
        result = tool.handler(tc, args)
    except ToolError as exc:
        tc.ctx.db.rollback() if tool.prepares else None
        return {"ok": False, "error": str(exc)}
    except HTTPException as exc:
        return {"ok": False, "error": _detail(exc)}
    blob = json.dumps(result, default=str)
    if len(blob) > MAX_RESULT_CHARS:
        result = {"truncated": True, "excerpt": blob[:MAX_RESULT_CHARS]}
    return {"ok": True, "result": result}
