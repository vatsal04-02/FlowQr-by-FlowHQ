"""Location-level permissions: a staff member limited to some locations must not reach any other location's data through
ANY endpoint, including by calling the API directly with ids they should not know."""
import uuid

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal, set_rls_context
from app.core.deps import member_may_act
from app.models import Membership, QRCard, Review, Role, User
from app.models.base import utcnow
from app.services import google as g
from tests.conftest import latest_token, make_user, owner_query
from tests.test_gbp import FakeGbpProvider
from app.services.google.provider import GReviewPage
from tests.test_google_and_reviews import callback, connect, greview

UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36"}


def invite(biz, role="staff", location_ids=None):
    """Invite through the real API and accept through the real API; returns the new member's session."""
    user = make_user()
    body = {"email": user.email, "role": role}
    if location_ids is not None:
        body["location_ids"] = location_ids
    r = biz.post("/staff/invitations", json=body)
    assert r.status_code == 201, r.text
    assert user.post("/invitations/accept", json={"token": latest_token(user.email, "accept-invite")}).status_code == 200
    user.user_id = next(m["user_id"] for m in biz.get("/staff").json()["members"] if m["email"] == user.email)
    return user


@pytest.fixture()
def world(monkeypatch, admin):
    """One business, two locations (A, B), each with a Google location, a synced review, a card with a scan and a campaign.
    `staff` is limited to A. Google is a TEST DOUBLE."""
    from tests.conftest import make_business
    fake = FakeGbpProvider()
    monkeypatch.setattr(g, "get_google_provider", lambda: fake)
    biz = make_business("Scope Clinic")
    biz.loc_a = biz.location_id
    biz.loc_b = biz.post("/locations", json={"name": "Scope Clinic - Aliganj", "city": "Lucknow", "review_url": "https://g.page/r/XYZ/review"}).json()["id"]

    assert callback(biz, connect(biz, fake)).status_code == 303
    conn = biz.get("/google/status").json()["connections"][0]["id"]
    glocs = biz.get(f"/google/connections/{conn}/locations").json()
    by_loc = {glocs[0]["google_location_name"]: [greview(1, 5, "Lovely place")], glocs[1]["google_location_name"]: [greview(2, 1, "Long wait")]}
    fake.list_reviews = lambda at, acct, loc, page_token=None: GReviewPage(reviews=list(by_loc.get(loc, [])))  # one review per branch
    sel = [{"google_location_id": glocs[0]["id"], "selected": True, "location_id": biz.loc_a},
           {"google_location_id": glocs[1]["id"], "selected": True, "location_id": biz.loc_b}]
    assert biz.put(f"/google/connections/{conn}/selection", json={"selections": sel}).status_code == 200
    biz.conn, biz.gloc_a, biz.gloc_b = conn, glocs[0]["id"], glocs[1]["id"]
    reviews = biz.get("/reviews", params={"limit": 100}).json()["items"]
    biz.rev_a = next(r["id"] for r in reviews if r["location_id"] == biz.loc_a)
    biz.rev_b = next(r["id"] for r in reviews if r["location_id"] == biz.loc_b)
    biz.draft_b = biz.post(f"/reviews/{biz.rev_b}/drafts", json={"body": "Sorry about the wait."}).json()["id"]

    batch = admin.post("/admin/batches", json={"name": "Scope batch", "quantity": 2}).json()
    cards = admin.get("/admin/cards", params={"batch_id": batch["id"]}).json()["items"]
    for card, loc in zip(cards, (biz.loc_a, biz.loc_b)):
        assert admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz.tenant_id, "location_id": loc}).status_code == 200
        assert biz.http.get(f"/api/v1/public/c/{card['public_token']}", headers=UA).json()["state"] == "ok"
    biz.card_a, biz.card_b = cards[0], cards[1]

    biz.camp_a = biz.post("/review-growth/campaigns", json={"name": "Front desk A", "location_id": biz.loc_a}).json()
    biz.camp_b = biz.post("/review-growth/campaigns", json={"name": "Front desk B", "location_id": biz.loc_b}).json()
    for c in (biz.camp_a, biz.camp_b):
        assert biz.http.get(f"/api/v1/public/reviews/{c['public_id']}", headers=UA).status_code == 200

    biz.staff = invite(biz, location_ids=[biz.loc_a])
    biz.fake = fake
    return biz


def test_restricted_staff_lists_only_their_location_everywhere(world):
    s, w = world.staff, world
    assert [l["id"] for l in s.get("/locations").json()] == [w.loc_a]
    assert [r["id"] for r in s.get("/reviews").json()["items"]] == [w.rev_a] and s.get("/reviews").json()["total"] == 1
    assert [c["id"] for c in s.get("/cards").json()] == [w.card_a["id"]]
    assert [c["id"] for c in s.get("/review-growth/campaigns").json() if c["name"] != "Default review page"] == [w.camp_a["id"]]  # (a scanned plain card also makes its location's default page: see tests/test_default_review_page.py)
    assert [x["id"] for x in s.get(f"/google/connections/{w.conn}/locations").json()] == [w.gloc_a]
    # the owner still sees both
    assert len(w.get("/locations").json()) == 2 and w.get("/reviews").json()["total"] == 2 and len(w.get("/cards").json()) == 2


@pytest.mark.parametrize("method, path, body", [
    ("GET", "/locations/{loc_b}", None),
    ("GET", "/reviews/{rev_b}", None),
    ("GET", "/reviews?location_id={loc_b}", "EMPTY"),
    ("POST", "/reviews/{rev_b}/drafts", {"body": "Trying to reply for another branch"}),
    ("POST", "/reviews/{rev_b}/drafts/generate", None),
    ("PATCH", "/reply-drafts/{draft_b}", {"body": "Editing another branch's draft"}),
    ("DELETE", "/reply-drafts/{draft_b}", None),
    ("GET", "/gbp/{gloc_b}/info", None),
    ("GET", "/gbp/{gloc_b}/posts", None),
    ("GET", "/gbp/{gloc_b}/media", None),
    ("GET", "/gbp/{gloc_b}/performance", None),
    ("GET", "/gbp/{gloc_b}/categories?q=dent", None),
    ("GET", "/review-growth/campaigns/{camp_b_id}", None),
    ("GET", "/review-growth/analytics?campaign_id={camp_b_id}", None),
    ("GET", "/analytics/overview?location_id={loc_b}", None),
    ("GET", "/analytics/insights?location_id={loc_b}", None),
])
def test_direct_requests_for_another_location_are_refused(world, method, path, body):
    w = world
    url = path.format(loc_b=w.loc_b, rev_b=w.rev_b, draft_b=w.draft_b, gloc_b=w.gloc_b, camp_b_id=w.camp_b["id"])
    r = w.staff.request(method, url, **({"json": body} if isinstance(body, dict) else {}))
    if body == "EMPTY":  # a filter for a location they can't see matches nothing; it must not leak rows
        assert r.status_code == 200 and r.json() == {"total": 0, "items": []}
    else:
        assert r.status_code == 404, f"{method} {url} -> {r.status_code} {r.text[:200]}"
    # ...and the same call against their own location is allowed, so the 404 above is the permission, not a broken route
    own = path.format(loc_b=w.loc_a, rev_b=w.rev_a, draft_b=w.draft_b, gloc_b=w.gloc_a, camp_b_id=w.camp_a["id"])
    if "draft" not in path:
        ok = w.staff.request(method, own, **({"json": body} if isinstance(body, dict) else {}))
        assert ok.status_code in (200, 201, 402, 403, 503), f"{method} {own} -> {ok.status_code} {ok.text[:200]}"  # 402/403/503: plan, AI not configured


def test_analytics_totals_exclude_other_locations(world):
    w = world
    mine, everything = w.staff.get("/analytics/overview").json(), w.get("/analytics/overview").json()
    assert everything["reviews"]["total_synced"] == 2 and mine["reviews"]["total_synced"] == 1
    assert mine["reviews"]["rating_distribution"]["5"] + mine["reviews"]["rating_distribution"]["1"] == 1
    assert everything["engagement"]["scans"] == 2 and mine["engagement"]["scans"] == 1
    assert [c["card_code"] for c in mine["cards"]] == [w.card_a["card_code"]] and len(mine["locations"]) == 1 and len(mine["sync"]) == 1
    assert mine["reviews"]["drafts_pending_approval"] == 0 and everything["reviews"]["drafts_pending_approval"] == 1  # the draft is at B
    rg_mine, rg_all = w.staff.get("/review-growth/analytics").json(), w.get("/review-growth/analytics").json()
    assert rg_all["totals"]["scans"] == 2 and rg_mine["totals"]["scans"] == 1 and [c["id"] for c in rg_mine["campaigns"] if c["name"] != "Default review page"] == [w.camp_a["id"]]


def test_data_without_a_location_is_hidden_from_restricted_staff(world):
    w = world
    db = SessionLocal(); set_rls_context(db, bypass=True)
    db.get(Review, uuid.UUID(w.rev_a)).location_id = None  # e.g. the Google location was unmapped
    db.commit(); db.close()
    assert w.staff.get("/reviews").json()["total"] == 0 and w.staff.get(f"/reviews/{w.rev_a}").status_code == 404
    assert w.get("/reviews").json()["total"] == 2  # unrestricted members still see it


def test_scope_is_managed_by_admins_validated_and_audited(world, biz_b):
    w, s = world, world.staff
    members = {m["email"]: m for m in w.get("/staff").json()["members"]}
    assert members[s.email]["all_locations"] is False and members[s.email]["location_ids"] == [w.loc_a]
    assert members[w.email]["all_locations"] is True and members[w.email]["location_ids"] == []
    url = f"/staff/{s.user_id}/locations"
    assert s.put(url, json={"all_locations": True}).status_code == 403  # staff cannot widen their own access
    assert w.put(url, json={"all_locations": False, "location_ids": [biz_b.location_id]}).status_code == 404  # another tenant's location
    assert w.put(url, json={"all_locations": False, "location_ids": [str(uuid.uuid4())]}).status_code == 404
    assert [l["id"] for l in s.get("/locations").json()] == [w.loc_a]  # failed changes changed nothing
    assert w.put(url, json={"all_locations": False, "location_ids": [w.loc_b]}).status_code == 204
    assert [l["id"] for l in s.get("/locations").json()] == [w.loc_b] and s.get(f"/reviews/{w.rev_a}").status_code == 404  # takes effect at once
    assert w.put(url, json={"all_locations": False, "location_ids": []}).status_code == 204
    assert s.get("/locations").json() == [] and s.get("/reviews").json()["total"] == 0 and s.get("/analytics/overview").json()["reviews"]["total_synced"] == 0
    assert w.put(url, json={"all_locations": True}).status_code == 204
    assert len(s.get("/locations").json()) == 2
    actions = [a for (a,) in owner_query("SELECT action FROM audit_logs WHERE tenant_id = :t AND action = 'staff.locations_change'", t=w.tenant_id)]
    assert len(actions) == 3
    owner_id = next(m["user_id"] for m in w.get("/staff").json()["members"] if m["email"] == w.email)
    assert w.put(f"/staff/{owner_id}/locations", json={"all_locations": False, "location_ids": [w.loc_a]}).status_code == 400  # owners can't be limited


def test_admins_are_never_restricted_and_promotion_clears_the_restriction(world):
    w, s = world, world.staff
    assert w.post("/staff/invitations", json={"email": "x@example.com", "role": "admin", "location_ids": [w.loc_a]}).status_code == 422
    assert w.patch(f"/staff/{s.user_id}", json={"role": "admin"}).status_code == 204
    assert len(s.get("/locations").json()) == 2 and s.get(f"/reviews/{w.rev_b}").status_code == 200
    assert w.patch(f"/staff/{s.user_id}", json={"role": "staff"}).status_code == 204
    m = next(m for m in w.get("/staff").json()["members"] if m["email"] == s.email)
    assert m["all_locations"] is True and len(s.get("/locations").json()) == 2  # the old restriction did not silently come back


def test_existing_and_unrestricted_staff_keep_full_access(world):
    plain = invite(world)  # no location_ids: behaves exactly as before this feature
    assert len(plain.get("/locations").json()) == 2 and plain.get("/reviews").json()["total"] == 2
    assert plain.get(f"/gbp/{world.gloc_b}/posts").status_code == 200


def test_restricted_staff_cannot_use_another_tenants_ids_or_writes(world, biz_b):
    s = world.staff
    assert s.get(f"/locations/{biz_b.location_id}").status_code == 404
    assert s.patch(f"/locations/{world.loc_a}", json={"name": "Renamed"}).status_code == 403  # writes stay admin-only
    assert s.post(f"/gbp/{world.gloc_a}/posts", json={"summary": "Staff trying to post"}).status_code == 403
    assert s.post("/google/sync").status_code == 403


def test_background_retry_honours_the_approver_losing_access(world):
    """The reply auto-retry job publishes on the strength of an earlier approval. If that approver has since been demoted,
    restricted away from the location or removed, the job must not publish for them."""
    w = world
    second = invite(w, role="admin")
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        tid, loc_a, loc_b = uuid.UUID(w.tenant_id), uuid.UUID(w.loc_a), uuid.UUID(w.loc_b)
        admin_id = uuid.UUID(second.user_id)
        assert member_may_act(db, tid, admin_id, loc_b, Role.admin)
        assert not member_may_act(db, tid, uuid.UUID(w.staff.user_id), loc_a, Role.admin)  # staff never could
        assert not member_may_act(db, tid, None, loc_b, Role.admin) and not member_may_act(db, uuid.uuid4(), admin_id, loc_b, Role.admin)
    finally:
        db.close()
    assert w.patch(f"/staff/{second.user_id}", json={"role": "staff"}).status_code == 204
    assert w.put(f"/staff/{second.user_id}/locations", json={"all_locations": False, "location_ids": [w.loc_a]}).status_code == 204
    db = SessionLocal(); set_rls_context(db, bypass=True)
    try:
        assert not member_may_act(db, tid, admin_id, loc_b, Role.admin)
        assert member_may_act(db, tid, admin_id, loc_a, Role.staff) and not member_may_act(db, tid, admin_id, loc_b, Role.staff)
    finally:
        db.close()

    # end to end: a draft approved by an admin who is then demoted is NOT auto-published by the retry job
    from app.models import ReplyDraft, ReplyLog, ReplyStatus
    from app.workers.tasks import retry_failed_replies
    did = w.post(f"/reviews/{w.rev_a}/drafts", json={"body": "Thank you so much!"}).json()["id"]
    db = SessionLocal(); set_rls_context(db, bypass=True)
    d = db.get(ReplyDraft, uuid.UUID(did))
    d.status, d.approved_by, d.approved_at, d.attempts = ReplyStatus.failed, admin_id, utcnow(), 1
    db.add(ReplyLog(tenant_id=tid, review_id=d.review_id, draft_id=d.id, user_id=admin_id, action="publish_attempt", success=False, http_status=503, error="x", created_at=utcnow()))
    db.commit(); db.close()
    assert retry_failed_replies.run() == {"retried": 0} and w.fake.replies == []
    assert w.patch(f"/staff/{second.user_id}", json={"role": "admin"}).status_code == 204
    assert retry_failed_replies.run() == {"retried": 1} and len(w.fake.replies) == 1


def test_membership_locations_table_is_tenant_isolated_at_the_database(world, biz_b):
    from sqlalchemy import create_engine, text
    from app.core.config import settings
    eng = create_engine(settings.database_url)  # the non-superuser app role: RLS applies
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": biz_b.tenant_id})
        assert c.execute(text("SELECT count(*) FROM membership_locations")).scalar() == 0
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": world.tenant_id})
        assert c.execute(text("SELECT count(*) FROM membership_locations")).scalar() == 1
