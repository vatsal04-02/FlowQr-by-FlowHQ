"""Production-readiness hardening: review synchronisation must always end in a state the owner and the operators can see.

Found by the production-readiness audit (PRODUCTION_READINESS_AUDIT.md, finding F-01). A Google response FlowQR cannot parse (here: a review with a malformed timestamp) or any other unexpected
error used to escape `sync_google_location` AFTER the row had been committed as "running". The row then showed "running" forever, no failure was counted and no back-off was set, so every
half-interval the same location was queued again and failed again, three Celery retries each time, while the dashboard and the operations page showed nothing wrong. Mock Google only."""
import uuid
from contextlib import closing
from dataclasses import replace

from sqlalchemy import select

from app.core.db import system_session
from app.models import GoogleLocation, Review
from app.services import ops
from app.services.google.sync import due_locations, sync_google_location
from tests.test_google_and_reviews import connected, fake, greview, sync_select  # noqa: F401  (fixtures)


def _selected_gloc_id(biz):
    return uuid.UUID(biz.glocs[0]["id"])


def _sync(gloc_id, provider):
    with closing(system_session()) as db:
        gloc = db.get(GoogleLocation, gloc_id)
        return sync_google_location(db, gloc, provider, sleep=lambda s: None)


def _row(gloc_id):
    with closing(system_session()) as db:
        g = db.get(GoogleLocation, gloc_id)
        return g.last_sync_status, g.last_sync_error, g.consecutive_failures, g.next_sync_after


def test_an_unparseable_google_review_ends_in_a_visible_error_state_not_running_forever(connected, fake):
    sync_select(connected, fake)  # first, a good sync so the location is selected and healthy
    gid = _selected_gloc_id(connected)
    bad = replace(greview(9), created_at="not-a-date")
    fake.reviews = [greview(1), bad]

    result = _sync(gid, fake)

    status, error, failures, next_after = _row(gid)
    assert result["status"] == "error"
    assert status == "error", "the row must not stay on 'running'"
    assert error and "not-a-date" not in error and "Traceback" not in error  # a plain sentence, no internals
    assert failures == 1 and next_after is not None  # counted, and backed off: the same location is not hammered every cycle


def test_a_failing_location_is_backed_off_so_it_is_not_queued_again_at_once(connected, fake):
    sync_select(connected, fake)
    gid = _selected_gloc_id(connected)
    fake.reviews = [replace(greview(9), updated_at="garbage")]
    _sync(gid, fake)
    with closing(system_session()) as db:
        assert gid not in {x.id for x in due_locations(db)}


def test_the_failure_is_visible_to_the_operations_page(connected, fake):
    sync_select(connected, fake)
    gid = _selected_gloc_id(connected)
    fake.reviews = [replace(greview(9), created_at="nonsense")]
    _sync(gid, fake)
    with closing(system_session()) as db:
        check = ops.check_failed_work(db)
    assert check["status"] in ("warn", "critical"), check


def test_the_good_reviews_before_the_bad_one_are_kept_and_a_later_clean_sync_recovers(connected, fake):
    sync_select(connected, fake)
    gid = _selected_gloc_id(connected)
    fake.reviews = [greview(1), replace(greview(9), created_at="nonsense")]
    _sync(gid, fake)
    fake.reviews = [greview(1), greview(2)]
    with closing(system_session()) as db:  # the back-off has passed
        g = db.get(GoogleLocation, gid)
        g.next_sync_after = None
        db.commit()
    assert _sync(gid, fake)["status"] == "ok"
    status, error, failures, next_after = _row(gid)
    assert (status, error, failures, next_after) == ("ok", None, 0, None)
    with closing(system_session()) as db:
        ids = {r.external_id for r in db.scalars(select(Review).where(Review.google_location_id == gid))}
    assert ids == {"rev-1", "rev-2"}  # no duplicates, nothing lost


def test_one_failing_location_does_not_stop_another_from_syncing(connected, fake):
    """Each location is its own Celery job: a poison location only fails itself."""
    sync_select(connected, fake)
    first = _selected_gloc_id(connected)
    fake.reviews = [replace(greview(9), created_at="nonsense")]
    assert _sync(first, fake)["status"] == "error"
    fake.reviews = [greview(1)]
    other = uuid.UUID(next(g for g in connected.glocs if uuid.UUID(g["id"]) != first)["id"])
    # the second profile is selectable and syncs although the first one is failing
    with closing(system_session()) as db:
        g2 = db.get(GoogleLocation, other)
        g2.selected = True
        db.commit()
    assert _sync(other, fake)["status"] == "ok"
