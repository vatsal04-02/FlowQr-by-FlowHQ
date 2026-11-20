"""What the owner tells the assistant, and how many replies a month a tier includes.

KNOWLEDGE. The assistant may say only what is in `whatsapp_knowledge_items`: about, address, hours, services (with prices), FAQs, policies and booking rules. **Offers are not a kind and are never
copied in**: an offer is marketing and the assistant never talks about offers. Pre-filling from the business's own details (name, description, services, hours, FAQs, address) copies only those and
never the offers list. Nothing is fetched from a website in this phase (deferred).

QUOTA. `whatsapp_ai_quotas` is dated and append-only (a change is a new row with a new date). Each assistant reply that is sent counts one; the month is the Indian calendar month. Starter has none.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Location, Tenant, User
from app.models.base import utcnow
from app.models.whatsapp import ADDON_KEYS, KNOWLEDGE_KINDS, WhatsAppAiQuota, WhatsAppAiRun, WhatsAppKnowledgeItem
from app.services.audit import audit
from app.services.whatsapp import WaError, addons

IST = timezone(timedelta(hours=5, minutes=30))
MAX_ITEMS = 80
MAX_BODY = 1200
MAX_TITLE = 120
SINGLE_KINDS = ("about", "address", "hours")  # one of each is plenty; more would be a second "about"
KIND_WORDS = {"about": "About the business", "address": "Address and how to find you", "hours": "Opening hours", "service": "Services and prices", "faq": "Frequently asked questions", "policy": "Policies", "booking_rule": "Booking rules"}
NOT_OFFERS = "Do not put offers, discounts or coupons here. The assistant never talks about offers: those go through Offers, to customers who agreed to them."

_SUGGEST = {
    "clinic": ["Do I need a referral or an appointment?", "How long is a visit and what should I bring?", "Do you take insurance or cards, and what is the first visit fee?", "How do I cancel or move an appointment?"],
    "salon": ["Do you take walk-ins or only appointments?", "How long does a haircut, colour or facial take?", "What is the price list for your main services?", "How early should I come for bridal makeup?"],
    "restaurant": ["Do you take bookings and for how many people?", "Is the food veg, non-veg or both?", "Do you do home delivery or party orders, and with how much notice?", "Is there parking?"],
    "gym": ["Is there a trial pass?", "What are the membership options and what do they include?", "Are there women-only or beginner batches?", "What are the timings on Sunday?"],
    "retail": ["Do you give a bill and warranty?", "Do you exchange or repair?", "Which brands or items do you keep?", "Do you deliver nearby?"],
    "coaching": ["Is there a demo class?", "Which classes, boards and subjects do you teach?", "What are the batch timings and fees?", "How do I meet the teacher?"],
    "general": ["What are your timings, including holidays?", "Where are you and how do I get there?", "How do I book or order?", "What is your cancellation or refund policy?"],
}
_KIND_BY_WORD = (("clinic", ("physio", "dental", "dentist", "clinic", "doctor", "hospital", "diagnostic", "therapy", "dermat", "ortho")), ("salon", ("salon", "spa", "beauty", "barber", "makeup", "parlour", "parlor")),
                 ("restaurant", ("restaurant", "cafe", "café", "bakery", "food", "kitchen", "dhaba", "sweet")), ("gym", ("gym", "fitness", "yoga", "crossfit", "zumba")),
                 ("retail", ("shop", "store", "mobile", "retail", "boutique", "supermarket", "electronics")), ("coaching", ("coaching", "classes", "tuition", "academy", "institute", "school")))


def business_type(category: str | None) -> str:
    c = (category or "").lower()
    for kind, words in _KIND_BY_WORD:
        if any(w in c for w in words):
            return kind
    return "general"


def suggestions(tenant: Tenant) -> dict:
    """Guided set-up: what to write for each section, with example questions for this kind of business. Plain prompts; nothing is filled in for the owner."""
    t = business_type(tenant.category)
    return {"business_type": t, "questions": _SUGGEST[t], "sections": [{"kind": k, "label": KIND_WORDS[k], "single": k in SINGLE_KINDS} for k in KNOWLEDGE_KINDS], "warning": NOT_OFFERS,
            "examples": {"about": "A physiotherapy clinic in Gomti Nagar for back and neck pain and sports injuries.", "hours": "Monday to Saturday 9 am to 7 pm. Closed on Sunday.", "address": "Shop 4, Main Road, Gomti Nagar, Lucknow. Next to the post office.",
                         "service": "Back pain assessment, 45 minutes, price 600 rupees.", "faq": "Do I need a referral? No, you can book directly.", "policy": "Please tell us 4 hours before if you need to cancel.",
                         "booking_rule": "Appointments are booked by phone or WhatsApp, a day ahead if possible."}}


# ---- items
def _price(v) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v).replace(",", "").strip())
    except InvalidOperation:
        raise WaError(422, "invalid_price", "The price must be a number of rupees, for example 600.")
    if d < 0 or d > Decimal("10000000"):
        raise WaError(422, "invalid_price", "The price must be a number of rupees, for example 600.")
    return d.quantize(Decimal("0.01"))


def _clean(s: str | None, limit: int) -> str:
    return " ".join((s or "").split())[:limit] if limit <= MAX_TITLE else "\n".join(" ".join(line.split()) for line in (s or "").strip().splitlines() if line.strip())[:limit]


def list_items(db: Session, tenant_id: uuid.UUID, *, active_only: bool = False) -> list[WhatsAppKnowledgeItem]:
    q = select(WhatsAppKnowledgeItem).where(WhatsAppKnowledgeItem.tenant_id == tenant_id)
    if active_only:
        q = q.where(WhatsAppKnowledgeItem.active.is_(True))
    return list(db.scalars(q.order_by(WhatsAppKnowledgeItem.kind, WhatsAppKnowledgeItem.position, WhatsAppKnowledgeItem.created_at)))


def get_item(db: Session, tenant_id: uuid.UUID, item_id: uuid.UUID) -> WhatsAppKnowledgeItem:
    row = db.get(WhatsAppKnowledgeItem, item_id)
    if row is None or row.tenant_id != tenant_id:
        raise WaError(404, "not_found", "That item was not found.")
    return row


def serialize_item(r: WhatsAppKnowledgeItem) -> dict:
    return {"id": r.id, "kind": r.kind, "title": r.title, "body": r.body, "price_inr": float(r.price_inr) if r.price_inr is not None else None, "active": r.active, "position": r.position, "updated_at": r.updated_at}


def _validate(kind: str, title, body, price) -> tuple[str | None, str, Decimal | None]:
    if kind not in KNOWLEDGE_KINDS:
        raise WaError(422, "invalid_kind", "Unknown section.")
    body = _clean(body, MAX_BODY)
    if len(body) < 2:
        raise WaError(422, "body_required", "Write what the assistant may say.")
    if len((body or "")) > MAX_BODY:
        raise WaError(422, "too_long", f"Keep it under {MAX_BODY} characters.")
    from app.services.whatsapp import rules
    if rules.marketing_terms(f"{title or ''} {body}"):
        raise WaError(422, "offers_not_allowed", NOT_OFFERS)
    if price is not None and kind != "service":
        raise WaError(422, "price_only_for_services", "Only a service has a price.")
    return (_clean(title, MAX_TITLE) or None), body, _price(price)


def create_item(db: Session, tenant: Tenant, user: User, *, kind: str, title=None, body=None, price_inr=None, ip: str | None = None) -> WhatsAppKnowledgeItem:
    title, body, price = _validate(kind, title, body, price_inr)
    existing = list_items(db, tenant.id)
    if len(existing) >= MAX_ITEMS:
        raise WaError(409, "too_many", f"You can keep up to {MAX_ITEMS} items. Remove one first.")
    if kind in SINGLE_KINDS and any(i.kind == kind for i in existing):
        raise WaError(409, "already_there", f"There is already one \"{KIND_WORDS[kind]}\" item. Edit it instead.")
    row = WhatsAppKnowledgeItem(tenant_id=tenant.id, kind=kind, title=title, body=body, price_inr=price, active=True, position=len([i for i in existing if i.kind == kind]))
    db.add(row)
    db.flush()
    audit(db, action="whatsapp.ai_knowledge_add", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_knowledge_item", entity_id=row.id, meta={"kind": kind}, ip=ip)
    return row


def update_item(db: Session, tenant: Tenant, user: User, item: WhatsAppKnowledgeItem, *, title=None, body=None, price_inr=None, active=None, set_price: bool = False, ip: str | None = None) -> WhatsAppKnowledgeItem:
    t, b, p = _validate(item.kind, title if title is not None else item.title, body if body is not None else item.body, (price_inr if set_price else item.price_inr))
    item.title, item.body, item.price_inr = t, b, p
    if active is not None:
        item.active = bool(active)
    db.flush()
    audit(db, action="whatsapp.ai_knowledge_edit", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_knowledge_item", entity_id=item.id, meta={"kind": item.kind, "active": item.active}, ip=ip)
    return item


def delete_item(db: Session, tenant: Tenant, user: User, item: WhatsAppKnowledgeItem, ip: str | None = None) -> None:
    audit(db, action="whatsapp.ai_knowledge_delete", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_knowledge_item", entity_id=item.id, meta={"kind": item.kind}, ip=ip)
    db.delete(item)
    db.flush()


def import_existing(db: Session, tenant: Tenant, user: User, ip: str | None = None) -> dict:
    """Pre-fill from the business's OWN details: description, services, hours, FAQs and the first location's address. Only kinds that are still empty are filled. Offers are never copied."""
    from app.services.agent import knowledge as kb

    have = {i.kind for i in list_items(db, tenant.id)}
    ctx = kb.context(db, tenant)
    made = 0
    adds: list[tuple[str, str | None, str, None]] = []
    if "about" not in have and ctx["description"].strip():
        adds.append(("about", None, ctx["description"].strip(), None))
    if "hours" not in have and ctx["hours"].strip():
        adds.append(("hours", None, ctx["hours"].strip(), None))
    if "address" not in have:
        loc = db.scalar(select(Location).where(Location.tenant_id == tenant.id).order_by(Location.created_at))
        if loc is not None and (loc.address_line or loc.city):
            adds.append(("address", None, ", ".join(x for x in (loc.address_line, loc.city) if x), None))
    if "service" not in have:
        adds += [("service", None, s, None) for s in ctx["services"][:20]]
    if "faq" not in have:
        adds += [("faq", f.get("q", "")[:120], f"{f.get('q', '')} {f.get('a', '')}".strip(), None) for f in ctx["faqs"][:15] if f.get("q") and f.get("a")]
    from app.services.whatsapp import rules
    for kind, title, body, _ in adds:
        if rules.marketing_terms(body):  # the owner's own text mentioned an offer: left out, they can add it by hand if it is not one
            continue
        try:
            create_item(db, tenant, user, kind=kind, title=title, body=body, ip=ip)
            made += 1
        except WaError:
            continue
    return {"added": made}


def readiness(items: list[WhatsAppKnowledgeItem]) -> dict:
    """The assistant needs enough to be useful and safe: what the business is, when it is open, and at least one service or FAQ. Anything else is optional."""
    act = [i for i in items if i.active]
    kinds = {i.kind for i in act}
    missing = [KIND_WORDS[k] for k in ("about", "hours") if k not in kinds]
    if not ({"service", "faq"} & kinds):
        missing.append("At least one service or FAQ")
    return {"ready": not missing, "missing": missing, "count": len(act)}


# ---- the assistant's view: numbered facts the model can cite
def render_facts(tenant: Tenant, items: list[WhatsAppKnowledgeItem]) -> tuple[str, dict[str, str]]:
    """The facts block placed in the prompt, each item numbered K1..Kn, and {K-number: its text} for checking a reply's claims. Only the business name is added: no customer, no offers."""
    lines, by_id = [], {}
    n = 0
    for it in items:
        if not it.active:
            continue
        n += 1
        key = f"K{n}"
        price = f" Price: Rs {it.price_inr:g}." if it.price_inr is not None else ""
        text = f"[{key}] ({KIND_WORDS[it.kind]}) {(it.title + ': ') if it.title else ''}{it.body}{price}"
        lines.append(text)
        by_id[key] = f"{it.title or ''} {it.body}{(' ' + format(it.price_inr, 'f') + ' ' + format(it.price_inr, 'g')) if it.price_inr is not None else ''}"
    return "\n".join(lines), by_id


def search(items: list[WhatsAppKnowledgeItem], query: str, limit: int = 4) -> list[WhatsAppKnowledgeItem]:
    """A plain keyword lookup over this business's own active items (the assistant's one lookup tool)."""
    words = {w for w in "".join(c.lower() if c.isalnum() else " " for c in query or "").split() if len(w) > 2}
    scored = []
    for it in items:
        if not it.active:
            continue
        hay = f"{it.title or ''} {it.body}".lower()
        sc = sum(1 for w in words if w in hay)
        if sc:
            scored.append((sc, it))
    scored.sort(key=lambda x: -x[0])
    return [it for _, it in scored[:limit]]


# ---- quota (dated)
def month_key(now: datetime | None = None) -> str:
    return (now or utcnow()).astimezone(IST).strftime("%Y-%m")


def month_start(now: datetime | None = None) -> datetime:
    n = (now or utcnow()).astimezone(IST)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def quota_for(db: Session, addon_key: str, on: date | None = None) -> int:
    on = on or utcnow().astimezone(IST).date()
    row = db.scalar(select(WhatsAppAiQuota).where(WhatsAppAiQuota.addon_key == addon_key, WhatsAppAiQuota.effective_from <= on).order_by(WhatsAppAiQuota.effective_from.desc(), WhatsAppAiQuota.created_at.desc()).limit(1))
    return row.monthly_replies if row is not None else 0


def used_this_month(db: Session, tenant_id: uuid.UUID, now: datetime | None = None) -> int:
    return db.scalar(select(func.count()).select_from(WhatsAppAiRun).where(WhatsAppAiRun.tenant_id == tenant_id, WhatsAppAiRun.counted.is_(True), WhatsAppAiRun.is_test.is_(False), WhatsAppAiRun.created_at >= month_start(now))) or 0


def quota_status(db: Session, tenant_id: uuid.UUID, now: datetime | None = None) -> dict:
    now = now or utcnow()
    a = addons.active_addon(db, tenant_id)
    limit = quota_for(db, a.addon_key, now.astimezone(IST).date()) if a is not None else 0
    from app.core.config import settings
    if a is None and not settings.whatsapp_require_addon:
        limit = quota_for(db, "whatsapp_growth", now.astimezone(IST).date())  # no add-on required (development): the Growth allowance applies
    used = used_this_month(db, tenant_id, now)
    return {"limit": limit, "used": used, "remaining": max(0, limit - used), "month": month_key(now), "near_limit": limit > 0 and used >= int(limit * 0.8), "tier": a.addon_key if a else None}


def list_quotas(db: Session) -> list[dict]:
    rows = db.scalars(select(WhatsAppAiQuota).order_by(WhatsAppAiQuota.addon_key, WhatsAppAiQuota.effective_from.desc()))
    return [{"id": r.id, "addon_key": r.addon_key, "monthly_replies": r.monthly_replies, "effective_from": r.effective_from, "note": r.note, "created_at": r.created_at} for r in rows]


def add_quota(db: Session, admin: User, *, addon_key: str, monthly_replies: int, effective_from: date, note: str, ip: str | None = None) -> WhatsAppAiQuota:
    """A change is a NEW dated row; old rows are never edited. A written reason is required."""
    note = " ".join((note or "").split())
    if addon_key not in ADDON_KEYS:
        raise WaError(422, "invalid_addon", "Unknown tier.")
    if monthly_replies < 0 or monthly_replies > 100000:
        raise WaError(422, "invalid_quota", "The monthly replies must be between 0 and 100000.")
    if len(note) < 5:
        raise WaError(422, "note_required", "Write a short reason (for example: raised to 300 after a month of real use).")
    if db.scalar(select(WhatsAppAiQuota).where(WhatsAppAiQuota.addon_key == addon_key, WhatsAppAiQuota.effective_from == effective_from)):
        raise WaError(409, "date_taken", "There is already a value from that date. Add the change with a later date.")
    row = WhatsAppAiQuota(addon_key=addon_key, monthly_replies=monthly_replies, effective_from=effective_from, note=note[:300], created_by=admin.id)
    db.add(row)
    db.flush()
    audit(db, action="admin.whatsapp_ai_quota", tenant_id=None, user_id=admin.id, entity_type="whatsapp_ai_quota", entity_id=row.id, meta={"addon_key": addon_key, "monthly_replies": monthly_replies, "from": str(effective_from)}, ip=ip)
    return row
