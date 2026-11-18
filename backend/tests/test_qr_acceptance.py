"""Acceptance tests for the physical-card lifecycle: a printed code must keep reaching the right place for as long as it exists.

Gaps closed here (the inventory, posters, scans, NFC and destination basics are already covered by test_card_inventory, test_poster, test_qr and test_qr_assets):
batch limits and transactional failure, token entropy and enumeration, a destination never outliving its business, the redirect door never looping back to a print domain, hostile paths,
privacy of analytics output, poster output for a print domain at print-size reduction, and what a tenant can and cannot do to a card's destination."""
import io
import json
import math
import re
import time
import uuid
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from app.core import rate_limit
from app.core.config import settings
from app.services import cards as cards_svc
from app.services import poster
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_card_inventory import new_batch, scan
from tests.test_qr import UA, UA2, raster, zxing
from tests.test_qr_assets import BOT, DEST, DESKTOP, go, live_card, put

ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


def count(table="qr_cards"):
    return owner_query(f"SELECT count(*) FROM {table}")[0][0]


# ============================================================================================================================ A. bulk generation
@pytest.mark.parametrize("quantity", [1, 10, 2000])
def test_batches_of_one_ten_and_the_maximum_produce_that_many_unique_unpredictable_permanent_codes(admin, quantity):
    before = count()
    t0 = time.monotonic()
    r = admin.post("/admin/batches", json={"name": f"Acceptance {quantity}", "quantity": quantity})
    took = time.monotonic() - t0
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    rows = owner_query("SELECT public_token, card_code, status::text, qr_path, tenant_id, location_id, destination_url FROM qr_cards WHERE batch_id = :b", b=bid)
    assert len(rows) == quantity == count() - before
    tokens = [r[0] for r in rows]
    assert len(set(tokens)) == quantity and len({r[1] for r in rows}) == quantity  # no duplicate code or serial
    assert all(len(t) == 24 and set(t) <= ALPHABET for t in tokens)  # 24 URL-safe characters = 144 bits
    assert {r[2] for r in rows} == {"generated"} and {r[3] for r in rows} == {"q"} and {(r[4], r[5], r[6]) for r in rows} == {(None, None, None)}  # nobody owns them, nowhere to send people
    assert took < 60, f"{quantity} codes took {took:.1f}s"
    if quantity == 2000:
        # unpredictability: no ordering, no shared prefix, and the characters are spread like random data (not a counter)
        assert tokens != sorted(tokens) and len({t[:4] for t in tokens}) > 1900 and len({t[0] for t in tokens}) >= 60
        bits = sum(-p * math.log2(p) for p in (c / (24 * quantity) for c in __import__("collections").Counter("".join(tokens)).values()))
        assert bits > 5.9  # close to the 6 bits per character of a uniform 64-letter alphabet


def test_one_more_than_the_maximum_zero_and_negative_batches_are_refused_and_create_nothing(admin):
    before = count()
    for q in (2001, 0, -5, 10**9):
        assert admin.post("/admin/batches", json={"name": "Too big", "quantity": q}).status_code == 422
    assert admin.post("/admin/batches", json={"name": "Bad prefix", "quantity": 3, "prefix": "bad;--"}).status_code == 422
    assert count() == before


def test_the_database_itself_refuses_a_duplicate_public_code_or_serial(admin):
    b, cards = new_batch(admin, 2, release=False)
    import sqlalchemy.exc as sx
    with pytest.raises(sx.IntegrityError):
        owner_exec("UPDATE qr_cards SET public_token = :t WHERE id = :i", t=cards[0]["public_token"], i=cards[1]["id"])
    with pytest.raises(sx.IntegrityError):
        owner_exec("UPDATE qr_cards SET card_code = :t WHERE id = :i", t=cards[0]["card_code"], i=cards[1]["id"])


def test_a_failure_in_the_middle_of_a_batch_leaves_no_batch_and_no_cards_behind(admin, monkeypatch):
    before_cards, before_batches = count(), count("card_batches")
    monkeypatch.setattr(cards_svc, "new_public_tokens", lambda db, n: ["D" * 24] * n)  # a collision the unique constraint must stop
    r = admin.post("/admin/batches", json={"name": "Doomed", "quantity": 5})
    assert r.status_code == 500 and "retry" in r.text.lower()
    assert count() == before_cards and count("card_batches") == before_batches  # all or nothing
    monkeypatch.undo()
    assert admin.post("/admin/batches", json={"name": "Recovered", "quantity": 5}).status_code == 201  # and the next attempt works


def test_two_batches_never_share_a_code_or_a_serial(admin):
    (_, a), (_, b) = new_batch(admin, 25, release=False), new_batch(admin, 25, release=False)
    assert not ({c["public_token"] for c in a} & {c["public_token"] for c in b}) and not ({c["card_code"] for c in a} & {c["card_code"] for c in b})


def test_every_new_card_carries_the_permanent_print_address_on_its_batch(admin):
    b, cards = new_batch(admin, 3, release=False)
    assert owner_query("SELECT base_url FROM card_batches WHERE id = :b", b=b["id"])[0][0] == settings.public_card_base_url.rstrip("/")
    for c in cards:
        assert c["url"] == f"{settings.public_card_base_url.rstrip('/')}/q/{c['public_token']}" and c["nfc_url"] == f"{settings.public_card_base_url.rstrip('/')}/n/{c['public_token']}"
        assert "g.page" not in c["url"] and "google" not in c["url"].lower()  # the QR never encodes the review link itself


# ============================================================================================================================ B/C. assignment guards
def test_assignment_refuses_unknown_foreign_and_mismatched_targets_and_changes_nothing(admin, biz_a, biz_b):
    b, cards = new_batch(admin, 2)
    c = cards[0]
    before = owner_query("SELECT status::text, tenant_id::text, location_id::text FROM qr_cards WHERE id = :i", i=c["id"])
    bad = [
        {"tenant_id": str(uuid.uuid4()), "location_id": biz_a.location_id},  # unknown business
        {"tenant_id": biz_a.tenant_id, "location_id": str(uuid.uuid4())},  # unknown location
        {"tenant_id": biz_a.tenant_id, "location_id": biz_b.location_id},  # another business's location
        {"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "campaign_id": str(uuid.uuid4())},  # unknown campaign
    ]
    for body in bad:
        r = admin.post(f"/admin/cards/{c['id']}/assign", json=body)
        assert r.status_code in (400, 404), (body, r.status_code, r.text)
    assert admin.post(f"/admin/cards/{c['id']}/assign", json={"tenant_id": biz_a.tenant_id}).status_code == 422  # a location is required
    assert owner_query("SELECT status::text, tenant_id::text, location_id::text FROM qr_cards WHERE id = :i", i=c["id"]) == before
    assert owner_query("SELECT count(*) FROM card_assignments WHERE card_id = :i", i=c["id"])[0][0] == 0


def test_a_card_is_never_open_for_two_businesses_and_every_move_is_in_the_history_and_the_audit_log(admin, biz_a, biz_b):
    b, cards = new_batch(admin, 2)
    c = cards[0]
    assert admin.post(f"/admin/cards/{c['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "activate": True}).status_code == 200
    r = admin.post(f"/admin/cards/{c['id']}/assign", json={"tenant_id": biz_b.tenant_id, "location_id": biz_b.location_id})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "confirmation_required"  # moving a distributed card needs an explicit yes
    assert owner_query("SELECT tenant_id::text FROM qr_cards WHERE id = :i", i=c["id"])[0][0] == biz_a.tenant_id
    assert admin.post(f"/admin/cards/{c['id']}/assign", json={"tenant_id": biz_b.tenant_id, "location_id": biz_b.location_id, "confirm": True}).status_code == 200
    open_rows = owner_query("SELECT tenant_id::text FROM card_assignments WHERE card_id = :i AND unassigned_at IS NULL", i=c["id"])
    assert open_rows == [(biz_b.tenant_id,)]  # exactly one open assignment, and it is the new business
    assert owner_query("SELECT count(*) FROM card_assignments WHERE card_id = :i", i=c["id"])[0][0] == 2  # the first one is kept, closed
    assert owner_query("SELECT count(*) FROM audit_logs WHERE entity_id = :i AND action = 'admin.card_assign'", i=c["id"])[0][0] == 2


# ============================================================================================================================ D. a destination never outlives its business
def test_moving_a_card_to_another_business_removes_the_old_destination_and_records_it(admin, biz_a, biz_b, client):
    b, card = live_card(admin, biz_a)
    put(admin, card, "https://example.org/business-a-reviews", confirm=True)
    assert scan(client, card, "qr", UA)["state"] == "redirect"
    r = admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_b.tenant_id, "location_id": biz_b.location_id, "confirm": True, "activate": True})
    assert r.status_code == 200
    assert r.json()["destination_url"] is None  # the old owner's address did not follow the card
    body = scan(client, card, "qr", UA2)
    assert body["state"] == "ok" and body["business"]["name"] == "Beta Dental" and "url" not in body  # business B's own review page, not business A's destination
    h = admin.get(f"/admin/cards/{card['id']}/destination").json()["history"]
    assert [x["action"] for x in h] == ["cleared", "set"] and h[0]["old_url"] == "https://example.org/business-a-reviews" and "different business" in h[0]["reason"]
    a = owner_query("SELECT metadata FROM audit_logs WHERE entity_id = :i AND action = 'admin.card_destination_cleared'", i=card["id"])
    assert len(a) == 1 and a[0][0]["old"] == "https://example.org/business-a-reviews"


def test_returning_a_card_to_stock_or_reserving_it_also_removes_its_destination(admin, biz_a, biz_b):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    assert admin.post(f"/admin/cards/{card['id']}/unassign", json={"confirm": True}).status_code == 200
    assert admin.get(f"/admin/cards/{card['id']}/destination").json()["url"] is None
    put(admin, card)  # a stock card may be given one in advance...
    assert admin.post(f"/admin/cards/{card['id']}/reserve", json={"tenant_id": biz_b.tenant_id}).status_code == 200  # ...but it does not survive being handed to a business
    assert admin.get(f"/admin/cards/{card['id']}/destination").json()["url"] is None


def test_a_confirmed_move_to_another_location_of_the_same_business_also_clears_it_but_a_no_op_reassignment_does_not(admin, biz_a):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    same = admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "activate": True})
    assert same.status_code == 200 and same.json()["destination_url"] == DEST  # nothing changed, so nothing is dropped
    loc2 = biz_a.post("/locations", json={"name": "Aliganj", "city": "Lucknow", "review_url": "https://g.page/r/NEW/review"}).json()["id"]
    assert admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": loc2, "confirm": True}).json()["destination_url"] is None


def test_a_business_can_move_its_own_card_but_cannot_set_or_keep_a_destination_through_that_door(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    loc2 = biz_a.post("/locations", json={"name": "Aliganj", "city": "Lucknow", "review_url": "https://g.page/r/NEW/review"}).json()["id"]
    r = biz_a.patch(f"/cards/{card['id']}", json={"location_id": loc2, "confirm": True, "destination_url": "https://evil.example.net/phish"})
    assert r.status_code == 200 and r.json()["destination_url"] is None  # the move cleared the old one; the smuggled field was ignored
    assert owner_query("SELECT destination_url FROM qr_cards WHERE id = :i", i=card["id"])[0][0] is None
    assert scan(client, card, "qr", UA)["state"] == "ok"


# ============================================================================================================================ E. the redirect door: routing, loops, hostile input
@pytest.fixture()
def split_domains(monkeypatch):
    """The target production layout: cards print a redirect domain; the app lives elsewhere."""
    monkeypatch.setattr(settings, "public_card_base_url", "https://go.test.flowqr.example")
    monkeypatch.setattr(settings, "frontend_url", "https://app.test.flowqr.example")


@pytest.mark.parametrize("channel,door", [("qr", "q"), ("nfc", "n"), (None, "c")])
def test_the_door_never_redirects_back_to_the_print_domain_and_keeps_the_channel(admin, biz_a, client, split_domains, channel, door):
    b, card = live_card(admin, biz_a)  # no destination: the card's own landing page
    r = go(client, card, UA, **({"channel": channel} if channel else {}))
    assert r.status_code == 302 and r.headers["location"] == f"https://app.test.flowqr.example/{door}/{card['public_token']}"
    assert "go.test.flowqr.example" not in r.headers["location"]  # a print domain that fronts /q and /n would otherwise loop forever


@pytest.mark.parametrize("how", ["paused", "retired", "archived", "stock"])
def test_a_card_that_is_not_live_sends_scanners_to_the_neutral_notice_never_to_a_destination(admin, biz_a, client, split_domains, how):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    if how == "paused":
        admin.post(f"/admin/cards/{card['id']}/status", json={"status": "paused"})
    elif how == "retired":
        admin.post(f"/admin/cards/{card['id']}/retire", json={"confirm": True})
    else:
        admin.post(f"/admin/cards/{card['id']}/unassign", json={"confirm": True})
        if how == "archived":
            admin.post(f"/admin/cards/{card['id']}/archive")
    r = go(client, card, UA, channel="qr")
    assert r.status_code == 302 and r.headers["location"].startswith("https://app.test.flowqr.example/q/") and DEST not in r.headers["location"]
    body = scan(client, card, "qr", UA2)
    assert body["state"] in ("inactive", "unassigned") and "url" not in body


def test_a_destination_that_is_down_does_not_change_what_flowqr_does(admin, biz_a, client):
    # FlowQR never contacts the destination, so an outage there cannot make a scan fail or slow here: the visitor is handed the address and the browser reports the outage.
    b, card = live_card(admin, biz_a)
    put(admin, card, "https://this-host-does-not-exist.example.org/x", confirm=True)
    t0 = time.monotonic()
    r = go(client, card, UA)
    assert r.status_code == 302 and r.headers["location"] == "https://this-host-does-not-exist.example.org/x" and time.monotonic() - t0 < 2


@pytest.mark.parametrize("token", [
    "..%2f..%2fetc%2fpasswd", "%2e%2e%2fadmin", "....//....//x", "a" * 23 + "%00", "a" * 23 + "'", "' OR '1'='1", "1; DROP TABLE qr_cards;--", "a" * 23 + "‮", "%252e%252e",
    "a" * 24 + "/extra", "a" * 24 + ".json", "A" * 200, "-" * 24, "_" * 24, "０" * 24,
])
def test_hostile_paths_are_404_or_422_never_a_redirect_and_never_touch_the_data(admin, client, token):
    before = count()
    for path in (f"/api/v1/go/{token}", f"/api/v1/public/c/{token}"):
        r = client.get(path, headers=UA, follow_redirects=False)
        assert r.status_code in (404, 405, 422, 429), (path, r.status_code)
        assert "location" not in r.headers
    assert count() == before


def test_unknown_codes_look_identical_whatever_their_shape_and_are_not_recorded(client, admin):
    rate_limit.reset_memory_limits()
    shapes = ["a" * 24, "Zq3k9xLmP0aTtYw2bV7cNg", "short", "x" * 63]
    bodies = {json.dumps(client.get(f"/api/v1/go/{t}", headers=UA, follow_redirects=False).json(), sort_keys=True) for t in shapes[:2] + shapes[3:]}
    assert len(bodies) == 1  # a valid-looking unknown code answers exactly like any other: nothing reveals "close" codes
    assert owner_query("SELECT count(*) FROM scan_events WHERE card_id IS NULL AND event_type = 'scan'")[0][0] == 0
    rate_limit.reset_memory_limits()


def test_guessing_codes_is_cut_off_quickly(client):
    rate_limit.reset_memory_limits()
    codes = [client.get(f"/api/v1/go/{uuid.uuid4().hex[:24]}", headers=UA, follow_redirects=False).status_code for _ in range(45)]
    assert codes[0] == 404 and 429 in codes and codes.index(429) <= 32  # 30 misses per 5 minutes per address
    rate_limit.reset_memory_limits()


def test_query_strings_cannot_steer_the_redirect_and_bots_are_redirected_but_counted_apart(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    for q in ({"channel": "qr", "url": "https://evil.example.net"}, {"channel": "nfc", "to": "//evil.example.net", "redirect_uri": "javascript:alert(1)"}, {"channel": ["qr", "nfc"]}):
        r = client.get(f"/api/v1/go/{card['public_token']}", params=q, headers=DESKTOP, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == DEST
    r = client.get(f"/api/v1/go/{card['public_token']}", params={"channel": "qr"}, headers=BOT, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == DEST  # a link-preview robot gets the same answer...
    a = admin.get(f"/admin/cards/{card['id']}/analytics").json()
    assert a["automated_visits"] == 1 and a["totals"]["total"] >= 1  # ...but is not counted as a customer


def test_the_door_response_carries_nothing_about_the_business_the_card_or_the_visitor(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    r = go(client, card, UA, channel="qr")
    blob = (str(dict(r.headers)) + r.text).lower()
    for secret in ("alpha physio", biz_a.tenant_id, biz_a.location_id, card["id"], card["card_code"].lower(), "tenant", "g.page"):
        assert secret not in blob, secret
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"


# ============================================================================================================================ F. NFC parity
def test_qr_and_nfc_addresses_differ_only_by_the_door_letter_and_the_nfc_status_cannot_be_forged(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    assert card["url"].rsplit("/", 2)[-1] == card["nfc_url"].rsplit("/", 2)[-1] == card["public_token"]
    assert card["url"].replace("/q/", "/n/") == card["nfc_url"]
    n = admin.get(f"/admin/cards/{card['id']}/nfc").json()
    assert n["nfc_url"] == card["nfc_url"] and n["status"] == "not_programmed"
    for forged in ({"programmed": True, "verified": True}, {"programmed": True, "status": "tap_seen"}, {"status": "tap_seen"}):
        assert admin.post(f"/admin/cards/{card['id']}/nfc", json=forged).status_code == 422  # there is no way to claim a verification that did not happen
    admin.post(f"/admin/cards/{card['id']}/nfc", json={"programmed": True})
    assert admin.get(f"/admin/cards/{card['id']}/nfc").json()["status"] == "marked_programmed"
    put(admin, card, confirm=True)
    assert scan(client, card, "qr", UA)["url"] == scan(client, card, "nfc", UA2)["url"] == DEST  # one destination for both doors
    put(admin, card, "https://example.org/changed", confirm=True)
    assert scan(client, card, "qr", DESKTOP)["url"] == "https://example.org/changed"


# ============================================================================================================================ G. analytics: access and privacy
def test_analytics_are_closed_to_anonymous_callers_and_to_every_business(admin, biz_a, biz_b, client):
    b, card = live_card(admin, biz_a)
    for path in (f"/api/v1/admin/cards/{card['id']}/analytics", "/api/v1/admin/cards-analytics", f"/api/v1/admin/cards/{card['id']}/destination", f"/api/v1/admin/cards/{card['id']}/nfc"):
        assert client.get(path).status_code in (401, 403), path
    for who in (biz_a, biz_b):
        assert who.get(f"/admin/cards/{card['id']}/analytics").status_code == 403 and who.get("/admin/cards-analytics").status_code == 403
    scan(client, card, "qr", UA)
    mine, theirs = biz_a.get("/analytics/overview").json(), biz_b.get("/analytics/overview").json()
    assert mine["engagement"]["by_channel"]["qr"]["scans"] == 1 and theirs["engagement"]["by_channel"]["qr"]["scans"] == 0  # a business sees only its own cards' traffic


def test_analytics_output_contains_no_personal_data_and_no_raw_identifiers(admin, biz_a, client):
    b, card = live_card(admin, biz_a, label="Counter")
    scan(client, card, "qr", UA)
    client.get(f"/api/v1/public/c/{card['public_token']}", params={"channel": "nfc", "ref": "https://www.instagram.com/p/secret?token=abc"}, headers=UA2)
    hashes = [r[0] for r in owner_query("SELECT visitor_hash FROM scan_events WHERE card_id = :c", c=card["id"])]
    outputs = [admin.get(f"/admin/cards/{card['id']}/analytics").text, admin.get("/admin/cards-analytics").text, biz_a.get("/analytics/overview").text, admin.get(f"/admin/cards/{card['id']}").text]
    for text in outputs:
        low = text.lower()
        assert not any(h and h in text for h in hashes)  # not even the salted daily hash leaves the server
        for banned in ("visitor_hash", "user_agent", "user-agent", "mozilla", "iphone", "\"ip\"", "ip_address", "secret", "token=abc", "127.0.0.1", "testclient"):
            assert banned not in low, banned
    assert not owner_query("SELECT 1 FROM scan_events WHERE referrer_host LIKE '%/%' OR referrer_host LIKE '%?%'")  # the referrer is stored as a host, never a path or query


def test_a_scan_is_never_recorded_as_a_review_or_a_conversion(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    for ua in (UA, UA2, DESKTOP):
        go(client, card, ua, channel="qr")
    kinds = {r[0] for r in owner_query("SELECT event_type::text FROM scan_events WHERE card_id = :c", c=card["id"])}
    assert kinds == {"scan"}  # no landing_view, no google_click, nothing that could be mistaken for a posted review
    assert owner_query("SELECT count(*) FROM reviews WHERE tenant_id = :t", t=biz_a.tenant_id)[0][0] == 0


# ============================================================================================================================ H. tenant isolation of cards
def test_a_business_cannot_see_edit_download_or_scan_for_another_businesss_card(admin, biz_a, biz_b):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    cid = card["id"]
    assert all(c["id"] != cid for c in biz_b.get("/cards").json())
    for method, path, body in (("get", f"/cards/{cid}/qr.png", None), ("get", f"/cards/{cid}/qr.svg", None), ("get", f"/cards/{cid}/poster.png", None), ("patch", f"/cards/{cid}", {"label": "mine now"}),
                               ("post", f"/cards/{cid}/pause", {}), ("post", f"/cards/{cid}/retire", {"confirm": True}), ("post", f"/cards/{cid}/assign", {"location_id": biz_b.location_id})):
        r = getattr(biz_b, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code in (403, 404), (method, path, r.status_code)
    assert "destination" not in json.dumps(biz_b.get("/cards").json())
    after = owner_query("SELECT tenant_id::text, label, status::text, destination_url FROM qr_cards WHERE id = :i", i=cid)[0]
    assert after[0] == biz_a.tenant_id and after[1] != "mine now" and after[2] in ("active", "assigned") and after[3] == DEST


# ============================================================================================================================ I. print output for the redirect domain
GO_URLS = [f"https://go.flowqr.site/q/{'Zq3k9xLmP0aTtYw2bV7cNgAB'}", f"https://go.flowqr.site/n/{'k' * 24}", f"https://flowqr.site/q/{'9' * 24}"]


@pytest.mark.parametrize("url", GO_URLS)
def test_posters_for_the_permanent_domain_decode_exactly_at_every_format_and_survive_print_size_reduction(url):
    for fmt, data in (("png", poster.poster_png(url)), ("svg", poster.poster_svg(url)), ("pdf", poster.poster_pdf(url)), ("pdf-a6", poster.poster_pdf(url, size="a6"))):
        assert zxing(raster(data, "png" if fmt == "png" else "svg" if fmt == "svg" else "pdf")) == [url], fmt
    big = Image.open(io.BytesIO(poster.poster_png(url, scale=1))).convert("RGB")
    for shrink in (2, 3, 4):  # 300 dpi shown at 150, 100 and 75 dpi: a card scanned from a screen or a small proof print
        small = big.resize((big.width // shrink, big.height // shrink), Image.LANCZOS)
        assert zxing(small) == [url], f"shrunk {shrink}x"


def test_the_pdf_page_is_the_approved_size_and_the_svg_and_png_files_are_well_formed():
    url = GO_URLS[0]
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open(stream=poster.poster_pdf(url), filetype="pdf")
    assert doc.page_count == 1 and abs(doc[0].rect.width - 253.2) < 0.5 and abs(doc[0].rect.height - 357.84) < 0.5  # 89 x 126 mm
    assert abs(doc[0].rect.width / 72 * 25.4 - 89.3) < 0.3
    root = ET.fromstring(poster.poster_svg(url))
    assert root.tag.endswith("svg") and root.attrib.get("viewBox")
    png = Image.open(io.BytesIO(poster.poster_png(url)))
    assert png.size == (1055, 1491) and png.info.get("dpi", (0, 0))[0] in (300, 299.9994)
    assert doc[0].get_text().strip() == "" or len(doc[0].get_fonts()) <= 2  # no missing-font dependence: the poster is artwork, not live text


def test_a_sheet_of_cards_for_the_permanent_domain_has_one_distinct_correct_code_per_card(admin, monkeypatch):
    monkeypatch.setattr(settings, "public_card_base_url", "https://go.flowqr.site")
    b, cards = new_batch(admin, 25, release=False)
    urls = [c["url"] for c in cards]
    assert len(set(urls)) == 25 and all(u.startswith("https://go.flowqr.site/q/") for u in urls)
    sheet = poster.poster_sheet_pdf([(c["card_code"], c["url"]) for c in cards])
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open(stream=sheet, filetype="pdf")
    assert doc.page_count == 7  # four to a page, 25 cards
    seen = []
    for page in doc:
        pix = page.get_pixmap(dpi=300)
        seen += zxing(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    assert sorted(seen) == sorted(urls)  # every card's own address appears exactly once on the sheets
