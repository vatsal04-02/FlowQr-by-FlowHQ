"""The real Google answer (read live 2026-11-23): an invitation to the FlowHQ Location Group carries the location's DISPLAY NAME in `targetLocation.locationName` ("FlowHQ"), not `locations/{id}`,
with the place id beside it. The code used to compare the id only, so the invitation was never found and never accepted. These tests use that exact shape."""
import httpx

from app.services.google.agency import pick_invitation
from app.services.google.agency_client import HttpAgencyClient, PendingInvitation
from tests.test_google_contract import Wire

GROUP = "accounts/114863040359228435467"
PLACE = "ChIJfZUa2-LjmzkR14Ax-pKwJko"
LIVE = {"invitations": [{"name": f"{GROUP}/invitations/L118191687919799515035", "role": "MANAGER",
                         "targetLocation": {"locationName": "FlowHQ", "address": "2/68, Viram Khand-2, Gomti Nagar, Lucknow, Uttar Pradesh, India", "placeId": PLACE}}]}


class Gl:  # the two fields the matcher reads
    def __init__(self, name="locations/6589197820321114990", place=PLACE): self.google_location_name, self.place_id = name, place


def test_the_live_answer_is_read_with_its_place_id():
    c = HttpAgencyClient(transport=httpx.MockTransport(Wire((200, LIVE))))
    inv = c.list_pending_invitations("AT", [GROUP])
    assert [(i.name, i.location_name, i.place_id, i.receiving_account) for i in inv] == [(f"{GROUP}/invitations/L118191687919799515035", "FlowHQ", PLACE, GROUP)]


def test_the_invitation_is_matched_by_place_id_when_the_name_is_a_display_name():
    c = HttpAgencyClient(transport=httpx.MockTransport(Wire((200, LIVE))))
    found = pick_invitation(c.list_pending_invitations("AT", [GROUP]), Gl())
    assert found is not None and found.name.endswith("L118191687919799515035")


def test_the_documented_resource_id_still_matches():
    assert pick_invitation([PendingInvitation("accounts/1/invitations/i", "locations/6589197820321114990", "MANAGER", "accounts/1")], Gl(place=None)).name == "accounts/1/invitations/i"


def test_a_display_name_alone_never_matches():
    inv = [PendingInvitation("accounts/1/invitations/i", "FlowHQ", "MANAGER", "accounts/1", None)]
    assert pick_invitation(inv, Gl(place=None)) is None  # same title as another business is not the same location
    assert pick_invitation(inv, Gl()) is None  # an invitation without a place id cannot be matched by name either


def test_a_different_place_id_does_not_match():
    inv = [PendingInvitation("accounts/1/invitations/i", "FlowHQ", "MANAGER", "accounts/1", "ChIJother")]
    assert pick_invitation(inv, Gl()) is None


def test_an_ambiguous_place_id_accepts_nothing():
    inv = [PendingInvitation(f"accounts/1/invitations/{n}", "FlowHQ", "MANAGER", "accounts/1", PLACE) for n in ("a", "b")]
    assert pick_invitation(inv, Gl()) is None
