"""Plain-language BEFORE -> AFTER for any action, so every proposed change can be shown the same way: what is on Google now, what it would become, and what is added or removed. PURE."""
from __future__ import annotations

from app.services.agent.v2 import fields as v2f


def _hours(rows) -> list[str]:
    by: dict[str, list[str]] = {}
    for h in rows or []:
        d, o, c = (h["day"], h["open"], h["close"]) if isinstance(h, dict) else h
        by.setdefault(d, []).append(f"{o}-{c}")
    order = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
    return [f"{d.title()}: {', '.join(by[d])}" for d in order if d in by]


def _sp(p: dict) -> str:
    return f"{p['start']}: " + ("closed" if p["closed"] else f"{p['open']}-{p['close']}" + (f" (until {p['end']})" if p["end"] != p["start"] else ""))


def _attr(a: dict) -> str:
    v = a["value"]
    if a["type"] == "BOOL":
        v = "Yes" if v else "No"
    elif a["type"] == "REPEATED_ENUM":
        v = ", ".join(v["set"]) + (f" (not: {', '.join(v['unset'])})" if v["unset"] else "")
    elif a["type"] == "URL":
        v = ", ".join(v)
    return f"{a['name'].split('/')[-1].replace('_', ' ')}: {v}"


def describe(field: str, before, after, evidence: dict | None = None) -> dict:
    """{"before": [lines], "after": [lines], "added": [lines], "removed": [lines], "changed": bool}. Never raises on a value it does not recognise: it falls back to the raw text."""
    ev = evidence or {}
    try:
        if field == "services":
            names = ev.get("type_names") or {}
            b, a = v2f.canon_services(before), v2f.canon_services(after)
            lab = lambda xs: [v2f.service_label(x, names) for x in xs]  # noqa: E731
            return {"before": lab(b), "after": lab(a), "added": lab(v2f.services_added(b, a)), "removed": lab(v2f.services_removed(b, a)), "changed": b != a}
        if field == "special_hours":
            b, a = v2f.canon_special_hours(before), v2f.canon_special_hours(after)
            bs, as_ = {_sp(p) for p in b}, {_sp(p) for p in a}
            return {"before": [_sp(p) for p in b], "after": [_sp(p) for p in a], "added": sorted(as_ - bs), "removed": sorted(bs - as_), "changed": b != a}
        if field == "attributes":
            b, a = v2f.canon_attributes(before), v2f.canon_attributes(after)
            bs, as_ = {_attr(x) for x in b}, {_attr(x) for x in a}
            return {"before": [_attr(x) for x in b], "after": [_attr(x) for x in a], "added": sorted(as_ - bs), "removed": sorted(bs - as_), "changed": b != a}
        if field == "categories":
            nm = {r["id"]: r["name"] for r in ev.get("recommendations") or []}
            b, a = v2f.canon_categories(before) or {"primary": None, "additional": []}, v2f.canon_categories(after) or {"primary": None, "additional": []}
            lab = lambda ids: [nm.get(i, i.split(":")[-1].replace("_", " ").title()) for i in ids]  # noqa: E731
            bl = ([f"Main: {lab([b['primary']])[0]}"] if b["primary"] else []) + lab(b["additional"])
            al = ([f"Main: {lab([a['primary']])[0]}"] if a["primary"] else []) + lab(a["additional"])
            return {"before": bl, "after": al, "added": [x for x in al if x not in bl], "removed": [x for x in bl if x not in al], "changed": bl != al}
        if field == "service_area":
            bn = [p["name"] for p in (before or {}).get("places", [])] if isinstance(before, dict) else []
            an = [p["name"] for p in (after or {}).get("places", [])] if isinstance(after, dict) else []
            return {"before": bn, "after": an, "added": [x for x in an if x not in bn], "removed": [x for x in bn if x not in an], "changed": bn != an}
        if field == "hours":
            b, a = _hours(before), _hours(after)
            return {"before": b, "after": a, "added": [x for x in a if x not in b], "removed": [x for x in b if x not in a], "changed": b != a}
    except (v2f.FieldError, KeyError, TypeError, AttributeError):
        pass
    b = [] if before in (None, "", []) else [str(before)]
    a = [] if after in (None, "", []) else [str(after)]
    return {"before": b, "after": a, "added": a if b != a else [], "removed": b if b != a else [], "changed": b != a}
