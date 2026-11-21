"""Contract tests for the LocationGroup calls of HttpAgencyClient: the REAL client code against a mock HTTP transport. Never a live call.
They pin each request to Google's reference (read 2026-11-21: locations.admins `Admin.account`, accounts.invitations.list, accounts.invitations.accept). They prove the code matches the
documentation, not that Google behaves as documented: where the documentation is silent, the test says so."""
import json

import httpx
import pytest

from app.services import google as g
from app.services.google.agency_client import AGENCY_ROLE, HttpAgencyClient, InviteTarget, normalize_group
from tests.test_google_contract import Wire

AM = "https://mybusinessaccountmanagement.googleapis.com/v1"
INFO = "https://mybusinessbusinessinformation.googleapis.com/v1"
GROUP = "accounts/5488245563"


def client(*answers):
    wire = Wire(*answers)
    return HttpAgencyClient(transport=httpx.MockTransport(wire)), wire


def test_the_two_targets_are_explicit_and_named():
    assert {t.name: t.value for t in InviteTarget} == {"INDIVIDUAL_AGENCY_USER": "individual_agency_user", "FLOWHQ_LOCATION_GROUP": "flowhq_location_group"}


def test_a_group_invitation_sends_the_group_in_account_and_nothing_else():
    c, wire = client((200, {"name": "locations/222/admins/g1", "account": GROUP, "role": "MANAGER", "pendingInvitation": True}))
    out = c.invite_location_group("CLIENT-TOKEN", "locations/222", GROUP)
    r = wire.last()
    assert (r.method, str(r.url)) == ("POST", f"{AM}/locations/222/admins")
    assert json.loads(r.content) == {"account": "accounts/5488245563", "role": "MANAGER"}  # exactly the documented shape: no `admin`, no e-mail
    assert r.headers["authorization"] == "Bearer CLIENT-TOKEN"  # the CLIENT invites with their own token
    assert (out.name, out.account, out.pending, out.email) == ("locations/222/admins/g1", GROUP, True, None)


def test_a_group_invitation_can_never_carry_an_email_address():
    """Google says that when `account` and `admin` are both set, `account` wins and the e-mail is ignored, so a request with both would only hide a mistake. This method has no e-mail
    parameter, the role is fixed, and anything that is not a numeric account id is refused BEFORE a request exists."""
    import inspect

    assert list(inspect.signature(HttpAgencyClient.invite_location_group).parameters) == ["self", "client_token", "location_name", "group_account"]
    for bad in ("agency@flowqr.test", "accounts/abc", "locations/5", "", "accounts/", "5488245563 ", "accounts/5488245563/extra"):
        if bad == "5488245563 ":
            assert normalize_group(bad) == GROUP  # surrounding blanks are harmless
            continue
        c, wire = client((200, {}))
        with pytest.raises(ValueError):
            c.invite_location_group("T", "locations/222", bad)
        assert wire.requests == []  # nothing was sent


@pytest.mark.parametrize("given", ["5488245563", "accounts/5488245563", " accounts/5488245563 "])
def test_a_bare_numeric_id_and_the_resource_form_are_the_same_group(given):
    assert normalize_group(given) == GROUP


def test_a_group_invitation_without_an_admin_resource_in_the_answer_is_an_error_not_a_success():
    c, _ = client((200, {}))
    with pytest.raises(g.GoogleAPIError):
        c.invite_location_group("T", "locations/222", GROUP)


def test_the_individual_fallback_still_sends_an_email_and_never_an_account():
    c, wire = client((200, {"name": "locations/222/admins/a1", "admin": "agency@flowqr.test", "role": "MANAGER", "pendingInvitation": True}))
    c.invite_manager("CLIENT-TOKEN", "locations/222", "agency@flowqr.test")
    assert json.loads(wire.last().content) == {"admin": "agency@flowqr.test", "role": "MANAGER"}
    assert AGENCY_ROLE == "MANAGER"


def test_the_groups_own_invitation_list_is_read_with_the_agency_users_token_and_records_where_it_was_found():
    c, wire = client((200, {"invitations": [
        {"name": f"{GROUP}/invitations/i1", "role": "MANAGER", "targetLocation": {"locationName": "locations/222"}},
        {"name": f"{GROUP}/invitations/i2", "role": "MANAGER", "targetAccount": {"name": "accounts/7"}}]}))
    inv = c.list_pending_invitations("AGENCY-TOKEN", [GROUP])
    r = wire.last()
    assert (r.method, str(r.url)) == ("GET", f"{AM}/{GROUP}/invitations") and r.headers["authorization"] == "Bearer AGENCY-TOKEN"
    assert [(i.name, i.location_name, i.receiving_account) for i in inv] == [(f"{GROUP}/invitations/i1", "locations/222", GROUP)]  # account-level invitations are dropped


def test_a_refusal_on_the_groups_own_list_is_raised_because_it_means_no_group_access():
    c, _ = client((403, {"error": {"code": 403, "message": "no", "status": "PERMISSION_DENIED"}}))
    with pytest.raises(g.GoogleAPIError) as exc:
        c.list_pending_invitations("AT", [GROUP])
    assert exc.value.status == 403
    c, _ = client((404, {"error": {"code": 404, "message": "no", "status": "NOT_FOUND"}}))
    with pytest.raises(g.GoogleAPIError):
        c.list_pending_invitations("AT", [GROUP])


def test_discovery_without_a_named_account_skips_refusals_and_records_the_account_each_invitation_came_from():
    def answer(request):
        u = str(request.url)
        if u.startswith(f"{AM}/accounts?"):
            return 200, {"accounts": [{"name": "accounts/1"}, {"name": GROUP}]}
        if "/accounts/1/invitations" in u:
            return 403, {"error": {"code": 403, "message": "no", "status": "PERMISSION_DENIED"}}
        return 200, {"invitations": [{"name": f"{GROUP}/invitations/i9", "targetLocation": {"locationName": "locations/222"}}]}
    c, _ = client(answer)
    assert [(i.name, i.receiving_account) for i in c.list_pending_invitations("AT")] == [(f"{GROUP}/invitations/i9", GROUP)]


def test_the_groups_locations_are_listed_under_the_group_account_and_a_refusal_is_raised():
    c, wire = client((200, {"locations": [{"name": "locations/222", "title": "Clinic"}]}))
    out = c.list_group_locations("AGENCY-TOKEN", "5488245563")
    r = wire.last()
    assert (r.method, str(r.url).split("?")[0]) == ("GET", f"{INFO}/{GROUP}/locations") and r.headers["authorization"] == "Bearer AGENCY-TOKEN"
    assert [(x.account_name, x.name) for x in out] == [(GROUP, "locations/222")]
    denied, _ = client((403, {"error": {"code": 403, "message": "no", "status": "PERMISSION_DENIED"}}))
    with pytest.raises(g.GoogleAPIError):
        denied.list_group_locations("AT", GROUP)


def test_the_admin_list_exposes_which_admin_is_the_group_and_whether_it_is_pending():
    c, _ = client((200, {"admins": [{"name": "locations/222/admins/g1", "account": GROUP, "role": "MANAGER", "pendingInvitation": True},
                                    {"name": "locations/222/admins/o1", "admin": "Owner Name", "role": "OWNER"}]}))
    a, b = c.list_admins("T", "locations/222")
    assert (a.account, a.pending, a.role, a.email) == (GROUP, True, "MANAGER", None)
    assert (b.account, b.email, b.role) == (None, "Owner Name", "OWNER")  # after acceptance a person shows by NAME in `admin`, not e-mail (documented), so e-mail matching cannot find an accepted person


def test_group_removal_deletes_the_admin_resource_the_invite_returned():
    c, wire = client((200, {}))
    c.remove_manager("AGENCY-TOKEN", "locations/222/admins/g1")
    assert (wire.last().method, str(wire.last().url)) == ("DELETE", f"{AM}/locations/222/admins/g1")


def test_accounts_list_carries_each_accounts_type_so_a_group_can_be_told_from_the_organisation():
    """manage-locations documents that accounts.list returns each account's `name` and `type` (for example LOCATION_GROUP). The pre-flight relies on it: the organisation is typed ORGANIZATION."""
    c, wire = client((200, {"accounts": [{"name": "accounts/5488245563", "accountName": "FlowQR", "type": "LOCATION_GROUP"},
                                         {"name": "accounts/5234249121", "accountName": "FlowQR Ltd", "type": "ORGANIZATION"}, {"name": "accounts/9001", "accountName": "A Person", "type": "PERSONAL"}, {"name": "accounts/1"}]}))
    out = c.list_accounts("AGENCY-TOKEN")
    assert (wire.last().method, str(wire.last().url).split("?")[0]) == ("GET", f"{AM}/accounts") and wire.last().headers["authorization"] == "Bearer AGENCY-TOKEN"
    assert [(a.name, a.type) for a in out] == [("accounts/5488245563", "LOCATION_GROUP"), ("accounts/5234249121", "ORGANIZATION"), ("accounts/9001", "PERSONAL"), ("accounts/1", None)]
