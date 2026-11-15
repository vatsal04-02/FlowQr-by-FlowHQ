"""Photo library + scheduler for one Google location (PRD: Photo Manager & Scheduler). See services/media.py for the workflow.

Anyone who can see the location may upload a photo into the library; only an owner or admin can approve it for Google, choose when it
goes, cancel or retry. What is shown as "on Google" always comes from Google itself."""
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.gbp import _call, _gloc
from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.models import GoogleLocation, Role, ScheduledMedia
from app.services import entitlements as ent
from app.services import media as svc
from app.services.audit import audit

router = APIRouter(prefix="/gbp/{google_location_id}/library", tags=["photos"])


def _loc_only(ctx: TenantContext, gid: uuid.UUID) -> GoogleLocation:
    """The location without requiring an active Google connection (the library works while Google is being reconnected)."""
    gl = ctx.db.scalar(select(GoogleLocation).where(GoogleLocation.id == gid, GoogleLocation.tenant_id == ctx.tenant_id))
    if not gl or not gl.selected or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Google location not found")
    return gl


def _item(ctx: TenantContext, gl: GoogleLocation, mid: uuid.UUID, *, lock: bool = False) -> ScheduledMedia:
    q = select(ScheduledMedia).where(ScheduledMedia.id == mid, ScheduledMedia.tenant_id == ctx.tenant_id, ScheduledMedia.google_location_id == gl.id)
    m = ctx.db.scalar(q.with_for_update() if lock else q)
    if not m:
        raise HTTPException(status_code=404, detail="Photo not found")
    return m


def _wrap(fn):
    try:
        return fn()
    except svc.MediaError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


@router.get("")
def library(google_location_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    ent.require_feature(ctx.db, ctx.tenant_id, "gbp_media")
    gl = _loc_only(ctx, google_location_id)
    rows = ctx.db.scalars(select(ScheduledMedia).where(ScheduledMedia.tenant_id == ctx.tenant_id, ScheduledMedia.google_location_id == gl.id,
                                                       ScheduledMedia.status != "canceled").order_by(ScheduledMedia.created_at.desc()).limit(200)).all()
    ctx.db.commit()
    return {"items": [svc.out(m) for m in rows], "categories": svc.CATEGORIES, "timezone": ctx.tenant.timezone,
            "rules": {"formats": ["JPG", "PNG"], "min_bytes": svc.MIN_BYTES, "max_bytes": svc.MAX_BYTES, "min_edge": svc.MIN_EDGE, "recommended_edge": svc.RECOMMENDED_EDGE}}


@router.get("/coverage")
def coverage(google_location_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    """Which photo categories Google already shows for this location (read live from Google), and which to add next."""
    ent.require_feature(ctx.db, ctx.tenant_id, "gbp_media")
    gl, conn = _gloc(ctx, google_location_id)
    pending = [c for (c,) in ctx.db.execute(select(ScheduledMedia.category).where(ScheduledMedia.tenant_id == ctx.tenant_id, ScheduledMedia.google_location_id == gl.id,
                                                                                    ScheduledMedia.status.in_(("awaiting_approval", "scheduled", "publishing"))))]
    ctx.db.commit()
    google = _call(ctx, conn, lambda p, t: p.list_media(t, gl.google_account_name, gl.google_location_name))
    counts: dict[str, int] = {}
    for m in google:
        counts[m.get("category") or "UNKNOWN"] = counts.get(m.get("category") or "UNKNOWN", 0) + 1
    return {"on_google": counts, "total_on_google": len(google), "suggestions": svc.suggestions(ctx.tenant.category, list(counts), pending),
            "note": "Read from Google just now. Photos can take 24–48 hours to appear on Google, and only appear once the profile is verified."}


@router.post("", status_code=201)
async def upload(google_location_id: uuid.UUID, request: Request, category: str = Query(max_length=24), description: str | None = Query(None, max_length=300),
                 file_name: str | None = Query(None, max_length=200), ctx: TenantContext = Depends(get_tenant_context)):
    """Add a photo to the library. Send the JPG/PNG bytes as the request body. It waits for an owner or admin to approve it."""
    ent.require_active(ctx.db, ctx.tenant_id)
    ent.require_feature(ctx.db, ctx.tenant_id, "gbp_media")
    gl = _loc_only(ctx, google_location_id)
    if not hit(f"photo-upload:{ctx.tenant_id}", 60, 3600):
        raise HTTPException(status_code=429, detail="Too many uploads this hour. Try again later.")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > svc.MAX_BYTES:
        raise HTTPException(status_code=413, detail="Google accepts photos up to 5 MB.")
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > svc.MAX_BYTES:
            raise HTTPException(status_code=413, detail="Google accepts photos up to 5 MB.")
    m, warnings = _wrap(lambda: svc.create(ctx.db, tenant_id=ctx.tenant_id, gloc=gl, data=bytes(raw), category=category.upper(),
                                           description=description, file_name=file_name, user_id=ctx.user.id))
    audit(ctx.db, action="photo.upload", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_media", entity_id=m.id,
          meta={"category": m.category, "bytes": m.size_bytes, "size": f"{m.width}x{m.height}"}, ip=client_ip(request))
    ctx.db.commit()
    return {**svc.out(m), "warnings": warnings}


@router.get("/{media_id}/image")
def image(google_location_id: uuid.UUID, media_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    gl = _loc_only(ctx, google_location_id)
    m = _item(ctx, gl, media_id)
    data = ctx.db.scalar(select(ScheduledMedia.data).where(ScheduledMedia.id == m.id))
    ctx.db.commit()
    return Response(data, media_type=m.content_type, headers={"Cache-Control": "private, max-age=3600"})


class EditIn(BaseModel):
    category: str | None = Field(default=None, max_length=24)
    description: str | None = Field(default=None, max_length=300)


@router.patch("/{media_id}")
def edit(google_location_id: uuid.UUID, media_id: uuid.UUID, body: EditIn, ctx: TenantContext = Depends(get_tenant_context)):
    gl = _loc_only(ctx, google_location_id)
    m = _item(ctx, gl, media_id, lock=True)
    if m.status not in ("awaiting_approval", "failed"):
        raise HTTPException(status_code=409, detail="Only a photo that is waiting for approval (or failed) can be changed.")
    if body.category is not None:
        cat = body.category.upper()
        data = ctx.db.scalar(select(ScheduledMedia.data).where(ScheduledMedia.id == m.id))
        _wrap(lambda: svc.inspect(data, cat))  # e.g. a small image allowed as a logo is not allowed as a normal photo
        m.category = cat
    if body.description is not None:
        m.description = body.description.strip() or None
    if m.status == "failed":  # a changed photo needs approving again
        m.status = "awaiting_approval"
    ctx.db.commit()
    return svc.out(m)


class ApproveIn(BaseModel):
    scheduled_for: datetime | None = None  # naive = the business's local time; omit to send at the next run (within a minute)


@router.post("/{media_id}/approve")
def approve(google_location_id: uuid.UUID, media_id: uuid.UUID, body: ApproveIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    ent.require_active(ctx.db, ctx.tenant_id)
    gl = _loc_only(ctx, google_location_id)
    m = _item(ctx, gl, media_id, lock=True)
    when = body.scheduled_for
    if when is not None and when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo(ctx.tenant.timezone or "Asia/Kolkata"))
    _wrap(lambda: svc.approve(m, user_id=ctx.user.id, when=when))
    audit(ctx.db, action="photo.approve", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_media", entity_id=m.id,
          meta={"category": m.category, "scheduled_for": m.scheduled_for.isoformat()}, ip=client_ip(request))
    ctx.db.commit()
    return svc.out(m)


@router.post("/{media_id}/cancel")
def cancel(google_location_id: uuid.UUID, media_id: uuid.UUID, ctx: TenantContext = Depends(require_role(Role.admin))):
    gl = _loc_only(ctx, google_location_id)
    m = _item(ctx, gl, media_id, lock=True)
    _wrap(lambda: svc.move(m, "canceled"))
    audit(ctx.db, action="photo.cancel", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_media", entity_id=m.id)
    ctx.db.commit()
    return svc.out(m)


@router.post("/{media_id}/retry")
def retry(google_location_id: uuid.UUID, media_id: uuid.UUID, ctx: TenantContext = Depends(require_role(Role.admin))):
    ent.require_active(ctx.db, ctx.tenant_id)
    gl = _loc_only(ctx, google_location_id)
    m = _item(ctx, gl, media_id, lock=True)
    _wrap(lambda: svc.retry(m))
    audit(ctx.db, action="photo.retry", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_media", entity_id=m.id)
    ctx.db.commit()
    return svc.out(m)


@router.post("/{media_id}/check")
def check(google_location_id: uuid.UUID, media_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    """Ask Google now whether it is serving a published photo yet."""
    gl, conn = _gloc(ctx, google_location_id)
    m = _item(ctx, gl, media_id, lock=True)
    if m.status != "published":
        raise HTTPException(status_code=409, detail="Only a photo Google has accepted can be checked.")
    _call(ctx, conn, lambda p, t: svc.check_processing(ctx.db, m, provider=p))
    ctx.db.commit()
    return svc.out(m)
