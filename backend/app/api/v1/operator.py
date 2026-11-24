"""FlowQR AI Business Operator API: the unified pending-work list, "prepare this improvement", edit and regenerate a prepared description, and ask the operator.

Nothing here approves or writes to Google. A prepared change is a normal `agent_action` (or reply draft, or post draft) that waits for a person; approval and execution stay on their existing
endpoints (`/agent/actions/{id}/approve`, `/reply-drafts/{id}/approve`, `/posts/{id}/approve`, ...), each with its own policy, consent, gate and read-back."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.autonomy_actions import _action, _gloc
from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.models import Role
from app.services import entitlements as ent
from app.services.agent import executor
from app.services.ai.base import AIUnavailable, get_provider
from app.services.ai_usage import metered
from app.services.audit import audit
from app.services.operator import changes as changes_svc
from app.services.operator import orchestrator, pending as pending_svc, prepare as prepare_svc
from app.services.operator import tools as tool_registry

router = APIRouter(prefix="/operator", tags=["operator"])


def _item_for_action(ctx: TenantContext, a) -> dict:
    gl = _gloc(ctx, a.google_location_id)
    return pending_svc.action_item(ctx.db, a, gl)


@router.get("/pending")
def pending(category: Literal["profile", "business_info", "reviews", "posts", "other"] | None = Query(None), attention: bool = Query(True), ctx: TenantContext = Depends(get_tenant_context)):
    """Everything waiting for a person (and, with `attention`, what failed or was blocked), from the tables that already hold it. Read-only."""
    out = pending_svc.list_pending(ctx.db, ctx.tenant, ctx, category=category, include_attention=attention)
    ctx.db.commit()
    return out


class PrepareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    google_location_id: uuid.UUID
    area: Literal["description", "categories", "services", "hours", "special_hours", "attributes", "contacts", "service_area"]


@router.post("/prepare")
def prepare(body: PrepareIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Have the AI draft the complete change for one profile area, or open the one already prepared. Stores a proposal; writes nothing to Google."""
    ent.require_feature(ctx.db, ctx.tenant_id, "autonomy")
    gl = _gloc(ctx, body.google_location_id)
    if not hit(f"operator-prepare:{ctx.tenant_id}", 12, 3600):
        raise HTTPException(status_code=429, detail="Preparing changes is limited to a few times an hour. Open the ones already prepared, or try again later.")
    res = prepare_svc.prepare(ctx.db, ctx.tenant, gl, body.area)
    change = None
    if res["action_id"]:
        a = _action(ctx, uuid.UUID(res["action_id"]))
        change = _item_for_action(ctx, a)
    audit(ctx.db, action="operator.prepare", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="google_location", entity_id=gl.id, meta={"area": body.area, "status": res["status"]}, ip=client_ip(request))
    ctx.db.commit()
    return {**res, "change": change}


class EditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)


def _wrap(fn):
    try:
        return fn()
    except changes_svc.ChangeError as exc:
        raise HTTPException(status_code=exc.status, detail=({"message": str(exc), "violations": exc.detail} if exc.detail else str(exc)))
    except (executor.ActionError,) as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/changes/{action_id}/edit")
def edit_change(action_id: uuid.UUID, body: EditIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Reword a prepared description. The old proposal is retired and the new text is a new proposal, checked against the Business Brain, waiting for approval."""
    ent.require_feature(ctx.db, ctx.tenant_id, "autonomy")
    a = _action(ctx, action_id)
    gl = _gloc(ctx, a.google_location_id)
    new = _wrap(lambda: changes_svc.edit_description(ctx.db, ctx.tenant, gl, a, body.text, user_id=ctx.user.id, role=ctx.role))
    audit(ctx.db, action="operator.edit", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="agent_action", entity_id=new.id, meta={"replaces": str(a.id)}, ip=client_ip(request))
    out = pending_svc.action_item(ctx.db, new, gl)
    ctx.db.commit()
    return out


@router.post("/changes/{action_id}/regenerate")
def regenerate_change(action_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    ent.require_feature(ctx.db, ctx.tenant_id, "autonomy")
    if not hit(f"operator-regen:{ctx.tenant_id}", 10, 3600):
        raise HTTPException(status_code=429, detail="New versions are limited to a few an hour.")
    a = _action(ctx, action_id)
    gl = _gloc(ctx, a.google_location_id)
    new = _wrap(lambda: changes_svc.regenerate_description(ctx.db, ctx.tenant, gl, a, user_id=ctx.user.id, role=ctx.role))
    audit(ctx.db, action="operator.regenerate", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="agent_action", entity_id=new.id, meta={"replaces": str(a.id)}, ip=client_ip(request))
    out = pending_svc.action_item(ctx.db, new, gl)
    ctx.db.commit()
    return out


@router.get("/tools")
def tools(ctx: TenantContext = Depends(get_tenant_context)):
    """What the operator can and cannot do, served from the registry the code enforces."""
    return {"tools": [{"name": s["name"], "description": s["description"], "prepares_a_draft": s["prepares"]} for s in tool_registry.specs()],
            "cannot": ["approve or publish anything", "write to Google", "read another business's data", "change a price, an offer or business facts on its own"]}


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=2, max_length=600)


@router.post("/ask")
def ask(body: AskIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Ask the operator to do something ("improve my profile", "reply to my reviews"). It uses the registered tools, prepares drafts for approval, and answers from what they returned."""
    ent.require_active(ctx.db, ctx.tenant_id)
    if not hit(f"operator-ask:{ctx.tenant_id}", 20, 3600):
        raise HTTPException(status_code=429, detail="You have asked the operator a lot this hour. Try again a little later.")
    try:
        provider = metered(get_provider(), ctx.db, ctx.tenant_id, "agent_draft", actor_user_id=ctx.user.id)
    except AIUnavailable:
        raise HTTPException(status_code=503, detail="The AI is not configured on this server.")
    tc = tool_registry.ToolContext(ctx=ctx, request=request, provider_name=getattr(provider, "name", None))
    run = orchestrator.run(tc, body.message, orchestrator.JsonPlanner(provider))
    keys: list[str] = []
    for e in run["events"]:
        r = e.result or {}
        if e.kind == "tool" and e.ok and e.prepares:
            if r.get("change"):
                keys.append(r["change"]["id"])
            if (r.get("draft") or {}).get("id"):
                keys.append(f"reply:{r['draft']['id']}")
            if (r.get("post") or {}).get("id"):
                keys.append(f"post:{r['post']['id']}")
    items = [i for i in pending_svc.list_pending(ctx.db, ctx.tenant, ctx, include_attention=True)["items"] if i["key"] in set(keys)]
    audit(ctx.db, action="operator.ask", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="tenant", entity_id=ctx.tenant_id,
          meta={"status": run["status"], "tools": [e.tool for e in run["events"] if e.kind == "tool"], "prepared": keys}, ip=client_ip(request))
    ctx.db.commit()
    out = {"status": run["status"], "answer": run["answer"], "reason": run.get("reason"), "reason_text": prepare_svc.AI_DOWN.get(run.get("reason") or "") if run.get("reason") else None,
           "steps": [{"tool": e.tool, "args": e.args, "ok": e.ok, "summary": e.summary, "prepares": e.prepares} for e in run["events"] if e.kind == "tool"], "changes": items}
    return out
