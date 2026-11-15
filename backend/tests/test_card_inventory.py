"""Pre-printed card inventory: bulk production, QR + NFC identity, lifecycle, scan-to-assign, destinations, analytics, security.

Everything here runs against the real API and a real database. Google and AI are not involved. NFC is the PUBLIC ROUTE /n/<id> and the
channel it records: no tag is written here (real tag writing and phone reading must be tested on hardware, see docs/CARD_INVENTORY.md)."""
import csv
import io
import re
import zipfile

import pytest

from app.core.config import settings
from app.core import rate_limit
from app.services.qr import card_nfc_url, card_qr_url, permanent_url_problem
from tests.conftest import make_business, owner_query
from tests.test_location_permissions import invite
from tests.test_qr import UA, UA2, campaign

BASE = "https://go.test.flowqr.example"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{24}$")


def all_cards(admin, batch_id):
    out, offset = [], 0
    while True:
        page = admin.get("/admin/cards", params={"batch_id": batch_id, "limit": 200, "offset": offset}).json()
        out += page["items"]
        offset += 200
        if offset >= page["total"]:
            return out


def new_batch(admin, quantity=6, release=True, name="Inventory batch"):
    b = admin.post("/admin/batches", json={"name": name, "quantity": quantity})
    assert b.status_code == 201, b.text
    b = b.json()
    if release:
        assert admin.post(f"/admin/batches/{b['id']}/release").status_code == 200
    return b, all_cards(admin, b["id"])


def scan(client, card, channel, ua=UA):
    r = client.get(f"/api/v1/public/c/{card['public_token']}", params={"channel": channel} if channel else {}, headers=ua)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ 1. bulk production, permanent identity
def test_batch_of_500_has_unique_random_ids_serials_and_both_addresses(admin):
    b = admin.post("/admin/batches", json={"name": "Five hundred", "quantity": 500}).json()
    cards = all_cards(admin, b["id"])
    assert len(cards) == 500
    ids = [c["id"] for c in cards]
    tokens = [c["public_token"] for c in cards]
    serials = [c["card_code"] for c in cards]
    assert len(set(ids)) == len(set(tokens)) == len(set(serials)) == 500
    assert all(TOKEN_RE.match(t) for t in tokens)  # 144 bits, URL-safe: cryptographically random, not derived from the serial
    assert tokens != sorted(tokens) and not any(c["card_code"].split("-")[1] in c["public_token"] for c in cards)  # non-sequential, not guessable from the serial
    assert all(c["url"] == f"{BASE}/q/{c['public_token']}" and c["nfc_url"] == f"{BASE}/n/{c['public_token']}" for c in cards)
    assert all(c["status"] == "generated" for c in cards)
    # both addresses end in the same permanent identity; the NFC URL is short enough for the smallest common tags (NTAG213: ~137 bytes)
    assert all(len(c["nfc_url"].encode()) < 100 for c in cards)
    other = admin.post("/admin/batches", json={"name": "Another", "quantity": 50}).json()
    assert not set(tokens) & {c["public_token"] for c in all_cards(admin, other["id"])}  # nothing repeats across batches
    assert len(all_cards(admin, other["id"])) == 50  # the other offered sizes (100, 250) use the same code path


def test_inventory_counts_follow_the_lifecycle_and_stock_is_invisible_to_businesses(admin, biz_a, biz_b):
    b, cards = new_batch(admin, 6, release=False)
    inv = admin.get("/admin/inventory").json()
    row = next(x for x in inv["batches"] if x["id"] == b["id"])
    assert row["counts"]["generated"] == 6 and row["released_at"] is None
    assert admin.post(f"/admin/batches/{b['id']}/release").json()["released"] == 6
    row = next(x for x in admin.get("/admin/inventory").json()["batches"] if x["id"] == b["id"])
    assert row["counts"]["unassigned"] == 6 and row["counts"]["generated"] == 0 and row["released_at"]
    assert admin.get("/admin/inventory").json()["available"] >= 6

    # reserve for A: A sees exactly that card, with no location yet; B and the rest of the stock stay invisible
    r = admin.post(f"/admin/cards/{cards[0]['id']}/reserve", json={"tenant_id": biz_a.tenant_id})
    assert r.status_code == 200 and r.json()["status"] == "reserved" and r.json()["location_id"] is None
    mine = biz_a.get("/cards").json()
    assert [c["id"] for c in mine] == [cards[0]["id"]] and mine[0]["location_id"] is None
    assert biz_b.get("/cards").json() == []
    assert admin.post(f"/admin/cards/{cards[0]['id']}/reserve", json={"tenant_id": biz_b.tenant_id}).status_code == 409  # only stock can be reserved

    # archive is only for stock, and reversible
    assert admin.post(f"/admin/cards/{cards[0]['id']}/archive").status_code == 409
    assert admin.post(f"/admin/cards/{cards[1]['id']}/archive").json()["status"] == "archived"
    assert admin.post(f"/admin/cards/{cards[1]['id']}/unarchive").json()["status"] == "unassigned"
    assert admin.get("/admin/cards", params={"batch_id": b["id"], "in_stock": True}).json()["total"] == 5
    # reservations are history too
    assert len(admin.get(f"/admin/cards/{cards[0]['id']}").json()["history"]) == 1


def test_old_cards_keep_their_c_address_and_every_door_resolves_the_same_card(admin, biz_a, client):
    b, cards = new_batch(admin, 2)
    old = cards[0]
    from tests.conftest import owner_exec
    owner_exec("UPDATE qr_cards SET qr_path = 'c' WHERE id = :i", i=old["id"])
    again = admin.get(f"/admin/cards/{old['id']}").json()["card"]
    assert again["url"] == f"{BASE}/c/{old['public_token']}"  # what is on the paper for a card printed before batches existed
    assert again["nfc_url"] == f"{BASE}/n/{old['public_token']}"
    assert admin.post(f"/admin/cards/{old['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "activate": True}).status_code == 200
    for channel, ua in (("qr", UA), ("nfc", UA2), (None, {"User-Agent": "Mozilla/5.0 (X11; Linux) Firefox/125 Mobile"})):
        body = scan(client, old, channel, ua)
        assert body["state"] == "ok" and body["card_code"] == old["card_code"]


# ------------------------------------------------------------------ 2. before assignment: nothing leaks
def test_scanning_a_card_before_it_belongs_to_anyone_shows_a_neutral_page_and_cannot_claim_it(admin, biz_a, client):
    b, cards = new_batch(admin, 3, release=False)
    generated, stock, reserved = cards
    admin.post(f"/admin/cards/{stock['id']}/archive")  # generated cards can be archived too
    admin.post(f"/admin/batches/{b['id']}/release")
    admin.post(f"/admin/cards/{cards[2]['id']}/reserve", json={"tenant_id": biz_a.tenant_id})
    for c in cards:
        for channel in ("qr", "nfc"):
            body = scan(client, c, channel, UA if channel == "qr" else UA2)
            assert body["state"] == "unassigned" and set(body) == {"state", "message"}, body  # no business, tenant id, campaign or location
            assert biz_a.tenant_id not in str(body) and "Acme" not in str(body)
    rows = owner_query("SELECT tenant_id, status::text, location_id FROM qr_cards WHERE batch_id = :b ORDER BY card_code", b=b["id"])
    assert [r[1] for r in rows] == ["unassigned", "archived", "reserved"] and rows[0][0] is None and rows[2][2] is None  # a scan changed nothing
    assert owner_query("SELECT count(*) FROM scan_events WHERE card_id = :c AND event_type::text = 'fallback' AND channel IS NOT NULL", c=cards[0]["id"])[0][0] == 2


# ------------------------------------------------------------------ 3. identify, assign, activate
def test_scan_to_assign_identifies_the_card_from_any_form_and_activates_it(admin, biz_a, client):
    b, cards = new_batch(admin, 3)
    card = cards[0]
    for form in (card["url"], card["nfc_url"], f"{BASE}/c/{card['public_token']}", card["public_token"], card["card_code"], card["card_code"].lower(), f"  {card['card_code']} "):
        r = admin.post("/admin/cards/lookup", json={"scan": form})
        assert r.status_code == 200 and r.json()["id"] == card["id"], form
    assert admin.post("/admin/cards/lookup", json={"scan": f"{BASE}/r/Zq3k9xLmP0aTtYw2bV7cNg"}).status_code == 422  # a campaign code is not a card
    assert "campaign" in admin.post("/admin/cards/lookup", json={"scan": f"{BASE}/r/Zq3k9xLmP0aTtYw2bV7cNg"}).json()["detail"]
    assert admin.post("/admin/cards/lookup", json={"scan": "https://example.com/phish"}).status_code == 422
    assert admin.post("/admin/cards/lookup", json={"scan": "hello world"}).status_code == 422
    assert admin.post("/admin/cards/lookup", json={"scan": "A" * 24}).status_code == 404
    assert admin.post("/admin/cards/lookup", json={"scan": "FQR-999999"}).status_code == 404

    camp = campaign(biz_a)
    r = admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "campaign_id": camp["id"], "activate": True})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "active" and out["campaign_id"] == camp["id"] and out["campaign_name"] == camp["name"] and out["tenant_name"] == biz_a.get("/tenant").json()["name"]
    assert out["url"] == card["url"] and out["nfc_url"] == card["nfc_url"]  # identity unchanged
    body = scan(client, card, "qr")
    assert body["state"] == "ok" and body["campaign"] == {"id": camp["public_id"]} and body["channel"] == "qr"
    # a campaign from another business or location is refused
    other_loc = biz_a.post("/locations", json={"name": "Branch 2", "review_url": "https://g.page/r/ZZZ/review"}).json()["id"]
    camp2 = biz_a.post("/review-growth/campaigns", json={"name": "Branch 2 desk", "location_id": other_loc}).json()
    assert admin.post(f"/admin/cards/{cards[1]['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "campaign_id": camp2["id"]}).status_code == 400
    biz_b = make_business("Other Clinic")
    camp_b = campaign(biz_b)
    assert admin.post(f"/admin/cards/{cards[1]['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "campaign_id": camp_b["id"]}).status_code == 404
    assert owner_query("SELECT status::text FROM qr_cards WHERE id = :i", i=cards[1]["id"]) == [("unassigned",)]  # refused means unchanged


def test_a_business_can_place_its_own_reserved_card_but_never_claim_stock(admin, biz_a, biz_b, client):
    b, cards = new_batch(admin, 3)
    reserved, stock = cards[0], cards[1]
    admin.post(f"/admin/cards/{reserved['id']}/reserve", json={"tenant_id": biz_a.tenant_id})
    camp = campaign(biz_a)
    r = biz_a.post("/cards/lookup", json={"scan": reserved["nfc_url"]})
    assert r.status_code == 200 and r.json()["id"] == reserved["id"]
    r = biz_a.post(f"/cards/{reserved['id']}/assign", json={"location_id": biz_a.location_id, "campaign_id": camp["id"], "label": "Front desk"})
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["campaign_name"] == camp["name"] and r.json()["label"] == "Front desk"
    assert scan(client, reserved, "nfc")["state"] == "ok"
    # stock, another business's card and a card that does not exist all answer identically
    answers = {biz_a.post("/cards/lookup", json={"scan": stock["card_code"]}).json()["detail"],
               biz_a.post("/cards/lookup", json={"scan": "B" * 24}).json()["detail"]}
    assert len(answers) == 1
    assert biz_a.post("/cards/lookup", json={"scan": stock["card_code"]}).status_code == 404
    assert biz_a.post(f"/cards/{stock['id']}/assign", json={"location_id": biz_a.location_id}).status_code == 404
    assert biz_b.post(f"/cards/{reserved['id']}/assign", json={"location_id": biz_b.location_id}).status_code == 404
    assert biz_b.post("/cards/lookup", json={"scan": reserved["card_code"]}).status_code == 404
    assert owner_query("SELECT tenant_id::text FROM qr_cards WHERE id = :i", i=stock["id"]) == [(None,)]


# ------------------------------------------------------------------ 4. one card, two doors
def test_qr_and_nfc_resolve_to_the_same_card_and_are_counted_separately(admin, biz_a, client):
    b, cards = new_batch(admin, 2)
    card = cards[0]
    assert admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "activate": True}).status_code == 200
    q = scan(client, card, "qr", UA)
    n = scan(client, card, "nfc", UA2)
    assert q["state"] == n["state"] == "ok" and q["card_code"] == n["card_code"] == card["card_code"] and q["business"] == n["business"]
    assert (q["channel"], n["channel"]) == ("qr", "nfc")
    assert scan(client, card, "bogus", {"User-Agent": "Mozilla/5.0 (Linux; Android 13) Chrome/120 Mobile Safari/537.36 X"})["channel"] is None  # an unknown channel is not trusted
    # conversion events keep their channel
    r = client.post(f"/api/v1/public/c/{card['public_token']}/event", json={"type": "google_click", "channel": "nfc"}, headers=UA2)
    assert r.status_code == 204
    assert client.post(f"/api/v1/public/c/{card['public_token']}/event", json={"type": "landing_view", "channel": "sms"}, headers=UA).status_code == 422
    mine = next(c for c in biz_a.get("/cards").json() if c["id"] == card["id"])
    assert mine["stats"]["qr_scan"] == 1 and mine["stats"]["nfc_scan"] == 1 and mine["last_scan_at"]
    ov = biz_a.get("/analytics/overview").json()
    ch = ov["engagement"]["by_channel"]
    assert ch["qr"]["scans"] == 1 and ch["nfc"]["scans"] == 1 and ch["nfc"]["google_clicks"] == 1
    assert ch["qr"]["unique_visitors"] == 1 and ch["nfc"]["unique_visitors"] == 1
    row = next(c for c in ov["cards"] if c["card_code"] == card["card_code"])
    assert row["qr_scans"] == 1 and row["nfc_taps"] == 1 and row["unique_visitors"] >= 2 and row["last_activity"]
    # events from before channels were tracked stay visible as untracked, never relabelled
    from tests.conftest import owner_exec
    owner_exec("UPDATE scan_events SET channel = NULL WHERE card_id = :c AND channel = 'qr'", c=card["id"])
    ch = biz_a.get("/analytics/overview").json()["engagement"]["by_channel"]
    assert ch["qr"]["scans"] == 0 and ch["untracked"]["scans"] >= 1


# ------------------------------------------------------------------ 5. destinations change, printed codes do not
def test_destination_changes_apply_to_the_same_printed_code_and_need_confirmation(admin, biz_a, client):
    b, cards = new_batch(admin, 2)
    card = cards[0]
    camp = campaign(biz_a)
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "campaign_id": camp["id"], "activate": True})
    second = biz_a.post("/locations", json={"name": "Aliganj", "city": "Lucknow", "review_url": "https://g.page/r/NEW/review"}).json()["id"]
    assert scan(client, card, "qr")["campaign"]["id"] == camp["public_id"]

    r = biz_a.patch(f"/cards/{card['id']}", json={"location_id": second})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "confirmation_required" and d["current"]["location"] and d["new"]["location"] == "Aliganj" and "printed code does not change" in d["message"]
    assert next(c for c in biz_a.get("/cards").json() if c["id"] == card["id"])["location_id"] == biz_a.location_id  # nothing moved without the confirmation
    r = biz_a.patch(f"/cards/{card['id']}", json={"location_id": second, "confirm": True})
    assert r.status_code == 200 and r.json()["location_id"] == second and r.json()["campaign_id"] is None  # the campaign belonged to the old location
    body = scan(client, card, "qr", UA2)
    assert body["location"]["name"] == "Aliganj" and body["campaign"] is None and body["review_url"] == "https://g.page/r/NEW/review"  # immediately, no reprint
    assert (r.json()["url"], r.json()["nfc_url"]) == (card["url"], card["nfc_url"])

    camp2 = biz_a.post("/review-growth/campaigns", json={"name": "Aliganj desk", "location_id": second}).json()
    assert biz_a.patch(f"/cards/{card['id']}", json={"campaign_id": camp2["id"]}).status_code == 409
    assert biz_a.patch(f"/cards/{card['id']}", json={"campaign_id": camp2["id"], "confirm": True}).status_code == 200
    assert scan(client, card, "nfc", {"User-Agent": "Mozilla/5.0 (Linux; Android 12) Chrome/119 Mobile Safari/537.36 B"})["campaign"] == {"id": camp2["public_id"]}
    assert biz_a.patch(f"/review-growth/campaigns/{camp2['id']}", json={"status": "paused"}).status_code == 200
    assert scan(client, card, "qr", {"User-Agent": "Mozilla/5.0 (Linux; Android 12) Chrome/119 Mobile Safari/537.36 C"})["campaign"] is None  # paused campaign: plain page, customers can still review
    assert biz_a.patch(f"/cards/{card['id']}", json={"clear_campaign": True, "confirm": True}).status_code == 200
    wrong = biz_a.post("/review-growth/campaigns", json={"name": "Old branch", "location_id": biz_a.location_id}).json()
    assert biz_a.patch(f"/cards/{card['id']}", json={"campaign_id": wrong["id"], "confirm": True}).status_code == 400  # another location's campaign
    hist = admin.get(f"/admin/cards/{card['id']}").json()["history"]
    assert len(hist) >= 4 and sum(1 for h in hist if h["unassigned_at"] is None) == 1  # exactly one open period; the past is kept
    assert [h["ended_reason"] for h in hist if h["unassigned_at"]].count("reassigned") >= 3
    assert owner_query("SELECT public_token FROM qr_cards WHERE id = :i", i=card["id"]) == [(card["public_token"],)]


def test_pause_resume_and_retire_keep_history_and_retirement_is_permanent(admin, biz_a, client):
    b, cards = new_batch(admin, 2)
    card = cards[0]
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "activate": True})
    scan(client, card, "qr")
    assert biz_a.post(f"/cards/{card['id']}/pause").json()["status"] == "paused"
    body = scan(client, card, "qr", UA2)
    assert body["state"] == "inactive" and body.get("reason") == "paused" and "switched off" in body["message"] and "Acme" not in str(body)
    assert biz_a.post(f"/cards/{card['id']}/activate").json()["status"] == "active"
    assert scan(client, card, "qr", {"User-Agent": "Mozilla/5.0 (Linux; Android 12) Chrome/119 Mobile Safari/537.36 D"})["state"] == "ok"

    r = biz_a.post(f"/cards/{card['id']}/retire", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "confirmation_required" and "permanent" in r.json()["detail"]["message"]
    assert biz_a.get("/cards").json()[0]["status"] != "retired"
    r = biz_a.post(f"/cards/{card['id']}/retire", json={"confirm": True})
    assert r.status_code == 200 and r.json()["status"] == "retired"
    body = scan(client, card, "nfc", {"User-Agent": "Mozilla/5.0 (Linux; Android 12) Chrome/119 Mobile Safari/537.36 E"})
    assert body["state"] == "inactive" and "reason" not in body and "no longer active" in body["message"]
    # permanent: nothing brings it back
    assert biz_a.post(f"/cards/{card['id']}/activate").status_code == 409
    assert biz_a.post(f"/cards/{card['id']}/deactivate").status_code == 409
    assert biz_a.patch(f"/cards/{card['id']}", json={"location_id": biz_a.location_id, "confirm": True, "label": "x"}).status_code in (200, 409)
    assert admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id}).status_code == 409
    assert admin.post(f"/admin/cards/{card['id']}/unassign", json={"confirm": True}).status_code == 409
    assert admin.post(f"/admin/cards/{card['id']}/status", json={"status": "active"}).status_code == 409
    assert admin.post(f"/admin/cards/{card['id']}/reserve", json={"tenant_id": biz_a.tenant_id}).status_code == 409
    # history and scans survive
    detail = admin.get(f"/admin/cards/{card['id']}").json()
    assert detail["card"]["status"] == "retired" and detail["history"][0]["ended_reason"] == "retired" and detail["card"]["stats"]["scan"] >= 2
    assert owner_query("SELECT retired_at IS NOT NULL FROM qr_cards WHERE id = :i", i=card["id"]) == [(True,)]


def test_moving_a_card_to_another_business_needs_confirmation_and_keeps_both_histories(admin, biz_a, biz_b, client):
    b, cards = new_batch(admin, 2)
    card = cards[0]
    admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "activate": True})
    scan(client, card, "qr")
    target = {"tenant_id": biz_b.tenant_id, "location_id": biz_b.location_id}
    r = admin.post(f"/admin/cards/{card['id']}/assign", json=target)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "confirmation_required"
    assert owner_query("SELECT tenant_id::text FROM qr_cards WHERE id = :i", i=card["id"]) == [(biz_a.tenant_id,)]
    assert admin.post(f"/admin/cards/{card['id']}/assign", json={**target, "confirm": True}).status_code == 200
    body = scan(client, card, "nfc", UA2)
    assert body["state"] == "ok" and body["business"]["name"] != biz_a.get("/tenant").json()["name"]
    hist = admin.get(f"/admin/cards/{card['id']}").json()["history"]
    assert len(hist) == 2 and hist[1]["ended_reason"] == "reassigned" and hist[0]["unassigned_at"] is None
    assert owner_query("SELECT count(*) FROM scan_events WHERE card_id = :c AND tenant_id = :t", c=card["id"], t=biz_a.tenant_id)[0][0] >= 1  # A keeps its own scan history
    assert biz_a.get("/cards").json() == []  # and it no longer sees the card
    assert biz_a.post(f"/cards/{card['id']}/pause").status_code == 404


# ------------------------------------------------------------------ 6. security
def test_unauthorised_assignment_and_claiming_are_refused_and_audited(admin, biz_a, biz_b, client):
    b, cards = new_batch(admin, 4)
    card, stock = cards[0], cards[1]
    # nothing a customer (or anyone not logged in) can do changes a card
    anon = client
    assert anon.post(f"/api/v1/cards/{card['id']}/assign", json={"location_id": biz_a.location_id}).status_code in (401, 403)
    assert anon.post("/api/v1/admin/cards/lookup", json={"scan": card["card_code"]}).status_code in (401, 403)
    assert anon.post(f"/api/v1/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id}).status_code in (401, 403)
    for path in ("claim", "assign", "activate"):
        assert anon.post(f"/api/v1/public/c/{card['public_token']}/{path}").status_code in (404, 405)
    scan(client, card, "qr")
    assert owner_query("SELECT status::text, tenant_id::text FROM qr_cards WHERE id = :i", i=card["id"]) == [("unassigned", None)]
    # a business is not a platform admin
    for call in (lambda: biz_a.post("/admin/cards/lookup", json={"scan": card["card_code"]}),
                 lambda: biz_a.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id}),
                 lambda: biz_a.post("/admin/cards/bulk-assign", json={"card_ids": [card["id"]], "tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id}),
                 lambda: biz_a.post(f"/admin/cards/{card['id']}/reserve", json={"tenant_id": biz_a.tenant_id}),
                 lambda: biz_a.get("/admin/inventory"), lambda: biz_a.post(f"/admin/batches/{b['id']}/release")):
        assert call().status_code == 403
    assert owner_query("SELECT status::text FROM qr_cards WHERE id = :i", i=card["id"]) == [("unassigned",)]
    # an assignment is attributed: who, to whom
    assert admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id}).status_code == 200
    rows = owner_query("SELECT action, tenant_id::text, user_id IS NOT NULL FROM audit_logs WHERE entity_id = :e AND action = 'admin.card_assign'", e=card["id"])
    assert rows == [("admin.card_assign", biz_a.tenant_id, True)]
    # B cannot touch A's card at all
    assert biz_b.post(f"/cards/{card['id']}/retire", json={"confirm": True}).status_code == 404
    assert biz_b.patch(f"/cards/{card['id']}", json={"label": "mine now"}).status_code == 404
    assert owner_query("SELECT status::text, label FROM qr_cards WHERE id = :i", i=card["id"]) == [("assigned", None)]


def test_a_teammate_limited_to_one_location_cannot_see_or_place_other_cards(admin, biz_a):
    second = biz_a.post("/locations", json={"name": "Aliganj", "review_url": "https://g.page/r/B/review"}).json()["id"]
    b, cards = new_batch(admin, 4)
    admin.post(f"/admin/cards/{cards[0]['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    admin.post(f"/admin/cards/{cards[1]['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": second})
    admin.post(f"/admin/cards/{cards[2]['id']}/reserve", json={"tenant_id": biz_a.tenant_id})
    staff = invite(biz_a, "staff", [second])
    seen = {c["id"] for c in staff.get("/cards").json()}
    assert seen == {cards[1]["id"]}  # only their location: not the other branch's card, not the unplaced reserved one
    assert staff.post("/cards/lookup", json={"scan": cards[0]["card_code"]}).status_code == 403  # lookup/assign are for owners and admins
    assert staff.post(f"/cards/{cards[2]['id']}/assign", json={"location_id": second}).status_code == 403
    assert staff.post(f"/cards/{cards[0]['id']}/retire", json={"confirm": True}).status_code == 403
    assert {c["id"] for c in biz_a.get("/cards").json()} == {cards[0]["id"], cards[1]["id"], cards[2]["id"]}


def test_lookups_are_rate_limited(admin):
    codes = []
    for _ in range(121):
        codes.append(admin.post("/admin/cards/lookup", json={"scan": "FQR-000000"}).status_code)
    assert codes[0] == 404 and codes[-1] == 429


# ------------------------------------------------------------------ 7. bulk assignment
def test_bulk_assignment_is_all_or_nothing_and_confirms_cards_in_use(admin, biz_a, biz_b, client):
    b, cards = new_batch(admin, 6)
    camp = campaign(biz_a)
    admin.post(f"/admin/cards/{cards[5]['id']}/retire", json={"confirm": True})
    target = {"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "campaign_id": camp["id"]}
    serials = [c["card_code"] for c in cards[:5]]
    # one bad card: nothing at all is assigned
    r = admin.post("/admin/cards/bulk-assign", json={**target, "serials": serials[:3] + [cards[5]["card_code"]]})
    assert r.status_code == 409 and cards[5]["card_code"] in r.json()["detail"]["message"]
    assert r.status_code == 409 and owner_query("SELECT count(*) FROM qr_cards WHERE batch_id = :b AND tenant_id IS NOT NULL", b=b["id"]) == [(0,)]
    assert admin.post("/admin/cards/bulk-assign", json={**target, "serials": serials + ["FQR-NOPE-1"]}).status_code in (404, 422)
    assert admin.post("/admin/cards/bulk-assign", json={**target, "serials": serials[:2], "card_ids": [cards[2]["id"], cards[3]["id"]]}).json()["assigned"] == 4
    assert admin.post("/admin/cards/bulk-assign", json={**target, "card_ids": [cards[4]["id"]]}).json()["assigned"] == 1
    assert owner_query("SELECT status::text, count(*) FROM qr_cards WHERE batch_id = :b GROUP BY 1 ORDER BY 1", b=b["id"]) == [("active", 5), ("retired", 1)]
    assert all(scan(client, cards[i], "qr", {"User-Agent": f"Mozilla/5.0 (Linux; Android 11) Chrome/110 Mobile Safari/537.36 {i}"})["campaign"]["id"] == camp["public_id"] for i in range(5))
    # moving cards that are in use to someone else asks first, and still changes nothing without it
    other = {"tenant_id": biz_b.tenant_id, "location_id": biz_b.location_id}
    r = admin.post("/admin/cards/bulk-assign", json={**other, "card_ids": [cards[0]["id"], cards[1]["id"]]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "confirmation_required"
    assert owner_query("SELECT count(*) FROM qr_cards WHERE tenant_id = :t", t=biz_b.tenant_id) == [(0,)]
    assert admin.post("/admin/cards/bulk-assign", json={**other, "card_ids": [cards[0]["id"], cards[1]["id"]], "confirm": True}).json()["assigned"] == 2
    assert admin.post("/admin/cards/bulk-assign", json={**target}).status_code == 422  # nothing chosen


# ------------------------------------------------------------------ 8. printing safety: permanent HTTPS domain only
@pytest.mark.parametrize("base,ok", [
    ("https://go.flowqr.in", True), ("https://go.test.flowqr.example", True), ("https://qr.clinic.co.in/", True),
    ("http://go.flowqr.in", False), ("http://localhost:3000", False), ("https://localhost", False), ("https://127.0.0.1", False),
    ("https://192.168.1.20", False), ("https://abc123.ngrok-free.app", False), ("https://x.trycloudflare.com", False),
    ("https://thing.loca.lt", False), ("https://flowqr.local", False), ("https://mypc.ts.net", False), ("https://intranet", False), ("", False),
])
def test_only_a_permanent_https_domain_is_printable(base, ok):
    assert (permanent_url_problem(base) is None) is ok


def test_batch_print_exports_and_production_downloads_are_blocked_on_a_temporary_address(admin, biz_a, monkeypatch):
    b, cards = new_batch(admin, 3)
    camp = campaign(biz_a)
    admin.post(f"/admin/cards/{cards[0]['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id})
    ours = {"export": f"/admin/batches/{b['id']}/export.zip", "csv": f"/admin/batches/{b['id']}/inventory.csv", "sheet": f"/admin/batches/{b['id']}/sheet",
            "posters": f"/admin/batches/{b['id']}/posters.pdf", "files": f"/admin/batches/{b['id']}/posters.zip"}
    for name, path in ours.items():
        assert admin.get(path).status_code == 200, name  # the permanent test domain is fine
    for bad in ("http://localhost:3000", "https://shy-tunnel.trycloudflare.com", "http://go.flowqr.in"):
        monkeypatch.setattr(settings, "public_card_base_url", bad)
        for name, path in ours.items():
            r = admin.get(path)
            assert r.status_code == 409 and r.json()["detail"]["code"] == "print_domain_not_permanent", (bad, name)
        assert biz_a.post("/qr/bulk", json={"campaign_ids": [camp["id"]], "design": "poster"}).status_code == 409
    # a single poster: allowed while developing (flagged), refused in staging/production
    monkeypatch.setattr(settings, "public_card_base_url", "http://localhost:3000")
    r = biz_a.get(f"/review-growth/campaigns/{camp['id']}/poster.png")
    assert r.status_code == 200 and r.headers["x-flowqr-not-for-print"]
    monkeypatch.setattr(settings, "app_env", "production")
    r = biz_a.get(f"/review-growth/campaigns/{camp['id']}/poster.png")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "print_domain_not_permanent"


def test_inventory_csv_carries_serial_qr_and_nfc_addresses_for_the_tag_writer(admin):
    b, cards = new_batch(admin, 7, name="Printer run")
    r = admin.get(f"/admin/batches/{b['id']}/inventory.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert [x["serial"] for x in rows] == sorted(c["card_code"] for c in cards) and len(rows) == 7
    by_serial = {c["card_code"]: c for c in cards}
    for x in rows:
        c = by_serial[x["serial"]]
        assert x["qr_url"] == c["url"] == f"{BASE}/q/{c['public_token']}" and x["nfc_url"] == c["nfc_url"] == f"{BASE}/n/{c['public_token']}"
        assert int(x["nfc_ndef_uri_bytes"]) == len(x["nfc_url"].encode()) < 137 and x["batch"] == "Printer run"
    z = zipfile.ZipFile(io.BytesIO(admin.get(f"/admin/batches/{b['id']}/export.zip").content))
    man = list(csv.DictReader(io.StringIO(z.read("manifest.csv").decode())))
    assert {m["card_code"]: (m["url"], m["nfc_url"]) for m in man} == {c["card_code"]: (c["url"], c["nfc_url"]) for c in cards}


# ------------------------------------------------------------------ 9. old printed codes
def test_every_previously_issued_code_still_works(admin, biz_a, client):
    """Cards whose paper says /c/ keep working, and a destination change never touches a campaign's printed /r/ link."""
    camp = campaign(biz_a)
    before = (camp["public_id"], camp["url"])
    b, cards = new_batch(admin, 2)
    from tests.conftest import owner_exec
    owner_exec("UPDATE qr_cards SET qr_path = 'c' WHERE batch_id = :b", b=b["id"])
    for c in cards:
        admin.post(f"/admin/cards/{c['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "activate": True})
    second = biz_a.post("/locations", json={"name": "Moved", "review_url": "https://g.page/r/M/review"}).json()["id"]
    assert biz_a.patch(f"/review-growth/campaigns/{camp['id']}", json={"location_id": second}).status_code == 200
    assert biz_a.patch(f"/cards/{cards[0]['id']}", json={"location_id": second, "confirm": True}).status_code == 200
    now = biz_a.get(f"/review-growth/campaigns/{camp['id']}").json()
    assert (now["public_id"], now["url"]) == before
    assert client.get(f"/api/v1/public/reviews/{camp['public_id']}", headers=UA).json()["state"] == "ok"
    assert admin.get(f"/admin/cards/{cards[0]['id']}").json()["card"]["url"] == f"{BASE}/c/{cards[0]['public_token']}"
    assert card_qr_url(type("C", (), {"public_token": "T" * 24, "qr_path": None})) == f"{BASE}/c/{'T' * 24}"  # a card with no path recorded is an old one
    assert card_nfc_url("T" * 24) == f"{BASE}/n/{'T' * 24}"
