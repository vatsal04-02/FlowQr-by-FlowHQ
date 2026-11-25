"""Platform-admin (FlowHQ staff) endpoints: card inventory, batches, tenants overview."""
import csv
import html
import io
import uuid
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from datetime import date, datetime, time as dtime, timedelta, timezone

from sqlalchemy import exists, func, or_, select, update

from app.api.v1.cards import card_out, names_for
from app.api.v1.qr import cr80_file, cr80_response, poster_file, poster_response, require_print_domain
from app.core.deps import AuthContext, require_platform_admin
from app.core.rate_limit import client_ip, hit
from app.models import (
    CardAssignment, CardBatch, CardDestinationHistory, CardStatus, Location, Membership, QRCard, Review, ReviewCampaign, ScanEvent, ScanEventType, Tenant,
)
from app.models import (
    AIGenerationLog, AuditLog, AuthSession, BillingPlan, CardOrder, Payment, Subscription, User, WebhookEvent,
)
from app.models.base import utcnow
from app.models.sites import Site
from app.models.tenancy import Membership as _M, Role as _R
from app.schemas.admin import BudgetsIn, CardOrderAdminIn, PlanLimitsIn, SubscriptionAdminIn, SuspendIn, SupportIn, UserActiveIn
from app.services import billing as billing_svc
from app.services import finance as finance_svc
from app.services import plans as plans_svc
from app.services.ai_usage import month_start
from app.schemas.cards import AssignIn, BatchCreateIn, BatchOut, BulkAssignIn, CardOut, ConfirmIn, LookupIn, ReserveIn, StatusIn
from app.services import cards as svc
from app.services import destinations as dest_svc
from app.services import poster as poster_svc
from app.services.audit import audit
from app.services.qr import card_nfc_url, card_qr_url, qr_png, qr_svg

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


@router.post("/batches/{batch_id}/release")
def release_batch(batch_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Mark a batch as printed and in stock: its 'generated' cards become 'unassigned' and can be reserved or assigned."""
    batch = ctx.db.get(CardBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    n = svc.release_batch(ctx.db, batch)
    audit(ctx.db, action="admin.batch_release", user_id=ctx.user.id, entity_type="batch", entity_id=batch.id, meta={"cards": n}, ip=client_ip(request))
    ctx.db.commit()
    return {"released": n, "counts": svc.status_counts(ctx.db, batch.id)}


@router.get("/inventory")
def inventory(ctx: AuthContext = Depends(require_platform_admin)):
    """Stock at a glance: counts by lifecycle state, overall and per batch."""
    batches = ctx.db.scalars(select(CardBatch).order_by(CardBatch.created_at.desc())).all()
    rows = ctx.db.execute(select(QRCard.batch_id, QRCard.status, func.count()).group_by(QRCard.batch_id, QRCard.status)).all()
    per: dict = {}
    for bid, st, n in rows:
        per.setdefault(bid, {})[st.value] = n
    total = svc.status_counts(ctx.db)
    available = sum(total.get(k, 0) for k in ("generated", "unassigned"))
    return {
        "counts": total,
        "available": available,  # in stock: can be reserved or assigned
        "in_use": sum(total.get(k, 0) for k in ("assigned", "active", "paused", "reserved")),
        "batches": [{"id": b.id, "name": b.name, "prefix": b.prefix, "quantity": b.quantity, "created_at": b.created_at, "released_at": b.released_at,
                     "counts": {**{st.value: 0 for st in CardStatus}, **per.get(b.id, {})}} for b in batches],
    }


@router.get("/batches/{batch_id}/export.zip")
def export_batch_zip(batch_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """ZIP with one print-quality PNG + SVG per card (plain code) and a manifest.csv (serial -> QR URL and NFC URL)."""
    require_print_domain()
    batch, cards = _batch_cards(ctx, batch_id)
    buf = io.BytesIO()
    manifest = io.StringIO()
    w = csv.writer(manifest)
    w.writerow(["card_code", "url", "nfc_url", "status"])
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in cards:
            url = card_qr_url(c)
            z.writestr(f"png/{c.card_code}.png", qr_png(url, scale=16))
            z.writestr(f"svg/{c.card_code}.svg", qr_svg(url))
            w.writerow([c.card_code, url, card_nfc_url(c.public_token), c.status.value])
        z.writestr("manifest.csv", manifest.getvalue())
    audit(ctx.db, action="admin.batch_export", user_id=ctx.user.id, entity_type="batch", entity_id=batch.id,
          ip=client_ip(request))
    ctx.db.commit()
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{batch.prefix}-batch-{batch.id.hex[:8]}.zip"'})


@router.get("/batches/{batch_id}/inventory.csv")
def inventory_csv(batch_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Inventory sheet for the printer and for whoever writes the NFC tags: serial, QR address, NFC address (an NDEF URL record), state."""
    require_print_domain()
    batch, cards = _batch_cards(ctx, batch_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["serial", "batch", "status", "qr_url", "nfc_url", "nfc_ndef_uri_bytes", "created"])
    for c in cards:
        nfc = card_nfc_url(c.public_token)
        w.writerow([c.card_code, batch.name, c.status.value, card_qr_url(c), nfc, len(nfc.encode()), c.created_at.date().isoformat()])
    audit(ctx.db, action="admin.batch_inventory_csv", user_id=ctx.user.id, entity_type="batch", entity_id=batch.id, ip=client_ip(request))
    ctx.db.commit()
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{batch.prefix}-inventory-{batch.id.hex[:8]}.csv"', "Cache-Control": "private, no-store"})


@router.get("/batches/{batch_id}/posters.pdf")
def batch_poster_sheets(batch_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Print-ready A4 sheets of the approved FlowQR poster, four per page, each with this card's own code and serial. Every code is
    decoded back to its URL before the file is produced; the artwork is embedded once, so 500 cards stay a manageable file."""
    require_print_domain()
    batch, cards = _batch_cards(ctx, batch_id)
    try:
        body = poster_svc.poster_sheet_pdf([(c.card_code, card_qr_url(c), c.card_code) for c in cards])
    except poster_svc.PosterError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    audit(ctx.db, action="admin.batch_posters", user_id=ctx.user.id, entity_type="batch", entity_id=batch.id, meta={"cards": len(cards)}, ip=client_ip(request))
    ctx.db.commit()
    return Response(body, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{batch.prefix}-posters-{batch.id.hex[:8]}.pdf"', "X-FlowQR-Codes": str(len(cards)),
        "X-FlowQR-Verified": "decoded", "Cache-Control": "private, no-store"})


@router.get("/batches/{batch_id}/posters.zip")
def batch_poster_files(batch_id: uuid.UUID, request: Request, fmt: str = Query("png", pattern="^(png|svg|pdf)$"),
                       offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), ctx: AuthContext = Depends(require_platform_admin)):
    """Individual poster files (PNG, SVG or PDF), one per card, in pages of up to 100 so a 500-card batch is five downloads."""
    require_print_domain()
    batch, cards = _batch_cards(ctx, batch_id)
    page = cards[offset:offset + limit]
    if not page:
        raise HTTPException(status_code=404, detail="No cards in that range")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in page:
            z.writestr(f"{c.card_code}-poster.{fmt}", poster_file(card_qr_url(c), fmt, serial=c.card_code))
    audit(ctx.db, action="admin.batch_poster_files", user_id=ctx.user.id, entity_type="batch", entity_id=batch.id,
          meta={"format": fmt, "offset": offset, "count": len(page)}, ip=client_ip(request))
    ctx.db.commit()
    return Response(buf.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{batch.prefix}-posters-{offset + 1}-{offset + len(page)}.zip"',
        "X-FlowQR-Codes": str(len(page)), "X-FlowQR-Total": str(len(cards)), "Cache-Control": "private, no-store"})


@router.get("/batches/{batch_id}/cards.zip")
def batch_card_files(batch_id: uuid.UUID, request: Request, fmt: str = Query("pdf", pattern="^(png|pdf)$"), bleed: float = Query(0.0),
                     offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), ctx: AuthContext = Depends(require_platform_admin)):
    """Print files for the physical card (CR80, 85.6 x 54 mm, portrait), one per card, in pages of up to 100. `bleed` is 0 (trim size) or 3 (mm, for a printer who die-cuts)."""
    require_print_domain()
    if bleed not in (0.0, 3.0):
        raise HTTPException(status_code=422, detail="bleed must be 0 or 3 (mm)")
    batch, cards = _batch_cards(ctx, batch_id)
    page = cards[offset:offset + limit]
    if not page:
        raise HTTPException(status_code=404, detail="No cards in that range")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in page:
            z.writestr(f"{c.card_code}-cr80.{fmt}", cr80_file(card_qr_url(c), fmt, bleed=bleed, serial=c.card_code))
    audit(ctx.db, action="admin.batch_card_files", user_id=ctx.user.id, entity_type="batch", entity_id=batch.id,
          meta={"format": fmt, "bleed_mm": bleed, "offset": offset, "count": len(page)}, ip=client_ip(request))
    ctx.db.commit()
    return Response(buf.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{batch.prefix}-cr80-{offset + 1}-{offset + len(page)}.zip"',
        "X-FlowQR-Codes": str(len(page)), "X-FlowQR-Total": str(len(cards)), "Cache-Control": "private, no-store"})


@router.get("/batches/{batch_id}/sheet", response_class=Response)
def printable_sheet(batch_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    """Printable A4 sheet (open and Ctrl+P). 3 columns of QR cards with the card code underneath."""
    require_print_domain()
    batch, cards = _batch_cards(ctx, batch_id)
    cells = []
    for c in cards:
        svg = qr_svg(card_qr_url(c), scale=4).decode()
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
    location_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    has_destination: bool | None = None,
    nfc: str | None = Query(None, pattern="^(programmed|not_programmed)$"),
    in_stock: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    q = select(QRCard)
    if location_id:
        q = q.where(QRCard.location_id == location_id)
    if campaign_id:
        q = q.where(QRCard.campaign_id == campaign_id)
    if created_from:
        q = q.where(QRCard.created_at >= datetime.combine(created_from, dtime.min, tzinfo=timezone.utc))
    if created_to:
        q = q.where(QRCard.created_at < datetime.combine(created_to, dtime.min, tzinfo=timezone.utc) + timedelta(days=1))
    if has_destination is not None:
        q = q.where(QRCard.destination_url.is_not(None) if has_destination else QRCard.destination_url.is_(None))
    if nfc:
        q = q.where(QRCard.nfc_programmed_at.is_not(None) if nfc == "programmed" else QRCard.nfc_programmed_at.is_(None))
    if search:
        term = search.strip()
        q = q.where(or_(QRCard.card_code.ilike(f"%{term}%"), QRCard.public_token == term))
    if status:
        q = q.where(QRCard.status == status)
    if in_stock:
        q = q.where(QRCard.status.in_(list(svc.STOCK_STATUSES - {CardStatus.archived})))
    if tenant_id:
        q = q.where(QRCard.tenant_id == tenant_id)
    if batch_id:
        q = q.where(QRCard.batch_id == batch_id)
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    cards = ctx.db.scalars(q.order_by(QRCard.card_code).limit(limit).offset(offset)).all()
    tenants = {t.id: t.name for t in ctx.db.scalars(select(Tenant).where(Tenant.id.in_([c.tenant_id for c in cards if c.tenant_id])))}
    locs, camps, batches = names_for(ctx.db, list(cards))
    counts = svc.card_scan_counts(ctx.db, [c.id for c in cards])
    last = svc.card_last_scans(ctx.db, [c.id for c in cards])
    return {
        "total": total,
        "items": [card_out(c, stats=counts.get(c.id), tenant_name=tenants.get(c.tenant_id), location_name=locs.get(c.location_id), last_scan_at=last.get(c.id),
                           campaign_name=camps.get(c.campaign_id), batch_name=batches.get(c.batch_id)) for c in cards],
    }


def _card_or_404(ctx: AuthContext, card_id: uuid.UUID) -> QRCard:
    card = ctx.db.get(QRCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


def _full_card(ctx: AuthContext, card: QRCard):
    tenant = ctx.db.get(Tenant, card.tenant_id) if card.tenant_id else None
    locs, camps, batches = names_for(ctx.db, [card])
    return card_out(card, stats=svc.card_scan_counts(ctx.db, [card.id]).get(card.id), tenant_name=tenant.name if tenant else None,
                    location_name=locs.get(card.location_id), campaign_name=camps.get(card.campaign_id), batch_name=batches.get(card.batch_id))


@router.post("/cards/lookup")
def lookup_card(body: LookupIn, ctx: AuthContext = Depends(require_platform_admin)):
    """Identify a physical card from what the camera read (its /q/, /n/ or /c/ link), its token, or its printed serial."""
    if not hit(f"admin-card-lookup:{ctx.user.id}", 120, 60):
        raise HTTPException(status_code=429, detail="Too many lookups. Please wait a moment.")
    card = svc.find_by_scan(ctx.db, body.scan)
    if not card:
        raise HTTPException(status_code=404, detail="No card with that code was found. Check the serial or scan again.")
    return _full_card(ctx, card)


@router.get("/cards/{card_id}")
def card_detail(card_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    history = ctx.db.execute(
        select(CardAssignment, Tenant.name, Location.name, ReviewCampaign.name)
        .join(Tenant, Tenant.id == CardAssignment.tenant_id)
        .outerjoin(Location, Location.id == CardAssignment.location_id)
        .outerjoin(ReviewCampaign, ReviewCampaign.id == CardAssignment.campaign_id)
        .where(CardAssignment.card_id == card.id).order_by(CardAssignment.assigned_at.desc())
    ).all()
    return {
        "card": _full_card(ctx, card),
        "history": [{"tenant": t, "location": l, "campaign": c, "assigned_at": a.assigned_at, "unassigned_at": a.unassigned_at, "ended_reason": a.ended_reason}
                    for a, t, l, c in history],
        "destination": _destination_out(ctx, card),
        "nfc": svc.nfc_status(ctx.db, card),
    }


def _target_for(ctx: AuthContext, tenant_id: uuid.UUID, location_id: uuid.UUID, campaign_id: uuid.UUID | None):
    tenant = ctx.db.get(Tenant, tenant_id)
    location = ctx.db.get(Location, location_id)
    if not tenant or not location:
        raise HTTPException(status_code=404, detail="Business or location not found")
    if location.tenant_id != tenant.id:
        raise HTTPException(status_code=400, detail="Location does not belong to this business")
    return tenant, location, svc.check_campaign(ctx.db, campaign_id, tenant, location)


@router.post("/cards/{card_id}/assign", response_model=CardOut)
def assign(card_id: uuid.UUID, body: AssignIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    tenant, location, campaign = _target_for(ctx, body.tenant_id, body.location_id, body.campaign_id)
    if card.status == CardStatus.lost:
        raise HTTPException(status_code=400, detail="Card is marked lost; set status first")
    if card.tenant_id and card.tenant_id != tenant.id and card.status in svc.OWNED_STATUSES and not body.confirm:
        # Moving a card to a different business is the most consequential reassignment: always ask first.
        old = ctx.db.get(Tenant, card.tenant_id)
        raise svc.confirmation_required("This card belongs to another business. Moving it sends everyone who scans or taps it to the new business.",
                                        {"business": old.name if old else None, "location": None, "campaign": None},
                                        {"business": tenant.name, "location": location.name, "campaign": campaign.name if campaign else None})
    svc.assign_card(ctx.db, card, tenant=tenant, location=location, by=ctx.user.id, campaign=campaign, confirm=body.confirm, activate=body.activate)
    if body.label is not None:
        card.label = body.label
    audit(ctx.db, action="admin.card_assign", tenant_id=tenant.id, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, meta={"location_id": str(location.id), "campaign_id": str(campaign.id) if campaign else None, "activate": body.activate},
          ip=client_ip(request))
    ctx.db.commit()
    return _full_card(ctx, card)


@router.post("/cards/bulk-assign")
def bulk_assign(body: BulkAssignIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Assign many cards to one business, location and campaign at once. All-or-nothing: if any card cannot be assigned, none are."""
    if not hit(f"admin-bulk-assign:{ctx.user.id}", 20, 600):
        raise HTTPException(status_code=429, detail="Too many bulk assignments. Try again in a few minutes.")
    tenant, location, campaign = _target_for(ctx, body.tenant_id, body.location_id, body.campaign_id)
    cards: list[QRCard] = []
    if body.card_ids:
        cards += list(ctx.db.scalars(select(QRCard).where(QRCard.id.in_(body.card_ids))))
    if body.serials:
        wanted = {s.strip().upper() for s in body.serials if s.strip()}
        cards += list(ctx.db.scalars(select(QRCard).where(QRCard.card_code.in_(wanted))))
        missing = wanted - {c.card_code for c in cards}
        if missing:
            raise HTTPException(status_code=404, detail=f"No card found for: {', '.join(sorted(missing)[:10])}")
    seen: dict = {c.id: c for c in cards}
    cards = list(seen.values())
    if not cards:
        raise HTTPException(status_code=422, detail="Choose at least one card.")
    if body.card_ids and not set(body.card_ids) <= set(seen):
        raise HTTPException(status_code=404, detail="One or more cards were not found.")
    if len(cards) > 500:
        raise HTTPException(status_code=422, detail="Assign up to 500 cards at a time.")
    problems = [f"{c.card_code}: {c.status.value}" for c in cards if c.status in (CardStatus.retired, CardStatus.lost, CardStatus.deactivated)]
    in_use = [c for c in cards if c.status in (CardStatus.assigned, CardStatus.active, CardStatus.paused) and not (c.tenant_id == tenant.id and c.location_id == location.id and c.campaign_id == (campaign.id if campaign else None))]
    if problems:
        raise HTTPException(status_code=409, detail={"code": "cards_not_assignable", "message": "These cards cannot be assigned: " + ", ".join(problems[:10])})
    if in_use and not body.confirm:
        raise svc.confirmation_required(f"{len(in_use)} of these cards are already in use. Assigning them sends their scans and taps to the new destination.",
                                        {"cards_in_use": [c.card_code for c in in_use[:20]]}, {"business": tenant.name, "location": location.name, "campaign": campaign.name if campaign else None})
    for c in cards:
        svc.assign_card(ctx.db, c, tenant=tenant, location=location, by=ctx.user.id, campaign=campaign, confirm=True, activate=body.activate)
    audit(ctx.db, action="admin.card_bulk_assign", tenant_id=tenant.id, user_id=ctx.user.id, entity_type="card",
          meta={"cards": len(cards), "location_id": str(location.id), "campaign_id": str(campaign.id) if campaign else None}, ip=client_ip(request))
    ctx.db.commit()
    return {"assigned": len(cards), "serials": [c.card_code for c in sorted(cards, key=lambda x: x.card_code)]}


@router.post("/cards/{card_id}/reserve", response_model=CardOut)
def reserve(card_id: uuid.UUID, body: ReserveIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Set a card aside for one business. They can then give it a location and campaign themselves."""
    card = _card_or_404(ctx, card_id)
    tenant = ctx.db.get(Tenant, body.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Business not found")
    svc.reserve_card(ctx.db, card, tenant, ctx.user.id)
    audit(ctx.db, action="admin.card_reserve", tenant_id=tenant.id, user_id=ctx.user.id, entity_type="card", entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return _full_card(ctx, card)


@router.post("/cards/{card_id}/unassign", response_model=CardOut)
def unassign(card_id: uuid.UUID, request: Request, body: ConfirmIn | None = None, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    if card.status in (CardStatus.assigned, CardStatus.active, CardStatus.paused) and not (body and body.confirm):
        t = ctx.db.get(Tenant, card.tenant_id) if card.tenant_id else None
        raise svc.confirmation_required("This card is in use. Returning it to stock stops it working for its business straight away; the printed code is unchanged and can be assigned again.",
                                        {"business": t.name if t else None, "location": None, "campaign": None}, {"status": "unassigned"})
    old_tenant = card.tenant_id
    svc.unassign_card(ctx.db, card, "released" if card.status == CardStatus.reserved else "unassigned")
    audit(ctx.db, action="admin.card_unassign", tenant_id=old_tenant, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return _full_card(ctx, card)


@router.post("/cards/{card_id}/retire", response_model=CardOut)
def retire(card_id: uuid.UUID, body: ConfirmIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    old_tenant = card.tenant_id
    svc.retire_card(ctx.db, card, confirm=body.confirm)
    audit(ctx.db, action="admin.card_retire", tenant_id=old_tenant, user_id=ctx.user.id, entity_type="card", entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return _full_card(ctx, card)


@router.post("/cards/{card_id}/archive", response_model=CardOut)
def archive(card_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    card = svc.archive_card(_card_or_404(ctx, card_id))
    audit(ctx.db, action="admin.card_archive", user_id=ctx.user.id, entity_type="card", entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return _full_card(ctx, card)


@router.post("/cards/{card_id}/unarchive", response_model=CardOut)
def unarchive(card_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    card = svc.unarchive_card(_card_or_404(ctx, card_id))
    audit(ctx.db, action="admin.card_unarchive", user_id=ctx.user.id, entity_type="card", entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return _full_card(ctx, card)


@router.post("/cards/{card_id}/status", response_model=CardOut)
def set_status(card_id: uuid.UUID, body: StatusIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    if card.status == CardStatus.retired:
        raise HTTPException(status_code=409, detail="This card has been retired and cannot change state.")
    if body.status in (CardStatus.assigned, CardStatus.active) and not card.tenant_id:
        raise HTTPException(status_code=400, detail="Assign the card to a location first")
    if body.status in (CardStatus.assigned, CardStatus.active, CardStatus.paused) and not card.location_id:
        raise HTTPException(status_code=400, detail="Assign the card to a location first")
    if body.status in (CardStatus.unassigned, CardStatus.reserved, CardStatus.generated, CardStatus.archived, CardStatus.retired):
        raise HTTPException(status_code=400, detail="Use the unassign, reserve, archive or retire action for that")
    card.status = body.status
    audit(ctx.db, action="admin.card_status", tenant_id=card.tenant_id, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, meta={"status": body.status.value}, ip=client_ip(request))
    ctx.db.commit()
    return _full_card(ctx, card)


@router.get("/cards/{card_id}/qr.{fmt}")
def admin_card_qr(card_id: uuid.UUID, fmt: str, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    url = card_qr_url(card)
    if fmt == "png":
        return Response(qr_png(url), media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{card.card_code}.png"'})
    if fmt == "svg":
        return Response(qr_svg(url), media_type="image/svg+xml", headers={"Content-Disposition": f'attachment; filename="{card.card_code}.svg"'})
    raise HTTPException(status_code=404, detail="Unsupported format")


@router.get("/cards/{card_id}/poster.{fmt}")
def admin_card_poster(card_id: uuid.UUID, fmt: str, scale: int = Query(1, ge=1, le=3), size: str = Query("ref"), ctx: AuthContext = Depends(require_platform_admin)):
    """The approved FlowQR poster with this card's permanent QR code (PNG, SVG or print-ready PDF)."""
    card = _card_or_404(ctx, card_id)
    return poster_response(card_qr_url(card), fmt, card.card_code, scale=scale, size=size, serial=card.card_code)


@router.get("/cards/{card_id}/cr80.{fmt}")
def admin_card_cr80(card_id: uuid.UUID, fmt: str, bleed: float = Query(0.0), ctx: AuthContext = Depends(require_platform_admin)):
    """This card's print file for the physical card: CR80 (85.6 x 54 mm), portrait, PNG or PDF at 600 dpi, optionally with 3 mm bleed."""
    card = _card_or_404(ctx, card_id)
    return cr80_response(card_qr_url(card), fmt, card.card_code, bleed=bleed, serial=card.card_code)


def _tenant_row(db, t: Tenant, sub: Subscription | None, owner_email: str | None) -> dict:
    from app.models import TenantAgreement
    from app.services import provisioning as prov

    first_loc = db.scalar(select(Location).where(Location.tenant_id == t.id).order_by(Location.created_at).limit(1))
    return {
        "contact_name": t.contact_name, "phone": t.phone, "email": t.email, "origin": t.origin, "city": first_loc.city if first_loc else None,
        "active_cards": db.scalar(select(func.count()).select_from(QRCard).where(QRCard.tenant_id == t.id, QRCard.status.in_(prov.LIVE_CARD_STATUSES))),
        "onboarding_status": prov.onboarding_status(db, t, owner_email is not None or prov.has_owner(db, t.id)),
        "agreement_recorded": db.scalar(select(TenantAgreement.id).where(TenantAgreement.tenant_id == t.id).limit(1)) is not None,
        "managed_access": prov.managed_state(sub),
        "website_interest": t.website_interest, "website_url": t.website,
        "site_status": db.scalar(select(Site.status).where(Site.tenant_id == t.id)),
        "id": t.id, "name": t.name, "category": t.category, "created_at": t.created_at, "is_active": t.is_active,
        "suspended_at": t.suspended_at, "suspension_reason": t.suspension_reason, "support_status": t.support_status,
        "owner_email": owner_email, "plan": sub.plan if sub else None, "subscription_status": sub.status if sub else None,
        "locations": db.scalar(select(func.count()).select_from(Location).where(Location.tenant_id == t.id)),
        "cards": db.scalar(select(func.count()).select_from(QRCard).where(QRCard.tenant_id == t.id)),
        "members": db.scalar(select(func.count()).select_from(Membership).where(Membership.tenant_id == t.id)),
    }


@router.get("/tenants")
def list_tenants(ctx: AuthContext = Depends(require_platform_admin), search: str | None = None, status: str | None = None,
                 origin: str | None = Query(None, pattern="^(admin|self_service)$"), onboarding: str | None = Query(None, pattern="^(has_account|live|ready|incomplete)$"),
                 website: str | None = Query(None, pattern="^(wants|built|none)$"),
                 limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    q = select(Tenant)
    if search:
        term = search.strip()
        digits = "".join(ch for ch in term if ch.isdigit())
        conds = [Tenant.name.ilike(f"%{term}%"), Tenant.contact_name.ilike(f"%{term}%"), Tenant.email.ilike(f"%{term}%"),
                 Tenant.id.in_(select(Location.tenant_id).where(Location.city.ilike(f"%{term}%") | Location.name.ilike(f"%{term}%")))]
        if len(digits) >= 4:
            conds.append(func.regexp_replace(func.coalesce(Tenant.phone, ""), "[^0-9]", "", "g").like(f"%{digits}%"))
        try:
            conds.append(Tenant.id == uuid.UUID(term))  # search by client ID
        except ValueError:
            pass
        q = q.where(or_(*conds))
    if origin:
        q = q.where(Tenant.origin == origin)
    if onboarding:
        has_owner = exists().where(_M.tenant_id == Tenant.id, _M.role == _R.owner)
        live = exists().where(QRCard.tenant_id == Tenant.id, QRCard.status.in_([CardStatus.assigned, CardStatus.active]))
        ready = exists().where(Location.tenant_id == Tenant.id, Location.is_active.is_(True), Location.review_url.is_not(None), Location.review_url != "")
        q = q.where({"has_account": has_owner, "live": ~has_owner & live, "ready": ~has_owner & ~live & ready, "incomplete": ~has_owner & ~live & ~ready}[onboarding])
    if website:
        built = exists().where(Site.tenant_id == Tenant.id)
        q = q.where({"built": built, "wants": ~built & (Tenant.website_interest == "wants_site"), "none": ~built & (Tenant.website_interest.is_(None) | (Tenant.website_interest == "not_now"))}[website])
    if status == "suspended":
        q = q.where(Tenant.is_active.is_(False))
    elif status in ("trialing", "active", "past_due", "halted", "expired", "canceled", "pending"):
        q = q.where(Tenant.id.in_(select(Subscription.tenant_id).where(Subscription.status == status)))
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    tenants = ctx.db.scalars(q.order_by(Tenant.created_at.desc()).limit(limit).offset(offset)).all()
    subs = {x.tenant_id: x for x in ctx.db.scalars(select(Subscription).where(Subscription.tenant_id.in_([t.id for t in tenants])))}
    owners = dict(ctx.db.execute(select(_M.tenant_id, User.email).join(User, User.id == _M.user_id).where(_M.role == _R.owner, _M.tenant_id.in_([t.id for t in tenants]))).all())
    rows = [_tenant_row(ctx.db, t, subs.get(t.id), owners.get(t.id)) for t in tenants]
    return {"total": total, "items": rows}


@router.get("/tenants/{tenant_id}/locations")
def tenant_locations(tenant_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    locs = ctx.db.scalars(select(Location).where(Location.tenant_id == tenant_id, Location.is_active.is_(True)).order_by(Location.name)).all()
    return [{"id": l.id, "name": l.name, "city": l.city} for l in locs]


@router.get("/tenants/{tenant_id}/campaigns")
def tenant_campaigns(tenant_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    """The review campaigns a card of this business can open (not archived), so FlowHQ can bind a card to one while assigning it."""
    rows = ctx.db.scalars(select(ReviewCampaign).where(ReviewCampaign.tenant_id == tenant_id, ReviewCampaign.status != "archived").order_by(ReviewCampaign.name)).all()
    return [{"id": c.id, "name": c.name, "location_id": c.location_id, "status": c.status} for c in rows]


def _tenant_or_404(ctx: AuthContext, tenant_id: uuid.UUID) -> Tenant:
    t = ctx.db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Business not found")
    return t


def _email_of(db, user_id) -> str | None:
    return db.scalar(select(User.email).where(User.id == user_id)) if user_id else None


def _review_keywords(t: Tenant) -> dict:
    from app.services import provisioning as prov

    return prov.review_keywords(t)


def _provisioning_detail(db, t: Tenant) -> dict:
    """What the Business page adds for admin-managed businesses: the offline agreement record, claim invitations, this month's AI use and cost, and whether claiming is switched on."""
    from app.core.config import settings
    from app.models import DataRequest, Invitation, TenantAgreement
    from app.services import data_requests
    from app.services import provisioning as prov

    now = utcnow()
    agreements = db.scalars(select(TenantAgreement).where(TenantAgreement.tenant_id == t.id).order_by(TenantAgreement.recorded_at.desc())).all()
    invs = db.scalars(select(Invitation).where(Invitation.tenant_id == t.id, Invitation.role == _R.owner).order_by(Invitation.created_at.desc()).limit(10)).all()
    return {
        "agreements": [{"id": a.id, "recorded_at": a.recorded_at, "recorded_by": _email_of(db, a.recorded_by), "terms_version": a.terms_version, "method": a.method, "note": a.note, "statement": a.statement}
                       for a in agreements],
        "claim": {"enabled": settings.claim_invitations_enabled, "has_owner": prov.has_owner(db, t.id),
                  "invitations": [{"id": i.id, "email": i.email, "expires_at": i.expires_at, "accepted_at": i.accepted_at, "revoked_at": i.revoked_at,
                                   "state": "accepted" if i.accepted_at else "revoked" if i.revoked_at else "expired" if i.expires_at < now else "open",
                                   "allowlist": prov.allowlist_removal_check(db, i)} for i in invs]},
        "ai_usage": prov.ai_usage(db, t.id),
        "data_requests": [data_requests.serialize(db, r) for r in db.scalars(select(DataRequest).where(DataRequest.tenant_id == t.id).order_by(DataRequest.created_at.desc()).limit(10)).all()],
    }


@router.get("/tenants/{tenant_id}")
def tenant_detail(tenant_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant_or_404(ctx, tenant_id)
    db = ctx.db
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == t.id))
    members = db.execute(select(_M, User).join(User, User.id == _M.user_id).where(_M.tenant_id == t.id)).all()
    locs = db.scalars(select(Location).where(Location.tenant_id == t.id)).all()
    cards = db.scalars(select(QRCard).where(QRCard.tenant_id == t.id).order_by(QRCard.card_code)).all()
    pays = db.scalars(select(Payment).where(Payment.tenant_id == t.id).order_by(Payment.created_at.desc()).limit(25)).all()
    audit_rows = db.scalars(select(AuditLog).where(AuditLog.tenant_id == t.id).order_by(AuditLog.created_at.desc()).limit(25)).all()
    ai_month = db.scalar(select(func.count()).select_from(AIGenerationLog).where(AIGenerationLog.tenant_id == t.id, AIGenerationLog.created_at >= month_start())) or 0
    return {
        "tenant": _tenant_row(db, t, sub, next((u.email for m, u in members if m.role == _R.owner), None)) | {"support_note": t.support_note, "email": t.email, "phone": t.phone, "address": t.address,
                                                                                                         "website": t.website, **_review_keywords(t), "created_by": _email_of(db, t.created_by), "updated_by": _email_of(db, t.updated_by), "updated_at": t.updated_at},
        **_provisioning_detail(db, t),
        "subscription": None if not sub else {c: getattr(sub, c) for c in ("plan", "status", "source", "max_locations", "monthly_ai_generations", "max_staff", "features",
                                                                           "trial_ends_at", "current_period_end", "cancel_at_period_end", "past_due_since", "razorpay_subscription_id")},
        "members": [{"user_id": u.id, "email": u.email, "full_name": u.full_name, "role": m.role.value, "is_active": u.is_active, "email_verified": bool(u.email_verified_at)} for m, u in members],
        "locations": [{"id": l.id, "name": l.name, "city": l.city, "address_line": l.address_line, "phone": l.phone, "review_url": l.review_url, "is_active": l.is_active,
                       "has_review_link": bool(l.review_url)} for l in locs],
        "cards": [{"id": c.id, "card_code": c.card_code, "status": c.status.value, "location_id": c.location_id, "label": c.label} for c in cards],
        "payments": [{"id": p.id, "kind": p.kind, "status": p.status, "amount_paise": p.amount_paise, "created_at": p.created_at} for p in pays],
        "audit": [{"action": a.action, "created_at": a.created_at, "user_id": a.user_id, "meta": a.meta} for a in audit_rows],
        "ai_generations_this_month": ai_month,
    }


@router.post("/tenants/{tenant_id}/suspend", status_code=204)
def suspend(tenant_id: uuid.UUID, body: SuspendIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant_or_404(ctx, tenant_id)
    t.is_active, t.suspended_at, t.suspension_reason = False, utcnow(), body.reason
    from app.core.config import settings as _settings

    if _settings.sites_enabled:
        from app.services.sites import service as sites_svc

        site = sites_svc.get_by_tenant(ctx.db, t.id)
        if site is not None and site.status == "published":
            try:
                sites_svc.suspend(ctx.db, admin=ctx.user, site=site, reason=f"Business suspended: {body.reason}"[:300], ip=client_ip(request))
            except sites_svc.SiteError:
                pass  # the daily check suspends it as soon as hosting is reachable; the business suspension itself must not fail because of a website
    audit(ctx.db, action="admin.tenant_suspend", tenant_id=t.id, user_id=ctx.user.id, entity_type="tenant", entity_id=t.id, meta={"reason": body.reason}, ip=client_ip(request))
    ctx.db.commit()


@router.post("/tenants/{tenant_id}/unsuspend", status_code=204)
def unsuspend(tenant_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant_or_404(ctx, tenant_id)
    t.is_active, t.suspended_at, t.suspension_reason = True, None, None
    audit(ctx.db, action="admin.tenant_unsuspend", tenant_id=t.id, user_id=ctx.user.id, entity_type="tenant", entity_id=t.id, ip=client_ip(request))
    ctx.db.commit()


@router.patch("/tenants/{tenant_id}/support", status_code=204)
def support(tenant_id: uuid.UUID, body: SupportIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant_or_404(ctx, tenant_id)
    t.support_status, t.support_note = body.status, body.note
    audit(ctx.db, action="admin.support_status", tenant_id=t.id, user_id=ctx.user.id, entity_type="tenant", entity_id=t.id, meta={"status": body.status}, ip=client_ip(request))
    ctx.db.commit()


@router.patch("/users/{user_id}", status_code=204)
def set_user_active(user_id: uuid.UUID, body: UserActiveIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    u = ctx.db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u.id == ctx.user.id:
        raise HTTPException(status_code=400, detail="You can't deactivate yourself")
    u.is_active = body.is_active
    if not body.is_active:  # kill live sessions immediately
        ctx.db.execute(update(AuthSession).where(AuthSession.user_id == u.id, AuthSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    audit(ctx.db, action="admin.user_active", user_id=ctx.user.id, entity_type="user", entity_id=u.id, meta={"is_active": body.is_active}, ip=client_ip(request))
    ctx.db.commit()


@router.post("/tenants/{tenant_id}/subscription")
def manage_subscription(tenant_id: uuid.UUID, body: SubscriptionAdminIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Manual override (comps, extended trials, corrections). Does not touch Razorpay: a live Razorpay subscription keeps billing."""
    t = _tenant_or_404(ctx, tenant_id)
    sub = ctx.db.scalar(select(Subscription).where(Subscription.tenant_id == t.id).with_for_update())
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription")
    before = billing_svc.snapshot(sub)
    if body.plan:
        plan = ctx.db.get(BillingPlan, body.plan)
        if plan is None:
            raise HTTPException(status_code=422, detail="Unknown plan")
        billing_svc.apply_plan(sub, plan)
    if body.status:
        sub.status = body.status
        if body.status in ("manual", "active") and not sub.razorpay_subscription_id:
            sub.source = "manual"
        if body.status != "trialing":
            sub.past_due_since = None
    if body.extend_trial_days:
        base = max(sub.trial_ends_at or utcnow(), utcnow())
        sub.trial_ends_at = base + timedelta(days=body.extend_trial_days)
        sub.status = "trialing" if not body.status else body.status
    billing_svc.record_change(ctx.db, sub, before, source="admin", kind="admin_override", meta={"note": body.note, "extend_trial_days": body.extend_trial_days, "by": str(ctx.user.id)})
    audit(ctx.db, action="admin.subscription_override", tenant_id=t.id, user_id=ctx.user.id, entity_type="subscription", entity_id=sub.id,
          meta={"plan": body.plan, "status": body.status, "extend_trial_days": body.extend_trial_days, "note": body.note,
                "razorpay_live": bool(sub.razorpay_subscription_id)}, ip=client_ip(request))
    ctx.db.commit()
    return {"plan": sub.plan, "status": sub.status, "trial_ends_at": sub.trial_ends_at, "source": sub.source}


@router.get("/subscriptions")
def subscriptions(ctx: AuthContext = Depends(require_platform_admin), status: str | None = None, plan: str | None = None,
                  limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    q = select(Subscription, Tenant.name).join(Tenant, Tenant.id == Subscription.tenant_id)
    if status:
        q = q.where(Subscription.status == status)
    if plan:
        q = q.where(Subscription.plan == plan)
    rows = ctx.db.execute(q.order_by(Subscription.created_at.desc()).limit(limit).offset(offset)).all()
    return [{"tenant_id": s.tenant_id, "tenant": name, "plan": s.plan, "status": s.status, "source": s.source, "trial_ends_at": s.trial_ends_at,
             "current_period_end": s.current_period_end, "cancel_at_period_end": s.cancel_at_period_end, "razorpay_subscription_id": s.razorpay_subscription_id,
             "provider": s.provider, "cashfree_subscription_id": s.cashfree_subscription_id, "authorization_status": s.authorization_status,
             "first_charge_at": s.first_charge_at, "next_charge_at": s.next_charge_at, "pending_plan": s.pending_plan, "past_due_since": s.past_due_since} for s, name in rows]


@router.get("/payments")
def all_payments(ctx: AuthContext = Depends(require_platform_admin), kind: str | None = None, status: str | None = None,
                 tenant_id: uuid.UUID | None = None, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    q = select(Payment, Tenant.name).join(Tenant, Tenant.id == Payment.tenant_id)
    if kind:
        q = q.where(Payment.kind == kind)
    if status:
        q = q.where(Payment.status == status)
    if tenant_id:
        q = q.where(Payment.tenant_id == tenant_id)
    rows = ctx.db.execute(q.order_by(Payment.created_at.desc()).limit(limit).offset(offset)).all()
    return [{"id": p.id, "tenant_id": p.tenant_id, "tenant": name, "kind": p.kind, "status": p.status, "amount_paise": p.amount_paise,
             "razorpay_payment_id": p.razorpay_payment_id, "error_description": p.error_description, "created_at": p.created_at, "paid_at": p.paid_at,
             "provider": p.provider, "cashfree_payment_id": p.cashfree_payment_id, "payment_type": p.payment_type, "failure_reason": p.failure_reason} for p, name in rows]


@router.get("/webhooks")
def webhook_events(ctx: AuthContext = Depends(require_platform_admin), status: str | None = None, limit: int = Query(100, ge=1, le=200)):
    """Provider events as they arrived: the type, our subscription reference, whether they were processed, and a short safe failure note. The payload itself is not stored."""
    q = select(WebhookEvent).where(WebhookEvent.provider == "cashfree")
    if status:
        q = q.where(WebhookEvent.status == status)
    rows = ctx.db.scalars(q.order_by(WebhookEvent.received_at.desc()).limit(limit)).all()
    return [{"id": r.id, "type": r.event_type, "status": r.status, "attempts": r.attempts, "subscription_ref": r.subscription_ref, "payment_ref": r.payment_ref,
             "received_at": r.received_at, "processed_at": r.processed_at, "provider_event_time": r.provider_event_time, "last_error": r.last_error} for r in rows]


@router.post("/webhooks/{event_id}/reprocess")
def reprocess_webhook(event_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Re-reads the subscription from Cashfree and applies it. It cannot mark anything paid: only what Cashfree itself reports can change a subscription."""
    from app.services import billing_cashfree as cfb
    from app.services import cashfree as cashfree_svc
    row = ctx.db.get(WebhookEvent, event_id)
    if row is None or row.provider != "cashfree":
        raise HTTPException(status_code=404, detail="Not found")
    sub = ctx.db.scalar(select(Subscription).where(Subscription.cashfree_subscription_id == row.subscription_ref)) if row.subscription_ref else None
    if sub is None:
        raise HTTPException(status_code=409, detail="This event does not belong to any subscription")
    try:
        client = cashfree_svc.get_cashfree()
        cfb.sync(ctx.db, client, sub, source="admin", ref=str(row.id)[:16])
    except cashfree_svc.CashfreeNotConfigured:
        raise HTTPException(status_code=503, detail="Billing is not configured")
    except cashfree_svc.CashfreeError:
        ctx.db.rollback()
        raise HTTPException(status_code=502, detail="Cashfree could not be reached")
    row.status, row.processed_at, row.last_error, row.attempts = "processed", utcnow(), None, (row.attempts or 0) + 1
    audit(ctx.db, action="admin.webhook_reprocess", user_id=ctx.user.id, tenant_id=sub.tenant_id, entity_type="webhook_event", entity_id=row.id, ip=client_ip(request))
    ctx.db.commit()
    return {"status": "processed", "subscription_status": sub.status}


@router.get("/card-orders")
def all_card_orders(ctx: AuthContext = Depends(require_platform_admin), status: str | None = None, limit: int = Query(100, ge=1, le=200)):
    q = select(CardOrder, Tenant.name).join(Tenant, Tenant.id == CardOrder.tenant_id)
    if status:
        q = q.where(CardOrder.status == status)
    rows = ctx.db.execute(q.order_by(CardOrder.created_at.desc()).limit(limit)).all()
    return [{"id": o.id, "tenant_id": o.tenant_id, "tenant": name, "quantity": o.quantity, "amount_paise": o.amount_paise, "status": o.status,
             "shipping": o.shipping, "tracking_note": o.tracking_note, "created_at": o.created_at} for o, name in rows]


@router.patch("/card-orders/{order_id}")
def update_card_order(order_id: uuid.UUID, body: CardOrderAdminIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    o = ctx.db.get(CardOrder, order_id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    if o.status not in ("paid", "processing", "shipped") and body.status != "cancelled":
        raise HTTPException(status_code=409, detail="Only paid orders can be fulfilled")  # never ship before Razorpay confirmed payment
    o.status = body.status
    o.tracking_note = body.tracking_note or o.tracking_note
    audit(ctx.db, action="admin.card_order_update", tenant_id=o.tenant_id, user_id=ctx.user.id, entity_type="card_order", entity_id=o.id, meta={"status": body.status}, ip=client_ip(request))
    ctx.db.commit()
    return {"status": o.status}


@router.get("/ai-usage")
def ai_usage(ctx: AuthContext = Depends(require_platform_admin)):
    rows = ctx.db.execute(
        select(Tenant.id, Tenant.name, func.count(AIGenerationLog.id), func.count(AIGenerationLog.id).filter(AIGenerationLog.status != "ok"), Subscription.monthly_ai_generations)
        .select_from(Tenant).outerjoin(AIGenerationLog, (AIGenerationLog.tenant_id == Tenant.id) & (AIGenerationLog.created_at >= month_start()))
        .outerjoin(Subscription, Subscription.tenant_id == Tenant.id).group_by(Tenant.id, Tenant.name, Subscription.monthly_ai_generations)
        .order_by(func.count(AIGenerationLog.id).desc())).all()
    return [{"tenant_id": i, "tenant": n, "generations": c, "errors": int(e), "monthly_limit": lim} for i, n, c, e, lim in rows]


@router.get("/audit")
def audit_history(ctx: AuthContext = Depends(require_platform_admin), tenant_id: uuid.UUID | None = None, action: str | None = Query(None, max_length=64),
                  limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    q = select(AuditLog, User.email, Tenant.name).outerjoin(User, User.id == AuditLog.user_id).outerjoin(Tenant, Tenant.id == AuditLog.tenant_id)
    if tenant_id:
        q = q.where(AuditLog.tenant_id == tenant_id)
    if action:
        q = q.where(AuditLog.action.ilike(f"{action}%"))
    rows = ctx.db.execute(q.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)).all()
    return [{"id": a.id, "action": a.action, "created_at": a.created_at, "user": email, "tenant": tname, "tenant_id": a.tenant_id, "entity_type": a.entity_type, "meta": a.meta} for a, email, tname in rows]


@router.get("/stats")
def platform_stats(ctx: AuthContext = Depends(require_platform_admin)):
    db = ctx.db
    by_status = dict(db.execute(select(QRCard.status, func.count()).group_by(QRCard.status)).all())
    events = dict(db.execute(select(ScanEvent.event_type, func.count()).where(ScanEvent.is_bot.is_(False)).group_by(ScanEvent.event_type)).all())
    subs = dict(db.execute(select(Subscription.status, func.count()).group_by(Subscription.status)).all())
    prices = {p.code: p.price_paise for p in db.scalars(select(BillingPlan))}
    mrr = sum(prices.get(s.plan, 0) for s in db.scalars(select(Subscription).where(Subscription.status == "active", Subscription.source == "razorpay")))
    since = utcnow() - timedelta(days=30)
    signups = dict(db.execute(select(func.date(Tenant.created_at), func.count()).where(Tenant.created_at >= since).group_by(func.date(Tenant.created_at))).all())
    revenue = dict(db.execute(select(Payment.kind, func.coalesce(func.sum(Payment.amount_paise), 0)).where(Payment.status == "captured").group_by(Payment.kind)).all())
    return {
        "tenants": db.scalar(select(func.count()).select_from(Tenant)), "suspended_tenants": db.scalar(select(func.count()).select_from(Tenant).where(Tenant.is_active.is_(False))),
        "open_support": db.scalar(select(func.count()).select_from(Tenant).where(Tenant.support_status.in_(["open", "waiting"]))),
        "locations": db.scalar(select(func.count()).select_from(Location)), "synced_reviews": db.scalar(select(func.count()).select_from(Review)),
        "cards_by_status": {k.value: v for k, v in by_status.items()}, "events": {k.value: v for k, v in events.items()},
        "subscriptions_by_status": subs, "mrr_paise": mrr,
        "revenue_paise": {"subscription": int(revenue.get("subscription", 0)), "card_order": int(revenue.get("card_order", 0))},
        "signups_30d": [{"date": (since + timedelta(days=i + 1)).date().isoformat(), "count": signups.get((since + timedelta(days=i + 1)).date(), 0)} for i in range(30)],
        "ai_generations_this_month": db.scalar(select(func.count()).select_from(AIGenerationLog).where(AIGenerationLog.created_at >= month_start())),
    }


# ---------------------------------------------------------------------------------------------------------------------------------------------
# plan catalogue: what each plan includes, and the limits the owner has not approved yet
# ---------------------------------------------------------------------------------------------------------------------------------------------
def _plan_out(p: BillingPlan) -> dict:
    from app.core.config import settings

    return {"code": p.code, "name": p.name, "price_paise": p.price_paise, "currency": p.currency, "active": p.is_active, "retired": not p.is_active, "max_locations": p.max_locations,
            "max_staff": p.max_staff, "review_generations": p.review_generations, "review_replies": p.review_replies, "features": list(p.features or []), "limits": p.limits or {},
            "pending_owner_configuration": plans_svc.pending_limits(p.limits) if p.is_active else [], "razorpay_plan_id": p.razorpay_plan_id}


@router.get("/plans")
def list_plans(ctx: AuthContext = Depends(require_platform_admin)):
    """Every plan, with the limits that are still waiting for an owner decision (those features stay OFF until they are set), and the assumptions this catalogue makes."""
    from app.core.config import settings

    rows = ctx.db.scalars(select(BillingPlan).order_by(BillingPlan.sort_order)).all()
    return {"plans": [_plan_out(p) for p in rows], "assumptions": list(plans_svc.ASSUMPTIONS), "unapproved_limits": plans_svc.UNAPPROVED_LIMITS,
            "promotion": {"plan": settings.promo_card_plan, "days": settings.promo_card_days, "max_per_business": settings.promo_max_grants_per_business,
                          "owner_decision_pending": ["how long 'one month' is (30 days assumed)", "whether a second card order earns a second month (no, assumed)"]},
            "card_offers": settings.card_offers,
            "quota_rule": "Review generations and AI replies are separate monthly allowances. Posts, descriptions and the growth agent have no per-plan count: they are limited by the plan feature and the USD budgets."}


@router.put("/plans/{code}/limits")
def set_plan_limits(code: str, body: PlanLimitsIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Approve (or clear) a plan's map allowances. All three numbers or none: a half-configured plan is an unconfigured plan, and maps stay off."""
    plan = ctx.db.get(BillingPlan, code)
    if plan is None:
        raise HTTPException(status_code=404, detail="Unknown plan")
    vals = body.geo.model_dump()
    if any(v is not None for v in vals.values()) and any(v is None for v in vals.values()):
        raise HTTPException(status_code=422, detail="Set max_grids, max_points and monthly_points together, or clear all three.")
    before = dict((plan.limits or {}).get("geo") or {})
    plan.limits = {**(plan.limits or {}), "geo": vals}
    updated = 0
    if body.apply_to_existing:
        from app.core.config import settings

        cond = (Subscription.plan == code) | (Subscription.plan == "trial") if settings.trial_plan == code else (Subscription.plan == code)  # trials carry the trial plan's limits
        for sub in ctx.db.scalars(select(Subscription).where(cond)):
            sub.limits = {**(sub.limits or {}), "geo": vals}
            updated += 1
    audit(ctx.db, action="admin.plan_limits", user_id=ctx.user.id, entity_type="billing_plan", entity_id=None, meta={"plan": code, "before": before, "after": vals,
          "note": body.note, "subscriptions_updated": updated}, ip=client_ip(request))
    ctx.db.commit()
    return {**_plan_out(plan), "subscriptions_updated": updated}


# ---------------------------------------------------------------------------------------------------------------------------------------------
# usage, cost and finance (every figure says whether it is actual, estimated or missing)
# ---------------------------------------------------------------------------------------------------------------------------------------------
_MONTH = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM, default the current month")


@router.get("/costs")
def costs(month: str | None = _MONTH, top: int = Query(20, ge=1, le=500), ctx: AuthContext = Depends(require_platform_admin)):
    """AI and Google/Places usage and cost for a month: by feature, by operation, by business, with failed and refused calls. A call with no configured price is counted but never priced at zero."""
    return finance_svc.costs(ctx.db, month, top)


@router.get("/finance")
def finance(month: str | None = _MONTH, ctx: AuthContext = Depends(require_platform_admin)):
    """MRR, one-time card revenue, costs and unit economics. Missing inputs are listed, never assumed to be zero."""
    return finance_svc.economics(ctx.db, month)


class AllowlistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    note: str | None = Field(default=None, max_length=300)


@router.get("/registration")
def registration_status(ctx: AuthContext = Depends(require_platform_admin)):
    """Who may register: the mode, how many addresses come from the environment and from the administrator list, and the administrator-managed list itself."""
    from app.services import registration as reg

    return reg.summary(ctx.db)


@router.post("/registration/allowlist", status_code=201)
def registration_allow(body: AllowlistIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    from app.services import registration as reg

    try:
        row = reg.add(ctx.db, body.email, note=body.note, user_id=ctx.user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    audit(ctx.db, action="admin.registration_allow", user_id=ctx.user.id, entity_type="registration", entity_id=row.id, meta={"email": row.email, "note": row.note}, ip=client_ip(request))
    ctx.db.commit()
    return {"id": str(row.id), "email": row.email, "note": row.note}


@router.delete("/registration/allowlist/{entry_id}", status_code=204)
def registration_disallow(entry_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    from app.models import RegistrationAllowlist

    row = ctx.db.get(RegistrationAllowlist, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    email = row.email
    ctx.db.delete(row)
    audit(ctx.db, action="admin.registration_disallow", user_id=ctx.user.id, entity_type="registration", entity_id=entry_id, meta={"email": email}, ip=client_ip(request))
    ctx.db.commit()


@router.get("/work-queue")
def work_queue(limit: int = Query(50, ge=1, le=200), ctx: AuthContext = Depends(require_platform_admin)):
    """What needs a person across every business: failed or blocked Google changes and failed posts, approvals that have been waiting, and account deletion and export requests. Read-only, from real records."""
    from app.services import work_queue as wq

    return wq.snapshot(ctx.db, limit)


@router.put("/tenants/{tenant_id}/budgets")
def set_budgets(tenant_id: uuid.UUID, body: BudgetsIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Review and change one business's spending ceilings (AI dollars per month, Places searches per month). Audited with the reason."""
    t = _tenant_or_404(ctx, tenant_id)
    sent = body.model_fields_set - {"note"}
    before = {"ai_monthly_budget_usd": float(t.ai_monthly_budget_usd) if t.ai_monthly_budget_usd is not None else None, "places_monthly_cap": t.places_monthly_cap}
    if "ai_monthly_budget_usd" in sent:
        t.ai_monthly_budget_usd = body.ai_monthly_budget_usd
    if "places_monthly_cap" in sent:
        t.places_monthly_cap = body.places_monthly_cap
    after = {"ai_monthly_budget_usd": float(t.ai_monthly_budget_usd) if t.ai_monthly_budget_usd is not None else None, "places_monthly_cap": t.places_monthly_cap}
    audit(ctx.db, action="admin.budgets", tenant_id=t.id, user_id=ctx.user.id, entity_type="tenant", entity_id=t.id, meta={"before": before, "after": after, "note": body.note}, ip=client_ip(request))
    ctx.db.commit()
    return {"before": before, "after": after}


@router.get("/tenants/{tenant_id}/budgets")
def get_budgets(tenant_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    from app.services import ai_usage, usage as usage_svc

    t = _tenant_or_404(ctx, tenant_id)
    spend = ai_usage.spend_this_month(t.id)
    return {"ai_monthly_budget_usd": float(t.ai_monthly_budget_usd) if t.ai_monthly_budget_usd is not None else None, "ai_spent_usd": float(spend["usd"]) if ai_usage.price_known() else None,
            "ai_priced": ai_usage.price_known(), "places_monthly_cap": t.places_monthly_cap, "places_used_this_month": usage_svc.units_this_month(ctx.db, t.id)}


@router.get("/release-gates")
def release_gates(ctx: AuthContext = Depends(require_platform_admin)):
    """Which rungs of the release ladder have actually been passed, with the evidence. Read from app/release_gates.json (a person edits it when a rung is passed); nothing here is computed,
    so a test double can never turn a live rung green."""
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parents[2] / "release_gates.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"overall": "Unknown", "gates": [], "_about": "app/release_gates.json was not found in this deployment; nothing can be claimed passed."}



# ================================================================================================================================ destination, NFC status and analytics for one QR/NFC asset
class DestinationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=2100)
    reason: str | None = Field(default=None, max_length=300)
    confirm: bool = False


class DestinationClearIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=300)
    confirm: bool = False


class NfcIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    programmed: bool


def _destination_out(ctx: AuthContext, card: QRCard) -> dict:
    rows = dest_svc.history(ctx.db, card)
    users = {u.id: u.email for u in ctx.db.scalars(select(User).where(User.id.in_([r.changed_by for r in rows if r.changed_by])))} if rows else {}
    return {"url": card.destination_url, "set_at": card.destination_set_at, "default": "the card's review landing page" if not card.destination_url else None, "live": dest_svc.is_live(card),
            "history": [{"action": r.action, "old_url": r.old_url, "new_url": r.new_url, "reason": r.reason, "changed_by": users.get(r.changed_by), "changed_at": r.changed_at} for r in rows]}


def _dest_error(exc: "dest_svc.DestinationError") -> HTTPException:
    return HTTPException(status_code=422 if exc.code != "not_found" else 404, detail={"code": exc.code, "message": exc.message})


@router.get("/cards/{card_id}/destination")
def get_destination(card_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    return _destination_out(ctx, _card_or_404(ctx, card_id))


@router.post("/cards/{card_id}/destination/check")
def check_destination(card_id: uuid.UUID, body: DestinationIn, ctx: AuthContext = Depends(require_platform_admin)):
    """Validates an address WITHOUT saving or fetching it (a server that fetches admin-supplied addresses is an SSRF hole). The admin opens the cleaned address in their own browser to test it."""
    _card_or_404(ctx, card_id)
    try:
        url = dest_svc.normalise(body.url)
    except dest_svc.DestinationError as exc:
        raise _dest_error(exc)
    from urllib.parse import urlsplit
    return {"ok": True, "url": url, "host": urlsplit(url).hostname}


@router.put("/cards/{card_id}/destination")
def set_destination(card_id: uuid.UUID, body: DestinationIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    try:
        new = dest_svc.normalise(body.url)
    except dest_svc.DestinationError as exc:
        raise _dest_error(exc)
    if dest_svc.is_live(card) and not body.confirm and (card.destination_url or None) != new:
        raise svc.confirmation_required("This card is live. Everyone who scans or taps it from now on will be sent to the new address. The printed QR and the NFC tag do not change.",
                                        {"destination": card.destination_url or "the review landing page"}, {"destination": new})
    try:
        card, changed = dest_svc.set_destination(ctx.db, card_id, new, by=ctx.user.id, reason=body.reason)
    except dest_svc.DestinationError as exc:
        ctx.db.rollback()
        raise _dest_error(exc)
    ctx.db.commit()
    return {"changed": changed, **_destination_out(ctx, card)}


@router.post("/cards/{card_id}/destination/clear")
def clear_destination(card_id: uuid.UUID, body: DestinationClearIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Back to the card's normal review landing page. Same confirmation rule as setting one."""
    card = _card_or_404(ctx, card_id)
    if card.destination_url and dest_svc.is_live(card) and not body.confirm:
        raise svc.confirmation_required("This card is live. Scans and taps will go back to its normal review page.", {"destination": card.destination_url}, {"destination": "the review landing page"})
    try:
        card, changed = dest_svc.clear_destination(ctx.db, card_id, by=ctx.user.id, reason=body.reason)
    except dest_svc.DestinationError as exc:
        ctx.db.rollback()
        raise _dest_error(exc)
    ctx.db.commit()
    return {"changed": changed, **_destination_out(ctx, card)}


@router.get("/cards/{card_id}/nfc")
def get_nfc(card_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    return {"nfc_url": card_nfc_url(card.public_token), "qr_url": card_qr_url(card), **svc.nfc_status(ctx.db, card),
            "instructions": ["Open an NFC writer app (for example NFC Tools or NFC TagWriter) on an NFC-capable phone.",
                             "Choose Write, Add a record, then URL / URI, and paste the NFC address above exactly.",
                             "Hold the blank tag to the phone and write it. Do not lock the tag until you have tested it.",
                             "Tap the written tag with a second phone: the review page (or the destination) should open. That tap is recorded and confirms the tag here.",
                             "Then press 'Mark as programmed'. FlowQR records your statement; it cannot write or read the tag itself."]}


@router.post("/cards/{card_id}/nfc")
def set_nfc(card_id: uuid.UUID, body: NfcIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """An admin's statement that this card's NFC tag was (or was not) written. Audited. It never claims FlowQR wrote the tag."""
    card = ctx.db.scalar(select(QRCard).where(QRCard.id == card_id).with_for_update())
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    if card.status in (CardStatus.retired, CardStatus.deactivated, CardStatus.lost):
        raise HTTPException(status_code=409, detail={"code": "card_dead", "message": "This card is out of use."})
    before = card.nfc_programmed_at
    card.nfc_programmed_at, card.nfc_programmed_by = (utcnow(), ctx.user.id) if body.programmed else (None, None)
    audit(ctx.db, action="admin.card_nfc_marked" if body.programmed else "admin.card_nfc_unmarked", tenant_id=card.tenant_id, user_id=ctx.user.id, entity_type="card", entity_id=card.id,
          meta={"was_marked": before is not None}, ip=client_ip(request))
    ctx.db.commit()
    return svc.nfc_status(ctx.db, card)


@router.get("/cards/{card_id}/analytics")
def card_analytics(card_id: uuid.UUID, days: int = Query(30, ge=1, le=365), ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    return {"card_code": card.card_code, **svc.card_analytics(ctx.db, card_ids=[card.id], days=days)}


@router.get("/cards-analytics")
def cards_analytics(days: int = Query(30, ge=1, le=365), batch_id: uuid.UUID | None = None, tenant_id: uuid.UUID | None = None, location_id: uuid.UUID | None = None,
                    campaign_id: uuid.UUID | None = None, ctx: AuthContext = Depends(require_platform_admin)):
    """Scans and taps across a batch, a business, a location or a campaign (or everything)."""
    q = select(QRCard.id)
    for col, val in ((QRCard.batch_id, batch_id), (QRCard.tenant_id, tenant_id), (QRCard.location_id, location_id), (QRCard.campaign_id, campaign_id)):
        if val:
            q = q.where(col == val)
    return svc.card_analytics(ctx.db, card_filter=q, days=days)
