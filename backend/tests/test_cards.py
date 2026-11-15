import io
import zipfile

import pytest

from tests.conftest import make_business, make_user


@pytest.fixture()
def batch(admin):
    r = admin.post("/admin/batches", json={"name": "Test batch", "quantity": 5})
    assert r.status_code == 201, r.text
    return r.json()


def cards_of(admin, batch_id):
    return admin.get("/admin/cards", params={"batch_id": batch_id}).json()["items"]


def test_batch_generates_unique_codes_and_unguessable_tokens(admin, batch):
    items = cards_of(admin, batch["id"])
    assert len(items) == 5
    codes = [c["card_code"] for c in items]
    assert len(set(codes)) == 5 and all(c.startswith("FQR-") for c in codes)
    tokens = [c["public_token"] for c in items]
    assert len(set(tokens)) == 5 and all(len(t) >= 24 for t in tokens)
    assert all(c["url"] == f"https://go.test.flowqr.example/q/{c['public_token']}" for c in items)
    assert all(c["status"] == "generated" for c in items)


def test_non_admin_cannot_use_admin_endpoints(biz_a, batch):
    assert biz_a.post("/admin/batches", json={"name": "x" * 3, "quantity": 1}).status_code == 403
    assert biz_a.get("/admin/cards").status_code == 403
    assert biz_a.get("/admin/stats").status_code == 403


def test_qr_png_and_svg_are_valid_images(admin, batch):
    card = cards_of(admin, batch["id"])[0]
    png = admin.get(f"/admin/cards/{card['id']}/qr.png")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    svg = admin.get(f"/admin/cards/{card['id']}/qr.svg")
    assert svg.status_code == 200 and b"<svg" in svg.content


def test_qr_decodes_to_card_url(admin, batch):
    """Round-trip: the generated QR must actually encode the card URL (using an independent decoder if available)."""
    pytest.importorskip("cv2"), pytest.importorskip("zxingcpp")
    from tests.test_qr import opencv, raster, zxing  # ZXing + OpenCV's ArUco detector (see tests/test_qr.py for why not the legacy one)
    card = cards_of(admin, batch["id"])[0]
    data = admin.get(f"/admin/cards/{card['id']}/qr.png").content
    assert zxing(raster(data, "png")) == [card["url"]] and opencv(raster(data, "png")) == card["url"]


def test_batch_zip_and_printable_sheet(admin, batch):
    z = admin.get(f"/admin/batches/{batch['id']}/export.zip")
    assert z.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert "manifest.csv" in names and sum(n.startswith("png/") for n in names) == 5
    sheet = admin.get(f"/admin/batches/{batch['id']}/sheet")
    assert sheet.status_code == 200 and sheet.text.count("<svg") == 5


def test_assignment_and_cross_tenant_assignment_blocked(admin, batch, biz_a, biz_b):
    card = cards_of(admin, batch["id"])[0]
    # location of B cannot be assigned under tenant A
    r = admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_b.location_id})
    assert r.status_code == 400
    r = admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    assert r.status_code == 200 and r.json()["status"] == "assigned"
    assert [c["id"] for c in biz_a.get("/cards").json()] == [card["id"]]
    assert biz_b.get("/cards").json() == []
    # B cannot touch / download A's card
    assert biz_b.patch(f"/cards/{card['id']}", json={"label": "mine now"}).status_code == 404
    assert biz_b.post(f"/cards/{card['id']}/deactivate").status_code == 404
    assert biz_b.get(f"/cards/{card['id']}/qr.png").status_code == 404
    # A cannot repoint its card to B's location
    assert biz_a.patch(f"/cards/{card['id']}", json={"location_id": biz_b.location_id}).status_code == 404


def test_public_resolve_records_scan_and_fallbacks(admin, batch, biz_a, client):
    from tests.conftest import Session
    cards = cards_of(admin, batch["id"])
    card = cards[0]
    ua = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"}
    # unassigned
    r = client.get(f"/api/v1/public/c/{card['public_token']}", headers=ua)
    assert r.status_code == 200 and r.json()["state"] == "unassigned"
    # unknown token
    assert client.get("/api/v1/public/c/" + "x" * 30).status_code == 404

    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    r = client.get(f"/api/v1/public/c/{card['public_token']}", headers=ua)
    body = r.json()
    assert body["state"] == "ok" and body["business"]["name"] == "Alpha Physio"
    assert body["review_url"] == "https://g.page/r/ABC123/review"
    # no internal IDs leak into public payload
    assert biz_a.tenant_id not in r.text and biz_a.location_id not in r.text and card["id"] not in r.text
    # first genuine scan activates the card
    assert admin.get(f"/admin/cards/{card['id']}").json()["card"]["status"] == "active"
    stats = biz_a.get("/cards").json()[0]["stats"]
    assert stats["scan"] == 1


def test_bot_scans_are_not_counted(admin, batch, biz_a, client):
    card = cards_of(admin, batch["id"])[1]
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    client.get(f"/api/v1/public/c/{card['public_token']}", headers={"user-agent": "facebookexternalhit/1.1"})
    client.get(f"/api/v1/public/c/{card['public_token']}", headers={"user-agent": "python-requests/2.31"})
    assert biz_a.get("/cards").json()[0]["stats"].get("scan", 0) == 0
    # and a bot does not flip the card to active
    assert admin.get(f"/admin/cards/{card['id']}").json()["card"]["status"] == "assigned"


def test_last_scan_at_reflects_only_human_scans(admin, batch, biz_a, client):
    card = cards_of(admin, batch["id"])[3]
    ua = {"user-agent": "Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile Safari/537.36"}
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    assert biz_a.get("/cards").json()[0]["last_scan_at"] is None  # never scanned
    client.get(f"/api/v1/public/c/{card['public_token']}", headers={"user-agent": "python-requests/2.31"})
    assert biz_a.get("/cards").json()[0]["last_scan_at"] is None  # a bot is not a scan
    client.get(f"/api/v1/public/c/{card['public_token']}", headers=ua)
    assert biz_a.get("/cards").json()[0]["last_scan_at"] is not None
    listed = admin.get("/admin/cards", params={"search": card["card_code"]}).json()["items"][0]
    assert listed["last_scan_at"] is not None  # platform admin sees the same value


def test_deactivated_card_shows_fallback_but_keeps_history(admin, batch, biz_a, client):
    card = cards_of(admin, batch["id"])[2]
    ua = {"user-agent": "Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile Safari/537.36"}
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    client.get(f"/api/v1/public/c/{card['public_token']}", headers=ua)
    assert biz_a.post(f"/cards/{card['id']}/deactivate").status_code == 200
    r = client.get(f"/api/v1/public/c/{card['public_token']}", headers=ua)
    assert r.json()["state"] == "inactive"
    assert biz_a.get("/cards").json()[0]["stats"]["scan"] == 1


def test_reassignment_preserves_scan_history_and_review_link_can_change(admin, batch, biz_a, biz_b, client):
    card = cards_of(admin, batch["id"])[3]
    ua = {"user-agent": "Mozilla/5.0 (iPhone) Safari/604.1"}
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    client.get(f"/api/v1/public/c/{card['public_token']}", headers=ua)
    # business changes its Google review URL: same card URL keeps working
    biz_a.patch(f"/locations/{biz_a.location_id}", json={"review_url": "https://g.page/r/NEWLINK/review"})
    body = client.get(f"/api/v1/public/c/{card['public_token']}", headers={"user-agent": "Mozilla/5.0 Other Safari/604.1"}).json()
    assert body["review_url"] == "https://g.page/r/NEWLINK/review"
    # platform reassigns to B
    assert admin.post(f"/admin/cards/{card['id']}/unassign").status_code == 409  # a card in use needs an explicit confirmation
    assert admin.post(f"/admin/cards/{card['id']}/unassign", json={"confirm": True}).status_code == 200
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_b.tenant_id, "location_id": biz_b.location_id})
    detail = admin.get(f"/admin/cards/{card['id']}").json()
    assert len(detail["history"]) == 2
    # A still sees its historical scans in analytics-related ScanEvents (tenant snapshot), B starts at zero.
    from app.core.db import SessionLocal, set_rls_context
    from app.models import ScanEvent
    from sqlalchemy import select, func
    db = SessionLocal(); set_rls_context(db, bypass=True)
    a_scans = db.scalar(select(func.count()).select_from(ScanEvent).where(ScanEvent.tenant_id == biz_a.tenant_id))
    b_scans = db.scalar(select(func.count()).select_from(ScanEvent).where(ScanEvent.tenant_id == biz_b.tenant_id))
    db.close()
    assert a_scans == 2 and b_scans == 0


def test_public_scan_rate_limited(admin, batch, client):
    card = cards_of(admin, batch["id"])[4]
    codes = [client.get(f"/api/v1/public/c/{card['public_token']}", headers={"user-agent": "Mozilla/5.0 Safari"}).status_code
             for _ in range(70)]
    assert 429 in codes


def test_batch_records_base_url_and_audit_detects_mismatch(admin, monkeypatch, capsys):
    from app.core.config import settings
    from app import cli
    b = admin.post("/admin/batches", json={"name": "audit batch", "quantity": 1}).json()
    assert b["base_url"] == "https://go.test.flowqr.example"
    monkeypatch.setattr(settings, "public_card_base_url", "https://go.other-domain.in")
    assert cli.card_url_audit(live=False, expect_domain=None) == 1  # a batch printed with another domain => FAIL
    out = capsys.readouterr().out
    assert "existing batches were generated with the current base URL" in out and "AUDIT FAILED" in out
