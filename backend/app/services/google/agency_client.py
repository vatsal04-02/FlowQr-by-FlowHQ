"""The Google calls the agency-manager flow needs, behind an interface (docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md, Option B).

`HttpAgencyClient` reuses `HttpGoogleProvider` (same transport, error mapping and OAuth client) and adds the Account Management calls. Nothing here is exercised
against live Google: tests/test_google_agency_client.py pins each request against a mock transport, and the two-account runbook
(docs/runbooks/GOOGLE_AGENCY_TWO_ACCOUNT_TEST.md) is the only way to prove Google behaves as documented.

What was read in Google's reference on 2026-11-21 (developers.google.com/my-business/reference/accountmanagement/rest/v1/...):
  * locations.admins.create   POST   /v1/locations/{id}/admins          body Admin {admin: <email>, role}; returns the Admin; the invitee must accept.   CONFIRMED
  * invitations.accept        POST   /v1/accounts/{a}/invitations/{i}:accept   empty body, empty response                                                 CONFIRMED
  * invitations.list          GET    /v1/accounts/{a}/invitations       "Lists pending invitations for the specified account"                              CONFIRMED (shape below is not)
  * locations.admins.list     GET    /v1/locations/{id}/admins          returns admins[]                                                                   CONFIRMED (per-field content is not)
  * locations.admins.delete   DELETE /v1/locations/{id}/admins/{admin}  "Removes the specified admin as a manager of the specified location"             CONFIRMED
All of them need the business.manage scope. The role is ALWAYS MANAGER: neither invite call has a role parameter on purpose.

TWO different invitation targets (InviteTarget), never mixed in one request:
  * invite_location_group  POST /v1/locations/{id}/admins  body {"account": "accounts/<id>", "role": "MANAGER"}  (Admin.account, documented as the way to invite a LocationGroup;
                           when `account` and `admin` are both set Google ignores the e-mail, so the group call has NO e-mail parameter at all)
  * invite_manager         the same URL with {"admin": <email>, "role": "MANAGER"}: one person. The documented fallback only.
What Google's pages do NOT say about a group invitation (where it appears, who may accept, how the agency user reaches the group) is marked TODO(verify) below and in section 11 of the design doc.

Everything marked TODO(verify) is something the reference does not say. It is repeated in docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md section 8.
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

import httpx

from app.services.google.errors import GoogleAPIError
from app.services.google.provider import REVOKE_URL, GAccount, GLocation, HttpGoogleProvider

ACCOUNT_MGMT_URL = "https://mybusinessaccountmanagement.googleapis.com/v1"
AGENCY_ROLE = "MANAGER"  # never OWNER, PRIMARY_OWNER or SITE_MANAGER (SITE_MANAGER cannot be created through this API anyway)


class InviteTarget(str, Enum):
    """WHAT is invited as manager. They are different things at Google and are never mixed in one request.
    INDIVIDUAL_AGENCY_USER  one person's e-mail in Admin.admin: access follows that one Google login.   (documented fallback only)
    FLOWHQ_LOCATION_GROUP   a LocationGroup in Admin.account (`accounts/<id>`): access follows membership of that group. The intended architecture."""

    INDIVIDUAL_AGENCY_USER = "individual_agency_user"
    FLOWHQ_LOCATION_GROUP = "flowhq_location_group"


_GROUP = re.compile(r"accounts/[0-9]+")


SHORT_NUMBER_DIGITS = 15  # OBSERVED, not documented: Google's accountNumber references are 10 digits and its account resource ids 21. Used only to WARN; it never decides anything.


def looks_like_account_number(value: str | None) -> bool:
    """True for a short all-digit value, bare or after `accounts/`. Google shows an account's `accountNumber` (a display reference such as 5488245563) in Business Profile Manager, but the API
    names the account `accounts/{account_id}` with a much longer id, and `accounts/<accountNumber>` does not exist there (404). This is a hint for messages only: whether a value really is an
    accountNumber is decided by comparing it with what Google's accounts.list returns (agency_check), never by its length."""
    v = (value or "").strip().removeprefix("accounts/")
    return v.isdigit() and len(v) < SHORT_NUMBER_DIGITS


def normalize_group(value: str | None) -> str:
    """The SHAPE of a Location Group resource name: `accounts/<digits>`, so the complete form from accounts.list (`accounts/114863040359228435467`) is accepted unchanged, and a bare number gets the
    `accounts/` prefix. Only the shape is checked: whether Google knows that account, and whether it is the accountNumber reference instead of the resource id, is decided by the live check
    (`google-agency-check`). Anything that is not digits is refused: a typo must not become a request to Google."""
    v = (value or "").strip()
    v = v if v.startswith("accounts/") else f"accounts/{v}"
    if not _GROUP.fullmatch(v):
        raise ValueError("A LocationGroup is given by its API resource name, accounts/ followed by digits, exactly as accounts.list returns it (not the short accountNumber shown in Business Profile Manager)")
    return v


@dataclass
class AdminEntry:
    name: str  # locations/{id}/admins/{admin_id}: what delete needs. Returned by the invite call.
    email: str | None = None  # TODO(verify): the reference says `admin` is "only needed during creation", so a list may not return it
    role: str | None = None
    pending: bool = False  # Admin.pendingInvitation (output only)
    account: str | None = None  # Admin.account: `accounts/<id>` when the admin IS a LocationGroup. TODO(verify): that list and create answers carry it


@dataclass
class PendingInvitation:
    name: str  # accounts/{account_id}/invitations/{invitation_id}
    location_name: str | None  # Invitation.targetLocation.locationName; None for an account-level invitation
    role: str | None = None
    receiving_account: str | None = None  # the account whose invitation list this was FOUND in (the `parent` of the list call). Read, never assumed


class AgencyAdminClient(Protocol):
    def invite_manager(self, client_token: str, location_name: str, admin_email: str) -> AdminEntry: ...  # INDIVIDUAL_AGENCY_USER (fallback)
    def invite_location_group(self, client_token: str, location_name: str, group_account: str) -> AdminEntry: ...  # FLOWHQ_LOCATION_GROUP
    def list_admins(self, access_token: str, location_name: str) -> list[AdminEntry]: ...
    def list_pending_invitations(self, agency_token: str, accounts: list[str] | None = None) -> list[PendingInvitation]: ...
    def list_group_locations(self, agency_token: str, group_account: str) -> list[GLocation]: ...
    def list_accounts(self, access_token: str) -> list[GAccount]: ...  # accounts.list: each account carries its `type` (PERSONAL, LOCATION_GROUP, USER_GROUP, ORGANIZATION)
    def accept_invitation(self, agency_token: str, invitation_name: str) -> None: ...
    def list_visible_locations(self, agency_token: str) -> list[GLocation]: ...
    def remove_manager(self, access_token: str, admin_name: str) -> None: ...
    def revoke_token(self, token: str) -> bool: ...


def location_key(name: str | None) -> str:
    """`locations/456` and `456` and `accounts/1/locations/456` all name the same location: compare by the last segment."""
    return (name or "").rstrip("/").rsplit("/", 1)[-1]


def _admin(j: dict) -> AdminEntry:
    return AdminEntry(name=j.get("name") or "", email=j.get("admin"), role=j.get("role"), pending=bool(j.get("pendingInvitation")), account=j.get("account"))


class HttpAgencyClient(HttpGoogleProvider):
    def invite_manager(self, client_token: str, location_name: str, admin_email: str) -> AdminEntry:
        """POST locations/{id}/admins with the CLIENT's token. Sends an invitation only; access starts when the invitee accepts."""
        j = self._send("POST", f"{ACCOUNT_MGMT_URL}/{location_name}/admins", client_token, json={"admin": admin_email, "role": AGENCY_ROLE})
        entry = _admin(j)
        if not entry.name:
            raise GoogleAPIError(502, "Google did not return the invitation's admin resource")
        return entry

    def invite_location_group(self, client_token: str, location_name: str, group_account: str) -> AdminEntry:
        """POST locations/{id}/admins with the CLIENT's token and the LocationGroup in `account`. The body carries NO `admin` (e-mail): Google says that when both are set `account` wins and the
        e-mail is ignored, so sending both would only hide a mistake. The group must be a numeric account id; anything else raises before a request exists.

        TODO(verify): the manage-admins page shows `"account": "LocationGroupID"` while the Admin reference says the format is `accounts/{account}`. The reference form is sent."""
        body = {"account": normalize_group(group_account), "role": AGENCY_ROLE}
        entry = _admin(self._send("POST", f"{ACCOUNT_MGMT_URL}/{location_name}/admins", client_token, json=body))
        if not entry.name:
            raise GoogleAPIError(502, "Google did not return the invitation's admin resource")
        return entry

    def list_admins(self, access_token: str, location_name: str) -> list[AdminEntry]:
        j = self._send("GET", f"{ACCOUNT_MGMT_URL}/{location_name}/admins", access_token)
        return [_admin(a) for a in j.get("admins", []) if isinstance(a, dict)]

    def list_pending_invitations(self, agency_token: str, accounts: list[str] | None = None) -> list[PendingInvitation]:
        """Pending LOCATION invitations. With `accounts` (the LocationGroup), ONLY those accounts' invitation lists are read and a refusal (403, 404) is raised, because it means the login has
        no access to the group. Without it, every account the agency login can list is asked and a refusal skips that account (discovery).

        TODO(verify): where an invitation to a LocationGroup appears. The reference only says a list returns invitations "pending for the account"; the group's own list is read first and every
        invitation records the account it was found under (`receiving_account`), so the real answer is captured rather than assumed.

        TODO(verify): which account is the `parent` for an invitation to a location. Every account the login lists is asked, and one that answers 403 or 404 is skipped.
        TODO(verify): the Invitation fields (the page lists name, role, targetAccount, targetLocation{locationName,address,placeId}); `state` is not documented, so it is not read.
        TODO(verify): the list has a `filter` on Invitation.target_type; its syntax is not documented, so the filter is not sent and account-level invitations are dropped here instead."""
        out: list[PendingInvitation] = []
        explicit = accounts is not None
        for acct_name in [normalize_group(x) for x in accounts] if explicit else [a.name for a in self.list_accounts(agency_token)]:
            token = None
            while True:
                try:
                    j = self._send("GET", f"{ACCOUNT_MGMT_URL}/{acct_name}/invitations", agency_token, params={"pageToken": token} if token else None)
                except GoogleAPIError as exc:
                    if exc.status in (403, 404) and not explicit:
                        break
                    raise
                for inv in j.get("invitations", []):
                    loc = (inv.get("targetLocation") or {}).get("locationName") if isinstance(inv, dict) else None
                    if inv.get("name") and loc:
                        out.append(PendingInvitation(name=inv["name"], location_name=loc, role=inv.get("role"), receiving_account=acct_name))
                token = j.get("nextPageToken")  # TODO(verify): the page does not say this list is paged; read if present
                if not token:
                    break
        return out

    def accept_invitation(self, agency_token: str, invitation_name: str) -> None:
        """POST accounts/{a}/invitations/{i}:accept with the AGENCY's token and an empty body."""
        self._send("POST", f"{ACCOUNT_MGMT_URL}/{invitation_name}:accept", agency_token)

    def list_visible_locations(self, agency_token: str) -> list[GLocation]:
        """Every location the agency login can list, with the account it is listed under (Business Information API).

        TODO(verify): after an invitation is accepted, under WHICH account the location appears (the agency's personal account, a location group, or the client's account) is not documented.
        The flow stores whatever account name this returns and uses it for the v4 reviews, posts and media paths, which need `accounts/{a}/locations/{l}`."""
        out: list[GLocation] = []
        for acct in self.list_accounts(agency_token):
            try:
                out += self.list_locations(agency_token, acct.name)
            except GoogleAPIError as exc:
                if exc.status not in (403, 404):
                    raise
        return out

    def list_group_locations(self, agency_token: str, group_account: str) -> list[GLocation]:
        """The locations the LocationGroup itself lists (Business Information `accounts/{group}/locations`), read with the agency user's token. This is how a group invitation is verified: the
        location must be listed UNDER THE GROUP, not merely visible somewhere. A refusal (403, 404) is raised: it means this login has no access to the group.

        TODO(verify): that an accepted location is listed under the LocationGroup this way, and how the agency user's OAuth identity gets access to the group (assumed: it is an owner or manager of the group)."""
        return self.list_locations(agency_token, normalize_group(group_account))

    def remove_manager(self, access_token: str, admin_name: str) -> None:
        """DELETE locations/{id}/admins/{admin}. FlowQR removes ITSELF, so the agency token is used.

        TODO(verify): the reference does not say whether a manager may delete its own admin entry (the Business Profile help says managers can leave). If Google refuses with 403, the flow
        reports it and tells the client to remove FlowQR in Google (Business Profile > People and access)."""
        self._send("DELETE", f"{ACCOUNT_MGMT_URL}/{admin_name}", access_token)

    def revoke_token(self, token: str) -> bool:
        """Revoke an OAuth token at Google and say whether Google confirmed it (the older `revoke` swallows failures; this one must not)."""
        try:
            return self._http.post(REVOKE_URL, data={"token": token}).status_code == 200
        except httpx.HTTPError:
            return False


def get_agency_client() -> AgencyAdminClient:
    """Factory; tests replace this with tests/fake_agency_google.FakeAgencyClient."""
    return HttpAgencyClient()
