"""Validation of website content.

Two levels, on purpose:
  * `validate_content`  SHAPE and SAFETY, run on every save. Strict: unknown keys, wrong types, over-long text, unsafe links, unknown or foreign images are refused. Empty is allowed, so a
    draft can be saved half-written.
  * `publish_blockers`  COMPLETENESS, run before a publish. Names every empty section, missing alt text and missing contact detail, so nothing half-finished goes live.

All business content is plain text. There is no field that accepts HTML, CSS, JavaScript or a script URL, and the renderer escapes every value it prints; this module makes sure the values are
the right kind before they are stored. Control characters, zero-width characters and bidirectional overrides (used to disguise text) are removed from every string."""
from __future__ import annotations

import re
import uuid
from typing import Any

from app.schemas.common import normalize_phone, validate_google_review_url
from app.services import registration
from app.services.sites import catalog as C
from app.services.sites.rules import clean_https_url

_INVISIBLE = dict.fromkeys(list(range(0, 9)) + [11, 12] + list(range(14, 32)) + [127] + list(range(0x200B, 0x2010)) + list(range(0x202A, 0x202F)) + list(range(0x2060, 0x2070)) + [0xFEFF], None)
_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_SECTION_ID = re.compile(r"^[a-z][a-z0-9]{1,11}$")
ONLY_ONCE = ("hero", "contact", "disclaimer", "hours", "location", "reviews")


class Errors(list):
    def add(self, path: str, message: str) -> None:
        self.append({"path": path, "message": message})


def _str(v: Any, path: str, errs: Errors, *, max: int, multiline: bool = False) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        errs.add(path, "Enter text.")
        return ""
    s = v.replace("\r\n", "\n").replace("\r", "\n").translate(_INVISIBLE)
    s = s.strip() if multiline else re.sub(r"\s+", " ", s.replace("\n", " ")).strip()
    if multiline:
        s = re.sub(r"\n{3,}", "\n\n", s)
    if len(s) > max:
        errs.add(path, f"Use at most {max} characters.")
        return s[:max]
    return s


def _check_keys(d: Any, allowed: set[str], path: str, errs: Errors) -> dict:
    if not isinstance(d, dict):
        errs.add(path, "This must be an object.")
        return {}
    for k in d:
        if k not in allowed:
            errs.add(f"{path}.{k}" if path else k, "This field is not allowed.")
    return d


def _value(spec: dict, v: Any, path: str, errs: Errors, asset_ids: set[str]) -> Any:
    kind = spec["kind"]
    if kind == "text":
        return _str(v, path, errs, max=spec.get("max", 100))
    if kind == "textarea":
        return _str(v, path, errs, max=spec.get("max", 500), multiline=True)
    if kind == "bool":
        if v is None:
            return False
        if not isinstance(v, bool):
            errs.add(path, "This must be on or off.")
            return False
        return v
    if kind == "select":
        v = "" if v is None else v
        if v not in spec["options"]:
            errs.add(path, "Choose one of the listed options.")
            return spec["options"][0]
        return v
    if kind == "asset":
        if v in (None, ""):
            return None
        try:
            key = str(uuid.UUID(str(v)))
        except ValueError:
            errs.add(path, "That image is not valid.")
            return None
        if key not in asset_ids:
            errs.add(path, "That image does not belong to this website.")
            return None
        return key
    if kind == "phone":
        s = _str(v, path, errs, max=32)
        if not s:
            return ""
        try:
            return normalize_phone(s) or ""
        except ValueError as exc:
            errs.add(path, str(exc))
            return ""
    if kind == "email":
        s = _str(v, path, errs, max=254)
        if not s:
            return ""
        if not registration.normalize_email(s):
            errs.add(path, "Enter a valid email address.")
            return ""
        return s.lower()
    if kind == "url":
        s = _str(v, path, errs, max=spec.get("max", 500))
        try:
            if spec["link"] == "review":
                return validate_google_review_url(s) or ""
            return clean_https_url(s, spec["link"], max_len=spec.get("max", 500)) or ""
        except ValueError as exc:
            errs.add(path, str(exc))
            return ""
    if kind == "strings":
        if v is None:
            return []
        if not isinstance(v, list):
            errs.add(path, "This must be a list.")
            return []
        if len(v) > spec["max_items"]:
            errs.add(path, f"Use at most {spec['max_items']} items.")
            v = v[: spec["max_items"]]
        out = [_str(x, f"{path}[{i}]", errs, max=spec.get("max", 60)) for i, x in enumerate(v)]
        return [x for x in out if x]
    if kind == "list":
        if v is None:
            return []
        if not isinstance(v, list):
            errs.add(path, "This must be a list.")
            return []
        if len(v) > spec["max_items"]:
            errs.add(path, f"Use at most {spec['max_items']} items.")
            v = v[: spec["max_items"]]
        return [_fields(spec["fields"], item, f"{path}[{i}]", errs, asset_ids) for i, item in enumerate(v)]
    errs.add(path, "Unsupported field.")
    return None


def _fields(specs: list[dict], d: Any, path: str, errs: Errors, asset_ids: set[str]) -> dict:
    d = _check_keys(d, {s["key"] for s in specs}, path, errs)
    return {s["key"]: _value(s, d.get(s["key"]), f"{path}.{s['key']}" if path else s["key"], errs, asset_ids) for s in specs}


def _hours(v: Any, path: str, errs: Errors) -> list[dict]:
    if not isinstance(v, list) or len(v) != 7:
        errs.add(path, "Give the opening hours for all seven days.")
        return [{"day": d, "closed": False, "open": "", "close": ""} for d in C.DAYS]
    by_day: dict[str, dict] = {}
    for i, row in enumerate(v):
        row = _check_keys(row, {"day", "closed", "open", "close"}, f"{path}[{i}]", errs)
        day = row.get("day")
        if day not in C.DAYS or day in by_day:
            errs.add(f"{path}[{i}].day", "Each day must appear exactly once.")
            continue
        o, c = _str(row.get("open"), f"{path}[{i}].open", errs, max=5), _str(row.get("close"), f"{path}[{i}].close", errs, max=5)
        for k, t in (("open", o), ("close", c)):
            if t and not _HHMM.match(t):
                errs.add(f"{path}[{i}].{k}", "Use the 24-hour format HH:MM.")
        closed = row.get("closed")
        if closed is not None and not isinstance(closed, bool):
            errs.add(f"{path}[{i}].closed", "This must be on or off.")
        by_day[day] = {"day": day, "closed": bool(closed), "open": o if _HHMM.match(o or "") else "", "close": c if _HHMM.match(c or "") else ""}
    return [by_day.get(d, {"day": d, "closed": False, "open": "", "close": ""}) for d in C.DAYS]


def _cta(v: Any, path: str, errs: Errors, optional: bool) -> dict | None:
    if v is None and optional:
        return None
    v = _check_keys(v, {"kind", "label"}, path, errs)
    kind = v.get("kind")
    if kind not in C.CTA_KINDS:
        errs.add(f"{path}.kind", "Choose a button type.")
        kind = "call"
    return {"kind": kind, "label": _str(v.get("label"), f"{path}.label", errs, max=30)}


def validate_content(content: Any, template_key: str, asset_ids: set[str]) -> tuple[dict, list[dict]]:
    """(clean content, errors). The clean content has every key present, so the renderer never has to guess."""
    errs = Errors()
    if template_key not in C.TEMPLATES:
        errs.add("template_key", "Unknown template.")
        return {}, list(errs)
    top = _check_keys(content, {"business", "cta", "seo", "theme", "sections"}, "", errs)
    b = _check_keys(top.get("business") or {}, {s["key"] for s in C.BUSINESS_FIELDS} | {"hours"}, "business", errs)
    business = {s["key"]: _value(s, b.get(s["key"]), f"business.{s['key']}", errs, asset_ids) for s in C.BUSINESS_FIELDS}
    business["hours"] = _hours(b.get("hours"), "business.hours", errs)
    cta_in = _check_keys(top.get("cta") or {}, {"primary", "secondary"}, "cta", errs)
    cta = {"primary": _cta(cta_in.get("primary"), "cta.primary", errs, False), "secondary": _cta(cta_in.get("secondary"), "cta.secondary", errs, True)}
    seo_in = _check_keys(top.get("seo") or {}, {"title", "description", "og_image"}, "seo", errs)
    seo = {"title": _str(seo_in.get("title"), "seo.title", errs, max=70), "description": _str(seo_in.get("description"), "seo.description", errs, max=160),
           "og_image": _value(C.asset("og_image", "Share image"), seo_in.get("og_image"), "seo.og_image", errs, asset_ids)}
    th = _check_keys(top.get("theme") or {}, {"accent"}, "theme", errs)
    accent = th.get("accent") or C.TEMPLATES[template_key]["accent"]
    if accent not in C.ACCENTS:
        errs.add("theme.accent", "Choose one of the listed colours.")
        accent = C.TEMPLATES[template_key]["accent"]

    sections_in = top.get("sections")
    sections: list[dict] = []
    if not isinstance(sections_in, list):
        errs.add("sections", "Sections must be a list.")
        sections_in = []
    if len(sections_in) > C.MAX_SECTIONS:
        errs.add("sections", f"Use at most {C.MAX_SECTIONS} sections.")
        sections_in = sections_in[: C.MAX_SECTIONS]
    allowed, seen_ids, counts = set(C.allowed_sections(template_key)), set(), {}
    for i, sec in enumerate(sections_in):
        path = f"sections[{i}]"
        sec = _check_keys(sec, {"id", "type", "enabled", "data"}, path, errs)
        typ, sid = sec.get("type"), sec.get("id")
        if typ not in C.SECTION_TYPES or typ not in allowed:
            errs.add(f"{path}.type", "This section is not available in this template.")
            continue
        if not isinstance(sid, str) or not _SECTION_ID.match(sid) or sid in seen_ids:
            errs.add(f"{path}.id", "Each section needs its own short id.")
            continue
        seen_ids.add(sid)
        counts[typ] = counts.get(typ, 0) + 1
        if typ in ONLY_ONCE and counts[typ] > 1:
            errs.add(f"{path}.type", f"A website can have only one {C.SECTION_TYPES[typ]['label'].lower()} section.")
            continue
        en = sec.get("enabled", True)
        if not isinstance(en, bool):
            errs.add(f"{path}.enabled", "This must be on or off.")
            en = True
        sections.append({"id": sid, "type": typ, "enabled": en, "data": _fields(C.SECTION_TYPES[typ]["fields"], sec.get("data") or {}, f"{path}.data", errs, asset_ids)})
    clean = {"business": business, "cta": cta, "seo": seo, "theme": {"accent": accent}, "sections": sections}
    return clean, list(errs)


def referenced_assets(content: dict) -> set[str]:
    """Every image id a content document uses."""
    found: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("image", "logo", "og_image", "asset") and isinstance(v, str):
                    found.add(v)
                else:
                    walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)

    walk(content)
    return found


def _empty(typ: str, data: dict) -> str | None:
    """Why a section has nothing to show, or None."""
    spec = {f["key"]: f for f in C.SECTION_TYPES[typ]["fields"]}
    if typ == "hero":
        return None if data.get("heading") else "add a heading"
    if typ in ("hours", "location", "contact", "cta_band", "reviews"):
        return None if data.get("heading") else "add a heading"
    if typ == "about":
        return None if data.get("body") else "write the text"
    if typ == "disclaimer":
        return None if data.get("text") else "write the text"
    for key in ("items", "groups", "categories", "steps", "members", "images", "areas"):
        if key in spec:
            items = data.get(key) or []
            if not items:
                return "add at least one entry"
            if typ == "price_menu" and not any(g.get("items") for g in items):
                return "add at least one priced item"
            if typ == "menu" and not any(c.get("items") for c in items):
                return "add at least one dish"
            if typ == "gallery" and not any(i.get("asset") for i in items):
                return "add at least one image"
            return None
    return None


def publish_blockers(content: dict, template_key: str, assets: dict[str, dict]) -> list[dict]:
    """What must be fixed before this can go live. `assets`: id -> {alt_text}. Empty list = ready."""
    out: list[dict] = []
    b = content.get("business", {})
    if not b.get("name"):
        out.append({"path": "business.name", "message": "Add the business name."})
    if not (b.get("phone") or b.get("whatsapp") or b.get("email")):
        out.append({"path": "business.phone", "message": "Add at least one way to contact the business (phone, WhatsApp or email)."})
    seo = content.get("seo", {})
    if not seo.get("title"):
        out.append({"path": "seo.title", "message": "Add a search title."})
    if not seo.get("description"):
        out.append({"path": "seo.description", "message": "Add a search description."})
    enabled = [s for s in content.get("sections", []) if s.get("enabled")]
    if not any(s["type"] == "hero" for s in enabled):
        out.append({"path": "sections", "message": "Keep the hero section on."})
    for i, s in enumerate(content.get("sections", [])):
        if not s.get("enabled"):
            continue
        why = _empty(s["type"], s["data"])
        if s["type"] == "hours" and not why and not any(h["closed"] or (h["open"] and h["close"]) for h in b.get("hours", [])):
            why = "fill in the opening hours"
        if why:
            out.append({"path": f"sections[{i}]", "message": f"{C.SECTION_TYPES[s['type']]['label']}: {why}, or turn the section off."})
    for aid in sorted(referenced_assets(content)):
        a = assets.get(aid)
        if a is None:
            out.append({"path": "assets", "message": "An image used on the page is missing."})
        elif not (a.get("alt_text") or "").strip():
            out.append({"path": f"assets.{aid}", "message": "Every image needs alt text (a short description for people who cannot see it)."})
    if template_key == "clinic" and not any(s["type"] == "disclaimer" and s["data"].get("text") for s in enabled):
        out.append({"path": "sections", "message": "A clinic website must keep its health disclaimer on."})
    if any(s["type"] == "contact" and s["data"].get("show_enquiry") for s in enabled) and not (b.get("phone") or b.get("email") or b.get("whatsapp")):
        out.append({"path": "business.phone", "message": "The enquiry form needs a contact detail for the business."})
    return out
