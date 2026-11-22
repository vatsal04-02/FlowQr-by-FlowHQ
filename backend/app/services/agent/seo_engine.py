"""The SEO opportunity scan: turns verified data into proposals, and hands every one of them to the policy engine and executor.

It decides WHAT could be improved; it never decides how much freedom it has (autonomy_policy) and never writes to Google (executor). Inputs, all real:
the latest Google profile snapshot, the business knowledge base and tenant record, the optimizer's checks, and the measured search visibility (Places results for the
tracked search terms). Without ranking data the visibility-driven opportunity simply does not exist: rank data changes what the engine proposes."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentAction, GbpSnapshot, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Tenant
from app.models.autonomy import LIVE_STATUSES
from app.models.base import utcnow
from app.services.agent import autonomy_policy as pol
from app.services.agent import executor, learning, optimizer
from app.services.agent import knowledge as kbs
from app.services.ai import intelligence
from app.services.ai.base import AIUnavailable
from app.services.ai.description import draft_description

log = logging.getLogger("flowqr.seo")
STOP_WORDS = frozenset({"near", "me", "in", "the", "a", "an", "and", "for", "best", "top", "good", "cheap", "my", "of", "to", "at", "open", "now"})
MIN_AI_DESCRIPTION = 100  # the engine's own quality bar, stricter than the policy's hard floor


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in STOP_WORDS and len(w) > 2]


def applicable_weak_terms(rank: dict | None, kb: dict, tenant: Tenant, current_description: str) -> list[dict]:
    """Tracked terms where the business was NOT shown in the first 10 results AND whose every word is something the business verifiably is or does (its category,
    description or services in the knowledge base) AND that the current description does not yet say. Only these may be mentioned: never a term the business has no
    verified basis for."""
    if not rank:
        return []
    facts = " ".join([kb.get("description") or "", " ".join(map(str, kb.get("services") or [])), tenant.category or ""]).lower()
    have = (current_description or "").lower()
    out = []
    for w in rank.get("weak", []):
        toks = _words(w["keyword"])
        if toks and all(t in facts for t in toks) and not all(t in have for t in toks):
            out.append(w)
    return out


def _recent_action(db: Session, tenant_id, gloc_id, action_type: str, now: datetime) -> bool:
    """Is there already a live, recently blocked or recently executed action of this type here? (Avoids paying for a new AI draft that would be a duplicate.)"""
    return db.scalar(select(AgentAction.id).where(
        AgentAction.tenant_id == tenant_id, AgentAction.google_location_id == gloc_id, AgentAction.action_type == action_type,
        (AgentAction.status.in_(("pending_approval", "approved", "executing"))) |
        ((AgentAction.status == "executed") & (AgentAction.executed_at >= now - timedelta(days=14))) |
        ((AgentAction.status == "blocked") & (AgentAction.created_at >= now - timedelta(days=7)))).limit(1)) is not None


def scan_location(db: Session, tenant: Tenant, gloc: GoogleLocation, *, provider=None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    out: dict = {"proposed": [], "skipped": []}
    snap = db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gloc.id))
    if snap is None or snap.info is None:
        out["skipped"].append("no recent copy of the Google profile")
        return out
    kb = kbs.context(db, tenant)
    rank = learning.rank_summary(db, gloc.id)
    checks = {c["key"]: c for c in optimizer.checks(snap, kb, rank=rank)}
    # ---- 1. missing contact details that the business record already holds (no AI involved)
    for fk in ("website", "phone"):
        value = getattr(tenant, fk, None)
        if pol.is_empty(pol.field_value(snap.info, fk)) and value:
            a = executor.propose(db, tenant, gloc, "contact_update", field_key=fk, proposed=value, source={"kind": "tenant_record", "refs": [fk]}, trigger=f"optimizer:{fk}",
                                 problem=f"Your Google profile has no {fk}.", reason=f"Your business record has a {fk} that your Google profile is missing, so customers cannot use it.",
                                 evidence={"check": checks.get(fk), "from": "the business record you entered"}, now=now)
            out["proposed"].append(str(a.id))
    # ---- 2. the description: because it is missing/weak, or because measured visibility is weak for terms that genuinely describe the business
    current = (snap.info.get("description") or "").strip()
    desc_check = checks.get("description")
    weak_terms = applicable_weak_terms(rank, kb, tenant, current)
    trigger = None
    if desc_check and desc_check["state"] in ("missing", "improve"):
        trigger = "optimizer:description"
    elif weak_terms:
        trigger = "rank:weak_visibility"
    if trigger is None:
        out["skipped"].append("the description is fine and no measured term calls for a change" if rank else "the description is fine (no ranking data to suggest more)")
        return out
    sup = learning.suppression(db, tenant.id, gloc.id, "description_improve", "description", now)
    if sup:
        out["skipped"].append(sup)
        return out
    if _recent_action(db, tenant.id, gloc.id, "description_improve", now):
        out["skipped"].append("a description change is already proposed, was executed recently, or was recently blocked")
        return out
    try:
        from app.services.ai import get_provider
        from app.services.ai_usage import metered

        provider = provider or metered(get_provider(), db, tenant.id, "agent_draft")
        terms_line = optimizer.search_terms_line(snap)
        if weak_terms:
            extra = ("Tracked search terms where this business was not shown in the first 10 results, and which genuinely describe it (mention naturally only if true, never repeat or stuff): "
                     + ", ".join(w["keyword"] for w in weak_terms[:4]))
            terms_line = f"{terms_line}\n{extra}" if terms_line else extra
        intel = intelligence.build(db, tenant, kb, google_location_id=gloc.id)
        text, qa = draft_description(provider, tenant, kb, intel, terms_line=terms_line)
    except AIUnavailable as exc:
        out["skipped"].append(f"the description could not be drafted ({exc.code})")
        return out
    if len(text.strip()) < MIN_AI_DESCRIPTION:
        out["skipped"].append("the drafted description was too short to be useful")
        return out
    refs = [r for r in ("description", "services") if kb.get(r)]
    evidence = {"optimizer_check": desc_check, "rank": ({"weak_terms": [{k: w[k] for k in ("keyword", "rank", "checked_at")} for w in weak_terms], "note": rank["note"]} if weak_terms else None),
                "ai": {"model": getattr(provider, "model", None), "provider": getattr(provider, "name", None), "quality": qa.score if qa else None, "checked_against": "business knowledge (services, prices, claims)"}}
    a = executor.propose(db, tenant, gloc, "description_improve", proposed=text.strip()[:750], source={"kind": "business_knowledge", "refs": refs}, trigger=trigger,
                         problem=(desc_check["detail"] if trigger == "optimizer:description" else f"{len(weak_terms)} tracked search terms that describe your business were not shown in the first 10 results."),
                         reason=("A fuller description, written only from the facts in your business knowledge, helps customers and the search terms they use."
                                 if trigger == "optimizer:description" else "The current description does not mention terms that genuinely describe your business and that you track."),
                         evidence=evidence, now=now)
    out["proposed"].append(str(a.id))
    return out


def scan_tenant(db: Session, tenant: Tenant, *, provider=None, now: datetime | None = None, v2: bool = True) -> dict:
    """Scan every connected, selected location of one business. Tenant-scoped end to end: nothing from another business is read.

    After the original description/contact scan, each location also gets the V2 scan (services, categories, contact differences; docs/LOCAL_SEO_ENGINE_V2_IMPLEMENTATION.md). It runs in its own
    savepoint: whatever it does or fails to do can never undo or break the original scan."""
    out = {"locations": 0, "proposed": 0, "recommended": 0, "superseded": 0, "skipped": []}
    for gloc in db.scalars(select(GoogleLocation).join(GoogleConnection, GoogleConnection.id == GoogleLocation.connection_id).where(
            GoogleLocation.tenant_id == tenant.id, GoogleLocation.selected.is_(True), GoogleConnection.status == GoogleConnectionStatus.active)):
        r = scan_location(db, tenant, gloc, provider=provider, now=now)
        out["locations"] += 1
        out["proposed"] += len(r["proposed"])
        out["skipped"] += r["skipped"]
        if v2:
            from app.services.agent.v2 import scan as v2_scan

            try:
                with db.begin_nested():
                    r2 = v2_scan.scan_location_v2(db, tenant, gloc, now=now)
                out["proposed"] += len(r2["proposed"])
                out["recommended"] += len(r2["recommended"])
                out["superseded"] += len(r2["superseded"])
                out["skipped"] += r2["skipped"]
            except Exception:  # noqa: BLE001 - one location's V2 scan never stops the rest, nor undoes the original scan
                log.exception("v2 scan failed for location %s", gloc.id)
                out["skipped"].append("the V2 scan could not run for one location")
    return out
