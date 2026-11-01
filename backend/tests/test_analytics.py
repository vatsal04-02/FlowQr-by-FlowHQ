from tests.conftest import make_business
from tests.test_google_and_reviews import FakeGoogleProvider, greview, sync_select, connected, fake  # noqa: F401

UA = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1"}


def test_analytics_separates_funnel_stages_and_is_tenant_scoped(admin, connected, fake, biz_b, client):  # noqa: F811
    b = admin.post("/admin/batches", json={"name": "an", "quantity": 1}).json()
    card = admin.get("/admin/cards", params={"batch_id": b["id"]}).json()["items"][0]
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": connected.tenant_id, "location_id": connected.location_id})
    client.get(f"/api/v1/public/c/{card['public_token']}", headers=UA)
    for t in ["landing_view", "landing_view", "google_click"]:
        client.post(f"/api/v1/public/c/{card['public_token']}/event", json={"type": t}, headers=UA)
    fake.reviews = [greview(1, 5), greview(2, 3, "ok", reply="thanks")]
    sync_select(connected, fake)

    data = connected.get("/analytics/overview", params={"from": "2024-12-01", "to": "2025-01-31"}).json()
    assert data["reviews"]["total_synced"] == 2 and data["reviews"]["new_in_range"] == 2
    assert data["reviews"]["awaiting_reply"] == 1 and data["reviews"]["reply_rate_in_range"] == 0.5
    assert data["reviews"]["average_rating_all_time"] == 4.0

    today = connected.get("/analytics/overview").json()["engagement"]
    assert (today["scans"], today["landing_views"], today["google_clicks"]) == (1, 2, 1)
    assert "NOT mean a review was submitted" in today["definitions"]["google_clicks"]
    assert today["click_through_rate"] == 0.5
    assert connected.get("/analytics/overview").json()["cards"][0]["scans"] == 1

    # another tenant sees none of it
    other = biz_b.get("/analytics/overview").json()
    assert other["reviews"]["total_synced"] == 0 and other["engagement"]["scans"] == 0 and other["cards"] == []
    # cannot filter by a foreign location
    assert biz_b.get("/analytics/overview", params={"location_id": connected.location_id}).status_code == 404


def test_range_validation():
    biz = make_business("Range Co")
    assert biz.get("/analytics/overview", params={"from": "2025-02-01", "to": "2025-01-01"}).status_code == 422
    assert biz.get("/analytics/overview", params={"from": "2020-01-01", "to": "2025-01-01"}).status_code == 422
