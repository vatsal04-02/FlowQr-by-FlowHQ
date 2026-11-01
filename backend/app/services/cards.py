import hashlib
import re
import secrets
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    CardAssignment, CardBatch, CardStatus, Location, QRCard, ScanEvent, ScanEventType, Tenant,
)
from app.models.base import utcnow

BOT_PATTERN = re.compile(
    r"bot|crawl|spider|slurp|preview|fetch|monitor|headless|curl|wget|python|httpclient|okhttp|java/|go-http|"
    r"facebookexternalhit|whatsapp|telegram|discord|skype|embedly|pingdom|uptime|lighthouse|scanner|checker",
    re.I,
)
LIVE_STATUSES = {CardStatus.assigned, CardStatus.active}


def is_bot(user_agent: str | None) -> bool:
    return not user_agent or bool(BOT_PATTERN.search(user_agent))


def visitor_hash(ip: str, user_agent: str | None) -> str:
    day = utcnow().strftime("%Y-%m-%d")
    raw = f"{settings.secret_key}|{day}|{ip}|{user_agent or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def new_public_token() -> str:
    return secrets.token_urlsafe(18)  # 144 bits of entropy, 24 chars


def create_batch(db: Session, *, name: str, quantity: int, prefix: str, created_by: uuid.UUID, notes: str | None) -> CardBatch:
    batch = CardBatch(name=name, prefix=prefix, quantity=quantity, created_by=created_by, notes=notes)
    db.add(batch)
    db.flush()
    nums = db.scalars(text("SELECT nextval('card_code_seq') FROM generate_series(1, :n)"), {"n": quantity}).all()
    for n in nums:
        db.add(QRCard(card_code=f"{prefix}-{n:04d}", public_token=new_public_token(), batch_id=batch.id,
                      status=CardStatus.unassigned))
    try:
        db.flush()
    except IntegrityError:  # astronomically unlikely token collision
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not generate unique tokens, please retry")
    return batch


def assign_card(db: Session, card: QRCard, *, tenant: Tenant, location: Location, by: uuid.UUID | None) -> QRCard:
    """Point a card at a tenant location, preserving history. Caller commits."""
    if location.tenant_id != tenant.id:
        raise HTTPException(status_code=400, detail="Location does not belong to this business")
    now = utcnow()
    if card.tenant_id:
        close_open_assignment(db, card)
    card.tenant_id = tenant.id
    card.location_id = location.id
    card.assigned_at = now
    if card.status in (CardStatus.unassigned, CardStatus.lost):
        card.status = CardStatus.assigned
    db.add(CardAssignment(card_id=card.id, tenant_id=tenant.id, location_id=location.id, assigned_by=by, assigned_at=now))
    return card


def close_open_assignment(db: Session, card: QRCard) -> None:
    now = utcnow()
    for a in db.scalars(select(CardAssignment).where(CardAssignment.card_id == card.id, CardAssignment.unassigned_at.is_(None))):
        a.unassigned_at = now


def unassign_card(db: Session, card: QRCard) -> QRCard:
    close_open_assignment(db, card)
    card.tenant_id = None
    card.location_id = None
    card.assigned_at = None
    card.label = None
    card.status = CardStatus.unassigned
    return card


def record_event(db: Session, card: QRCard | None, event_type: ScanEventType, *, ip: str, ua: str | None) -> ScanEvent:
    ev = ScanEvent(
        card_id=card.id if card else None,
        tenant_id=card.tenant_id if card else None,
        location_id=card.location_id if card else None,
        event_type=event_type,
        visitor_hash=visitor_hash(ip, ua),
        is_bot=is_bot(ua),
        created_at=utcnow(),
    )
    db.add(ev)
    return ev


def card_scan_counts(db: Session, card_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    if not card_ids:
        return {}
    rows = db.execute(
        select(ScanEvent.card_id, ScanEvent.event_type, func.count())
        .where(ScanEvent.card_id.in_(card_ids), ScanEvent.is_bot.is_(False))
        .group_by(ScanEvent.card_id, ScanEvent.event_type)
    ).all()
    out: dict[uuid.UUID, dict[str, int]] = {cid: {} for cid in card_ids}
    for cid, et, n in rows:
        out[cid][et.value] = n
    return out
