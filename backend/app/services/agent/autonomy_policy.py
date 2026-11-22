"""Balanced Autonomy: the ONE place that decides how much freedom FlowQR has for each kind of Google Business Profile change.

    LEVEL 1  autonomous              monitoring, analysis, and low-risk wording of the description from verified, owner-approved facts
    LEVEL 2  conditionally autonomous  hours, services, contact details, secondary categories, approved content, approved photos:
                                       only with a pre-authorisation for THAT action type AND verified source data; otherwise the owner is asked
    LEVEL 3  owner authorisation     name, primary category, address, important attributes, service area, primary phone/website, removing significant
                                       information, regulated or sensitive claims: a person, always, every time

What makes this safe:
  * The level comes from this table and the values being changed, in CODE. No request, draft or model output carries a level, and nothing here accepts one.
  * Classification can only ESCALATE (a change that removes information, replaces a primary contact or makes a regulated claim is Level 3 whatever it was
    called). It can never be lowered by the caller.
  * Level 3 can never be pre-authorised; Level 2 only per action type, by an owner, in settings; Level 1 only runs when the owner switched autonomy on.
  * A proposal without verified evidence is BLOCKED, not executed: the facts must come from the business knowledge base, the tenant record or the owner's
    own input, and must be consistent with each other.
This module is pure (no database, no Google): everything here is testable and deterministic."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date

from app.services.agent.safety import check_text, is_health
from app.services.agent.v2 import fields as v2f

DESCRIPTION_MIN, DESCRIPTION_MAX = 40, 750  # Google's limit is 750. 40 is the floor the existing approval API already enforces; the SEO engine asks for 100+.
PERMISSIONS = ("auto", "ask", "off")
SOURCE_KINDS = ("business_knowledge", "tenant_record", "owner_input", "google_profile")


class PolicyError(Exception):
    """The request itself is not acceptable (unknown action type, a level supplied by the caller...). Distinct from a proposal that is merely BLOCKED."""


@dataclass(frozen=True)
class ActionSpec:
    key: str
    level: int
    label: str
    field: str | None  # the Google field it writes; None = decided per proposal (contact) or not a profile write
    writable: bool  # can the existing Google integration write it (provider.update_location)? False = recognised and classified, but only a person can do it in Google
    rank_relevant: bool  # worth measuring ranking before/after
    sources: frozenset[str] = frozenset()
    internal: bool = False  # not a Google write at all
    person_only: bool = False  # public content (posts, photos, replies) and the V2 profile structures (services, attributes, special hours): a named person approves each one; it cannot be pre-authorised or run by policy in this release


def _s(key, level, label, field, writable, rank, *sources, internal=False, person_only=False):
    return key, ActionSpec(key, level, label, field, writable, rank, frozenset(sources), internal, person_only)


SPECS: dict[str, ActionSpec] = dict([
    # ---- Level 1: autonomous
    _s("rank_monitoring", 1, "Ranking and keyword monitoring", None, False, False, internal=True),
    _s("seo_report", 1, "SEO analysis and reporting", None, False, False, internal=True),
    _s("profile_completeness_analysis", 1, "Profile completeness analysis", None, False, False, internal=True),
    _s("internal_planning", 1, "Internal optimization planning", None, False, False, internal=True),
    _s("ranking_trend_analysis", 1, "Ranking trend analysis and alerts", None, False, False, internal=True),
    _s("description_improve", 1, "Description improvement from verified facts", "description", True, True, "business_knowledge", "owner_input"),
    _s("text_correction", 1, "Spelling, formatting or wording correction", "description", True, False, "google_profile", "owner_input"),
    _s("service_description_improve", 1, "Service description improvement from verified services", "services", False, True, "business_knowledge", "owner_input"),
    # ---- Level 2: conditionally autonomous (needs a pre-authorisation for the type, else the owner is asked)
    _s("hours_update", 2, "Regular opening hours", "hours", True, False, "owner_input"),
    _s("service_update", 2, "Services (the complete list)", "services", True, True, "business_knowledge", "owner_input", person_only=True),
    _s("special_hours_update", 2, "Special and holiday hours", "special_hours", True, False, "owner_input", person_only=True),
    _s("attribute_change", 2, "Business attributes", "attributes", True, True, "owner_input", person_only=True),
    _s("contact_update", 2, "Add a missing website or phone number", None, True, False, "tenant_record", "owner_input"),
    _s("secondary_category_update", 2, "Secondary categories (add)", "additional_categories", True, True, "owner_input"),
    _s("publish_content", 2, "Publish an approved Google Post", None, True, False, "business_knowledge", "owner_input", person_only=True),
    _s("upload_photo", 2, "Upload a genuine photo from the approved media library", None, True, False, "owner_input", person_only=True),
    _s("reply_publish", 2, "Publish an approved review reply", None, True, False, "person_approval", person_only=True),
    _s("content_edit", 2, "Edit a published Google Post", None, True, False, "person_approval", person_only=True),
    _s("content_delete", 2, "Delete a Google Post or photo", None, True, False, "person_approval", person_only=True),
    # ---- Level 3: owner authorisation, every time
    _s("business_name_change", 3, "Business name", "title", False, True, "owner_input"),
    _s("primary_category_change", 3, "Primary category", "primary_category", True, True, "owner_input"),
    _s("address_change", 3, "Address or location", "address", False, True, "owner_input"),
    _s("service_area_change", 3, "Service area", "service_area", True, True, "owner_input"),
    _s("category_set_update", 3, "Categories (primary and additional, together)", "categories", True, True, "owner_input", "business_knowledge"),
    _s("primary_contact_change", 3, "Change an existing primary phone number or website", None, True, False, "owner_input", "tenant_record"),
    _s("significant_removal", 3, "Remove significant information", None, True, False, "owner_input"),
    _s("sensitive_claim", 3, "Regulated or sensitive business claim", None, True, False, "owner_input"),
])
WRITABLE_FIELDS = {"description", "hours", "website", "phone", "additional_categories", "primary_category", "services", "special_hours", "attributes", "service_area", "categories"}
V2_FIELDS = frozenset({"services", "special_hours", "attributes", "service_area", "categories"})  # written by the V2 engine: behind the customer-write policy gate (v2/gate.py)
LABELS = {1: "Level 1: autonomous", 2: "Level 2: conditionally autonomous", 3: "Level 3: owner authorisation"}
RISK = {1: "low", 2: "medium", 3: "high"}
# Words that make a health business's profile text a regulated/sensitive claim. They are not forbidden (the owner may say them), they just need the owner.
SENSITIVE = re.compile(r"\b(cure[sd]?|heal(?:s|ed|ing)?|treat(?:s|ed|ment|ments|ing)?|diagnos\w*|prescri\w*|surger\w+|medication|clinically proven|guarantee\w*|"
                       r"approved by|certified|licensed|accredited|fda|ayush)\b", re.I)


# ---------------------------------------------------------------------------------------------------------------------------------------------
# normalising and fingerprinting values (the same functions are used when proposing, approving, executing and reading back)
# ---------------------------------------------------------------------------------------------------------------------------------------------
def norm_text(v) -> str:
    return " ".join(str(v or "").split())


def canon(field_key: str, v):
    """A comparable, canonical form of one Google field's value."""
    if field_key == "description" or field_key == "title":
        return norm_text(v)
    if field_key == "website":
        return norm_text(v).rstrip("/").lower()
    if field_key == "phone":
        digits = re.sub(r"\D", "", str(v or ""))
        return digits[-10:] if digits else ""
    if field_key == "hours":
        return sorted([str(h.get("day")), str(h.get("open")), str(h.get("close"))] for h in (v or []))
    if field_key == "additional_categories":
        return sorted({str(c.get("id") if isinstance(c, dict) else c) for c in (v or []) if c})
    if field_key == "primary_category":
        return str(v.get("id") if isinstance(v, dict) else (v or ""))
    if field_key in V2_FIELDS:
        try:
            if field_key == "services":
                return v2f.canon_services(v)
            if field_key == "special_hours":
                return v2f.canon_special_hours(v)
            if field_key == "attributes":
                return v2f.canon_attributes(v)
            if field_key == "service_area":
                return v2f.canon_service_area(v) or {}
            if field_key == "categories":
                return v2f.canon_categories(v) or {}
        except v2f.FieldError as exc:
            raise PolicyError(str(exc)) from exc
    return v


def fingerprint(v) -> str:
    return hashlib.sha256(json.dumps(v, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def field_value(details: dict | None, field_key: str):
    """The value of one field in what Google returned (provider.get_location_details), canonicalised."""
    d = details or {}
    if field_key in V2_FIELDS:  # a key that was never read is UNKNOWN (None), never "empty": an empty services list must not be mistaken for "replace everything"
        src = {"services": "service_items", "special_hours": "special_hours_periods", "attributes": "attributes", "service_area": "service_area", "categories": "primary_category"}[field_key]
        if details is None or src not in d:
            return None
        if field_key == "categories":
            return canon("categories", v2f.categories_from_details(d))
        return canon(field_key, d.get(src))
    raw = {"description": d.get("description"), "website": d.get("website"), "phone": d.get("phone"), "hours": d.get("hours"), "title": d.get("title"),
           "additional_categories": d.get("additional_categories"), "primary_category": d.get("primary_category")}.get(field_key)
    return canon(field_key, raw)


def is_empty(v) -> bool:
    return v in (None, "", [], {})


# ---------------------------------------------------------------------------------------------------------------------------------------------
# classification: escalate only, never lower
# ---------------------------------------------------------------------------------------------------------------------------------------------
@dataclass
class Decision:
    level: int
    effective_type: str
    risk: str
    label: str
    reasons: list[str] = field(default_factory=list)
    writable: bool = True
    internal: bool = False
    field_key: str | None = None


def classify(action_type: str, *, field_key: str | None = None, current=None, proposed=None, kb: dict | None = None) -> Decision:
    """Classify one proposed action. `current`/`proposed` are canonical field values (see `canon`). Raises PolicyError for an unknown type."""
    spec = SPECS.get(action_type)
    if spec is None:
        raise PolicyError(f"Unknown action type '{action_type}': nothing is allowed that the policy does not name.")
    reasons = [f"'{spec.label}' is {LABELS[spec.level]} by policy."]
    level, eff = spec.level, spec.key
    fk = spec.field or field_key
    if spec.internal:
        return Decision(1, eff, "low", spec.label, reasons, writable=False, internal=True)

    def escalate(new_type: str, why: str) -> None:
        nonlocal level, eff
        n = SPECS[new_type]
        if n.level > level or (n.level == level and new_type != eff):
            level, eff = max(level, n.level), new_type
        reasons.append(why)

    if action_type == "contact_update":
        if fk not in ("website", "phone"):
            raise PolicyError("contact_update needs field website or phone.")
        if not is_empty(current):
            escalate("primary_contact_change", f"There is already a {fk} on Google; replacing it is Level 3.")
    if action_type in ("primary_contact_change",) and fk not in ("website", "phone"):
        raise PolicyError("primary_contact_change needs field website or phone.")
    # a value of the wrong shape is a malformed request, refused here rather than crashing a comparison further down
    if fk == "hours" and any(not isinstance(v, list) or not all(isinstance(h, (list, tuple)) and len(h) == 3 for h in v) for v in (current, proposed) if v is not None and not isinstance(v, str)):
        raise PolicyError("Opening hours must be a list of [day, open, close].")
    if fk == "additional_categories" and any(not isinstance(v, list) or not all(isinstance(c, str) for c in v) for v in (current, proposed) if v is not None and not isinstance(v, str)):
        raise PolicyError("Secondary categories must be a list of category ids.")
    if fk in V2_FIELDS and not (_v2_shape(fk, current) and _v2_shape(fk, proposed)):
        raise PolicyError(f"The {fk.replace('_', ' ')} value is not in the expected shape.")
    if fk in WRITABLE_FIELDS and not is_empty(current) and is_empty(proposed):
        escalate("significant_removal", f"This would remove the {fk} that Google holds.")
    if fk == "description" and isinstance(current, str) and isinstance(proposed, str) and current and proposed and len(proposed) < 0.6 * len(current):
        escalate("significant_removal", "The new description is much shorter than the current one, so information would be removed.")
    if fk == "hours" and isinstance(current, list) and isinstance(proposed, list) and {h[0] for h in current} - {h[0] for h in proposed}:
        escalate("significant_removal", "The new hours drop a day that is currently open.")
    if fk == "additional_categories" and isinstance(current, list) and isinstance(proposed, list) and set(current) - set(proposed):
        escalate("significant_removal", "The change removes an existing secondary category (only adding is Level 2).")
    if fk == "services" and isinstance(current, list) and isinstance(proposed, list) and v2f.services_removed(current, proposed):
        escalate("significant_removal", "The new service list drops a service that is on Google today (only adding is Level 2).")
    if fk == "special_hours" and isinstance(current, list) and isinstance(proposed, list):
        today = date.today().isoformat()
        have = {_sp_key(p): p for p in proposed}
        if any(p["start"] >= today and have.get(_sp_key(p)) != p for p in current):
            escalate("significant_removal", "The change drops or alters special hours that are already set on Google.")
    if fk == "attributes" and isinstance(current, list) and isinstance(proposed, list) and {a["name"] for a in current} - {a["name"] for a in proposed}:
        escalate("significant_removal", "The change removes an attribute that is set on Google today.")
    if fk == "service_area" and isinstance(current, dict) and isinstance(proposed, dict) and current and proposed and \
            {p["place_id"] for p in current.get("places", [])} - {p["place_id"] for p in proposed.get("places", [])}:
        escalate("significant_removal", "The change removes an area you serve on Google today.")
    if fk == "categories" and isinstance(current, dict) and isinstance(proposed, dict) and current and proposed:
        if current.get("primary") != proposed.get("primary"):
            escalate("primary_category_change", "The primary category changes. That decides which searches you can appear in, so only the owner may approve it.")
        if set(current.get("additional", [])) - set(proposed.get("additional", [])):
            escalate("significant_removal", "The change removes an existing additional category.")
    if fk == "description" and isinstance(proposed, str) and kb and (kb.get("safety_profile") == "health" or is_health(kb.get("category"))) and SENSITIVE.search(proposed):
        escalate("sensitive_claim", "The text makes health or regulated claims, which only the owner may approve.")
    final = SPECS[eff]
    return Decision(level, eff, RISK[level], final.label, reasons, writable=final.writable and (fk in WRITABLE_FIELDS), field_key=fk)


def _sp_key(p: dict) -> str:
    return p["start"]


def _v2_shape(fk: str, v) -> bool:
    """A canonical V2 value has a known shape; anything else is a malformed request, refused rather than crashing a comparison."""
    if v in (None, "", [], {}) or isinstance(v, str):  # a bare string never reaches here from propose (canon refuses it first); the level of the TYPE is still reportable
        return True
    if fk in ("service_area", "categories"):
        return isinstance(v, dict)
    need = {"services": "k", "special_hours": "start", "attributes": "name"}[fk]
    return isinstance(v, list) and all(isinstance(x, dict) and need in x for x in v)


def authorization_for(decision: Decision, *, autonomy_enabled: bool, suspended: bool, permissions: dict | None) -> str:
    """Who must authorise this action: 'policy' (Level 1, autonomy on), 'preauthorized' (Level 2, the owner pre-authorised exactly this type), or 'owner'."""
    perms = permissions or {}
    t = decision.effective_type
    if decision.internal:
        return "policy"
    if decision.level >= 3 or not autonomy_enabled or suspended or SPECS[t].person_only:
        return "owner"
    mode = perms.get(t, "auto" if decision.level == 1 else "ask")
    if decision.level == 1:
        return "policy" if mode == "auto" else "owner"
    return "preauthorized" if mode == "auto" else "owner"


def permission_off(action_type: str, permissions: dict | None) -> bool:
    return (permissions or {}).get(action_type) == "off"


def validate_permissions(perms: dict) -> list[str]:
    """Problems with an owner's permission settings. Level 3 can never be 'auto'; unknown types and values are refused."""
    bad = []
    for t, mode in (perms or {}).items():
        spec = SPECS.get(t)
        if spec is None or spec.internal:
            bad.append(f"'{t}' is not an action type that can be configured.")
        elif mode not in PERMISSIONS:
            bad.append(f"'{t}': choose one of {', '.join(PERMISSIONS)}.")
        elif mode == "auto" and spec.level == 3:
            bad.append(f"'{t}' is Level 3: it always needs your authorisation and can never be pre-authorised.")
        elif mode == "auto" and spec.person_only:
            bad.append(f"'{t}' is public content: a person approves each one, so it cannot be set to run on its own.")
    return bad


# ---------------------------------------------------------------------------------------------------------------------------------------------
# evidence and fact validation
# ---------------------------------------------------------------------------------------------------------------------------------------------
def kb_facts(kb: dict, refs: list[str]) -> dict:
    return {r: kb.get(r) for r in sorted(refs)}


def facts_fingerprint(action_type: str, source: dict, kb: dict, tenant_facts: dict, proposed) -> str:
    """Fingerprint of the facts the new value claims to rest on, so that a change to those facts after approval is detectable."""
    kind = source.get("kind")
    if kind == "business_knowledge":
        return fingerprint({"kb": kb_facts(kb, list(source.get("refs") or [])), "approved": kb.get("approved_claims"), "prohibited": kb.get("prohibited_claims"),
                            "offers": kb.get("offers"), "profile": kb.get("safety_profile")})
    if kind == "tenant_record":
        return fingerprint({k: tenant_facts.get(k) for k in sorted(source.get("refs") or [])})
    if kind == "owner_input":
        return fingerprint({"owner_value": proposed, "by": source.get("user_id")})
    return fingerprint({"current": proposed})  # google_profile: the value derived from what Google holds is the fact


def _word_ok(a: str, b: str) -> bool:
    if a == b or a.lower() == b.lower():
        return True
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.8 and abs(len(a) - len(b)) <= 2


def correction_is_safe(current: str, proposed: str) -> bool:
    """A safe wording correction changes spelling, case, spacing or punctuation of existing words. It adds no new words, numbers or links."""
    a, b = norm_text(current).split(), norm_text(proposed).split()
    if len(a) != len(b) or re.findall(r"\d", " ".join(b)) != re.findall(r"\d", " ".join(a)) or re.search(r"https?://|www\.", " ".join(b), re.I):
        return False
    return all(_word_ok(x.strip(".,;:!?\"'()"), y.strip(".,;:!?\"'()")) for x, y in zip(a, b))


def description_problems(text: str, current: str, kb: dict, *, relaxed: bool = False) -> list[str]:
    """`relaxed` is for a description a PERSON typed themselves: Google's hard limits and the business's own prohibited claims still apply, the agent's minimum length does not."""
    out: list[str] = []
    t = norm_text(text)
    lo = 1 if relaxed else DESCRIPTION_MIN
    if not lo <= len(t) <= DESCRIPTION_MAX:
        out.append(f"A description must be {lo} to {DESCRIPTION_MAX} characters (this is {len(t)}).")
    if re.search(r"https?://|www\.", t, re.I):
        out.append("The description contains a link, which Google may reject.")
    if re.search(r"(\+?\d[\d \-]{8,}\d)", t):
        out.append("The description contains a phone number, which Google may reject.")
    if norm_text(current) == t:
        out.append("The proposed description is the same as the one on Google: nothing to change.")
    for v in check_text(t, kb=kb, kind="profile"):
        out.append(f"{v.message}")
    return out


def _kb_has(kb: dict, term: str) -> bool:
    """Is `term` something the owner's verified business knowledge says the business is or does? (a service, or the business category)"""
    t = v2f.key_of(term)
    if not t:
        return False
    pool = [v2f.key_of(x if isinstance(x, str) else (x.get("name") if isinstance(x, dict) else "")) for x in (kb.get("services") or [])] + [v2f.key_of(kb.get("category") or "")]
    return any(t == p or (p and (t in p or p in t)) for p in pool if p)


def v2_problems(action_type: str, fk: str, current, proposed, source: dict, kb: dict, info: dict | None) -> list[str]:
    """Problems with a V2 proposal that need no network: shape, Google's stated limits, eligibility the profile itself reports, and "every new fact traces to something verified"."""
    out: list[str] = []
    kind = (source or {}).get("kind")
    info = info or {}
    if current is None:
        return ["FlowQR has no recent read of this part of your Google profile, so it cannot tell what is there now. Refresh from Google first (nothing is replaced blindly)."]
    if fk == "services":
        if info.get("can_modify_service_list") is False:
            out.append("Google says the service list of this profile cannot be edited through the API (canModifyServiceList is false). Edit the services in Google Business Profile.")
        elif info.get("can_modify_service_list") is None:
            out.append("Google did not say whether this profile's service list can be edited, so FlowQR does not assume it can.")
        out += v2f.services_problems(proposed)
        added = v2f.services_added(current, proposed)
        if kind == "business_knowledge":
            matches = (source or {}).get("service_matches") or {}
            for it in added:
                kbname = matches.get(v2f.service_key(it))
                if not kbname or not _kb_has(kb, kbname) or v2f.key_of(kbname) not in {v2f.key_of(x) for x in kb.get("services") or []}:
                    out.append(f"'{it.get('n') or it['id']}' is not traced to a service in your business knowledge, so it will not be added.")
    elif fk == "special_hours":
        out += v2f.special_hours_problems(proposed, has_regular_hours=info.get("has_regular_hours"))
        if kind != "owner_input":
            out.append("Special hours only come from dates the owner entered; FlowQR never guesses them.")
    elif fk == "attributes":
        if kind != "owner_input":
            out.append("An attribute is only set from an answer the owner gave; FlowQR never infers it (not from competitors, not from the category).")
        if not proposed:
            out.append("No attribute was given.")
    elif fk == "service_area":
        if kind != "owner_input":
            out.append("A service area only comes from areas the owner chose; FlowQR never widens it to reach more searches.")
        out += v2f.service_area_problems(proposed or None, current or None)
    elif fk == "categories":
        out += v2f.categories_problems(proposed or None)
        if kind == "business_knowledge":
            matches = (source or {}).get("category_matches") or {}
            cur = {current.get("primary")} | set(current.get("additional", [])) if current else set()
            for cid in [proposed.get("primary")] + list(proposed.get("additional", [])):
                if cid and cid not in cur and not _kb_has(kb, matches.get(cid) or ""):
                    out.append(f"The category '{cid}' is not traced to a service or business type in your business knowledge, so it will not be added.")
    return out


def validate_proposal(action_type: str, *, field_key: str | None, current, proposed, source: dict, proposed_by: str, kb: dict, tenant_facts: dict, relaxed: bool = False,
                      info: dict | None = None) -> list[str]:
    """Why this proposal may NOT be acted on, from verified facts only. Empty = the evidence is sufficient. `current`/`proposed` are canonical values.
    Never invents anything: a missing fact is a reason to stop, not something to fill in."""
    spec = SPECS.get(action_type)
    if spec is None:
        return [f"Unknown action type '{action_type}'."]
    if spec.internal:
        return []
    problems: list[str] = []
    kind = (source or {}).get("kind")
    if kind not in spec.sources:
        problems.append(f"'{spec.label}' needs a verified source of kind {' or '.join(sorted(spec.sources))}; got '{kind}'.")
        return problems
    if kind == "owner_input" and proposed_by != "user":
        problems.append("A value cannot be attributed to the owner unless a person actually entered it.")
    fk = spec.field or field_key
    if fk in WRITABLE_FIELDS and is_empty(proposed) and action_type != "significant_removal":
        problems.append(f"No new {fk} value was given.")
    if kind == "business_knowledge":
        refs = list((source or {}).get("refs") or [])
        if not refs:
            problems.append("The source names no business-knowledge fields, so nothing supports the new value.")
        for r in refs:
            if is_empty(kb.get(r)):
                problems.append(f"The business knowledge field '{r}' is empty, so it cannot support this change.")
    if action_type == "description_improve":
        if kind == "business_knowledge" and is_empty(kb.get("description")) and is_empty(kb.get("services")):  # a description the owner typed is its own evidence
            problems.append("Insufficient evidence: the business knowledge has neither a description nor services to write from.")
        # text a PERSON typed is held to Google's limits and the business's own prohibited claims, not to the agent's minimum length (the same at proposal and at execution)
        problems += description_problems(proposed if isinstance(proposed, str) else "", current if isinstance(current, str) else "", kb, relaxed=relaxed or (kind == "owner_input" and proposed_by == "user"))
    elif action_type == "text_correction":
        if not isinstance(current, str) or not current or not isinstance(proposed, str) or not correction_is_safe(current, proposed):
            problems.append("That is not a safe correction: it adds, removes or changes words, numbers or links, not just spelling, case or punctuation.")
        elif current == proposed:
            problems.append("The corrected text is identical to the current text.")
    elif action_type in ("contact_update", "primary_contact_change") and kind == "tenant_record":
        want = canon(fk, tenant_facts.get(fk))
        if is_empty(want):
            problems.append(f"The business record has no {fk}, so there is no verified value to use.")
        elif want != proposed:
            problems.append(f"Conflicting facts: the proposed {fk} does not match the {fk} in the business record.")
    elif fk in V2_FIELDS:
        problems += v2_problems(action_type, fk, current, proposed, source or {}, kb, info)
    elif action_type == "hours_update":
        if not isinstance(proposed, list) or not proposed:
            problems.append("Hours must be a non-empty list of day, open and close times.")
        else:
            for h in proposed:
                if not (len(h) == 3 and re.fullmatch(r"\d{2}:\d{2}", h[1]) and re.fullmatch(r"\d{2}:\d{2}(\+1)?", h[2])):
                    problems.append("Each opening period needs a day and HH:MM open and close times.")
                    break
    if current is not None and proposed is not None and current == proposed and action_type not in ("description_improve", "text_correction"):
        problems.append("The proposed value is already what Google holds: nothing to change.")
    return problems
