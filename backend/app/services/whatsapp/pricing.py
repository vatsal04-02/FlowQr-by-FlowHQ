"""Meta's per-message charges, as DATED DATA (table whatsapp_rates), never as constants in code.

* A rate has a country, a category, an effective date and a source; a change is a new row with a new date, old rows are never edited, so any past message can be re-estimated at the rate that applied.
* Everything here is an ESTIMATE. Meta bills per delivered template message, can apply volume tiers or free allowances, and changes rates; the estimate uses the rate in force and is labelled as an estimate.
  Whether a row is `verified` (checked against Meta's own rate card by an administrator) is shown with every estimate. That is read from the LATEST check in
  whatsapp_rate_verifications (an append-only record), so a check never edits a rate row; a row with no check keeps the flag it was written with.
* A rate row can carry a free allowance (`free_per_number_month`, for example Meta's first 1,000 service messages per number per month). The estimate subtracts it; it is never ignored.
* Meta's charges are never added to, or hidden inside, FlowQR's add-on fee.
"""
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User
from app.models.base import utcnow
from app.models.whatsapp import RATE_CATEGORIES, WhatsAppMessage, WhatsAppRate, WhatsAppRateVerification
from app.services.audit import audit
from app.services.whatsapp import WaError

COUNTRY = "IN"
NOTE = "An estimate of WhatsApp's charge, not a bill. WhatsApp charges for each delivered message and can change its rates. FlowQR's fee is separate."
WARNING = "These prices are starting values and have not been checked against WhatsApp's own price list yet. Treat every cost here as a rough guide."


def rate_for(db: Session, category: str, on: date | None = None, country: str = COUNTRY) -> WhatsAppRate | None:
    on = on or utcnow().date()
    return db.scalar(select(WhatsAppRate).where(WhatsAppRate.country == country, WhatsAppRate.category == category, WhatsAppRate.effective_from <= on).order_by(WhatsAppRate.effective_from.desc()).limit(1))


def latest_verification(db: Session, rate_id: uuid.UUID) -> WhatsAppRateVerification | None:
    return db.scalar(select(WhatsAppRateVerification).where(WhatsAppRateVerification.rate_id == rate_id).order_by(WhatsAppRateVerification.created_at.desc(), WhatsAppRateVerification.id.desc()).limit(1))


def is_verified(db: Session, r: WhatsAppRate) -> bool:
    """True only if the newest check of this row says it matches Meta's rate card (or, with no check at all, the row was written as verified)."""
    v = latest_verification(db, r.id)
    return bool(v.verified) if v is not None else bool(r.verified)


def _money(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def free_left(r: WhatsAppRate, already_used: int = 0) -> int:
    return max(0, int(r.free_per_number_month or 0) - max(0, already_used))


def estimate(db: Session, category: str, count: int, on: date | None = None, already_used: int = 0) -> dict:
    """What `count` delivered messages of this category would cost at the rate in force, after any free allowance (`already_used` = messages of this category already sent from this number this month).
    `amount` is None when no rate is known (then no cost is claimed)."""
    r = rate_for(db, category, on)
    if r is None:
        return {"category": category, "count": count, "rate": None, "currency": None, "amount": None, "verified": False, "rate_source": None, "effective_from": None, "free_included": 0, "billable": count,
                "warning": WARNING, "note": NOTE + " No rate is set for this kind of message."}
    free = min(count, free_left(r, already_used))
    billable = count - free
    ok = is_verified(db, r)
    return {"category": category, "count": count, "rate": str(r.rate), "currency": r.currency, "amount": str(_money(r.rate * billable)), "verified": ok, "rate_source": r.source,
            "effective_from": r.effective_from.isoformat(), "free_included": free, "billable": billable, "free_per_number_month": int(r.free_per_number_month or 0), "warning": None if ok else WARNING,
            "note": NOTE + ("" if ok else " The rate has not been checked against WhatsApp's own rate card yet.") + (f" The first {r.free_per_number_month:,} of these each month per number are free." if r.free_per_number_month else "")}


def est_rate_for_send(db: Session, tenant_id: uuid.UUID, category: str) -> Decimal | None:
    """The estimated charge to record against one message about to be sent: the rate in force, or 0 while the category's monthly free allowance for this number has room."""
    r = rate_for(db, category)
    if r is None:
        return None
    if not r.free_per_number_month:
        return r.rate
    month_start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(select(func.count()).select_from(WhatsAppMessage).where(WhatsAppMessage.tenant_id == tenant_id, WhatsAppMessage.direction == "outbound", WhatsAppMessage.category == category,
                                                                              WhatsAppMessage.created_at >= month_start, WhatsAppMessage.delivery_status != "failed")) or 0
    return Decimal(0) if free_left(r, used) > 0 else r.rate


def add_rate(db: Session, admin: User, *, category: str, rate: Decimal, effective_from: date, source: str, verified: bool, country: str = COUNTRY, free_per_number_month: int = 0, ip: str | None = None) -> WhatsAppRate:
    if category not in RATE_CATEGORIES:
        raise WaError(422, "invalid_category", "Unknown message category.")
    if rate < 0 or rate > Decimal("1000"):
        raise WaError(422, "invalid_rate", "That rate is not realistic.")
    if free_per_number_month < 0 or free_per_number_month > 10_000_000:
        raise WaError(422, "invalid_free_allowance", "The free allowance must be a whole number of messages, 0 or more.")
    source = " ".join((source or "").split())
    if len(source) < 10:
        raise WaError(422, "source_required", "Write where this rate comes from, for example: Meta rate card for India, effective 1 Jan 2026.")
    if db.scalar(select(WhatsAppRate.id).where(WhatsAppRate.country == country, WhatsAppRate.category == category, WhatsAppRate.effective_from == effective_from)):
        raise WaError(409, "rate_exists", "A rate for that category and date already exists. Add a new one with a later date; existing rates are never edited.")
    row = WhatsAppRate(country=country, category=category, rate=rate, currency="INR", effective_from=effective_from, source=source[:300], verified=verified, free_per_number_month=free_per_number_month, created_by=admin.id)
    db.add(row)
    db.flush()
    audit(db, action="admin.whatsapp_rate", entity_type="whatsapp_rate", entity_id=row.id, user_id=admin.id,
          meta={"category": category, "rate": str(rate), "from": effective_from.isoformat(), "verified": verified, "free_per_number_month": free_per_number_month}, ip=ip)
    if verified:  # saying "verified" is itself a check, so it is recorded the same way as any other
        add_verification(db, admin, row.id, True, "Marked as checked when the rate was added. " + source, ip=ip)
    return row


def add_verification(db: Session, admin: User, rate_id: uuid.UUID, verified: bool, note: str, ip: str | None = None) -> WhatsAppRateVerification:
    """Record that an administrator checked this rate row against Meta's own rate card. Appends a record; the rate row and earlier checks are never changed."""
    if db.get(WhatsAppRate, rate_id) is None:
        raise WaError(404, "rate_not_found", "That rate does not exist.")
    note = " ".join((note or "").split())
    if len(note) < 10:
        raise WaError(422, "note_required", "Write what you checked, for example: Matches Meta's India rate card, page dated 1 Oct 2026.")
    row = WhatsAppRateVerification(rate_id=rate_id, verified=verified, note=note[:300], verified_by=admin.id)
    db.add(row)
    db.flush()
    audit(db, action="admin.whatsapp_rate_verification", entity_type="whatsapp_rate", entity_id=rate_id, user_id=admin.id, meta={"verified": verified}, ip=ip)
    return row


def serialize(r: WhatsAppRate, v: WhatsAppRateVerification | None = None, *, in_force: bool | None = None, who: str | None = None) -> dict:
    out = {"id": r.id, "country": r.country, "category": r.category, "rate": str(r.rate), "currency": r.currency, "effective_from": r.effective_from.isoformat(), "source": r.source,
           "verified": bool(v.verified) if v is not None else bool(r.verified), "free_per_number_month": int(r.free_per_number_month or 0),
           "verification": None if v is None else {"verified": v.verified, "note": v.note, "at": v.created_at, "by": who}}
    if in_force is not None:
        out["in_force"] = in_force
    return out


def list_rates(db: Session) -> list[dict]:
    """Every rate row ever written (history is never dropped), newest first within each country and category, each with its latest check and whether it is the one in force today."""
    today = utcnow().date()
    rows = list(db.scalars(select(WhatsAppRate).order_by(WhatsAppRate.country, WhatsAppRate.category, WhatsAppRate.effective_from.desc())))
    latest: dict[uuid.UUID, WhatsAppRateVerification] = {}
    for v in db.scalars(select(WhatsAppRateVerification).order_by(WhatsAppRateVerification.created_at.asc(), WhatsAppRateVerification.id.asc())):
        latest[v.rate_id] = v  # the last one wins
    ids = [v.verified_by for v in latest.values() if v.verified_by]
    names = {u.id: (u.email or u.full_name) for u in db.scalars(select(User).where(User.id.in_(ids))).all()} if ids else {}
    seen: set[tuple[str, str]] = set()
    out = []
    for r in rows:
        key = (r.country, r.category)
        force = key not in seen and r.effective_from <= today
        if force:
            seen.add(key)
        v = latest.get(r.id)
        out.append(serialize(r, v, in_force=force, who=names.get(v.verified_by) if v is not None and v.verified_by else None))
    return out


def unverified_in_use(db: Session, categories: tuple[str, ...] = ("marketing", "utility")) -> list[str]:
    """The categories whose rate in force today has not been checked against Meta's rate card (or has no rate at all). Owners' cost screens show a banner while this is not empty."""
    bad = []
    for c in categories:
        r = rate_for(db, c)
        if r is None or not is_verified(db, r):
            bad.append(c)
    return bad
