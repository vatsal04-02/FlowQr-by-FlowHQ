"""Meta's per-message charges, as DATED DATA (table whatsapp_rates), never as constants in code.

* A rate has a country, a category, an effective date and a source; a change is a new row with a new date, old rows are never edited, so any past message can be re-estimated at the rate that applied.
* Everything here is an ESTIMATE. Meta bills per delivered template message, can apply volume tiers or free allowances, and changes rates; the estimate uses the rate in force and is labelled as an estimate.
  Whether a row is `verified` (checked against Meta's own rate card by an administrator) is shown with every estimate.
* Meta's charges are never added to, or hidden inside, FlowQR's add-on fee.
"""
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.models.base import utcnow
from app.models.whatsapp import RATE_CATEGORIES, WhatsAppRate
from app.services.audit import audit
from app.services.whatsapp import WaError

COUNTRY = "IN"
NOTE = "An estimate of WhatsApp's charge, not a bill. WhatsApp charges for each delivered message and can change its rates. FlowQR's fee is separate."


def rate_for(db: Session, category: str, on: date | None = None, country: str = COUNTRY) -> WhatsAppRate | None:
    on = on or utcnow().date()
    return db.scalar(select(WhatsAppRate).where(WhatsAppRate.country == country, WhatsAppRate.category == category, WhatsAppRate.effective_from <= on).order_by(WhatsAppRate.effective_from.desc()).limit(1))


def _money(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def estimate(db: Session, category: str, count: int, on: date | None = None) -> dict:
    """What `count` delivered messages of this category would cost at the rate in force. `amount` is None when no rate is known (then no cost is claimed)."""
    r = rate_for(db, category, on)
    if r is None:
        return {"category": category, "count": count, "rate": None, "currency": None, "amount": None, "verified": False, "rate_source": None, "effective_from": None, "note": NOTE + " No rate is set for this kind of message."}
    return {"category": category, "count": count, "rate": str(r.rate), "currency": r.currency, "amount": str(_money(r.rate * count)), "verified": bool(r.verified), "rate_source": r.source,
            "effective_from": r.effective_from.isoformat(), "note": NOTE + ("" if r.verified else " The rate has not been checked against WhatsApp's own rate card yet.")}


def add_rate(db: Session, admin: User, *, category: str, rate: Decimal, effective_from: date, source: str, verified: bool, country: str = COUNTRY, ip: str | None = None) -> WhatsAppRate:
    if category not in RATE_CATEGORIES:
        raise WaError(422, "invalid_category", "Unknown message category.")
    if rate < 0 or rate > Decimal("1000"):
        raise WaError(422, "invalid_rate", "That rate is not realistic.")
    source = " ".join((source or "").split())
    if len(source) < 10:
        raise WaError(422, "source_required", "Write where this rate comes from, for example: Meta rate card for India, effective 1 Jan 2026.")
    if db.scalar(select(WhatsAppRate.id).where(WhatsAppRate.country == country, WhatsAppRate.category == category, WhatsAppRate.effective_from == effective_from)):
        raise WaError(409, "rate_exists", "A rate for that category and date already exists. Add a new one with a later date; existing rates are never edited.")
    row = WhatsAppRate(country=country, category=category, rate=rate, currency="INR", effective_from=effective_from, source=source[:300], verified=verified, created_by=admin.id)
    db.add(row)
    db.flush()
    audit(db, action="admin.whatsapp_rate", entity_type="whatsapp_rate", entity_id=row.id, user_id=admin.id, meta={"category": category, "rate": str(rate), "from": effective_from.isoformat(), "verified": verified}, ip=ip)
    return row


def serialize(r: WhatsAppRate) -> dict:
    return {"id": r.id, "country": r.country, "category": r.category, "rate": str(r.rate), "currency": r.currency, "effective_from": r.effective_from.isoformat(), "source": r.source, "verified": r.verified}


def list_rates(db: Session) -> list[dict]:
    return [serialize(r) for r in db.scalars(select(WhatsAppRate).order_by(WhatsAppRate.country, WhatsAppRate.category, WhatsAppRate.effective_from.desc()))]
