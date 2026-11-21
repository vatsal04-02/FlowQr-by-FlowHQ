"""accountNumber (the short display reference Business Profile Manager shows) versus the API resource name (`accounts/{account_id}`, long).

Found by the first REAL read-only Google check (2026-11-21): the numbers the owner was given, 5488245563 and 5234249121, are `accountNumber` references. Google's API does not know them as ids
(`GET accounts/5488245563` is 404); the resources are accounts/114863040359228435467 (the Location Group) and accounts/110178313486978980497 (the organisation).

EVERY test here runs against tests/fake_agency_google: none makes a live Google call. The fake is set up to answer the way the real API did. That is a statement about this code, not about Google.
"""
import pathlib
import re
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, config_problems, settings
from app.core.db import system_session
from app.models import GoogleAgencyAccount
from app.services import google as g
from app.services.google import agency, agency_check
from app.services.google.agency_client import HttpAgencyClient, looks_like_account_number, normalize_group
from app.services.google.provider import GAccount, GLocation
from tests.conftest import owner_exec
from tests.fake_agency_google import AGENCY_ACCESS, GROUP
from tests.test_google_agency import _clean, calls  # noqa: F401  (_clean is an autouse fixture)
from tests.test_google_agency_group import AGENCY_EMAIL, gfake  # noqa: F401  (gfake is a fixture)
from tests.test_google_agency_registration import EMAIL, Spy
from tests.test_google_contract import Wire

GROUP_NUMBER, GROUP_RES = "5488245563", "accounts/114863040359228435467"
ORG_NUMBER, ORG_RES = "5234249121", "accounts/110178313486978980497"
GEETA = "726682899335438012"
TITLE = "GEETA KRISHNA PHYSIOTHERAPY DR. SANDEEP TIWARI,MPT (PT)"


@pytest.fixture()
def real(gfake, monkeypatch):
    """The world as the real API described it: a 21-digit Location Group with the short accountNumber, a 21-digit organisation, and one client location listed under the group."""
    gfake.group, gfake.group_number, gfake.org, gfake.org_number = GROUP_RES, GROUP_NUMBER, ORG_RES, ORG_NUMBER
    gfake.group_sees.add(GEETA)
    gfake.list_group_locations = lambda token, group: [GLocation(GROUP_RES, f"locations/{GEETA}", TITLE)]
    monkeypatch.setattr(settings, "google_agency_location_group_id", GROUP_RES)
    monkeypatch.setattr(settings, "google_agency_organization_id", ORG_RES)
    agency.register_account("flowqr-agency", code="c", provider=gfake, location_group_id=GROUP_RES)  # the stored login now records the real resource name
    return gfake


def run(f, **kw):
    kw.setdefault("account", "flowqr-agency")
    kw.setdefault("expected_email", AGENCY_EMAIL)
    return agency_check.run_checks(client=f, **kw)


def detail(checks, name):
    return next(c for c in checks if c.name == name).detail


# ------------------------------------------------------------------ telling the two apart
@pytest.mark.parametrize("value,expected", [
    ("5488245563", True), ("accounts/5488245563", True), ("5234249121", True), (" 5488245563 ", True),
    ("114863040359228435467", False), (GROUP_RES, False), (ORG_RES, False), ("", False), (None, False), ("abc", False), ("accounts/", False)])
def test_a_short_number_is_flagged_as_probably_an_account_number_and_a_full_resource_name_is_not(value, expected):
    assert looks_like_account_number(value) is expected


def test_the_check_with_the_complete_resource_name_passes_and_reads_through_the_group(real):
    checks = run(real, title="geeta  krishna")  # the stored login's recorded group is the resource name
    assert [c.status for c in checks if c.name in ("identity", "accounts.list", "group locations", "title match", "location match", "location read")] == ["PASS"] * 6
    assert GROUP_RES in detail(checks, "accounts.list") and f"locations/{GEETA}" in detail(checks, "title match")
    (rd,) = calls(real, "list_reviews")
    assert rd[1] == f"{GROUP_RES}/locations/{GEETA}" and rd[2] == AGENCY_ACCESS  # the path the review sync uses, with the agency token
    assert agency_check.ok(checks)


@pytest.mark.parametrize("given", [GROUP_NUMBER, f"accounts/{GROUP_NUMBER}"])
def test_the_group_account_number_is_recognised_and_the_resource_google_returned_is_named(real, given):
    checks = run(real, group=given, title="geeta")
    text = detail(checks, "accounts.list")
    assert [c.name for c in checks] == ["identity", "accounts.list"] and checks[1].status == "FAIL" and not agency_check.ok(checks)
    assert "accountNumber" in text and "display reference" in text and "404" in text  # the distinction, in words
    assert GROUP_RES in text and "Use its resource name" in text and "--location-group-id" in text
    assert calls(real, "list_group_locations") == [] and calls(real, "list_reviews") == []  # nothing further was tried with the wrong id


def test_the_organisation_account_number_is_recognised_as_the_organisation_never_a_group(real):
    text = detail(run(real, group=ORG_NUMBER), "accounts.list")
    assert ORG_RES in text and "ORGANISATION" in text and "never used as a group" in text and "Use its resource name" not in text


def test_the_organisations_real_resource_name_is_refused_as_a_group_by_type(real, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_organization_id", ORG_NUMBER)  # configured by its short number: the id guard cannot compare it with the resource, the live type check still refuses
    text = detail(run(real, group=ORG_RES), "accounts.list")
    assert "ORGANIZATION" in text and "not LOCATION_GROUP" in text


def test_a_number_that_matches_nothing_is_never_turned_into_a_resource_id(real):
    text = detail(run(real, group="9999999999"), "accounts.list")
    assert "looks like an accountNumber" in text and "No listed account has accountNumber 9999999999" in text and "Nothing was guessed" in text
    assert "not a member or administrator" in text  # the wording the existing test relies on is kept
    mentioned = set(re.findall(r"accounts/\d+", text))
    assert mentioned <= {"accounts/9999999999", GROUP_RES, ORG_RES, real.visible_account}  # only what Google listed, plus the value the user gave


def test_a_long_wrong_id_gets_the_ordinary_message_without_the_accountnumber_hint(real):
    text = detail(run(real, group="accounts/999999999999999999999"), "accounts.list")
    assert "looks like an accountNumber" not in text and "not a member or administrator" in text and GROUP_RES in text  # listed as one of the resources the login CAN use


def test_the_listing_in_the_failure_shows_ids_and_types_only_never_names_and_is_capped(real, monkeypatch):
    many = [GAccount(f"accounts/{i}00000000000000000", f"PRIVATE CLIENT NAME {i}", "LOCATION_GROUP", f"{i}000000000") for i in range(1, 13)]
    monkeypatch.setattr(real, "list_accounts", lambda token: many)
    text = detail(run(real, group="accounts/123"), "accounts.list")
    assert "PRIVATE CLIENT NAME" not in text and "and 2 more" in text and text.count("accounts/") <= 14


def test_the_real_provider_carries_googles_account_number():
    wire = Wire((200, {"accounts": [{"name": GROUP_RES, "type": "LOCATION_GROUP", "accountNumber": GROUP_NUMBER}, {"name": ORG_RES, "type": "ORGANIZATION", "accountNumber": ORG_NUMBER}, {"name": "accounts/1"}]}))
    out = HttpAgencyClient(transport=httpx.MockTransport(wire)).list_accounts("T")
    assert [(a.name, a.type, a.account_number) for a in out] == [(GROUP_RES, "LOCATION_GROUP", GROUP_NUMBER), (ORG_RES, "ORGANIZATION", ORG_NUMBER), ("accounts/1", None, None)]


# ------------------------------------------------------------------ complete resource names are accepted everywhere, consistently
def test_complete_resource_names_are_accepted_unchanged_and_bad_values_are_refused():
    assert normalize_group(GROUP_RES) == GROUP_RES and normalize_group("114863040359228435467") == GROUP_RES and normalize_group(f" {ORG_RES} ") == ORG_RES
    for bad in ("accounts/abc", "locations/726682899335438012", "agency@flowqr.test", "", "accounts/"):
        with pytest.raises(ValueError, match="API resource name"):
            normalize_group(bad)


def test_the_production_guard_accepts_the_complete_names_and_asks_for_the_resource_name_otherwise():
    def prod(**over):
        base = dict(app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True, public_card_base_url="https://go.flowqr.co.in",
                    frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in", database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr",
                    platform_admin_emails="ops@flowhq.in", smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
                    card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback", google_client_id="id", google_client_secret="secret",
                    google_agency_manager_enabled=True, agency_token_encryption_key=Fernet.generate_key().decode())
        base.update(over)
        return Settings(_env_file=None, **base)

    assert config_problems(prod(google_agency_location_group_id=GROUP_RES, google_agency_organization_id=ORG_RES)) == []
    assert config_problems(prod(google_agency_location_group_id="114863040359228435467", google_agency_organization_id="110178313486978980497")) == []  # the prefix is optional
    bad = config_problems(prod(google_agency_location_group_id="not-an-account"))
    assert any("numeric account id" in p and "resource name" in p and "accountNumber" in p for p in bad)
    assert any("same as GOOGLE_AGENCY_ORGANIZATION_ID" in p for p in config_problems(prod(google_agency_location_group_id=ORG_RES, google_agency_organization_id=ORG_RES)))


def test_the_complete_name_survives_registration_and_the_database_unchanged(gfake):
    account_id = agency.register_account("flowhq-names", code="C", provider=Spy(), expected_email=EMAIL, location_group_id=GROUP_RES)
    with system_session() as db:
        row = db.get(GoogleAgencyAccount, account_id)
        assert row.location_group_name == GROUP_RES and len(row.location_group_name) < 120  # not truncated, not rewritten, fits the column
    owner_exec("UPDATE google_agency_accounts SET location_group_name = :g WHERE id = :i", g=ORG_RES, i=str(account_id))  # the table's own check accepts any complete resource name
    with pytest.raises(IntegrityError):
        owner_exec("UPDATE google_agency_accounts SET location_group_name = 'accounts/abc' WHERE id = :i", i=str(account_id))


def test_the_organisation_guard_compares_complete_resource_names(gfake, monkeypatch):
    monkeypatch.setattr(settings, "google_agency_organization_id", ORG_RES)
    with pytest.raises(agency.AgencyError, match="organisation"):
        agency.refuse_if_organisation(normalize_group(ORG_RES))
    agency.refuse_if_organisation(normalize_group(GROUP_RES))  # the group is not the organisation


def test_registering_with_a_short_number_warns_and_with_the_resource_name_does_not(gfake, monkeypatch, capsys):
    from app import cli

    monkeypatch.setattr(g, "get_google_provider", lambda: Spy())
    base = dict(cmd="google-agency-register", label="flowhq-short", code="C", listen=False, max_locations=None, expect_email=EMAIL)
    assert cli._agency_cli(SimpleNamespace(**base, state=agency.new_oauth_state(), location_group_id=GROUP_NUMBER)) == 0
    out = capsys.readouterr().out
    assert f"WARNING: {GROUP_NUMBER} looks like an accountNumber" in out and "google-agency-check" in out and "PASS: agency account" in out  # it still registers: it only warns
    monkeypatch.setattr(g, "get_google_provider", lambda: Spy())
    assert cli._agency_cli(SimpleNamespace(**{**base, "label": "flowhq-full"}, state=agency.new_oauth_state(), location_group_id=GROUP_RES)) == 0
    assert "WARNING" not in capsys.readouterr().out


def test_the_status_line_flags_a_stored_short_number_and_shows_a_resource_name_plainly(gfake, capsys):
    from app import cli

    def line():
        assert cli._agency_cli(SimpleNamespace(cmd="google-agency-status")) == 0
        return next(x for x in capsys.readouterr().out.splitlines() if x.startswith("flowhq-status"))  # other rows (the fixture's own login) are not this test's business

    agency.register_account("flowhq-status", code="C", provider=Spy(), expected_email=EMAIL, location_group_id=GROUP_NUMBER)  # what actually happened on 2026-11-21
    assert "looks like an accountNumber" in line()
    agency.register_account("flowhq-status", code="C", provider=Spy(), expected_email=EMAIL, location_group_id=GROUP_RES)
    got = line()
    assert f"group: {GROUP_RES}" in got and "looks like an accountNumber" not in got


def test_the_check_command_accepts_the_resource_name_as_an_override_and_explains_a_short_number(real, capsys):
    from app import cli

    args = SimpleNamespace(cmd="google-agency-check", expect_email=AGENCY_EMAIL, account=None, location=None, connection_id=None, location_group_id=GROUP_RES, title="Geeta")
    assert cli._agency_cli(args) == 0 and "READ-ONLY CHECK PASSED" in capsys.readouterr().out
    args.location_group_id = GROUP_NUMBER
    assert cli._agency_cli(args) == 1
    out = capsys.readouterr().out
    assert "[FAIL] accounts.list" in out and GROUP_RES in out and "accountNumber" in out and AGENCY_ACCESS not in out


# ------------------------------------------------------------------ the documentation says the same thing
DOCS = ["audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md", "runbooks/GOOGLE_AGENCY_EXISTING_CLIENT_MIGRATION.md", "runbooks/GOOGLE_AGENCY_TWO_ACCOUNT_TEST.md", "ENVIRONMENT_VARIABLES.md"]


def test_no_document_presents_a_short_account_number_as_an_api_resource_name():
    root = pathlib.Path(__file__).resolve().parents[2] / "docs"
    if not root.exists():
        pytest.skip("the docs folder is not mounted in this environment")
    for name in DOCS:
        text = (root / name).read_text(encoding="utf-8")
        assert not re.search(r"accounts/(5488245563|5234249121)\b", text), name  # the number is never shown after `accounts/` as if it were an id
        assert not re.search(r"(GOOGLE_AGENCY_(LOCATION_GROUP|ORGANIZATION)_ID=|--location-group-id\s+)(5488245563|5234249121)\b", text), name  # nor offered as a setting
    migration = (root / DOCS[1]).read_text(encoding="utf-8")
    assert GROUP_RES in migration and "accountNumber" in migration and ORG_RES in migration
