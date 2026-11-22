"""Monitoring improvement: a customer location failing to sync for 6 hours or more is CRITICAL and e-mails the platform admins, even when it is the only location in the system.

Before this, `check_failed_work` was only a warning until 10 failures, and e-mails and the Sentry message are sent only for critical, so with a handful of customers nobody was told. Mock Google only;
Redis is the in-memory fake from test_ops."""
from datetime import timedelta

import pytest

from app.core.config import settings
from app.core.db import system_session
from app.models.base import utcnow
from app.services import mailer, ops
from tests.conftest import owner_exec, owner_query
from tests.test_google_and_reviews import connected, fake, greview, sync_select  # noqa: F401  (fixtures)
from tests.test_ops import redis  # noqa: F401  (fixture)


def _setup(biz, fake_provider):
    fake_provider.reviews = [greview(1)]
    sync_select(biz, fake_provider)
    # the shared test database may hold other tests' locations: park them as healthy so that only THIS business can make the check fire
    owner_exec("UPDATE google_locations SET last_sync_status = 'ok' WHERE tenant_id <> :t", t=biz.tenant_id)
    return biz.glocs[0]["id"]


def _set(gid, status="error", synced_hours_ago=7, selected=True):
    when = f"now() - interval '{synced_hours_ago} hours'" if synced_hours_ago is not None else "NULL"
    owner_exec(f"UPDATE google_locations SET last_sync_status = :s, last_synced_at = {when}, selected = :sel WHERE id = :g", s=status, sel=selected, g=gid)


def _check():
    db = system_session()
    try:
        return ops.check_stuck_sync(db)
    finally:
        db.close()


def _full():
    db = system_session()
    try:
        return ops.run_checks(db)
    finally:
        db.close()


def test_a_single_location_failing_for_six_hours_is_critical_although_fewer_than_ten_exist(connected, fake):
    gid = _setup(connected, fake)
    _set(gid, "error", synced_hours_ago=7)
    c = _check()
    assert c["status"] == "critical" and c["detail"].startswith("1 customer location(s)")
    by = {x["id"]: x for x in _full()["checks"]}
    assert by["sync_stuck"]["status"] == "critical"
    assert by["failed_work"]["status"] == "warn"  # the old check still only warns for one failure: this is the gap the new check closes


@pytest.mark.parametrize("hours,expected", [(5.9, "ok"), (6.1, "critical"), (30, "critical")])
def test_the_threshold_is_six_hours_since_the_last_good_sync(connected, fake, hours, expected):
    gid = _setup(connected, fake)
    owner_exec("UPDATE google_locations SET last_sync_status = 'error', last_synced_at = now() - make_interval(secs => :s) WHERE id = :g", s=int(hours * 3600), g=gid)
    assert _check()["status"] == expected


def test_a_location_that_syncs_again_clears_it(connected, fake):
    gid = _setup(connected, fake)
    _set(gid, "error", 8)
    assert _check()["status"] == "critical"
    _set(gid, "ok", 0)
    assert _check()["status"] == "ok"


def test_other_statuses_and_a_healthy_old_sync_do_not_count(connected, fake):
    gid = _setup(connected, fake)
    for status in ("ok", "running", "rate_limited", "awaiting_approval", "skipped"):
        _set(gid, status, 9)
        assert _check()["status"] == "ok", status  # only a real error is this alert; quota and approval waits are shown by their own checks


def test_a_location_that_never_synced_is_measured_from_when_it_was_created(connected, fake):
    gid = _setup(connected, fake)
    _set(gid, "error", None)
    owner_exec("UPDATE google_locations SET created_at = now() - interval '2 hours' WHERE id = :g", g=gid)
    assert _check()["status"] == "ok"
    owner_exec("UPDATE google_locations SET created_at = now() - interval '7 hours' WHERE id = :g", g=gid)
    assert _check()["status"] == "critical"


def test_a_revoked_connection_that_stays_in_error_counts(connected, fake):
    gid = _setup(connected, fake)
    _set(gid, "error", 12)
    owner_exec("UPDATE google_connections SET status = 'revoked' WHERE id = :c", c=connected.conn_id)
    assert _check()["status"] == "critical"
    owner_exec("UPDATE google_connections SET status = 'active' WHERE id = :c", c=connected.conn_id)


def test_deselected_suspended_and_deleting_businesses_are_not_counted(connected, fake):
    gid = _setup(connected, fake)
    _set(gid, "error", 9, selected=False)
    assert _check()["status"] == "ok"  # no longer synced on purpose
    _set(gid, "error", 9, selected=True)
    owner_exec("UPDATE tenants SET suspended_at = now() WHERE id = :t", t=connected.tenant_id)
    assert _check()["status"] == "ok"
    owner_exec("UPDATE tenants SET suspended_at = NULL, deletion_scheduled_for = now() + interval '10 days' WHERE id = :t", t=connected.tenant_id)
    assert _check()["status"] == "ok"
    owner_exec("UPDATE tenants SET deletion_scheduled_for = NULL WHERE id = :t", t=connected.tenant_id)
    assert _check()["status"] == "critical"


def test_the_alert_text_carries_counts_only_never_a_business_name_or_location(connected, fake):
    gid = _setup(connected, fake)
    _set(gid, "error", 9)
    c = _check()
    text = " ".join([c["label"], c["detail"], c["action"]])
    name = owner_query("SELECT name FROM tenants WHERE id = :t", t=connected.tenant_id)[0][0]
    title = owner_query("SELECT title FROM google_locations WHERE id = :g", g=gid)[0][0]
    assert name not in text and title not in text and "@" not in text  # this text goes to Sentry as well as to e-mail


def test_the_platform_admins_are_e_mailed_once_and_again_only_after_it_clears(connected, fake, redis, monkeypatch):
    monkeypatch.setattr(settings, "platform_admin_emails", "ops-a@example.com,ops-b@example.com")
    gid = _setup(connected, fake)
    _set(gid, "error", 7)
    mailer.OUTBOX.clear()
    assert "sync_stuck" in ops.alert_on_new_critical(_full())
    mails = [m for m in mailer.OUTBOX if "Customer syncs failing for hours" in m["subject"] + m["body"]]
    assert sorted(m["to"] for m in mails) == ["ops-a@example.com", "ops-b@example.com"]
    assert "1 customer location(s) have been failing to sync for 6 hours or more" in mails[0]["body"]
    mailer.OUTBOX.clear()
    assert "sync_stuck" not in ops.alert_on_new_critical(_full()) and mailer.OUTBOX == []  # ops_watch runs every 15 minutes: no repeat while it lasts
    _set(gid, "ok", 0)
    ops.alert_on_new_critical(_full())  # recovered: forgotten
    _set(gid, "error", 7)
    assert "sync_stuck" in ops.alert_on_new_critical(_full())  # breaks again: told again


def test_it_is_part_of_the_operations_page_and_changes_the_overall_status(connected, fake):
    gid = _setup(connected, fake)
    _set(gid, "ok", 0)
    assert {c["id"]: c for c in _full()["checks"]}["sync_stuck"]["status"] == "ok"
    _set(gid, "error", 7)
    full = _full()
    assert full["status"] == "critical" and full["counts"]["critical"] >= 1
