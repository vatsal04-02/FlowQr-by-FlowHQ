"""Phase 1.5: live-validation preparation and data retention. MOCKED: the governed-path live test runs against a test double and says so ("mode": "mocked"); nothing here is evidence
about real Google. The retention tests use the real database, the real append-only trigger and the real cascade."""
import argparse
import json
import uuid
from datetime import timedelta

import pytest

from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.models import GoogleLocation
from app.models.base import utcnow
from app.ops_cli import LIVE_ENV, autonomy_live_test, add_commands
from app.services import account
from app.services import google as g
from app.services.agent import history, retention
from tests.conftest import owner_exec, owner_query
from tests.test_google_and_reviews import connected, sync_select  # noqa: F401
from tests.test_phase15_governed import GovGoogle, scheduled_post, acts, events  # noqa: F401


@pytest.fixture()
def fake(monkeypatch):
    f = GovGoogle()
    monkeypatch.setattr(g, "get_google_provider", lambda: f)
    return f


@pytest.fixture()
def gid(connected, fake):  # noqa: F811
    sync_select(connected, fake)
    return connected.glocs[0]["id"]


@pytest.fixture(autouse=True)
def _quiet():
    owner_exec("UPDATE agent_actions SET status = 'canceled' WHERE status IN ('pending_approval', 'approved', 'executing')")
    owner_exec("UPDATE scheduled_posts SET status = 'canceled' WHERE status IN ('scheduled', 'publishing')")
    yield


def loc_name(gid_):
    return owner_query("SELECT google_location_name FROM google_locations WHERE id = :g", g=gid_)[0][0]


def conn_of(gid_):
    return str(owner_query("SELECT connection_id FROM google_locations WHERE id = :g", g=gid_)[0][0])


def args(location, **kw):
    base = dict(connection=None, location=location, profile=True, post=True, execute=False, confirm_location=None, confirm_title=None, report=None)
    return argparse.Namespace(**{**base, **kw})


# ============================================================================ the governed-path live test (prepared, not run live)

def test_the_governed_live_test_is_a_dry_run_unless_told_otherwise(connected, fake, gid, capsys):
    rc = autonomy_live_test(args(loc_name(gid), connection=conn_of(gid)), provider=fake)
    out = capsys.readouterr().out
    assert rc == 0 and "DRY RUN" in out and "NOT EXECUTED" in out and "MOCKED PROVIDER" in out and fake.writes == [] and fake.posts == []


def test_the_governed_live_test_refuses_without_all_three_confirmations(connected, fake, gid, monkeypatch, capsys):
    loc = loc_name(gid)
    assert autonomy_live_test(args(loc, connection=conn_of(gid), execute=True, confirm_location="locations/other"), provider=fake) == 2  # location not repeated
    monkeypatch.delenv(LIVE_ENV, raising=False)
    assert autonomy_live_test(args(loc, connection=conn_of(gid), execute=True, confirm_location=loc), provider=fake) == 2  # the person did not export the authorisation
    monkeypatch.setenv(LIVE_ENV, loc)
    assert autonomy_live_test(args(loc, connection=conn_of(gid), execute=True, confirm_location=loc, confirm_title="Not the title"), provider=fake) == 2  # nobody looked at which profile this is
    assert "Nothing was sent" in capsys.readouterr().out and fake.writes == [] and fake.posts == []


def test_the_governed_live_test_goes_through_the_engine_and_every_step_is_read_back(connected, fake, gid, monkeypatch, tmp_path, capsys):
    loc = loc_name(gid)
    monkeypatch.setenv(LIVE_ENV, loc)
    original = fake.details["description"]
    report = tmp_path / "r.json"
    rc = autonomy_live_test(args(loc, connection=conn_of(gid), execute=True, confirm_location=loc, confirm_title=fake.details["title"], report=str(report)), provider=fake, sleep=lambda s: None)
    assert rc == 0 and fake.details["description"] == original and fake.posts == []  # restored; the test post is gone
    rep = json.loads(report.read_text())
    assert rep["mode"] == "mocked" and rep["failed"] == 0 and all(r["verified_by_read_back"] for r in rep["results"]) and len(rep["results"]) == 4
    assert "MOCKED" in capsys.readouterr().out and "NOT evidence" in rep["note"].replace("not evidence", "NOT evidence") or "not evidence" in rep["note"]
    kinds = owner_query("SELECT action_type, status, verification->>'matched' FROM agent_actions WHERE tenant_id = :t ORDER BY created_at", t=connected.tenant_id)
    assert kinds.count(("description_improve", "executed", "true")) == 2 and ("publish_content", "executed", "true") in kinds and ("content_delete", "executed", "true") in kinds
    for (aid,) in owner_query("SELECT id FROM agent_actions WHERE tenant_id = :t AND status = 'executed'", t=connected.tenant_id):
        db = SessionLocal(); set_rls_context(db, bypass=True)
        assert history.verify(db, aid)["ok"] is True
        db.close()


def test_a_governed_live_test_fails_loudly_when_google_does_not_show_the_change(connected, fake, gid, monkeypatch, tmp_path):
    loc = loc_name(gid)
    monkeypatch.setenv(LIVE_ENV, loc)
    fake.update_location = lambda at, name, changes: dict(fake.details)  # a 200 that stores nothing
    report = tmp_path / "r.json"
    rc = autonomy_live_test(args(loc, connection=conn_of(gid), post=False, execute=True, confirm_location=loc, confirm_title=fake.details["title"], report=str(report)), provider=fake, sleep=lambda s: None)
    rep = json.loads(report.read_text())
    assert rc == 1 and rep["failed"] == 1 and rep["results"][0]["status"] != "PASS" and rep["results"][0]["verified_by_read_back"] is False


def test_the_command_is_registered_in_the_cli():
    p = argparse.ArgumentParser()
    add_commands(p.add_subparsers(dest="cmd"))
    ns = p.parse_args(["autonomy-live-test", "--location", "locations/1", "--profile"])
    assert ns.cmd == "autonomy-live-test" and ns.execute is False and ns.profile is True


# ============================================================================ retention

def _executed_action(connected, gid_):
    from app.workers.tasks import publish_due_posts
    sid = scheduled_post(connected, gid_)
    publish_due_posts.run()
    aid = acts(sid)[0][8]
    assert acts(sid)[0][0] == "executed"
    return aid


def test_finished_actions_past_retention_are_erased_whole_and_counted_not_described(connected, fake, gid):
    old, recent = _executed_action(connected, gid), _executed_action(connected, gid)
    owner_exec("UPDATE agent_actions SET created_at = now() - interval '800 days' WHERE id = :a", a=old)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    out = retention.purge_old_history(db)
    db.close()
    assert out["actions"] >= 1 and out["tenants"] >= 1
    assert owner_query("SELECT count(*) FROM agent_actions WHERE id = :a", a=old)[0][0] == 0
    for table in ("agent_action_approvals", "agent_intervention_events"):  # the record went whole: nothing of it is left behind
        assert owner_query(f"SELECT count(*) FROM {table} WHERE action_id = :a", a=old)[0][0] == 0
    assert owner_query("SELECT count(*) FROM agent_actions WHERE id = :a", a=recent)[0][0] == 1 and len(events(recent)) > 3
    meta = owner_query("SELECT metadata FROM audit_logs WHERE action = 'autonomy.history_purged' AND tenant_id = :t ORDER BY created_at DESC LIMIT 1", t=connected.tenant_id)[0][0]
    assert set(meta) == {"records", "older_than", "retention_days"} and meta["records"] >= 1  # a count and a date; no content


def test_retention_never_touches_live_work_or_actions_still_being_measured(connected, fake, gid):
    from app.models import AgentAction
    done = _executed_action(connected, gid)
    owner_exec("UPDATE agent_actions SET created_at = now() - interval '900 days' WHERE id = :a", a=done)
    owner_exec("INSERT INTO agent_rank_followups (id, tenant_id, action_id, google_location_id, day_offset, due_at, status, attempts) "
               "SELECT gen_random_uuid(), tenant_id, id, google_location_id, 28, now() + interval '5 days', 'pending', 0 FROM agent_actions WHERE id = :a", a=done)
    live = _executed_action(connected, gid)
    owner_exec("UPDATE agent_actions SET created_at = now() - interval '900 days', status = 'pending_approval', verified_at = NULL WHERE id = :a", a=live)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    retention.purge_old_history(db)
    assert db.get(AgentAction, done) is not None and db.get(AgentAction, live) is not None  # one is being measured, one is waiting for a person
    db.close()
    owner_exec("UPDATE agent_rank_followups SET status = 'done' WHERE action_id = :a", a=done)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    retention.purge_old_history(db)
    assert db.get(AgentAction, done) is None and db.get(AgentAction, live) is not None  # measured and finished: erased; the waiting one is still waiting
    db.close()


def test_retention_can_be_switched_off(connected, fake, gid, monkeypatch):
    a = _executed_action(connected, gid)
    owner_exec("UPDATE agent_actions SET created_at = now() - interval '5000 days' WHERE id = :a", a=a)
    monkeypatch.setattr(settings, "autonomy_history_retention_days", 0)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert retention.purge_old_history(db)["actions"] == 0
    db.close()
    assert owner_query("SELECT count(*) FROM agent_actions WHERE id = :a", a=a)[0][0] == 1


def test_the_retention_job_exists_runs_daily_and_the_flag_does_not_leak(connected, fake, gid):
    from app.workers import tasks
    from app.workers.celery_app import celery_app
    assert celery_app.conf.beat_schedule["autonomy-retention"]["task"] == "flowqr.autonomy_retention" and celery_app.conf.beat_schedule["autonomy-retention"]["schedule"] == 86400.0
    a = _executed_action(connected, gid)
    assert set(tasks.autonomy_retention.run()) == {"actions", "tenants", "grid_scans"}
    # the erase permission is transaction-local: after the job a normal session still cannot delete history
    db = SessionLocal(); set_rls_context(db, bypass=True)
    from sqlalchemy import text
    with pytest.raises(Exception) as exc:
        db.execute(text("DELETE FROM agent_intervention_events WHERE action_id = :a"), {"a": a})
    assert "append-only" in str(exc.value) or "permission denied" in str(exc.value)
    db.close()


def test_old_map_scans_are_erased_with_their_points(connected, fake, gid):
    from app.models import RankGrid
    db = SessionLocal(); set_rls_context(db, bypass=True)
    owner_exec("UPDATE google_locations SET lat = 26.85, lng = 80.95, place_id = 'PID' WHERE id = :g", g=gid)
    owner_exec("INSERT INTO rank_keywords (id, created_at, updated_at, tenant_id, google_location_id, keyword) VALUES (gen_random_uuid(), now(), now(), :t, :g, 'physio') ON CONFLICT DO NOTHING", t=connected.tenant_id, g=gid)
    kid = owner_query("SELECT id FROM rank_keywords WHERE google_location_id = :g LIMIT 1", g=gid)[0][0]
    gridid = uuid.uuid4()
    owner_exec("INSERT INTO rank_grids (id, created_at, updated_at, tenant_id, google_location_id, name, mode, points, points_hash, active) VALUES (:i, now(), now(), :t, :g, 'old', 'square', '[]', 'h', true)", i=gridid, t=connected.tenant_id, g=gid)
    sid = uuid.uuid4()
    owner_exec("INSERT INTO rank_grid_scans (id, tenant_id, google_location_id, grid_id, keyword_id, points_hash, source, status, started_at, points_total, points_ok, points_found, calls) "
               "VALUES (:s, :t, :g, :gr, :k, 'h', 'auto', 'done', now() - interval '500 days', 1, 1, 1, 1)", s=sid, t=connected.tenant_id, g=gid, gr=gridid, k=kid)
    owner_exec("INSERT INTO rank_grid_points (id, tenant_id, scan_id, point_index, lat, lng, status, rank, checked_at) VALUES (gen_random_uuid(), :t, :s, 0, 26.85, 80.95, 'ok', 3, now() - interval '500 days')", t=connected.tenant_id, s=sid)
    assert retention.purge_old_history(db)["grid_scans"] >= 1
    db.close()
    assert owner_query("SELECT count(*) FROM rank_grid_scans WHERE id = :s", s=sid)[0][0] == 0 and owner_query("SELECT count(*) FROM rank_grid_points WHERE scan_id = :s", s=sid)[0][0] == 0
    owner_exec("DELETE FROM rank_grids WHERE tenant_id = :t", t=connected.tenant_id)
    owner_exec("DELETE FROM rank_keywords WHERE tenant_id = :t", t=connected.tenant_id)
    assert RankGrid is not None


# ============================================================================ offboarding and data rights

def test_the_owners_data_export_includes_the_autonomy_records_and_maps_without_secrets(connected, fake, gid):
    a = _executed_action(connected, gid)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    from app.models import Tenant
    data, manifest = account.build_export(db, db.get(Tenant, uuid.UUID(connected.tenant_id)))
    db.close()
    for f in ("agent_actions.json", "agent_action_approvals.json", "agent_intervention_events.json", "agent_rank_followups.json", "rank_grids.json", "rank_grid_scans.json", "rank_grid_points.json", "rank_keywords.json"):
        assert f in manifest["files"], f
    assert manifest["files"]["agent_actions.json"] >= 1 and manifest["files"]["agent_intervention_events.json"] >= 4
    import io
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(data))
    rows = json.loads(z.read("agent_actions.json"))
    assert any(r["id"] == str(a) for r in rows) and all("idempotency_key" not in r for r in rows)  # the internal dedupe key is never exported


def test_deleting_a_business_erases_its_autonomy_records_and_maps_but_not_another_businesses(connected, fake, gid):
    from tests.conftest import make_business
    a = _executed_action(connected, gid)
    other = make_business("Stays Clinic")
    owner_exec("INSERT INTO agent_settings (id, created_at, updated_at, tenant_id) VALUES (gen_random_uuid(), now(), now(), :t) ON CONFLICT DO NOTHING", t=other.tenant_id)
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert account.delete_tenant(db, uuid.UUID(connected.tenant_id), provider=fake)["deleted"] is True
    db.close()
    for table in ("agent_actions", "agent_action_approvals", "agent_intervention_events", "agent_rank_followups", "rank_grids", "rank_grid_scans", "rank_grid_points", "rank_keywords"):
        assert owner_query(f"SELECT count(*) FROM {table} WHERE tenant_id = :t", t=connected.tenant_id)[0][0] == 0, table
    assert owner_query("SELECT count(*) FROM tenants WHERE id = :t", t=other.tenant_id)[0][0] == 1
    assert owner_query("SELECT count(*) FROM agent_actions WHERE id = :a", a=a)[0][0] == 0


def test_removing_a_person_keeps_the_history_intact_and_identifies_nobody(connected, fake, gid):
    a = _executed_action(connected, gid)
    uid = owner_query("SELECT approved_by FROM scheduled_posts WHERE tenant_id = :t AND approved_by IS NOT NULL LIMIT 1", t=connected.tenant_id)[0][0]
    assert owner_query("SELECT count(*) FROM agent_intervention_events WHERE action_id = :a AND user_id = :u", a=a, u=uid)[0][0] >= 1  # the record names the person only by an opaque id
    owner_exec("DELETE FROM users WHERE id = :u", u=uid)  # the person is erased from FlowQR
    db = SessionLocal(); set_rls_context(db, bypass=True)
    assert history.verify(db, a)["ok"] is True  # the tamper-evident chain still verifies: no row had to be edited
    db.close()
    assert owner_query("SELECT count(*) FROM users WHERE id = :u", u=uid)[0][0] == 0  # nothing left that maps the id back to a name or an email
    assert owner_query("SELECT authorized_by FROM agent_action_approvals WHERE action_id = :a", a=a)[0][0] is None  # the approval row (not append-only) is anonymised by the database


def test_a_business_that_asked_to_be_deleted_sends_nothing_more_to_google(connected, fake, gid):
    from app.workers.tasks import publish_due_posts
    sid = scheduled_post(connected, gid)
    owner_exec("UPDATE tenants SET deletion_requested_at = now(), deletion_scheduled_for = now() + interval '10 days' WHERE id = :t", t=connected.tenant_id)
    assert publish_due_posts.run()["held"] == 1 and fake.posts == [] and acts(sid) == []
    owner_exec("UPDATE tenants SET deletion_requested_at = NULL, deletion_scheduled_for = NULL WHERE id = :t", t=connected.tenant_id)
    assert publish_due_posts.run()["published"] == 1 and len(fake.posts) == 1
