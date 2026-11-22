"""The data behind the Local SEO dashboard: what the profile looks like, what FlowQR found, what is waiting for the owner, what was changed AND verified on Google, what failed or was blocked.

Everything here is a count or a value that exists in the database or in Google's own answers. There is no invented score, no invented total and no placeholder: where Google has not been read
yet, the area says so ("not read yet") instead of showing a number. Each fixable issue says HOW it can be fixed:

    automatic              the owner switched on, for this location and this kind of change, FlowQR making it by itself (existing Level 1-2 consent), verified afterwards
    owner_approved         FlowQR drafts the exact change and makes it once the owner approves it
    recommended_only       FlowQR drafts and explains it but does not make it: the customer-write policy gate is closed (v2/gate.py). The owner can make it in Google Business Profile
    owner_input_needed     only the owner knows (an attribute, a holiday, an area): FlowQR asks
    unavailable_via_api    Google does not let this profile's data be changed through the API (e.g. a locked service list)
    edit_in_google         FlowQR does not make this kind of change; the owner does it in Google
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentAction, GbpSnapshot, GoogleLocation, Review, Tenant
from app.models.base import utcnow
from app.services import consent as consent_svc
from app.services.agent import autonomy_policy as pol
from app.services.agent import executor, health, learning, optimizer
from app.services.agent import knowledge as kbs
from app.services.agent.v2 import catalog as v2_catalog
from app.services.agent.v2 import discovery as disc
from app.services.agent.v2 import fields as v2f
from app.services.agent.v2 import gate as v2gate
from app.services.agent.v2 import keywords as kw
from app.services.agent.v2 import present

BUCKETS = {"pending": ("pending_approval",), "recommended": ("recommended",), "in_progress": ("approved", "executing"), "verified": ("executed",),
           "failed": ("failed",), "blocked": ("blocked", "invalidated"), "closed": ("rejected", "expired", "superseded", "canceled")}
FIX_LABEL = {"automatic": "FlowQR makes it (you allowed this)", "owner_approved": "FlowQR makes it after you approve", "recommended_only": "Shown to you: make it in Google",
             "owner_input_needed": "We need your answer", "unavailable_via_api": "Google does not allow this through FlowQR", "edit_in_google": "Edit it in Google Business Profile"}


def fix_mode(db: Session, tenant: Tenant, gloc: GoogleLocation, action_type: str, fk: str | None = None) -> str:
    """How a change of this kind would be made on this location, from the real policy, settings, consent and gate (not from the screen)."""
    spec = pol.SPECS[action_type]
    if not spec.writable:
        return "edit_in_google"
    g = v2gate.status_for(gloc, spec.field or fk)
    if g["applies"] and not g["allowed"]:
        return "recommended_only"
    if spec.person_only or spec.level >= 3:
        return "owner_approved"
    s = executor.get_settings(db, tenant.id)
    dec = pol.Decision(spec.level, spec.key, pol.RISK[spec.level], spec.label)
    if pol.authorization_for(dec, autonomy_enabled=s.autonomy_enabled, suspended=bool(s.autonomy_suspended_at), permissions=s.autonomy_permissions) in ("policy", "preauthorized") \
            and consent_svc.has_active(db, tenant.id, gloc.id, spec.key):
        return "automatic"
    return "owner_approved"


def _area(key, label, state, summary, mode=None, **extra) -> dict:
    return {"key": key, "label": label, "state": state, "summary": summary, "fix": ({"mode": mode, "label": FIX_LABEL[mode]} if mode else None), **extra}


def _action_row(db: Session, a: AgentAction) -> dict:
    out = executor.action_out(db, a)
    out["diff"] = present.describe(a.field_key, out["before"], out["after"], a.evidence)
    out["executed_note"] = ("Changed on Google and confirmed by reading the profile back." if a.status == "executed" and a.verified_at else None)
    return out


def _location(db: Session, tenant: Tenant, gloc: GoogleLocation, now: datetime) -> dict:
    snap = db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gloc.id))
    info = snap.info if snap is not None and snap.info else None
    kb = kbs.context(db, tenant)
    gate = v2gate.check(gloc)
    acts = list(db.scalars(select(AgentAction).where(AgentAction.google_location_id == gloc.id, AgentAction.subject_type.is_(None)).order_by(AgentAction.updated_at.desc()).limit(80)))
    buckets = {name: [_action_row(db, a) for a in acts if a.status in sts] for name, sts in BUCKETS.items()}
    loc = {"google_location_id": str(gloc.id), "title": gloc.title, "profile_read": info is not None, "fetched_at": snap.fetched_at if snap else None, "snapshot_error": snap.error if snap else None,
           "gate": {"allowed": gate["allowed"], "test_profile": gate["test_profile"], "customer_writes": gate["customer_writes"], "reason": gate["reason"]}}
    if info is None:
        loc.update({"areas": [], "actions": buckets, "opportunities": [], "performance": None, "checks": [],
                    "note": "FlowQR has not read this Google profile yet, so nothing is scored and nothing is proposed. Refresh from Google."})
        return loc
    catalog = info.get("catalog") or {}
    rank = learning.rank_summary(db, gloc.id)
    checks = optimizer.checks(snap, kb, rank=rank)
    areas: list[dict] = []
    # ---- description
    d = next((c for c in checks if c["key"] == "description"), None)
    if d:
        areas.append(_area("description", "Description", d["state"], d["detail"], None if d["state"] == "ok" else fix_mode(db, tenant, gloc, "description_improve")))
    # ---- categories
    cats = v2f.categories_from_details(info)
    cand = (catalog.get("categories") or {}).get("candidates")
    if cats is None:
        areas.append(_area("categories", "Categories", "missing", "No main category is set on Google.", "owner_input_needed"))
    elif cand is None:
        areas.append(_area("categories", "Categories", "unknown", f"{len(cats['additional'])} additional categories. Google's category list has not been read yet.", None))
    else:
        ca = disc.assess_categories(cats, kb, cand)
        rec = ca["recommendations"]
        areas.append(_area("categories", "Categories", "improve" if rec else "ok",
                           (f"Categories your own services support and that are not set: {', '.join(r['name'] for r in rec)}." if rec else f"Main category plus {len(cats['additional'])} more."),
                           fix_mode(db, tenant, gloc, "category_set_update") if rec else None, recommendations=rec, note=(ca["primary"] or {}).get("note")))
    # ---- services
    elig = disc.service_eligibility(info)
    items = info.get("service_items")
    if items is None:
        areas.append(_area("services", "Services", "unknown", "Google's service list has not been read yet.", None))
    elif elig["editable"] is not True:
        cov = disc.coverage(items, kb.get("services") or [], None)
        areas.append(_area("services", "Services", "improve" if cov["missing"] else "ok", elig["reason"] + (f" Not on Google yet: {', '.join(cov['missing'][:4])}." if cov["missing"] else ""),
                           "unavailable_via_api" if cov["missing"] else None, coverage=cov))
    else:
        cat_ids = [c["id"] for c in [info.get("primary_category"), *(info.get("additional_categories") or [])] if c]
        names = {t["id"]: t["name"] for t in v2_catalog.types_for(catalog, cat_ids)}
        cov = disc.coverage(items, kb.get("services") or [], names)
        if not kb.get("services"):
            areas.append(_area("services", "Services", "unknown", f"{len(items)} on Google. Add your services to your Business Brain so FlowQR can compare them.", "owner_input_needed", coverage=cov))
        else:
            areas.append(_area("services", "Services", "improve" if cov["missing"] else "ok",
                               (f"{cov['on_google']} of the {cov['verified']} services you listed are on Google. Missing: {', '.join(cov['missing'][:4])}{'…' if len(cov['missing']) > 4 else ''}."
                                if cov["missing"] else f"All {cov['verified']} services you listed are on Google."), fix_mode(db, tenant, gloc, "service_update") if cov["missing"] else None, coverage=cov))
    # ---- attributes
    meta, cur_attrs = catalog.get("attribute_metadata"), info.get("attributes")
    if meta is None or cur_attrs is None:
        areas.append(_area("attributes", "Attributes", "unknown", "Google's attributes for your business have not been read yet.", None))
    else:
        aa = disc.assess_attributes(meta, cur_attrs)
        areas.append(_area("attributes", "Attributes", "improve" if aa["unset"] else "ok",
                           (f"{aa['set']} of {aa['total']} attributes Google offers for your business are answered. {len(aa['unset'])} need your answer." if aa["unset"] else "Every attribute Google offers is answered."),
                           "owner_input_needed" if aa["unset"] else None, assessment={k: aa[k] for k in ("total", "set", "percent")}, questions=aa["unset"][:40]))
    # ---- regular hours
    ha = disc.assess_hours(info.get("hours"), kb.get("hours"))
    h_state = {"ok": "ok", "missing": "missing", "problem": "improve"}[ha["state"]]
    if ha["comparison"] and not ha["comparison"]["same"]:
        h_state = "improve"
    h_summary = (ha["problems"][0] if ha["problems"] else ("Hours on Google differ from your business record: " + "; ".join(ha["comparison"]["differences"][:2])) if ha["comparison"] and not ha["comparison"]["same"]
                 else f"Set for {ha['days_open']} day{'s' if ha['days_open'] != 1 else ''} a week.")
    areas.append(_area("hours", "Opening hours", h_state, h_summary, None if h_state == "ok" else ("owner_input_needed" if ha["state"] == "missing" else "owner_approved"),
                       assessment={"days_open": ha["days_open"], "problems": ha["problems"], "comparison": ha["comparison"]}))
    # ---- special hours
    sp = info.get("special_hours_periods")
    if sp is None:
        areas.append(_area("special_hours", "Holiday hours", "unknown", "Special hours have not been read yet.", None))
    else:
        sa = disc.assess_special(sp, bool(info.get("has_regular_hours")), now.date())
        if sa["needs_regular_hours_first"]:
            areas.append(_area("special_hours", "Holiday hours", "improve", "Set regular opening hours first: Google does not accept special hours without them.", "owner_input_needed", assessment=sa))
        elif sa["gaps"]:
            g0 = sa["gaps"][0]
            areas.append(_area("special_hours", "Holiday hours", "improve", f"{g0['name']} ({g0['date']}) has no special hours. Are you closed or open different hours?",
                               "owner_input_needed", assessment=sa))
        else:
            areas.append(_area("special_hours", "Holiday hours", "ok", f"{sa['upcoming_set']} upcoming special-hours dates are set." if sa["upcoming_set"] else "No fixed-date holiday in the next 60 days needs hours.", None, assessment=sa))
    # ---- contacts
    ct = disc.assess_contacts(info, tenant.phone, tenant.website)
    bad = [k for k, v in ct.items() if v["state"] in ("fill", "differs", "missing_everywhere", "record_invalid")]
    areas.append(_area("contacts", "Phone and website", "improve" if bad else "ok",
                       ("; ".join({"fill": f"{k} is missing on Google but is in your record", "differs": f"{k} on Google differs from your record", "missing_everywhere": f"no {k} anywhere yet",
                                   "record_invalid": f"the {k} in your record is not valid"}[ct[k]["state"]] for k in bad).capitalize() + ".") if bad else "Phone and website match your business record.",
                       None if not bad else ("owner_approved" if any(ct[k]["state"] in ("fill", "differs") for k in bad) else "owner_input_needed"), detail=ct))
    # ---- service area
    sv = disc.assess_service_area(info)
    areas.append(_area("service_area", "Service area", sv["state"] if sv["state"] != "unknown" else "unknown", sv["note"] or (f"Serving: {', '.join(sv['areas'][:5])}." if sv["areas"] else "Customers visit your address."),
                       "owner_input_needed" if sv["state"] == "missing" else None, kind=sv["kind"]))
    # ---- name, photos, posts: from the existing checks (detection only; their own flows stay as they are)
    for key, label in (("name", "Business name"), ("photos", "Photos"), ("posts", "Google posts")):
        c = next((x for x in checks if x["key"] == key), None)
        if c:
            areas.append(_area(key, label, c["state"], c["detail"], None if c["state"] == "ok" else ("edit_in_google" if key == "name" else "owner_approved"), href=c.get("href")))
    gc = sorted(v2_catalog.google_changed_fields(catalog))
    # ---- opportunities (suggestions to track; no invented volume or difficulty)
    tracked = [k.keyword for k in learning.tracked(db, gloc.id)]
    texts = [(t or "").lower() for t in db.scalars(select(Review.text).where(Review.google_location_id == gloc.id, Review.text.is_not(None)).order_by(Review.review_created_at.desc()).limit(300))]
    mentioned = [s for s in (kb.get("services") or []) if isinstance(s, str) and any(v2f.key_of(s) in v2f.key_of(t) for t in texts)]
    opps = kw.discover(services=[s for s in (kb.get("services") or []) if isinstance(s, str)], category=kb.get("category"),
                       localities=kw.localities_from_address(gloc.address or tenant.address, disc.assess_service_area(info)["areas"]), google_terms=(snap.performance or {}).get("keywords"), tracked=tracked,
                       description=info.get("description"), review_topics=mentioned)
    perf = snap.performance or {}
    open_n = sum(1 for a in areas if a["state"] in ("missing", "improve"))
    loc.update({
        "areas": areas, "actions": buckets, "opportunities": opps, "google_changed": gc, "checks": [{"key": c["key"], "state": c["state"]} for c in checks],
        "completeness": {"known_areas": len([a for a in areas if a["state"] != "unknown"]), "ok_areas": len([a for a in areas if a["state"] == "ok"]), "total_areas": len(areas)},
        "issues_detected": open_n, "performance": ({"current": perf.get("current"), "previous": perf.get("previous"), "from": perf.get("from"), "to": perf.get("to"), "metrics": perf.get("metrics"),
                                                    "keywords": (perf.get("keywords") or [])[:8]} if perf else None),
        "rank_note": (rank or {}).get("note"),
    })
    return loc


def build(db: Session, tenant: Tenant, glocs: list[GoogleLocation], *, now: datetime | None = None) -> dict:
    now = now or utcnow()
    locs = [_location(db, tenant, g, now) for g in glocs]
    hs = health.compute(db, tenant, location_ids=frozenset(g.location_id for g in glocs if g.location_id) or None, now=now) if glocs else None

    def n(bucket):
        return sum(len(x["actions"][bucket]) for x in locs)
    verified_90 = sum(1 for x in locs for a in x["actions"]["verified"] if a.get("verified_at") and a["verified_at"] >= now - timedelta(days=90))
    return {
        "generated_at": now, "locations": locs,
        "totals": {"issues_detected": sum(x.get("issues_detected", 0) for x in locs), "optimizations_available": n("recommended") + n("pending"), "pending_approvals": n("pending"),
                   "recommended_only": n("recommended"), "in_progress": n("in_progress"), "verified_on_google": n("verified"), "verified_last_90_days": verified_90,
                   "failed": n("failed"), "blocked": n("blocked")},
        "health": ({"score": hs.get("score"), "formula": hs.get("formula"), "components": hs.get("components")} if hs else None),
        "how_it_works": "FlowQR finds issues, drafts the exact fix, and shows you BEFORE and AFTER. A change counts as done only after Google's profile is read back and shows it.",
        "gate_note": v2gate.CLOSED_REASON,
    }
