"""TEST DOUBLE for the agency-manager Google calls: an in-memory Google with locations, admins, invitations and what the agency login can see.
It implements app.services.google.agency_client.AgencyAdminClient and ALSO the token methods the flow uses on the provider, so one object stands in for both.

Two worlds, because they behave differently at Google (docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md section 11):
  individual  the invitation is for one e-mail and lands in the agency user's own invitation list; the location is then listed for that user.
  group       the invitation is for a LocationGroup (`Admin.account`) and lands in the list of `invitation_account` (the group by default; set it to the user's own account to model the other
              possibility); only a MEMBER of the group can read or accept it, and the location is then listed under the group.

Failure switches (set before the step you want to break):
  invite_error, accept_error, remove_error, list_error, visibility_error, group_list_error: an exception instance raised by that call
  visible_after_accept: False = the invitation is accepted but the location never shows up
  agency_in_group: False = the agency Google USER is not a member of the group (no group access)
  group_visible_account: the account the group's location list reports (a wrong one models "listed somewhere else")
  group_admin_stays_pending: True = the group is listed but its admin entry still says pending
  group_admin_role: the role the group holds after acceptance
  revoke_ok: False = Google does not confirm a token revocation
  list_returns_emails: False = list_admins omits the email (the reference says `admin` is only needed on creation)
"""
from app.services.google.agency_client import AdminEntry, PendingInvitation, location_key, normalize_group
from app.services.google.errors import GoogleAPIError
from app.services.google.provider import GAccount, GLocation, GReviewPage, TokenSet

AGENCY_ACCESS = "agency-access-token"
AGENCY_REFRESH = "agency-refresh-token"
CLIENT_ACCESS = "client-access-token"
CLIENT_REFRESH = "client-refresh-token"
OTHER_ACCESS = "someone-elses-access-token"  # a Google user who is NOT an administrator of the FlowQR group
OTHER_REFRESH = "someone-elses-refresh-token"
GROUP = "accounts/5488245563"  # a FIXTURE id, deliberately shaped like the short accountNumber the owner was first given. Google's REAL resource names are 21 digits, e.g. accounts/114863040359228435467 (see tests/test_google_agency_resource_names.py)


def denied():
    return GoogleAPIError(403, "The caller does not have permission", google_status="PERMISSION_DENIED")


class FakeAgencyClient:
    def __init__(self, agency_email="agency@flowqr.test"):
        self.agency_email = agency_email
        self.admins: dict[str, list[AdminEntry]] = {}  # location key -> admins
        self.invitations: dict[str, str] = {}  # individual invitations: name -> location key (pending, in the agency user's own list)
        self.group_invitations: dict[str, tuple[str, str]] = {}  # group invitations: name -> (location key, account whose list holds it)
        self.agency_sees: set[str] = set()  # location keys the agency login can list as an individual
        self.group_sees: set[str] = set()  # location keys listed under the group
        self.visible_account = "accounts/9001"  # where the location appears for the agency login (individual world)
        self.group = GROUP
        self.place_ids: dict[str, str] = {}  # location key -> the Google place id a listing reports for it (none = not reported)
        self.group_number = None  # the Account.accountNumber accounts.list reports for the group (None = not reported)
        self.org, self.org_number = None, None  # an ORGANIZATION account, listed to a group administrator when set
        self.invitation_account = GROUP
        self.calls: list[tuple] = []  # (method, location or name, token): tokens are asserted on, never printed
        self.requests: list[dict] = []  # what each invite would have sent: {"kind": "individual"|"group", "location", "admin"?, "account"?, "role"}
        self.invite_error = self.accept_error = self.remove_error = self.list_error = self.visibility_error = self.group_list_error = None
        self.visible_after_accept = True
        self.agency_in_group = True
        self.group_visible_account = None
        self.group_admin_token = AGENCY_ACCESS  # the ONLY token Google treats as an administrator of the group
        self.group_type = "LOCATION_GROUP"  # what accounts.list reports for the group (set "ORGANIZATION" to model the wrong id)
        self.account_lists: list[str] = []  # tokens that called accounts.list (kept apart from `calls`)
        self.group_admin_stays_pending = False
        self.group_admin_role = "MANAGER"
        self.hidden: set[str] = set()  # location keys that never show up for the agency login
        self.revoke_ok = True
        self.list_returns_emails = True
        self.revoked: list[str] = []
        self.refresh_calls = 0
        self.fail_refresh_with = None
        self._n = 0

    def _is_group_admin(self, token):
        return self.agency_in_group and token == self.group_admin_token

    def _can_see(self, key, token=AGENCY_ACCESS):
        return key in self.agency_sees or (self._is_group_admin(token) and key in self.group_sees)

    # ---- AgencyAdminClient: individual ----
    def invite_manager(self, client_token, location_name, admin_email):
        self.calls.append(("invite", location_name, client_token))
        self.requests.append({"kind": "individual", "location": location_name, "admin": admin_email, "role": "MANAGER"})
        if self.invite_error:
            raise self.invite_error
        key = location_key(location_name)
        if any(a.email == admin_email for a in self.admins.get(key, [])):
            raise GoogleAPIError(409, "already invited", google_status="ALREADY_EXISTS")
        self._n += 1
        entry = AdminEntry(name=f"locations/{key}/admins/adm{self._n}", email=admin_email, role="MANAGER", pending=True)
        self.admins.setdefault(key, []).append(entry)
        self.invitations[f"accounts/9001/invitations/inv{self._n}"] = key
        return AdminEntry(entry.name, admin_email, "MANAGER", True)

    # ---- AgencyAdminClient: LocationGroup ----
    def invite_location_group(self, client_token, location_name, group_account):
        self.calls.append(("invite_group", location_name, client_token))
        self.requests.append({"kind": "group", "location": location_name, "account": group_account, "role": "MANAGER"})  # no `admin` key, ever
        if self.invite_error:
            raise self.invite_error
        key = location_key(location_name)
        if any(a.account == group_account for a in self.admins.get(key, [])):
            raise GoogleAPIError(409, "already invited", google_status="ALREADY_EXISTS")
        self._n += 1
        entry = AdminEntry(name=f"locations/{key}/admins/grp{self._n}", email=None, role="MANAGER", pending=True, account=group_account)
        self.admins.setdefault(key, []).append(entry)
        self.group_invitations[f"{self.invitation_account}/invitations/ginv{self._n}"] = (key, self.invitation_account)
        return AdminEntry(entry.name, None, "MANAGER", True, group_account)

    def list_admins(self, access_token, location_name):
        self.calls.append(("list_admins", location_name, access_token))
        if self.list_error:
            raise self.list_error
        key = location_key(location_name)
        if access_token != CLIENT_ACCESS and not self._can_see(key, access_token) and not any(a.pending for a in self.admins.get(key, [])):
            raise denied()
        return [AdminEntry(a.name, a.email if self.list_returns_emails else None, a.role, a.pending, a.account) for a in self.admins.get(key, [])]

    def list_pending_invitations(self, agency_token, accounts=None):
        if accounts is None:
            self.calls.append(("list_invitations", None, agency_token))
            out = [PendingInvitation(n, f"locations/{k}", "MANAGER", self.visible_account) for n, k in self.invitations.items()]
            for n, (k, acct) in self.group_invitations.items():
                if acct != self.group or self._is_group_admin(agency_token):  # a group's list is only readable by its administrator
                    out.append(PendingInvitation(n, f"locations/{k}", "MANAGER", acct))
            return out
        self.calls.append(("list_group_invitations", ",".join(accounts), agency_token))
        out = []
        for acct in [normalize_group(x) for x in accounts]:
            if acct == self.group and not self._is_group_admin(agency_token):
                raise denied()
            out += [PendingInvitation(n, f"locations/{k}", "MANAGER", a) for n, (k, a) in self.group_invitations.items() if a == acct]
        return out

    def accept_invitation(self, agency_token, invitation_name):
        self.calls.append(("accept", invitation_name, agency_token))
        if self.accept_error:
            raise self.accept_error
        if invitation_name in self.group_invitations:
            key, acct = self.group_invitations[invitation_name]
            if acct == self.group and not self._is_group_admin(agency_token):
                raise denied()  # only an administrator of the group may accept for it
            del self.group_invitations[invitation_name]
            for a in self.admins.get(key, []):
                if a.account == self.group:
                    a.pending = self.group_admin_stays_pending
                    a.role = self.group_admin_role
            if self.visible_after_accept:
                self.group_sees.add(key)
            return
        key = self.invitations.pop(invitation_name, None)
        if key is None:
            raise GoogleAPIError(404, "invitation not found", google_status="NOT_FOUND")
        for a in self.admins.get(key, []):
            if a.email == self.agency_email:
                a.pending = False
        if self.visible_after_accept:
            self.agency_sees.add(key)

    def list_visible_locations(self, agency_token):
        self.calls.append(("list_visible", None, agency_token))
        if self.visibility_error:
            raise self.visibility_error
        return [GLocation(self.visible_account, f"locations/{k}", f"Location {k}", None, self.place_ids.get(k)) for k in sorted(self.agency_sees - self.hidden)]

    def list_group_locations(self, agency_token, group_account):
        self.calls.append(("list_group_locations", group_account, agency_token))
        if self.group_list_error:
            raise self.group_list_error
        if normalize_group(group_account) == self.group and not self._is_group_admin(agency_token):
            raise denied()
        return [GLocation(self.group_visible_account or self.group, f"locations/{k}", f"Location {k}", None, self.place_ids.get(k)) for k in sorted(self.group_sees - self.hidden)]

    def remove_manager(self, access_token, admin_name):
        self.calls.append(("remove", admin_name, access_token))
        if self.remove_error:
            raise self.remove_error
        key = location_key(admin_name.split("/admins/")[0])
        if access_token != CLIENT_ACCESS and not self._can_see(key, access_token):
            raise denied()
        self.admins[key] = [a for a in self.admins.get(key, []) if a.name != admin_name]
        if not any(a.account == self.group for a in self.admins.get(key, [])):
            self.group_sees.discard(key)
        if not any(a.email == self.agency_email for a in self.admins.get(key, [])):
            self.agency_sees.discard(key)

    def revoke_token(self, token):
        self.calls.append(("revoke", None, token))
        if self.revoke_ok:
            self.revoked.append(token)
        return self.revoke_ok

    # ---- the provider methods the flow and get_access_token use ----
    def refresh_access_token(self, refresh_token):
        self.refresh_calls += 1
        if self.fail_refresh_with and refresh_token == AGENCY_REFRESH:
            raise self.fail_refresh_with
        return TokenSet({AGENCY_REFRESH: AGENCY_ACCESS, OTHER_REFRESH: OTHER_ACCESS}.get(refresh_token, CLIENT_ACCESS), 3600)

    # ---- profile calls, to prove WHICH token and account the work used ----
    def _profile(self, name, token, account, location):
        self.calls.append((name, f"{account}/{location}", token))
        if token != CLIENT_ACCESS and not self._can_see(location_key(location), token):
            raise denied()

    def list_reviews(self, token, account, location, page_token=None):
        self._profile("list_reviews", token, account, location)
        return GReviewPage(reviews=[])

    def reply_to_review(self, token, account, location, review_id, comment):
        self._profile("reply", token, account, location)
        return {"comment": comment, "state": "APPROVED"}

    def create_post(self, token, account, location, post):
        self._profile("post", token, account, location)
        return {"name": "post-1"}

    def add_media(self, token, account, location, source_url, category):
        self._profile("photo", token, account, location)
        return {"name": "media-1"}

    def fetch_performance(self, token, location, start, end, metrics):
        self._profile("performance", token, "-", location)
        return {}

    def exchange_code(self, code):
        return TokenSet(AGENCY_ACCESS, 3600, AGENCY_REFRESH, "openid email https://www.googleapis.com/auth/business.manage")

    def get_userinfo(self, access_token):
        return {"sub": "agency-sub-1", "email": self.agency_email}

    def list_accounts(self, token):
        """accounts.list: the user's own account, and the LocationGroup when this token belongs to one of its administrators (documented: the response carries each account's `type`)."""
        self.account_lists.append(token)
        out = [GAccount(self.visible_account, "Agency", "PERSONAL")]
        if self._is_group_admin(token):
            out.append(GAccount(self.group, "FlowQR", self.group_type, self.group_number))
            if self.org:
                out.append(GAccount(self.org, "FlowHQ", "ORGANIZATION", self.org_number))
        return out

    def list_locations(self, token, account_name):
        """The Business Information list for an account: for the group that is EVERY location in it, i.e. every client's. Present so a test can prove FlowQR never copies it into one tenant."""
        self.calls.append(("list_locations", account_name, token))
        keys = self.group_sees if account_name == self.group and self._is_group_admin(token) else self.agency_sees
        return [GLocation(account_name, f"locations/{k}", f"Another client's profile {k}", "1 Other Street") for k in sorted(keys)]

    def build_auth_url(self, state):
        return f"https://accounts.google.test/auth?state={state}"

    def revoke(self, token):
        self.revoked.append(token)

    # ---- things that happen in Google outside FlowQR ----
    def client_removes_agency(self, location_name):
        """The business owner removes FlowQR in Google (People and access). Works for an individual and for the group."""
        key = location_key(location_name)
        self.admins[key] = [a for a in self.admins.get(key, []) if a.email != self.agency_email and a.account != self.group]
        self.agency_sees.discard(key)
        self.group_sees.discard(key)
