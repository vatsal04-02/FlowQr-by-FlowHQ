"""Settings pages' data: honest integration status, AI usage and model health, the tenant's own audit log.

Status words are fixed and mean exactly one thing:
  connected       a real call to the service has succeeded for this business
  attention       configured, but the service is refusing or the grant was lost; says why
  not_connected   configured on the server, nothing connected for this business yet
  setup_required  something the platform owner must configure first (keys, approval)
  not_available   credentials exist but FlowQR has no working adapter for it yet
"""
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select

from app.core.config import settings
from app.core.deps import TenantContext, get_tenant_context, require_role
from app.models import AIGenerationLog, AuditLog, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Role, User
from app.models.base import utcnow
from app.services import entitlements as ent
from app.services.ai import health as ai_health
from app.services.ai_usage import month_start, usage_this_month

router = APIRouter(prefix="/workspace", tags=["workspace"])


def _google(ctx: TenantContext) -> dict:
    base = {"id": "google", "label": "Google Business Profile", "href": "/google"}
    if not settings.google_configured:
        return {**base, "status": "setup_required", "detail": "Google OAuth credentials are not configured on this server.", "steps": ["Create an OAuth client and set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET (see docs/GOOGLE_SETUP.md)."]}
    conns = ctx.db.scalars(select(GoogleConnection).where(GoogleConnection.tenant_id == ctx.tenant_id, GoogleConnection.status != GoogleConnectionStatus.disconnected)).all()
    if not conns:
        return {**base, "status": "not_connected", "detail": "No Google account is connected.", "steps": ["Open Google Business → Overview and press Connect Google."]}
    locs = ctx.db.scalar(select(func.count()).select_from(GoogleLocation).where(GoogleLocation.tenant_id == ctx.tenant_id, GoogleLocation.selected.is_(True))) or 0
    c = conns[0]
    if c.status == GoogleConnectionStatus.revoked:
        return {**base, "status": "attention", "detail": "Google access was lost. Reconnect to continue.", "steps": ["Press Reconnect on the Google connection page."]}
    if c.api_access == "api_disabled":
        return {**base, "status": "setup_required", "detail": c.last_error or "A Business Profile API is not enabled on FlowQR's Google project.", "steps": ["Platform owner: enable the Business Profile APIs in Google Cloud Console (docs/GOOGLE_SETUP.md)."]}
    if c.api_access == "awaiting_approval":
        return {**base, "status": "setup_required", "detail": c.last_error or "Google has not approved FlowQR for Business Profile API access yet.", "steps": ["Platform owner: submit or follow up the Basic API Access application."]}
    if c.status == GoogleConnectionStatus.error:
        return {**base, "status": "attention", "detail": c.last_error or "Google returned an error.", "steps": ["Open the Google connection page for details."]}
    if c.api_access == "approved" and locs:
        return {**base, "status": "connected", "detail": f"{locs} location{'s' if locs != 1 else ''} connected; Google answered our last request.", "steps": []}
    if c.api_access == "approved":
        return {**base, "status": "attention", "detail": "Your Google account is connected but no location is selected (or none was found on it). This is not a working business connection.",
                "steps": ["Select a location, or connect another Google account that manages one."]}
    return {**base, "status": "attention", "detail": "Connected, but Google has not confirmed access yet.", "steps": ["Press Re-check on the Google connection page."]}


@router.get("/getting-started")
def getting_started(ctx: TenantContext = Depends(get_tenant_context)):
    """The owner's checklist, computed from what actually exists (see services/onboarding.py). No sample data, no saved flags."""
    from app.services import onboarding

    out = onboarding.steps(ctx.db, ctx.tenant_id, ctx.user)
    ctx.db.commit()
    return out


@router.get("/integrations")
def integrations(ctx: TenantContext = Depends(get_tenant_context)):
    ai = {"id": "ai", "label": "AI provider", "href": "/settings/ai"}
    if not settings.ai_configured:
        ai |= {"status": "setup_required", "detail": "No AI provider key is configured on this server.", "steps": ["Set the AI provider variables in the server .env."]}
    else:
        deg = ai_health.current()
        ai |= ({"status": "attention", "detail": f"The AI provider is paused: {deg['message']}", "steps": ["It resumes automatically."]} if deg
               else {"status": "connected", "detail": f"Configured ({settings.ai_provider}). Health is judged from real requests.", "steps": []})
    pay = {"id": "razorpay", "label": "Payments (Razorpay)", "href": "/subscription"}
    pay |= ({"status": "connected", "detail": f"Keys configured ({settings.razorpay_mode} mode).", "steps": []} if settings.razorpay_configured else
            {"status": "setup_required", "detail": "Razorpay keys are not configured, so plans cannot be purchased online.", "steps": ["Set RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET and RAZORPAY_WEBHOOK_SECRET."]})
    mail = {"id": "email", "label": "Email", "href": None}
    mail |= ({"status": "connected", "detail": "SMTP is configured.", "steps": []} if settings.smtp_host else {"status": "setup_required", "detail": "SMTP is not configured: invitations and password resets cannot be emailed.", "steps": ["Set SMTP_HOST and credentials."]})

    def unbuilt(id_, label, have, steps, what):
        return {"id": id_, "label": label, "href": None, "status": "not_available" if have else "setup_required",
                "detail": (f"Credentials are present, but FlowQR has no working {what} integration yet, so nothing is simulated." if have else f"Not configured. {what[0].upper() + what[1:]} is a planned release."), "steps": steps}
    def _rank():
        if settings.rank_provider == "google_places" and settings.rank_provider_key:
            return {"id": "rank_provider", "label": "Local rank tracking (Google Places)", "href": "/gbp/rank", "status": "connected",
                    "detail": f"Key configured. Each business may spend {settings.rank_monthly_check_cap} billed checks a month.", "steps": []}
        if settings.rank_provider and settings.rank_provider != "google_places":
            return {"id": "rank_provider", "label": "Local rank provider", "href": None, "status": "not_available",
                    "detail": f"RANK_PROVIDER={settings.rank_provider!r} isn't supported, so nothing is simulated. Use google_places.", "steps": ["Set RANK_PROVIDER=google_places and RANK_PROVIDER_KEY."]}
        return {"id": "rank_provider", "label": "Local rank tracking (Google Places)", "href": None, "status": "setup_required",
                "detail": "Not configured. Local rank tracking needs a Places API (New) key.",
                "steps": ["Enable Places API (New), link billing, create a restricted key, then set RANK_PROVIDER=google_places and RANK_PROVIDER_KEY."]}
    items = [_google(ctx), ai, pay, mail,
             unbuilt("meta", "Facebook & Instagram (Meta)", bool(settings.meta_app_id and settings.meta_app_secret), ["Create a Meta app, complete App Review for publishing permissions, then set META_APP_ID / META_APP_SECRET."], "Meta publishing"),
             unbuilt("whatsapp", "WhatsApp Business Platform", bool(settings.whatsapp_phone_number_id and settings.whatsapp_access_token), ["Register with the official WhatsApp Business Platform, get approved templates, then set WHATSAPP_PHONE_NUMBER_ID / WHATSAPP_ACCESS_TOKEN."], "WhatsApp messaging"),
             _rank()]
    return {"integrations": items}


@router.get("/ai-usage")
def ai_usage(ctx: TenantContext = Depends(get_tenant_context)):
    e = ent.for_tenant(ctx.db, ctx.tenant_id)
    since = month_start()
    by_kind = ctx.db.execute(select(AIGenerationLog.kind, AIGenerationLog.status, func.count()).where(AIGenerationLog.tenant_id == ctx.tenant_id, AIGenerationLog.created_at >= since, ctx.scope(AIGenerationLog.location_id) if ctx.restricted else AIGenerationLog.tenant_id == ctx.tenant_id)
                             .group_by(AIGenerationLog.kind, AIGenerationLog.status)).all()
    daily = ctx.db.execute(select(func.date(AIGenerationLog.created_at), func.count()).where(AIGenerationLog.tenant_id == ctx.tenant_id, AIGenerationLog.created_at >= utcnow() - timedelta(days=30)).group_by(func.date(AIGenerationLog.created_at)).order_by(func.date(AIGenerationLog.created_at))).all()
    errors = ctx.db.execute(select(AIGenerationLog.kind, AIGenerationLog.error, AIGenerationLog.created_at).where(AIGenerationLog.tenant_id == ctx.tenant_id, AIGenerationLog.status != "ok").order_by(desc(AIGenerationLog.created_at)).limit(10)).all()
    deg = ai_health.current()
    return {"used_this_month": usage_this_month(ctx.db, ctx.tenant_id), "monthly_limit": e.monthly_ai_generations, "plan": e.plan, "month_started": since.isoformat(),
            "provider": {"configured": settings.ai_configured, "name": settings.ai_provider if settings.ai_configured else None, "model": (settings.gemini_model if settings.ai_provider == "gemini" else None) if settings.ai_configured else None,
                         "paused": None if not deg else {"code": deg["code"], "message": deg["message"]}},
            "by_kind": [{"kind": k, "status": s, "count": n} for k, s, n in by_kind], "daily": [{"day": str(d), "count": n} for d, n in daily],
            "recent_problems": [{"kind": k, "error": (err or "")[:160], "at": at} for k, err, at in errors],
            "note": "Each draft, fact-check and rewrite counts as one use. When the plan limit is reached, customers write their own words and drafts pause."}


@router.get("/audit-log")
def audit_log(limit: int = Query(50, ge=1, le=200), before: str | None = None, action: str | None = Query(None, max_length=64), ctx: TenantContext = Depends(require_role(Role.admin))):
    """This business's own audit trail (owners and admins). Tenant-scoped by the database itself as well as here."""
    q = select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id).where(AuditLog.tenant_id == ctx.tenant_id)
    if action:
        q = q.where(AuditLog.action.like(action.replace("%", "") + "%"))
    if before:
        try:
            from datetime import datetime
            q = q.where(AuditLog.created_at < datetime.fromisoformat(before))
        except ValueError:
            pass
    rows = ctx.db.execute(q.order_by(desc(AuditLog.created_at)).limit(limit + 1)).all()
    page = rows[:limit]
    return {"entries": [{"id": str(a.id), "action": a.action, "by": email, "entity_type": a.entity_type, "entity_id": a.entity_id, "meta": a.meta, "ip": a.ip, "at": a.created_at} for a, email in page],
            "next_before": page[-1][0].created_at.isoformat() if len(rows) > limit else None}
