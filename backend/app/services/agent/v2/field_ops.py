"""The ONE place that knows how each profile field is read from, dry-run against and written to Google. The executor calls these; it contains no per-field branches of its own.

    live_value   read the field from Google now, as a canonical value (autonomy_policy.canon form)
    validate     the dry run made before any write: Google's own validateOnly for location fields; Google's attribute metadata for attributes (updateAttributes has no validateOnly)
    write        send the change. Services, special hours and attributes are COMPLETE-list operations: the caller passes the full resulting value, never a delta
    same         are two canonical values the same thing? (read-back comparison)

A field that is not V2 goes through exactly the code path it always did (get_location_details / update_location); validation for it is recorded as "skipped".
"""
from __future__ import annotations

from app.services.agent import autonomy_policy as pol
from app.services.agent.v2 import fields as v2f


def live_value(provider, token: str, location_name: str, fk: str) -> tuple[dict | None, object]:
    """(live details or None, canonical value). Attributes live on their own resource, so they are read there."""
    if fk == "attributes":
        return None, v2f.canon_attributes(provider.get_attributes_normalized(token, location_name))
    live = provider.get_location_details(token, location_name)
    return live, pol.field_value(live, fk)


def same(fk: str, a, b) -> bool:
    return a == b  # every canonical form is already order-stable and de-duplicated


def _changes(fk: str, canonical) -> dict:
    if fk == "categories":
        return {"categories": canonical}
    return {fk: canonical}


def validate(provider, token: str, location_name: str, fk: str, canonical, *, live: dict | None = None, current=None) -> dict:
    """{"status": "validated"|"rejected"|"skipped", "method", "errors": [...], "detail"}. Google's own errors are returned verbatim, never swallowed. Raises on a transient/transport
    error so the executor can schedule a retry instead of treating it as a verdict."""
    if fk not in pol.V2_FIELDS:
        return {"status": "skipped", "method": None, "errors": [], "detail": "this field is written by the existing, already-governed path"}
    if fk == "attributes":
        meta = provider.attribute_metadata_for_location(token, location_name)
        send, gone = v2f.attributes_changed(current or [], canonical or [])
        errors = [e for a in send for e in v2f.validate_attribute_against_metadata(a, meta.get(a["name"]))]
        for n in gone:
            if n not in meta:
                errors.append(f"{n}: Google does not list this attribute for the business, so it cannot be removed here.")
        return {"status": "rejected" if errors else "validated", "method": "attribute_metadata", "errors": errors,
                "detail": f"{len(send)} to set, {len(gone)} to remove, checked against Google's attribute list for this business"}
    if fk == "special_hours" and live is not None and not live.get("has_regular_hours"):
        return {"status": "rejected", "method": "precondition", "errors": ["Google needs regular opening hours before it accepts special hours."], "detail": "regular hours are not set"}
    if not hasattr(provider, "validate_changes"):
        return {"status": "skipped", "method": None, "errors": [], "detail": "this Google provider cannot dry-run a change"}
    from app.services.google.errors import GoogleAPIError

    try:
        provider.validate_changes(token, location_name, _changes(fk, canonical))
    except GoogleAPIError as exc:
        if getattr(exc, "status", None) == 400:  # Google's verdict on THIS value: a validation failure, not a transport problem
            return {"status": "rejected", "method": "validateOnly", "errors": [str(exc)[:400]], "detail": "Google refused the change in its dry run"}
        raise
    return {"status": "validated", "method": "validateOnly", "errors": [], "detail": "Google accepted the change in its dry run (nothing was changed)"}


def write(provider, token: str, location_name: str, fk: str, raw, canonical, *, current=None):
    """Send the change. Returns Google's answer (or None). `raw` is what the legacy path sends untouched; V2 fields send the canonical complete value."""
    if fk == "attributes":
        send, gone = v2f.attributes_changed(current or [], canonical or [])
        return provider.update_attributes(token, location_name, send, gone)
    if fk in pol.V2_FIELDS:
        return provider.update_location(token, location_name, _changes(fk, canonical))
    return provider.update_location(token, location_name, {fk: raw})


def returned_value(result, fk: str):
    """What Google's write response itself says the field now is (recorded in the history; the verdict still comes from the separate read-back)."""
    if fk == "attributes" or not isinstance(result, dict):
        return None
    return pol.field_value(result, fk)
