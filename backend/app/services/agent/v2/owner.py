"""Changes the OWNER asks for (a holiday, an answer about their facilities, an extra service, a service area), turned into proposals through the one action system.

Each builds the COMPLETE resulting value from what Google holds now plus the owner's entry (never a partial list), then calls `executor.propose` with the owner as the source. The proposal is then
classified by code, validated, gated (`v2/gate.py`), approved by a person and executed and verified exactly like every other change. These functions never touch Google."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models import AgentAction, GbpSnapshot, GoogleLocation, Tenant
from app.models.base import utcnow
from app.services.agent import autonomy_policy as pol
from app.services.agent import executor
from app.services.agent import knowledge as kbs
from app.services.agent.v2 import catalog as v2_catalog
from app.services.agent.v2 import discovery as disc
from app.services.agent.v2 import fields as v2f


def _info(db, gloc: GoogleLocation) -> dict:
    snap = db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gloc.id))
    if snap is None or not snap.info:
        raise executor.ActionError("FlowQR has no recent copy of this Google profile. Refresh from Google first, so nothing is replaced blindly.", 409)
    return snap.info


def _owner_source(user_id: uuid.UUID) -> dict:
    return {"kind": "owner_input", "user_id": str(user_id)}


def _propose(db, tenant, gloc, atype, fk, proposed, user_id, trigger, problem, reason, evidence, now):
    return executor.propose(db, tenant, gloc, atype, field_key=fk, proposed=proposed, source=_owner_source(user_id), trigger=trigger, problem=problem, reason=reason, evidence=evidence,
                            proposed_by="user", user_id=user_id, now=now)


def propose_special_hours(db, tenant: Tenant, gloc: GoogleLocation, *, user_id: uuid.UUID, entries: list[dict], now: datetime | None = None) -> AgentAction:
    """Add the owner's exceptional dates to the special hours already on Google. Existing entries are kept as they are; an entry for a date that is already set is a conflict the owner must resolve."""
    now = now or utcnow()
    info = _info(db, gloc)
    if info.get("special_hours_periods") is None:
        raise executor.ActionError("FlowQR has not read the special hours of this profile yet. Refresh from Google first.", 409)
    try:
        additions = v2f.canon_special_hours(entries)
    except v2f.FieldError as exc:
        raise pol.PolicyError(str(exc)) from exc
    if not additions:
        raise pol.PolicyError("Add at least one date.")
    m = disc.merge_special(info["special_hours_periods"], additions, now.date())
    if m["conflicts"]:
        raise executor.ActionError(f"Special hours are already set on Google for {', '.join(m['conflicts'])}. FlowQR does not overwrite them: change those in Google, or remove the dates from this list.", 409)
    return _propose(db, tenant, gloc, "special_hours_update", "special_hours", m["proposed"], user_id, "owner_request",
                    f"You added special hours for {', '.join(a['start'] for a in additions)}.", "Customers see your real hours on those days instead of the usual ones. Special hours already on Google stay as they are.",
                    {"added": additions, "kept": len(info["special_hours_periods"]), "from": "dates you entered"}, now)


def propose_attributes(db, tenant: Tenant, gloc: GoogleLocation, *, user_id: uuid.UUID, answers: list[dict], now: datetime | None = None) -> AgentAction:
    """`answers`: [{"name": "attributes/wi_fi", "value": true | "free_wifi" | {"set": [...], "unset": [...]} | ["https://..."]}]. The TYPE of each attribute comes from Google's own metadata for
    this business, never from the request, and an attribute Google does not offer for it is refused."""
    now = now or utcnow()
    info = _info(db, gloc)
    meta = (info.get("catalog") or {}).get("attribute_metadata")
    cur = info.get("attributes")
    if meta is None or cur is None:
        raise executor.ActionError("FlowQR has not read the attributes Google offers for this business yet. Refresh from Google first.", 409)
    built, errors = [], []
    for ans in answers:
        name = str(ans.get("name") or "")
        name = name if name.startswith("attributes/") else f"attributes/{name}"
        m = meta.get(name)
        if m is None:
            errors.append(f"{name}: Google does not offer this attribute for your business.")
            continue
        try:
            a = v2f.canon_attribute({"name": name, "type": m.get("valueType"), "value": ans.get("value")})
        except v2f.FieldError as exc:
            errors.append(str(exc))
            continue
        errors += v2f.validate_attribute_against_metadata(a, m)
        built.append(a)
    if errors:
        raise pol.PolicyError(" ".join(errors))
    if not built:
        raise pol.PolicyError("Give at least one answer.")
    merged = {a["name"]: a for a in cur}
    merged.update({a["name"]: a for a in built})
    labels = [(meta[a["name"]].get("displayName") or a["name"]) for a in built]
    return _propose(db, tenant, gloc, "attribute_change", "attributes", list(merged.values()), user_id, "owner_request",
                    f"You answered {len(built)} question{'s' if len(built) != 1 else ''} about your business: {', '.join(labels[:4])}.",
                    "Google shows these details to customers. They come only from your answers: FlowQR never guesses a facility or service.",
                    {"answers": [{"name": a["name"], "label": meta[a["name"]].get("displayName"), "value": a["value"]} for a in built], "kept": len(cur)}, now)


def propose_services(db, tenant: Tenant, gloc: GoogleLocation, *, user_id: uuid.UUID, names: list[str], now: datetime | None = None) -> AgentAction:
    """The owner adds services by name. They are matched to Google's predefined services where a name matches, otherwise added as custom services; everything already on Google is kept."""
    now = now or utcnow()
    info = _info(db, gloc)
    if info.get("service_items") is None or not info.get("primary_category"):
        raise executor.ActionError("FlowQR has not read the services of this profile yet. Refresh from Google first.", 409)
    cat_ids = [c["id"] for c in [info["primary_category"], *(info.get("additional_categories") or [])] if c]
    plan = disc.plan_services(info["service_items"], [n for n in names if n and n.strip()], v2_catalog.types_for(info.get("catalog"), cat_ids), info["primary_category"]["id"],
                              language=info.get("language_code"))
    if not plan["added"]:
        raise pol.PolicyError("Those services are already on your Google profile.")
    labels = [v2f.service_label(x, plan["type_names"]) for x in plan["added"]]
    return _propose(db, tenant, gloc, "service_update", "services", plan["proposed"], user_id, "owner_request", f"You added services: {', '.join(labels[:5])}.",
                    "Your existing services stay exactly as they are; only the ones you added are included.", {"added": labels, "kept": len(info["service_items"]), "type_names": plan["type_names"]}, now)


def propose_service_area(db, tenant: Tenant, gloc: GoogleLocation, *, user_id: uuid.UUID, places: list[dict], now: datetime | None = None) -> AgentAction:
    """The owner's chosen areas ([{name, place_id}]), keeping the business type already on Google. Only areas the owner names are used: FlowQR never widens an area to reach more searches."""
    now = now or utcnow()
    info = _info(db, gloc)
    area = info.get("service_area")
    if area is None:
        raise executor.ActionError("This profile has no service area on Google, so there is no business type to keep. Set it up in Google Business Profile first.", 409)
    proposed = {"business_type": area["business_type"], "places": places, "region": area.get("region")}
    return _propose(db, tenant, gloc, "service_area_change", "service_area", proposed, user_id, "owner_request", "You chose the areas you serve.",
                    "Customers in these areas can find you. Only the areas you chose are used.", {"areas": [p.get("name") for p in places], "was": [p["name"] for p in area.get("places", [])]}, now)


def kb_services(db, tenant: Tenant) -> list[str]:
    return list(kbs.context(db, tenant).get("services") or [])
