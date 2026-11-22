"""The V2 live-test command, run against a TEST DOUBLE (MOCKED: the report says "mocked"; nothing here is evidence about Google). It proves the command's own guards and logic:
dry run by default, refusal without the authorisation, the title confirmation or the allowlist, the governed path end to end with read-back, a clean restore, and that a change Google
refuses is blocked and never written."""
import argparse
import json

import pytest

from app.core.config import settings
from app.ops_cli import LIVE_ENV, add_commands, seo_v2_live_test
from app.services import google as g
from app.services.agent.v2 import fields as v2f
from tests.conftest import owner_query
from tests.test_google_and_reviews import connected, sync_select  # noqa: F401
from tests.test_seo_v2_engine import V2Google


@pytest.fixture()
def fake(monkeypatch):
    f = V2Google()

    def validate(at, loc, changes):
        f.validate_calls.append(dict(changes))
        if any("not_a_real_category" in (x.get("c") or "") for x in changes.get("services") or []):
            raise g.GoogleAPIError(400, "serviceItems[1].freeFormServiceItem.category: invalid category")
        return {}
    f.validate_changes = validate
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    return f


@pytest.fixture()
def gid(connected, fake):  # noqa: F811
    sync_select(connected, fake)
    return connected.glocs[0]["id"]


def loc_name(gid_):
    return owner_query("SELECT google_location_name FROM google_locations WHERE id = :g", g=gid_)[0][0]


def conn_of(gid_):
    return str(owner_query("SELECT connection_id FROM google_locations WHERE id = :g", g=gid_)[0][0])


def args(location, **kw):
    base = dict(connection=None, location=location, steps=None, execute=False, confirm_location=None, confirm_title=None, report=None)
    return argparse.Namespace(**{**base, **kw})


def title_of(fake):
    return fake.details["title"]


def test_it_is_a_dry_run_unless_told_otherwise_and_sends_nothing(connected, fake, gid, capsys):
    assert seo_v2_live_test(args(loc_name(gid)), provider=fake) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "NOT EXECUTED" in out and fake.update_calls == 0 and fake.validate_calls == []


def test_every_guard_refuses_before_anything_is_sent(connected, fake, gid, monkeypatch, capsys):
    loc = loc_name(gid)
    monkeypatch.delenv(LIVE_ENV, raising=False)
    monkeypatch.setattr(settings, "seo_v2_test_location_names", loc)
    assert seo_v2_live_test(args(loc, execute=True, confirm_location="locations/other"), provider=fake) == 2  # location not repeated
    assert seo_v2_live_test(args(loc, execute=True, confirm_location=loc), provider=fake) == 2  # the person did not export the authorisation
    monkeypatch.setenv(LIVE_ENV, loc)
    monkeypatch.setattr(settings, "seo_v2_test_location_names", "")
    assert seo_v2_live_test(args(loc, connection=conn_of(gid), execute=True, confirm_location=loc), provider=fake) == 2  # not in the allowlist: the V2 gate is closed for it
    assert "not in SEO_V2_TEST_LOCATION_NAMES" in capsys.readouterr().out
    monkeypatch.setattr(settings, "seo_v2_test_location_names", loc)
    assert seo_v2_live_test(args(loc, connection=conn_of(gid), execute=True, confirm_location=loc, confirm_title="Some other clinic"), provider=fake) == 2  # wrong profile
    assert fake.update_calls == 0 and fake.validate_calls == [] and fake.attr_calls == []


def test_the_full_run_goes_through_the_engine_reads_back_and_restores_the_profile(connected, fake, gid, monkeypatch, tmp_path, capsys):
    loc = loc_name(gid)
    monkeypatch.setenv(LIVE_ENV, loc)
    monkeypatch.setattr(settings, "seo_v2_test_location_names", loc)
    before_services = v2f.canon_services(fake.details["service_items"])
    before_special = v2f.canon_special_hours(fake.details["special_hours_periods"])
    report = tmp_path / "r.json"
    rc = seo_v2_live_test(args(loc, connection=conn_of(gid), execute=True, confirm_location=loc, confirm_title=title_of(fake), report=str(report)), provider=fake)
    out = capsys.readouterr().out
    rep = json.loads(report.read_text())
    assert rc == 0 and rep["mode"] == "mocked" and rep["failed"] == 0, out
    by = {r["step"]: r for r in rep["results"]}
    assert by["special-hours: add one closed day through the engine, Google must show it"]["verified_by_read_back"] is True
    assert by["services: add one marked custom service through the engine, Google must show the complete list"]["verified_by_read_back"] is True
    assert "dry run validated via validateOnly" in by["services: add one marked custom service through the engine, Google must show the complete list"]["detail"]
    assert by["failure: the refused change is blocked in Google's dry run and never reported as success"]["status"] == "PASS"
    assert by["the test profile is back exactly as it was (services and special hours)"]["status"] == "PASS"
    assert v2f.canon_services(fake.details["service_items"]) == before_services and v2f.canon_special_hours(fake.details["special_hours_periods"]) == before_special
    assert "MOCKED" in out
    # the refused change was never written: the only service writes are the add and the restore
    assert len([w for w in fake.writes if "services" in w[1]]) == 2


def test_a_change_google_refuses_is_never_written_even_if_the_dry_run_were_to_pass(connected, fake, gid, monkeypatch, tmp_path):
    loc = loc_name(gid)
    monkeypatch.setenv(LIVE_ENV, loc)
    monkeypatch.setattr(settings, "seo_v2_test_location_names", loc)
    fake.validate_changes = lambda at, l, changes: {}  # Google (wrongly) accepts the invalid category in the dry run
    report = tmp_path / "r.json"
    rc = seo_v2_live_test(args(loc, connection=conn_of(gid), steps=["failure"], execute=True, confirm_location=loc, confirm_title=title_of(fake), report=str(report)), provider=fake)
    rep = json.loads(report.read_text())
    assert rc == 1 and rep["failed"] >= 1  # the step reports it could NOT demonstrate a refusal
    assert fake.update_calls == 0 and not any("services" in w[1] for w in fake.writes)  # and nothing was written


def test_a_profile_without_regular_hours_or_with_a_locked_list_skips_with_the_real_reason(connected, fake, gid, monkeypatch, tmp_path):
    loc = loc_name(gid)
    monkeypatch.setenv(LIVE_ENV, loc)
    monkeypatch.setattr(settings, "seo_v2_test_location_names", loc)
    fake.details["has_regular_hours"] = False
    fake.details["can_modify_service_list"] = False
    report = tmp_path / "r.json"
    rc = seo_v2_live_test(args(loc, connection=conn_of(gid), steps=["special-hours", "services", "failure"], execute=True, confirm_location=loc, confirm_title=title_of(fake), report=str(report)), provider=fake)
    rep = json.loads(report.read_text())
    assert rc == 0 and fake.update_calls == 0 and fake.validate_calls == []
    assert [r["status"] for r in rep["results"] if r["step"] != "the test profile is back exactly as it was (services and special hours)"] == ["SKIP", "SKIP", "SKIP"]


def test_the_command_is_registered():
    import argparse as ap
    p = ap.ArgumentParser()
    add_commands(p.add_subparsers(dest="cmd"))
    ns = p.parse_args(["seo-v2-live-test", "--location", "locations/1"])
    assert ns.cmd == "seo-v2-live-test" and ns.execute is False and ns.steps is None
