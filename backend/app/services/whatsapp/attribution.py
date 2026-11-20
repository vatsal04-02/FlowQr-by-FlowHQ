"""Click-to-WhatsApp attribution (Phase 11). Ships OFF (WHATSAPP_ATTRIBUTION_ENABLED) and is part of the Pro tier only. We do not create ads: we only recognise the referral Meta attaches to the first message
of a chat that started from an ad or a page button, tag the conversation with it, and show it in the inbox, the export and a small summary.

The shape of Meta's `referral` object is written from documentation and has NOT been seen from real traffic (docs/WHATSAPP_META_CHECKLIST.md). Only the fields below are read, each is length-limited, and
nothing in it is ever treated as an instruction. A referral never creates consent and never changes who may be messaged.

THE FREE ENTRY-POINT WINDOW. After a customer starts a chat from an ad or page button, Meta gives a free period. Sources disagree about its length (72 hours, or 7 days from 21 Sep 2026), so it is DATED data
(`whatsapp_entry_windows`, append-only, never edited), both values are seeded UNVERIFIED, and **an estimate treats those messages as free only when the window row in force on the day of the click has been
checked by an administrator against Meta's own documentation** (an append-only record of checks, like the price checks). Until then they are estimated at the normal rate and the screen says so."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Tenant, User
from app.models.base import utcnow
from app.models.whatsapp import WhatsAppBooking, WhatsAppContact, WhatsAppConversation, WhatsAppEntryWindow, WhatsAppEntryWindowCheck
from app.services.audit import audit
from app.services.whatsapp import WaError, addons

SOURCE_TYPES = ("ad", "post")
WARNING = ("The length of WhatsApp's free window after an ad or page-button click has not been checked against WhatsApp's own documentation yet, so FlowQR still estimates these messages at the normal rate.")


def platform_on() -> bool:
    return bool(settings.whatsapp_enabled and settings.whatsapp_attribution_enabled)


def enabled_for(db: Session, tenant_id: uuid.UUID) -> bool:
    return platform_on() and addons.attribution_allowed(db, tenant_id)


def clean_referral(raw) -> dict | None:
    """The few fields we keep from Meta's referral object, trimmed. None when there is nothing usable. Used at webhook time, before the business is known, so it needs no database."""
    if not isinstance(raw, dict):
        return None
    t = str(raw.get("source_type") or "").lower()[:8]
    if t not in SOURCE_TYPES:
        return None
    def s(k: str, n: int) -> str | None:
        v = raw.get(k)
        return " ".join(str(v).split())[:n] if isinstance(v, (str, int)) and str(v).strip() else None
    return {"type": t, "id": s("source_id", 64), "headline": s("headline", 120), "url": s("source_url", 300), "clid": s("ctwa_clid", 200)}


def apply_to_conversation(conv: WhatsAppConversation, ref: dict | None, when: datetime) -> bool:
    """Tag the conversation with the latest ad or post it came from and restart the entry-point clock (each click is a new entry). Returns whether anything was recorded."""
    if not ref:
        return False
    conv.referral_type, conv.referral_id, conv.referral_headline, conv.referral_url, conv.referral_clid = ref["type"], ref.get("id"), ref.get("headline"), ref.get("url"), ref.get("clid")
    conv.entry_point_at = max(conv.entry_point_at or when, when)
    conv.source = "ad" if ref["type"] == "ad" else "post"
    return True


# ---- the dated free-window setting
def window_for(db: Session, on: date) -> WhatsAppEntryWindow | None:
    return db.scalar(select(WhatsAppEntryWindow).where(WhatsAppEntryWindow.effective_from <= on).order_by(WhatsAppEntryWindow.effective_from.desc()).limit(1))


def latest_check(db: Session, window_id: uuid.UUID) -> WhatsAppEntryWindowCheck | None:
    return db.scalar(select(WhatsAppEntryWindowCheck).where(WhatsAppEntryWindowCheck.window_id == window_id).order_by(WhatsAppEntryWindowCheck.created_at.desc(), WhatsAppEntryWindowCheck.id.desc()).limit(1))


def is_verified(db: Session, w: WhatsAppEntryWindow) -> bool:
    c = latest_check(db, w.id)
    return bool(c.verified) if c is not None else False  # never verified by default


def state(db: Session, conv: WhatsAppConversation | None, now: datetime | None = None) -> dict | None:
    """What the entry-point window means for this conversation right now. None when it did not start from an ad or post."""
    if conv is None or conv.entry_point_at is None:
        return None
    now = now or utcnow()
    w = window_for(db, conv.entry_point_at.date())
    if w is None:
        return {"until": None, "open": False, "verified": False, "counts_as_free": False, "hours": None, "warning": WARNING}
    until = conv.entry_point_at + timedelta(hours=w.hours)
    ok = is_verified(db, w)
    is_open = now < until
    return {"until": until, "open": is_open, "verified": ok, "counts_as_free": bool(is_open and ok), "hours": w.hours, "warning": None if ok else WARNING}


def free_now(db: Session, tenant_id: uuid.UUID, contact_id: uuid.UUID, now: datetime | None = None) -> bool:
    """True only if this customer's chat started from an ad or post, its free window is still open, AND the window length has been verified. Used by the cost estimate; it never affects what may be sent."""
    if not platform_on():
        return False
    conv = db.scalar(select(WhatsAppConversation).where(WhatsAppConversation.tenant_id == tenant_id, WhatsAppConversation.contact_id == contact_id))
    st = state(db, conv, now)
    return bool(st and st["counts_as_free"])


def serialize_window(db: Session, w: WhatsAppEntryWindow, *, in_force: bool = False) -> dict:
    c = latest_check(db, w.id)
    return {"id": w.id, "hours": w.hours, "effective_from": w.effective_from.isoformat(), "source": w.source, "verified": bool(c.verified) if c else False, "in_force": in_force,
            "check": None if c is None else {"verified": c.verified, "note": c.note, "at": c.created_at}}


def list_windows(db: Session) -> list[dict]:
    rows = list(db.scalars(select(WhatsAppEntryWindow).order_by(WhatsAppEntryWindow.effective_from.desc())))
    now_row = window_for(db, utcnow().date())
    return [serialize_window(db, w, in_force=bool(now_row and w.id == now_row.id)) for w in rows]


def add_window(db: Session, admin: User, *, hours: int, effective_from: date, source: str, ip: str | None = None) -> WhatsAppEntryWindow:
    """A change is a NEW dated row (never an edit), and it starts unverified."""
    source = " ".join((source or "").split())
    if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 720:
        raise WaError(422, "invalid_hours", "The free window must be from 1 to 720 hours.")
    if len(source) < 10:
        raise WaError(422, "source_required", "Write where this length comes from, for example: Meta's pricing documentation, page dated 1 Dec 2026.")
    if db.scalar(select(WhatsAppEntryWindow.id).where(WhatsAppEntryWindow.effective_from == effective_from)):
        raise WaError(409, "date_taken", "There is already a value from that date. Add the change with a later date; existing ones are never edited.")
    w = WhatsAppEntryWindow(hours=hours, effective_from=effective_from, source=source[:300], created_by=admin.id)
    db.add(w)
    db.flush()
    audit(db, action="admin.whatsapp_entry_window", entity_type="whatsapp_entry_window", entity_id=w.id, user_id=admin.id, meta={"hours": hours, "from": effective_from.isoformat()}, ip=ip)
    return w


def add_check(db: Session, admin: User, window_id: uuid.UUID, verified: bool, note: str, ip: str | None = None) -> WhatsAppEntryWindowCheck:
    if db.get(WhatsAppEntryWindow, window_id) is None:
        raise WaError(404, "not_found", "That window does not exist.")
    note = " ".join((note or "").split())
    if len(note) < 10:
        raise WaError(422, "note_required", "Write what you checked, for example: Matches Meta's documentation page dated 1 Dec 2026.")
    row = WhatsAppEntryWindowCheck(window_id=window_id, verified=bool(verified), note=note[:300], checked_by=admin.id)
    db.add(row)
    db.flush()
    audit(db, action="admin.whatsapp_entry_window_check", entity_type="whatsapp_entry_window", entity_id=window_id, user_id=admin.id, meta={"verified": bool(verified)}, ip=ip)
    return row


# ---- what the owner sees
def summary(db: Session, tenant: Tenant, days: int = 90, now: datetime | None = None) -> dict:
    """Conversations by the ad or post they came from, and how many of those customers booked. Counts and ad names only: no customer is named."""
    now = now or utcnow()
    since = now - timedelta(days=max(1, min(days, 365)))
    rows = db.execute(select(WhatsAppConversation.referral_type, WhatsAppConversation.referral_id, func.max(WhatsAppConversation.referral_headline), func.count(), func.max(WhatsAppConversation.entry_point_at))
                      .where(WhatsAppConversation.tenant_id == tenant.id, WhatsAppConversation.referral_type.is_not(None), WhatsAppConversation.entry_point_at >= since)
                      .group_by(WhatsAppConversation.referral_type, WhatsAppConversation.referral_id).order_by(func.count().desc()).limit(50)).all()
    out = []
    for t, rid, head, n, last in rows:
        booked = db.scalar(select(func.count(func.distinct(WhatsAppBooking.contact_id))).select_from(WhatsAppBooking).join(WhatsAppConversation, WhatsAppConversation.contact_id == WhatsAppBooking.contact_id)
                           .where(WhatsAppBooking.tenant_id == tenant.id, WhatsAppBooking.status != "cancelled", WhatsAppConversation.tenant_id == tenant.id, WhatsAppConversation.referral_type == t,
                                  WhatsAppConversation.referral_id.is_(rid) if rid is None else WhatsAppConversation.referral_id == rid, WhatsAppConversation.entry_point_at >= since)) or 0
        out.append({"type": t, "id": rid, "headline": head, "conversations": n, "customers_who_booked": booked, "last_at": last})
    total = db.scalar(select(func.count()).select_from(WhatsAppConversation).where(WhatsAppConversation.tenant_id == tenant.id, WhatsAppConversation.created_at >= since)) or 0
    return {"days": days, "sources": out, "conversations_in_period": total, "from_ads_or_posts": sum(x["conversations"] for x in out),
            "window_note": WARNING if not (window_for(db, now.date()) and is_verified(db, window_for(db, now.date()))) else None}
