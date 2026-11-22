"""Google's reference data for ONE profile (what its category offers), read with the customer's token as READS (like the profile and review syncs) and kept in the profile snapshot so the
six-hourly scan makes no Google call at all.

    service_types       the predefined services Google offers for the profile's categories          (categories:batchGet, view=FULL)
    attribute_metadata  the attributes Google offers for this business's category, country, language (attributes.list, parent=location)
    categories          candidate categories matching the owner's own words                           (categories.list, filter=displayName prefix)
    google_updated      which fields Google's live view differs from the merchant's data in          (locations.getGoogleUpdated: diffMask / pendingMask; masks only, no content)

This is reference data about what Google offers, not customer content. Nothing here writes anything. Each part is independent: one failing leaves the others, and what could not be read is
recorded as unavailable, never guessed."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.services.google.errors import GoogleError

log = logging.getLogger("flowqr.v2catalog")
CATEGORY_SEARCH_EVERY = timedelta(days=7)
MAX_CATEGORY_QUERIES = 6
GOOGLE_UPDATED_MASK = "title,profile,regularHours,specialHours,categories,websiteUri,phoneNumbers,serviceItems,serviceArea"
KEEP_META = ("valueType", "displayName", "groupDisplayName", "repeatable", "valueMetadata", "deprecated")


def _region(info: dict) -> str:
    return "IN"  # FlowQR is India-first; a profile's own region is not in the read mask. Kept in one place so it can follow the profile later.


def fetch(provider, token: str, location_name: str, info: dict, *, search_terms: list[str], previous: dict | None, now: datetime) -> tuple[dict, list[str]]:
    """(catalog, errors). `previous` is the catalog from the last snapshot: its category search is reused for a week (the search is a handful of calls and the answers rarely change)."""
    cat: dict = {"fetched_at": now.isoformat()}
    errors: list[str] = []
    prev = previous or {}

    def attempt(label, fn):
        try:
            return fn()
        except GoogleError as exc:
            errors.append(f"{label}: {exc}")
        except Exception as exc:  # noqa: BLE001 - reference data is optional: the rest of the snapshot must still be saved
            log.warning("v2 catalog %s failed: %s", label, exc)
            errors.append(f"{label}: {type(exc).__name__}")
        return None

    cat_ids = [c["id"] for c in [info.get("primary_category"), *(info.get("additional_categories") or [])] if c and c.get("id")]
    if cat_ids and hasattr(provider, "get_category_service_types"):
        st = attempt("service types", lambda: provider.get_category_service_types(token, cat_ids, _region(info), "en"))
        if st is not None:
            cat["service_types"] = st
    if hasattr(provider, "attribute_metadata_for_location"):
        meta = attempt("attribute metadata", lambda: provider.attribute_metadata_for_location(token, location_name))
        if meta is not None:
            cat["attribute_metadata"] = {n: {k: m[k] for k in KEEP_META if k in m} for n, m in meta.items()}
    searched_at = (prev.get("categories") or {}).get("searched_at")
    fresh = searched_at and datetime.fromisoformat(searched_at) > now - CATEGORY_SEARCH_EVERY and (prev.get("categories") or {}).get("terms") == search_terms[:MAX_CATEGORY_QUERIES]
    if fresh:
        cat["categories"] = prev["categories"]
    elif search_terms and hasattr(provider, "search_categories"):
        found: dict[str, dict] = {}
        for term in search_terms[:MAX_CATEGORY_QUERIES]:
            res = attempt(f"category search '{term[:20]}'", lambda t=term: provider.search_categories(token, t, _region(info), "en"))
            for c in res or []:
                if c and c.get("id"):
                    found.setdefault(c["id"], {"id": c["id"], "name": c.get("name"), "matched_term": term})
        cat["categories"] = {"candidates": list(found.values()), "searched_at": now.isoformat(), "terms": search_terms[:MAX_CATEGORY_QUERIES]}
    if hasattr(provider, "get_google_updated"):
        gu = attempt("google updated", lambda: provider.get_google_updated(token, location_name, GOOGLE_UPDATED_MASK))
        if gu is not None:
            cat["google_updated"] = {"diff_mask": gu.get("diff_mask") or "", "pending_mask": gu.get("pending_mask") or "", "checked_at": now.isoformat()}
    return cat, errors


def types_for(catalog: dict | None, category_ids: list[str]) -> list[dict]:
    """The predefined service types of the given categories, de-duplicated."""
    st = (catalog or {}).get("service_types") or {}
    seen, out = set(), []
    for cid in category_ids:
        for t in st.get(cid, []):
            if t["id"] not in seen:
                seen.add(t["id"])
                out.append(t)
    return out


def google_changed_fields(catalog: dict | None) -> set[str]:
    """Top-level profile fields Google reports as different from the merchant's data (diffMask), as FlowQR field keys. The engine never proposes over these and never reverts them."""
    mask = ((catalog or {}).get("google_updated") or {}).get("diff_mask") or ""
    names = {m.strip().split(".")[0] for m in mask.split(",") if m.strip()}
    mapping = {"profile": "description", "regularHours": "hours", "specialHours": "special_hours", "categories": "categories", "websiteUri": "website", "phoneNumbers": "phone",
               "serviceItems": "services", "serviceArea": "service_area", "title": "title"}
    return {mapping[n] for n in names if n in mapping}
