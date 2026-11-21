"""The one-shot local listener that receives the agency sign-in's redirect (services/google/agency_listen.py, `google-agency-register --listen`).

These tests use REAL loopback sockets, the way a browser would arrive, so the redirect handling itself is exercised. They make NO Google call: the Google side is tests/fake_agency_google. They prove the
code; the real sign-in is done by a person (docs/runbooks/GOOGLE_AGENCY_EXISTING_CLIENT_MIGRATION.md).

The failure this exists for: with FlowQR's own local stack running on the redirect port, Google's redirect was swallowed by the CUSTOMER callback, which rejected the agency state without using the
code and sent the browser on to /login. The code and state then existed only in a redirected browser request, and the app's access log redacts them.
"""
import socket
import threading
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import system_session
from app.models import GoogleAgencyAccount
from app.services import google as g
from app.services.google import agency, agency_listen
from tests.fake_agency_google import AGENCY_ACCESS, AGENCY_REFRESH
from tests.test_google_agency import _clean  # noqa: F401  (autouse fixture)
from tests.test_google_agency_group import gfake  # noqa: F401  (fixture: agency key set, group configured)
from tests.test_google_agency_registration import EMAIL, Spy

PATH = "/api/v1/google/callback"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start(state: str, port: int, timeout: float = 15):
    server = agency_listen.open_listener("127.0.0.1", port)
    out: dict = {}

    def run():
        try:
            out["result"] = agency_listen.wait_for_callback(server, path=PATH, expected_state=state, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - handed to the test thread
            out["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, out


def get(port: int, target: str, method: str = "GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{target}", method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


# ------------------------------------------------------------------ the redirect URI
def test_only_a_localhost_http_redirect_can_be_listened_for():
    assert agency_listen.parse_redirect("http://localhost:3000/api/v1/google/callback") == ("localhost", 3000, PATH)
    assert agency_listen.parse_redirect("http://127.0.0.1:3000/x") == ("127.0.0.1", 3000, "/x")
    for bad in ("https://api.flowqr.site/api/v1/google/callback", "https://app.flowqr.co.in/api/v1/google/callback", "http://evil.example/api/v1/google/callback", "http://localhost.evil.example:3000/x", "", "localhost:3000/x"):
        with pytest.raises(agency_listen.ListenError):
            agency_listen.parse_redirect(bad)


# ------------------------------------------------------------------ the listener
def test_it_returns_the_code_for_the_expected_state_and_closes(gfake):
    state, port = agency.new_oauth_state(), free_port()
    t, out = start(state, port)
    status, body = get(port, f"{PATH}?code=THE-CODE&state={state}&iss=x&scope=y&authuser=0")
    t.join(10)
    assert out["result"] == ("THE-CODE", None) and status == 200
    assert "THE-CODE" not in body and state not in body  # the page the browser sees carries neither value
    with pytest.raises(Exception):
        get(port, PATH)  # it closed after one valid callback


def test_a_request_with_any_other_state_is_refused_and_the_wait_continues(gfake):
    state, other, port = agency.new_oauth_state(), agency.new_oauth_state(), free_port()
    t, out = start(state, port)
    assert get(port, f"{PATH}?code=A&state={other}")[0] == 400  # a state this process did not issue
    assert get(port, f"{PATH}?code=A")[0] == 400  # no state at all
    assert get(port, f"{PATH}?code=A&state=")[0] == 400
    assert "result" not in out and t.is_alive()  # still waiting
    assert get(port, f"{PATH}?code=THE-CODE&state={state}")[0] == 200
    t.join(10)
    assert out["result"] == ("THE-CODE", None)


def test_only_a_get_on_the_exact_path_is_served(gfake):
    state, port = agency.new_oauth_state(), free_port()
    t, out = start(state, port)
    assert get(port, f"/other?code=A&state={state}")[0] == 404
    assert get(port, f"{PATH}/extra?code=A&state={state}")[0] == 404
    for method in ("POST", "PUT", "DELETE"):
        assert get(port, f"{PATH}?code=A&state={state}", method=method)[0] == 405
    assert "result" not in out and t.is_alive()
    get(port, f"{PATH}?code=A&state={state}")
    t.join(10)


def test_googles_error_answer_is_reported_without_a_code(gfake):
    state, port = agency.new_oauth_state(), free_port()
    t, out = start(state, port)
    assert get(port, f"{PATH}?error=access_denied&state={state}")[0] == 200
    t.join(10)
    assert out["result"] == (None, "access_denied")


def test_it_gives_up_at_the_time_limit_and_frees_the_port(gfake):
    port = free_port()
    server = agency_listen.open_listener("127.0.0.1", port)
    started = time.monotonic()
    with pytest.raises(agency_listen.ListenError, match="No sign-in arrived"):
        agency_listen.wait_for_callback(server, path=PATH, expected_state=agency.new_oauth_state(), timeout=1.2)
    assert time.monotonic() - started < 6
    agency_listen.open_listener("127.0.0.1", port).server_close()  # the port is free again


def test_a_busy_port_is_reported_at_once_and_names_the_likely_cause():
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    try:
        with pytest.raises(agency_listen.ListenError, match="docker stop flowqr-frontend-1"):
            agency_listen.open_listener("127.0.0.1", busy.getsockname()[1])
    finally:
        busy.close()


def test_the_listener_writes_no_log_line_so_the_code_is_never_in_a_log(gfake, capsys):
    state, port = agency.new_oauth_state(), free_port()
    t, out = start(state, port)
    get(port, f"{PATH}?code=SECRET-LOOKING-CODE&state={state}")
    t.join(10)
    seen = capsys.readouterr()
    assert "SECRET-LOOKING-CODE" not in seen.out + seen.err and state not in seen.out + seen.err


# ------------------------------------------------------------------ the command, end to end against the fake Google
def _args(**over):
    base = dict(cmd="google-agency-register", label="flowhq-agency-listen", code=None, state=None, listen=True, listen_host="127.0.0.1", listen_timeout=20,
                location_group_id="5488245563", max_locations=None, expect_email=EMAIL)
    base.update(over)
    return SimpleNamespace(**base)


def run_command(cli, args):
    result: dict = {}
    t = threading.Thread(target=lambda: result.__setitem__("rc", cli._agency_cli(args)), daemon=True)
    t.start()
    return t, result


def wait_for_url(capsys, seen: list[str]) -> str:
    """The state is in the sign-in address the command prints: that is how a person gets it too."""
    import re

    for _ in range(100):
        seen.append(capsys.readouterr().out)
        m = re.search(r"state=([^&\s]+)", "".join(seen))
        if m:
            return m.group(1)
        time.sleep(0.05)
    raise AssertionError("the command never printed its sign-in address")


def test_listen_mode_registers_from_a_real_redirect_without_anything_being_copied(gfake, monkeypatch, capsys):
    from app import cli

    spy = Spy()
    monkeypatch.setattr(g, "get_google_provider", lambda: spy)
    port = free_port()
    monkeypatch.setattr(settings, "google_redirect_uri", f"http://localhost:{port}{PATH}")
    t, result = run_command(cli, _args())
    seen: list[str] = []
    state = wait_for_url(capsys, seen)
    status, body = get(port, f"{PATH}?code=THE-CODE&state={state}&scope=x&authuser=0&hd=flowhq.co.in")
    t.join(20)
    seen.append(capsys.readouterr().out)
    out = "".join(seen)
    assert result["rc"] == 0 and status == 200 and spy.exchanged == ["THE-CODE"]
    assert "PASS: agency account 'flowhq-agency-listen' stored" in out and "Received the sign-in" in out
    assert "THE-CODE" not in out and "THE-CODE" not in body and AGENCY_REFRESH not in out and AGENCY_ACCESS not in out  # the code is never printed or shown
    with system_session() as db:
        row = db.scalar(select(GoogleAgencyAccount).where(GoogleAgencyAccount.label == "flowhq-agency-listen"))
        assert row is not None and row.google_email == EMAIL and AGENCY_REFRESH not in row.refresh_token_encrypted  # stored, encrypted, for the right account


def test_listen_mode_stores_nothing_and_revokes_when_the_wrong_google_account_signs_in(gfake, monkeypatch, capsys):
    from app import cli

    spy = Spy("apigbp@gmail.com")  # the OLD account signs in
    monkeypatch.setattr(g, "get_google_provider", lambda: spy)
    port = free_port()
    monkeypatch.setattr(settings, "google_redirect_uri", f"http://localhost:{port}{PATH}")
    t, result = run_command(cli, _args(label="flowhq-agency-wrongacct"))
    seen: list[str] = []
    state = wait_for_url(capsys, seen)
    get(port, f"{PATH}?code=C&state={state}")
    t.join(20)
    out = "".join(seen) + capsys.readouterr().out
    assert result["rc"] == 1 and "not the expected agency account" in out and spy.revoked
    with system_session() as db:
        assert db.scalar(select(GoogleAgencyAccount).where(GoogleAgencyAccount.google_email == "apigbp@gmail.com")) is None


def test_listen_mode_reports_a_refused_sign_in_and_never_calls_google(gfake, monkeypatch, capsys):
    from app import cli

    spy = Spy()
    monkeypatch.setattr(g, "get_google_provider", lambda: spy)
    port = free_port()
    monkeypatch.setattr(settings, "google_redirect_uri", f"http://localhost:{port}{PATH}")
    t, result = run_command(cli, _args(label="flowhq-agency-denied"))
    seen: list[str] = []
    state = wait_for_url(capsys, seen)
    get(port, f"{PATH}?error=access_denied&state={state}")
    t.join(20)
    out = "".join(seen) + capsys.readouterr().out
    assert result["rc"] == 1 and "did not complete the sign-in (access_denied)" in out and spy.exchanged == []


def test_listen_mode_with_a_busy_port_fails_before_any_address_is_shown(gfake, monkeypatch, capsys):
    from app import cli

    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    monkeypatch.setattr(settings, "google_redirect_uri", f"http://localhost:{busy.getsockname()[1]}{PATH}")
    try:
        assert cli._agency_cli(_args()) == 1
    finally:
        busy.close()
    out = capsys.readouterr().out
    assert "docker stop flowqr-frontend-1" in out and "accounts.google" not in out and "state=" not in out  # you are told before you sign in, not after


def test_listen_mode_refuses_a_redirect_that_is_not_localhost(gfake, monkeypatch, capsys):
    from app import cli

    monkeypatch.setattr(settings, "google_redirect_uri", "https://api.flowqr.site/api/v1/google/callback")
    assert cli._agency_cli(_args()) == 1
    out = capsys.readouterr().out
    assert "http://localhost" in out and "state=" not in out


def test_without_listen_both_code_and_state_are_still_needed(gfake, capsys):
    from app import cli

    assert cli._agency_cli(_args(listen=False, code="C", state=None)) == 1
    assert "give both --code and --state" in capsys.readouterr().out
    assert cli._agency_cli(_args(listen=False, code=None, state=agency.new_oauth_state())) == 1
    assert "give both --code and --state" in capsys.readouterr().out
