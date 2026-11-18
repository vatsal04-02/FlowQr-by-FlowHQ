"""Milestone 2 provider additions (reads and validation-only patches): the REAL provider code against a mock transport, plus the guards of the readiness tool.
They pin the request each call sends and prove a validation patch can never be sent without `validateOnly=true`. They do not prove Google's behaviour: the live
results are in docs/GOOGLE_READINESS_M2.md and docs/evidence/google-readiness-2026-11-17.json."""
import inspect
from types import SimpleNamespace

import pytest

from app.services.google import readiness
from app.services.google.provider import HttpGoogleProvider
from tests.test_google_contract import INFO, LOC, body, provider, q


def test_validate_patch_always_sends_validate_only_and_the_given_mask():
    p, wire = provider((200, {"name": LOC, "profile": {"description": "x"}}))
    out = p.validate_location_patch("tok", LOC, {"profile": {"description": "x"}}, "profile")
    r = wire.last()
    assert r.method == "PATCH" and str(r.url).startswith(f"{INFO}/{LOC}?")
    assert q(r)["validateOnly"] == ["true"] and q(r)["updateMask"] == ["profile"] and body(r) == {"profile": {"description": "x"}}
    assert out["name"] == LOC


def test_validate_patch_has_no_way_to_turn_validate_only_off():
    params = inspect.signature(HttpGoogleProvider.validate_location_patch).parameters
    assert set(params) == {"self", "access_token", "location_name", "body", "update_mask"}  # no flag, no kwargs: validateOnly is not a parameter
    assert "validateOnly" in inspect.getsource(HttpGoogleProvider.validate_location_patch)


def test_get_google_updated_reads_the_documented_endpoint_and_masks():
    p, wire = provider((200, {"location": {"profile": {"description": "live"}}, "diffMask": "profile.description", "pendingMask": ""}))
    out = p.get_google_updated("tok", LOC, "profile,title")
    r = wire.last()
    assert r.method == "GET" and r.url.path.endswith(f"/v1/{LOC}:getGoogleUpdated") and q(r)["readMask"] == ["profile,title"]
    assert out == {"location": {"profile": {"description": "live"}}, "diff_mask": "profile.description", "pending_mask": ""}


def test_readiness_reads_use_the_documented_services():
    p, wire = provider((200, {}))
    p.get_voice_of_merchant_state("t", LOC)
    assert str(wire.last().url) == f"https://mybusinessverifications.googleapis.com/v1/{LOC}/VoiceOfMerchantState"
    p.list_verifications("t", LOC)
    assert str(wire.last().url) == f"https://mybusinessverifications.googleapis.com/v1/{LOC}/verifications"
    p.get_attributes("t", LOC)
    assert str(wire.last().url) == f"{INFO}/{LOC}/attributes"
    p.list_place_action_links("t", LOC)
    assert str(wire.last().url) == f"https://mybusinessplaceactions.googleapis.com/v1/{LOC}/placeActionLinks"
    p.get_notification_setting("t", "accounts/1")
    assert str(wire.last().url) == "https://mybusinessnotifications.googleapis.com/v1/accounts/1/notificationSetting"


def test_attribute_metadata_for_a_location_sends_only_parent():
    """Observed live (2026-11-17): Google answers 400 when `parent` is combined with region, language or category filters."""
    p, wire = provider((200, {"attributeMetadata": []}))
    p.list_attribute_metadata("t", parent=LOC)
    params = q(wire.last())
    assert params["parent"] == [LOC] and "regionCode" not in params and "categoryName" not in params and "languageCode" not in params
    p.list_attribute_metadata("t", category_name="categories/gcid:physiotherapist")
    params = q(wire.last())
    assert params["categoryName"] == ["categories/gcid:physiotherapist"] and params["regionCode"] == ["IN"] and "parent" not in params


# ------------------------------------------------------------------------------------------------------------ the readiness tool's guards
class Prov:
    """A provider that records every call and refuses any real write method."""

    def __init__(self, title="Some Clinic"):
        self.calls, self.title = [], title

    def refresh_access_token(self, rt):
        return SimpleNamespace(access_token="at", expires_in=3599, scope="https://www.googleapis.com/auth/business.manage")

    def get_location_raw(self, at, loc, mask):
        self.calls.append(("raw", mask))
        return {"name": loc, "title": self.title}

    def __getattr__(self, name):
        if name in ("update_location", "create_post", "add_media", "reply_to_review", "delete_post", "delete_media", "delete_reply", "update_post", "upload_media_bytes"):
            raise AssertionError(f"the readiness tool must never call {name}")
        raise AttributeError(name)


def test_the_tool_stops_after_one_read_when_the_live_title_is_not_the_designated_profile(monkeypatch):
    prov = Prov(title="GEETA KRISHNA PHYSIOTHERAPY")  # a real clinic: must never be probed
    monkeypatch.setattr(readiness.g, "get_google_provider", lambda: prov)
    monkeypatch.setattr(readiness.settings, "google_client_id", "x"), monkeypatch.setattr(readiness.settings, "google_client_secret", "y")

    from app.models import GoogleConnectionStatus
    conn = SimpleNamespace(refresh_token_encrypted=b"x", status=GoogleConnectionStatus.active)
    monkeypatch.setattr("app.core.db.system_session", lambda: SimpleNamespace(get=lambda m, i: conn, close=lambda: None))
    monkeypatch.setattr("app.core.security.get_cipher", lambda: SimpleNamespace(decrypt=lambda b: "rt"))
    args = SimpleNamespace(connection="00000000-0000-0000-0000-000000000001", location=LOC, expect_title="FlowHQ", evidence=None, pace_seconds=0)
    assert readiness.run(args) == 1
    assert prov.calls == [("raw", "name,title")]  # exactly the guard read, nothing else


def test_the_tool_refuses_an_inactive_connection(monkeypatch):
    from app.models import GoogleConnectionStatus
    monkeypatch.setattr(readiness.settings, "google_client_id", "x"), monkeypatch.setattr(readiness.settings, "google_client_secret", "y")
    conn = SimpleNamespace(refresh_token_encrypted=b"x", status=GoogleConnectionStatus.disconnected)
    monkeypatch.setattr("app.core.db.system_session", lambda: SimpleNamespace(get=lambda m, i: conn, close=lambda: None))
    monkeypatch.setattr(readiness.g, "get_google_provider", lambda: pytest.fail("no provider must be built for an isolated connection"))
    args = SimpleNamespace(connection="00000000-0000-0000-0000-000000000001", location=LOC, expect_title="FlowHQ", evidence=None, pace_seconds=0)
    assert readiness.run(args) == 2


def test_the_evidence_shape_holds_no_values():
    assert readiness._shape({"phoneNumbers": {"primaryPhone": "+91 98765 43210"}, "title": "T"}) == {"phoneNumbers": {"primaryPhone": "str"}, "title": "str"}
