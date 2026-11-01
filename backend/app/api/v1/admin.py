"""Platform-admin (FlowHQ staff) endpoints: card inventory, batches, tenants overview."""
import csv
import html
import io
import uuid
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select

from app.api.v1.cards import card_out
from app.core.deps import AuthContext, require_platform_admin
from app.core.rate_limit import client_ip
from app.models import (
    CardAssignment, CardBatch, CardStatus, Location, Membership, QRCard, Review, ScanEvent, ScanEventType, Tenant,
)
from app.schemas.cards import AssignIn, BatchCreateIn, BatchOut, CardOut, StatusIn
from app.services import cards as svc
from app.services.audit import audit
from app.services.qr import card_url, qr_png, qr_svg

router = APIRouter(prefix="/admin", tags=["platform-admin"])


@router.post("/batches", response_model=BatchOut, status_code=201)
def create_batch(body: BatchCreateIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    batch = svc.create_batch(ctx.db, name=body.name, quantity=body.quantity, prefix=body.prefix,
                             created_by=ctx.user.id, notes=body.notes)
    audit(ctx.db, action="admin.batch_create", user_id=ctx.user.id, entity_type="batch", entity_id=batch.id,
          meta={"quantity": body.quantity, "prefix": body.prefix}, ip=client_ip(request))
    ctx.db.commit()
    return batch


@router.get("/batches", response_model=list[BatchOut])
def list_batches(ctx: AuthContext = Depends(require_platform_admin)):
    return ctx.db.scalars(select(CardBatch).order_by(CardBatch.created_at.desc())).all()


def _batch_cards(ctx: AuthContext, batch_id: uuid.UUID) -> tuple[CardBatch, list[QRCard]]:
    batch = ctx.db.get(CardBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    cards = ctx.db.scalars(select(QRCard).where(QRCard.batch_id == batch_id).order_by(QRCard.card_code)).all()
    return batch, list(cards)


@router.get("/batches/{batch_id}/export.zip")
def export_batch_zip(batch_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """ZIP with one print-quality PNG + SVG per card and a manifest.csv (card code -> URL for NFC encoding)."""
    batch, cards = _batch_cards(ctx, batch_id)
    buf = io.BytesIO()
    manifest = io.StringIO()
    w = csv.writer(manifest)
    w.writerow(["card_code", "url", "status"])
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in cards:
            url = card_url(c.public_token)
            z.writestr(f"png/{c.card_code}.png", qr_png(url, scale=16))
            z.writestr(f"svg/{c.card_code}.svg", qr_svg(url))
            w.writerow([c.card_code, url, c.status.value])
        z.writestr("manifest.csv", manifest.getvalue())
    audit(ctx.db, action="admin.batch_export", user_id=ctx.user.id, entity_type="batch", entity_id=batch.id,
          ip=client_ip(request))
    ctx.db.commit()
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{batch.prefix}-batch-{batch.id.hex[:8]}.zip"'})


@router.get("/batches/{batch_id}/sheet", response_class=Response)
def printable_sheet(batch_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    """Printable A4 sheet (open and Ctrl+P). 3 columns of QR cards with the card code underneath."""
    batch, cards = _batch_cards(ctx, batch_id)
    cells = []
    for c in cards:
        svg = qr_svg(card_url(c.public_token), scale=4).decode()
        cells.append(
            f'<div class="cell">{svg}<div class="code">{html.escape(c.card_code)}</div>'
            f'<div class="brand">FlowQR by FlowHQ</div></div>'
        )
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(batch.name)} - print sheet</title>
<style>
@page {{ size: A4; margin: 10mm; }}
body {{ font-family: system-ui, sans-serif; margin: 0; }}
h1 {{ font-size: 14px; margin: 0 0 8px; }}
.grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 6mm; }}
.cell {{ border: 1px dashed #bbb; padding: 4mm; text-align: center; break-inside: avoid; }}
.cell svg {{ width: 48mm; height: 48mm; }}
.code {{ font-weight: 700; font-size: 14px; margin-top: 2mm; letter-spacing: .06em; }}
.brand {{ font-size: 9px; color: #666; }}
@media print {{ h1 {{ display: none; }} }}
</style></head><body><h1>{html.escape(batch.name)} - {len(cards)} cards. Press Ctrl+P to print.</h1>
<div class="grid">{''.join(cells)}</div></body></html>"""
    return Response(page, media_type="text/html; charset=utf-8", headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


@router.get("/cards")
def list_cards(
    ctx: AuthContext = Depends(require_platform_admin),
    search: str | None = None,
    status: CardStatus | None = None,
    tenant_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    q = select(QRCard)
    if search:
        q = q.where(QRCard.card_code.ilike(f"%{search.strip()}%"))
    if status:
        q = q.where(QRCard.status == status)
    if tenant_id:
        q = q.where(QRCard.tenant_id == tenant_id)
    if batch_id:
        q = q.where(QRCard.batch_id == batch_id)
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    cards = ctx.db.scalars(q.order_by(QRCard.card_code).limit(limit).offset(offset)).all()
    tenants = {t.id: t.name for t in ctx.db.scalars(select(Tenant).where(Tenant.id.in_([c.tenant_id for c in cards if c.tenant_id])))}
    locs = {l.id: l.name for l in ctx.db.scalars(select(Location).where(Location.id.in_([c.location_id for c in cards if c.location_id])))}
    counts = svc.card_scan_counts(ctx.db, [c.id for c in cards])
    return {
        "total": total,
        "items": [card_out(c, stats=counts.get(c.id), tenant_name=tenants.get(c.tenant_id), location_name=locs.get(c.location_id)) for c in cards],
    }


def _card_or_404(ctx: AuthContext, card_id: uuid.UUID) -> QRCard:
    card = ctx.db.get(QRCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.get("/cards/{card_id}")
def card_detail(card_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    history = ctx.db.execute(
        select(CardAssignment, Tenant.name, Location.name)
        .join(Tenant, Tenant.id == CardAssignment.tenant_id)
        .outerjoin(Location, Location.id == CardAssignment.location_id)
        .where(CardAssignment.card_id == card.id).order_by(CardAssignment.assigned_at.desc())
    ).all()
    tenant = ctx.db.get(Tenant, card.tenant_id) if card.tenant_id else None
    loc = ctx.db.get(Location, card.location_id) if card.location_id else None
    return {
        "card": card_out(card, stats=svc.card_scan_counts(ctx.db, [card.id]).get(card.id),
                         tenant_name=tenant.name if tenant else None, location_name=loc.name if loc else None),
        "history": [{"tenant": t, "location": l, "assigned_at": a.assigned_at, "unassigned_at": a.unassigned_at} for a, t, l in history],
    }


@router.post("/cards/{card_id}/assign", response_model=CardOut)
def assign(card_id: uuid.UUID, body: AssignIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    tenant = ctx.db.get(Tenant, body.tenant_id)
    location = ctx.db.get(Location, body.location_id)
    if not tenant or not location:
        raise HTTPException(status_code=404, detail="Business or location not found")
    if card.status == CardStatus.lost:
        raise HTTPException(status_code=400, detail="Card is marked lost; set status first")
    svc.assign_card(ctx.db, card, tenant=tenant, location=location, by=ctx.user.id)
    if body.label is not None:
        card.label = body.label
    audit(ctx.db, action="admin.card_assign", tenant_id=tenant.id, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, meta={"location_id": str(location.id)}, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card, tenant_name=tenant.name, location_name=location.name)


@router.post("/cards/{card_id}/unassign", response_model=CardOut)
def unassign(card_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    old_tenant = card.tenant_id
    svc.unassign_card(ctx.db, card)
    audit(ctx.db, action="admin.card_unassign", tenant_id=old_tenant, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card)


@router.post("/cards/{card_id}/status", response_model=CardOut)
def set_status(card_id: uuid.UUID, body: StatusIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    if body.status in (CardStatus.assigned, CardStatus.active) and not card.tenant_id:
        raise HTTPException(status_code=400, detail="Assign the card to a location first")
    if body.status == CardStatus.unassigned:
        raise HTTPException(status_code=400, detail="Use the unassign action")
    card.status = body.status
    audit(ctx.db, action="admin.card_status", tenant_id=card.tenant_id, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, meta={"status": body.status.value}, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card)


@router.get("/cards/{card_id}/qr.{fmt}")
def admin_card_qr(card_id: uuid.UUID, fmt: str, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    url = card_url(card.public_token)
    if fmt == "png":
        return Response(qr_png(url), media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{card.card_code}.png"'})
    if fmt == "svg":
        return Response(qr_svg(url), media_type="image/svg+xml", headers={"Content-Disposition": f'attachment; filename="{card.card_code}.svg"'})
    raise HTTPException(status_code=404, detail="Unsupported format")


@router.get("/tenants")
def list_tenants(ctx: AuthContext = Depends(require_platform_admin), search: str | None = None):
    q = select(Tenant)
    if search:
        q = q.where(Tenant.name.ilike(f"%{search.strip()}%"))
    tenants = ctx.db.scalars(q.order_by(Tenant.created_at.desc()).limit(200)).all()
    out = []
    for t in tenants:
        out.append({
            "id": t.id, "name": t.name, "category": t.category, "created_at": t.created_at, "is_active": t.is_active,
            "locations": ctx.db.scalar(select(func.count()).select_from(Location).where(Location.tenant_id == t.id)),
            "cards": ctx.db.scalar(select(func.count()).select_from(QRCard).where(QRCard.tenant_id == t.id)),
            "members": ctx.db.scalar(select(func.count()).select_from(Membership).where(Membership.tenant_id == t.id)),
        })
    return out


@router.get("/tenants/{tenant_id}/locations")
def tenant_locations(tenant_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    locs = ctx.db.scalars(select(Location).where(Location.tenant_id == tenant_id, Location.is_active.is_(True)).order_by(Location.name)).all()
    return [{"id": l.id, "name": l.name, "city": l.city} for l in locs]


@router.get("/stats")
def platform_stats(ctx: AuthContext = Depends(require_platform_admin)):
    by_status = dict(ctx.db.execute(select(QRCard.status, func.count()).group_by(QRCard.status)).all())
    scans = dict(ctx.db.execute(
        select(ScanEvent.event_type, func.count()).where(ScanEvent.is_bot.is_(False)).group_by(ScanEvent.event_type)).all())
    return {
        "tenants": ctx.db.scalar(select(func.count()).select_from(Tenant)),
        "locations": ctx.db.scalar(select(func.count()).select_from(Location)),
        "cards_by_status": {k.value: v for k, v in by_status.items()},
        "events": {k.value: v for k, v in scans.items()},
        "synced_reviews": ctx.db.scalar(select(func.count()).select_from(Review)),
    }
