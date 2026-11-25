"""Edit or regenerate a prepared description change. Both go through the same `executor.propose` as everything else: the policy level, risk and validation are computed there, never here,
and a person's edit is always authorised by that person (`force_owner`), never by standing autonomy.

The old proposal is retired first (cancelled if it was waiting, rejected as "replaced" if it was only drafted) so there is never more than one live description change."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentAction, GbpSnapshot, GoogleLocation, Role, Tenant
from app.models.base import utcnow
from app.services.agent import executor
from app.services.agent import knowledge as kbs
from app.services.agent import optimizer
from app.services.agent.safety import check_text
from app.services.ai import intelligence
from app.services.ai.description import draft_description

MIN_LEN, MAX_LEN = 40, 750


class ChangeError(Exception):
    def __init__(self, message: str, status: int = 409, detail=None):
        super().__init__(message)
        self.status, self.detail = status, detail


def _retire(db: Session, a: AgentAction, *, user_id: uuid.UUID, role: Role, now: datetime) -> None:
    if a.status == "pending_approval":
        executor.cancel(db, a, user_id=user_id, now=now)
    elif a.status == "recommended":
        executor.decide(db, a, user_id=user_id, role=role, approve=False, reason="Replaced by a new version", now=now)
    else:
        raise ChangeError(f"This change is {a.status.replace('_', ' ')} and can no longer be replaced.")


def _check(a: AgentAction) -> None:
    if a.field_key != "description" or a.action_type not in ("description_improve", "text_correction"):
        raise ChangeError("Only the business description can be reworded here. The other fields are checked against Google's own lists, so you approve or reject the whole draft.")
    if a.status not in ("pending_approval", "recommended"):
        raise ChangeError(f"This change is {a.status.replace('_', ' ')} and can no longer be edited.")


def _propose(db: Session, tenant: Tenant, gloc: GoogleLocation, text: str, *, user_id: uuid.UUID, trigger: str, problem: str, reason: str, evidence: dict, now: datetime, ai: bool = False) -> AgentAction:
    kb = kbs.context(db, tenant)
    source = ({"kind": "business_knowledge", "refs": [r for r in ("description", "services") if kb.get(r)]} if ai else {"kind": "owner_input", "user_id": str(user_id), "refs": ["description"]})
    return executor.propose(db, tenant, gloc, "description_improve", proposed=text, source=source, trigger=trigger,
                            problem=problem, reason=reason, evidence=evidence, proposed_by="user", user_id=user_id, force_owner=True, now=now)


def edit_description(db: Session, tenant: Tenant, gloc: GoogleLocation, a: AgentAction, text: str, *, user_id: uuid.UUID, role: Role, now: datetime | None = None) -> AgentAction:
    now = now or utcnow()
    _check(a)
    text = " ".join(text.split()) if "\n" not in text else text.strip()
    if not (MIN_LEN <= len(text) <= MAX_LEN):
        raise ChangeError(f"A description is {MIN_LEN} to {MAX_LEN} characters long.", 422)
    bad = check_text(text, kb=kbs.context(db, tenant), kind="profile")
    if bad:
        raise ChangeError("This text breaks a rule from your Business Brain. Edit it first.", 422, [v.as_dict() for v in bad])
    problem, reason = a.problem, "You edited the wording yourself, and FlowQR checked it against your Business Brain."
    _retire(db, a, user_id=user_id, role=role, now=now)
    return _propose(db, tenant, gloc, text, user_id=user_id, trigger="owner_edit", problem=problem, reason=reason, evidence={"edited_by_owner": True, "replaces": str(a.id)}, now=now)


def regenerate_description(db: Session, tenant: Tenant, gloc: GoogleLocation, a: AgentAction, *, user_id: uuid.UUID, role: Role, provider=None, now: datetime | None = None) -> AgentAction:
    """A new AI version from the same verified facts. The AI is called BEFORE the old proposal is retired, so a failed draft never leaves the owner with nothing."""
    from app.services.ai import get_provider
    from app.services.ai.base import AIUnavailable
    from app.services.ai_usage import metered

    now = now or utcnow()
    _check(a)
    snap = db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gloc.id))
    kb = kbs.context(db, tenant)
    try:
        provider = provider or metered(get_provider(), db, tenant.id, "agent_draft")
        intel = intelligence.build(db, tenant, kb, google_location_id=gloc.id)
        text, qa = draft_description(provider, tenant, kb, intel, terms_line=optimizer.search_terms_line(snap) if snap else "")
    except AIUnavailable as exc:
        from app.services.operator.prepare import AI_DOWN

        raise ChangeError(AI_DOWN.get(exc.code, "The AI could not write a safe description. Try again, or write it yourself."), 502) from exc
    text = text.strip()[:MAX_LEN]
    if len(text) < 100:
        raise ChangeError("The new draft was too short to be useful. Try again, or write it yourself.", 502)
    ai_meta = {"model": getattr(provider, "model", None), "provider": getattr(provider, "name", None), "quality": qa.score if qa else None, "checked_against": "business knowledge (services, prices, claims)"}
    problem, reason = a.problem, "A new version of the description, written only from the facts in your Business Brain."
    _retire(db, a, user_id=user_id, role=role, now=now)
    return _propose(db, tenant, gloc, text, user_id=user_id, trigger="owner_regenerate", problem=problem, reason=reason, evidence={"ai": ai_meta, "replaces": str(a.id)}, now=now, ai=True)
