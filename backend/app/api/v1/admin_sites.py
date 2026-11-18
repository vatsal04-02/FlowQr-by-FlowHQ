"""Platform-admin website builder: create a website for a business, edit it, upload images, preview, publish, suspend, record the commercial status and read the enquiries.

Every route requires a verified platform administrator. All of them answer 409 `sites_disabled` while SITES_ENABLED is false (except the two that tell the admin screen whether the feature is on).
The business never needs a FlowQR login: this is administrator-managed. See services/sites/service.py for the rules."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse

from app.core.deps import AuthContext, require_platform_admin
from app.core.rate_limit import client_ip, hit
from app.models import Tenant
from app.schemas.sites import AssetPatchIn, CommercialIn, EnquiryStatusIn, PublishIn, ReasonIn, RollbackIn, SiteContentIn, SiteCreateIn, SlugIn, TemplateIn
from app.services.sites import catalog, media
from app.services.sites import service as svc

router = APIRouter(prefix="/admin", tags=["platform-admin"])


def _run(ctx: AuthContext, fn):
    """Run one step; a refusal undoes it and answers with its reason, success commits."""
    try:
        out = fn()
    except svc.SiteError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    ctx.db.commit()
    return out


def _site(ctx: AuthContext, site_id: uuid.UUID):
    try:
        return svc.get(ctx.db, site_id)
    except svc.SiteError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail())


def _enabled() -> None:
    try:
        svc.require_enabled()
    except svc.SiteError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail())


@router.get("/sites/config")
def config(ctx: AuthContext = Depends(require_platform_admin)):
    return svc.public_config()


@router.get("/sites/templates")
def templates(ctx: AuthContext = Depends(require_platform_admin)):
    """Templates, section types and their fields: the editor draws its forms from this."""
    return catalog.catalogue()


@router.get("/tenants/{tenant_id}/site")
def site_of_business(tenant_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    t = ctx.db.get(Tenant, tenant_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Business not found")
    s = svc.get_by_tenant(ctx.db, tenant_id)
    return {"enabled": svc.public_config()["enabled"], "website_interest": t.website_interest, "website_url": t.website, "suggested_template": catalog.suggest_template(t.category), "suggested_slug": svc.suggest_available_slug(ctx.db, t.name, tenant_id) if s is None else None,
            "site": svc.serialize(ctx.db, s, full=False) if s else None}


@router.post("/tenants/{tenant_id}/site", status_code=201)
def create_site(tenant_id: uuid.UUID, body: SiteCreateIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    t = ctx.db.get(Tenant, tenant_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Business not found")
    if not hit(f"admin-site-create:{ctx.user.id}", 30, 3600):
        raise HTTPException(status_code=429, detail="Too many websites created. Try again later.")
    site = _run(ctx, lambda: svc.create_site(ctx.db, admin=ctx.user, tenant=t, template_key=body.template_key, slug=body.site_slug, commercial_status=body.commercial_status,
                                             commercial_reason=body.commercial_reason, billing_period=body.billing_period, paid_until=body.paid_until, ip=client_ip(request)))
    return svc.serialize(ctx.db, site)


@router.get("/sites/slug-check")
def slug_check(slug: str = Query(max_length=60), tenant_id: uuid.UUID | None = None, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    problem = svc.slug_availability(ctx.db, slug.strip().lower(), tenant_id)
    return {"slug": slug, "available": problem is None, "problem": problem}


@router.get("/sites/{site_id}")
def get_site(site_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    return svc.serialize(ctx.db, _site(ctx, site_id))


@router.put("/sites/{site_id}/content")
def save_content(site_id: uuid.UUID, body: SiteContentIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    s = _site(ctx, site_id)
    _run(ctx, lambda: svc.save_content(ctx.db, admin=ctx.user, site=s, content=body.content, base_version=body.base_version, ip=client_ip(request)))
    return svc.serialize(ctx.db, s)


@router.post("/sites/{site_id}/template")
def change_template(site_id: uuid.UUID, body: TemplateIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    s = _site(ctx, site_id)
    _run(ctx, lambda: svc.change_template(ctx.db, admin=ctx.user, site=s, template_key=body.template_key, ip=client_ip(request)))
    return svc.serialize(ctx.db, s)


@router.post("/sites/{site_id}/slug")
def change_slug(site_id: uuid.UUID, body: SlugIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    s = _site(ctx, site_id)
    _run(ctx, lambda: svc.change_slug(ctx.db, admin=ctx.user, site=s, new_slug=body.site_slug.strip().lower(), ip=client_ip(request)))
    return svc.serialize(ctx.db, s)


# ---------------------------------------------------------------------------------------------------------------- images
@router.post("/sites/{site_id}/assets", status_code=201)
async def upload_asset(site_id: uuid.UUID, request: Request, kind: str = Query("photo", pattern="^(photo|logo)$"), alt_text: str = Query("", max_length=200),
                       ctx: AuthContext = Depends(require_platform_admin)):
    """Send the image bytes as the request body. The file is judged by its content, re-encoded and stripped of metadata; see services/sites/media.py."""
    _enabled()
    s = _site(ctx, site_id)
    if not hit(f"admin-site-upload:{ctx.user.id}", 120, 3600):
        raise HTTPException(status_code=429, detail="Too many uploads this hour. Try again later.")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > media.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail={"code": "too_large", "message": "Images can be up to 8 MB."})
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > media.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail={"code": "too_large", "message": "Images can be up to 8 MB."})
    a, created = _run(ctx, lambda: svc.upload_asset(ctx.db, admin=ctx.user, site=s, raw=bytes(raw), kind=kind, alt_text=alt_text, ip=client_ip(request)))
    return {"id": a.id, "kind": a.kind, "width": a.width, "height": a.height, "size_bytes": a.size_bytes, "alt_text": a.alt_text, "created": created}


@router.get("/sites/{site_id}/assets/{asset_id}/file")
def asset_file(site_id: uuid.UUID, asset_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    s = _site(ctx, site_id)
    try:
        a = svc.get_asset(ctx.db, s, asset_id)
    except svc.SiteError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    return Response(bytes(a.data), media_type="image/webp", headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.patch("/sites/{site_id}/assets/{asset_id}")
def patch_asset(site_id: uuid.UUID, asset_id: uuid.UUID, body: AssetPatchIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    s = _site(ctx, site_id)
    a = _run(ctx, lambda: svc.update_asset(ctx.db, admin=ctx.user, site=s, asset_id=asset_id, alt_text=body.alt_text, sort_order=body.sort_order, ip=client_ip(request)))
    return {"id": a.id, "alt_text": a.alt_text, "sort_order": a.sort_order}


@router.delete("/sites/{site_id}/assets/{asset_id}", status_code=204)
def delete_asset(site_id: uuid.UUID, asset_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    s = _site(ctx, site_id)
    _run(ctx, lambda: svc.delete_asset(ctx.db, admin=ctx.user, site=s, asset_id=asset_id, ip=client_ip(request)))


# ---------------------------------------------------------------------------------------------------------------- preview and lifecycle
@router.get("/sites/{site_id}/preview", response_class=HTMLResponse)
def preview(site_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    """The DRAFT as one self-contained page (images inlined, no scripts, noindex). The admin screen shows it in a sandboxed frame at desktop and phone width."""
    _enabled()
    s = _site(ctx, site_id)
    return HTMLResponse(svc.preview_html(ctx.db, s), headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "X-Content-Type-Options": "nosniff"})


@router.post("/sites/{site_id}/publish")
def publish(site_id: uuid.UUID, body: PublishIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    s = _site(ctx, site_id)
    if not hit(f"admin-site-publish:{ctx.user.id}", 60, 3600):
        raise HTTPException(status_code=429, detail="Too many publishes. Try again later.")
    try:
        svc.publish(ctx.db, admin=ctx.user, site=s, note=body.note, ip=client_ip(request))
    except svc.SiteError as exc:
        ctx.db.rollback() if exc.code != "publish_failed" else None  # a failed attempt was already committed on record by the service
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    ctx.db.commit()
    return svc.serialize(ctx.db, s)


@router.post("/sites/{site_id}/unpublish")
def unpublish(site_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    s = _site(ctx, site_id)
    _run(ctx, lambda: svc.unpublish(ctx.db, admin=ctx.user, site=s, ip=client_ip(request)))
    return svc.serialize(ctx.db, s)


@router.post("/sites/{site_id}/suspend")
def suspend(site_id: uuid.UUID, body: ReasonIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    s = _site(ctx, site_id)
    _run(ctx, lambda: svc.suspend(ctx.db, admin=ctx.user, site=s, reason=body.reason, ip=client_ip(request)))
    return svc.serialize(ctx.db, s)


@router.post("/sites/{site_id}/unsuspend")
def unsuspend(site_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    s = _site(ctx, site_id)
    _run(ctx, lambda: svc.unsuspend(ctx.db, admin=ctx.user, site=s, ip=client_ip(request)))
    return svc.serialize(ctx.db, s)


@router.post("/sites/{site_id}/rollback")
def rollback(site_id: uuid.UUID, body: RollbackIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    s = _site(ctx, site_id)
    try:
        svc.rollback(ctx.db, admin=ctx.user, site=s, revision=body.revision, ip=client_ip(request))
    except svc.SiteError as exc:
        ctx.db.rollback() if exc.code != "publish_failed" else None
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    ctx.db.commit()
    return svc.serialize(ctx.db, s)


@router.post("/sites/{site_id}/commercial")
def commercial(site_id: uuid.UUID, body: CommercialIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    s = _site(ctx, site_id)
    _run(ctx, lambda: svc.set_commercial(ctx.db, admin=ctx.user, site=s, status=body.status, reason=body.reason, billing_period=body.billing_period, paid_until=body.paid_until, ip=client_ip(request)))
    return svc.serialize(ctx.db, s)


@router.delete("/sites/{site_id}", status_code=204)
def delete_site(site_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    s = _site(ctx, site_id)
    _run(ctx, lambda: svc.delete_site(ctx.db, admin=ctx.user, site=s, ip=client_ip(request)))


# ---------------------------------------------------------------------------------------------------------------- enquiries
@router.get("/sites/{site_id}/enquiries")
def enquiries(site_id: uuid.UUID, status: str | None = Query(None, pattern="^(new|contacted|resolved|spam)$"), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
              ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    s = _site(ctx, site_id)
    total, rows = svc.list_enquiries(ctx.db, s, status, limit, offset)
    return {"total": total, "items": [{"id": e.id, "name": e.name, "phone": e.phone, "email": e.email, "message": e.message, "status": e.status, "received_at": e.created_at,
                                        "consent_at": e.consent_at, "contacted_at": e.contacted_at, "resolved_at": e.resolved_at} for e in rows]}


@router.patch("/sites/{site_id}/enquiries/{enquiry_id}")
def enquiry_status(site_id: uuid.UUID, enquiry_id: uuid.UUID, body: EnquiryStatusIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    _enabled()
    s = _site(ctx, site_id)
    e = _run(ctx, lambda: svc.set_enquiry_status(ctx.db, admin=ctx.user, site=s, enquiry_id=enquiry_id, status=body.status, ip=client_ip(request)))
    return {"id": e.id, "status": e.status, "contacted_at": e.contacted_at, "resolved_at": e.resolved_at}


@router.get("/sites/{site_id}/enquiries.csv")
def enquiries_csv(site_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Every enquiry of this website as a spreadsheet. Audited; cells that could run as a formula are neutralised."""
    _enabled()
    s = _site(ctx, site_id)
    if not hit(f"admin-site-enq-export:{ctx.user.id}", 20, 3600):
        raise HTTPException(status_code=429, detail="Too many exports. Try again later.")
    body = _run(ctx, lambda: svc.enquiries_csv(ctx.db, admin=ctx.user, site=s, ip=client_ip(request)))
    return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="enquiries-{s.site_slug}.csv"', "Cache-Control": "private, no-store"})
