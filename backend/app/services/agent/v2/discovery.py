"""Deterministic discovery: what is missing, wrong or improvable on a profile, and the exact change that would fix it. PURE (no DB, no network): the caller passes in what Google and the
business record say, and gets back plain data. Nothing here invents a fact: every drafted value traces to something the owner verified (their business knowledge or an answer they gave),
and where Google needs a fact only the owner has (an attribute, a holiday, an area), the result is a QUESTION for the owner, never a guessed value.

    plan_services     complete service list = what is on Google today + verified services that are missing (never a partial list, never a removal)
    assess_categories primary-category check and a small, evidenced set of additional categories (competitor categories are supporting evidence only)
    assess_attributes which of Google's attributes for this business are not set yet, as questions (no value is ever proposed from a guess)
    assess_hours      regular-hours problems (missing days, split periods, after-midnight, overlaps) and a comparison with hours the owner wrote down, when they can be read exactly
    assess_special    upcoming-holiday gaps (fixed-date public holidays only; movable festivals are the owner's to enter)
    assess_service_area, assess_contacts
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from app.services.agent.v2 import fields as v2f

DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
SHORT = {"mon": "MONDAY", "tue": "TUESDAY", "tues": "TUESDAY", "wed": "WEDNESDAY", "thu": "THURSDAY", "thur": "THURSDAY", "thurs": "THURSDAY", "fri": "FRIDAY", "sat": "SATURDAY", "sun": "SUNDAY"}
MAX_ADDITIONAL_RECOMMENDED = 3  # the engine suggests at most this many additions in one go; adding categories "to include more keywords" is exactly what it must not do
# Fixed-date public holidays in India that many local businesses close for. Movable festivals (Diwali, Holi, Eid...) change every year and are deliberately NOT listed: the owner enters them.
FIXED_HOLIDAYS_IN = [((1, 1), "New Year's Day"), ((1, 26), "Republic Day"), ((8, 15), "Independence Day"), ((10, 2), "Gandhi Jayanti"), ((12, 25), "Christmas Day")]


# ================================================================================================================================================
# services
# ================================================================================================================================================
def plan_services(current: list[dict], kb_services: list[str], service_types: list[dict], primary_category_id: str | None, *, language: str | None = None) -> dict:
    """The COMPLETE list to propose, built from what is on Google now plus verified services that are missing.

    `service_types` are Google's predefined services for the profile's category ([{id, name}]). A verified service that matches one by name becomes a structured item; one that does not
    becomes a custom (free-form) item under the primary category. Nothing is removed, nothing on Google is edited, and a service already there (matched by id or name) is never added again."""
    have_ids = {x["id"] for x in current if x["k"] == "s"}
    have_names = {v2f.key_of(x["n"]) for x in current if x["k"] == "c"}
    type_by_name = {v2f.key_of(t["name"]): t for t in service_types if t.get("id") and t.get("name")}
    type_names = {t["id"]: t["name"] for t in service_types if t.get("id") and t.get("name")}
    # a predefined service Google already lists under its display name also counts as present
    have_names |= {v2f.key_of(type_names.get(i, "")) for i in have_ids}
    added: list[dict] = []
    matches: dict[str, str] = {}
    unmatched: list[str] = []
    for name in kb_services:
        nm = v2f.norm(name if isinstance(name, str) else (name.get("name") if isinstance(name, dict) else ""))
        k = v2f.key_of(nm)
        if not k or k in have_names:
            continue
        t = type_by_name.get(k)
        if t is not None:
            if t["id"] in have_ids:
                continue
            item = {"k": "s", "id": t["id"]}
        elif primary_category_id:
            item = {"k": "c", "n": nm[: v2f.FREE_NAME_MAX], "c": primary_category_id, **({"l": language} if language else {})}
        else:
            unmatched.append(nm)
            continue
        key = v2f.service_key(item)
        if key in matches:
            continue
        added.append(item)
        matches[key] = nm
        have_names.add(k)
    proposed = v2f.canon_services(list(current) + added)
    return {"proposed": proposed, "added": added, "service_matches": matches, "unmatched": unmatched, "type_names": type_names,
            "removed": [], "coverage": coverage(current, kb_services, type_names)}


def coverage(current: list[dict], kb_services: list[str], type_names: dict | None = None) -> dict:
    """How many of the owner's verified services are on Google: {verified, on_google, missing[]}. Verified is what the owner wrote in their business knowledge."""
    names = {v2f.key_of(v2f.service_label(x, type_names)) for x in current}
    kb = [v2f.norm(x if isinstance(x, str) else (x.get("name") if isinstance(x, dict) else "")) for x in kb_services]
    kb = [x for x in kb if x]
    missing = [x for x in kb if v2f.key_of(x) not in names]
    return {"verified": len(kb), "on_google": len(kb) - len(missing), "missing": missing}


def service_eligibility(info: dict | None) -> dict:
    """{"editable": bool|None, "reason"}: whether the profile's service list can be edited through the API at all."""
    flag = (info or {}).get("can_modify_service_list")
    if flag is False:
        return {"editable": False, "reason": "Google says this profile's service list cannot be edited through the API. Edit it in Google Business Profile."}
    if flag is None:
        return {"editable": None, "reason": "Google did not say whether this service list can be edited, so FlowQR does not assume it can."}
    return {"editable": True, "reason": None}


# ================================================================================================================================================
# categories
# ================================================================================================================================================
def _tokens(s: str) -> set[str]:
    return {t for t in v2f.key_of(s).split() if len(t) > 2}


def assess_categories(current: dict | None, kb: dict, candidates: list[dict], competitor_categories: list[str] | None = None) -> dict:
    """`current` {primary, additional} (ids); `candidates` are Google categories found by searching the owner's own words ([{id, name, matched_term}]).

    A category is recommended only if (1) the owner's verified business knowledge supports it (a verified service or the business type contains/matches its name), (2) it is not already set,
    and (3) it fits the cap. Competitor categories are listed as supporting evidence, never as the reason, and never make a category eligible by themselves."""
    cur = current or {"primary": None, "additional": []}
    have = {cur["primary"], *cur["additional"]}
    verified_terms = [v2f.norm(x if isinstance(x, str) else (x.get("name") if isinstance(x, dict) else "")) for x in (kb.get("services") or [])] + ([v2f.norm(kb["category"])] if kb.get("category") else [])
    comp = {v2f.key_of(c) for c in (competitor_categories or [])}
    recs, matches = [], {}
    for c in candidates:
        if not c.get("id") or c["id"] in have:
            continue
        name_t = _tokens(c["name"])
        support = next((t for t in verified_terms if t and (_tokens(t) & name_t) and (name_t <= _tokens(t) | {"clinic", "center", "centre", "shop", "store", "service", "services"} or v2f.key_of(c["name"]) in v2f.key_of(t) or v2f.key_of(t) in v2f.key_of(c["name"]))), None)
        if not support:
            continue
        recs.append({"id": c["id"], "name": c["name"], "because": f"you list \"{support}\"", "competitors_also_use": v2f.key_of(c["name"]) in comp, "matched_term": support})
        matches[c["id"]] = support
    recs = recs[:MAX_ADDITIONAL_RECOMMENDED]
    room = v2f.ADDITIONAL_CATEGORIES_MAX - len(cur["additional"])
    recs = recs[: max(0, room)]
    primary_note = None
    if cur["primary"] and kb.get("category"):
        pn = next((c for c in candidates if c.get("id") == cur["primary"]), None)
        primary_note = {"google_primary": (pn or {}).get("name") or cur["primary"], "business_type": kb["category"],
                        "note": "FlowQR never changes your main category by itself: it decides which searches you can appear in. If it looks wrong, review it with the owner."}
    proposed = None
    if recs and cur["primary"]:
        proposed = v2f.canon_categories({"primary": cur["primary"], "additional": [*cur["additional"], *[r["id"] for r in recs]]})
    return {"recommendations": recs, "category_matches": matches, "proposed": proposed, "primary": primary_note, "additional_count": len(cur["additional"]),
            "has_primary": bool(cur["primary"])}


# ================================================================================================================================================
# attributes
# ================================================================================================================================================
def assess_attributes(metadata: dict, current: list[dict]) -> dict:
    """Which of Google's attributes for this business have no answer yet. These are QUESTIONS for the owner (yes/no, or one of Google's values): FlowQR never proposes an answer."""
    cur = {a["name"] for a in current}
    unset, deprecated = [], 0
    for name, m in sorted(metadata.items()):
        if m.get("deprecated"):
            deprecated += 1
            continue
        if name in cur:
            continue
        unset.append({"name": name, "label": m.get("displayName") or name, "group": m.get("groupDisplayName"), "type": m.get("valueType"), "repeatable": bool(m.get("repeatable")),
                      "choices": [{"value": (vm or {}).get("value"), "label": (vm or {}).get("displayName")} for vm in m.get("valueMetadata") or []]})
    total = len([1 for m in metadata.values() if not m.get("deprecated")])
    set_ct = len([n for n in cur if n in metadata and not metadata[n].get("deprecated")])
    return {"total": total, "set": set_ct, "unset": unset, "deprecated_skipped": deprecated, "percent": round(100 * set_ct / total) if total else None}


# ================================================================================================================================================
# regular hours
# ================================================================================================================================================
def _hm(t: str) -> int:
    t = t.split("+")[0]
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def hours_problems(hours: list) -> list[str]:
    """Problems in a weekly schedule given as [[day, open, close], ...] or [{"day","open","close"}]. Several periods on one day (split shifts) are fine; overlaps are not."""
    rows = [(h["day"], h["open"], h["close"]) if isinstance(h, dict) else tuple(h) for h in hours or []]
    out: list[str] = []
    by_day: dict[str, list[tuple[int, int]]] = {}
    for day, o, c in rows:
        if day not in DAYS:
            out.append(f"'{day}' is not a day of the week.")
            continue
        try:
            om, cm = _hm(o), _hm(c)
        except ValueError:
            out.append(f"{day.title()}: '{o}' to '{c}' is not a valid time range.")
            continue
        after_midnight = c.endswith("+1")
        end = cm + (1440 if after_midnight else 0)
        if om >= end:
            out.append(f"{day.title()}: it closes ({c}) before it opens ({o}). If it closes after midnight, write the close time as {c.split('+')[0]}+1.")
            continue
        by_day.setdefault(day, []).append((om, end))
    for day, spans in by_day.items():
        spans.sort()
        for (a1, b1), (a2, b2) in zip(spans, spans[1:]):
            if a2 < b1:
                out.append(f"{day.title()}: two opening periods overlap.")
                break
    return out


_DAY_RANGE = re.compile(r"(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*(?:\s*(?:-|to|–)\s*(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*)?", re.I)
_TIME_RANGE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:-|to|–)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)


def parse_written_hours(text: str) -> list[list[str]] | None:
    """Read hours the owner wrote down ("Mon-Sat 9am-6pm; Sun closed") into [[day, open, close]]. Returns None unless EVERY clause is understood exactly: a hour that cannot be read with
    certainty is never guessed, so no comparison is made."""
    if not text or not text.strip():
        return None
    out: list[list[str]] = []
    for clause in re.split(r"[;\n]|,(?=\s*(?:mon|tue|wed|thu|fri|sat|sun))", text.strip(), flags=re.I):
        clause = clause.strip()
        if not clause:
            continue
        dm = _DAY_RANGE.match(clause)
        if not dm:
            return None
        rest = clause[dm.end():].strip(" :")
        d1 = SHORT[dm.group(1).lower()]
        d2 = SHORT[dm.group(2).lower()] if dm.group(2) else d1
        i1, i2 = DAYS.index(d1), DAYS.index(d2)
        days = DAYS[i1:i2 + 1] if i1 <= i2 else DAYS[i1:] + DAYS[:i2 + 1]
        if re.fullmatch(r"closed", rest, re.I):
            continue
        tm = _TIME_RANGE.fullmatch(rest)
        if not tm:
            return None
        h1, m1, p1, h2, m2, p2 = tm.groups()
        p1 = (p1 or p2 or "").lower()
        p2 = (p2 or p1 or "").lower()

        def to24(h, m, p):
            h = int(h)
            if p == "pm" and h < 12:
                h += 12
            if p == "am" and h == 12:
                h = 0
            return f"{h:02d}:{int(m or 0):02d}"
        if not p1 and int(h2) <= 12:
            return None  # no am/pm and no 24-hour evidence ("9-6", "10-2"): ambiguous, never guessed
        o, c = to24(h1, m1, p1), to24(h2, m2, p2)
        for d in days:
            out.append([d, o, c])
    return sorted(out) or None


def assess_hours(google_hours: list[dict], written: str | None) -> dict:
    """{"state": ok|missing|problem, "problems", "days_open", "comparison": None | {"same": bool, "differences": [...]}}. The comparison exists only when the owner's written hours were read exactly."""
    rows = [[h["day"], h["open"], h["close"]] for h in google_hours or []]
    if not rows:
        return {"state": "missing", "problems": ["No regular opening hours are set on Google."], "days_open": 0, "comparison": None}
    problems = hours_problems(rows)
    comp = None
    parsed = parse_written_hours(written or "")
    if parsed is not None:
        g, w = {tuple(r) for r in rows}, {tuple(r) for r in parsed}
        if g == w:
            comp = {"same": True, "differences": [], "proposed": None}
        else:
            comp = {"same": False, "differences": [f"Only on Google: {d.title()} {o}-{c}" for d, o, c in sorted(g - w)] + [f"Only in your business record: {d.title()} {o}-{c}" for d, o, c in sorted(w - g)],
                    "proposed": parsed}
    return {"state": "problem" if problems else "ok", "problems": problems, "days_open": len({r[0] for r in rows}), "comparison": comp,
            "written_readable": parsed is not None if (written or "").strip() else None}


# ================================================================================================================================================
# special hours
# ================================================================================================================================================
def assess_special(current: list[dict], has_regular_hours: bool, today: date, region: str = "IN", horizon_days: int = 60) -> dict:
    """Upcoming fixed-date holidays within `horizon_days` that have no special-hours entry. A gap is a QUESTION for the owner ("are you closed or open different hours?"), not a value."""
    have = {p["start"] for p in current}
    gaps = []
    if region == "IN":
        for (mo, dy), name in FIXED_HOLIDAYS_IN:
            for yr in (today.year, today.year + 1):
                try:
                    d = date(yr, mo, dy)
                except ValueError:
                    continue
                if today <= d <= today + timedelta(days=horizon_days) and d.isoformat() not in have:
                    gaps.append({"date": d.isoformat(), "name": name})
    return {"upcoming_set": len([p for p in current if p["start"] >= today.isoformat()]), "gaps": sorted(gaps, key=lambda g: g["date"]),
            "needs_regular_hours_first": not has_regular_hours,
            "note": "Festivals that move each year (Diwali, Holi, Eid and others) are not listed: add them yourself when you know the dates."}


def merge_special(current: list[dict], additions: list[dict], today: date) -> list[dict]:
    """The COMPLETE special-hours list after adding the owner's entries. Every existing entry is kept as it is; an owner entry for a date already set REPLACES nothing silently: the caller
    must see the conflict (returned as `conflicts`) and decide."""
    cur = {p["start"]: p for p in current}
    conflicts = [a["start"] for a in additions if a["start"] in cur and cur[a["start"]] != a]
    merged = dict(cur)
    for a in additions:
        merged.setdefault(a["start"], a)
    return {"proposed": v2f.canon_special_hours(list(merged.values())), "conflicts": conflicts}


# ================================================================================================================================================
# service area, contacts
# ================================================================================================================================================
def assess_service_area(info: dict | None) -> dict:
    info = info or {}
    area = info.get("service_area")
    storefront = bool(info.get("storefront_address"))
    kind = "service_area_business" if area and area.get("business_type") == "CUSTOMER_LOCATION_ONLY" else "storefront_with_area" if area else "storefront" if storefront else "unknown"
    state, note = "ok", None
    if kind == "service_area_business" and not area.get("places"):
        state, note = "missing", "This business serves customers at their location but lists no areas, so Google cannot show where you work."
    elif kind == "unknown":
        state, note = "unknown", "Google did not return an address or a service area for this profile."
    return {"kind": kind, "state": state, "areas": [p["name"] for p in (area or {}).get("places", [])], "note": note,
            "note_never": "FlowQR never widens a service area to target more searches: only areas you choose are used."}


def phone_digits(p: str | None) -> str:
    d = re.sub(r"\D", "", p or "")
    return d[-10:] if len(d) >= 10 else d


def valid_url(u: str | None) -> bool:
    return bool(u) and bool(re.match(r"https?://[^\s/]+\.[^\s/]+(/\S*)?$", u.strip()))


def assess_contacts(info: dict | None, tenant_phone: str | None, tenant_website: str | None) -> dict:
    """Compare Google's phone and website with the business record. A missing value with a verified one on record is a fill; a DIFFERENT value is only flagged (replacing a working
    contact is a high-risk change the owner must approve, and an unverifiable value is never preferred over the one that works)."""
    info = info or {}
    out = {}
    for key, g, t, ok in (("phone", info.get("phone"), tenant_phone, lambda v: len(phone_digits(v)) >= 10), ("website", info.get("website"), tenant_website, valid_url)):
        g, t = (g or "").strip(), (t or "").strip()
        if not g and t:
            state = "fill" if ok(t) else "record_invalid"
        elif g and not t:
            state = "ok_google_only"
        elif not g and not t:
            state = "missing_everywhere"
        else:
            same = phone_digits(g) == phone_digits(t) if key == "phone" else g.rstrip("/").lower() == t.rstrip("/").lower()
            state = "ok" if same else ("differs" if ok(t) else "record_invalid")
        out[key] = {"state": state, "google": g or None, "record": t or None}
    return out
