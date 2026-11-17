import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    CardAssignment, CardBatch, CardStatus, Location, QRCard, ReviewCampaign, ScanEvent, ScanEventType, Tenant,
)
from app.models.base import utcnow

BOT_PATTERN = re.compile(
    r"bot|crawl|spider|slurp|preview|fetch|monitor|headless|curl|wget|python|httpclient|okhttp|java/|go-http|"
    r"facebookexternalhit|whatsapp|telegram|discord|skype|embedly|pingdom|uptime|lighthouse|scanner|checker",
    re.I,
)
LIVE_STATUSES = {CardStatus.assigned, CardStatus.active}
STOCK_STATUSES = {CardStatus.generated, CardStatus.unassigned, CardStatus.archived}  # belongs to nobody
OWNED_STATUSES = {CardStatus.reserved, CardStatus.assigned, CardStatus.active, CardStatus.paused}  # belongs to one business
DEAD_STATUSES = {CardStatus.retired, CardStatus.deactivated, CardStatus.lost}
CHANNELS = ("qr", "nfc")


def is_bot(user_agent: str | None) -> bool:
    return not user_agent or bool(BOT_PATTERN.search(user_agent))


def visitor_hash(ip: str, user_agent: str | None) -> str:
    day = utcnow().strftime("%Y-%m-%d")
    raw = f"{settings.secret_key}|{day}|{ip}|{user_agent or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def new_public_token() -> str:
    return secrets.token_urlsafe(18)  # 144 bits from the OS CSPRNG, 24 URL-safe chars


def new_public_tokens(db: Session, count: int) -> list[str]:
    """`count` tokens that are distinct from each other AND from every token already issued. A collision between random
    144-bit values is not expected in the lifetime of the universe; this makes "not expected" into "cannot happen", and the
    UNIQUE constraint on qr_cards.public_token still backs it at the database."""
    tokens: set[str] = set()
    while len(tokens) < count:
        fresh = {new_public_token() for _ in range(count - len(tokens))} - tokens
        taken = set(db.scalars(select(QRCard.public_token).where(QRCard.public_token.in_(fresh))))
        tokens |= fresh - taken
    return list(tokens)


def create_batch(db: Session, *, name: str, quantity: int, prefix: str, created_by: uuid.UUID, notes: str | None) -> CardBatch:
    batch = CardBatch(name=name, prefix=prefix, quantity=quantity, created_by=created_by, notes=notes,
                      base_url=settings.public_card_base_url.rstrip("/"))
    db.add(batch)
    db.flush()
    nums = db.scalars(text("SELECT nextval('card_code_seq') FROM generate_series(1, :n)"), {"n": quantity}).all()
    for n, token in zip(nums, new_public_tokens(db, len(nums))):
        db.add(QRCard(card_code=f"{prefix}-{n:04d}", public_token=token, batch_id=batch.id,
                      status=CardStatus.generated, qr_path="q"))
    try:
        db.flush()
    except IntegrityError:  # astronomically unlikely token collision
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not generate unique tokens, please retry")
    return batch


def confirmation_required(message: str, current: dict, new: dict) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "confirmation_required", "message": message, "current": current, "new": new})


def _target(business: str | None, location: str | None, campaign: str | None) -> dict:
    return {"business": business, "location": location, "campaign": campaign}


def check_campaign(db: Session, campaign_id: uuid.UUID | None, tenant: Tenant, location: Location) -> ReviewCampaign | None:
    """The campaign a card should open, or None for the plain card page. It must belong to this business and this location."""
    if campaign_id is None:
        return None
    c = db.scalar(select(ReviewCampaign).where(ReviewCampaign.id == campaign_id, ReviewCampaign.tenant_id == tenant.id))
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.status == "archived":
        raise HTTPException(status_code=400, detail="That campaign is archived. Choose an active one.")
    if c.location_id and c.location_id != location.id:
        raise HTTPException(status_code=400, detail="That campaign belongs to a different location.")
    return c


def assign_card(db: Session, card: QRCard, *, tenant: Tenant, location: Location, by: uuid.UUID | None,
                campaign: ReviewCampaign | None = None, confirm: bool = False, activate: bool = False) -> QRCard:
    """Point a card at a tenant location (and optionally a review campaign), preserving history. Caller commits.
    Changing where a card that is already in use points requires `confirm`: the printed code stays the same, so this is
    the moment a business's customers start landing somewhere else."""
    if card.status == CardStatus.retired:
        raise HTTPException(status_code=409, detail="This card has been retired and cannot be used again.")
    if location.tenant_id != tenant.id:
        raise HTTPException(status_code=400, detail="Location does not belong to this business")
    if not location.is_active:
        # Pointing a printed card at a deactivated location would make it show "no longer active": refuse instead of breaking it.
        raise HTTPException(status_code=400, detail="This location is deactivated. Reactivate it first, or choose another location, so the card keeps working.")
    if campaign is not None and (campaign.tenant_id != tenant.id or (campaign.location_id and campaign.location_id != location.id)):
        raise HTTPException(status_code=400, detail="That campaign does not belong to this business and location.")
    new_campaign = campaign.id if campaign else None
    in_use = bool(card.status in (CardStatus.assigned, CardStatus.active, CardStatus.paused) and card.tenant_id)
    same = card.tenant_id == tenant.id and card.location_id == location.id and card.campaign_id == new_campaign
    if in_use and not same and not confirm:
        old_t = db.get(Tenant, card.tenant_id)
        old_l = db.get(Location, card.location_id) if card.location_id else None
        old_c = db.get(ReviewCampaign, card.campaign_id) if card.campaign_id else None
        raise confirmation_required(
            "This card is already in use. Changing it sends everyone who scans or taps it to the new destination straight away. The printed code does not change.",
            _target(old_t.name if old_t else None, old_l.name if old_l else None, old_c.name if old_c else None),
            _target(tenant.name, location.name, campaign.name if campaign else None))
    now = utcnow()
    was = card.status
    if card.tenant_id and not same:
        close_open_assignment(db, card, "reassigned" if in_use else "assigned")
    card.tenant_id = tenant.id
    card.location_id = location.id
    card.campaign_id = new_campaign
    if not same or not card.assigned_at:
        card.assigned_at = now
        db.add(CardAssignment(card_id=card.id, tenant_id=tenant.id, location_id=location.id, campaign_id=new_campaign, assigned_by=by, assigned_at=now))
    if was in (CardStatus.generated, CardStatus.unassigned, CardStatus.reserved, CardStatus.lost, CardStatus.archived):
        card.status = CardStatus.assigned
    if activate and card.status == CardStatus.assigned:
        card.status = CardStatus.active
    return card


def close_open_assignment(db: Session, card: QRCard, reason: str | None = None) -> None:
    now = utcnow()
    for a in db.scalars(select(CardAssignment).where(CardAssignment.card_id == card.id, CardAssignment.unassigned_at.is_(None))):
        a.unassigned_at = now
        a.ended_reason = reason or a.ended_reason


def unassign_card(db: Session, card: QRCard, reason: str = "unassigned") -> QRCard:
    if card.status == CardStatus.retired:
        raise HTTPException(status_code=409, detail="This card has been retired and cannot be returned to stock.")
    close_open_assignment(db, card, reason)
    card.tenant_id = None
    card.location_id = None
    card.campaign_id = None
    card.assigned_at = None
    card.label = None
    card.status = CardStatus.unassigned
    return card


def reserve_card(db: Session, card: QRCard, tenant: Tenant, by: uuid.UUID | None) -> QRCard:
    """Set a card aside for one business. It belongs to them (they can see it and give it a location) but is not live."""
    if card.status not in (CardStatus.generated, CardStatus.unassigned):
        raise HTTPException(status_code=409, detail=f"Only cards in stock can be reserved (this one is {card.status.value}).")
    card.tenant_id, card.location_id, card.campaign_id, card.status = tenant.id, None, None, CardStatus.reserved
    db.add(CardAssignment(card_id=card.id, tenant_id=tenant.id, location_id=None, assigned_by=by, assigned_at=utcnow()))
    return card


def retire_card(db: Session, card: QRCard, *, confirm: bool) -> QRCard:
    """Permanently take a card out of use. Scans show 'no longer active' from now on. History is kept; it cannot come back."""
    if card.status == CardStatus.retired:
        return card
    if not confirm:
        t = db.get(Tenant, card.tenant_id) if card.tenant_id else None
        raise confirmation_required(
            "Retiring a card is permanent. Anyone who scans or taps it will see that it is no longer active, and it can never be used again. Its history is kept.",
            _target(t.name if t else None, None, None), {"status": "retired"})
    close_open_assignment(db, card, "retired")
    card.status = CardStatus.retired
    card.retired_at = utcnow()
    return card


def archive_card(card: QRCard) -> QRCard:
    if card.status not in (CardStatus.generated, CardStatus.unassigned):
        raise HTTPException(status_code=409, detail="Only cards in stock can be archived.")
    card.status = CardStatus.archived
    return card


def unarchive_card(card: QRCard) -> QRCard:
    if card.status != CardStatus.archived:
        raise HTTPException(status_code=409, detail="This card is not archived.")
    card.status = CardStatus.unassigned
    return card


def release_batch(db: Session, batch: CardBatch) -> int:
    """Mark a batch as printed and in stock: every card still 'generated' becomes 'unassigned'. Returns how many changed."""
    n = 0
    for c in db.scalars(select(QRCard).where(QRCard.batch_id == batch.id, QRCard.status == CardStatus.generated)):
        c.status = CardStatus.unassigned
        n += 1
    batch.released_at = batch.released_at or utcnow()
    return n


SERIAL_PATTERN = re.compile(r"^[A-Za-z]{2,6}-\d{1,8}$")


def parse_scan(text: str) -> tuple[str, str]:
    """What a scanned or typed value refers to: ('token', value) or ('serial', CODE). Accepts a card's /q/, /n/ or /c/ link, the
    bare token, or the printed serial. A campaign link (/r/) is a different thing and is refused with a clear message."""
    from urllib.parse import urlsplit

    raw = (text or "").strip()
    if not raw or len(raw) > 600:
        raise HTTPException(status_code=422, detail="Nothing to look up. Scan a card or type its serial number.")
    if "://" in raw:
        path = [x for x in urlsplit(raw).path.split("/") if x]
        if len(path) >= 2 and path[-2] in ("c", "q", "n") and TOKEN_PATTERN.match(path[-1]):
            return "token", path[-1]
        if len(path) >= 2 and path[-2] == "r":
            raise HTTPException(status_code=422, detail="That is a review campaign code, not a card. Scan the code on the physical card.")
        raise HTTPException(status_code=422, detail="That is not a FlowQR card link.")
    if SERIAL_PATTERN.match(raw):
        return "serial", raw.upper()
    if TOKEN_PATTERN.match(raw):
        return "token", raw
    raise HTTPException(status_code=422, detail="That is not a FlowQR card. Check the serial number (like FQR-0001) or scan again.")


def find_by_scan(db: Session, text: str) -> QRCard | None:
    kind, value = parse_scan(text)
    col = QRCard.public_token if kind == "token" else QRCard.card_code
    return db.scalar(select(QRCard).where(col == value))


def status_counts(db: Session, batch_id: uuid.UUID | None = None) -> dict[str, int]:
    q = select(QRCard.status, func.count()).group_by(QRCard.status)
    if batch_id:
        q = q.where(QRCard.batch_id == batch_id)
    out = {st.value: 0 for st in CardStatus}
    for st, n in db.execute(q):
        out[st.value] = n
    return out


_HOST_ONLY = re.compile(r"^(?=.{1,120}$)[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


def referrer_host(value: str | None) -> str | None:
    """The host of a referring page, or None. Host ONLY: a path or query could carry personal data, so it is never kept. Accepts a bare host or a full URL."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if "://" in v:
        from urllib.parse import urlsplit
        try:
            v = (urlsplit(v).hostname or "")
        except ValueError:
            return None
    v = v.rstrip(".")
    return v if _HOST_ONLY.match(v) and "." in v else None


def device_category(ua: str | None) -> str:
    """mobile | tablet | desktop | other, from the user agent (coarse on purpose: no model, no version)."""
    u = (ua or "").lower()
    if not u or is_bot(ua):
        return "other"
    if "ipad" in u or "tablet" in u or ("android" in u and "mobile" not in u):
        return "tablet"
    if "mobile" in u or "iphone" in u or "android" in u:
        return "mobile"
    if any(k in u for k in ("windows", "macintosh", "x11", "linux", "cros")):
        return "desktop"
    return "other"


def record_event(db: Session, card: QRCard | None, event_type: ScanEventType, *, ip: str, ua: str | None, channel: str | None = None, referrer: str | None = None) -> ScanEvent:
    ev = ScanEvent(
        referrer_host=referrer_host(referrer), device=device_category(ua), placement=(card.label[:120] if card and card.label else None), campaign_id=card.campaign_id if card else None,
        channel=channel if channel in CHANNELS else None,
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


NFC_NOTE = ("FlowQR cannot write NFC tags. 'Marked programmed' is an administrator's statement; only a real tap on the tag (an NFC visit recorded after it was marked) confirms it works.")


def nfc_status(db: Session, card: QRCard) -> dict:
    """not_programmed | marked_programmed (an admin said so) | tap_seen (a real NFC tap has opened this card since). Never claims more than the evidence."""
    q = select(func.max(ScanEvent.created_at)).where(ScanEvent.card_id == card.id, ScanEvent.channel == "nfc", ScanEvent.event_type == ScanEventType.scan, ScanEvent.is_bot.is_(False))
    if card.nfc_programmed_at:
        q = q.where(ScanEvent.created_at >= card.nfc_programmed_at)
    last_tap = db.scalar(q)
    status = "tap_seen" if last_tap else "marked_programmed" if card.nfc_programmed_at else "not_programmed"
    return {"status": status, "programmed_at": card.nfc_programmed_at, "last_tap_at": last_tap, "pairing": "QR and NFC resolve to the same card and the same destination", "note": NFC_NOTE}


def card_analytics(db: Session, card_ids=None, *, card_filter=None, days: int = 30) -> dict:
    """Scans and taps for one card, several cards, or a filtered set. Humans and automated traffic are counted SEPARATELY; a scan is never a completed Google review."""
    since = utcnow() - timedelta(days=days)
    where = [ScanEvent.event_type == ScanEventType.scan, ScanEvent.created_at >= since]
    if card_ids is not None:
        where.append(ScanEvent.card_id.in_(card_ids))
    if card_filter is not None:
        where.append(ScanEvent.card_id.in_(card_filter))
    human = where + [ScanEvent.is_bot.is_(False)]
    by_ch = {ch or "untracked": n for ch, n in db.execute(select(ScanEvent.channel, func.count()).where(*human).group_by(ScanEvent.channel))}
    uniq = db.scalar(select(func.count(func.distinct(ScanEvent.visitor_hash))).where(*human)) or 0
    bots = db.scalar(select(func.count()).where(*where, ScanEvent.is_bot.is_(True)).select_from(ScanEvent)) or 0
    qr, nfc, other = by_ch.get("qr", 0), by_ch.get("nfc", 0), by_ch.get("untracked", 0)
    devices = {d or "unknown": n for d, n in db.execute(select(ScanEvent.device, func.count()).where(*human).group_by(ScanEvent.device))}
    refs = [{"host": h, "scans": n} for h, n in db.execute(select(ScanEvent.referrer_host, func.count()).where(*human, ScanEvent.referrer_host.is_not(None)).group_by(ScanEvent.referrer_host).order_by(func.count().desc()).limit(10))]
    places = [{"placement": p, "scans": n} for p, n in db.execute(select(ScanEvent.placement, func.count()).where(*human, ScanEvent.placement.is_not(None)).group_by(ScanEvent.placement).order_by(func.count().desc()).limit(10))]
    day = func.date(ScanEvent.created_at)
    daily: dict = {}
    for d, ch, n in db.execute(select(day, ScanEvent.channel, func.count()).where(*human).group_by(day, ScanEvent.channel).order_by(day)):
        row = daily.setdefault(str(d), {"date": str(d), "qr": 0, "nfc": 0, "untracked": 0})
        row[ch if ch in ("qr", "nfc") else "untracked"] += n
    last = db.scalar(select(func.max(ScanEvent.created_at)).where(*human))
    last_tap = db.scalar(select(func.max(ScanEvent.created_at)).where(*human, ScanEvent.channel == "nfc"))
    return {"days": days, "since": since, "totals": {"qr_scans": qr, "nfc_taps": nfc, "untracked": other, "total": qr + nfc + other, "unique_visitors": uniq},
            "automated_visits": bots, "devices": devices, "referrers": refs, "placements": places, "by_day": list(daily.values()), "last_scan_at": last, "last_nfc_tap_at": last_tap,
            "note": "A scan or tap is a visit, not a completed Google review. Automated traffic (bots, link previews) is counted separately and excluded from the totals."}


def card_last_scans(db: Session, card_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """Most recent human scan per card (cards never scanned are absent)."""
    if not card_ids:
        return {}
    rows = db.execute(
        select(ScanEvent.card_id, func.max(ScanEvent.created_at))
        .where(ScanEvent.card_id.in_(card_ids), ScanEvent.event_type == ScanEventType.scan, ScanEvent.is_bot.is_(False))
        .group_by(ScanEvent.card_id)
    ).all()
    return {cid: ts for cid, ts in rows}


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
    # Unique scans: distinct visitors among human scans. The visitor hash is salted per day and not reversible, so this
    # counts "different devices per day" - the same phone on two days counts twice, by design (no cross-day tracking).
    uniq = db.execute(
        select(ScanEvent.card_id, func.count(func.distinct(ScanEvent.visitor_hash)))
        .where(ScanEvent.card_id.in_(card_ids), ScanEvent.is_bot.is_(False), ScanEvent.event_type == ScanEventType.scan)
        .group_by(ScanEvent.card_id)
    ).all()
    for cid, n in uniq:
        out[cid]["unique_scan"] = n
    # The same card seen through its two doors: printed QR and NFC tap. NULL = recorded before the channel was tracked.
    by_ch = db.execute(
        select(ScanEvent.card_id, ScanEvent.channel, func.count(), func.count(func.distinct(ScanEvent.visitor_hash)))
        .where(ScanEvent.card_id.in_(card_ids), ScanEvent.is_bot.is_(False), ScanEvent.event_type == ScanEventType.scan)
        .group_by(ScanEvent.card_id, ScanEvent.channel)
    ).all()
    for cid, ch, n, u in by_ch:
        key = ch or "untracked"
        out[cid][f"{key}_scan"] = n
        out[cid][f"{key}_unique"] = u
    return out
