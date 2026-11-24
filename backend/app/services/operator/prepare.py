"""Prepare ONE improvement on demand: the AI drafts the complete change and it is stored as a normal `agent_action`, ready to approve.

This is the answer to "the card says it can be improved, I click it, and nothing opens". A recommendation card now calls `prepare` and then opens the prepared change. It reuses, and does not
copy, the engines that already draft changes (`seo_engine.scan_location` for the description and contact details, `v2.scan.scan_location_v2` for services, categories, hours and the rest). Nothing is
written to Google here: a prepared change is a proposal, and only a person's approval (through the existing executor) ever writes.

Returns {"status", "action_id", "message", "reasons"}:
  prepared             a change was drafted now
  already_prepared     a live change for this area already exists (it is opened, never duplicated)
  needs_owner_input    only the owner knows the answer (an attribute, a holiday, a service area): the card says what to enter
  nothing_to_change    the engines looked and found nothing worth changing
  cannot_prepare       the reason is in `message` (AI unavailable, profile not read yet, a limit, an unsupported area)"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentAction, GoogleLocation, Tenant
from app.models.base import utcnow
from app.services.agent import seo_engine

log = logging.getLogger("flowqr.operator")

AREA_TYPES = {"description": ("description_improve", "text_correction"), "categories": ("category_set_update", "secondary_category_update"), "services": ("service_update",),
              "hours": ("hours_update",), "special_hours": ("special_hours_update",), "attributes": ("attribute_change",), "contacts": ("contact_update", "primary_contact_change"),
              "service_area": ("service_area_change",)}
NEEDS_INPUT = {"attributes": "Google asks about attributes (for example Wi-Fi or wheelchair access). FlowQR never guesses these. Answer them under \"Tell us what we cannot know\".",
               "special_hours": "Holiday hours depend on your plans. Enter the date and whether you are closed or open different hours under \"Tell us what we cannot know\".",
               "service_area": "Your service area is something only you know. Enter the areas you serve under \"Tell us what we cannot know\"."}
LIVE = ("pending_approval", "recommended", "approved", "executing")
AI_DOWN = {"credits": "The AI service has no credit left. Add credit to the AI account, then try again.", "auth": "The AI service rejected FlowQR's key. The key needs to be replaced.",
           "not_configured": "No AI service is configured.", "quota_exhausted": "The AI service's daily limit was reached. Try again later.",
           "rate_limited": "The AI service is busy. Try again in a minute.", "timeout": "The AI service did not answer in time. Try again.", "rejected": "The AI's draft broke a safety rule twice, so nothing is shown."}


def explain_skip(reason: str) -> str:
    """The engines report why they skipped as a sentence that may contain an AI error code in brackets; turn the code into words an owner can act on."""
    for code, words in AI_DOWN.items():
        if f"({code})" in reason:
            return words
    return reason[:1].upper() + reason[1:] if reason else reason


def _live_for(db: Session, gloc: GoogleLocation, area: str) -> AgentAction | None:
    types = AREA_TYPES[area]
    return db.scalar(select(AgentAction).where(AgentAction.google_location_id == gloc.id, AgentAction.action_type.in_(types), AgentAction.status.in_(LIVE),
                                               AgentAction.subject_type.is_(None)).order_by(AgentAction.created_at.desc()).limit(1))


def prepare(db: Session, tenant: Tenant, gloc: GoogleLocation, area: str, *, provider=None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    if area not in AREA_TYPES:
        return {"status": "cannot_prepare", "action_id": None, "reasons": [], "message": "FlowQR does not prepare this part of the profile. It can only point you to where it is changed."}
    if area in NEEDS_INPUT:
        have = _live_for(db, gloc, area)
        if have is not None:
            return {"status": "already_prepared", "action_id": str(have.id), "reasons": [], "message": "This change is already prepared."}
        return {"status": "needs_owner_input", "action_id": None, "reasons": [], "message": NEEDS_INPUT[area]}
    have = _live_for(db, gloc, area)
    if have is not None:
        return {"status": "already_prepared", "action_id": str(have.id), "reasons": [], "message": "This change is already prepared. Opening it."}
    reasons: list[str] = []
    r1 = seo_engine.scan_location(db, tenant, gloc, provider=provider, now=now)  # description and missing contact details
    reasons += r1["skipped"]
    if area not in ("description", "contacts"):
        from app.services.agent.v2 import scan as v2_scan

        try:
            with db.begin_nested():
                r2 = v2_scan.scan_location_v2(db, tenant, gloc, now=now)
            reasons += r2["skipped"]
        except Exception:  # noqa: BLE001 - never turns a click into a server error; the reason is shown
            log.exception("operator prepare: v2 scan failed for %s", gloc.id)
            reasons.append("the check for this part of the profile could not run just now")
    db.flush()
    made = _live_for(db, gloc, area)
    if made is not None:
        return {"status": "prepared", "action_id": str(made.id), "reasons": [], "message": "The change is ready for your approval."}
    words = [explain_skip(x) for x in reasons]
    ai_blocked = [w for w in words if w in AI_DOWN.values()]
    if ai_blocked:
        return {"status": "cannot_prepare", "action_id": None, "reasons": words, "message": ai_blocked[0]}
    return {"status": "nothing_to_change", "action_id": None, "reasons": words,
            "message": ("FlowQR looked and found nothing it can safely change here right now. " + (words[0] + "." if words else "")).strip()}
