"""Ready-made automations: Review follow-up and Enquiry follow-up. One small engine, configuration-driven, no per-business code.

Trigger -> a scheduled RUN (one row, unique idempotency key) -> the worker executes due runs through the sender. The sender is the only thing that talks to Meta, so every rule in sender.py and gate.py
(consent, approved template, limits, emergency stop, duplicate suppression) applies to every automation without being repeated here.

Reliability: a trigger that fires twice creates one run; a run executes once (row lock + idempotency key on the message); a temporary failure is retried with growing delays, then marked `failed`
with its reason (the dead letter, visible to the owner); switching an automation off or pausing it cancels what has not been sent.

What these automations NEVER do: send to someone who has not agreed; filter or steer who is asked for a review by how they are expected to rate; offer anything in exchange for a review; follow up
on an enquiry that has already been answered.
"""
import logging
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Location, Tenant, User
from app.models.base import utcnow
from app.models.sites import SiteEnquiry
from app.models.whatsapp import WhatsAppAutomation, WhatsAppAutomationRun, WhatsAppContact
from app.services.audit import audit
from app.services.whatsapp import WaError, addons, connection, consent, links, sender, templates

log = logging.getLogger("flowqr.whatsapp.automations")
IST = ZoneInfo("Asia/Kolkata")

DEFAULTS = {"review_followup": {"delay_minutes": 60, "track_clicks": False}, "enquiry_followup": {"send_ack": True, "ack_delay_minutes": 2, "follow_up_hours": 24}, "birthday": {"send_hour": 10}, "festival": {"send_hour": 10}}
NEEDS = {"review_followup": ("review_followup",), "enquiry_followup": ("enquiry_ack", "enquiry_followup"), "birthday": ("occasion_birthday",), "festival": ("occasion_festival",)}
OCCASION_KEYS = ("birthday", "festival")  # greetings: Growth and Pro only, their own consent, 9 am to 9 pm India time
STEP_TEMPLATE = {"request": "review_followup", "ack": "enquiry_ack", "followup": "enquiry_followup"}
RANGES = {"delay_minutes": (5, 10080), "ack_delay_minutes": (0, 60), "follow_up_hours": (1, 168), "send_hour": (9, 20)}  # send_hour: India time, 9 am to 8 pm (so a greeting is always inside 9 am to 9 pm)
BACKOFF = (120, 600, 1800, 7200, 21600)


def clean_config(key: str, raw: dict | None) -> dict:
    base = dict(DEFAULTS[key])
    for k, v in (raw or {}).items():
        if k not in base:
            raise WaError(422, "invalid_config", "Unknown setting.")
        if isinstance(base[k], bool):
            if not isinstance(v, bool):
                raise WaError(422, "invalid_config", "That setting must be yes or no.")
            base[k] = v
        else:
            lo, hi = RANGES[k]
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                raise WaError(422, "invalid_config", f"Choose a number between {lo} and {hi}.")
            base[k] = v
    return base


def get(db: Session, tenant_id: uuid.UUID, key: str) -> WhatsAppAutomation | None:
    return db.scalar(select(WhatsAppAutomation).where(WhatsAppAutomation.tenant_id == tenant_id, WhatsAppAutomation.automation_key == key))


def active_count(db: Session, tenant_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(WhatsAppAutomation).where(WhatsAppAutomation.tenant_id == tenant_id, WhatsAppAutomation.status == "on")) or 0


def _checklist(db: Session, tenant_id: uuid.UUID, key: str) -> dict:
    conn = connection.connected_connection(db, tenant_id)
    rows = {k: templates.standard_row(db, tenant_id, k) for k in NEEDS[key]}
    return {"connected": conn is not None and conn.status == "connected", "templates_installed": all(r is not None for r in rows.values()), "templates_approved": all(r is not None and r.approval_status == "approved" for r in rows.values()),
            "missing": [k for k, r in rows.items() if r is None], "waiting": [k for k, r in rows.items() if r is not None and r.approval_status == "pending"], "refused": [k for k, r in rows.items() if r is not None and r.approval_status in ("rejected", "paused", "disabled")]}


def serialize(db: Session, tenant_id: uuid.UUID, key: str) -> dict:
    a = get(db, tenant_id, key)
    last = db.execute(select(WhatsAppAutomationRun.status, func.count()).where(WhatsAppAutomationRun.tenant_id == tenant_id, WhatsAppAutomationRun.automation_id == (a.id if a else None)).group_by(WhatsAppAutomationRun.status)).all() if a else []
    return {"key": key, "status": a.status if a else "off", "config": a.config if a else dict(DEFAULTS[key]), "activated_at": a.activated_at if a else None, "last_run_at": a.last_run_at if a else None,
            "runs": {s: n for s, n in last}, "checklist": _checklist(db, tenant_id, key)}


def set_status(db: Session, tenant: Tenant, user: User, key: str, status: str, config: dict | None = None, ip: str | None = None) -> dict:
    if key not in DEFAULTS:
        raise WaError(404, "unknown_automation", "Unknown helper.")
    if status not in ("on", "paused", "off"):
        raise WaError(422, "invalid_status", "Choose on, paused or off.")
    a = get(db, tenant.id, key)
    cfg = clean_config(key, config) if config is not None else (a.config if a else dict(DEFAULTS[key]))
    if cfg.get("track_clicks") and not addons.click_tracking_allowed(db, tenant.id):
        raise WaError(402, "plan_required", "Counting link clicks is part of the Pro add-on.")
    if status == "on" and (a is None or a.status != "on"):
        if key in OCCASION_KEYS and not addons.occasions_allowed(db, tenant.id):
            raise WaError(402, "plan_required", "Birthday and festival wishes are part of the Growth and Pro add-ons.")
        addon = addons.active_addon(db, tenant.id)
        if settings.whatsapp_require_addon and addon is None:
            raise WaError(402, "addon_required", "WhatsApp automation is an add-on. Ask FlowQR to switch it on for your business.")
        limit = addons.tier(addon)["automation_limit"] if addon else 15
        if active_count(db, tenant.id) >= limit:
            raise WaError(409, "automation_limit", f"Your plan allows {limit} automations at a time. Switch one off first, or ask FlowQR about a bigger plan.")
        chk = _checklist(db, tenant.id, key)
        if not chk["connected"]:
            raise WaError(409, "not_connected", "Connect your WhatsApp number first.")
        for k in NEEDS[key]:
            if templates.standard_row(db, tenant.id, k) is None:
                templates.install(db, tenant.id, k, user.id, ip)  # first time: submit the standard message to WhatsApp for approval
        chk = _checklist(db, tenant.id, key)
        if not chk["templates_approved"]:
            raise WaError(409, "templates_pending", "WhatsApp is still reviewing the message for this helper. This usually takes a short while. Press Check messages on the Messages page, then try again.")
    if a is None:
        a = WhatsAppAutomation(tenant_id=tenant.id, automation_key=key, status="off", config=cfg, created_by=user.id)
        db.add(a)
        db.flush()
    was = a.status
    a.config = cfg
    a.status = status
    if status == "on" and was != "on":
        a.activated_at = utcnow()
    if status != "on":
        for r in db.scalars(select(WhatsAppAutomationRun).where(WhatsAppAutomationRun.automation_id == a.id, WhatsAppAutomationRun.status == "scheduled")):
            r.status, r.reason = "cancelled", f"automation_{status}"
    db.flush()
    audit(db, action="whatsapp.automation_status", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_automation", entity_id=a.id, meta={"key": key, "from": was, "to": status, "config": cfg}, ip=ip)
    return serialize(db, tenant.id, key)


def _schedule(db: Session, a: WhatsAppAutomation, contact: WhatsAppContact | None, step: str, trigger_ref: str, when: datetime, context: dict) -> WhatsAppAutomationRun | None:
    idem = f"{a.id}:{trigger_ref}:{step}"
    run = WhatsAppAutomationRun(tenant_id=a.tenant_id, automation_id=a.id, contact_id=contact.id if contact else None, step=step, trigger_ref=trigger_ref[:120], idempotency_key=idem[:200], status="scheduled",
                                scheduled_at=when, context=context)
    try:
        with db.begin_nested():
            db.add(run)
            db.flush()
    except IntegrityError:
        return None  # this trigger already scheduled this step
    return run


# ---- triggers
def on_visit_completed(db: Session, tenant: Tenant, contact: WhatsAppContact, user_id: uuid.UUID | None = None, now: datetime | None = None) -> dict:
    """The owner marked a customer's visit as done. Schedules ONE neutral request for honest feedback (never more than one a day, never more often than WHATSAPP_REVIEW_GAP_DAYS)."""
    now = now or utcnow()
    a = get(db, tenant.id, "review_followup")
    if a is None or a.status != "on":
        raise WaError(409, "automation_off", "Switch on 'Get more customer reviews' first.")
    row = templates.standard_row(db, tenant.id, "review_followup")
    if row is None or row.approval_status != "approved":
        return {"scheduled": False, "reason": "template_not_approved"}
    ok, reason = consent.has_consent(db, tenant.id, contact, row.category)
    if not ok:
        return {"scheduled": False, "reason": reason}
    since = now - timedelta(days=settings.whatsapp_review_gap_days)
    if db.scalar(select(WhatsAppAutomationRun.id).where(WhatsAppAutomationRun.automation_id == a.id, WhatsAppAutomationRun.contact_id == contact.id, WhatsAppAutomationRun.step == "request",
                                                       WhatsAppAutomationRun.status.in_(("scheduled", "sending", "sent")), WhatsAppAutomationRun.created_at >= since).limit(1)):
        return {"scheduled": False, "reason": "asked_recently"}
    run = _schedule(db, a, contact, "request", f"visit:{contact.id}:{now.date().isoformat()}", now + timedelta(minutes=int(a.config.get("delay_minutes", 60))), {"first_name": templates.first_name(contact.customer_name)})
    audit(db, action="whatsapp.visit_completed", tenant_id=tenant.id, user_id=user_id, entity_type="whatsapp_contact", entity_id=contact.id)
    return {"scheduled": run is not None, "reason": "ok" if run else "already_scheduled", "send_at": run.scheduled_at if run else None}


def on_enquiry(db: Session, tenant_id: uuid.UUID, enquiry: SiteEnquiry, whatsapp_ok: bool, now: datetime | None = None) -> dict:
    """A website enquiry arrived. If the visitor ticked 'WhatsApp updates', record THEIR consent (source website_form) and schedule an acknowledgement and, if nobody has answered, one follow-up.
    Without the tick nothing is recorded and nothing is sent. Never raises into the caller's flow beyond what the caller chooses to catch."""
    now = now or utcnow()
    if not settings.whatsapp_enabled or not whatsapp_ok or not enquiry.phone:
        return {"scheduled": 0}
    a = get(db, tenant_id, "enquiry_followup")
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return {"scheduled": 0}
    try:
        phone = consent.e164(enquiry.phone)
    except WaError:
        return {"scheduled": 0}
    contact, _ = consent.create_contact(db, tenant, phone=phone, name=enquiry.name, tags=["website enquiry"], source="website_form", user_id=None)
    consent.grant(db, tenant, contact, "utility", "website_form")  # the visitor ticked the box on the site: their own act
    if a is None or a.status != "on":
        return {"scheduled": 0, "consent_recorded": True}
    n = 0
    ctx = {"first_name": templates.first_name(enquiry.name), "enquiry_id": str(enquiry.id)}
    if a.config.get("send_ack", True) and _schedule(db, a, contact, "ack", f"enquiry:{enquiry.id}", now + timedelta(minutes=int(a.config.get("ack_delay_minutes", 2))), ctx):
        n += 1
    if _schedule(db, a, contact, "followup", f"enquiry:{enquiry.id}", now + timedelta(hours=int(a.config.get("follow_up_hours", 24))), ctx):
        n += 1
    return {"scheduled": n, "consent_recorded": True}


# ---- execution
def _review_link(db: Session, tenant_id: uuid.UUID) -> str | None:
    loc = db.scalar(select(Location).where(Location.tenant_id == tenant_id, Location.is_active.is_(True), Location.review_url.is_not(None), Location.review_url != "").order_by(Location.created_at).limit(1))
    return loc.review_url if loc else None


def _finish(run: WhatsAppAutomationRun, status: str, reason: str | None, now: datetime) -> None:
    run.status, run.reason, run.executed_at = status, (reason or None), now


def execute_run(db: Session, run: WhatsAppAutomationRun, now: datetime | None = None) -> str:
    now = now or utcnow()
    a = db.get(WhatsAppAutomation, run.automation_id)
    if a is None or a.status != "on":
        _finish(run, "cancelled", f"automation_{a.status if a else 'gone'}", now)
        return "cancelled"
    tenant, contact = db.get(Tenant, run.tenant_id), (db.get(WhatsAppContact, run.contact_id) if run.contact_id else None)
    if tenant is None or contact is None:
        _finish(run, "cancelled", "contact_deleted", now)
        return "cancelled"
    if run.step == "followup":  # an answered enquiry needs no chasing
        enq = db.get(SiteEnquiry, uuid.UUID(run.context.get("enquiry_id", "00000000-0000-0000-0000-000000000000")))
        if enq is None or enq.status != "new":
            _finish(run, "skipped", "responded", now)
            return "skipped"
    if a.automation_key in OCCASION_KEYS:
        return _execute_greeting(db, run, a, tenant, contact, now)
    key = STEP_TEMPLATE[run.step]
    row = templates.standard_row(db, tenant.id, key)
    if row is None:
        _finish(run, "failed", "template_missing", now)
        return "failed"
    name = run.context.get("first_name") or templates.first_name(contact.customer_name)
    tracked = None
    if run.step == "request":
        link = _review_link(db, tenant.id)
        if not link:
            _finish(run, "skipped", "no_review_link", now)
            return "skipped"
        if a.config.get("track_clicks") and addons.click_tracking_allowed(db, tenant.id):  # Pro: the link goes through FlowQR so a click can be counted; it still leads to the same review page
            tracked = links.get_or_create(db, tenant.id, link, f"run:{run.idempotency_key}", contact.id)
        variables = [name, tenant.name, links.url_for(tracked.token) if tracked else link]
    else:
        variables = [name, tenant.name]
    res = sender.send_template(db, tenant, contact, row, variables, idem_key=f"run:{run.idempotency_key}", run_id=run.id)
    if tracked is not None and res.message_id is not None and tracked.message_id is None:
        tracked.message_id = res.message_id
    return _apply(run, a, res, now)


def _apply(run: WhatsAppAutomationRun, a: WhatsAppAutomation, res, now: datetime) -> str:
    if res.status == "sent":
        _finish(run, "sent", None, now)
        a.last_run_at = now
    elif res.status == "skipped":
        _finish(run, "skipped", res.reason, now)
    elif res.status == "failed":
        _finish(run, "failed", res.reason, now)
    else:  # retry
        run.attempts += 1
        if run.attempts >= settings.whatsapp_send_max_attempts:
            _finish(run, "failed", f"gave_up:{res.reason}", now)  # the dead letter: visible to the owner, never silently dropped
        else:
            run.scheduled_at = now + timedelta(seconds=max(res.retry_after, BACKOFF[min(run.attempts - 1, len(BACKOFF) - 1)]))
            run.reason = res.reason
    return run.status


def _execute_greeting(db: Session, run: WhatsAppAutomationRun, a: WhatsAppAutomation, tenant: Tenant, contact: WhatsAppContact, now: datetime) -> str:
    """A birthday or festival greeting. It goes out on its own day or not at all: a greeting that missed its day (the worker was down, or the hours closed) is skipped, never sent late."""
    if run.context.get("on") != now.astimezone(IST).date().isoformat():
        _finish(run, "skipped", "day_passed", now)
        return "skipped"
    row = templates.standard_row(db, tenant.id, "occasion_birthday" if a.automation_key == "birthday" else "occasion_festival")
    if row is None:
        _finish(run, "failed", "template_missing", now)
        return "failed"
    variables = [run.context.get("first_name") or templates.first_name(contact.customer_name), tenant.name]
    if a.automation_key == "festival":
        variables.append(run.context.get("festival") or "")
    res = sender.send_template(db, tenant, contact, row, variables, idem_key=f"run:{run.idempotency_key}", run_id=run.id, kind="occasion", now=now)
    return _apply(run, a, res, now)


def sending_allowed() -> bool:
    return bool(settings.whatsapp_enabled and settings.whatsapp_sending_enabled and not settings.whatsapp_emergency_stop)


def run_due(db: Session, limit: int = 50, now: datetime | None = None, tenant_id: uuid.UUID | None = None) -> dict:
    """The worker pass: execute due runs. Rows are locked (SKIP LOCKED), so two workers never run the same one."""
    now = now or utcnow()
    if not sending_allowed():
        return {"held": True, "executed": 0}
    out: dict = {"executed": 0}
    q = select(WhatsAppAutomationRun).where(WhatsAppAutomationRun.status == "scheduled", WhatsAppAutomationRun.scheduled_at <= now)
    if tenant_id is not None:
        q = q.where(WhatsAppAutomationRun.tenant_id == tenant_id)
    runs = list(db.scalars(q.order_by(WhatsAppAutomationRun.scheduled_at).limit(limit).with_for_update(skip_locked=True)))
    for r in runs:
        try:
            with db.begin_nested():
                s = execute_run(db, r, now)
        except Exception:  # noqa: BLE001 - one broken run must not stop the others
            log.exception("automation run %s crashed", r.id)
            r.attempts += 1
            r.status, r.reason, r.executed_at = ("failed", "internal_error", now) if r.attempts >= settings.whatsapp_send_max_attempts else ("scheduled", "internal_error", None)
            if r.status == "scheduled":
                r.scheduled_at = now + timedelta(seconds=BACKOFF[min(r.attempts - 1, len(BACKOFF) - 1)])
            s = r.status
        out["executed"] += 1
        out[s] = out.get(s, 0) + 1
    return out


def list_runs(db: Session, tenant_id: uuid.UUID, key: str, limit: int = 50, status: str | None = None) -> list[dict]:
    a = get(db, tenant_id, key)
    if a is None:
        return []
    q = select(WhatsAppAutomationRun, WhatsAppContact).join(WhatsAppContact, WhatsAppContact.id == WhatsAppAutomationRun.contact_id, isouter=True).where(WhatsAppAutomationRun.automation_id == a.id)
    if status:
        q = q.where(WhatsAppAutomationRun.status == status)
    return [{"id": r.id, "step": r.step, "status": r.status, "reason": r.reason, "to": c.customer_name if c else None, "phone_last4": c.phone[-4:] if c else None, "scheduled_at": r.scheduled_at,
             "executed_at": r.executed_at, "attempts": r.attempts} for r, c in db.execute(q.order_by(WhatsAppAutomationRun.created_at.desc()).limit(max(1, min(limit, 200)))).all()]
