"""Promotional campaigns ("Offers"): a message sent to customers who agreed to receive offers.

The owner's journey: create (name, an approved marketing message, who, what it says, when) -> PREVIEW (how many people, the message as they will read it, an estimated WhatsApp charge, when it
will start) -> APPROVE (an explicit final step) -> the worker sends in small batches during sending hours -> results. Nothing is sent before approval, and approval is bound to what the owner saw:

* approval must repeat the recipient count the owner was shown; if the audience changed in between (someone opted out, someone agreed), approval is refused and the new count is shown;
* the approved count is a ceiling: customers added after approval are never included;
* consent is checked again for every person at the moment of sending (an opt-out after approval removes them), and the sender's own gate applies as for every message;
* offers go out only during sending hours (default 9:00 to 21:00 India time); outside them a campaign waits;
* a campaign can be rescheduled before it starts, paused, resumed or cancelled at any time; the emergency stop holds all sending;
* the same customer is never in a campaign twice, and never receives two marketing messages within WHATSAPP_MARKETING_GAP_HOURS.

Who can be chosen depends on the add-on: Growth has the basics (everyone, a group, new or earlier customers); Pro adds location, several groups, groups to leave out, "not sent an offer lately" and "never sent
an offer". Which message can be used: an approved MARKETING template whose body is plain text, with each blank filled from the customer's first name, the business name or fixed text.

Results never claim sales or revenue: WhatsApp reports sent, delivered and (only when the customer's read receipts are on) read.
"""
import csv
import io
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased

from app.core.config import settings
from app.models import Tenant, User
from app.models.base import utcnow
from app.models.whatsapp import WhatsAppCampaign, WhatsAppCampaignRecipient, WhatsAppConsent, WhatsAppContact, WhatsAppLinkClick, WhatsAppMessage, WhatsAppTemplate
from app.services.audit import audit
from app.services.whatsapp import WaError, addons, automations, connection, consent, pricing, sender, templates, usage

log = logging.getLogger("flowqr.whatsapp.campaigns")
IST = ZoneInfo("Asia/Kolkata")
KINDS = ("all", "tag", "new", "existing")
SOURCES = ("customer_name", "business_name", "text")
ADVANCED_KEYS = ("tags_any", "tags_all", "exclude_tags", "location_id", "not_messaged_days", "never_messaged", "engaged", "engaged_days", "no_engagement_last_offers", "winback_days")
ENGAGED = ("read", "replied", "clicked", "delivered_not_read")
MAX_TEXT = 200
MAX_OFFER = 120
MAX_AHEAD_DAYS = 90
RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}


def _money(v) -> str | None:
    """Money as the owner saw it: two decimals, or nothing when no rate was known."""
    return None if v is None else str(Decimal(v).quantize(Decimal("0.01")))


# ---- sending hours (India time)
def send_window() -> tuple[int, int]:
    return settings.whatsapp_send_window_start, settings.whatsapp_send_window_end


def in_window(now: datetime | None = None) -> bool:
    start, end = send_window()
    if start <= 0 and end >= 24:
        return True
    t = (now or utcnow()).astimezone(IST)
    return start <= t.hour + t.minute / 60 < end


def next_open(now: datetime | None = None) -> datetime:
    """The first moment at or after `now` when offers may be sent."""
    now = now or utcnow()
    if in_window(now):
        return now
    start, _ = send_window()
    t = now.astimezone(IST)
    opens = t.replace(hour=start, minute=0, second=0, microsecond=0)
    if opens <= t:
        opens += timedelta(days=1)
    return opens.astimezone(timezone.utc)


def window_info(now: datetime | None = None) -> dict:
    start, end = send_window()
    return {"start": start, "end": end, "timezone": "Asia/Kolkata", "open_now": in_window(now), "always": start <= 0 and end >= 24}


# ---- plan
def segmentation_level(db: Session, tenant_id: uuid.UUID) -> str:
    if not settings.whatsapp_require_addon:
        return "advanced"
    t = addons.tier(addons.active_addon(db, tenant_id))
    return t["segmentation"] if t else "none"


def can_use_campaigns(db: Session, tenant_id: uuid.UUID) -> bool:
    if not settings.whatsapp_require_addon:
        return True
    t = addons.tier(addons.active_addon(db, tenant_id))
    return bool(t and t["campaigns"])


# ---- audience
def _names(raw, label: str) -> list[str]:
    if not isinstance(raw, list) or len(raw) > 10:
        raise WaError(422, "invalid_audience", f"Choose up to 10 {label}.")
    return [x for x in dict.fromkeys(templates.clean_variable(x)[:30] for x in raw) if x]


def _empty(v) -> bool:
    """Nothing chosen. (Zero is a choice, and an invalid one: it must be refused, not ignored.)"""
    return v is None or v is False or (isinstance(v, (str, list)) and len(v) == 0)


def clean_audience(raw: dict | None, level: str = "basic") -> dict:
    a = dict(raw or {})
    kind = a.get("kind", "all")
    if kind not in KINDS:
        raise WaError(422, "invalid_audience", "Choose who should get it.")
    out: dict = {"kind": kind}
    if kind == "tag":
        tag = templates.clean_variable(a.get("tag") or "")[:30]
        if not tag:
            raise WaError(422, "invalid_audience", "Choose a group.")
        out["tag"] = tag
    if kind in ("new", "existing"):
        days = a.get("days", 30)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
            raise WaError(422, "invalid_audience", "Choose between 1 and 365 days.")
        out["days"] = days
    extra = {k: a[k] for k in ADVANCED_KEYS if k in a and not _empty(a[k])}
    if extra:
        if level != "advanced":
            raise WaError(402, "plan_required", "Choosing by location, several groups, how recently someone got an offer, or by engagement and win-back is part of the Pro add-on.")
        for k, label in (("tags_any", "groups"), ("tags_all", "groups"), ("exclude_tags", "groups")):
            if k in extra:
                out[k] = _names(extra[k], label)
        if "location_id" in extra:
            try:
                out["location_id"] = str(uuid.UUID(str(extra["location_id"])))
            except ValueError:
                raise WaError(422, "invalid_audience", "Choose one of your locations.") from None
        if "not_messaged_days" in extra:
            d = extra["not_messaged_days"]
            if isinstance(d, bool) or not isinstance(d, int) or not 1 <= d <= 365:
                raise WaError(422, "invalid_audience", "Choose between 1 and 365 days.")
            out["not_messaged_days"] = d
        if extra.get("never_messaged") is True:
            out["never_messaged"] = True
        if "engaged" in extra:
            if extra["engaged"] not in ENGAGED:
                raise WaError(422, "invalid_audience", "Choose who read, replied, clicked, or had a message delivered but not read.")
            d = extra.get("engaged_days", 30)
            if isinstance(d, bool) or not isinstance(d, int) or not 1 <= d <= 365:
                raise WaError(422, "invalid_audience", "Choose between 1 and 365 days.")
            out["engaged"], out["engaged_days"] = extra["engaged"], d
        if "no_engagement_last_offers" in extra:
            n = extra["no_engagement_last_offers"]
            if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 10:
                raise WaError(422, "invalid_audience", "Choose between 1 and 10 offers.")
            out["no_engagement_last_offers"] = n
        if "winback_days" in extra:
            w = extra["winback_days"]
            if isinstance(w, bool) or not isinstance(w, int) or not 1 <= w <= 365:
                raise WaError(422, "invalid_audience", "Choose between 1 and 365 days.")
            out["winback_days"] = w
    return out


def _filtered(tenant_id: uuid.UUID, audience: dict, now: datetime):
    """Everyone the audience's CHOICES pick out, before consent and opt-outs are applied (so the preview can say how many were left out and why)."""
    q = select(WhatsAppContact).where(WhatsAppContact.tenant_id == tenant_id)
    k = audience.get("kind", "all")
    if k == "tag":
        q = q.where(WhatsAppContact.tags.contains([audience["tag"]]))
    elif k == "new":
        q = q.where(WhatsAppContact.created_at >= now - timedelta(days=audience["days"]))
    elif k == "existing":
        q = q.where(WhatsAppContact.created_at < now - timedelta(days=audience["days"]))
    if audience.get("tags_any"):
        q = q.where(or_(*[WhatsAppContact.tags.contains([t]) for t in audience["tags_any"]]))
    for t in audience.get("tags_all", []):
        q = q.where(WhatsAppContact.tags.contains([t]))
    for t in audience.get("exclude_tags", []):
        q = q.where(~WhatsAppContact.tags.contains([t]))
    if audience.get("location_id"):
        q = q.where(WhatsAppContact.location_id == uuid.UUID(audience["location_id"]))
    got = select(WhatsAppMessage.contact_id).where(WhatsAppMessage.tenant_id == tenant_id, WhatsAppMessage.category == "marketing", WhatsAppMessage.delivery_status != "failed", WhatsAppMessage.contact_id.is_not(None))
    if audience.get("not_messaged_days"):
        q = q.where(~WhatsAppContact.id.in_(got.where(WhatsAppMessage.created_at >= now - timedelta(days=audience["not_messaged_days"]))))
    if audience.get("never_messaged"):
        q = q.where(~WhatsAppContact.id.in_(got))
    return _engagement(q, tenant_id, audience, now)


def _engagement(q, tenant_id: uuid.UUID, audience: dict, now: datetime):
    """Engagement and win-back choices (Pro). Timestamps only: a message's read and delivered times, the time a customer last wrote, link clicks, visits. Nothing about what anyone said."""
    M, C = WhatsAppMessage, WhatsAppContact
    out = (M.tenant_id == tenant_id, M.direction == "outbound", M.contact_id.is_not(None))
    kind = audience.get("engaged")
    if kind:
        cut = now - timedelta(days=audience["engaged_days"])
        read = select(M.contact_id).where(*out, M.read_at >= cut)
        if kind == "read":
            q = q.where(C.id.in_(read))  # only customers who have read receipts on can ever be counted here
        elif kind == "replied":
            q = q.where(C.last_replied_at >= cut)
        elif kind == "clicked":
            q = q.where(C.id.in_(select(WhatsAppLinkClick.contact_id).where(WhatsAppLinkClick.tenant_id == tenant_id, WhatsAppLinkClick.contact_id.is_not(None), WhatsAppLinkClick.clicked_at >= cut)))
        elif kind == "delivered_not_read":  # delivered, and not read: this includes people who simply have read receipts turned off
            q = q.where(C.id.in_(select(M.contact_id).where(*out, M.delivered_at >= cut)), ~C.id.in_(read))
    n = audience.get("no_engagement_last_offers")
    if n:
        # an "offer" here is a campaign message that reached the phone. For each customer take the last N of them; the customer qualifies if they had N, read none, and did not reply or click since the oldest of the N.
        ranked = select(M.contact_id.label("cid"), M.read_at.label("read_at"), M.created_at.label("at"),
                        func.row_number().over(partition_by=M.contact_id, order_by=M.created_at.desc()).label("rn")).where(
            *out, M.category == "marketing", M.campaign_id.is_not(None), M.delivery_status.in_(("delivered", "read"))).subquery()
        last_n = select(ranked.c.cid.label("cid"), func.min(ranked.c.at).label("oldest")).where(ranked.c.rn <= n).group_by(ranked.c.cid).having(func.count() == n, func.count(ranked.c.read_at) == 0).subquery()
        c2 = aliased(WhatsAppContact)
        clicked = exists().where(WhatsAppLinkClick.contact_id == last_n.c.cid, WhatsAppLinkClick.clicked_at >= last_n.c.oldest)
        q = q.where(C.id.in_(select(last_n.c.cid).join(c2, c2.id == last_n.c.cid).where(or_(c2.last_replied_at.is_(None), c2.last_replied_at < last_n.c.oldest), ~clicked)))
    w = audience.get("winback_days")
    if w:
        cut = now - timedelta(days=w)
        c3 = aliased(WhatsAppContact)
        visits_marked = exists().where(c3.tenant_id == tenant_id, c3.last_visit_at.is_not(None))  # if no visit was ever marked, "not visited" cannot be judged: fall back to "not messaged"
        q = q.where(C.created_at < cut,  # a customer added inside the window has had no chance to be away
                    ~C.id.in_(select(M.contact_id).where(*out, M.delivery_status != "failed", M.created_at >= cut)),  # any message counts: offers, updates, greetings
                    or_(~visits_marked, C.last_visit_at.is_(None), C.last_visit_at < cut),
                    or_(C.last_enquiry_at.is_(None), C.last_enquiry_at < cut))
    return q


def audience_query(tenant_id: uuid.UUID, audience: dict, now: datetime | None = None):
    now = now or utcnow()
    return _filtered(tenant_id, audience, now).where(WhatsAppContact.marketing_opted_out_at.is_(None),
                                                      WhatsAppContact.id.in_(select(WhatsAppConsent.contact_id).where(WhatsAppConsent.tenant_id == tenant_id, WhatsAppConsent.purpose == "marketing", WhatsAppConsent.revoked_at.is_(None))))


def exclusions(db: Session, tenant_id: uuid.UUID, audience: dict, now: datetime | None = None) -> dict:
    """Of the customers the choices pick out, how many are left out because they asked to stop offers, or never agreed to receive them."""
    now = now or utcnow()
    f = _filtered(tenant_id, audience, now).subquery()
    matching = db.scalar(select(func.count()).select_from(f)) or 0
    opted = db.scalar(select(func.count()).select_from(f).where(f.c.marketing_opted_out_at.is_not(None))) or 0
    agreed = select(WhatsAppConsent.contact_id).where(WhatsAppConsent.tenant_id == tenant_id, WhatsAppConsent.purpose == "marketing", WhatsAppConsent.revoked_at.is_(None))
    no_consent = db.scalar(select(func.count()).select_from(f).where(f.c.marketing_opted_out_at.is_(None), ~f.c.id.in_(agreed))) or 0
    return {"matching": matching, "opted_out": opted, "no_consent": no_consent}


def audience_notes(db: Session, tenant_id: uuid.UUID, audience: dict) -> list[dict]:
    """The limits of the choices made, in plain words, shown beside the count."""
    notes: list[dict] = []
    kind = audience.get("engaged")
    if kind == "read":
        notes.append({"key": "read", "text": "Read only counts customers who have read receipts turned on."})
    if kind == "delivered_not_read":
        notes.append({"key": "delivered_not_read", "text": "Delivered but not read may include people with read receipts turned off. It does not show whether they saw the message."})
    if kind == "clicked" or audience.get("no_engagement_last_offers"):
        notes.append({"key": "clicked", "text": "Link clicks only have data from the time link click counting was switched on (Pro). Before that, nobody can show up as having clicked."})
    if audience.get("no_engagement_last_offers"):
        notes.append({"key": "offers", "text": f"Only customers who were sent at least {audience['no_engagement_last_offers']} offers that reached their phone are counted, and read receipts must be on to see a read."})
    if audience.get("winback_days"):
        marked = db.scalar(select(WhatsAppContact.id).where(WhatsAppContact.tenant_id == tenant_id, WhatsAppContact.last_visit_at.is_not(None)).limit(1)) is not None
        d = audience["winback_days"]
        if marked:
            notes.append({"key": "winback_visits", "basis": "visits", "text": f"Customers you have not marked as visited, not had an enquiry from, and not messaged in the last {d} days. Any message counts, including greetings. Only visits you marked can be known."})
        else:
            notes.append({"key": "winback_messages_only", "basis": "messages_only", "text": f"You have not marked any visits yet, so this uses messages only: customers you have not messaged in the last {d} days (any message counts, including greetings). Mark visits on the Customers page to use them too."})
    return notes


def audience_count(db: Session, tenant_id: uuid.UUID, audience: dict) -> int:
    return db.scalar(select(func.count()).select_from(audience_query(tenant_id, audience).subquery())) or 0


# ---- the message
def campaign_template(db: Session, tenant_id: uuid.UUID, template_id: uuid.UUID) -> WhatsAppTemplate:
    t = db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id, WhatsAppTemplate.tenant_id == tenant_id))
    if t is None:
        raise WaError(404, "template_not_found", "Choose one of your approved offer messages.")
    if t.category != "marketing":
        raise WaError(422, "template_not_marketing", "Offers can only use a message WhatsApp treats as an offer.")
    if not t.simple:
        raise WaError(422, "template_not_simple", "That message has a picture, header or button, which offers cannot fill in yet. Choose a text-only message.")
    return t


def _blanks(t: WhatsAppTemplate) -> int:
    return max(templates.placeholders(t.body_text), len(t.variable_schema or []))


def clean_variables(t: WhatsAppTemplate, raw) -> dict:
    v = raw if isinstance(raw, dict) else {}
    if templates.key_of(t.template_name) == "offer":
        text = templates.clean_variable(v.get("offer_text") or "").rstrip(" .")  # the message adds its own full stop
        if not 5 <= len(text) <= MAX_OFFER:
            raise WaError(422, "invalid_offer", f"Describe your offer in 5 to {MAX_OFFER} characters.")
        return {"offer_text": text}
    mapping = v.get("mapping")
    n = _blanks(t)
    if not isinstance(mapping, list) or len(mapping) != n:
        raise WaError(422, "invalid_variables", f"This message has {n} blank{'s' if n != 1 else ''} to fill in.")
    out = []
    for m in mapping:
        src = m.get("source") if isinstance(m, dict) else None
        if src not in SOURCES:
            raise WaError(422, "invalid_variables", "Each blank is the customer's first name, your business name, or text you write.")
        if src == "text":
            if len(str(m.get("value") or "")) > MAX_TEXT:
                raise WaError(422, "invalid_variables", f"Text for a blank must be 1 to {MAX_TEXT} characters.")
            val = templates.clean_variable(m.get("value") or "")
            if not 1 <= len(val) <= MAX_TEXT:
                raise WaError(422, "invalid_variables", f"Text for a blank must be 1 to {MAX_TEXT} characters.")
            out.append({"source": "text", "value": val})
        else:
            out.append({"source": src})
    return {"mapping": out}


def params_for(c: WhatsAppCampaign, t: WhatsAppTemplate, contact_name: str | None, tenant: Tenant) -> list[str]:
    first = templates.first_name(contact_name)
    if templates.key_of(t.template_name) == "offer":
        return [first, tenant.name, (c.variables or {}).get("offer_text", "")]
    return [first if m["source"] == "customer_name" else tenant.name if m["source"] == "business_name" else m.get("value", "") for m in (c.variables or {}).get("mapping", [])]


# ---- lifecycle
def get(db: Session, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> WhatsAppCampaign:
    c = db.scalar(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant_id))
    if c is None:
        raise WaError(404, "not_found", "That campaign was not found.")
    return c


def check_schedule(when: datetime | None, now: datetime | None = None) -> datetime | None:
    """A start time must be in the future (within a minute's grace) and within 90 days. A time without a zone is read as India time."""
    if when is None:
        return None
    now = now or utcnow()
    if when.tzinfo is None:
        when = when.replace(tzinfo=IST)
    when = when.astimezone(timezone.utc)
    if when < now - timedelta(minutes=1):
        raise WaError(422, "invalid_schedule", "Choose a start time in the future.")
    if when > now + timedelta(days=MAX_AHEAD_DAYS):
        raise WaError(422, "invalid_schedule", f"Choose a start time within the next {MAX_AHEAD_DAYS} days.")
    return when


def create(db: Session, tenant: Tenant, user: User, *, name: str, template_id: uuid.UUID, audience: dict | None, variables: dict | None, scheduled_at: datetime | None, ip: str | None = None) -> WhatsAppCampaign:
    if not can_use_campaigns(db, tenant.id):
        raise WaError(402, "plan_required", "Campaigns are part of the Growth and Pro add-ons. Ask FlowQR to upgrade your WhatsApp add-on.")
    name = " ".join((name or "").split())
    if not 2 <= len(name) <= 120:
        raise WaError(422, "invalid_name", "Give the campaign a name (2 to 120 characters).")
    t = campaign_template(db, tenant.id, template_id)
    c = WhatsAppCampaign(tenant_id=tenant.id, name=name, template_id=t.id, audience=clean_audience(audience, segmentation_level(db, tenant.id)), variables=clean_variables(t, variables), status="draft",
                         scheduled_at=check_schedule(scheduled_at), created_by=user.id)
    db.add(c)
    db.flush()
    audit(db, action="whatsapp.campaign_create", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_campaign", entity_id=c.id, ip=ip)
    return c


def update(db: Session, tenant: Tenant, c: WhatsAppCampaign, *, name=None, audience=None, variables=None, scheduled_at=None, set_schedule: bool = False) -> WhatsAppCampaign:
    if c.status != "draft":
        raise WaError(409, "not_editable", "Only a draft can be changed. Pause or cancel it first.")
    if name is not None:
        nm = " ".join(name.split())
        if not 2 <= len(nm) <= 120:
            raise WaError(422, "invalid_name", "Give the campaign a name (2 to 120 characters).")
        c.name = nm
    if audience is not None:
        c.audience = clean_audience(audience, segmentation_level(db, tenant.id))
    if variables is not None:
        c.variables = clean_variables(campaign_template(db, tenant.id, c.template_id), variables)
    if set_schedule:
        c.scheduled_at = check_schedule(scheduled_at)
    return c


def reschedule(db: Session, tenant: Tenant, user: User, c: WhatsAppCampaign, when: datetime, ip: str | None = None) -> WhatsAppCampaign:
    """Change the start time of a campaign that has not started. (A draft can also simply be edited.)"""
    if c.status not in ("draft", "scheduled") or c.started_at is not None:
        raise WaError(409, "not_reschedulable", "Only a campaign that has not started can be moved. Pause it first if it is already sending.")
    old = c.scheduled_at
    c.scheduled_at = check_schedule(when)
    audit(db, action="whatsapp.campaign_reschedule", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_campaign", entity_id=c.id,
          meta={"from": old.isoformat() if old else None, "to": c.scheduled_at.isoformat()}, ip=ip)
    return c


def duplicate(db: Session, tenant: Tenant, user: User, c: WhatsAppCampaign, ip: str | None = None) -> WhatsAppCampaign:
    """A new DRAFT with the same message, audience and wording (never copies approval, schedule or results)."""
    if not can_use_campaigns(db, tenant.id):
        raise WaError(402, "plan_required", "Campaigns are part of the Growth and Pro add-ons.")
    d = WhatsAppCampaign(tenant_id=tenant.id, name=(c.name + " (copy)")[:120], template_id=c.template_id, audience=dict(c.audience or {}), variables=dict(c.variables or {}), status="draft", created_by=user.id)
    db.add(d)
    db.flush()
    audit(db, action="whatsapp.campaign_duplicate", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_campaign", entity_id=d.id, meta={"from": str(c.id)}, ip=ip)
    return d


def _sample_name(db: Session, tenant_id: uuid.UUID, audience: dict) -> str | None:
    first = db.scalar(audience_query(tenant_id, audience).order_by(WhatsAppContact.created_at).limit(1))
    return first.customer_name if first else "Asha"


def approved_estimate(c: WhatsAppCampaign) -> dict:
    """The estimate the owner approved, exactly as it was, labelled with the price date it used. New prices never change it. An offer approved before price dates were kept says so and is shown as unverified."""
    p = c.approved_price or {}
    ok = bool(p.get("verified"))
    when = p.get("effective_from")
    label = f"This estimate was fixed when you approved the offer, using the price dated {when}. Newer prices apply only to new estimates." if when else \
        "This estimate was fixed when you approved the offer. The date of the price it used was not recorded. Newer prices apply only to new estimates."
    return {"category": "marketing", "count": c.approved_recipients or 0, "rate": p.get("rate"), "currency": "INR", "amount": str(_money(c.approved_cost)) if c.approved_cost is not None else None, "verified": ok,
            "rate_source": p.get("source"), "effective_from": when, "free_included": 0, "billable": c.approved_recipients or 0, "fixed_at_approval": True,
            "warning": None if ok else pricing.WARNING, "note": pricing.NOTE + " " + label}


def preview(db: Session, tenant: Tenant, c: WhatsAppCampaign, now: datetime | None = None) -> dict:
    now = now or utcnow()
    t = db.get(WhatsAppTemplate, c.template_id) if c.template_id else None
    n = audience_count(db, tenant.id, c.audience)
    left_out = exclusions(db, tenant.id, c.audience, now)
    est = pricing.estimate(db, "marketing", n) if c.status == "draft" or c.approved_at is None else approved_estimate(c)  # once approved the owner's estimate never moves
    conn = connection.connected_connection(db, tenant.id)
    ready = {"plan": can_use_campaigns(db, tenant.id), "connection": bool(conn and conn.status == "connected"), "template_approved": bool(t and t.approval_status == "approved"), "has_recipients": n > 0,
             "sending_on": automations.sending_allowed()}
    text = templates.render(t, params_for(c, t, _sample_name(db, tenant.id, c.audience), tenant)) if t and t.body_text and (c.variables or {}) else None
    want = max(c.scheduled_at or now, now)
    starts = next_open(want)
    return {"id": c.id, "name": c.name, "status": c.status, "audience": c.audience, "recipients": n, "estimate": est, "message_preview": text, "ready": ready, "approved_recipients": c.approved_recipients,
            "approved_cost": _money(c.approved_cost), "scheduled_at": c.scheduled_at, "variables": c.variables, "template_id": c.template_id, "segmentation": segmentation_level(db, tenant.id),
            "window": window_info(now), "starts_at": starts, "waits_for_hours": starts > want, "estimated_minutes": math.ceil(n / max(1, settings.whatsapp_campaign_batch)) if n else 0,
            "excluded_note": "Only customers who agreed to receive offers and have not asked to stop are counted.",
            "matching": left_out["matching"], "excluded": {"no_consent": left_out["no_consent"], "opted_out": left_out["opted_out"]}, "audience_notes": audience_notes(db, tenant.id, c.audience)}


def approve(db: Session, tenant: Tenant, user: User, c: WhatsAppCampaign, *, confirm_recipients: int, accept_estimate: bool, ip: str | None = None, now: datetime | None = None) -> WhatsAppCampaign:
    """The explicit final approval. Nothing is ever sent without it."""
    now = now or utcnow()
    if c.status not in ("draft", "paused"):
        raise WaError(409, "not_approvable", "This campaign cannot be approved in its current state.")
    if not can_use_campaigns(db, tenant.id):
        raise WaError(402, "plan_required", "Campaigns are part of the Growth and Pro add-ons.")
    p = preview(db, tenant, c, now)
    if not p["ready"]["connection"]:
        raise WaError(409, "not_connected", "Connect your WhatsApp number first.")
    if not p["ready"]["template_approved"]:
        raise WaError(409, "template_not_approved", "WhatsApp has not approved this message yet.")
    if p["recipients"] == 0:
        raise WaError(409, "no_recipients", "No customers who agreed to receive offers match this audience.")
    if not accept_estimate:
        raise WaError(422, "estimate_not_accepted", "Please confirm you have seen the estimated WhatsApp charge.")
    if confirm_recipients != p["recipients"]:
        raise WaError(409, "recipients_changed", f"The number of customers changed from {confirm_recipients} to {p['recipients']}. Please review and approve again.")
    c.approved_by, c.approved_at, c.approved_recipients = user.id, now, p["recipients"]
    c.approved_cost = Decimal(p["estimate"]["amount"]) if p["estimate"]["amount"] is not None else None
    c.approved_price = {"rate": p["estimate"]["rate"], "effective_from": p["estimate"]["effective_from"], "verified": p["estimate"]["verified"], "source": p["estimate"]["rate_source"]}
    c.status = "scheduled"
    if c.scheduled_at is None or c.scheduled_at < now:
        c.scheduled_at = now
    _fix_list(db, c, now)
    audit(db, action="whatsapp.campaign_approve", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_campaign", entity_id=c.id,
          meta={"recipients": p["recipients"], "estimate": p["estimate"]["amount"], "verified_rate": p["estimate"]["verified"], "starts_at": p["starts_at"].isoformat()}, ip=ip)
    return c


def pause(db: Session, tenant: Tenant, user: User, c: WhatsAppCampaign, ip: str | None = None) -> WhatsAppCampaign:
    if c.status not in ("scheduled", "sending"):
        raise WaError(409, "not_pausable", "Only a scheduled or sending campaign can be paused.")
    c.status = "paused"
    audit(db, action="whatsapp.campaign_pause", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_campaign", entity_id=c.id, ip=ip)
    return c


def resume(db: Session, tenant: Tenant, user: User, c: WhatsAppCampaign, ip: str | None = None) -> WhatsAppCampaign:
    if c.status != "paused" or c.approved_at is None:
        raise WaError(409, "not_resumable", "Only a paused, approved campaign can be resumed.")
    c.status = "sending" if c.started_at else "scheduled"
    audit(db, action="whatsapp.campaign_resume", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_campaign", entity_id=c.id, ip=ip)
    return c


def cancel(db: Session, tenant: Tenant, user: User, c: WhatsAppCampaign, ip: str | None = None, now: datetime | None = None) -> WhatsAppCampaign:
    if c.status in ("done", "cancelled"):
        raise WaError(409, "not_cancellable", "This campaign has already finished.")
    c.status, c.finished_at = "cancelled", (now or utcnow())
    for r in db.scalars(select(WhatsAppCampaignRecipient).where(WhatsAppCampaignRecipient.campaign_id == c.id, WhatsAppCampaignRecipient.status == "pending")):
        r.status, r.reason = "skipped", "campaign_cancelled"
    audit(db, action="whatsapp.campaign_cancel", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_campaign", entity_id=c.id, ip=ip)
    return c


# ---- results
def _timeline(db: Session, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> list[dict]:
    day = func.date(func.timezone("Asia/Kolkata", WhatsAppMessage.created_at))
    by: dict = {}
    for d, status, n in db.execute(select(day, WhatsAppMessage.delivery_status, func.count()).where(WhatsAppMessage.tenant_id == tenant_id, WhatsAppMessage.campaign_id == campaign_id).group_by(day, WhatsAppMessage.delivery_status)):
        row = by.setdefault(d.isoformat(), {"date": d.isoformat(), "sent": 0, "delivered": 0, "read": 0, "failed": 0})
        if status == "failed":
            row["failed"] += n
        else:
            r = RANK.get(status, 0)
            row["sent"] += n if r >= 1 else 0
            row["delivered"] += n if r >= 2 else 0
            row["read"] += n if r >= 3 else 0
    return [by[k] for k in sorted(by)]


def results(db: Session, tenant_id: uuid.UUID, c: WhatsAppCampaign) -> dict:
    far = datetime(2100, 1, 1, tzinfo=c.created_at.tzinfo)
    m = usage.counts(db, tenant_id, datetime(2000, 1, 1, tzinfo=c.created_at.tzinfo), far, campaign_id=c.id).get("marketing", {"attempted": 0, "sent": 0, "delivered": 0, "read": 0, "failed": 0, "estimated_cost": Decimal(0)})
    rec = dict(db.execute(select(WhatsAppCampaignRecipient.status, func.count()).where(WhatsAppCampaignRecipient.campaign_id == c.id).group_by(WhatsAppCampaignRecipient.status)).all())
    opted = 0
    if c.started_at:
        opted = db.scalar(select(func.count()).select_from(WhatsAppCampaignRecipient).join(WhatsAppContact, WhatsAppContact.id == WhatsAppCampaignRecipient.contact_id).where(
            WhatsAppCampaignRecipient.campaign_id == c.id, WhatsAppContact.marketing_opted_out_at >= c.started_at)) or 0
    skipped_reasons = dict(db.execute(select(WhatsAppCampaignRecipient.reason, func.count()).where(WhatsAppCampaignRecipient.campaign_id == c.id, WhatsAppCampaignRecipient.status == "skipped").group_by(WhatsAppCampaignRecipient.reason)).all())
    return {"id": c.id, "name": c.name, "status": c.status, "approved_recipients": c.approved_recipients, "approved_estimate": _money(c.approved_cost), "approved_price_date": (c.approved_price or {}).get("effective_from"),
            "attempted": m["attempted"], "sent": m["sent"], "delivered": m["delivered"], "read": m["read"], "failed": m["failed"], "waiting": rec.get("pending", 0), "skipped": rec.get("skipped", 0),
            "skipped_reasons": skipped_reasons, "opted_out_after": opted, "estimated_meta_cost": str(m["estimated_cost"].quantize(Decimal("0.01"))), "started_at": c.started_at, "finished_at": c.finished_at,
            "delivery_rate": round(m["delivered"] * 100 / m["sent"]) if m["sent"] else None, "read_rate": round(m["read"] * 100 / m["delivered"]) if m["delivered"] else None,
            "timeline": _timeline(db, tenant_id, c.id),
            "note": "WhatsApp tells us when a message is sent, delivered and, if the customer allows it, read. FlowQR cannot tell you how many sales an offer led to. " + pricing.NOTE}


def compare(db: Session, tenant_id: uuid.UUID, limit: int = 20) -> list[dict]:
    """The owner's recent campaigns side by side. Only what WhatsApp reports; no ranking by sales."""
    rows = db.scalars(select(WhatsAppCampaign).where(WhatsAppCampaign.tenant_id == tenant_id, WhatsAppCampaign.started_at.is_not(None)).order_by(WhatsAppCampaign.started_at.desc()).limit(max(1, min(limit, 50))))
    keys = ("id", "name", "status", "approved_recipients", "sent", "delivered", "read", "failed", "delivery_rate", "read_rate", "opted_out_after", "estimated_meta_cost", "approved_estimate", "started_at")
    out = []
    for c in rows:
        r = results(db, tenant_id, c)
        out.append({k: r[k] for k in keys})
    return out


LABEL = {"queued": "waiting", "sent": "sent", "delivered": "delivered", "read": "read", "failed": "not delivered"}


def recipients_csv(db: Session, tenant_id: uuid.UUID, c: WhatsAppCampaign) -> str:
    """Who the campaign went to and what happened to each message: the owner's own customers and results, for their own records. Cells that could run as spreadsheet formulas are neutralised."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["name", "phone", "result", "reason", "delivered_at", "read_at"])
    q = select(WhatsAppCampaignRecipient, WhatsAppContact, WhatsAppMessage).join(WhatsAppContact, WhatsAppContact.id == WhatsAppCampaignRecipient.contact_id).join(
        WhatsAppMessage, WhatsAppMessage.id == WhatsAppCampaignRecipient.message_id, isouter=True).where(WhatsAppCampaignRecipient.campaign_id == c.id, WhatsAppCampaignRecipient.tenant_id == tenant_id).order_by(WhatsAppContact.created_at)
    for r, ct, m in db.execute(q):
        result = LABEL.get(m.delivery_status, m.delivery_status) if m is not None else ("waiting" if r.status == "pending" else "not sent")
        reason = r.reason or (m.error_code if m is not None and m.delivery_status == "failed" else "") or ""
        w.writerow([consent._cell(ct.customer_name), ct.phone, result, reason, m.delivered_at.isoformat() if m is not None and m.delivered_at else "", m.read_at.isoformat() if m is not None and m.read_at else ""])  # noqa: SLF001
    return out.getvalue()


def serialize(c: WhatsAppCampaign) -> dict:
    return {"id": c.id, "name": c.name, "status": c.status, "audience": c.audience, "variables": c.variables, "template_id": c.template_id, "scheduled_at": c.scheduled_at, "approved_at": c.approved_at,
            "approved_recipients": c.approved_recipients, "approved_cost": _money(c.approved_cost), "started_at": c.started_at, "finished_at": c.finished_at, "created_at": c.created_at}


# ---- the worker
def _fix_list(db: Session, c: WhatsAppCampaign, now: datetime) -> int:
    """Fix the recipient list at the moment of approval: exactly the customers the owner was shown, at most the approved number. From here on the single send gate decides about each one at the moment of
    sending, so anyone who opts out or loses consent after approval is skipped, with the reason, and counted as skipped in the results."""
    if db.scalar(select(WhatsAppCampaignRecipient.id).where(WhatsAppCampaignRecipient.campaign_id == c.id).limit(1)) is not None:
        return 0
    ids = list(db.scalars(audience_query(c.tenant_id, c.audience, now).with_only_columns(WhatsAppContact.id).order_by(WhatsAppContact.created_at).limit(c.approved_recipients or 0)))
    if ids:
        db.execute(pg_insert(WhatsAppCampaignRecipient).values([{"id": uuid.uuid4(), "tenant_id": c.tenant_id, "campaign_id": c.id, "contact_id": i, "status": "pending"} for i in ids]).on_conflict_do_nothing(constraint="uq_wa_campaign_recipient"))
    return len(ids)


def _materialize(db: Session, c: WhatsAppCampaign) -> int:
    """A campaign approved before lists were fixed at approval has none yet: fix it when sending starts (whoever is eligible now, at most the approved number). Otherwise the approved list stands."""
    if db.scalar(select(WhatsAppCampaignRecipient.id).where(WhatsAppCampaignRecipient.campaign_id == c.id).limit(1)) is not None:
        return 0
    ids = list(db.scalars(audience_query(c.tenant_id, c.audience).with_only_columns(WhatsAppContact.id).order_by(WhatsAppContact.created_at).limit(c.approved_recipients or 0)))
    if ids:
        db.execute(pg_insert(WhatsAppCampaignRecipient).values([{"id": uuid.uuid4(), "tenant_id": c.tenant_id, "campaign_id": c.id, "contact_id": i, "status": "pending"} for i in ids]).on_conflict_do_nothing(constraint="uq_wa_campaign_recipient"))
    return len(ids)


def run_due(db: Session, now: datetime | None = None, tenant_id: uuid.UUID | None = None) -> dict:
    now = now or utcnow()
    if not automations.sending_allowed():
        return {"held": True}
    if not in_window(now):
        return {"held": True, "reason": "outside_hours"}  # offers wait for sending hours; nothing is lost
    out = {"started": 0, "sent": 0, "skipped": 0, "failed": 0, "finished": 0}
    scope = [WhatsAppCampaign.tenant_id == tenant_id] if tenant_id is not None else []
    for c in db.scalars(select(WhatsAppCampaign).where(WhatsAppCampaign.status == "scheduled", WhatsAppCampaign.scheduled_at <= now, *scope).with_for_update(skip_locked=True)):
        c.status, c.started_at = "sending", now
        _materialize(db, c)
        out["started"] += 1
    db.flush()
    for c in db.scalars(select(WhatsAppCampaign).where(WhatsAppCampaign.status == "sending", *scope).with_for_update(skip_locked=True)):
        tenant = db.get(Tenant, c.tenant_id)
        t = db.get(WhatsAppTemplate, c.template_id) if c.template_id else None
        batch = list(db.scalars(select(WhatsAppCampaignRecipient).where(WhatsAppCampaignRecipient.campaign_id == c.id, WhatsAppCampaignRecipient.status == "pending").order_by(WhatsAppCampaignRecipient.id).limit(settings.whatsapp_campaign_batch).with_for_update(skip_locked=True)))
        for r in batch:
            contact = db.get(WhatsAppContact, r.contact_id)
            if contact is None or t is None or tenant is None:
                r.status, r.reason = "skipped", "contact_deleted" if contact is None else "template_missing"
                out["skipped"] += 1
                continue
            res = sender.send_template(db, tenant, contact, t, params_for(c, t, contact.customer_name, tenant), idem_key=f"camp:{c.id}:{contact.id}", campaign_id=c.id)
            if res.status == "sent":
                r.status, r.message_id = "sent", res.message_id
                out["sent"] += 1
            elif res.status == "failed":
                r.status, r.reason, r.message_id = "failed", res.reason, res.message_id
                out["failed"] += 1
            elif res.status == "skipped":
                r.status, r.reason = "skipped", res.reason
                out["skipped"] += 1
            else:
                break  # a limit or a Meta hiccup: stop this pass, the rest stays pending for the next one
        db.flush()
        if not db.scalar(select(WhatsAppCampaignRecipient.id).where(WhatsAppCampaignRecipient.campaign_id == c.id, WhatsAppCampaignRecipient.status == "pending").limit(1)):
            c.status, c.finished_at = "done", now
            out["finished"] += 1
    return out
