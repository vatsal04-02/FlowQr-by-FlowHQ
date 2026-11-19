"""Birthday and festival greetings.

What this is: a short, neutral greeting on a customer's birthday (once a year) or on a festival the business chose, sent only to customers who agreed to occasion greetings. It is never an offer and
never mentions a discount (the two message texts are fixed and festival names are checked), it goes out at the hour the business chose between 9 am and 9 pm India time, and a greeting that missed
its day is skipped, never sent late.

How it stays inside the rules: this module only SCHEDULES. Every greeting is an automation run executed through `sender.send_template(kind="occasion")`, the single send gate. The gate requires:
the add-on (Growth or Pro), the helper being on within the plan's helper count, the greeting's own approved template, occasion consent, offers consent too while the template's category is marketing or
not yet known (fail closed), no STOP, the hours, the greeting's own 14-day cap, the global switches and the emergency stop. Nothing here can bypass those.

Dates: a birthday is a day and a month, never a year. A 29 February birthday is greeted on 28 February in years that have no 29 February. All "today" decisions use India time.
"""
import logging
import re
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Tenant, User
from app.models.base import utcnow
from app.models.whatsapp import WhatsAppAutomation, WhatsAppConsent, WhatsAppContact, WhatsAppFestival, WhatsAppFestivalOptin
from app.services.audit import audit
from app.services.whatsapp import WaError, addons, automations, pricing, rules, templates

log = logging.getLogger("flowqr.whatsapp.occasions")
IST = ZoneInfo("Asia/Kolkata")
CATEGORY_WARNING = ("WhatsApp has not yet confirmed what kind of message this greeting is, so FlowQR treats it as marketing: only customers who agreed to occasion greetings AND to offers will get it, "
                    "and anyone who asked to stop offers will not.")
MARKETING_WARNING = ("WhatsApp treats this greeting as marketing, so only customers who agreed to occasion greetings AND to offers will get it, and anyone who asked to stop offers will not. "
                     "It is charged at the marketing price.")


def ist_today(now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(IST).date()


def _leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def birthday_filter(today: date):
    """Who has a birthday on `today`: the matching day and month, plus 29 February birthdays on 28 February when this year has no 29 February."""
    cond = (WhatsAppContact.birth_month == today.month) & (WhatsAppContact.birth_day == today.day)
    if today.month == 2 and today.day == 28 and not _leap(today.year):
        cond = cond | ((WhatsAppContact.birth_month == 2) & (WhatsAppContact.birth_day == 29))
    return cond


def send_at(today: date, hour: int, now: datetime) -> datetime:
    """The chosen hour today in India time, or right now if that hour has already passed (the gate still keeps it inside 9 am to 9 pm)."""
    when = datetime(today.year, today.month, today.day, hour, 0, tzinfo=IST).astimezone(now.tzinfo)
    return max(when, now)


def _on(db: Session, tenant_id: uuid.UUID, key: str) -> WhatsAppAutomation | None:
    a = automations.get(db, tenant_id, key)
    return a if a is not None and a.status == "on" else None


def _consented(tenant_id: uuid.UUID):
    return select(WhatsAppConsent.contact_id).where(WhatsAppConsent.tenant_id == tenant_id, WhatsAppConsent.purpose == "occasion", WhatsAppConsent.revoked_at.is_(None))


def schedule_tenant(db: Session, tenant: Tenant, now: datetime | None = None) -> dict:
    """Schedule today's birthday greetings and the greetings for today's festivals the business chose. Safe to run many times a day: each (person, year) and (person, festival) is scheduled once."""
    now = now or utcnow()
    today = ist_today(now)
    out = {"birthdays": 0, "festivals": 0}
    if not settings.whatsapp_enabled or not addons.occasions_allowed(db, tenant.id):
        return out
    if now.astimezone(IST).hour >= rules.OCCASION_END:  # the hours are closed for today: a greeting is never sent late
        return out
    a = _on(db, tenant.id, "birthday")
    if a is not None:
        when = send_at(today, int(a.config.get("send_hour", 10)), now)
        for c in db.scalars(select(WhatsAppContact).where(WhatsAppContact.tenant_id == tenant.id, birthday_filter(today), WhatsAppContact.id.in_(_consented(tenant.id)))):
            if automations._schedule(db, a, c, "greeting", f"birthday:{c.id}:{today.year}", when, {"first_name": templates.first_name(c.customer_name), "on": today.isoformat()}):  # noqa: SLF001
                out["birthdays"] += 1
    a = _on(db, tenant.id, "festival")
    if a is not None:
        when = send_at(today, int(a.config.get("send_hour", 10)), now)
        fests = db.scalars(select(WhatsAppFestival).join(WhatsAppFestivalOptin, WhatsAppFestivalOptin.festival_id == WhatsAppFestival.id).where(
            WhatsAppFestival.festival_date == today, WhatsAppFestival.active.is_(True), WhatsAppFestivalOptin.tenant_id == tenant.id, WhatsAppFestivalOptin.enabled.is_(True))).all()
        for f in fests:
            for c in db.scalars(select(WhatsAppContact).where(WhatsAppContact.tenant_id == tenant.id, WhatsAppContact.id.in_(_consented(tenant.id)))):
                if automations._schedule(db, a, c, "greeting", f"festival:{f.id}:{c.id}", when, {"first_name": templates.first_name(c.customer_name), "on": today.isoformat(), "festival": f.name}):  # noqa: SLF001
                    out["festivals"] += 1
    return out


def schedule_due(db: Session, now: datetime | None = None, tenant_id: uuid.UUID | None = None) -> dict:
    """The worker pass that schedules greetings: for every business with a greeting helper switched on. Holds (does nothing) unless sending is allowed."""
    now = now or utcnow()
    if not automations.sending_allowed():
        return {"held": True, "birthdays": 0, "festivals": 0}
    q = select(WhatsAppAutomation.tenant_id).where(WhatsAppAutomation.automation_key.in_(automations.OCCASION_KEYS), WhatsAppAutomation.status == "on").distinct()
    if tenant_id is not None:
        q = q.where(WhatsAppAutomation.tenant_id == tenant_id)
    total = {"birthdays": 0, "festivals": 0}
    for tid in db.scalars(q).all():
        t = db.get(Tenant, tid)
        if t is None:
            continue
        try:
            with db.begin_nested():
                r = schedule_tenant(db, t, now)
            total["birthdays"] += r["birthdays"]
            total["festivals"] += r["festivals"]
        except Exception:  # noqa: BLE001 - one business must not stop the others
            log.exception("greeting scheduling failed for %s", tid)
    return total


# ---- what the owner sees: the category and a warning before anything is switched on
def template_state(db: Session, tenant_id: uuid.UUID, key: str) -> dict:
    row = templates.standard_row(db, tenant_id, key)
    if row is None:
        return {"key": key, "submitted": False, "status": None, "category": None, "category_known": False, "needs_offers_consent": True, "warning": CATEGORY_WARNING, "body": templates.STANDARD[key]["body"]}
    known = bool(row.category_confirmed)
    needs_offers = row.category == "marketing" or not known
    warning = None if not needs_offers else (MARKETING_WARNING if known else CATEGORY_WARNING)
    return {"key": key, "submitted": True, "status": row.approval_status, "category": row.category if known else None, "category_known": known, "needs_offers_consent": needs_offers, "warning": warning, "body": row.body_text}


def audience(db: Session, tenant_id: uuid.UUID, needs_offers: bool) -> dict:
    """How many customers would actually receive a greeting right now (occasion consent, not opted out, and offers consent where the category needs it)."""
    base = select(func.count()).select_from(WhatsAppContact).where(WhatsAppContact.tenant_id == tenant_id, WhatsAppContact.marketing_opted_out_at.is_(None), WhatsAppContact.id.in_(_consented(tenant_id)))
    agreed = db.scalar(select(func.count()).select_from(WhatsAppContact).where(WhatsAppContact.tenant_id == tenant_id, WhatsAppContact.id.in_(_consented(tenant_id)))) or 0
    if needs_offers:
        base = base.where(WhatsAppContact.id.in_(select(WhatsAppConsent.contact_id).where(WhatsAppConsent.tenant_id == tenant_id, WhatsAppConsent.purpose == "marketing", WhatsAppConsent.revoked_at.is_(None))))
    would = db.scalar(base) or 0
    with_birthday = db.scalar(select(func.count()).select_from(WhatsAppContact).where(WhatsAppContact.tenant_id == tenant_id, WhatsAppContact.birth_day.is_not(None), WhatsAppContact.id.in_(_consented(tenant_id)))) or 0
    return {"agreed": agreed, "would_receive": would, "with_birthday": with_birthday, "left_out": agreed - would}


def cost(db: Session, state: dict, aud: dict) -> dict:
    """The likely WhatsApp charge for a greeting, always an estimate and always apart from FlowQR's fee. Marketing price unless WhatsApp has confirmed the greeting is a utility message. Carries the price
    date and the unverified warning, so the owner sees both when switching the helper on."""
    cat = "utility" if state["category_known"] and state["category"] == "utility" else "marketing"
    return {"category_used": cat, "per_greeting": pricing.estimate(db, cat, 1), "for_everyone_who_would_get_it": pricing.estimate(db, cat, aud["would_receive"])}


def overview(db: Session, tenant: Tenant, now: datetime | None = None) -> dict:
    today = ist_today(now)
    b, f = template_state(db, tenant.id, "occasion_birthday"), template_state(db, tenant.id, "occasion_festival")
    ba, fa = audience(db, tenant.id, b["needs_offers_consent"]), audience(db, tenant.id, f["needs_offers_consent"])
    chosen = {o.festival_id: o.enabled for o in db.scalars(select(WhatsAppFestivalOptin).where(WhatsAppFestivalOptin.tenant_id == tenant.id))}
    fests = db.scalars(select(WhatsAppFestival).where(WhatsAppFestival.active.is_(True), WhatsAppFestival.festival_date >= today).order_by(WhatsAppFestival.festival_date)).all()
    return {"allowed": addons.occasions_allowed(db, tenant.id), "hours": {"start": rules.OCCASION_START, "end": rules.OCCASION_END, "timezone": "Asia/Kolkata"}, "gap_days": settings.whatsapp_occasion_gap_days,
            "birthday": {**b, "audience": ba, "estimate": cost(db, b, ba), "helper": automations.serialize(db, tenant.id, "birthday")},
            "festival": {**f, "audience": fa, "estimate": cost(db, f, fa), "helper": automations.serialize(db, tenant.id, "festival")},
            "festivals": [{"id": x.id, "name": x.name, "date": x.festival_date.isoformat(), "region": x.region, "enabled": bool(chosen.get(x.id, False))} for x in fests],
            "wording": rules.wording_for("occasion", tenant.name), "note": "Greetings are never offers. They are sent only between 9 am and 9 pm India time, at most once every "
            f"{settings.whatsapp_occasion_gap_days} days to the same person, and never to anyone who replied STOP."}


def set_festival(db: Session, tenant: Tenant, user: User, festival_id: uuid.UUID, enabled: bool, ip: str | None = None) -> dict:
    f = db.get(WhatsAppFestival, festival_id)
    if f is None or not f.active:
        raise WaError(404, "festival_not_found", "That festival is not on the list.")
    row = db.scalar(select(WhatsAppFestivalOptin).where(WhatsAppFestivalOptin.tenant_id == tenant.id, WhatsAppFestivalOptin.festival_id == f.id))
    if row is None:
        row = WhatsAppFestivalOptin(tenant_id=tenant.id, festival_id=f.id, enabled=enabled)
        db.add(row)
    else:
        row.enabled = enabled
    db.flush()
    audit(db, action="whatsapp.festival_optin", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_festival", entity_id=f.id, meta={"festival": f.name, "enabled": enabled}, ip=ip)
    return {"id": f.id, "enabled": enabled}


# ---- the festival list kept by FlowQR staff
def serialize_festival(f: WhatsAppFestival) -> dict:
    return {"id": f.id, "name": f.name, "date": f.festival_date.isoformat(), "region": f.region, "active": f.active}


def add_festival(db: Session, admin: User, *, name: str, festival_date: date, region: str, ip: str | None = None) -> WhatsAppFestival:
    name = " ".join((name or "").split())
    problem = rules.greeting_name_problem(name)
    if problem:
        raise WaError(422, "invalid_name", problem)
    region = " ".join((region or "All India").split()) or "All India"
    if not re.fullmatch(r"[A-Za-z][A-Za-z ]{1,39}", region):
        raise WaError(422, "invalid_region", "Use letters only for the region, like All India or Gujarat.")
    if db.scalar(select(WhatsAppFestival.id).where(WhatsAppFestival.name == name, WhatsAppFestival.festival_date == festival_date, WhatsAppFestival.region == region)):
        raise WaError(409, "festival_exists", "That festival is already on the list for that date and region.")
    f = WhatsAppFestival(name=name, festival_date=festival_date, region=region, active=True, created_by=admin.id)
    db.add(f)
    db.flush()
    audit(db, action="admin.whatsapp_festival_add", entity_type="whatsapp_festival", entity_id=f.id, user_id=admin.id, meta={"name": name, "date": festival_date.isoformat(), "region": region}, ip=ip)
    return f


def set_festival_active(db: Session, admin: User, festival_id: uuid.UUID, active: bool, ip: str | None = None) -> WhatsAppFestival:
    f = db.get(WhatsAppFestival, festival_id)
    if f is None:
        raise WaError(404, "festival_not_found", "That festival is not on the list.")
    f.active = active
    db.flush()
    audit(db, action="admin.whatsapp_festival_active", entity_type="whatsapp_festival", entity_id=f.id, user_id=admin.id, meta={"active": active}, ip=ip)
    return f


def list_festivals(db: Session) -> list[dict]:
    return [serialize_festival(f) for f in db.scalars(select(WhatsAppFestival).order_by(WhatsAppFestival.festival_date.desc(), WhatsAppFestival.name))]

