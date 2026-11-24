"""A live card that was never given a campaign opens the one-tap review page (stars, "what stood out", a review written from the picks) through its location's default review
page. Made once, reused by every such card at that location, and never put back after the owner pauses it. Google and the AI are not involved here."""
import pytest

from tests.conftest import make_business, owner_query

UA = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1"}


def assign(admin, biz, n=1):
    b = admin.post("/admin/batches", json={"name": "dflt", "quantity": n}).json()
    cards = admin.get("/admin/cards", params={"batch_id": b["id"]}).json()["items"]
    for c in cards:
        admin.post(f"/admin/cards/{c['id']}/assign", json={"tenant_id": biz.tenant_id, "location_id": biz.location_id})
    return cards


def landing(client, card):
    return client.get(f"/api/v1/public/c/{card['public_token']}", headers=UA).json()


def defaults(biz):
    return [c for c in biz.get("/review-growth/campaigns").json() if c["name"] == "Default review page"]


def test_a_plain_card_opens_the_one_tap_page_and_every_card_at_the_location_shares_it(admin, biz_a, client):
    c1, c2 = assign(admin, biz_a, 2)
    first = landing(client, c1)
    assert first["state"] == "ok" and first["campaign"] and first["campaign"]["id"]
    assert landing(client, c2)["campaign"]["id"] == first["campaign"]["id"]  # the second card reuses it
    assert landing(client, c1)["campaign"]["id"] == first["campaign"]["id"]  # and so does a rescan
    mine = defaults(biz_a)
    assert len(mine) == 1 and mine[0]["status"] == "active"  # the owner sees ONE default page, not one per scan
    page = client.get(f"/api/v1/public/reviews/{first['campaign']['id']}").json()
    assert page["state"] == "ok" and page["suggestions"] and page["review_url"] == "https://g.page/r/ABC123/review"  # stars and topics are there; the Google link is the location's


def test_an_owner_who_paused_it_is_never_overruled(admin, biz_a, client):
    (card,) = assign(admin, biz_a)
    cid = landing(client, card)["campaign"]["id"]
    row = defaults(biz_a)[0]
    assert biz_a.patch(f"/review-growth/campaigns/{row['id']}", json={"status": "paused"}).status_code == 200
    again = landing(client, card)
    assert again["state"] == "ok" and again["campaign"] is None  # the plain page, as before
    assert len(defaults(biz_a)) == 1  # and no second default was made
    assert owner_query("SELECT count(*) FROM review_campaigns WHERE tenant_id = :t", t=biz_a.tenant_id)[0][0] == 1
    assert cid


def test_a_card_with_its_own_campaign_keeps_it_and_no_default_is_made(admin, biz_a, client):
    (card,) = assign(admin, biz_a)
    mine = biz_a.post("/review-growth/campaigns", json={"name": "Spring", "location_id": biz_a.location_id}).json()
    r = biz_a.post(f"/cards/{card['id']}/assign", json={"location_id": biz_a.location_id, "campaign_id": mine["id"], "confirm": True})
    assert r.status_code == 200, r.text
    body = landing(client, card)
    assert body["campaign"] and body["campaign"]["id"] == mine["public_id"]  # their campaign, untouched
    assert not defaults(biz_a)


def test_each_business_gets_its_own_default_and_never_anothers(admin, biz_a, biz_b, client):
    (ca,) = assign(admin, biz_a)
    (cb,) = assign(admin, biz_b)
    ida, idb = landing(client, ca)["campaign"]["id"], landing(client, cb)["campaign"]["id"]
    assert ida != idb
    assert len(defaults(biz_a)) == 1 and len(defaults(biz_b)) == 1
    assert biz_a.get("/review-growth/campaigns").json() and all(c["id"] != defaults(biz_b)[0]["id"] for c in biz_a.get("/review-growth/campaigns").json())


@pytest.mark.parametrize("state", ["paused"])
def test_a_card_that_is_switched_off_still_shows_its_fallback_and_makes_nothing(admin, biz_a, client, state):
    (card,) = assign(admin, biz_a)
    assert admin.post(f"/admin/cards/{card['id']}/status", json={"status": state}).status_code == 200
    body = landing(client, card)
    assert body["state"] == "inactive"
    assert not defaults(biz_a)  # a dead card does not create a page
