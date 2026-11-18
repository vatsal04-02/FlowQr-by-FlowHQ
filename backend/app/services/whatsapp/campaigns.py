"""Promotional campaigns: an offer sent to customers who agreed to receive offers.

The owner's journey: create (name, the approved Offer message, who, the offer text) -> PREVIEW (how many people, the message as they will read it, an estimated WhatsApp charge) -> APPROVE (an
explicit final step) -> the worker sends in small batches -> results. Nothing is sent before approval, and approval is bound to what the owner saw:

* approval must repeat the recipient count the owner was shown; if the audience changed in between (someone opted out, someone agreed), approval is refused and the new count is shown;
* the approved count is a ceiling: customers added after approval are never included;
* consent is checked again for every person at the moment of sending (an opt-out after approval removes them), and the sender's own gate applies as for every message;
* a campaign can be paused, resumed or cancelled at any time; the emergency stop holds all sending;
* the same customer is never in a campaign twice, and never receives two marketing messages within WHATSAPP_MARKETING_GAP_HOURS.

Results never claim sales or revenue: WhatsApp reports sent, delivered and (only when the customer's read receipts are on) read.
"""
import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Tenant, User
from app.models.base import utcnow
from app.models.whatsapp import WhatsAppCampaign, WhatsAppCampaignRecipient, WhatsAppConsent, WhatsAppContact, WhatsAppMessage, WhatsAppTemplate
from app.services.audit import audit
from app.services.whatsapp import WaError, addons, automations, connection, pricing, sender, templates, usage

log = logging.getLogger("flowqr.whatsapp.campaigns")
KINDS = ("all", "tag", "new", "existing")
MAX_OFFER = 120


def _money(v) -> str | None:
    """Money as the owner saw it: two decimals, or nothing when no rate was known."""
    return None if v is None else str(Decimal(v).quantize(Decimal("0.01")))


def clean_audience(raw: dict | None) -> dict:
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
    return out


def _tier(db: Session, tenant_id: uuid.UUID) -> dict | None:
    return addons.tier(addons.active_addon(db, tenant_id))


def can_use_campaigns(db: Session, tenant_id: uuid.UUID) -> bool:
    if not settings.whatsapp_require_addon:
        return True
    t = _tier(db, tenant_id)
    return bool(t and t["campaigns"])


def audience_query(tenant_id: uuid.UUID, audience: dict, now: datetime | None = None):
    now = now or utcnow()
    q = select(WhatsAppContact).where(WhatsAppContact.tenant_id == tenant_id, WhatsAppContact.marketing_opted_out_at.is_(None),
                                      WhatsAppContact.id.in_(select(WhatsAppConsent.contact_id).where(WhatsAppConsent.tenant_id == tenant_id, WhatsAppConsent.purpose == "marketing", WhatsAppConsent.revoked_at.is_(None))))
    k = audience.get("kind", "all")
    if k == "tag":
        q = q.where(WhatsAppContact.tags.contains([audience["tag"]]))
    elif k == "new":
        q = q.where(WhatsAppContact.created_at >= now - timedelta(days=audience["days"]))
    elif k == "existing":
        q = q.where(WhatsAppContact.created_at < now - timedelta(days=audience["days"]))
    return q


def audience_count(db: Session, tenant_id: uuid.UUID, audience: dict) -> int:
    return db.scalar(select(func.count()).select_from(audience_query(tenant_id, audience).subquery())) or 0


def offer_template(db: Session, tenant_id: uuid.UUID, template_id: uuid.UUID) -> WhatsAppTemplate:
    t = db.scalar(select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id, WhatsAppTemplate.tenant_id == tenant_id))
    if t is None or templates.key_of(t.template_name) != "offer":
        raise WaError(404, "template_not_found", "Choose the Offer message.")
    return t


def clean_offer(variables) -> dict:
    v = variables if isinstance(variables, dict) else {}
    text = templates.clean_variable(v.get("offer_text") or "").rstrip(" .")  # the message adds its own full stop
    if not 5 <= len(text) <= MAX_OFFER:
        raise WaError(422, "invalid_offer", f"Describe your offer in 5 to {MAX_OFFER} characters.")
    return {"offer_text": text}


def get(db: Session, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> WhatsAppCampaign:
    c = db.scalar(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant_id))
    if c is None:
        raise WaError(404, "not_found", "That campaign was not found.")
    return c


def create(db: Session, tenant: Tenant, user: User, *, name: str, template_id: uuid.UUID, audience: dict | None, variables: dict | None, scheduled_at: datetime | None, ip: str | None = None) -> WhatsAppCampaign:
    if not can_use_campaigns(db, tenant.id):
        raise WaError(402, "plan_required", "Campaigns are part of the Growth and Pro add-ons. Ask FlowQR to upgrade your WhatsApp add-on.")
    name = " ".join((name or "").split())
    if not 2 <= len(name) <= 120:
        raise WaError(422, "invalid_name", "Give the campaign a name (2 to 120 characters).")
    offer_template(db, tenant.id, template_id)
    c = WhatsAppCampaign(tenant_id=tenant.id, name=name, template_id=template_id, audience=clean_audience(audience), variables=clean_offer(variables), status="draft", scheduled_at=scheduled_at, created_by=user.id)
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
        c.audience = clean_audience(audience)
    if variables is not None:
        c.variables = clean_offer(variables)
    if set_schedule:
        c.scheduled_at = scheduled_at
    return c


def _sample_name(db: Session, tenant_id: uuid.UUID, audience: dict) -> str:
    first = db.scalar(audience_query(tenant_id, audience).order_by(WhatsAppContact.created_at).limit(1))
    return templates.first_name(first.customer_name) if first else "Asha"


def preview(db: Session, tenant: Tenant, c: WhatsAppCampaign) -> dict:
    t = db.get(WhatsAppTemplate, c.template_id) if c.template_id else None
    n = audience_count(db, tenant.id, c.audience)
    est = pricing.estimate(db, "marketing", n)
    conn = connection.connected_connection(db, tenant.id)
    ready = {"plan": can_use_campaigns(db, tenant.id), "connection": bool(conn and conn.status == "connected"), "template_approved": bool(t and t.approval_status == "approved"), "has_recipients": n > 0, "sending_on": automations.sending_allowed()}
    text = templates.render(t, [_sample_name(db, tenant.id, c.audience), tenant.name, c.variables.get("offer_text", "")]) if t and t.body_text else None
    return {"id": c.id, "name": c.name, "status": c.status, "audience": c.audience, "recipients": n, "estimate": est, "message_preview": text, "ready": ready, "approved_recipients": c.approved_recipients,
            "approved_cost": _money(c.approved_cost), "scheduled_at": c.scheduled_at,
            "excluded_note": "Only customers who agreed to receive offers and have not asked to stop are counted."}


def approve(db: Session, tenant: Tenant, user: User, c: WhatsAppCampaign, *, confirm_recipients: int, accept_estimate: bool, ip: str | None = None, now: datetime | None = None) -> WhatsAppCampaign:
    """The explicit final approval. Nothing is ever sent without it."""
    now = now or utcnow()
    if c.status not in ("draft", "paused"):
        raise WaError(409, "not_approvable", "This campaign cannot be approved in its current state.")
    if not can_use_campaigns(db, tenant.id):
        raise WaError(402, "plan_required", "Campaigns are part of the Growth and Pro add-ons.")
    p = preview(db, tenant, c)
    if not p["ready"]["connection"]:
        raise WaError(409, "not_connected", "Connect your WhatsApp number first.")
    if not p["ready"]["template_approved"]:
        raise WaError(409, "template_not_approved", "WhatsApp has not approved the Offer message yet.")
    if p["recipients"] == 0:
        raise WaError(409, "no_recipients", "No customers who agreed to receive offers match this audience.")
    if not accept_estimate:
        raise WaError(422, "estimate_not_accepted", "Please confirm you have seen the estimated WhatsApp charge.")
    if confirm_recipients != p["recipients"]:
        raise WaError(409, "recipients_changed", f"The number of customers changed from {confirm_recipients} to {p['recipients']}. Please review and approve again.")
    c.approved_by, c.approved_at, c.approved_recipients = user.id, now, p["recipients"]
    c.approved_cost = Decimal(p["estimate"]["amount"]) if p["estimate"]["amount"] is not None else None
    c.status = "scheduled"
    if c.scheduled_at is None or c.scheduled_at < now:
        c.scheduled_at = now
    audit(db, action="whatsapp.campaign_approve", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_campaign", entity_id=c.id,
          meta={"recipients": p["recipients"], "estimate": p["estimate"]["amount"], "verified_rate": p["estimate"]["verified"]}, ip=ip)
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
def results(db: Session, tenant_id: uuid.UUID, c: WhatsAppCampaign) -> dict:
    far = datetime(2100, 1, 1, tzinfo=c.created_at.tzinfo)
    m = usage.counts(db, tenant_id, datetime(2000, 1, 1, tzinfo=c.created_at.tzinfo), far, campaign_id=c.id).get("marketing", {"attempted": 0, "sent": 0, "delivered": 0, "read": 0, "failed": 0, "estimated_cost": Decimal(0)})
    rec = dict(db.execute(select(WhatsAppCampaignRecipient.status, func.count()).where(WhatsAppCampaignRecipient.campaign_id == c.id).group_by(WhatsAppCampaignRecipient.status)).all())
    opted = 0
    if c.started_at:
        opted = db.scalar(select(func.count()).select_from(WhatsAppCampaignRecipient).join(WhatsAppContact, WhatsAppContact.id == WhatsAppCampaignRecipient.contact_id).where(
            WhatsAppCampaignRecipient.campaign_id == c.id, WhatsAppContact.marketing_opted_out_at >= c.started_at)) or 0
    skipped_reasons = dict(db.execute(select(WhatsAppCampaignRecipient.reason, func.count()).where(WhatsAppCampaignRecipient.campaign_id == c.id, WhatsAppCampaignRecipient.status == "skipped").group_by(WhatsAppCampaignRecipient.reason)).all())
    return {"id": c.id, "name": c.name, "status": c.status, "approved_recipients": c.approved_recipients, "approved_estimate": _money(c.approved_cost),
            "attempted": m["attempted"], "sent": m["sent"], "delivered": m["delivered"], "read": m["read"], "failed": m["failed"], "waiting": rec.get("pending", 0), "skipped": rec.get("skipped", 0),
            "skipped_reasons": skipped_reasons, "opted_out_after": opted, "estimated_meta_cost": str(m["estimated_cost"].quantize(Decimal("0.01"))), "started_at": c.started_at, "finished_at": c.finished_at,
            "note": "WhatsApp tells us when a message is sent, delivered and, if the customer allows it, read. FlowQR cannot tell you how many sales an offer led to. " + pricing.NOTE}


def serialize(c: WhatsAppCampaign) -> dict:
    return {"id": c.id, "name": c.name, "status": c.status, "audience": c.audience, "variables": c.variables, "template_id": c.template_id, "scheduled_at": c.scheduled_at, "approved_at": c.approved_at,
            "approved_recipients": c.approved_recipients, "approved_cost": _money(c.approved_cost), "started_at": c.started_at, "finished_at": c.finished_at, "created_at": c.created_at}


# ---- the worker
def _materialize(db: Session, c: WhatsAppCampaign) -> int:
    """Fix the recipient list at the moment sending starts: whoever is eligible now, at most the approved number."""
    ids = [r for r in db.scalars(audience_query(c.tenant_id, c.audience).with_only_columns(WhatsAppContact.id).order_by(WhatsAppContact.created_at).limit(c.approved_recipients or 0))]
    if ids:
        db.execute(pg_insert(WhatsAppCampaignRecipient).values([{"id": uuid.uuid4(), "tenant_id": c.tenant_id, "campaign_id": c.id, "contact_id": i, "status": "pending"} for i in ids]).on_conflict_do_nothing(constraint="uq_wa_campaign_recipient"))
    return len(ids)


def run_due(db: Session, now: datetime | None = None, tenant_id: uuid.UUID | None = None) -> dict:
    now = now or utcnow()
    if not automations.sending_allowed():
        return {"held": True}
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
            res = sender.send_template(db, tenant, contact, t, [templates.first_name(contact.customer_name), tenant.name, c.variables.get("offer_text", "")], idem_key=f"camp:{c.id}:{contact.id}", campaign_id=c.id)
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
