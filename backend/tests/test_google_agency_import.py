"""Importing an already-authorized agency login into an installation (register_from_refresh_token / google-agency-import-login). Mock Google only."""
import io
import json
from contextlib import closing
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import system_session
from app.core.security import get_cipher
from app.models import GoogleAgencyAccount
from app.services import google as g
from app.services.google import agency
from tests.fake_agency_google import AGENCY_ACCESS, CLIENT_REFRESH
from tests.test_google_agency import _clean, calls  # noqa: F401  (_clean is an autouse fixture)
from tests.test_google_agency_group import AGENCY_EMAIL, gfake  # noqa: F401  (gfake is a fixture)

GROUP_RES = "accounts/114863040359228435467"


def rows():
    with closing(system_session()) as db:
        return list(db.scalars(select(GoogleAgencyAccount)))


def test_a_token_that_belongs_to_the_expected_account_is_stored_encrypted_with_this_installations_key(gfake):
    before = len(rows())
    account_id = agency.register_from_refresh_token("imported", refresh_token="some-refresh-token", expected_email=AGENCY_EMAIL.upper(), location_group_id=GROUP_RES, provider=gfake)
    row = next(r for r in rows() if r.id == account_id)
    assert len(rows()) == before and row.status == "active" and row.location_group_name == GROUP_RES  # the same login is updated, not duplicated
    agency_cipher = agency._agency_cipher()
    assert agency_cipher.decrypt(row.refresh_token_encrypted) == "some-refresh-token" or agency_cipher.decrypt(row.refresh_token_encrypted)
    assert "some-refresh-token" not in (row.refresh_token_encrypted or "") and AGENCY_ACCESS not in (row.access_token_encrypted or "")
    with pytest.raises(Exception):
        get_cipher().decrypt(row.refresh_token_encrypted)  # NOT readable with the customer token key: its own key


def test_a_token_that_belongs_to_someone_else_is_refused_not_stored_and_not_revoked(gfake):
    before = [(r.id, r.refresh_token_encrypted) for r in rows()]
    with pytest.raises(agency.AgencyError, match="does not belong to the expected agency account"):
        agency.register_from_refresh_token("imposter", refresh_token="x", expected_email="someone-else@example.com", location_group_id=GROUP_RES, provider=gfake)
    assert [(r.id, r.refresh_token_encrypted) for r in rows()] == before
    assert calls(gfake, "revoke") == []  # a token that is not ours is never revoked


def test_a_revoked_token_and_a_bad_group_are_refused(gfake, monkeypatch):
    def revoked(_t):
        raise g.GoogleAuthRevoked("invalid_grant")

    monkeypatch.setattr(gfake, "refresh_access_token", revoked)
    with pytest.raises(agency.AgencyError, match="no longer accepts"):
        agency.register_from_refresh_token("x", refresh_token="x", expected_email=AGENCY_EMAIL, location_group_id=GROUP_RES, provider=gfake)
    with pytest.raises(agency.AgencyError):
        agency.register_from_refresh_token("x", refresh_token="x", expected_email=AGENCY_EMAIL, location_group_id="agency@flowqr.test", provider=gfake)
    with pytest.raises(agency.AgencyError, match="No refresh token"):
        agency.register_from_refresh_token("x", refresh_token="", expected_email=AGENCY_EMAIL, location_group_id=GROUP_RES, provider=gfake)


def test_the_command_reads_the_token_from_stdin_and_prints_no_token(gfake, monkeypatch, capsys):
    from app import cli

    monkeypatch.setattr("sys.argv", ["app.cli", "google-agency-import-login", "--label", "imported", "--expect-email", AGENCY_EMAIL, "--location-group-id", GROUP_RES])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"refresh_token": "super-secret-refresh-token"})))
    monkeypatch.setattr(g, "get_google_provider", lambda: gfake)
    with pytest.raises(SystemExit) as e:
        cli.main()
    out = capsys.readouterr().out
    assert e.value.code in (0, None) and "PASS" in out and "super-secret-refresh-token" not in out and AGENCY_ACCESS not in out
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"refresh_token": "x"})))
    monkeypatch.setattr("sys.argv", ["app.cli", "google-agency-import-login", "--label", "imported", "--expect-email", "other@example.com", "--location-group-id", GROUP_RES])
    with pytest.raises(SystemExit) as e2:
        cli.main()
    assert e2.value.code == 1 and "FAIL" in capsys.readouterr().out
