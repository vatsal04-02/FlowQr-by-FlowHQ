"""QR customisation and downloads for a business: brand style, logo, preview and bulk export.

What a QR code ENCODES is never decided here: it is always the permanent FlowQR URL of a card (`/c/{token}`) or a campaign
(`/r/{public_id}`). These endpoints only change how codes are drawn, and every non-default style is checked by decoding
its rendering before it is saved or served (services/qr_style.py)."""
import csv
import io
import re
import uuid
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.models import Location, QRCard, QRStyle, ReviewCampaign, Role
from app.schemas.qr import BulkIn, QRStyleIn, QRStyleOut
from app.services import poster as poster_svc
from app.services import qr_style as qs
from app.services.audit import audit
from app.services.qr import campaign_url, card_qr_url, permanent_url_problem

router = APIRouter(prefix="/qr", tags=["qr"])
MIME = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf"}
RENDER = {"png": qs.render_png, "svg": qs.render_svg, "pdf": qs.render_pdf}
MAX_BULK = 200
MAX_BULK_POSTER_FILES = 50  # each poster file is ~1 MB (the approved artwork); a print sheet holds any number
SAMPLE_TOKEN = "PREVIEW-not-a-real-code0"  # same length as a real card token, so the sample has the same density as real codes


def tenant_style(db: Session, tenant_id: uuid.UUID) -> tuple[dict, bytes | None]:
    """(style, logo) saved for the tenant; the plain FlowQR style if none."""
    row = db.scalar(select(QRStyle).where(QRStyle.tenant_id == tenant_id))
    if not row:
        return dict(qs.DEFAULT_STYLE), None
    return {**qs.DEFAULT_STYLE, **(row.style or {})}, row.logo_png


def style_for(db: Session, tenant_id: uuid.UUID, override: dict | None = None) -> tuple[dict, bytes | None]:
    """The tenant's style, or a campaign's own style on top of the tenant's logo."""
    style, logo = tenant_style(db, tenant_id)
    return ({**qs.DEFAULT_STYLE, **override}, logo) if override else (style, logo)


def qr_file(url: str, fmt: str, style: dict, logo: bytes | None, *, size_px: int | None = None) -> tuple[bytes, bool]:
    """Render `url` in `fmt`. Returns (bytes, style_applied): an unscannable style is replaced by the plain one, never served."""
    if fmt not in RENDER:
        raise HTTPException(status_code=404, detail="Unsupported format")
    safe, safe_logo, applied = qs.safe_style(url, style, logo)
    return RENDER[fmt](url, safe, safe_logo, size_px=size_px), applied


def qr_response(url: str, fmt: str, style: dict, logo: bytes | None, filename: str, *, size_px: int | None = None) -> Response:
    body, applied = qr_file(url, fmt, style, logo, size_px=size_px)
    return Response(body, media_type=MIME[fmt], headers={
        "Content-Disposition": f'attachment; filename="{filename}.{fmt}"',
        "X-FlowQR-Style": "applied" if applied else "fallback-plain",  # fallback: the saved style failed the scan check
        "Cache-Control": "private, no-store"})


def print_blocker() -> str | None:
    """Why codes must not be printed from this server right now (not a permanent public HTTPS domain), or None."""
    return permanent_url_problem()


def require_print_domain() -> None:
    """Raise 409 when the public address is localhost, plain http, a bare IP or a temporary tunnel. Used for every batch / print-grade export."""
    problem = print_blocker()
    if problem:
        raise HTTPException(status_code=409, detail={"code": "print_domain_not_permanent", "message": problem})


POSTER_MIME = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf"}


def poster_file(url: str, fmt: str, *, scale: int = 1, size: str = "ref") -> bytes:
    """The approved poster with `url` as its QR code, in `fmt`. Raises 404 for an unknown format and 500 if the code could not be proven scannable."""
    if fmt not in POSTER_MIME:
        raise HTTPException(status_code=404, detail="Unsupported format")
    try:
        if fmt == "png":
            return poster_svc.poster_png(url, scale=scale)
        if fmt == "svg":
            return poster_svc.poster_svg(url)
        return poster_svc.poster_pdf(url, size=size)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except poster_svc.PosterError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def poster_response(url: str, fmt: str, filename: str, *, scale: int = 1, size: str = "ref") -> Response:
    """Download of one poster. In staging/production a non-permanent public address blocks it; elsewhere it is allowed (so the owner can
    try it out) and flagged with a header and a note the UI shows."""
    problem = permanent_url_problem(url)  # judged on the address this poster actually encodes (a card's, or a campaign's), not only on the card base
    if problem and settings.hardened:
        raise HTTPException(status_code=409, detail={"code": "print_domain_not_permanent", "message": problem})
    body = poster_file(url, fmt, scale=scale, size=size)
    headers = {"Content-Disposition": f'attachment; filename="{filename}-poster.{fmt}"', "X-FlowQR-Verified": "decoded", "Cache-Control": "private, no-store"}
    if problem:
        headers["X-FlowQR-Not-For-Print"] = "public address is not permanent"
    return Response(body, media_type=POSTER_MIME[fmt], headers=headers)


def slug(text: str, fallback: str = "qr") -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or fallback


def _out(db: Session, tenant_id: uuid.UUID) -> QRStyleOut:
    style, logo = tenant_style(db, tenant_id)
    return QRStyleOut(style=QRStyleIn.model_validate(style), has_logo=logo is not None, is_default=qs.is_plain(qs.effective_style(style, bool(logo))),
                      verification="decoded" if qs.decoder_available() else "rules_only")


def _sample_url() -> str:
    from app.services.qr import card_url

    return card_url(SAMPLE_TOKEN)


def check_scannable(url: str, style: dict, logo: bytes | None) -> None:
    """422 unless the styled rendering of `url` decodes back to `url`."""
    if qs.scannable(url, style, logo) is False:
        raise HTTPException(status_code=422, detail={"code": "qr_not_scannable", "message":
                            "A code drawn with this style could not be read back reliably, so it was not saved. "
                            "Try a smaller logo, a larger margin or stronger contrast."})


def _row(ctx: TenantContext) -> QRStyle:
    row = ctx.db.scalar(select(QRStyle).where(QRStyle.tenant_id == ctx.tenant_id))
    if not row:
        row = QRStyle(tenant_id=ctx.tenant_id, style={})
        ctx.db.add(row)
    return row


@router.get("/style", response_model=QRStyleOut)
def get_style(ctx: TenantContext = Depends(get_tenant_context)):
    return _out(ctx.db, ctx.tenant_id)


@router.put("/style", response_model=QRStyleOut)
def put_style(body: QRStyleIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Save the business's QR look. Applies to future downloads only; it never changes where any code points."""
    row = _row(ctx)
    style = body.model_dump()
    if style["use_logo"] and row.logo_png is None:
        raise HTTPException(status_code=422, detail="Upload a logo first, then turn it on")
    check_scannable(_sample_url(), style, row.logo_png)
    row.style, row.updated_by = style, ctx.user.id
    audit(ctx.db, action="qr.style_update", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="qr_style",
          meta={k: style[k] for k in ("dark", "light", "margin", "error_correction", "use_logo")}, ip=client_ip(request))
    ctx.db.commit()
    return _out(ctx.db, ctx.tenant_id)


@router.delete("/style", response_model=QRStyleOut)
def reset_style(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Back to the plain FlowQR look (the logo is removed too)."""
    row = ctx.db.scalar(select(QRStyle).where(QRStyle.tenant_id == ctx.tenant_id))
    if row:
        ctx.db.delete(row)
        audit(ctx.db, action="qr.style_reset", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="qr_style", ip=client_ip(request))
        ctx.db.commit()
    return _out(ctx.db, ctx.tenant_id)


@router.put("/style/logo", response_model=QRStyleOut)
async def put_logo(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Upload the logo drawn in the middle of codes. Send the image bytes as the request body (PNG, JPEG or WebP, up to 512 KB)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > qs.MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="Logo must be 512 KB or smaller")
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > qs.MAX_LOGO_BYTES:
            raise HTTPException(status_code=413, detail="Logo must be 512 KB or smaller")
    try:
        logo = qs.normalise_logo(bytes(raw))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    row = _row(ctx)
    style = {**qs.DEFAULT_STYLE, **(row.style or {})}
    if style["use_logo"]:  # the new logo will be drawn straight away, so it has to pass the same scan check
        check_scannable(_sample_url(), style, logo)
    row.logo_png, row.updated_by = logo, ctx.user.id
    audit(ctx.db, action="qr.logo_update", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="qr_style",
          meta={"bytes": len(logo)}, ip=client_ip(request))
    ctx.db.commit()
    return _out(ctx.db, ctx.tenant_id)


@router.delete("/style/logo", response_model=QRStyleOut)
def delete_logo(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    row = ctx.db.scalar(select(QRStyle).where(QRStyle.tenant_id == ctx.tenant_id))
    if row and row.logo_png is not None:
        row.logo_png = None
        row.style = {**(row.style or {}), "use_logo": False}
        audit(ctx.db, action="qr.logo_delete", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="qr_style", ip=client_ip(request))
        ctx.db.commit()
    return _out(ctx.db, ctx.tenant_id)


@router.get("/style/logo.png")
def get_logo(ctx: TenantContext = Depends(get_tenant_context)):
    _, logo = tenant_style(ctx.db, ctx.tenant_id)
    if logo is None:
        raise HTTPException(status_code=404, detail="No logo uploaded")
    return Response(logo, media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/preview.png")
def preview(body: QRStyleIn, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Draw a SAMPLE code with a style without saving it. The sample does not point at any card or campaign."""
    if not hit(f"qr-preview:{ctx.user.id}", 60, 60):
        raise HTTPException(status_code=429, detail="Too many previews. Please slow down.")
    _, logo = tenant_style(ctx.db, ctx.tenant_id)
    style = body.model_dump()
    ok = qs.scannable(_sample_url(), style, logo)
    return Response(qs.render_png(_sample_url(), style, logo if style["use_logo"] else None, size_px=min(style["size_px"], 768)), media_type="image/png",
                    headers={"X-FlowQR-Scannable": {True: "yes", False: "no", None: "unverified"}[ok], "Cache-Control": "private, no-store"})


@router.post("/bulk")
def bulk(body: BulkIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """ZIP of codes for many cards and/or campaigns: one file per code per format, an A4 print sheet and a manifest.csv.
    Codes are drawn for the EXISTING permanent links; nothing is created, rotated or re-pointed."""
    if not hit(f"qr-bulk:{ctx.tenant_id}", 10, 600):
        raise HTTPException(status_code=429, detail="Too many bulk exports. Try again in a few minutes.")
    db = ctx.db
    cq = select(QRCard).where(QRCard.tenant_id == ctx.tenant_id, ctx.scope(QRCard.location_id)).order_by(QRCard.card_code)
    cards = list(db.scalars(cq if body.all_cards else cq.where(QRCard.id.in_(body.card_ids)))) if (body.all_cards or body.card_ids) else []
    pq = select(ReviewCampaign).where(ReviewCampaign.tenant_id == ctx.tenant_id, ctx.scope(ReviewCampaign.location_id)).order_by(ReviewCampaign.created_at)
    if body.all_campaigns:
        campaigns = list(db.scalars(pq.where(ReviewCampaign.status != "archived")))
    else:
        campaigns = list(db.scalars(pq.where(ReviewCampaign.id.in_(body.campaign_ids)))) if body.campaign_ids else []
    if not body.all_cards and len(cards) != len(set(body.card_ids)):
        raise HTTPException(status_code=404, detail="Card not found")  # includes another business's card ids
    if not body.all_campaigns and len(campaigns) != len(set(body.campaign_ids)):
        raise HTTPException(status_code=404, detail="Campaign not found")
    if not cards and not campaigns:
        raise HTTPException(status_code=404, detail="Nothing to export")
    if len(cards) + len(campaigns) > MAX_BULK:
        raise HTTPException(status_code=422, detail=f"A bulk export is limited to {MAX_BULK} codes. Select fewer and export again.")
    if body.design == "poster":
        require_print_domain()
        return _bulk_posters(ctx, body, cards, campaigns, request)

    style, logo = tenant_style(db, ctx.tenant_id)
    locs = {l.id: l.name for l in db.scalars(select(Location).where(Location.tenant_id == ctx.tenant_id))}
    items: list[dict] = []
    for c in cards:
        items.append({"kind": "card", "name": c.card_code, "file": c.card_code, "label": c.card_code + (f" - {c.label}" if c.label else ""),
                      "url": card_qr_url(c), "status": c.status.value, "location": locs.get(c.location_id, ""), "style": style})
    seen: set[str] = set()
    for c in campaigns:
        base = f"campaign-{slug(c.name, 'campaign')}"
        name = base if base not in seen else f"{base}-{c.public_id[:6]}"
        seen.add(name)
        items.append({"kind": "campaign", "name": c.name, "file": name, "label": c.name, "url": campaign_url(c.public_id), "status": c.status,
                      "location": locs.get(c.location_id, ""), "style": {**qs.DEFAULT_STYLE, **c.qr_style} if c.qr_style else style})

    buf, manifest, fallbacks = io.BytesIO(), io.StringIO(), 0
    w = csv.writer(manifest)
    w.writerow(["kind", "name", "permanent_url", "status", "location", "style"])
    sheet = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for it in items:
            safe, safe_logo, applied = qs.safe_style(it["url"], it["style"], logo)
            fallbacks += not applied
            for fmt in dict.fromkeys(body.formats):
                z.writestr(f"{fmt}/{it['file']}.{fmt}", RENDER[fmt](it["url"], safe, safe_logo, size_px=body.size_px))
            sheet.append((it["label"], it["url"], safe, safe_logo))
            w.writerow([it["kind"], it["name"], it["url"], it["status"], it["location"], "applied" if applied else "fallback-plain"])
        if body.sheet:
            z.writestr("print-sheet-A4.pdf", qs.render_sheet_pdf(sheet))
        z.writestr("manifest.csv", manifest.getvalue())
    audit(db, action="qr.bulk_export", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="qr",
          meta={"cards": len(cards), "campaigns": len(campaigns), "formats": list(dict.fromkeys(body.formats)), "sheet": body.sheet}, ip=client_ip(request))
    db.commit()
    return Response(buf.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="flowqr-codes-{slug(ctx.tenant.name, "business")}.zip"',
        "X-FlowQR-Codes": str(len(items)), "X-FlowQR-Style-Fallbacks": str(fallbacks), "Cache-Control": "private, no-store"})



def _bulk_posters(ctx: TenantContext, body: BulkIn, cards: list, campaigns: list, request: Request) -> Response:
    """ZIP of posters: each file is the approved artwork with that code in it, plus one A4 print sheet (4 per page) of all of them."""
    db = ctx.db
    items = [(c.card_code, card_qr_url(c), c.card_code, c.status.value) for c in cards]
    seen: set[str] = set()
    for c in campaigns:
        base = f"campaign-{slug(c.name, 'campaign')}"
        name = base if base not in seen else f"{base}-{c.public_id[:6]}"
        seen.add(name)
        items.append((name, campaign_url(c.public_id), c.name, c.status))
    formats = list(dict.fromkeys(body.formats))
    if formats and len(items) > MAX_BULK_POSTER_FILES:
        raise HTTPException(status_code=422, detail=f"Poster files are large. Select up to {MAX_BULK_POSTER_FILES} for individual files, or choose only the print sheet for more.")
    buf, manifest = io.BytesIO(), io.StringIO()
    w = csv.writer(manifest)
    w.writerow(["name", "permanent_url", "status", "verified_by_decoding"])
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for file, url, _label, status in items:
                for fmt in formats:
                    z.writestr(f"{fmt}/{file}-poster.{fmt}", poster_file(url, fmt))
                w.writerow([file, url, status, "yes"])
            if body.sheet:
                z.writestr("print-sheet-A4-posters.pdf", poster_svc.poster_sheet_pdf([(label, url) for _f, url, label, _s in items]))
            z.writestr("manifest.csv", manifest.getvalue())
    except poster_svc.PosterError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    audit(db, action="qr.bulk_export", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="qr",
          meta={"cards": len(cards), "campaigns": len(campaigns), "formats": formats, "sheet": body.sheet, "design": "poster"}, ip=client_ip(request))
    db.commit()
    return Response(buf.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="flowqr-posters-{slug(ctx.tenant.name, "business")}.zip"',
        "X-FlowQR-Codes": str(len(items)), "Cache-Control": "private, no-store"})
