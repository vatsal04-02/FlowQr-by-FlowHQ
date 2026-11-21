"""The agency path's project model and activation readiness (services/google/agency_activation.py). Mock Google only; nothing here calls Google."""
from contextlib import closing
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings, config_problems, settings
from app.core.db import system_session
from app.models import GoogleConnection, GoogleLocation
from app.services import google as g
from app.services.google import agency, agency_activation as act
from tests.conftest import owner_query
from tests.test_google_agency import _clean, go, seed  # noqa: F401  (_clean is an autouse fixture)
from tests.test_google_agency_group import AGENCY_EMAIL, gfake  # noqa: F401  (gfake is a fixture)
from tests.conftest import make_business

GROUP_RES, ORG_RES = "accounts/114863040359228435467", "accounts/110178313486978980497"


def names(items, status=None):
    return {i.name for i in items if status is None or i.status == status}


def lines():
    with closing(system_session()) as db:
        return act.lines(db)


def fully_configured(monkeypatch, gfake):
    monkeypatch.setattr(settings, "google_agency_location_group_id", GROUP_RES)
    monkeypatch.setattr(settings, "google_agency_organization_id", ORG_RES)
    monkeypatch.setattr(settings, "google_agency_project_model", "flowhq_own_project")
    monkeypatch.setattr(settings, "google_agency_policy_reference", "written-answer-recorded-by-a-person")
    monkeypatch.setattr(settings, "google_content_retention_enabled", True)
    monkeypatch.setattr(settings, "autonomy_emergency_stop", True)
    monkeypatch.setattr(settings, "registration_mode", "allowlist")
    agency.register_account("flowhq-ready", code="c", provider=gfake, location_group_id=GROUP_RES)


# ------------------------------------------------------------------ readiness
def test_by_default_the_agency_path_is_not_ready_and_says_who_has_to_act(monkeypatch):
    monkeypatch.setattr(settings, "google_agency_manager_enabled", False)
    monkeypatch.setattr(settings, "google_agency_operations_enabled", False)
    monkeypatch.setattr(settings, "google_agency_project_model", "")
    monkeypatch.setattr(settings, "google_agency_policy_reference", "")
    items = lines()
    assert not act.ready(items)
    blocked = {i.name: i.who for i in items if i.status == act.BLOCK}
    assert blocked["project model"] == "EXTERNAL" and blocked["policy reference"] == "EXTERNAL"  # only Google can answer these
    assert blocked["agency manager switch"] == "CONFIG" and blocked["agency operations switch"] == "CONFIG" and blocked["retention running"] == "CONFIG"
    assert blocked["agency login registered"] == "DATA"
    assert all(i.detail for i in items) and "never invent" in next(i.detail for i in items if i.name == "policy reference")


def test_with_every_precondition_met_the_check_says_ready_and_still_makes_no_google_call(gfake, monkeypatch):
    fully_configured(monkeypatch, gfake)
    monkeypatch.setattr(settings, "google_agency_manager_enabled", True)
    monkeypatch.setattr(settings, "google_agency_operations_enabled", True)
    n = len(gfake.calls)
    items = lines()
    assert act.ready(items), [(i.name, i.detail) for i in items if i.status == act.BLOCK]
    assert len(gfake.calls) == n  # read-only and offline


@pytest.mark.parametrize("name,setting,value,expected", [
    ("project model", "google_agency_project_model", "", "EXTERNAL"),
    ("policy reference", "google_agency_policy_reference", "", "EXTERNAL"),
    ("retention running", "google_content_retention_enabled", False, "CONFIG"),
    ("no individual fallback", "google_agency_individual_fallback", True, "CONFIG"),
    ("location group id", "google_agency_location_group_id", "5488245563", "CONFIG"),  # the short accountNumber is not a resource name
    ("agency manager switch", "google_agency_manager_enabled", False, "CONFIG"),
    ("agency operations switch", "google_agency_operations_enabled", False, "CONFIG"),
])
def test_removing_any_one_precondition_blocks_activation(gfake, monkeypatch, name, setting, value, expected):
    fully_configured(monkeypatch, gfake)
    monkeypatch.setattr(settings, "google_agency_manager_enabled", True)
    monkeypatch.setattr(settings, "google_agency_operations_enabled", True)
    monkeypatch.setattr(settings, setting, value)
    items = lines()
    blocked = {i.name: i.who for i in items if i.status == act.BLOCK}
    assert not act.ready(items) and blocked.get(name) == expected


def test_a_login_registered_for_another_group_blocks_activation(gfake, monkeypatch):
    fully_configured(monkeypatch, gfake)
    monkeypatch.setattr(settings, "google_agency_manager_enabled", True)
    monkeypatch.setattr(settings, "google_agency_operations_enabled", True)
    monkeypatch.setattr(settings, "google_agency_location_group_id", "accounts/999999999999999999999")
    assert "login group matches" in names(lines(), act.BLOCK)


# ------------------------------------------------------------------ the project model gate
def test_in_production_no_agency_token_is_used_until_the_project_model_and_a_reference_are_both_set(gfake, monkeypatch):
    biz = make_business("Gate Clinic")
    s = seed(biz)
    assert go(biz, s) == [("active", None)]
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "google_agency_policy_reference", "ref")
    monkeypatch.setattr(settings, "google_agency_project_model", "")
    assert agency.operations_enabled() is False  # a reference alone is not enough: the model is undecided
    with closing(system_session()) as db:
        with pytest.raises(g.GoogleAgencyUnavailable):
            agency.token_for_connection(db, db.get(GoogleConnection, s.conn_id), gfake, db.get(GoogleLocation, s.gids[0]))
    monkeypatch.setattr(settings, "google_agency_project_model", "flowhq_own_project")
    monkeypatch.setattr(settings, "google_agency_policy_reference", "")
    assert agency.operations_enabled() is False  # and a model alone is not enough: no recorded answer
    monkeypatch.setattr(settings, "google_agency_policy_reference", "ref")
    assert agency.operations_enabled() is True
    with closing(system_session()) as db:
        assert agency.token_for_connection(db, db.get(GoogleConnection, s.conn_id), gfake, db.get(GoogleLocation, s.gids[0]))  # both set: it resolves


def test_the_audit_entry_for_a_resolved_use_names_the_project_model(gfake, monkeypatch):
    biz = make_business("Audit Project Clinic")
    s = seed(biz)
    go(biz, s)
    monkeypatch.setattr(settings, "google_agency_project_model", "flowhq_own_project")
    with closing(system_session()) as db:
        agency.resolve_agency_access(db, db.get(GoogleConnection, s.conn_id), db.get(GoogleLocation, s.gids[0]))
        db.commit()
    metas = [r[0] for r in owner_query("SELECT metadata FROM audit_logs WHERE action = 'google.agency.used' AND tenant_id = :t", t=biz.tenant_id)]
    assert metas and metas[-1]["project"] == "flowhq_own_project"


def test_the_start_up_guard_refuses_operations_without_a_decided_project_and_any_other_model():
    def prod(**over):
        base = dict(app_env="production", secret_key="s" * 48, token_encryption_key=Fernet.generate_key().decode(), cookie_secure=True, public_card_base_url="https://go.flowqr.co.in",
                    frontend_url="https://app.flowqr.co.in", cors_origins="https://app.flowqr.co.in", database_url="postgresql+psycopg://flowqr_app:Xk29sLmQ8vNa@db:5432/flowqr",
                    platform_admin_emails="ops@flowhq.in", smtp_host="smtp.sendgrid.net", razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20,
                    card_price_paise=19900, google_redirect_uri="https://app.flowqr.co.in/api/v1/google/callback", google_client_id="id", google_client_secret="secret",
                    google_agency_manager_enabled=True, agency_token_encryption_key=Fernet.generate_key().decode(), google_agency_location_group_id=GROUP_RES)
        base.update(over)
        return Settings(_env_file=None, **base)

    assert config_problems(prod()) == []
    bad = config_problems(prod(google_agency_operations_enabled=True, google_agency_policy_reference="ref"))
    assert any("GOOGLE_AGENCY_PROJECT_MODEL=flowhq_own_project" in p for p in bad)
    assert config_problems(prod(google_agency_operations_enabled=True, google_agency_policy_reference="ref", google_agency_project_model="flowhq_own_project")) == []
    for other in ("client_owned_project", "shared", "proxy"):
        assert any("no other project model is supported" in p for p in config_problems(prod(google_agency_project_model=other)))


# ------------------------------------------------------------------ the command
def test_the_command_prints_each_line_exits_non_zero_when_not_ready_and_changes_nothing(capsys, monkeypatch):
    from app import cli

    monkeypatch.setattr(settings, "google_agency_manager_enabled", False)
    before = owner_query("SELECT count(*) FROM google_agency_authorizations")[0][0], owner_query("SELECT count(*) FROM audit_logs")[0][0]
    monkeypatch.setattr("sys.argv", ["app.cli", "google-agency-activation-check"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    out = capsys.readouterr().out
    assert e.value.code == 1 and "AGENCY PATH NOT READY" in out and "[BLOCK] project model" in out and "(EXTERNAL)" in out
    assert (owner_query("SELECT count(*) FROM google_agency_authorizations")[0][0], owner_query("SELECT count(*) FROM audit_logs")[0][0]) == before
    assert "gAAAA" not in out and "accounts/" not in out.replace("`accounts/<long id>`", "")  # no token, no resource name printed
