"""Canonical forms, validators and Google payload converters for the Local SEO V2 profile fields.

PURE: no database, no network, no clock except where a caller passes `today`. Every comparison the engine makes (is this still what Google holds? did the write land?) is made
between canonical values from this module, so "the same" has exactly one definition.

Fields: services (the COMPLETE list), special_hours (the COMPLETE list), attributes (the complete configured set), service_area, categories (primary + additional TOGETHER).

Each shape below was checked against Google's Business Information reference (read 2026-11-22) and is pinned by tests/test_seo_v2_*.py:
  * serviceItems: StructuredServiceItem{serviceTypeId, description<=300} | FreeFormServiceItem{category, label{displayName, description<=250 recommended, languageCode}}, price opaque
  * specialHours.specialHourPeriods[]: startDate required; endDate optional (== startDate or +1 day); openTime/closeTime required unless closed; a period is < 24h; it needs regularHours set
  * attributes: Attribute{name, values[] | repeatedEnumValue{setValues, unsetValues} | uriValues[]}; valueType is output-only
  * serviceArea: businessType, places.placeInfos[<=20]{placeName, placeId}, regionCode (immutable)
  * categories: primaryCategory + additionalCategories, always sent together (Google: "both fields must be set")
Google does NOT document a count limit for serviceItems or whether a patch replaces the list, so the engine always sends the complete merged list (safe either way)."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

FREE_NAME_MAX, FREE_DESC_MAX, STRUCT_DESC_MAX = 140, 250, 300  # Google's stated limits (free-form label guidance is "recommended", still enforced here)
PLACES_MAX = 20
ADDITIONAL_CATEGORIES_MAX = 9  # Google Business Profile help: up to 9 additional categories (the API reference states no number)
SERVICE_AREA_TYPES = ("CUSTOMER_LOCATION_ONLY", "CUSTOMER_AND_BUSINESS_LOCATION")
ATTRIBUTE_TYPES = ("BOOL", "ENUM", "REPEATED_ENUM", "URL")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME = re.compile(r"(\d{2}):(\d{2})")


class FieldError(ValueError):
    """A value that is not even the right shape. The message is for the owner."""


def norm(s) -> str:
    return " ".join(str(s or "").split())


def key_of(s) -> str:
    """Matching key for a name: case-folded, punctuation and spacing ignored."""
    return re.sub(r"[^a-z0-9]+", " ", norm(s).lower()).strip()


def _dump(v) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


# ================================================================================================================================================
# services
# ================================================================================================================================================
def canon_service(x) -> dict:
    """{"k": "s"|"c", ...}. s = a Google predefined (structured) service, c = a custom (free-form) one. Price is passed through untouched, never invented."""
    if not isinstance(x, dict):
        raise FieldError("A service must be an object with a name or a Google service type.")
    kind = {"s": "s", "structured": "s", "c": "c", "custom": "c", "free": "c"}.get(str(x.get("k") or x.get("kind") or "").lower())
    if kind is None:
        kind = "s" if (x.get("id") or x.get("serviceTypeId")) else "c"
    out: dict = {"k": kind}
    if kind == "s":
        sid = norm(x.get("id") or x.get("serviceTypeId"))
        if not sid:
            raise FieldError("A Google service needs its service type id.")
        out["id"] = sid  # the display name of a predefined service is output-only on Google's side: it is not part of the value (the UI gets it from the category's service types)
        if norm(x.get("d") or x.get("description")):
            out["d"] = norm(x.get("d") or x.get("description"))
    else:
        name = norm(x.get("n") or x.get("name") or x.get("displayName"))
        if not name:
            raise FieldError("A custom service needs a name.")
        out["n"] = name
        if norm(x.get("d") or x.get("description")):
            out["d"] = norm(x.get("d") or x.get("description"))
        if norm(x.get("c") or x.get("category")):
            out["c"] = norm(x.get("c") or x.get("category"))
        if norm(x.get("l") or x.get("languageCode")):
            out["l"] = norm(x.get("l") or x.get("languageCode"))
    if x.get("p") or x.get("price"):
        out["p"] = x.get("p") or x.get("price")
    return out


def service_key(item: dict) -> str:
    return f"s:{item['id']}" if item["k"] == "s" else f"c:{key_of(item['n'])}"


def canon_services(v) -> list[dict]:
    """The complete service list, de-duplicated (Google removes duplicates itself) and in a fixed order. A structured item's display name is not part of its identity."""
    if v is None:
        return []
    if not isinstance(v, list):
        raise FieldError("Services must be a list.")
    seen: dict[str, dict] = {}
    for x in v:
        it = canon_service(x)
        seen.setdefault(service_key(it), it)
    return sorted(seen.values(), key=service_key)


def services_from_google(items) -> list[dict]:
    out = []
    for x in items or []:
        if not isinstance(x, dict):
            continue
        st, ff = x.get("structuredServiceItem"), x.get("freeFormServiceItem")
        if st and st.get("serviceTypeId"):
            it = {"k": "s", "id": st["serviceTypeId"], **({"d": st["description"]} if st.get("description") else {})}
        elif ff and ((ff.get("label") or {}).get("displayName")):
            lab = ff["label"]
            it = {"k": "c", "n": lab["displayName"], **({"d": lab["description"]} if lab.get("description") else {}), **({"c": ff["category"]} if ff.get("category") else {}),
                  **({"l": lab["languageCode"]} if lab.get("languageCode") else {})}
        else:
            continue
        if x.get("price"):
            it["p"] = x["price"]
        out.append(it)
    return canon_services(out)


def services_to_google(items) -> list[dict]:
    out = []
    for it in canon_services(items):
        if it["k"] == "s":
            g = {"structuredServiceItem": {"serviceTypeId": it["id"], **({"description": it["d"]} if it.get("d") else {})}}
        else:
            label = {"displayName": it["n"], **({"description": it["d"]} if it.get("d") else {}), **({"languageCode": it["l"]} if it.get("l") else {})}
            g = {"freeFormServiceItem": {"category": it.get("c", ""), "label": label}}
            if not g["freeFormServiceItem"]["category"]:
                raise FieldError(f"The custom service '{it['n']}' has no category. Google needs the category a free-form service belongs to.")
        if it.get("p"):
            g["price"] = it["p"]
        out.append(g)
    return out


def service_label(it: dict, type_names: dict | None = None) -> str:
    return it["n"] if it["k"] == "c" else ((type_names or {}).get(it["id"]) or it["id"])


def services_problems(proposed: list[dict]) -> list[str]:
    out = []
    for it in proposed:
        name = it.get("n") or it.get("id")
        if it["k"] == "c":
            if len(it["n"]) > FREE_NAME_MAX:
                out.append(f"The service name '{it['n'][:30]}...' is longer than {FREE_NAME_MAX} characters.")
            if len(it.get("d", "")) > FREE_DESC_MAX:
                out.append(f"The description of '{name}' is longer than {FREE_DESC_MAX} characters.")
            if not it.get("c"):
                out.append(f"The custom service '{name}' has no category, which Google requires.")
        elif len(it.get("d", "")) > STRUCT_DESC_MAX:
            out.append(f"The description of '{name}' is longer than {STRUCT_DESC_MAX} characters.")
        if re.search(r"https?://|www\.", f"{it.get('n', '')} {it.get('d', '')}", re.I):
            out.append(f"'{name}' contains a link, which does not belong in a service.")
    return out


def services_removed(current: list[dict], proposed: list[dict]) -> list[dict]:
    keep = {service_key(x) for x in proposed}
    return [x for x in current if service_key(x) not in keep]


def services_added(current: list[dict], proposed: list[dict]) -> list[dict]:
    have = {service_key(x) for x in current}
    return [x for x in proposed if service_key(x) not in have]


# ================================================================================================================================================
# special hours
# ================================================================================================================================================
def _mins(t: str) -> int:
    m = _TIME.fullmatch(t or "")
    if not m:
        raise FieldError(f"'{t}' is not a time (use HH:MM).")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 24 and 0 <= mi <= 59) or (h == 24 and mi != 0):
        raise FieldError(f"'{t}' is not a valid time (00:00 to 24:00).")
    return h * 60 + mi


def canon_special_period(p) -> dict:
    if not isinstance(p, dict):
        raise FieldError("A special-hours entry must be an object.")
    start = norm(p.get("start") or p.get("date"))
    if not _DATE.fullmatch(start):
        raise FieldError(f"'{start}' is not a date (use YYYY-MM-DD).")
    try:
        date.fromisoformat(start)
    except ValueError:
        raise FieldError(f"'{start}' is not a real date.") from None
    end = norm(p.get("end")) or start
    if not _DATE.fullmatch(end):
        raise FieldError(f"'{end}' is not a date (use YYYY-MM-DD).")
    closed = bool(p.get("closed"))
    if closed:
        return {"start": start, "end": start, "closed": True, "open": None, "close": None}
    return {"start": start, "end": end, "closed": False, "open": norm(p.get("open")) or None, "close": norm(p.get("close")) or None}


def canon_special_hours(v) -> list[dict]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise FieldError("Special hours must be a list.")
    return sorted((canon_special_period(p) for p in v), key=lambda p: (p["start"], p["end"], p["open"] or ""))


def special_period_problems(p: dict) -> list[str]:
    """Google's SpecialHourPeriod rules. A closed day needs nothing else; an open period needs both times, must be shorter than 24 hours and may end at most 11:59 the next day."""
    when = p["start"]
    try:
        s, e = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
    except ValueError:
        return [f"{when}: not a real date."]
    if p["closed"]:
        return []
    if not p["open"] or not p["close"]:
        return [f"{when}: an open day needs both an opening and a closing time (or mark it closed)."]
    try:
        o, c = _mins(p["open"]), _mins(p["close"])
    except FieldError as exc:
        return [f"{when}: {exc}"]
    days = (e - s).days
    if days not in (0, 1):
        return [f"{when}: a special period must end the same day or the next day."]
    length = days * 1440 + c - o
    if length <= 0:
        return [f"{when}: the closing time must be after the opening time."]
    if length >= 1440:
        return [f"{when}: a special period must be shorter than 24 hours."]
    if days == 1 and c > 11 * 60 + 59:
        return [f"{when}: a period that ends the next day can close at 11:59 at the latest."]
    return []


def special_hours_problems(proposed: list[dict], *, has_regular_hours: bool | None) -> list[str]:
    out: list[str] = []
    if has_regular_hours is False:
        out.append("Google does not accept special hours until regular opening hours are set on the profile. Set the regular hours first.")
    seen: set[str] = set()
    for p in proposed:
        out += special_period_problems(p)
        if p["start"] in seen:
            out.append(f"{p['start']}: two entries for the same date. Keep one.")
        seen.add(p["start"])
    return out


def future_special(v: list[dict], today: date) -> list[dict]:
    return [p for p in v if p["start"] >= today.isoformat()]


def special_hours_from_google(sh) -> list[dict]:
    out = []
    for p in (sh or {}).get("specialHourPeriods", []) or []:
        sd, ed = p.get("startDate"), p.get("endDate") or p.get("startDate")
        if not sd:
            continue

        def ymd(d):
            return f"{int(d['year']):04d}-{int(d['month']):02d}-{int(d['day']):02d}"

        def hm(t):
            t = t or {}
            return f"{int(t.get('hours', 0)):02d}:{int(t.get('minutes', 0)):02d}"
        if p.get("closed"):
            out.append({"start": ymd(sd), "end": ymd(sd), "closed": True, "open": None, "close": None})
        else:
            out.append({"start": ymd(sd), "end": ymd(ed), "closed": False, "open": hm(p.get("openTime")), "close": hm(p.get("closeTime"))})
    return canon_special_hours(out)


def special_hours_to_google(periods) -> dict:
    def d(s):
        y, m, dd = (int(x) for x in s.split("-"))
        return {"year": y, "month": m, "day": dd}

    def t(s):
        h, m = s.split(":")
        return {"hours": int(h), "minutes": int(m)}
    out = []
    for p in canon_special_hours(periods):
        if p["closed"]:
            out.append({"startDate": d(p["start"]), "closed": True})
        else:
            out.append({"startDate": d(p["start"]), "endDate": d(p["end"]), "openTime": t(p["open"]), "closeTime": t(p["close"]), "closed": False})
    return {"specialHourPeriods": out}


# ================================================================================================================================================
# attributes
# ================================================================================================================================================
def canon_attribute(a) -> dict:
    if not isinstance(a, dict) or not norm(a.get("name")):
        raise FieldError("An attribute needs a name (attributes/...).")
    name = norm(a["name"])
    if not name.startswith("attributes/"):
        name = f"attributes/{name}"
    typ = str(a.get("type") or "").upper()
    if typ not in ATTRIBUTE_TYPES:
        raise FieldError(f"{name}: the attribute type must be one of {', '.join(ATTRIBUTE_TYPES)}.")
    v = a.get("value")
    if typ == "BOOL":
        if not isinstance(v, bool):
            raise FieldError(f"{name}: a yes/no attribute needs true or false.")
        return {"name": name, "type": typ, "value": v}
    if typ == "ENUM":
        if not isinstance(v, str) or not v.strip():
            raise FieldError(f"{name}: choose one of the values Google offers.")
        return {"name": name, "type": typ, "value": v.strip()}
    if typ == "REPEATED_ENUM":
        v = v if isinstance(v, dict) else {}
        s, u = sorted({str(x) for x in v.get("set") or []}), sorted({str(x) for x in v.get("unset") or []})
        if not s and not u:
            raise FieldError(f"{name}: at least one value must be set or unset.")
        if set(s) & set(u):
            raise FieldError(f"{name}: a value cannot be both set and unset.")
        return {"name": name, "type": typ, "value": {"set": s, "unset": u}}
    uris = sorted({norm(x) for x in (v if isinstance(v, list) else [v]) if norm(x)})
    if not uris or any(not re.match(r"https?://[^\s]+\.[^\s]+$", u) for u in uris):
        raise FieldError(f"{name}: a link attribute needs a full web address.")
    return {"name": name, "type": typ, "value": uris}


def canon_attributes(v) -> list[dict]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise FieldError("Attributes must be a list.")
    return sorted({a["name"]: a for a in (canon_attribute(x) for x in v)}.values(), key=lambda a: a["name"])


def attributes_from_google(resp) -> list[dict]:
    """Normalise Attributes.attributes[] as Google returns it (valueType is output-only; bool values arrive in values[])."""
    out = []
    for a in (resp or {}).get("attributes", []) or []:
        typ, name = a.get("valueType"), a.get("name")
        if not name:
            continue
        try:
            if typ == "REPEATED_ENUM" or a.get("repeatedEnumValue"):
                r = a.get("repeatedEnumValue") or {}
                out.append({"name": name, "type": "REPEATED_ENUM", "value": {"set": r.get("setValues") or [], "unset": r.get("unsetValues") or []}})
            elif typ == "URL" or a.get("uriValues"):
                out.append({"name": name, "type": "URL", "value": [u.get("uri") for u in a.get("uriValues") or [] if u.get("uri")]})
            else:
                vals = a.get("values") or []
                if not vals:
                    continue
                if typ == "BOOL" or isinstance(vals[0], bool):
                    out.append({"name": name, "type": "BOOL", "value": bool(vals[0])})
                else:
                    out.append({"name": name, "type": "ENUM", "value": str(vals[0])})
        except (TypeError, AttributeError):
            continue
    try:
        return canon_attributes(out)
    except FieldError:
        return sorted(out, key=lambda a: a["name"])


def attribute_to_google(a: dict) -> dict:
    if a["type"] == "BOOL" or a["type"] == "ENUM":
        return {"name": a["name"], "values": [a["value"]]}
    if a["type"] == "REPEATED_ENUM":
        return {"name": a["name"], "repeatedEnumValue": {"setValues": a["value"]["set"], "unsetValues": a["value"]["unset"]}}
    return {"name": a["name"], "uriValues": [{"uri": u} for u in a["value"]]}


def attributes_changed(current: list[dict], proposed: list[dict]) -> tuple[list[dict], list[str]]:
    """(attributes to send, names to delete). Only what differs is sent: an attribute that is not in attributeMask is ignored by Google, so nothing else is touched."""
    cur = {a["name"]: a for a in current}
    prop = {a["name"]: a for a in proposed}
    send = [a for n, a in prop.items() if cur.get(n) != a]
    gone = [n for n in cur if n not in prop]
    return send, gone


def validate_attribute_against_metadata(a: dict, meta: dict | None) -> list[str]:
    """`meta` is one AttributeMetadata from attributes.list. An attribute Google does not list for this location/category, or marks deprecated, is not applied."""
    if meta is None:
        return [f"{a['name']}: Google does not offer this attribute for this business category and country."]
    out = []
    if meta.get("deprecated"):
        out.append(f"{a['name']}: Google has deprecated this attribute, so a change would not be saved.")
    vt = meta.get("valueType")
    if vt and vt != a["type"]:
        out.append(f"{a['name']}: Google expects a {vt} value, not {a['type']}.")
        return out
    allowed = [str((vm or {}).get("value")) if not isinstance((vm or {}).get("value"), bool) else (vm or {}).get("value") for vm in meta.get("valueMetadata") or []]
    if a["type"] == "ENUM" and allowed and a["value"] not in allowed:
        out.append(f"{a['name']}: '{a['value']}' is not one of Google's values ({', '.join(map(str, allowed))}).")
    if a["type"] == "REPEATED_ENUM" and allowed:
        bad = [x for x in a["value"]["set"] + a["value"]["unset"] if x not in allowed]
        if bad:
            out.append(f"{a['name']}: {', '.join(bad)} are not Google's values ({', '.join(map(str, allowed))}).")
    return out


# ================================================================================================================================================
# service area, categories
# ================================================================================================================================================
def canon_service_area(v) -> dict | None:
    if v in (None, {}):
        return None
    if not isinstance(v, dict):
        raise FieldError("A service area must be an object.")
    bt = str(v.get("business_type") or v.get("businessType") or "").upper()
    if bt not in SERVICE_AREA_TYPES:
        raise FieldError("The business type must be CUSTOMER_LOCATION_ONLY or CUSTOMER_AND_BUSINESS_LOCATION.")
    places = {}
    for p in v.get("places") or []:
        pid, name = norm(p.get("place_id") or p.get("placeId")), norm(p.get("name") or p.get("placeName"))
        if not pid or not name:
            raise FieldError("Every area needs a name and a Google place id.")
        places[pid] = {"name": name, "place_id": pid}
    return {"business_type": bt, "places": sorted(places.values(), key=lambda p: p["place_id"]), "region": norm(v.get("region") or v.get("regionCode")) or None}


def service_area_from_google(sa) -> dict | None:
    if not sa:
        return None
    infos = ((sa.get("places") or {}).get("placeInfos")) or []
    try:
        return canon_service_area({"business_type": sa.get("businessType"), "places": [{"name": p.get("placeName"), "place_id": p.get("placeId")} for p in infos], "region": sa.get("regionCode")})
    except FieldError:
        return None


def service_area_to_google(v: dict) -> dict:
    c = canon_service_area(v)
    out: dict = {"businessType": c["business_type"], "places": {"placeInfos": [{"placeName": p["name"], "placeId": p["place_id"]} for p in c["places"]]}}
    if c["business_type"] == "CUSTOMER_LOCATION_ONLY" and c.get("region"):
        out["regionCode"] = c["region"]
    return out


def service_area_problems(proposed: dict | None, current: dict | None) -> list[str]:
    out = []
    if proposed is None:
        return ["No service area was given."]
    if len(proposed["places"]) > PLACES_MAX:
        out.append(f"Google accepts at most {PLACES_MAX} service areas (this has {len(proposed['places'])}).")
    if current and current["business_type"] != proposed["business_type"]:
        out.append("Switching between a storefront-and-area and an area-only business changes the address on Google. FlowQR does not do that: change it in Google Business Profile.")
    if current and current.get("region") and proposed.get("region") and current["region"] != proposed["region"]:
        out.append("The region of a service area cannot be changed.")
    if proposed["business_type"] == "CUSTOMER_LOCATION_ONLY" and not (proposed.get("region") or (current or {}).get("region")):
        out.append("An area-only business needs its region (country) code.")
    return out


def canon_categories(v) -> dict | None:
    if v in (None, {}):
        return None
    if not isinstance(v, dict):
        raise FieldError("Categories must be an object with a primary and the additional categories.")
    pri = v.get("primary")
    pri = pri.get("id") if isinstance(pri, dict) else pri
    if not norm(pri):
        raise FieldError("Google requires a primary category.")
    add = {x.get("id") if isinstance(x, dict) else x for x in v.get("additional") or []}
    add = sorted(norm(x) for x in add if norm(x) and norm(x) != norm(pri))
    return {"primary": norm(pri), "additional": add}


def categories_from_details(d: dict | None) -> dict | None:
    d = d or {}
    pri = d.get("primary_category")
    if not pri:
        return None
    return canon_categories({"primary": pri, "additional": d.get("additional_categories") or []})


def categories_problems(proposed: dict | None) -> list[str]:
    if proposed is None:
        return ["No categories were given."]
    out = []
    if len(proposed["additional"]) > ADDITIONAL_CATEGORIES_MAX:
        out.append(f"At most {ADDITIONAL_CATEGORIES_MAX} additional categories are allowed (this has {len(proposed['additional'])}).")
    return out


def fingerprintable(v):
    """A JSON-stable view for hashing/comparison of any canonical V2 value."""
    return json.loads(_dump(v))
