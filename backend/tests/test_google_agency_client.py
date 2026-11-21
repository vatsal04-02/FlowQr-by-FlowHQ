"""Contract tests for HttpAgencyClient: the REAL client code against a mock HTTP transport. Never a live call.
They pin each request against Google's published reference (read 2026-11-21) and prove the code matches the documentation, not that Google behaves as documented."""
import json

import httpx
import pytest

from app.services import google as g
from app.services.google.agency_client import AGENCY_ROLE, HttpAgencyClient, location_key
from tests.test_google_contract import Wire

AM = "https://mybusinessaccountmanagement.googleapis.com/v1"


def client(*answers):
    wire = Wire(*answers)
    return HttpAgencyClient(transport=httpx.MockTransport(wire)), wire


def test_invite_posts_the_agency_email_as_manager_with_the_clients_token():
    c, wire = client((200, {"name": "locations/222/admins/abc", "admin": "agency@flowqr.test", "role": "MANAGER", "pendingInvitation": True}))
    out = c.invite_manager("CLIENT-TOKEN", "locations/222", "agency@flowqr.test")
    r = wire.last()
    assert (r.method, str(r.url)) == ("POST", f"{AM}/locations/222/admins")
    assert json.loads(r.content) == {"admin": "agency@flowqr.test", "role": "MANAGER"}
    assert r.headers["authorization"] == "Bearer CLIENT-TOKEN"
    assert (out.name, out.pending) == ("locations/222/admins/abc", True)


def test_the_role_can_only_ever_be_manager():
    assert AGENCY_ROLE == "MANAGER"
    import inspect
    assert "role" not in inspect.signature(HttpAgencyClient.invite_manager).parameters  # there is no way to ask for OWNER


def test_invite_without_an_admin_resource_in_the_answer_is_an_error_not_a_success():
    c, _ = client((200, {}))
    with pytest.raises(g.GoogleAPIError):
        c.invite_manager("T", "locations/222", "a@b.test")


def test_accept_posts_an_empty_body_to_the_invitation_with_the_agency_token():
    c, wire = client((200, {}))
    c.accept_invitation("AGENCY-TOKEN", "accounts/9001/invitations/inv1")
    r = wire.last()
    assert (r.method, str(r.url)) == ("POST", f"{AM}/accounts/9001/invitations/inv1:accept")
    assert r.content == b"" and r.headers["authorization"] == "Bearer AGENCY-TOKEN"


def test_pending_invitations_keep_only_location_invitations_and_skip_accounts_that_refuse():
    def answer(request):
        if str(request.url).startswith("https://mybusinessaccountmanagement.googleapis.com/v1/accounts?"):
            return 200, {"accounts": [{"name": "accounts/1"}, {"name": "accounts/2"}]}
        if "/accounts/1/invitations" in str(request.url):
            return 200, {"invitations": [{"name": "accounts/1/invitations/i1", "role": "MANAGER", "targetLocation": {"locationName": "locations/222"}},
                                         {"name": "accounts/1/invitations/i2", "role": "MANAGER", "targetAccount": {"name": "accounts/7"}}]}
        return 403, {"error": {"code": 403, "message": "no", "status": "PERMISSION_DENIED"}}
    c, _ = client(answer)
    inv = c.list_pending_invitations("AT")
    assert [(i.name, i.location_name) for i in inv] == [("accounts/1/invitations/i1", "locations/222")]


def test_list_admins_reads_the_admin_resources():
    c, wire = client((200, {"admins": [{"name": "locations/222/admins/a", "admin": "x@y.test", "role": "OWNER"},
                                       {"name": "locations/222/admins/b", "role": "MANAGER", "pendingInvitation": True}]}))
    out = c.list_admins("T", "locations/222")
    assert (wire.last().method, str(wire.last().url)) == ("GET", f"{AM}/locations/222/admins")
    assert [(a.name, a.email, a.pending) for a in out] == [("locations/222/admins/a", "x@y.test", False), ("locations/222/admins/b", None, True)]


def test_remove_deletes_the_admin_resource_by_its_name():
    c, wire = client((200, {}))
    c.remove_manager("AGENCY-TOKEN", "locations/222/admins/abc")
    assert (wire.last().method, str(wire.last().url)) == ("DELETE", f"{AM}/locations/222/admins/abc")


def test_visible_locations_carry_the_account_they_are_listed_under():
    def answer(request):
        u = str(request.url)
        if u.startswith(f"{AM}/accounts?"):
            return 200, {"accounts": [{"name": "accounts/9001"}]}
        return 200, {"locations": [{"name": "locations/222", "title": "Clinic"}]}
    c, _ = client(answer)
    out = c.list_visible_locations("AT")
    assert [(x.account_name, x.name) for x in out] == [("accounts/9001", "locations/222")]


def test_revoke_reports_whether_google_confirmed_it():
    ok, _ = client((200, {}))
    assert ok.revoke_token("T") is True
    bad, _ = client((400, {"error": "invalid_token"}))
    assert bad.revoke_token("T") is False


def test_location_keys_compare_across_name_shapes():
    assert location_key("locations/222") == location_key("accounts/1/locations/222") == location_key("222")
