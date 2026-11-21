"""A READ-ONLY check that FlowQR's agency Google login really reaches its LocationGroup and a client's location THROUGH that group.

Seeing the location in the Business Profile Manager website proves nothing about the API, so this makes the real calls with the stored agency token and reports each one separately
(`python -m app.cli google-agency-check`). It never writes: no invitation, edit, reply, post, photo or removal; the only calls are reads, and the only state it touches is the agency token's own
refresh (which any use of the token does). It prints no token and no Google content: the other clients in the group are COUNTED, never named, and a review is counted, never shown.

Each step is its own result, PASS | FAIL | SKIP, so a failure says exactly which link is missing:
    identity          the stored login is the expected account AND Google, asked with its token right now, says it is that account (never the label)
    accounts.list     the group is listed under the agency token, as `accounts/<group>`, typed LOCATION_GROUP (not the organisation, not a personal account)
    group locations   accounts/<group>/locations answers (the count of the group's locations is reported, never their names)
    location match    the requested location id appears in that list, under the group's own account
    location read     a review page is readable at accounts/<group>/locations/<id>, the very path the review sync uses
    tenant mapping    which FlowQR business and connection hold that location in THIS database (exactly one business; two is a FAIL)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select

from app.core.config import settings
from app.core.db import system_session
from app.models import GoogleAgencyAccount, GoogleConnection, GoogleLocation
from app.services import google as g
from app.services.google import agency
from app.services.google import agency_client as ac
from app.services.google.agency_client import location_key, looks_like_account_number

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


@dataclass
class Check:
    name: str
    status: str
    detail: str


def location_name(value: str) -> str:
    """`locations/123`, `123` and `accounts/9/locations/123` -> `locations/123`. Anything that is not a numeric id is refused before a request exists."""
    key = location_key(value)
    if not re.fullmatch(r"[0-9]+", key):
        raise ValueError("A Google location id is numeric, e.g. locations/1234567890123456789")
    return f"locations/{key}"


def _fail_text(exc: Exception) -> str:
    if isinstance(exc, g.GoogleRateLimited):
        return "Google rate limit: try again in a few minutes"
    if isinstance(exc, g.GoogleApiNotApproved):
        return "Google has not approved FlowQR for Business Profile API access (or the API is disabled)"
    if isinstance(exc, g.GoogleAPIError):
        return f"Google answered {exc.status}"
    return type(exc).__name__


def _norm(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def _not_listed_detail(group_name: str, accounts) -> str:
    """Why the group is not among the accounts this login can list. Names the resource Google RETURNED when the number matches an accountNumber exactly; otherwise lists what the login can list (ids,
    types and accountNumbers: never names) and says so. It never works out or invents a resource id."""
    number = group_name.removeprefix("accounts/")
    base = f"{group_name} is not among the {len(accounts)} account(s) this login can list"
    hit = next((a for a in accounts if a.account_number and a.account_number == number), None)
    if hit is not None:
        if hit.type == "LOCATION_GROUP":
            use = f"That is the Location Group. Use its resource name {hit.name} for GOOGLE_AGENCY_LOCATION_GROUP_ID and --location-group-id."
        elif hit.type == "ORGANIZATION":
            use = f"That is the ORGANISATION ({hit.name}), which is never used as a group. The group is a different account of type LOCATION_GROUP."
        else:
            use = f"That account is typed {hit.type or 'nothing'}, not LOCATION_GROUP."
        return (f"{base}, but {number} is the accountNumber of {hit.name}: a short display reference, not the API resource name (`accounts/{number}` is 404 at the API; the resource name is `accounts/{{account_id}}`, "
                f"here {hit.name}). {use}")
    shown = [f"{a.name} ({a.type or 'untyped'}" + (f", accountNumber {a.account_number}" if a.account_number else "") + ")" for a in accounts[:10]]
    listing = "; ".join(shown) + (f"; and {len(accounts) - 10} more" if len(accounts) > 10 else "")
    hint = (f" {number} looks like an accountNumber (a short display reference), not an API resource name." if looks_like_account_number(group_name) else "")
    return (f"{base}: it is not a member or administrator of the group, or {group_name} is not the API resource name of an account this login can see.{hint} "
            f"No listed account has accountNumber {number}. This login can list: {listing or 'nothing'}. Nothing was guessed: use one of those resource names, or have the login added to the group in Business Profile Manager.")


def run_checks(*, account: str | None, expected_email: str, locations: list[str] | None = None, connection_id=None, group: str | None = None, client=None, title: str | None = None) -> list[Check]:
    """Every check, in order. A failed step stops the steps that depend on it (they are reported as SKIP), so one missing link is never hidden behind a later PASS."""
    out: list[Check] = []
    want_email = (expected_email or "").strip().lower()
    if not want_email:
        return [Check("identity", FAIL, "No expected agency e-mail was given")]

    # ---- the stored login
    with system_session() as s:
        rows = list(s.scalars(select(GoogleAgencyAccount).order_by(GoogleAgencyAccount.created_at)))
        pick = [r for r in rows if account and account.strip().lower() in (r.label.lower(), r.google_email.lower())] if account else rows
        row = pick[0] if len(pick) == 1 else None
        if row is None:
            return [Check("identity", FAIL, "No agency login is registered in this database" if not rows else "No single agency login matches that label or e-mail")]
        acct_id, stored_email, stored_sub, stored_group, status = row.id, row.google_email, row.google_sub, row.location_group_name, row.status
    if stored_email != want_email:
        return [Check("identity", FAIL, "The stored agency login is a different Google account from the expected one")]
    if status != "active":
        return [Check("identity", FAIL, f"The agency login is {status}, not active")]

    try:
        client = client or ac.get_agency_client()
        token = agency.agency_access_token(acct_id, client)
        info = client.get_userinfo(token)
    except (g.GoogleError, agency.AgencyError) as exc:
        return [Check("identity", FAIL, f"Could not use the agency token: {_fail_text(exc)}")]
    live_email = (info.get("email") or "").strip().lower()
    if live_email != want_email or (stored_sub and info.get("sub") != stored_sub):
        return [Check("identity", FAIL, "Google says this token belongs to a different account from the expected one")]
    out.append(Check("identity", PASS, f"{want_email} (confirmed by Google with the stored token, not by the label)"))

    # ---- the group
    try:
        group_name = ac.normalize_group(group or stored_group or settings.google_agency_location_group_id)
        agency.refuse_if_organisation(group_name)
    except (ValueError, agency.AgencyError) as exc:
        return out + [Check("accounts.list", FAIL, str(exc) if isinstance(exc, agency.AgencyError) else "No LocationGroup id is configured for this agency login")]
    try:
        accounts = client.list_accounts(token)
    except g.GoogleError as exc:
        return out + [Check("accounts.list", FAIL, _fail_text(exc))]
    mine = next((a for a in accounts if a.name == group_name), None)
    if mine is None:
        return out + [Check("accounts.list", FAIL, _not_listed_detail(group_name, accounts))]
    if mine.type != "LOCATION_GROUP":
        return out + [Check("accounts.list", FAIL, f"{group_name} is typed {mine.type or 'nothing'}, not LOCATION_GROUP")]
    out.append(Check("accounts.list", PASS, f"{group_name} is listed and typed LOCATION_GROUP ({len(accounts)} account(s) visible in all)"))

    try:
        listed = client.list_group_locations(token, group_name)
    except g.GoogleError as exc:
        return out + [Check("group locations", FAIL, _fail_text(exc))]
    out.append(Check("group locations", PASS, f"{group_name}/locations answered: {len(listed)} location(s) in the group (other clients are counted, never named)"))

    # ---- which locations to look for
    wanted: list[str] = []
    try:
        wanted += [location_name(x) for x in (locations or [])]
    except ValueError as exc:
        return out + [Check("location match", FAIL, str(exc))]
    if connection_id:
        with system_session() as s:
            wanted += [location_name(n) for n in s.scalars(select(GoogleLocation.google_location_name).where(GoogleLocation.connection_id == connection_id, GoogleLocation.selected.is_(True)))]
    if title:
        needle = _norm(title)
        found = [x for x in listed if needle and needle in _norm(x.title)]
        if len(found) != 1:
            return out + [Check("title match", FAIL, "No location in the group has a title containing that text" if not found else
                                f"{len(found)} locations in the group match that text; none is named here. Use --location with the exact id")]
        out.append(Check("title match", PASS, f"exactly one location in the group matches: {found[0].name} (\"{found[0].title}\"), listed under {found[0].account_name}"))
        wanted.append(location_name(found[0].name))
    if not wanted:
        return out + [Check("location match", SKIP, "No location was given (use --title, --location or --connection-id)")]

    by_key = {location_key(x.name): x for x in listed}
    for name in dict.fromkeys(wanted):
        tag = name
        hit = by_key.get(location_key(name))
        if hit is None:
            out += [Check("location match", FAIL, f"{tag} is NOT listed under {group_name}"), Check("location read", SKIP, "needs the location match"), _mapping(name)]
            continue
        if hit.account_name != group_name:
            out += [Check("location match", FAIL, f"{tag} is listed, but under {hit.account_name}, not {group_name}"), Check("location read", SKIP, "needs the location match"), _mapping(name)]
            continue
        out.append(Check("location match", PASS, f"{tag} is listed under {group_name} (\"{hit.title or 'untitled'}\")"))
        try:
            page = client.list_reviews(token, group_name, name)
            out.append(Check("location read", PASS, f"{group_name}/{name}/reviews answered ({len(page.reviews)} review(s) on the first page; none shown)"))
        except g.GoogleError as exc:
            out.append(Check("location read", FAIL, f"{group_name}/{name}/reviews: {_fail_text(exc)}"))
        out.append(_mapping(name))
    return out


def _mapping(name: str) -> Check:
    """Which FlowQR business holds this Google location in THIS database. Ids only; nothing about any other business."""
    key = location_key(name)
    with system_session() as s:
        rows = s.execute(select(GoogleLocation.tenant_id, GoogleLocation.connection_id, GoogleLocation.selected, GoogleConnection.auth_mode, GoogleConnection.status)
                         .join(GoogleConnection, GoogleConnection.id == GoogleLocation.connection_id)
                         .where(GoogleLocation.google_location_name.in_((f"locations/{key}", key)))).all()
    if not rows:
        return Check("tenant mapping", SKIP, f"No FlowQR connection in this database holds {name}")
    tenants = {r[0] for r in rows}
    if len(tenants) > 1:
        return Check("tenant mapping", FAIL, f"{name} is held by {len(tenants)} different businesses: a person must decide which one owns it")
    t, c, sel, mode, st = rows[0]
    more = f" ({len(rows)} connection rows, one business)" if len(rows) > 1 else ""
    return Check("tenant mapping", PASS, f"business {t}, connection {c}, mode {mode}, status {getattr(st, 'value', st)}, selected {sel}{more}")


def ok(checks: list[Check]) -> bool:
    """True when nothing FAILED and the checks that matter all ran (a SKIP before the group steps is a failure of the whole run, because nothing was proven)."""
    return bool(checks) and not any(c.status == FAIL for c in checks) and any(c.name == "location read" and c.status == PASS for c in checks)
