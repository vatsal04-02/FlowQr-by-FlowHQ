"""The LocationGroup sequence as Google documents it (developers.google.com/my-business/content/transfer-locations, "Transferring to a location group", and .../manage-locations):

  1. the MERCHANT's OAuth credentials call locations.admins.create with `account` = the Location Group;
  2. the Location Group ADMINISTRATOR's credentials call accounts.invitations.list with the Location Group as `parent`;
  3. the same administrator calls accounts.invitations.accept;
  4. the Location Group's credentials call accounts.locations.list: the location must appear.

These tests prove FlowQR follows that sequence against a fake Google. They do NOT prove Google behaves as documented: the documented sequence is written for an ownership transfer, and nothing here
can show it is identical for a Manager invitation. Only the manual two-account runbook can. No test makes a live call, sends an invitation, revokes a token or touches production.
"""
import ast
import json
import pathlib
import uuid
from contextlib import closing

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import Settings, config_problems, settings
from app.core.db import system_session
from app.models import GoogleLocation
from app.services import google as g
from app.services.google import agency
from app.services.google.agency_client import HttpAgencyClient
from app.services.google.provider import TokenSet
from tests.conftest import make_business, owner_exec
from tests.fake_agency_google import AGENCY_ACCESS, CLIENT_ACCESS, CLIENT_REFRESH, GROUP, OTHER_ACCESS, OTHER_REFRESH, FakeAgencyClient
from tests.test_google_agency import ADMIN_EMAIL, _clean, advance, auths_of, calls, conn_of, consent, gloc_of, go, mail, seed, untouched  # noqa: F401  (_clean is an autouse fixture)
from tests.test_google_agency_group import gfake  # noqa: F401  (fixture)


def locations_of_tenant(tenant_id) -> list[str]:
    with closing(system_session()) as db:
        return sorted(r.google_location_name for r in db.scalars(select(GoogleLocation).where(GoogleLocation.tenant_id == uuid.UUID(tenant_id))))


def test_refreshing_locations_in_agency_mode_never_copies_other_clients_into_this_business(gfake):
    """The agency Google user sees EVERY client of the FlowQR group. A refresh that listed what that user can see would write other businesses' names and addresses into this one's records."""
    biz = make_business("Leak Clinic")
    s = seed(biz)
    assert go(biz, s) == [("active", None)]
    gfake.group_sees |= {"900001", "900002"}  # two other clients' locations, visible to the agency user through the group
    before = locations_of_tenant(biz.tenant_id)
    n = len(gfake.calls)
    r = biz.post(f"/google/connections/{s.conn_id}/refresh-locations")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "managed_by_flowqr", r.text
    assert locations_of_tenant(biz.tenant_id) == before and "900001" not in str(before)  # nothing from another client was stored
    assert len(gfake.calls) == n  # and Google was not even asked
    assert "Another client" not in biz.get(f"/google/connections/{s.conn_id}/locations").text


def nothing_switched(gfake, s):
    untouched(s)
    assert not calls(gfake, "revoke")


def used_by(gfake) -> dict:
    out: dict[str, set[str]] = {}
    for name, _target, token in gfake.calls:
        out.setdefault(token, set()).add(name)
    return out


# ------------------------------------------------------------------ who uses which credentials, step by step
def test_the_merchants_token_creates_the_invitation_and_never_lists_accepts_or_verifies(gfake):
    biz = make_business("Merchant Token Clinic")
    s = seed(biz)
    assert go(biz, s) == [("active", None)]
    used = used_by(gfake)
    # the merchant's token: the duplicate guard (a read of the admin list at the same step) and the create. It is never used to list invitations, accept, or list the group's locations.
    assert used[CLIENT_ACCESS] == {"list_admins", "invite_group"}
    assert used[AGENCY_ACCESS] == {"list_group_invitations", "accept", "list_group_locations", "list_admins"}
    assert used[CLIENT_REFRESH] == {"revoke"}  # and only at the very end
    names = [c[0] for c in gfake.calls]
    last_merchant = max(i for i, c in enumerate(gfake.calls) if c[2] == CLIENT_ACCESS)
    first_group_admin = min(i for i, c in enumerate(gfake.calls) if c[2] == AGENCY_ACCESS)
    assert last_merchant < first_group_admin and names.index("invite_group") <= last_merchant  # the merchant is finished before the group administrator starts


def test_the_group_administrators_token_lists_the_groups_invitations_with_the_group_as_parent(gfake):
    biz = make_business("Parent Clinic")
    s = seed(biz)
    go(biz, s)
    assert calls(gfake, "list_group_invitations") == [("list_group_invitations", GROUP, AGENCY_ACCESS)]  # parent = the Location Group, not the organisation, not the user's own account
    assert calls(gfake, "list_invitations") == []  # the search across every account the user can see is not used
    assert auths_of(s)[0].receiving_account_name == GROUP


def test_the_group_administrators_token_accepts_the_invitation(gfake):
    biz = make_business("Accept Clinic")
    s = seed(biz)
    go(biz, s)
    (acc,) = calls(gfake, "accept")
    assert acc[2] == AGENCY_ACCESS and acc[1].startswith(f"{GROUP}/invitations/")
    assert auths_of(s)[0].invitation_name == acc[1]


def test_the_groups_credentials_list_the_accepted_location_and_only_then_does_anything_change(gfake):
    biz = make_business("Group Listing Clinic")
    s = seed(biz)
    go(biz, s)
    names = [c[0] for c in gfake.calls]
    assert names.index("accept") < names.index("list_group_locations") < names.index("revoke")
    (lst,) = calls(gfake, "list_group_locations")
    assert lst[1:] == (GROUP, AGENCY_ACCESS)
    assert auths_of(s)[0].agency_account_name == GROUP and gloc_of(s.gids[0]).google_account_name == GROUP


# ------------------------------------------------------------------ the agency identity must already administer the group
def test_the_agency_user_must_already_administer_the_group_before_any_invitation_leaves(gfake):
    gfake.agency_in_group = False
    biz = make_business("Not Admin Clinic")
    s = seed(biz)
    assert go(biz, s) == [("needs_attention", "group_access_missing")]
    assert gfake.calls == [] and gfake.admins == {}  # nothing was sent to Google, not even with the merchant's token
    assert gfake.account_lists == [AGENCY_ACCESS]  # the only call made: the agency user's own accounts.list
    nothing_switched(gfake, s)
    assert mail(ADMIN_EMAIL, "no access to the FlowQR group")
    gfake.agency_in_group = True  # a person adds the user to the group
    assert advance(s, force=True, retry=True) == [("active", None)]
    assert len(calls(gfake, "invite_group")) == 1


def test_a_different_google_user_cannot_complete_the_process(gfake):
    class SomeoneElse(FakeAgencyClient):
        def exchange_code(self, code):
            return TokenSet(OTHER_ACCESS, 3600, OTHER_REFRESH, "openid email https://www.googleapis.com/auth/business.manage")

    owner_exec("DELETE FROM google_agency_accounts")
    agency.register_account("wrong-user", code="c", provider=SomeoneElse("someone@flowqr.test"))  # a login that is NOT an administrator of the group
    biz = make_business("Wrong Identity Clinic")
    s = seed(biz)
    assert go(biz, s) == [("needs_attention", "group_access_missing")]
    assert gfake.calls == [] and gfake.account_lists == [OTHER_ACCESS]
    assert advance(s, force=True, retry=True) == [("needs_attention", "group_access_missing")]  # asking again does not help
    assert gfake.calls == []
    nothing_switched(gfake, s)
    # and Google's own rule, as the fake models it: neither the merchant's token nor a non-administrator's can use the group's calls
    for token in (CLIENT_ACCESS, OTHER_ACCESS):
        with pytest.raises(g.GoogleAPIError):
            gfake.list_pending_invitations(token, [GROUP])
        with pytest.raises(g.GoogleAPIError):
            gfake.list_group_locations(token, GROUP)


def test_the_organisation_id_is_never_a_substitute_for_the_group_id(gfake, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_organization_id", "5234249121")
    with pytest.raises(agency.AgencyError):
        agency.register_account("org-as-group", code="c", provider=FakeAgencyClient("org@flowqr.test"), location_group_id="5234249121")
    with pytest.raises(agency.AgencyError):
        agency.refuse_if_organisation("accounts/5234249121")
    agency.refuse_if_organisation(GROUP)  # the real group is fine
    # a record that somehow targets the organisation is stopped before anything is sent
    biz = make_business("Org Guard Clinic")
    s = seed(biz)
    consent(biz, s)
    monkeypatch.setattr(settings, "google_agency_organization_id", "5488245563")  # misconfiguration: the organisation id now equals the group's
    assert advance(s, force=True) == [("needs_attention", "group_is_organisation")]
    assert gfake.calls == [] and gfake.account_lists == []
    nothing_switched(gfake, s)


@pytest.mark.parametrize("kind,expected", [("ORGANIZATION", "group_is_organisation"), (None, "group_type_unconfirmed"), ("USER_GROUP", "group_type_unconfirmed")])
def test_an_account_that_accounts_list_does_not_type_as_a_location_group_is_refused(gfake, kind, expected):
    gfake.group_type = kind  # what Google reports for that id
    biz = make_business("Type Check Clinic")
    s = seed(biz)
    assert go(biz, s) == [("needs_attention", expected)]
    assert gfake.calls == [] and gfake.admins == {}
    nothing_switched(gfake, s)
    assert mail(ADMIN_EMAIL, "not a Location Group") or mail(ADMIN_EMAIL, "is the organisation")


def test_the_production_guard_refuses_an_organisation_id_used_as_the_group():
    def prod(**over):
        base = dict(app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True, public_card_base_url="https://go.flowqr.co.in",
                    frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in", database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr",
                    platform_admin_emails="ops@flowhq.in", smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
                    card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback", google_client_id="id", google_client_secret="secret",
                    google_agency_manager_enabled=True, agency_token_encryption_key=Fernet.generate_key().decode())
        base.update(over)
        return Settings(_env_file=None, **base)

    assert config_problems(prod(google_agency_location_group_id="5488245563", google_agency_organization_id="5234249121")) == []
    assert any("not a Location Group" in p for p in config_problems(prod(google_agency_location_group_id="5234249121", google_agency_organization_id="accounts/5234249121")))
    assert any("numeric account id" in p for p in config_problems(prod(google_agency_location_group_id="5488245563", google_agency_organization_id="org@flowqr.test")))
    assert Settings(_env_file=None).google_agency_invitation_discovery is False and Settings(_env_file=None).google_agency_organization_id == ""


# ------------------------------------------------------------------ the documented procedure, not a search of everything
def test_without_the_diagnostic_the_invitation_is_only_looked_for_in_the_groups_own_list(gfake):
    gfake.invitation_account = "accounts/9001"  # Google put it somewhere else (the documentation says the group's list)
    biz = make_business("Documented Only Clinic")
    s = seed(biz)
    assert go(biz, s) == [("invited", "invitation_pending")]
    assert calls(gfake, "list_invitations") == [] and calls(gfake, "accept") == []  # no search across the user's other accounts, nothing accepted from elsewhere
    nothing_switched(gfake, s)
    owner_exec("UPDATE google_agency_authorizations SET invite_sent_at = now() - interval '49 hours', next_attempt_at = NULL WHERE connection_id = :c", c=str(s.conn_id))
    assert advance(s, force=True) == [("needs_attention", "invitation_not_found")]
    assert calls(gfake, "accept") == []
    nothing_switched(gfake, s)


# ------------------------------------------------------------------ nothing changes until the GROUP lists the location
def test_a_settled_manager_entry_is_not_enough_the_group_must_list_the_location_before_anything_switches(gfake):
    gfake.visible_after_accept = False  # accepted, the admin list is settled, but the group's own location list does not show it
    biz = make_business("Not Listed Yet Clinic")
    s = seed(biz)
    assert go(biz, s) == [("accepted", "not_visible_yet")]
    (adm,) = gfake.admins[s.key[0]]
    assert adm.account == GROUP and adm.pending is False and adm.role == "MANAGER"  # Google says it is a manager
    nothing_switched(gfake, s)  # and still nothing changed
    gfake.group_sees.add(s.key[0])  # now the group lists it
    owner_exec("UPDATE google_agency_authorizations SET next_attempt_at = NULL WHERE connection_id = :c", c=str(s.conn_id))
    assert advance(s, force=True) == [("active", None)]
    names = [c[0] for c in gfake.calls]
    assert names.index("revoke") > max(i for i, n in enumerate(names) if n == "list_group_locations")  # the revoke came after the last listing


# ------------------------------------------------------------------ the merchant's grant is kept while another connection depends on it
def test_the_merchants_token_is_kept_while_another_connection_uses_the_same_google_user(gfake):
    a_biz, b_biz = make_business("Shared User A"), make_business("Shared User B")
    sa, sb = seed(a_biz), seed(b_biz)
    owner_exec("UPDATE google_connections SET google_sub = 'one-google-user' WHERE id IN (:a, :b)", a=str(sa.conn_id), b=str(sb.conn_id))  # the same Google user connected two businesses
    assert go(a_biz, sa) == [("active", None)]
    ca = conn_of(sa)
    assert ca.auth_mode == "agency_account" and ca.refresh_token_encrypted is not None and not calls(gfake, "revoke")  # switched, but B still depends on that user's grant
    owner_exec("UPDATE google_agency_authorizations SET switched_at = now() - interval '25 hours' WHERE connection_id = :c", c=str(sa.conn_id))
    with closing(system_session()) as db:
        out = agency.housekeeping(db)
    assert out["revoked"] == 0 and out["alerts"] == 0 and not calls(gfake, "revoke")  # a deliberate wait, not a failure, so no alert either
    assert go(b_biz, sb) == [("active", None)]  # B switches; A no longer depends on the user's grant, so B's token is revoked
    assert len(calls(gfake, "revoke")) == 1 and conn_of(sb).refresh_token_encrypted is None
    with closing(system_session()) as db:
        assert agency.housekeeping(db)["revoked"] == 1  # and A's deferred revoke now goes through
    assert len(calls(gfake, "revoke")) == 2 and conn_of(sa).refresh_token_encrypted is None


# ------------------------------------------------------------------ no ownership is ever transferred
def test_no_ownership_is_ever_transferred_or_granted():
    """The transfer-locations page describes moving a listing to another account (locations.transfer, an Owner role). FlowQR only ever invites a MANAGER and never transfers anything."""
    assert not [n for n in dir(HttpAgencyClient) if "transfer" in n.lower() or "owner" in n.lower()]
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "google"
    roles = {"owner", "primary_owner", "site_manager"}  # a role is only ever a whole string; prose such as "never Owner" in a message is not a request

    def requests_ownership(x: str) -> bool:
        x = x.strip().lower()
        return x in roles or ":transfer" in x or "locations.transfer" in x or "destinationaccount" in x or x.startswith("transfer")

    for name in ("agency.py", "agency_client.py", "provider.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body and isinstance(n.body[0], ast.Expr)
                      and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str)}  # documentation may say "we never call locations.transfer"
        literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
        assert not [x for x in literals if requests_ownership(x)], name

    wire = []

    def record(request: httpx.Request) -> httpx.Response:
        wire.append((request.method, str(request.url), request.content.decode() if request.content else ""))
        return httpx.Response(200, json={"name": "locations/1/admins/x", "invitations": [], "locations": [], "accounts": [{"name": GROUP, "type": "LOCATION_GROUP"}]})

    c = HttpAgencyClient(transport=httpx.MockTransport(record))
    c.invite_location_group("T", "locations/1", GROUP)
    c.invite_manager("T", "locations/1", "a@b.test")
    c.list_pending_invitations("T", [GROUP])
    c.list_group_locations("T", GROUP)
    c.list_accounts("T")
    c.list_admins("T", "locations/1")
    c.remove_manager("T", "locations/1/admins/x")
    assert wire and not [w for w in wire if "transfer" in w[1].lower() or "transfer" in w[2].lower()]
    invites = [json.loads(w[2]) for w in wire if w[0] == "POST" and w[1].endswith("/admins")]
    assert len(invites) == 2 and all(b["role"] == "MANAGER" for b in invites) and ("admin" not in invites[0] and invites[0]["account"] == GROUP) and "account" not in invites[1]


def test_every_invitation_the_flow_sends_is_for_a_manager_and_names_only_the_group(gfake):
    biz = make_business("Role Clinic")
    s = seed(biz)
    go(biz, s)
    assert gfake.requests and all(r["role"] == "MANAGER" and r["kind"] == "group" and r["account"] == GROUP for r in gfake.requests)
    assert all(a.role == "MANAGER" for a in gfake.admins[s.key[0]])


def test_the_documented_flow_works_end_to_end_and_the_order_matches_googles(gfake):
    biz = make_business("Documented Order Clinic")
    s = seed(biz)
    assert go(biz, s) == [("active", None)]
    assert gfake.account_lists == [AGENCY_ACCESS]  # step 0: the agency user's accounts.list shows the group
    assert [c[0] for c in gfake.calls] == ["list_admins", "invite_group", "list_group_invitations", "accept", "list_group_locations", "list_admins", "revoke"]
