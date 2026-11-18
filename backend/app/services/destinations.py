"""A card's destination override: where a scan or tap goes INSTEAD of its review landing page.

The rules (each is tested in tests/test_qr_assets.py):
  * The URL is chosen by a platform admin and STORED. Nothing a visitor sends (query string, header, path) ever picks, extends or alters where they are sent: no open redirect.
  * HTTPS only, a real public host, no credentials in the URL, no IP literals, no local or temporary hosts, no FlowQR address (a redirect to ourselves can only loop), at most 2000 characters.
  * Setting or clearing is atomic (the card row is locked), appended to `card_destination_history` and to the audit log, and needs no new QR and no NFC re-programming: the printed
    address never changes.
  * Nothing here fetches the URL. A server that fetches admin-supplied URLs is an SSRF hole; "test" means validating the address and letting the admin open it in their own browser.
"""
from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CardDestinationHistory, CardStatus, QRCard
from app.models.base import utcnow
from app.services.audit import audit
from app.services.qr import _TEMPORARY_HOST_PARTS

MAX_URL = 2000
_HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class DestinationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _own_hosts() -> set[str]:
    hosts = set()
    for u in (settings.public_card_base_url, settings.frontend_url):
        h = (urlsplit(u or "").hostname or "").lower()
        if h:
            hosts |= {h, h[4:] if h.startswith("www.") else "www." + h}
    return hosts


def normalise(url: str | None) -> str:
    """The cleaned destination, or DestinationError. Idempotent: normalise(normalise(x)) == normalise(x)."""
    raw = (url or "").strip()
    if not raw:
        raise DestinationError("empty", "Enter the web address to send people to.")
    if len(raw) > MAX_URL:
        raise DestinationError("too_long", f"That address is longer than {MAX_URL} characters.")
    if any(ord(c) < 33 or ord(c) == 127 for c in raw):
        raise DestinationError("bad_characters", "The address contains spaces or control characters.")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise DestinationError("invalid", "That is not a valid web address.")
    if parts.scheme.lower() != "https":
        raise DestinationError("not_https", "Only secure https:// addresses are allowed.")
    if parts.username or parts.password or "@" in parts.netloc:
        raise DestinationError("credentials", "The address may not contain a username or password.")
    host = (parts.hostname or "").lower().rstrip(".")
    if host in _own_hosts():  # checked first: a FlowQR address is "self" whatever its port or form
        raise DestinationError("self", "That points back to FlowQR itself. Leave the destination empty to use the card's normal review page.")
    if port not in (None, 443):
        raise DestinationError("port", "Only the standard secure port is allowed.")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise DestinationError("invalid", "That is not a valid web address.")
    if not host:
        raise DestinationError("invalid", "That is not a valid web address.")
    try:
        ipaddress.ip_address(host.strip("[]"))
        raise DestinationError("ip_address", "Use a domain name, not an IP address.")
    except ValueError:
        pass
    if not _HOST.match(host) or any(m in host for m in _TEMPORARY_HOST_PARTS):
        raise DestinationError("host", "That address is not a permanent public website.")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))  # no fragment: it is never sent to a server anyway


def history(db: Session, card: QRCard) -> list[CardDestinationHistory]:
    return list(db.scalars(select(CardDestinationHistory).where(CardDestinationHistory.card_id == card.id).order_by(CardDestinationHistory.changed_at.desc(), CardDestinationHistory.id.desc())))


def is_live(card: QRCard) -> bool:
    return card.status in (CardStatus.assigned, CardStatus.active)


def _change(db: Session, card_id: uuid.UUID, new_url: str | None, *, by: uuid.UUID | None, reason: str | None, now: datetime | None = None) -> tuple[QRCard, bool]:
    card = db.scalar(select(QRCard).where(QRCard.id == card_id).with_for_update())  # atomic: two admins cannot interleave
    if card is None:
        raise DestinationError("not_found", "Card not found.")
    if card.status in (CardStatus.retired, CardStatus.deactivated, CardStatus.lost):
        raise DestinationError("card_dead", "This card is out of use, so its destination cannot be changed.")
    if (card.destination_url or None) == new_url:
        return card, False
    now = now or utcnow()
    db.add(CardDestinationHistory(card_id=card.id, tenant_id=card.tenant_id, action="set" if new_url else "cleared", old_url=card.destination_url, new_url=new_url,
                                  reason=(reason or "").strip()[:300] or None, changed_by=by, changed_at=now))
    old = card.destination_url
    card.destination_url, card.destination_set_at = new_url, (now if new_url else None)
    audit(db, action="admin.card_destination_set" if new_url else "admin.card_destination_cleared", tenant_id=card.tenant_id, user_id=by, entity_type="card", entity_id=card.id,
          meta={"old": old, "new": new_url, "reason": (reason or "")[:300]})
    return card, True


def drop_on_reassign(db: Session, card: QRCard, *, by: uuid.UUID | None, why: str) -> bool:
    """A destination belongs to the card's CURRENT business and placement. When the card moves to another business, location or campaign, is reserved, or goes back to stock, the old destination
    is removed (and recorded in the history and the audit log) so it can never send the NEW owner's customers to the OLD owner's address. The admin sets a new one after the move.
    Caller commits; the card row is already loaded in this transaction."""
    if not card.destination_url:
        return False
    now = utcnow()
    db.add(CardDestinationHistory(card_id=card.id, tenant_id=card.tenant_id, action="cleared", old_url=card.destination_url, new_url=None, reason=why[:300], changed_by=by, changed_at=now))
    audit(db, action="admin.card_destination_cleared", tenant_id=card.tenant_id, user_id=by, entity_type="card", entity_id=card.id, meta={"old": card.destination_url, "new": None, "reason": why[:300]})
    card.destination_url, card.destination_set_at = None, None
    return True


def set_destination(db: Session, card_id: uuid.UUID, url: str, *, by: uuid.UUID | None, reason: str | None = None, now: datetime | None = None) -> tuple[QRCard, bool]:
    return _change(db, card_id, normalise(url), by=by, reason=reason, now=now)


def clear_destination(db: Session, card_id: uuid.UUID, *, by: uuid.UUID | None, reason: str | None = None, now: datetime | None = None) -> tuple[QRCard, bool]:
    return _change(db, card_id, None, by=by, reason=reason, now=now)
