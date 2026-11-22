"""The V2 optimisation scan for one location. It runs INSIDE the existing six-hourly `seo_engine.scan_location` (no second engine, no second schedule) and works only from the stored profile
snapshot, so it makes no Google call.

    1. lock       one scan per location at a time (a transaction-scoped Postgres advisory lock): two simultaneous scans cannot both propose, so they cannot propose conflicting changes
    2. reconcile  a drafted change whose premise is gone is SUPERSEDED: the owner changed the field elsewhere, or Google did. Nothing is ever pushed over an edit
    3. google     fields Google reports as differing from the merchant's data (diffMask) are not proposed over, and never reverted (Google's policy: no automatic revert of Google's changes)
    4. propose    services (complete list), categories (set), and a contact that differs from the business record: each with its evidence, through `executor.propose` (the ONE action system)
    5. record     one audit row: what was seen, proposed and skipped

Re-proposing: a change the owner rejected is not proposed again with the same value, ever, and not with a different value for 14 days (learning.suppression); the same change against the same
Google value is never duplicated (the idempotency key)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AgentAction, GbpSnapshot, GoogleLocation, Tenant
from app.models.base import utcnow
from app.services.agent import autonomy_policy as pol
from app.services.agent import executor, history, learning
from app.services.agent import knowledge as kbs
from app.services.agent.v2 import catalog as v2_catalog
from app.services.agent.v2 import discovery as disc
from app.services.agent.v2 import fields as v2f
from app.services.audit import audit

log = logging.getLogger("flowqr.v2scan")
OPEN_STATUSES = ("recommended", "pending_approval", "approved")
REJECTION_MEMORY = timedelta(days=180)


def _lock(db: Session, gloc: GoogleLocation) -> bool:
    """True if this transaction now holds the location's scan lock (released at commit/rollback)."""
    return bool(db.scalar(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"seo-v2-scan:{gloc.id}"}))


def reconcile(db: Session, gloc: GoogleLocation, info: dict, now: datetime) -> list[str]:
    """Supersede V2 drafts whose base value no longer matches what Google holds. Returns the ids superseded."""
    out = []
    for a in db.scalars(select(AgentAction).where(AgentAction.google_location_id == gloc.id, AgentAction.status.in_(OPEN_STATUSES), AgentAction.subject_type.is_(None),
                                                  AgentAction.field_key.in_(sorted(pol.V2_FIELDS))).with_for_update(skip_locked=True)):
        live = pol.field_value(info, a.field_key)
        if live is None or pol.fingerprint(live) == a.base_fingerprint:
            continue
        applied = live == a.proposed_value.get("canonical")
        why = ("Google already shows exactly this change (you or Google made it)." if applied else "The profile changed after this was drafted (you or Google edited it), so it no longer fits.")
        ap = executor._valid_approval(db, a)
        if ap is not None:
            ap.invalidated_at, ap.invalidated_reason = now, "superseded: the profile changed"
        a.status, a.last_error = "superseded", why
        history.record(db, a, "superseded", actor="system", now=now, data={"reason": why, "was": "profile_changed", "live": live})
        out.append(str(a.id))
    return out


def _rejected_before(db: Session, gloc: GoogleLocation, action_type: str, fk: str, value_hash: str, now: datetime) -> bool:
    return db.scalar(select(AgentAction.id).where(AgentAction.google_location_id == gloc.id, AgentAction.action_type == action_type, AgentAction.field_key == fk,
                                                  AgentAction.status == "rejected", AgentAction.value_hash == value_hash, AgentAction.updated_at >= now - REJECTION_MEMORY).limit(1)) is not None


def _propose(db, tenant, gloc, out, now, atype, fk, proposed, source, trigger, problem, reason, evidence):
    prop_c = pol.canon(fk, proposed)
    if _rejected_before(db, gloc, atype, fk, pol.fingerprint(prop_c), now):
        out["skipped"].append(f"{fk}: you rejected this exact change before, so it is not proposed again")
        return None
    sup = learning.suppression(db, tenant.id, gloc.id, atype, fk, now)
    if sup:
        out["skipped"].append(f"{fk}: {sup}")
        return None
    a = executor.propose(db, tenant, gloc, atype, field_key=fk, proposed=proposed, source=source, trigger=trigger, problem=problem, reason=reason, evidence=evidence, now=now)
    (out["recommended"] if a.status == "recommended" else out["proposed"]).append(str(a.id))
    return a


def scan_location_v2(db: Session, tenant: Tenant, gloc: GoogleLocation, *, now: datetime | None = None) -> dict:
    now = now or utcnow()
    out: dict = {"proposed": [], "recommended": [], "superseded": [], "skipped": [], "detected": {}}
    if not _lock(db, gloc):
        out["skipped"].append("another scan of this location is running")
        return out
    snap = db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gloc.id))
    info = snap.info if snap is not None else None
    if not info:
        out["skipped"].append("no recent copy of the Google profile")
        return out
    out["superseded"] = reconcile(db, gloc, info, now)
    catalog = info.get("catalog") or {}
    google_changed = v2_catalog.google_changed_fields(catalog)
    if google_changed:
        out["detected"]["google_changed"] = sorted(google_changed)  # shown to the owner; never reverted, and nothing is proposed over these fields this run
    kb = kbs.context(db, tenant)

    # ---- services: the COMPLETE list (what is on Google + verified services that are missing)
    elig = disc.service_eligibility(info)
    if elig["editable"] is not True:
        out["detected"]["services"] = {"editable": elig["editable"], "reason": elig["reason"]}
    elif "services" in google_changed:
        out["skipped"].append("services: Google has changed this part of the profile; FlowQR does not propose over it")
    elif kb.get("services") and info.get("service_items") is not None and info.get("primary_category"):
        cat_ids = [c["id"] for c in [info.get("primary_category"), *(info.get("additional_categories") or [])] if c]
        plan = disc.plan_services(info["service_items"], kb["services"], v2_catalog.types_for(catalog, cat_ids), info["primary_category"]["id"], language=info.get("language_code"))
        out["detected"]["services"] = {"editable": True, "coverage": plan["coverage"]}
        if plan["added"]:
            labels = [v2f.service_label(x, plan["type_names"]) for x in plan["added"]]
            _propose(db, tenant, gloc, out, now, "service_update", "services", plan["proposed"],
                     {"kind": "business_knowledge", "refs": ["services"], "service_matches": plan["service_matches"]}, "optimizer:services",
                     f"{len(labels)} of the services you listed are not on your Google profile: {', '.join(labels[:5])}{'…' if len(labels) > 5 else ''}.",
                     "Customers and Google read your service list to decide whether you offer what they search for. Your existing services stay exactly as they are; only these verified ones are added.",
                     {"added": labels, "kept": len(info["service_items"]), "coverage": plan["coverage"], "type_names": plan["type_names"], "unmatched": plan["unmatched"],
                      "from": "the services in your Business Brain"})
    elif not kb.get("services"):
        out["skipped"].append("services: no services in your Business Brain to compare with")

    # ---- categories: a SET (primary + additional together), evidenced, small
    cats = v2f.categories_from_details(info)
    cand = (catalog.get("categories") or {}).get("candidates")
    if "categories" in google_changed:
        out["skipped"].append("categories: Google has changed this part of the profile; FlowQR does not propose over it")
    elif cats and cand:
        ca = disc.assess_categories(cats, kb, cand)
        out["detected"]["categories"] = {"additional": ca["additional_count"], "recommended": [r["name"] for r in ca["recommendations"]]}
        if ca["proposed"]:
            names = ", ".join(r["name"] for r in ca["recommendations"])
            _propose(db, tenant, gloc, out, now, "category_set_update", "categories", ca["proposed"],
                     {"kind": "business_knowledge", "refs": ["services", "category"], "category_matches": ca["category_matches"]}, "optimizer:categories",
                     f"Google offers categories that describe what you do and that are not on your profile: {names}.",
                     "Extra categories that genuinely describe your business let Google match you to more of the right searches. Your main category and existing categories are kept. FlowQR only suggests a category your own services support.",
                     {"recommendations": ca["recommendations"], "primary_kept": cats["primary"], "note": "Competitor categories are not used as a reason: a competitor having a category does not mean you qualify for it."})

    # ---- contacts: a DIFFERENT value is flagged and drafted for the owner (replacing a working contact is always the owner's decision)
    cont = disc.assess_contacts(info, tenant.phone, tenant.website)
    out["detected"]["contacts"] = {k: v["state"] for k, v in cont.items()}
    for key in ("website", "phone"):
        if cont[key]["state"] == "differs" and key not in google_changed:
            _propose(db, tenant, gloc, out, now, "primary_contact_change", key, cont[key]["record"], {"kind": "tenant_record", "refs": [key]}, f"optimizer:{key}_differs",
                     f"Your Google profile shows a different {key} from the one in your business record.",
                     f"Customers should see one correct {key} everywhere. FlowQR never replaces a working {key} on its own: you decide which one is right.",
                     {"google": cont[key]["google"], "record": cont[key]["record"], "from": "the business record you entered"})
    audit(db, action="seo.v2_scan", tenant_id=tenant.id, entity_type="google_location", entity_id=gloc.id,
          meta={"proposed": len(out["proposed"]), "recommended": len(out["recommended"]), "superseded": len(out["superseded"]), "skipped": out["skipped"][:10],
                "google_changed": sorted(google_changed)})
    return out
