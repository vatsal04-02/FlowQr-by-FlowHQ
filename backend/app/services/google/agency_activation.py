"""Is the agency path READY to be switched on? A read-only readiness check (`python -m app.cli google-agency-activation-check`).

It changes nothing and calls Google only with --live (the same read-only check `google-agency-check` makes). It exists so that switching the agency path on is a validated, repeatable decision instead of a
hope: every precondition is its own line, and each one that is not met says who has to act. Preconditions marked EXTERNAL cannot be satisfied by code: they need Google's written answer, and nothing here
(or anywhere) may be filled in to make a line pass.

    PASS     met
    BLOCK    not met; `who` says whether it is a CONFIG change, an EXTERNAL answer from Google, or DATA still to be registered

The agency path is READY only when no line is BLOCK. READY is a statement about FlowQR's configuration and data, never about Google's approval.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import GoogleAgencyAccount, GoogleAgencyAuthorization
from app.services.google import agency

PASS, BLOCK = "PASS", "BLOCK"
PROJECT_MODEL = "flowhq_own_project"  # the ONLY model the code supports: FlowHQ's own approved project, used by FlowHQ's own agency login, never handed to another agency or client (see GOOGLE_PROJECT_ARCHITECTURE_OPTIONS.md)


@dataclass
class Line:
    name: str
    status: str
    who: str  # CONFIG | EXTERNAL | DATA | -
    detail: str


def _ids_ok(value: str) -> bool:
    return bool(re.fullmatch(r"accounts/[0-9]{15,}", (value or "").strip()))


def lines(db: Session) -> list[Line]:
    s = settings
    out: list[Line] = []

    def add(name, ok, who, good, bad):
        out.append(Line(name, PASS if ok else BLOCK, "-" if ok else who, good if ok else bad))

    add("project model", s.google_agency_project_model == PROJECT_MODEL, "EXTERNAL",
        "GOOGLE_AGENCY_PROJECT_MODEL=flowhq_own_project: FlowHQ's own project, used only by FlowHQ's own agency login",
        "GOOGLE_AGENCY_PROJECT_MODEL is not set to flowhq_own_project. Google's published rules on agencies and the project are not answered for this case in writing; set it only when they are (docs/audits/GOOGLE_PROJECT_ARCHITECTURE_OPTIONS.md)")
    internal = bool(s.google_agency_internal_only and s.google_agency_operator_set and s.google_agency_internal_decision.strip())
    if s.google_agency_policy_reference.strip():
        basis_detail, basis_ok = "a policy reference is recorded (what it points to is for a person to check)", True
    elif internal:
        basis_detail, basis_ok = "INTERNAL-ONLY basis: the owner's own recorded decision for FlowHQ's own operators. This is NOT a Google approval and does not extend to any customer or other agency", True
    else:
        basis_detail, basis_ok = "", False
    add("authorization basis", basis_ok, "EXTERNAL", basis_detail,
        "neither a recorded Google answer (GOOGLE_AGENCY_POLICY_REFERENCE, never invent one) nor an internal-only decision (GOOGLE_AGENCY_INTERNAL_ONLY, GOOGLE_AGENCY_OPERATOR_EMAILS, GOOGLE_AGENCY_INTERNAL_DECISION) is set")
    add("internal operators enforced", bool(s.google_agency_internal_only and s.google_agency_operator_set), "CONFIG",
        f"internal-only is on and {len(s.google_agency_operator_set)} operator(s) are listed: the backend refuses everyone else", "internal-only is off or no operator is listed: any business admin could start agency operations (only acceptable once Google has answered for third parties)")
    add("agency manager switch", bool(s.google_agency_manager_enabled), "CONFIG", "GOOGLE_AGENCY_MANAGER_ENABLED is on", "GOOGLE_AGENCY_MANAGER_ENABLED is off")
    add("agency operations switch", bool(s.google_agency_operations_enabled), "CONFIG", "GOOGLE_AGENCY_OPERATIONS_ENABLED is on", "GOOGLE_AGENCY_OPERATIONS_ENABLED is off")
    add("agency token key", bool(s.agency_token_encryption_key) and s.agency_token_encryption_key not in (s.token_encryption_key, s.secret_key), "CONFIG",
        "AGENCY_TOKEN_ENCRYPTION_KEY is set and differs from the customer token key and the secret key", "AGENCY_TOKEN_ENCRYPTION_KEY is missing or equals another key")
    add("location group id", _ids_ok(s.google_agency_location_group_id), "CONFIG", "GOOGLE_AGENCY_LOCATION_GROUP_ID is a complete resource name",
        "GOOGLE_AGENCY_LOCATION_GROUP_ID is missing or is not a complete `accounts/<long id>` resource name (a short accountNumber is not accepted)")
    add("organisation id", (not s.google_agency_organization_id) or (_ids_ok(s.google_agency_organization_id) and s.google_agency_organization_id != s.google_agency_location_group_id), "CONFIG",
        "organisation id is a complete resource name and is not the group", "GOOGLE_AGENCY_ORGANIZATION_ID is malformed or equals the group")
    add("no individual fallback", not s.google_agency_individual_fallback, "CONFIG", "the individual-e-mail fallback is off (group delegation only)", "GOOGLE_AGENCY_INDIVIDUAL_FALLBACK is on")
    add("retention running", bool(s.google_content_retention_enabled), "CONFIG", "Google content retention is on, so what the agency path reads is expired on schedule",
        "GOOGLE_CONTENT_RETENTION_ENABLED is off: the agency path must not start storing Google content without expiry")
    login = db.scalar(select(GoogleAgencyAccount).where(GoogleAgencyAccount.status == "active", GoogleAgencyAccount.location_group_name.is_not(None)).limit(1))
    add("agency login registered", login is not None, "DATA", "an active agency login with a Location Group is registered in this database",
        "no active agency login with a Location Group is registered in this database (register it with google-agency-register --listen --expect-email; the token is stored encrypted, in this database only)")
    if login is not None:
        add("login group matches", _ids_ok(s.google_agency_location_group_id) and login.location_group_name == s.google_agency_location_group_id.strip(), "DATA",
            "the registered login's group equals the configured group", "the registered login's group differs from GOOGLE_AGENCY_LOCATION_GROUP_ID")
    n_active = db.scalar(select(func.count()).select_from(GoogleAgencyAuthorization).where(GoogleAgencyAuthorization.status == "active")) or 0
    out.append(Line("active authorizations", PASS, "-", f"{n_active} active authorization(s); each needs the client's recorded consent (nothing is switched without it)"))
    add("emergency stop kept", bool(s.autonomy_emergency_stop), "CONFIG", "AUTONOMY_EMERGENCY_STOP is on (unchanged)", "AUTONOMY_EMERGENCY_STOP is off: this is not changed by the agency work")
    add("registration allowlist kept", s.registration_mode == "allowlist", "CONFIG", "REGISTRATION_MODE=allowlist (unchanged)", "REGISTRATION_MODE is not allowlist")
    out.append(Line("operations gate answers", PASS if agency.operations_enabled() else BLOCK, "-" if agency.operations_enabled() else "CONFIG",
                    "agency.operations_enabled() is true" if agency.operations_enabled() else "agency.operations_enabled() is false right now: no agency token is used for any request"))
    return out


def ready(items: list[Line]) -> bool:
    return all(i.status == PASS for i in items)
