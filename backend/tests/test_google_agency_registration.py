"""Registering the agency Google login (python -m app.cli google-agency-auth-url / google-agency-register) and finding a client's location by title in the read-only check.

EVERY test runs against tests/fake_agency_google.FakeAgencyClient: none makes a live Google call. They prove the CODE: a random single-use OAuth state, the identity guard, encrypted storage under
the agency key alone, an authorization URL that asks for nothing extra, and a title lookup that names only the one location it was asked for. They do not prove Google behaves this way: the real
registration and the real read-only check are run by a person (docs/runbooks/GOOGLE_AGENCY_EXISTING_CLIENT_MIGRATION.md).
"""
import hashlib
import sys
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import system_session
from app.core.security import TokenCipher, get_cipher
from app.models import GoogleAgencyAccount
from app.models.base import utcnow
from app.services.google import agency, agency_check
from app.services.google.provider import GLocation, HttpGoogleProvider
from tests.conftest import owner_query
from tests.fake_agency_google import AGENCY_ACCESS, AGENCY_REFRESH, CLIENT_ACCESS, GROUP, FakeAgencyClient
from tests.test_google_agency import _clean, calls  # noqa: F401  (_clean is an autouse fixture)
from tests.test_google_agency_group import AGENCY_EMAIL, gfake  # noqa: F401  (gfake is a fixture: agency key set, group configured, one login registered as AGENCY_EMAIL)

EMAIL = "vatsal@flowhq.co.in"
REGISTERED_REDIRECTS = {"http://localhost:3000/api/v1/google/callback", "https://app.flowqr.co.in/api/v1/google/callback", "https://api.flowqr.site/api/v1/google/callback"}


class Spy(FakeAgencyClient):
    """A Google that records how often the single-use code is exchanged and when a grant is revoked."""

    def __init__(self, email=EMAIL):
        super().__init__(email)
        self.exchanged: list[str] = []

    def exchange_code(self, code):
        self.exchanged.append(code)
        return super().exchange_code(code)


def used_rows(state: str):
    digest = hashlib.sha256(state.split(".")[0].encode()).hexdigest()
    return owner_query("SELECT entity_id FROM audit_logs WHERE action = 'google.agency.oauth_state_used' AND entity_id = :h", h=digest)


# ------------------------------------------------------------------ the OAuth state
def test_every_state_is_random_signed_and_short_lived(gfake):
    states = [agency.new_oauth_state() for _ in range(60)]
    assert len(set(states)) == 60 and len({s.split(".")[0] for s in states}) == 60  # nothing repeats
    for s in states[:5]:
        nonce, expiry, signature = s.split(".")
        assert len(nonce) >= 43 and len(signature) == 64 and s != "agency-registration"  # 256 random bits, a SHA-256 signature, and never the old fixed word
        assert 14 * 60 < int(expiry) - int(utcnow().timestamp()) <= 15 * 60 + 1


def test_a_state_is_accepted_exactly_once(gfake):
    s = agency.new_oauth_state()
    assert used_rows(s) == []
    agency.consume_oauth_state(s)
    assert len(used_rows(s)) == 1
    with pytest.raises(agency.AgencyError, match="already used"):
        agency.consume_oauth_state(s)  # a replay, even before anything is exchanged
    assert len(used_rows(s)) == 1


@pytest.mark.parametrize("make,why", [
    (lambda s: s[:-1] + ("0" if s[-1] != "0" else "1"), "was not issued by this installation"),  # one signature character changed
    (lambda s: "x" + s, "was not issued by this installation"),  # the random part changed
    (lambda s: s.rsplit(".", 2)[0] + ".4102444800." + s.rsplit(".", 1)[1], "was not issued by this installation"),  # the expiry pushed to the year 2100
    (lambda s: "agency-registration", "malformed"),  # the old fixed state
    (lambda s: "", "missing or malformed"), (lambda s: "a.b", "malformed"), (lambda s: "a.b.c.d", "malformed"),
])
def test_a_tampered_or_foreign_state_is_refused_and_nothing_is_recorded(gfake, make, why):
    s = agency.new_oauth_state()
    with pytest.raises(agency.AgencyError, match=why):
        agency.consume_oauth_state(make(s))
    assert used_rows(s) == []  # the genuine state is still unused


def test_an_expired_state_and_a_state_from_another_installation_are_refused(gfake, monkeypatch):
    s = agency.new_oauth_state()
    with pytest.raises(agency.AgencyError, match="expired"):
        agency.consume_oauth_state(s, now=utcnow() + timedelta(minutes=16))
    assert used_rows(s) == []
    other = agency.new_oauth_state()
    from cryptography.fernet import Fernet
    monkeypatch.setattr(settings, "agency_token_encryption_key", Fernet.generate_key().decode())  # a different installation's key
    with pytest.raises(agency.AgencyError, match="not issued by this installation"):
        agency.consume_oauth_state(other)


def test_no_state_can_be_made_or_checked_without_the_agency_key(monkeypatch):
    monkeypatch.setattr(settings, "agency_token_encryption_key", "")
    with pytest.raises(agency.AgencyError, match="AGENCY_TOKEN_ENCRYPTION_KEY"):
        agency.new_oauth_state()
    with pytest.raises(agency.AgencyError, match="AGENCY_TOKEN_ENCRYPTION_KEY"):
        agency.consume_oauth_state("a.1.b")


def test_the_audit_record_of_a_used_state_holds_only_a_hash(gfake):
    s = agency.new_oauth_state()
    agency.consume_oauth_state(s)
    nonce = s.split(".")[0]
    blob = str(owner_query("SELECT entity_id, entity_type, metadata::text, tenant_id::text FROM audit_logs WHERE action = 'google.agency.oauth_state_used' AND entity_id = :h",
                           h=hashlib.sha256(nonce.encode()).hexdigest()))
    assert nonce not in blob and s not in blob and "agency_oauth_state" in blob


# ------------------------------------------------------------------ the authorization URL
def test_the_agency_authorization_url_asks_for_the_business_scope_only_and_one_registered_redirect(gfake, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "THE-EXISTING-CLIENT-ID.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "never-in-a-url")
    for redirect in REGISTERED_REDIRECTS:
        monkeypatch.setattr(settings, "google_redirect_uri", redirect)
        url = agency.agency_auth_url(HttpGoogleProvider(), agency.new_oauth_state())
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert urlsplit(url).netloc == "accounts.google.com"
        assert q["client_id"] == "THE-EXISTING-CLIENT-ID.apps.googleusercontent.com" and q["redirect_uri"] == redirect and q["redirect_uri"] in REGISTERED_REDIRECTS
        assert q["scope"].split() == ["openid", "email", "https://www.googleapis.com/auth/business.manage"]  # openid and email only to read WHO signed in
        assert q["response_type"] == "code" and q["access_type"] == "offline" and q["prompt"] == "consent"
        assert q["include_granted_scopes"] == "false"  # nothing granted earlier by this account is folded in
        assert q["state"].count(".") == 2 and q["state"] != "agency-registration" and "never-in-a-url" not in url


def test_the_customer_sign_in_url_is_not_changed_by_the_agency_one(gfake):
    q = {k: v[0] for k, v in parse_qs(urlsplit(HttpGoogleProvider().build_auth_url("S")).query).items()}
    assert q["include_granted_scopes"] == "true"  # unchanged: this work only tightens the agency sign-in


# ------------------------------------------------------------------ registering: identity, encryption, nothing printed
def test_a_valid_state_and_the_right_account_stores_the_login_encrypted_under_the_agency_key_alone(gfake):
    spy = Spy()
    state = agency.new_oauth_state()
    account_id = agency.register_account("flowhq-agency-state", code="THE-CODE", provider=spy, expected_email=EMAIL, state=state, location_group_id="5488245563")
    assert spy.exchanged == ["THE-CODE"] and len(used_rows(state)) == 1 and spy.revoked == []
    with system_session() as db:
        row = db.get(GoogleAgencyAccount, account_id)
        assert row.google_email == EMAIL and row.location_group_name == GROUP and row.status == "active"
        assert AGENCY_REFRESH not in row.refresh_token_encrypted and AGENCY_ACCESS not in row.access_token_encrypted  # nothing readable in the table
        assert TokenCipher(settings.agency_token_encryption_key).decrypt(row.refresh_token_encrypted) == AGENCY_REFRESH
        with pytest.raises(RuntimeError):
            get_cipher().decrypt(row.refresh_token_encrypted)  # the key that protects customers' tokens cannot open it


def test_a_replayed_state_never_reaches_google(gfake):
    spy, state = Spy(), agency.new_oauth_state()
    agency.register_account("flowhq-agency-replay", code="C1", provider=spy, expected_email=EMAIL, state=state)
    again = Spy()
    with pytest.raises(agency.AgencyError, match="already used"):
        agency.register_account("flowhq-agency-replay", code="C2", provider=again, expected_email=EMAIL, state=state)
    assert again.exchanged == []  # the second code was not even exchanged


@pytest.mark.parametrize("bad", ["agency-registration", "", "x.1.y"])
def test_a_bad_state_means_the_single_use_google_code_is_not_spent(gfake, bad):
    spy = Spy()
    with pytest.raises(agency.AgencyError):
        agency.register_account("flowhq-agency-bad", code="UNSPENT", provider=spy, expected_email=EMAIL, state=bad)
    assert spy.exchanged == []
    with system_session() as db:
        assert db.scalar(select(GoogleAgencyAccount).where(GoogleAgencyAccount.label == "flowhq-agency-bad")) is None


def test_a_different_google_account_is_rejected_revoked_and_never_stored_even_with_a_valid_state(gfake):
    spy = Spy("apigbp@gmail.com")  # the OLD account signs in by mistake
    state = agency.new_oauth_state()
    with pytest.raises(agency.AgencyError, match="not the expected agency account"):
        agency.register_account("flowhq-agency-wrong", code="C", provider=spy, expected_email=EMAIL, state=state)
    assert spy.revoked and len(used_rows(state)) == 1  # the grant was revoked at Google, and the state is spent either way
    with system_session() as db:
        assert db.scalar(select(GoogleAgencyAccount).where(GoogleAgencyAccount.google_email == "apigbp@gmail.com")) is None
        assert db.scalar(select(GoogleAgencyAccount).where(GoogleAgencyAccount.label == "flowhq-agency-wrong")) is None


# ------------------------------------------------------------------ the commands
def test_the_auth_url_command_prints_a_signed_state_and_no_secret(gfake, monkeypatch, capsys):
    from app import cli
    from app.services import google as g

    monkeypatch.setattr(g, "get_google_provider", lambda: HttpGoogleProvider())  # the REAL URL builder, not the fixture's fake (it only builds a string: no network)
    monkeypatch.setattr(settings, "google_client_id", "CLIENT-ID-1.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "THE-CLIENT-SECRET-VALUE")
    assert cli._agency_cli(SimpleNamespace(cmd="google-agency-auth-url")) == 0
    out = capsys.readouterr().out
    url = next(line for line in out.splitlines() if line.startswith("https://accounts.google.com/"))
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert q["state"].count(".") == 2 and q["include_granted_scopes"] == "false" and "state=" in out and "BOTH the `code=` and the `state=`" in out
    assert "THE-CLIENT-SECRET-VALUE" not in out and settings.agency_token_encryption_key not in out
    monkeypatch.setattr(settings, "agency_token_encryption_key", "")
    assert cli._agency_cli(SimpleNamespace(cmd="google-agency-auth-url")) == 1 and "AGENCY_TOKEN_ENCRYPTION_KEY is not set" in capsys.readouterr().out


def test_the_register_command_needs_the_expected_email_and_either_the_redirect_values_or_listen(gfake, monkeypatch, capsys):
    """`--expect-email` is always required by the argument parser. `--state` and `--code` are required unless `--listen` is used (then this command issues the state and receives the code itself): that rule
    is enforced by the command, and covered in test_google_agency_listen.py."""
    from app import cli

    monkeypatch.setattr(sys, "argv", ["x", "google-agency-register", "--label", "a", "--code", "c", "--state", "s"])  # no --expect-email
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    for argv in (["x", "google-agency-register", "--label", "a", "--code", "c", "--expect-email", EMAIL],  # no state
                 ["x", "google-agency-register", "--label", "a", "--state", "s", "--expect-email", EMAIL]):  # no code
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as stop:
            cli.main()
        assert stop.value.code == 1  # the command itself refuses and says what to give
    assert "give both --code and --state" in capsys.readouterr().out


def test_the_register_command_stores_only_for_the_right_account_and_prints_no_token(gfake, monkeypatch, capsys):
    from app import cli
    from app.services import google as g

    spy = Spy()
    monkeypatch.setattr(g, "get_google_provider", lambda: spy)
    args = SimpleNamespace(cmd="google-agency-register", label="flowhq-agency-cli", code="C", location_group_id="5488245563", max_locations=None, expect_email=EMAIL, state=agency.new_oauth_state())
    assert cli._agency_cli(args) == 0
    out = capsys.readouterr().out
    assert "PASS: agency account 'flowhq-agency-cli' stored" in out and AGENCY_REFRESH not in out and AGENCY_ACCESS not in out and settings.agency_token_encryption_key not in out
    wrong = SimpleNamespace(**{**vars(args), "expect_email": "someone.else@flowhq.co.in", "state": agency.new_oauth_state()})
    assert cli._agency_cli(wrong) == 1 and "not the expected agency account" in capsys.readouterr().out
    replay = SimpleNamespace(**{**vars(args), "state": args.state})
    assert cli._agency_cli(replay) == 1 and "already used" in capsys.readouterr().out


# ------------------------------------------------------------------ finding a client by title in the read-only check
GEETA, OTHER_A, OTHER_B = "441000441", "442000442", "443000443"


def listing(f, titles: dict[str, str]):
    f.group_sees |= set(titles)
    f.list_group_locations = lambda token, group: [GLocation(GROUP, f"locations/{k}", t) for k, t in titles.items()]


def run(f, **kw):
    kw.setdefault("account", "flowqr-agency")
    kw.setdefault("expected_email", AGENCY_EMAIL)
    return agency_check.run_checks(client=f, **kw)


def text(checks):
    return "\n".join(f"{c.name} {c.status} {c.detail}" for c in checks)


def test_the_title_finds_exactly_one_location_reads_it_through_the_group_and_names_no_other_client(gfake):
    listing(gfake, {GEETA: "Geeta Krishna Physiotherapy", OTHER_A: "Sunrise Dental Care", OTHER_B: "Lucknow Skin Clinic"})
    checks = run(gfake, title="geeta  KRISHNA")  # case and spacing do not matter
    out = text(checks)
    got = {c.name: c.status for c in checks}
    assert got["title match"] == "PASS" and got["location match"] == "PASS" and got["location read"] == "PASS"
    assert f"locations/{GEETA}" in out and "Geeta Krishna Physiotherapy" in out and GROUP in out
    for other in (OTHER_A, OTHER_B, "Sunrise", "Lucknow Skin"):
        assert other not in out  # the other clients are not named
    (rd,) = calls(gfake, "list_reviews")
    assert rd[1] == f"{GROUP}/locations/{GEETA}" and rd[2] == AGENCY_ACCESS  # read at the group's own path, with the agency token
    assert {c[0] for c in gfake.calls} <= {"list_reviews"} and gfake.requests == [] and not [c for c in gfake.calls if c[2] == CLIENT_ACCESS] and gfake.revoked == []  # reads only
    assert agency_check.ok(checks)


def test_a_title_that_matches_nothing_or_more_than_one_location_is_a_failure_that_names_nobody(gfake):
    listing(gfake, {GEETA: "Geeta Krishna Physiotherapy", OTHER_A: "Geeta Krishna Dental", OTHER_B: "Sunrise Dental Care"})
    nothing = run(gfake, title="No Such Clinic")
    assert [c.status for c in nothing if c.name == "title match"] == ["FAIL"] and not agency_check.ok(nothing) and not any(c.name == "location read" for c in nothing)
    two = run(gfake, title="Geeta Krishna")  # two locations match
    out = text(two)
    assert [c.status for c in two if c.name == "title match"] == ["FAIL"] and "2 locations" in out
    assert GEETA not in out and OTHER_A not in out and "Dental" not in out and "Physiotherapy" not in out  # a failure does not reveal who they are
    assert calls(gfake, "list_reviews") == [] and not agency_check.ok(two)


def test_the_title_lookup_is_skipped_when_the_group_cannot_be_listed(gfake):
    gfake.agency_in_group = False
    checks = run(gfake, title="Geeta Krishna")
    assert [(c.name, c.status) for c in checks if c.status == "FAIL"] and not any(c.name == "title match" for c in checks)


def test_the_check_command_accepts_a_title(gfake, capsys):
    from app import cli

    listing(gfake, {GEETA: "Geeta Krishna Physiotherapy", OTHER_A: "Sunrise Dental Care"})
    args = SimpleNamespace(cmd="google-agency-check", expect_email=AGENCY_EMAIL, account=None, location=None, connection_id=None, location_group_id=None, title="Geeta Krishna Physiotherapy")
    assert cli._agency_cli(args) == 0
    out = capsys.readouterr().out
    assert "[PASS] title match" in out and f"locations/{GEETA}" in out and "Sunrise" not in out and "READ-ONLY CHECK PASSED" in out and AGENCY_ACCESS not in out
    args.title = "Nobody"
    assert cli._agency_cli(args) == 1 and "[FAIL] title match" in capsys.readouterr().out
