"""Appointment booking (Phase 9). Ships OFF behind WHATSAPP_BOOKING_ENABLED, then each business's own switch, on the Growth and Pro tiers.

* THE SERVER DECIDES, never the AI. Every booking, change and cancellation goes through `book` / `reschedule` / `cancel` here: the business's own hours and closed days, the service's length and buffer, the
  capacity and the least notice are checked, and the check and the write happen under a lock on the business's booking settings row, so two people (or an AI and a person) racing for the last slot cannot both get it.
* A booking never grants consent. Consent to visit updates is recorded only when the CUSTOMER explicitly answers YES, in the chat, to the fixed question below (source `whatsapp_booking`, wording version `booking-1`,
  updates about the visit only: no offers, no greetings). A person making a booking may record consent the existing way (attested, with evidence), never as a side effect.
* Reminders are fixed approved templates (two of them), sent through the single gate. The gate fails closed like greetings: until WhatsApp reports the category is utility, offers consent is needed too, so a
  booking-only customer gets no reminder. STOP blocks them.
* Marking a booking done records the visit and schedules the existing review request, so booking, visit and review are one loop. A booking is deleted with its customer and with the business.
All times are India time (no daylight saving) and stored in UTC."""
from __future__ import annotations

import hashlib
import logging
import random
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Tenant, User
from app.models.base import utcnow
from app.models.whatsapp import (WhatsAppBooking, WhatsAppBookingClosed, WhatsAppBookingHours, WhatsAppBookingService, WhatsAppBookingSettings, WhatsAppContact, WhatsAppConversation)
from app.services.audit import audit
from app.services.whatsapp import WaError, addons, ai_text, automations, consent, rules, sender, templates

log = logging.getLogger("flowqr.whatsapp.bookings")
IST = timezone(timedelta(hours=5, minutes=30))
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
LIMITS = {"capacity": (1, 50), "slot_step_minutes": (5, 120), "min_notice_minutes": (0, 10080), "max_days_ahead": (1, 180), "reminder_day_hour": (9, 20), "reminder_soon_hours": (1, 6)}
MAX_SERVICES = 40
MAX_CLOSED_DAYS = 400
REMINDER_KEYS = ("booking_reminder_day", "booking_reminder_soon")
ASK_WINDOW = timedelta(hours=24)
BOOKING_WORDS = {  # why a booking could not be made, in words the customer or the owner can act on
    "not_bookable": "Bookings are not switched on for this business yet.", "service_not_found": "That service is not on the list.", "closed_day": "The business is closed that day.",
    "outside_hours": "That time is outside the opening hours.", "too_soon": "That time is too soon to book.", "too_far": "That date is too far ahead.", "in_the_past": "That time has already passed.",
    "slot_taken": "That time is already taken.", "bad_time": "That date or time is not valid.", "not_booked": "Only a booked appointment can be changed.", "too_early": "A visit can only be marked after it starts.",
}


# ---- switches
def platform_on() -> bool:
    return bool(settings.whatsapp_enabled and settings.whatsapp_booking_enabled)


def get_settings(db: Session, tenant_id: uuid.UUID, *, create: bool = False) -> WhatsAppBookingSettings | None:
    row = db.scalar(select(WhatsAppBookingSettings).where(WhatsAppBookingSettings.tenant_id == tenant_id))
    if row is None and create:
        row = WhatsAppBookingSettings(tenant_id=tenant_id, enabled=False, capacity=1, slot_step_minutes=30, min_notice_minutes=60, max_days_ahead=30, reminders_enabled=False, reminder_day_hour=10, reminder_soon_hours=2)
        db.add(row)
        db.flush()
    return row


def enabled_for(db: Session, tenant_id: uuid.UUID) -> bool:
    """The platform switch, the Growth or Pro tier, and the business's own switch."""
    if not platform_on() or not addons.bookings_allowed(db, tenant_id):
        return False
    s = get_settings(db, tenant_id)
    return bool(s and s.enabled)


def services(db: Session, tenant_id: uuid.UUID, *, active_only: bool = False) -> list[WhatsAppBookingService]:
    q = select(WhatsAppBookingService).where(WhatsAppBookingService.tenant_id == tenant_id)
    if active_only:
        q = q.where(WhatsAppBookingService.active.is_(True))
    return list(db.scalars(q.order_by(WhatsAppBookingService.name)))


def hours(db: Session, tenant_id: uuid.UUID) -> list[WhatsAppBookingHours]:
    return list(db.scalars(select(WhatsAppBookingHours).where(WhatsAppBookingHours.tenant_id == tenant_id).order_by(WhatsAppBookingHours.weekday)))


def usable(db: Session, tenant_id: uuid.UUID) -> bool:
    """On, and set up enough to take a booking: at least one active service and one open day."""
    return enabled_for(db, tenant_id) and bool(services(db, tenant_id, active_only=True)) and bool(hours(db, tenant_id))


def setup_words(db: Session, tenant_id: uuid.UUID) -> list[str]:
    out = []
    if not services(db, tenant_id, active_only=True):
        out.append("Add at least one service")
    if not hours(db, tenant_id):
        out.append("Set your opening hours")
    return out


# ---- settings
def serialize_settings(s: WhatsAppBookingSettings | None) -> dict:
    s = s or WhatsAppBookingSettings(enabled=False, capacity=1, slot_step_minutes=30, min_notice_minutes=60, max_days_ahead=30, reminders_enabled=False, reminder_day_hour=10, reminder_soon_hours=2)
    return {"enabled": bool(s.enabled), "capacity": s.capacity, "slot_step_minutes": s.slot_step_minutes, "min_notice_minutes": s.min_notice_minutes, "max_days_ahead": s.max_days_ahead,
            "reminders_enabled": bool(s.reminders_enabled), "reminder_day_hour": s.reminder_day_hour, "reminder_soon_hours": s.reminder_soon_hours, "limits": {k: list(v) for k, v in LIMITS.items()}}


def set_settings(db: Session, tenant: Tenant, user: User, *, ip: str | None = None, **fields) -> WhatsAppBookingSettings:
    s = get_settings(db, tenant.id, create=True)
    changed = {}
    for k, v in fields.items():
        if v is None:
            continue
        if k in ("enabled", "reminders_enabled"):
            v = bool(v)
        elif k in LIMITS:
            lo, hi = LIMITS[k]
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                raise WaError(422, "invalid_setting", f"{k.replace('_', ' ').capitalize()} must be a whole number from {lo} to {hi}.")
        else:
            continue
        if getattr(s, k) != v:
            setattr(s, k, v)
            changed[k] = v
    db.flush()
    if changed:
        audit(db, action="whatsapp.booking_settings", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_booking_settings", entity_id=s.id, meta=changed, ip=ip)
    return s


# ---- services, hours, closed days
def _money(v) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v).replace(",", "").strip())
    except InvalidOperation:
        raise WaError(422, "invalid_price", "The price must be a number of rupees, for example 600.")
    if d < 0 or d > Decimal("10000000"):
        raise WaError(422, "invalid_price", "The price must be a number of rupees, for example 600.")
    return d.quantize(Decimal("0.01"))


def _minutes(v, lo: int, hi: int, label: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise WaError(422, "invalid_minutes", f"{label} must be a whole number of minutes from {lo} to {hi}.")
    return v


def serialize_service(r: WhatsAppBookingService) -> dict:
    return {"id": r.id, "name": r.name, "duration_minutes": r.duration_minutes, "buffer_minutes": r.buffer_minutes, "price_inr": float(r.price_inr) if r.price_inr is not None else None, "active": r.active}


def save_service(db: Session, tenant: Tenant, user: User, row: WhatsAppBookingService | None, *, name, duration_minutes, buffer_minutes=0, price_inr=None, active=True, ip: str | None = None) -> WhatsAppBookingService:
    name = " ".join((name or "").split())[:120]
    if len(name) < 2:
        raise WaError(422, "name_required", "Give the service a name.")
    dur, buf = _minutes(duration_minutes, 5, 480, "The length"), _minutes(buffer_minutes, 0, 120, "The gap after it")
    price = _money(price_inr)
    if row is None:
        if len(services(db, tenant.id)) >= MAX_SERVICES:
            raise WaError(409, "too_many", f"You can keep up to {MAX_SERVICES} services.")
        row = WhatsAppBookingService(tenant_id=tenant.id, name=name, duration_minutes=dur, buffer_minutes=buf, price_inr=price, active=bool(active))
        db.add(row)
    else:
        row.name, row.duration_minutes, row.buffer_minutes, row.price_inr, row.active = name, dur, buf, price, bool(active)
    db.flush()
    audit(db, action="whatsapp.booking_service", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_booking_service", entity_id=row.id, meta={"name": name}, ip=ip)
    return row


def get_service(db: Session, tenant_id: uuid.UUID, service_id: uuid.UUID) -> WhatsAppBookingService:
    row = db.get(WhatsAppBookingService, service_id)
    if row is None or row.tenant_id != tenant_id:
        raise WaError(404, "service_not_found", BOOKING_WORDS["service_not_found"])
    return row


def delete_service(db: Session, tenant: Tenant, user: User, row: WhatsAppBookingService, ip: str | None = None) -> None:
    audit(db, action="whatsapp.booking_service_delete", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_booking_service", entity_id=row.id, ip=ip)
    db.delete(row)  # bookings keep their own copy of the name and length
    db.flush()


def _hhmm(v) -> time:
    if isinstance(v, time):
        return v
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(v or "").strip())
    if not m:
        raise WaError(422, "bad_time", "Use a time like 09:30.")
    return time(int(m.group(1)), int(m.group(2)))


def set_hours(db: Session, tenant: Tenant, user: User, rows: list[dict], ip: str | None = None) -> list[WhatsAppBookingHours]:
    """Replace the weekly hours. One row per open weekday; a weekday with no row is closed."""
    seen, new = set(), []
    for r in rows or []:
        wd = r.get("weekday")
        if isinstance(wd, bool) or not isinstance(wd, int) or not 0 <= wd <= 6 or wd in seen:
            raise WaError(422, "bad_weekday", "Each weekday can appear once.")
        o, c = _hhmm(r.get("opens")), _hhmm(r.get("closes"))
        if c <= o:
            raise WaError(422, "bad_hours", f"{WEEKDAYS[wd]}: closing time must be after opening time.")
        seen.add(wd)
        new.append((wd, o, c))
    for old in hours(db, tenant.id):
        db.delete(old)
    db.flush()
    out = []
    for wd, o, c in new:
        row = WhatsAppBookingHours(tenant_id=tenant.id, weekday=wd, opens=o, closes=c)
        db.add(row)
        out.append(row)
    db.flush()
    audit(db, action="whatsapp.booking_hours", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_booking_settings", meta={"days_open": len(out)}, ip=ip)
    return out


def serialize_hours(rows: list[WhatsAppBookingHours]) -> list[dict]:
    return [{"weekday": r.weekday, "day": WEEKDAYS[r.weekday], "opens": r.opens.strftime("%H:%M"), "closes": r.closes.strftime("%H:%M")} for r in rows]


def closed_days(db: Session, tenant_id: uuid.UUID) -> list[WhatsAppBookingClosed]:
    return list(db.scalars(select(WhatsAppBookingClosed).where(WhatsAppBookingClosed.tenant_id == tenant_id, WhatsAppBookingClosed.day >= datetime.now(IST).date() - timedelta(days=1)).order_by(WhatsAppBookingClosed.day)))


def add_closed_day(db: Session, tenant: Tenant, user: User, day: date, reason: str | None, ip: str | None = None) -> WhatsAppBookingClosed:
    if db.scalar(select(func.count()).select_from(WhatsAppBookingClosed).where(WhatsAppBookingClosed.tenant_id == tenant.id)) >= MAX_CLOSED_DAYS:
        raise WaError(409, "too_many", "That is a lot of closed days. Remove old ones first.")
    row = db.scalar(select(WhatsAppBookingClosed).where(WhatsAppBookingClosed.tenant_id == tenant.id, WhatsAppBookingClosed.day == day))
    if row is None:
        row = WhatsAppBookingClosed(tenant_id=tenant.id, day=day, reason=(" ".join((reason or "").split())[:120] or None))
        db.add(row)
        db.flush()
        audit(db, action="whatsapp.booking_closed_day", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_booking_closed", entity_id=row.id, meta={"day": str(day)}, ip=ip)
    return row


def remove_closed_day(db: Session, tenant: Tenant, user: User, closed_id: uuid.UUID, ip: str | None = None) -> None:
    row = db.get(WhatsAppBookingClosed, closed_id)
    if row is None or row.tenant_id != tenant.id:
        raise WaError(404, "not_found", "That closed day was not found.")
    db.delete(row)
    db.flush()


# ---- time helpers
def to_utc(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=IST).astimezone(timezone.utc)


def when_text(dt: datetime) -> str:
    """"Sat 21 Nov at 10:30 am", in India time."""
    t = dt.astimezone(IST)
    hour12 = t.hour % 12 or 12
    return f"{t.strftime('%a')} {t.day} {t.strftime('%b')} at {hour12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def clock_text(dt: datetime) -> str:
    t = dt.astimezone(IST)
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def parse_start(day: str, at: str) -> datetime:
    """The AI and the API give a date as YYYY-MM-DD and a time as HH:MM (24 hours, India time)."""
    try:
        d = date.fromisoformat((day or "").strip())
    except ValueError:
        raise WaError(422, "bad_time", BOOKING_WORDS["bad_time"])
    return to_utc(d, _hhmm(at))


# ---- availability
def _overlapping(db: Session, tenant_id: uuid.UUID, start: datetime, until: datetime, exclude: uuid.UUID | None) -> list[WhatsAppBooking]:
    q = select(WhatsAppBooking).where(WhatsAppBooking.tenant_id == tenant_id, WhatsAppBooking.status == "booked", WhatsAppBooking.starts_at < until, WhatsAppBooking.blocks_until > start)
    if exclude is not None:
        q = q.where(WhatsAppBooking.id != exclude)
    return list(db.scalars(q))


def _fits(existing: list[WhatsAppBooking], start: datetime, until: datetime, capacity: int) -> bool:
    """Exact capacity check: at no instant inside the new booking may the people already there plus this one exceed the capacity."""
    points = {start} | {b.starts_at for b in existing if start < b.starts_at < until}
    return all(sum(1 for b in existing if b.starts_at <= t < b.blocks_until) + 1 <= capacity for t in points)


def _window(db: Session, tenant_id: uuid.UUID, day: date) -> tuple[time, time] | None:
    if db.scalar(select(WhatsAppBookingClosed.id).where(WhatsAppBookingClosed.tenant_id == tenant_id, WhatsAppBookingClosed.day == day)) is not None:
        return None
    h = db.scalar(select(WhatsAppBookingHours).where(WhatsAppBookingHours.tenant_id == tenant_id, WhatsAppBookingHours.weekday == day.weekday()))
    return (h.opens, h.closes) if h else None


def check_available(db: Session, tenant_id: uuid.UUID, s: WhatsAppBookingSettings, svc: WhatsAppBookingService, start: datetime, *, exclude: uuid.UUID | None = None, enforce_notice: bool = True,
                    now: datetime | None = None) -> tuple[datetime, datetime]:
    """Raises WaError(409/422, code) when this service cannot start at this moment; otherwise returns (ends_at, blocks_until). Call it under the booking lock."""
    now = now or utcnow()
    ends = start + timedelta(minutes=svc.duration_minutes)
    until = ends + timedelta(minutes=svc.buffer_minutes)
    local = start.astimezone(IST)
    if start <= now:
        raise WaError(409, "in_the_past", BOOKING_WORDS["in_the_past"])
    if enforce_notice and start < now + timedelta(minutes=s.min_notice_minutes):
        raise WaError(409, "too_soon", BOOKING_WORDS["too_soon"])
    if local.date() > now.astimezone(IST).date() + timedelta(days=s.max_days_ahead):
        raise WaError(409, "too_far", BOOKING_WORDS["too_far"])
    if db.scalar(select(WhatsAppBookingClosed.id).where(WhatsAppBookingClosed.tenant_id == tenant_id, WhatsAppBookingClosed.day == local.date())) is not None:
        raise WaError(409, "closed_day", BOOKING_WORDS["closed_day"])
    win = _window(db, tenant_id, local.date())
    if win is None or start < to_utc(local.date(), win[0]) or ends > to_utc(local.date(), win[1]):
        raise WaError(409, "outside_hours", BOOKING_WORDS["outside_hours"])
    if not _fits(_overlapping(db, tenant_id, start, until, exclude), start, until, s.capacity):
        raise WaError(409, "slot_taken", BOOKING_WORDS["slot_taken"])
    return ends, until


def slots_for_day(db: Session, tenant_id: uuid.UUID, s: WhatsAppBookingSettings, svc: WhatsAppBookingService, day: date, *, enforce_notice: bool = True, now: datetime | None = None) -> list[datetime]:
    now = now or utcnow()
    win = _window(db, tenant_id, day)
    if win is None or day > now.astimezone(IST).date() + timedelta(days=s.max_days_ahead):
        return []
    out = []
    cur = datetime.combine(day, win[0], tzinfo=IST)
    end_of_day = datetime.combine(day, win[1], tzinfo=IST)
    step = timedelta(minutes=s.slot_step_minutes)
    while cur + timedelta(minutes=svc.duration_minutes) <= end_of_day:
        start = cur.astimezone(timezone.utc)
        if start > now and (not enforce_notice or start >= now + timedelta(minutes=s.min_notice_minutes)):
            until = start + timedelta(minutes=svc.duration_minutes + svc.buffer_minutes)
            if _fits(_overlapping(db, tenant_id, start, until, None), start, until, s.capacity):
                out.append(start)
        cur += step
    return out


def next_open_days(db: Session, tenant_id: uuid.UUID, s: WhatsAppBookingSettings, svc: WhatsAppBookingService, from_day: date, count: int = 3, now: datetime | None = None) -> list[tuple[date, list[datetime]]]:
    found = []
    for i in range(0, min(s.max_days_ahead, 60) + 1):
        d = from_day + timedelta(days=i)
        sl = slots_for_day(db, tenant_id, s, svc, d, now=now)
        if sl:
            found.append((d, sl))
        if len(found) >= count:
            break
    return found


def _code(db: Session, tenant_id: uuid.UUID) -> str:
    for _ in range(20):
        c = "BK" + "".join(random.choice(CODE_ALPHABET) for _ in range(5))
        if db.scalar(select(WhatsAppBooking.id).where(WhatsAppBooking.tenant_id == tenant_id, WhatsAppBooking.code == c)) is None:
            return c
    return "BK" + uuid.uuid4().hex[:7].upper()


# ---- the one place a booking is made, changed or ended
def _event(db: Session, b: WhatsAppBooking, change: str, now: datetime | None) -> None:
    """Tell anyone listening (outbound webhooks). Lazy import: integrations uses this module too."""
    from app.services.whatsapp import integrations
    integrations.booking_event(db, b, change, now)


def _lock(db: Session, tenant_id: uuid.UUID) -> WhatsAppBookingSettings:
    """Take the business's booking lock. Everything that reads availability and then writes a booking does so while holding it."""
    s = db.scalar(select(WhatsAppBookingSettings).where(WhatsAppBookingSettings.tenant_id == tenant_id).with_for_update())
    if s is None:
        raise WaError(409, "not_bookable", BOOKING_WORDS["not_bookable"])
    return s


def book(db: Session, tenant: Tenant, contact: WhatsAppContact, svc: WhatsAppBookingService, start: datetime, *, source: str, user: User | None = None, conversation: WhatsAppConversation | None = None,
         idem_key: str | None = None, note: str | None = None, enforce_notice: bool = True, now: datetime | None = None, ip: str | None = None) -> tuple[WhatsAppBooking, bool]:
    """(booking, created). Asking again with the same idempotency key returns the first booking."""
    if contact.tenant_id != tenant.id or svc.tenant_id != tenant.id:
        raise WaError(404, "not_found", "That customer or service was not found.")
    s = _lock(db, tenant.id)
    if idem_key:
        old = db.scalar(select(WhatsAppBooking).where(WhatsAppBooking.tenant_id == tenant.id, WhatsAppBooking.idem_key == idem_key))
        if old is not None:
            return old, False
    if not svc.active:
        raise WaError(409, "service_not_found", BOOKING_WORDS["service_not_found"])
    ends, until = check_available(db, tenant.id, s, svc, start, enforce_notice=enforce_notice, now=now)
    b = WhatsAppBooking(tenant_id=tenant.id, contact_id=contact.id, service_id=svc.id, conversation_id=conversation.id if conversation else None, code=_code(db, tenant.id), service_name=svc.name,
                        duration_minutes=svc.duration_minutes, price_inr=svc.price_inr, starts_at=start, ends_at=ends, blocks_until=until, status="booked", source=source, note=(" ".join((note or "").split())[:300] or None),
                        idem_key=idem_key, created_by=user.id if user else None)
    db.add(b)
    db.flush()
    audit(db, action="whatsapp.booking_create", tenant_id=tenant.id, user_id=user.id if user else None, entity_type="whatsapp_booking", entity_id=b.id, meta={"source": source, "code": b.code}, ip=ip)
    _event(db, b, "created", now)
    return b, True


def reschedule(db: Session, tenant: Tenant, b: WhatsAppBooking, start: datetime, *, user: User | None = None, enforce_notice: bool = True, now: datetime | None = None, ip: str | None = None) -> WhatsAppBooking:
    s = _lock(db, tenant.id)
    db.refresh(b)
    if b.status != "booked":
        raise WaError(409, "not_booked", BOOKING_WORDS["not_booked"])
    svc = db.get(WhatsAppBookingService, b.service_id) if b.service_id else None
    dur, buf = (svc.duration_minutes, svc.buffer_minutes) if svc is not None else (b.duration_minutes, int((b.blocks_until - b.ends_at).total_seconds() // 60))
    probe = svc or WhatsAppBookingService(tenant_id=tenant.id, name=b.service_name, duration_minutes=dur, buffer_minutes=buf, active=True)
    ends, until = check_available(db, tenant.id, s, probe, start, exclude=b.id, enforce_notice=enforce_notice, now=now)
    b.starts_at, b.ends_at, b.blocks_until = start, ends, until
    b.reminder_day_at = b.reminder_day_result = b.reminder_soon_at = b.reminder_soon_result = None  # reminders are for the new time
    db.flush()
    audit(db, action="whatsapp.booking_reschedule", tenant_id=tenant.id, user_id=user.id if user else None, entity_type="whatsapp_booking", entity_id=b.id, ip=ip)
    _event(db, b, "rescheduled", now)
    return b


def cancel(db: Session, tenant: Tenant, b: WhatsAppBooking, reason: str | None = None, *, user: User | None = None, now: datetime | None = None, ip: str | None = None) -> WhatsAppBooking:
    _lock(db, tenant.id)
    db.refresh(b)
    if b.status != "booked":
        raise WaError(409, "not_booked", BOOKING_WORDS["not_booked"])
    b.status, b.cancelled_at, b.cancel_reason = "cancelled", now or utcnow(), (" ".join((reason or "").split())[:120] or None)
    db.flush()
    audit(db, action="whatsapp.booking_cancel", tenant_id=tenant.id, user_id=user.id if user else None, entity_type="whatsapp_booking", entity_id=b.id, ip=ip)
    _event(db, b, "cancelled", now)
    return b


def mark(db: Session, tenant: Tenant, user: User, b: WhatsAppBooking, status: str, now: datetime | None = None, ip: str | None = None) -> dict:
    """The owner marks a visit done or a no-show. Done records the visit and asks the existing review helper to schedule its one neutral request (if that helper is on and the customer agreed to updates)."""
    now = now or utcnow()
    if status not in ("done", "no_show"):
        raise WaError(422, "invalid_status", "Use done or no_show.")
    if b.status != "booked":
        raise WaError(409, "not_booked", BOOKING_WORDS["not_booked"])
    if b.starts_at > now:
        raise WaError(409, "too_early", BOOKING_WORDS["too_early"])
    b.status, b.done_at = status, now
    review = None
    if status == "done":
        contact = db.get(WhatsAppContact, b.contact_id)
        consent.mark_visit(db, contact, now)
        try:
            review = automations.on_visit_completed(db, tenant, contact, user.id, now)
        except WaError:  # the review helper is switched off: the visit is still recorded
            review = {"scheduled": False, "reason": "automation_off"}
    db.flush()
    audit(db, action=f"whatsapp.booking_{status}", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_booking", entity_id=b.id, ip=ip)
    _event(db, b, status, now)
    return {"booking": b, "review": review}


# ---- reading
def get(db: Session, tenant_id: uuid.UUID, booking_id: uuid.UUID) -> WhatsAppBooking:
    b = db.get(WhatsAppBooking, booking_id)
    if b is None or b.tenant_id != tenant_id:
        raise WaError(404, "not_found", "That booking was not found.")
    return b


def serialize(b: WhatsAppBooking, contact: WhatsAppContact | None = None) -> dict:
    return {"id": b.id, "code": b.code, "status": b.status, "source": b.source, "service": b.service_name, "service_id": b.service_id, "duration_minutes": b.duration_minutes, "price_inr": float(b.price_inr) if b.price_inr is not None else None,
            "starts_at": b.starts_at, "ends_at": b.ends_at, "when": when_text(b.starts_at), "note": b.note, "contact_id": b.contact_id,
            "customer": ({"name": contact.customer_name, "phone": contact.phone} if contact else None), "reminder_day": b.reminder_day_result, "reminder_soon": b.reminder_soon_result, "done_at": b.done_at, "cancel_reason": b.cancel_reason}


def list_bookings(db: Session, tenant_id: uuid.UUID, *, start_day: date, end_day: date, status: str | None = None, limit: int = 300) -> list[dict]:
    lo, hi = to_utc(start_day, time(0, 0)), to_utc(end_day + timedelta(days=1), time(0, 0))
    q = select(WhatsAppBooking, WhatsAppContact).join(WhatsAppContact, WhatsAppContact.id == WhatsAppBooking.contact_id).where(WhatsAppBooking.tenant_id == tenant_id, WhatsAppBooking.starts_at >= lo, WhatsAppBooking.starts_at < hi)
    if status:
        q = q.where(WhatsAppBooking.status == status)
    return [serialize(b, c) for b, c in db.execute(q.order_by(WhatsAppBooking.starts_at).limit(max(1, min(limit, 500)))).all()]


def upcoming_for_contact(db: Session, tenant_id: uuid.UUID, contact_id: uuid.UUID, now: datetime | None = None) -> list[WhatsAppBooking]:
    return list(db.scalars(select(WhatsAppBooking).where(WhatsAppBooking.tenant_id == tenant_id, WhatsAppBooking.contact_id == contact_id, WhatsAppBooking.status == "booked",
                                                         WhatsAppBooking.starts_at > (now or utcnow())).order_by(WhatsAppBooking.starts_at)))


def overview(db: Session, tenant: Tenant) -> dict:
    s = get_settings(db, tenant.id)
    state = {key: templates.standard_row(db, tenant.id, key) for key in REMINDER_KEYS}
    reminders = {}
    for key, row in state.items():
        known = bool(row is not None and row.category_confirmed)
        needs_offers = row is None or row.category == "marketing" or not known
        reminders[key] = {"key": key, "submitted": row is not None, "status": row.approval_status if row else None, "category": (row.category if known else None), "category_known": known, "needs_offers_consent": needs_offers,
                          "body": row.body_text if row else templates.STANDARD[key]["body"]}
    return {"platform_on": platform_on(), "plan_ok": addons.bookings_allowed(db, tenant.id), "active": enabled_for(db, tenant.id), "settings": serialize_settings(s), "services": [serialize_service(x) for x in services(db, tenant.id)],
            "hours": serialize_hours(hours(db, tenant.id)), "closed": [{"id": c.id, "day": c.day.isoformat(), "reason": c.reason} for c in closed_days(db, tenant.id)], "setup_needed": setup_words(db, tenant.id),
            "reminder_templates": reminders, "reminder_note": ("Reminders go only to customers who said YES to updates about their visit. Until WhatsApp tells us the category of a reminder, FlowQR also needs the customer's agreement to offers, "
                                                                "so customers who only booked will not get one. Nobody who replied STOP gets a reminder."), "timezone": "Asia/Kolkata"}


# ---- the customer's own YES, in the chat, to visit updates
YES = re.compile(r"^\s*(yes|y|yeah|yep|yup|sure|ok|okay|ok\s+sure|haan|han|haa|ha|ji|ji\s+haan|ji\s+ha|हाँ|हां|जी|जी\s+हाँ|जी\s+हां|ठीक\s+है)\s*[.!]*\s*$", re.I)
NO = re.compile(r"^\s*(no|n|nope|nahi|nahin|na|no\s+thanks|no\s+thank\s+you|नहीं|ना|नही)\s*[.!]*\s*$", re.I)


def consent_answer(text: str) -> str | None:
    """'yes' or 'no' only for a short, explicit answer. Anything else is neither: it is treated as no consent and the conversation carries on normally."""
    t = (text or "").strip()
    if len(t) > 24:
        return None
    return "yes" if YES.match(t) else "no" if NO.match(t) else None


def ask_consent(conv: WhatsAppConversation, b: WhatsAppBooking, now: datetime) -> None:
    conv.booking_consent_ask_id, conv.booking_consent_asked_at = b.id, now


def answer_consent(db: Session, tenant: Tenant, conv: WhatsAppConversation, contact: WhatsAppContact, text: str, lang: str, now: datetime) -> str | None:
    """Called first when a customer writes while the question is waiting. Returns the fixed reply to send, or None when this message is not an answer (the ask is then dropped: silence is not consent)."""
    if conv.booking_consent_ask_id is None:
        return None
    asked = conv.booking_consent_asked_at
    conv.booking_consent_ask_id, conv.booking_consent_asked_at = None, None
    if asked is None or now - asked > ASK_WINDOW:
        return None
    ans = consent_answer(text)
    if ans == "yes":
        wording = rules.wording_for("utility", tenant.name, "booking-1")
        consent.grant(db, tenant, contact, "utility", "whatsapp_booking", wording_text=wording, wording_version="booking-1", evidence=f'Replied "{(text or "").strip()[:24]}" to: {ai_text.say(ai_text.ASK_UPDATES, "en", tenant.name)[:200]}'.strip(), now=now)
        return ai_text.say(ai_text.UPDATES_YES, lang, tenant.name)
    if ans == "no":
        return ai_text.say(ai_text.UPDATES_NO, lang, tenant.name)
    return None


# ---- what the assistant may do, as server-validated tools
class ToolResult:
    def __init__(self, *, fact: str | None = None, final: str | None = None, handoff: str | None = None, booking: WhatsAppBooking | None = None, ask_consent: bool = False):
        self.fact, self.final, self.handoff, self.booking, self.ask_consent = fact, final, handoff, booking, ask_consent


def _pick_service(db: Session, tenant_id: uuid.UUID, name: str | None) -> tuple[WhatsAppBookingService | None, str | None]:
    active = services(db, tenant_id, active_only=True)
    if not active:
        return None, "No services can be booked yet."
    if not (name or "").strip():
        return (active[0], None) if len(active) == 1 else (None, "Which service? Options: " + "; ".join(s.name for s in active))
    n = " ".join(name.lower().split())
    exact = [s for s in active if s.name.lower() == n]
    near = exact or [s for s in active if n in s.name.lower() or s.name.lower() in n]
    if len(near) == 1:
        return near[0], None
    return None, "Which service? Options: " + "; ".join(s.name for s in (near or active))


class ChatTools:
    """The assistant's booking tools for ONE conversation. They act only on this customer: a booking is made for, and a change touches only, the person in this conversation. The server validates everything."""

    live = True

    def __init__(self, db: Session, tenant: Tenant, conv: WhatsAppConversation, contact: WhatsAppContact, lang: str, key: str, now: datetime | None = None):
        self.db, self.tenant, self.conv, self.contact, self.lang, self.key, self.now = db, tenant, conv, contact, lang, key, now or utcnow()
        self.s = get_settings(db, tenant.id)

    def services_fact(self) -> str:
        active = services(self.db, self.tenant.id, active_only=True)
        return ("Services that can be booked: " + "; ".join(f"{x.name} ({x.duration_minutes} minutes" + (f", Rs {x.price_inr:g}" if x.price_inr is not None else "") + ")" for x in active)) if active else ""

    def check_slots(self, service: str | None, day: str | None) -> str:
        svc, err = _pick_service(self.db, self.tenant.id, service)
        if svc is None:
            return err or "No services can be booked yet."
        try:
            d = date.fromisoformat((day or "").strip())
        except ValueError:
            d = self.now.astimezone(IST).date()
        sl = slots_for_day(self.db, self.tenant.id, self.s, svc, d, now=self.now)
        head = f"{svc.name} ({svc.duration_minutes} minutes)"
        if sl:
            return f"{head}. Free times on {d.strftime('%a')} {d.day} {d.strftime('%b')} (date {d.isoformat()}): " + ", ".join(f"{clock_text(x)} (time {x.astimezone(IST).strftime('%H:%M')})" for x in sl[:12])
        more = next_open_days(self.db, self.tenant.id, self.s, svc, d + timedelta(days=1), 3, now=self.now)
        tail = " Next free days: " + "; ".join(f"{x.strftime('%a')} {x.day} {x.strftime('%b')} (date {x.isoformat()}): " + ", ".join(clock_text(t) for t in sl2[:4]) for x, sl2 in more) if more else " No free time in the coming weeks."
        return f"{head}. No free time on {d.strftime('%a')} {d.day} {d.strftime('%b')}." + tail

    def _mine(self, code: str | None) -> tuple[WhatsAppBooking | None, str | None]:
        up = upcoming_for_contact(self.db, self.tenant.id, self.contact.id, self.now)
        if code:
            hit = [b for b in up if b.code.lower() == code.strip().lower()]
            return (hit[0], None) if hit else (None, "No upcoming booking with that code for this customer.")
        if not up:
            return None, "This customer has no upcoming booking."
        if len(up) > 1:
            return None, "This customer has several bookings: " + "; ".join(f"{b.code} {b.service_name} {when_text(b.starts_at)}" for b in up) + ". Ask which one."
        return up[0], None

    def book(self, service: str | None, day: str | None, at: str | None) -> ToolResult:
        svc, err = _pick_service(self.db, self.tenant.id, service)
        if svc is None:
            return ToolResult(fact=err)
        try:
            start = parse_start(day or "", at or "")
        except WaError:
            return ToolResult(fact="That date or time was not valid. Use a date like 2026-11-21 and a 24-hour time like 10:30.")
        try:
            with self.db.begin_nested():
                b, created = book(self.db, self.tenant, self.contact, svc, start, source="ai", conversation=self.conv, idem_key="ai:" + hashlib.sha256(f"{self.conv.id}:{self.key}:{svc.id}:{start.isoformat()}".encode()).hexdigest()[:40], now=self.now)
        except WaError as exc:
            return ToolResult(fact=f"That could not be booked: {exc.message}. " + self.check_slots(svc.name, day))
        text = ai_text.say(ai_text.BOOKED, self.lang, self.tenant.name, service=b.service_name, when=when_text(b.starts_at)) + " " + ai_text.say(ai_text.ASK_UPDATES, self.lang, self.tenant.name)
        return ToolResult(final=text, booking=b, ask_consent=created)

    def reschedule(self, code: str | None, day: str | None, at: str | None) -> ToolResult:
        b, err = self._mine(code)
        if b is None:
            return ToolResult(fact=err)
        try:
            start = parse_start(day or "", at or "")
            with self.db.begin_nested():
                reschedule(self.db, self.tenant, b, start, now=self.now)
        except WaError as exc:
            return ToolResult(fact=f"That could not be moved: {exc.message}. " + self.check_slots(b.service_name, day))
        return ToolResult(final=ai_text.say(ai_text.RESCHEDULED, self.lang, self.tenant.name, service=b.service_name, when=when_text(b.starts_at)), booking=b)

    def cancel(self, code: str | None) -> ToolResult:
        b, err = self._mine(code)
        if b is None:
            return ToolResult(fact=err)
        with self.db.begin_nested():
            cancel(self.db, self.tenant, b, "cancelled by the customer in the chat", now=self.now)
        return ToolResult(final=ai_text.say(ai_text.CANCELLED, self.lang, self.tenant.name, service=b.service_name, when=when_text(b.starts_at)), booking=b)


class DryTools(ChatTools):
    """"Test it": the real availability, but nothing is ever booked, changed or sent."""

    live = False

    def __init__(self, db: Session, tenant: Tenant, lang: str, now: datetime | None = None):
        self.db, self.tenant, self.lang, self.now = db, tenant, lang, now or utcnow()
        self.s = get_settings(db, tenant.id)
        self.contact = self.conv = None

    def _dry(self, what: str) -> ToolResult:
        return ToolResult(final=f"(Test only: in a real chat this would {what}. Nothing was booked or changed, and nothing was sent to WhatsApp.)")

    def book(self, service, day, at):
        svc, err = _pick_service(self.db, self.tenant.id, service)
        if svc is None:
            return ToolResult(fact=err)
        try:
            start = parse_start(day or "", at or "")
            check_available(self.db, self.tenant.id, self.s, svc, start, now=self.now)
        except WaError as exc:
            return ToolResult(fact=f"That could not be booked: {exc.message}. " + self.check_slots(svc.name, day))
        return self._dry(f"book {svc.name} on {when_text(start)}")

    def reschedule(self, code, day, at):
        return self._dry("move the customer's booking")

    def cancel(self, code):
        return self._dry("cancel the customer's booking")


# ---- reminders
def _reminder_state(db: Session, tenant_id: uuid.UUID, key: str):
    row = templates.standard_row(db, tenant_id, key)
    return row if row is not None and row.approval_status == "approved" else None


def _send_reminder(db: Session, tenant: Tenant, b: WhatsAppBooking, key: str, now: datetime) -> str:
    tpl = _reminder_state(db, tenant.id, key)
    if tpl is None:
        return "template_not_approved"
    contact = db.get(WhatsAppContact, b.contact_id)
    if contact is None:
        return "no_customer"
    if not rules.in_occasion_hours(now):
        return "outside_hours"  # a reminder is never sent in the middle of the night
    res = sender.send_template(db, tenant, contact, tpl, [templates.first_name(contact.customer_name) or "there", tenant.name, b.service_name, when_text(b.starts_at)], idem_key=f"bk:{b.id}:{key}:{b.starts_at.isoformat()}", kind="booking_reminder", now=now)
    return "sent" if res.ok else ("retry" if res.status == "retry" else res.reason)


def run_reminders(db: Session, now: datetime | None = None, tenant_id: uuid.UUID | None = None, limit: int = 200) -> dict:
    """The worker pass. Day-before reminder: from the chosen hour the day before. Second reminder: a few hours before. Each is attempted until it is sent or refused for a reason that will not change (no
    consent, STOP, template not approved...): a refusal is recorded and never retried, so nothing is ever sent late or twice. Does nothing unless bookings, reminders and sending are all on."""
    now = now or utcnow()
    out = {"sent": 0, "skipped": 0}
    if not platform_on() or not settings.whatsapp_sending_enabled or settings.whatsapp_emergency_stop:
        return {"held": True}
    q = select(WhatsAppBookingSettings).where(WhatsAppBookingSettings.enabled.is_(True), WhatsAppBookingSettings.reminders_enabled.is_(True))
    if tenant_id is not None:
        q = q.where(WhatsAppBookingSettings.tenant_id == tenant_id)
    for s in db.scalars(q):
        tenant = db.get(Tenant, s.tenant_id)
        if tenant is None or not addons.bookings_allowed(db, tenant.id):
            continue
        soon_at = timedelta(hours=s.reminder_soon_hours)
        rows = db.scalars(select(WhatsAppBooking).where(WhatsAppBooking.tenant_id == tenant.id, WhatsAppBooking.status == "booked", WhatsAppBooking.starts_at > now,
                                                         WhatsAppBooking.starts_at < now + timedelta(days=2)).order_by(WhatsAppBooking.starts_at).limit(limit))
        for b in rows:
            local = b.starts_at.astimezone(IST)
            day_due = to_utc(local.date() - timedelta(days=1), time(s.reminder_day_hour, 0))
            if b.reminder_day_result is None and now >= day_due and b.starts_at - now > soon_at + timedelta(hours=1):
                r = _send_reminder(db, tenant, b, "booking_reminder_day", now)
                if r not in ("retry", "template_not_approved"):  # not approved yet: tried again on the next pass while it is still useful
                    b.reminder_day_at, b.reminder_day_result = now, r[:40]
                    out["sent" if r == "sent" else "skipped"] += 1
            if b.reminder_soon_result is None and b.starts_at - now <= soon_at and b.starts_at - now > timedelta(minutes=15):
                r = _send_reminder(db, tenant, b, "booking_reminder_soon", now)
                if r not in ("retry", "template_not_approved"):
                    b.reminder_soon_at, b.reminder_soon_result = now, r[:40]
                    out["sent" if r == "sent" else "skipped"] += 1
    return out
