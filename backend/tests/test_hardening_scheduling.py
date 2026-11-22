"""Production-readiness hardening: scheduled publishing must not let one business's blocked items starve everyone else's (audit finding F-02).

`publish_due_posts` (and `publish_due_media`) take the OLDEST five due items each time. An item that is deliberately not sent (its business is suspended or has asked to be deleted, its plan lapsed,
it has no person's approval) stays `scheduled` with nothing to say "not before ...", so it stayed at the front of that list on every run: with five or more of them, every later item of every other
business was never reached. Held items must wait (and still publish when the reason goes away), without hiding behind-the-queue work. Mock Google only."""
import uuid
from datetime import timedelta

from app.core.db import SessionLocal, set_rls_context
from app.models import ScheduledMedia
from app.models.base import utcnow
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_google_and_reviews import callback, connect, sync_select
from tests.test_google_and_reviews import connected  # noqa: F401  (fixture)
from tests.test_phase0_post_publishing import _no_leftover_posts, fake, gid, make_post, rg, row  # noqa: F401  (fixtures and helpers)


def _second_business(fake_provider):
    biz = make_business("Second Clinic")
    r = callback(biz, connect(biz, fake_provider))
    assert r.status_code == 303 and "connected=1" in r.headers["location"]
    status = biz.get("/google/status").json()
    biz.conn_id = status["connections"][0]["id"]
    biz.glocs = biz.get(f"/google/connections/{biz.conn_id}/locations").json()
    sync_select(biz, fake_provider)
    return biz


def _tenant_of(gid_):
    return owner_query("SELECT tenant_id FROM google_locations WHERE id = :g", g=gid_)[0][0]


def test_posts_of_a_suspended_business_do_not_starve_another_business(connected, fake, gid):
    from app.workers.tasks import publish_due_posts

    other = _second_business(fake)
    other_gid = other.glocs[0]["id"]
    blocked = [make_post(gid, f"Blocked post number {i}: our clinic is open this week.") for i in range(7)]  # more than one batch of five
    healthy = make_post(other_gid, "Healthy business post: we are open this week, call to book.")
    owner_exec("UPDATE tenants SET suspended_at = now() WHERE id = :t", t=_tenant_of(gid))

    totals = publish_due_posts.run()

    assert row(healthy)["status"] == "published", f"the healthy business's post was starved: {totals}"
    assert fake.creates == 1  # exactly the healthy post reached Google; nothing of the suspended business did
    for pid in blocked:  # held, not lost, not failed, not published
        assert row(pid)["status"] == "scheduled" and row(pid)["attempts"] == 0

    # when the reason goes away the held posts are sent (they are only parked for a few minutes, never dropped)
    owner_exec("UPDATE tenants SET suspended_at = NULL WHERE id = :t", t=_tenant_of(gid))
    owner_exec("UPDATE scheduled_posts SET next_attempt_at = NULL WHERE status = 'scheduled'")
    again = publish_due_posts.run()
    assert again["published"] == 7 and all(row(pid)["status"] == "published" for pid in blocked)
    assert fake.creates == 8  # every post was created exactly once


def _make_media(gid_, name):
    tenant = _tenant_of(gid_)
    db = SessionLocal()
    set_rls_context(db, bypass=True)
    uid = owner_query("SELECT user_id FROM memberships WHERE tenant_id = :t LIMIT 1", t=tenant)[0][0]
    m = ScheduledMedia(tenant_id=tenant, google_location_id=uuid.UUID(gid_), category="ADDITIONAL", file_name=name, content_type="image/png", size_bytes=1, width=10, height=10,
                       sha256=uuid.uuid4().hex + uuid.uuid4().hex, data=b"x", status="scheduled", scheduled_for=utcnow() - timedelta(minutes=1), approved_by=uid, created_by=uid)
    db.add(m)
    db.commit()
    mid = m.id
    db.close()
    return mid


def test_photos_of_a_suspended_business_do_not_starve_another_business(connected, fake, gid):
    from app.workers.tasks import publish_due_media

    owner_exec("UPDATE scheduled_media SET status = 'canceled' WHERE status IN ('scheduled', 'publishing')")
    other = _second_business(fake)
    other_gid = other.glocs[0]["id"]
    blocked = [_make_media(gid, f"blocked-{i}.png") for i in range(7)]
    healthy = _make_media(other_gid, "healthy.png")
    owner_exec("UPDATE tenants SET suspended_at = now() WHERE id = :t", t=_tenant_of(gid))

    publish_due_media.run()

    status = {r[0]: r[1] for r in owner_query("SELECT id, status FROM scheduled_media WHERE id = ANY(:ids)", ids=blocked + [healthy])}
    assert status[healthy] != "scheduled", "the healthy business's photo was starved behind the suspended business's"
    assert all(status[m] == "scheduled" for m in blocked)  # held, not lost
