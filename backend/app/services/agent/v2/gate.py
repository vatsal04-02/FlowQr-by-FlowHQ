"""The Local SEO V2 policy gate: may FlowQR's engine change (or even dry-run a change against) THIS Google profile?

Why it exists. Google's Business Profile API policy page (re-read 2026-11-22) says automatic or programmatic use by end-clients or agencies needs their own Business Profile project,
that end users "need to manually sign in", and that edits may not be automated "without the user's prior specific and express consent". FlowHQ's written clarification on how that applies
to FlowQR's shared project is still pending. A button an owner presses, or a consent they tick, does not answer that question, so neither opens this gate.

The gate is closed unless one of these holds:
  * the profile is a DEDICATED TEST profile (SEO_V2_TEST_LOCATION_NAMES, set by an operator for a profile FlowHQ owns), or
  * SEO_V2_CUSTOMER_WRITES_ENABLED is on AND (outside development) SEO_V2_POLICY_REFERENCE records Google's written answer. Production refuses to start otherwise (core/config.py), and this check
    fails closed again at run time.

What "closed" means: V2 still DETECTS, DISCOVERS and DRAFTS (the owner sees the exact before/after and can make the change in Google themselves), but the action stays `recommended`; it is never
approved into execution, never dry-run with the customer's token, never written. Existing owner-OAuth profile edits and the legacy description/contact engine are not touched by this gate."""
from __future__ import annotations

from app.core.config import settings
from app.models import GoogleLocation
from app.services.agent import autonomy_policy as pol

CLOSED_REASON = ("Changes to this part of your profile are not made by FlowQR yet: Google's rules on automated changes to customers' profiles are still being confirmed with Google in writing. "
                 "FlowQR shows you exactly what to change, and you can make it in Google Business Profile.")


def is_v2_field(field_key: str | None) -> bool:
    return field_key in pol.V2_FIELDS


def is_test_profile(location_name: str | None) -> bool:
    return bool(location_name) and location_name in settings.seo_v2_test_locations


def customer_writes_open() -> bool:
    if not settings.seo_v2_customer_writes_enabled:
        return False
    if settings.hardened and not settings.seo_v2_policy_reference.strip():
        return False  # fail closed even if the start-up guard was bypassed
    return True


def check(gloc: GoogleLocation | None) -> dict:
    """{"allowed", "test_profile", "customer_writes", "reason"}. `allowed` is the only thing callers branch on."""
    test = is_test_profile(getattr(gloc, "google_location_name", None))
    cust = customer_writes_open()
    allowed = test or cust
    return {"allowed": allowed, "test_profile": test, "customer_writes": cust, "reason": None if allowed else CLOSED_REASON}


def status_for(gloc: GoogleLocation | None, field_key: str | None) -> dict:
    """The gate as it applies to one field: a non-V2 field is never held by it."""
    if not is_v2_field(field_key):
        return {"allowed": True, "test_profile": False, "customer_writes": True, "reason": None, "applies": False}
    return {**check(gloc), "applies": True}
