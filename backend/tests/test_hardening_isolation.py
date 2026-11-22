"""Production-readiness hardening: a cross-tenant attack sweep over the id-based routes (audit Journey 9).

Business B (the victim) owns a location, a Google connection and profile, reviews, a reply draft, a campaign, a scheduled post and a staff member. Business A (the attacker, a fully valid administrator
of ITS OWN business) calls every route that takes one of those ids, with B's real ids, using every HTTP method the route supports. Every call must be refused (never 2xx), must not echo anything of
B's, and B's data must be byte-for-byte what it was. Mock Google only."""
import json
import uuid

import pytest

from tests.conftest import make_business, owner_query
from tests.test_google_and_reviews import connected, fake, greview, sync_select  # noqa: F401
from tests.test_phase0_post_publishing import _no_leftover_posts, make_post  # noqa: F401

REFUSED = {400, 403, 404, 405, 409, 422}


def snapshot(tenant_id: str, extra: dict) -> str:
    t = tenant_id
    rows = {
        "tenant": owner_query("SELECT name, category, is_active, suspended_at FROM tenants WHERE id = :t", t=t),
        "locations": owner_query("SELECT id, name, is_active, review_url FROM locations WHERE tenant_id = :t ORDER BY id", t=t),
        "connections": owner_query("SELECT id, status::text, auth_mode, refresh_token_encrypted IS NOT NULL FROM google_connections WHERE tenant_id = :t ORDER BY id", t=t),
        "glocs": owner_query("SELECT id, selected, last_sync_status FROM google_locations WHERE tenant_id = :t ORDER BY id", t=t),
        "reviews": owner_query("SELECT id, rating, text FROM reviews WHERE tenant_id = :t ORDER BY id", t=t),
        "drafts": owner_query("SELECT id, status::text, body FROM reply_drafts WHERE tenant_id = :t ORDER BY id", t=t),
        "campaigns": owner_query("SELECT id, name, status FROM review_campaigns WHERE tenant_id = :t ORDER BY id", t=t),
        "posts": owner_query("SELECT id, status, summary FROM scheduled_posts WHERE tenant_id = :t ORDER BY id", t=t),
        "members": owner_query("SELECT user_id, role::text FROM memberships WHERE tenant_id = :t ORDER BY user_id", t=t),
        "grants": owner_query("SELECT count(*) FROM google_agency_tenant_grants WHERE tenant_id = :t", t=t),
        "audit_writes_by_victim_data": extra,
    }
    return json.dumps(rows, default=str, sort_keys=True)


@pytest.fixture()
def victim(connected, fake):  # noqa: F811
    fake.reviews = [greview(1), greview(2, rating=2, text="Victim private review text")]
    sync_select(connected, fake)
    v = connected
    reviews = v.get("/reviews").json()["items"]
    v.review_id = reviews[0]["id"]
    v.gloc_id = v.glocs[0]["id"]
    draft = v.post(f"/reviews/{v.review_id}/drafts", json={"body": "Victim's own reply draft, not for anyone else."})
    assert draft.status_code == 201, draft.text
    v.draft_id = draft.json()["id"]
    camp = v.post("/review-growth/campaigns", json={"name": "Victim Campaign", "location_id": v.location_id})
    assert camp.status_code == 201, camp.text
    v.campaign_id = camp.json()["id"]
    v.campaign_code = camp.json().get("public_id") or camp.json().get("code") or "x"
    v.post_id = str(make_post(v.gloc_id, "Victim scheduled post text, do not touch."))
    v.staff_user_id = str(owner_query("SELECT user_id FROM memberships WHERE tenant_id = :t LIMIT 1", t=v.tenant_id)[0][0])
    return v


def routes(v):
    """(method, path, body) for every id-based route, with the VICTIM's ids."""
    L, C, G, R, D, P, K, S = v.location_id, v.campaign_id, v.gloc_id, v.review_id, v.draft_id, v.post_id, v.conn_id, v.staff_user_id
    return [
        ("GET", f"/locations/{L}", None), ("PATCH", f"/locations/{L}", {"name": "pwned"}), ("DELETE", f"/locations/{L}", None),
        ("POST", f"/review-growth/locations/{L}/review-url", {"url": "https://g.page/r/PWNED/review"}),
        ("GET", f"/reviews/{R}", None), ("POST", f"/reviews/{R}/drafts", {"body": "pwned reply text"}), ("POST", f"/reviews/{R}/drafts/generate", {}),
        ("PATCH", f"/reply-drafts/{D}", {"body": "pwned reply text"}), ("DELETE", f"/reply-drafts/{D}", None), ("POST", f"/reply-drafts/{D}/approve", {"acknowledge_flags": True}),
        ("POST", f"/reply-drafts/{D}/publish", None),
        ("GET", f"/review-growth/campaigns/{C}", None), ("PATCH", f"/review-growth/campaigns/{C}", {"name": "pwned"}), ("DELETE", f"/review-growth/campaigns/{C}", None),
        ("GET", f"/review-growth/campaigns/{C}/qr.png", None), ("GET", f"/review-growth/campaigns/{C}/qr.svg", None), ("GET", f"/review-growth/campaigns/{C}/poster.pdf", None),
        ("POST", f"/review-growth/campaigns/{C}/regenerate-qr", {}),
        ("GET", f"/google/connections/{K}/locations", None), ("POST", f"/google/connections/{K}/refresh-locations", {}), ("DELETE", f"/google/connections/{K}", None),
        ("PUT", f"/google/connections/{K}/selection", {"selections": [{"google_location_id": G, "selected": False}]}),
        ("GET", f"/google/agency/connections/{K}/status", None), ("POST", f"/google/agency/connections/{K}/advance", {}), ("POST", f"/google/agency/connections/{K}/stop", {"confirm": True}),
        ("GET", f"/gbp/{G}/info", None), ("PATCH", f"/gbp/{G}/info", {"description": "pwned"}), ("GET", f"/gbp/{G}/posts", None), ("POST", f"/gbp/{G}/posts", {"summary": "pwned post text here"}),
        ("GET", f"/gbp/{G}/media", None), ("GET", f"/gbp/{G}/library", None), ("GET", f"/gbp/{G}/performance", None), ("GET", f"/gbp/{G}/rank", None), ("GET", f"/gbp/{G}/keywords", None),
        ("PATCH", f"/posts/{P}", {"summary": "pwned post text here"}), ("POST", f"/posts/{P}/approve", {}), ("POST", f"/posts/{P}/cancel", {}), ("POST", f"/posts/{P}/reject", {}),
        ("POST", f"/posts/{P}/retry", {}), ("POST", f"/posts/{P}/submit", {}),
        ("PATCH", f"/staff/{S}", {"role": "staff"}), ("DELETE", f"/staff/{S}", None), ("PUT", f"/staff/{S}/locations", {"location_ids": []}),
        ("POST", f"/agency-ops/tenants/{v.tenant_id}/grant", {}), ("POST", f"/agency-ops/tenants/{v.tenant_id}/revoke", {}),
    ]


def test_another_business_cannot_read_or_change_anything_through_any_id_route(victim):
    attacker = make_business("Attacker Co")
    before = snapshot(victim.tenant_id, {})
    leaks, accepted = [], []
    for method, path, body in routes(victim):
        r = attacker.request(method, path, **({"json": body} if body is not None else {}))
        if r.status_code not in REFUSED:
            accepted.append((method, path, r.status_code))
        text = r.text if "json" in r.headers.get("content-type", "") else ""
        for secret in ("Victim private review text", "Victim's own reply draft", "Victim Campaign", "Victim scheduled post", "REFRESH-SECRET-TOKEN", "owner@clinic.example.com", "Gomti"):
            if secret in text:
                leaks.append((method, path, secret))
    assert not accepted, f"a foreign business got a success answer: {accepted}"
    assert not leaks, f"a foreign business was shown the victim's data: {leaks}"
    assert snapshot(victim.tenant_id, {}) == before, "the victim's data changed"


def test_the_victims_own_session_still_reads_everything_the_attacker_was_refused(victim):
    """Guards the test above against passing for the wrong reason (the routes or ids being wrong): the same ids work for their owner."""
    for method, path in (("GET", f"/locations/{victim.location_id}"), ("GET", f"/reviews/{victim.review_id}"), ("GET", f"/review-growth/campaigns/{victim.campaign_id}"),
                         ("GET", f"/google/connections/{victim.conn_id}/locations"), ("GET", f"/gbp/{victim.gloc_id}/library"), ("GET", f"/review-growth/campaigns/{victim.campaign_id}/qr.png")):
        r = victim.request(method, path)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])


def test_a_tenant_selector_header_cannot_move_the_attacker_into_the_victims_business(victim):
    attacker = make_business("Selector Attacker")
    for path in ("/tenant", "/reviews", "/locations", "/google/status", "/review-growth/campaigns", "/analytics/overview", "/staff"):
        r = attacker.get(path, headers={"X-Tenant-Id": victim.tenant_id})
        assert r.status_code == 403, (path, r.status_code)
        assert "Victim" not in r.text and "Gomti" not in r.text
    assert attacker.post(f"/auth/select-tenant?tenant_id={victim.tenant_id}").status_code == 403
    assert attacker.get("/reviews", headers={"X-Tenant-Id": "not-a-uuid"}).status_code == 400
    assert attacker.get("/reviews", headers={"X-Tenant-Id": str(uuid.uuid4())}).status_code == 403
