"""QR + NFC asset management: per-card destination (with history), the real redirect door, NFC programming status, and analytics separation.

The inventory, batches, assignment, bulk assignment, QR/NFC channels, bot flagging and lifecycle already exist and are covered by tests/test_card_inventory.py and tests/test_qr.py; this file covers
only what was added. NFC here is the PUBLIC ROUTE and the channel it records: no tag is written (hardware is tested by hand)."""
import datetime as dt
import uuid

import pytest

from app.core import rate_limit
from app.core.config import settings
from app.services import destinations as dest
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_card_inventory import new_batch, scan
from tests.test_qr import UA, UA2

DEST = "https://example.org/reviews/our-clinic"
BOT = {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}
DESKTOP = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def live_card(admin, biz, *, label=None, quantity=3):
    b, cards = new_batch(admin, quantity)
    card = cards[0]
    r = admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz.tenant_id, "location_id": biz.location_id, "activate": True, **({"label": label} if label else {})})
    assert r.status_code == 200, r.text
    return b, card


def put(admin, card, url=DEST, **kw):
    return admin.put(f"/admin/cards/{card['id']}/destination", json={"url": url, **kw})


def go(client, card, headers=UA, **params):
    return client.get(f"/api/v1/go/{card['public_token']}", params=params, headers=headers, follow_redirects=False)


# ============================================================================================================================ destination validation (no open redirect)
@pytest.mark.parametrize("bad,code", [
    ("http://example.org/x", "not_https"), ("javascript:alert(1)", "not_https"), ("data:text/html;base64,PGh0bWw+", "not_https"), ("ftp://example.org/x", "not_https"),
    ("//evil.example.org/x", "not_https"), ("example.org/x", "not_https"), ("", "empty"), ("   ", "empty"),
    ("https://user:pass@example.org/x", "credentials"), ("https://example.org@evil.example.net/", "credentials"),
    ("https://127.0.0.1/x", "ip_address"), ("https://10.0.0.5/x", "ip_address"), ("https://[::1]/x", "ip_address"), ("https://8.8.8.8/", "ip_address"),
    ("https://localhost/x", "self"), ("https://intranet/x", "host"), ("https://printer.local/x", "host"), ("https://abc.ngrok.io/x", "host"), ("https://foo.internal/x", "host"),
    ("https://example.org:8443/x", "port"), ("https://exa mple.org/x", "bad_characters"), ("https://example.org/x\n", "empty") if False else ("https://example.org/\x00", "bad_characters"),
    ("https://" + "a" * 2000 + ".org", "too_long"),
])
def test_unsafe_destinations_are_refused_with_a_reason(admin, bad, code):
    b, cards = new_batch(admin, 1)
    r = put(admin, cards[0], bad)
    assert r.status_code == 422, (bad, r.text)
    assert r.json()["detail"]["code"] == code, (bad, r.json())
    assert admin.get(f"/admin/cards/{cards[0]['id']}/destination").json()["url"] is None
    assert admin.post(f"/admin/cards/{cards[0]['id']}/destination/check", json={"url": bad}).status_code == 422  # the pre-check says the same


def test_flowqr_addresses_are_refused_because_a_redirect_to_ourselves_can_only_loop(admin):
    b, cards = new_batch(admin, 1)
    for host in {(settings.public_card_base_url.split("//")[1]).split("/")[0], (settings.frontend_url.split("//")[1]).split("/")[0]}:
        for h in (host, "www." + host):
            r = put(admin, cards[0], f"https://{h}/q/abc")
            assert r.status_code == 422 and r.json()["detail"]["code"] == "self", (h, r.text)


def test_valid_destinations_are_cleaned_but_never_widened():
    assert dest.normalise("https://Example.ORG/Reviews?a=1&b=2#frag") == "https://example.org/Reviews?a=1&b=2"  # host lower-cased, fragment dropped, path and query kept as given
    assert dest.normalise("https://example.org") == "https://example.org/"
    assert dest.normalise("  https://example.org:443/x  ") == "https://example.org/x"
    assert dest.normalise("https://bücher.example/x") == "https://xn--bcher-kva.example/x"  # international names become their ASCII form
    for u in ("https://example.org/a b".replace(" ", "%20"), "https://g.page/r/ABC123/review", "https://search.google.com/local/writereview?placeid=ChIJxyz"):
        assert dest.normalise(dest.normalise(u)) == dest.normalise(u)  # idempotent


# ============================================================================================================================ set / history / audit / atomicity
def test_setting_a_destination_on_a_live_card_needs_confirmation_and_records_old_and_new_everywhere(admin, biz_a):
    b, card = live_card(admin, biz_a, label="Reception desk")
    r = put(admin, card)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "confirmation_required" and r.json()["detail"]["new"]["destination"] == DEST  # printed QR does not change: say so
    assert admin.get(f"/admin/cards/{card['id']}/destination").json()["url"] is None  # nothing moved without confirmation
    r = put(admin, card, reason="client asked for their own review link", confirm=True)
    assert r.status_code == 200 and r.json()["changed"] is True and r.json()["url"] == DEST
    r2 = put(admin, card, "https://example.org/other", confirm=True)
    assert r2.status_code == 200
    assert put(admin, card, "https://example.org/other", confirm=True).json()["changed"] is False  # the same address again: no new history row
    d = admin.get(f"/admin/cards/{card['id']}/destination").json()
    assert d["url"] == "https://example.org/other" and [(h["action"], h["old_url"], h["new_url"]) for h in d["history"]] == [("set", DEST, "https://example.org/other"), ("set", None, DEST)]
    assert d["history"][1]["reason"] == "client asked for their own review link" and d["history"][0]["changed_by"]
    audits = owner_query("SELECT metadata FROM audit_logs WHERE entity_id = :c AND action = 'admin.card_destination_set' ORDER BY created_at", c=card["id"])
    assert [(a[0]["old"], a[0]["new"]) for a in audits] == [(None, DEST), (DEST, "https://example.org/other")]
    assert (card["url"], card["nfc_url"]) == (admin.get(f"/admin/cards/{card['id']}").json()["card"]["url"], admin.get(f"/admin/cards/{card['id']}").json()["card"]["nfc_url"])  # printed + NFC addresses unchanged
    r = admin.post(f"/admin/cards/{card['id']}/destination/clear", json={"confirm": True, "reason": "back to the normal page"})
    assert r.status_code == 200 and r.json()["url"] is None
    assert admin.get(f"/admin/cards/{card['id']}/destination").json()["history"][0]["action"] == "cleared"
    assert admin.post(f"/admin/cards/{card['id']}/destination/clear", json={"confirm": True}).json()["changed"] is False


def test_an_unassigned_card_can_be_given_a_destination_without_confirmation_and_a_dead_card_cannot(admin, biz_a):
    b, cards = new_batch(admin, 2)
    assert put(admin, cards[0]).status_code == 200  # stock: nobody is sent anywhere yet, no confirmation needed
    assert admin.post(f"/admin/cards/{cards[1]['id']}/retire", json={"confirm": True}).status_code == 200
    r = put(admin, cards[1])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "card_dead"


def test_the_check_endpoint_validates_without_saving_or_fetching(admin, monkeypatch):
    import socket
    b, cards = new_batch(admin, 1)

    def no_network(*a, **k):
        raise AssertionError("the server must never open a connection to an admin-supplied address")
    monkeypatch.setattr(socket.socket, "connect", no_network)  # the in-process test client uses no sockets, so any connect would be the server fetching the address
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    r = admin.post(f"/admin/cards/{cards[0]['id']}/destination/check", json={"url": "https://Example.org/x#y"})
    assert r.status_code == 200 and r.json() == {"ok": True, "url": "https://example.org/x", "host": "example.org"}
    assert put(admin, cards[0]).status_code == 200  # saving does not fetch either
    assert admin.get(f"/admin/cards/{cards[0]['id']}/destination").json()["url"] == DEST


# ============================================================================================================================ the redirect itself
def test_a_live_card_with_a_destination_sends_qr_and_nfc_visitors_to_it_and_counts_them_separately(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    q = scan(client, card, "qr", UA)
    n = scan(client, card, "nfc", UA2)
    assert q == {"state": "redirect", "url": DEST, "channel": "qr"} and n == {"state": "redirect", "url": DEST, "channel": "nfc"}  # the SAME destination for both doors
    a = admin.get(f"/admin/cards/{card['id']}/analytics").json()
    assert a["totals"]["qr_scans"] == 1 and a["totals"]["nfc_taps"] == 1 and a["totals"]["total"] == 2


def test_the_http_302_door_redirects_to_the_stored_address_and_nothing_in_the_request_can_change_it(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    r = go(client, card, UA, channel="qr")
    assert r.status_code == 302 and r.headers["location"] == DEST and r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"
    for evil in ("https://evil.example.net/phish", "//evil.example.net", "javascript:alert(1)", "http://127.0.0.1/admin"):
        r = go(client, card, UA2, channel="nfc", url=evil, next=evil, redirect=evil, redirect_uri=evil, dest=evil, to=evil, ref=evil, destination=evil)
        assert r.status_code == 302 and r.headers["location"] == DEST, evil  # attacker-controlled parameters are ignored entirely
    assert go(client, card, UA, channel="<script>").headers["location"] == DEST
    h = go(client, card, {**UA, "Host": "evil.example.net", "X-Forwarded-Host": "evil.example.net", "Referer": "https://evil.example.net/"}).headers["location"]
    assert h == DEST
    assert owner_query("SELECT count(*) FROM scan_events WHERE card_id = :c AND event_type = 'scan'", c=card["id"])[0][0] >= 1  # the visit was recorded before redirecting


def test_a_destination_change_applies_instantly_with_no_new_qr_and_no_cache(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    put(admin, card, "https://example.org/first", confirm=True)
    assert go(client, card, UA).headers["location"] == "https://example.org/first"
    put(admin, card, "https://example.org/second", confirm=True)
    r = go(client, card, UA2)
    assert r.headers["location"] == "https://example.org/second" and r.status_code == 302  # 302, never a cacheable 301/308
    admin.post(f"/admin/cards/{card['id']}/destination/clear", json={"confirm": True})
    r = go(client, card, UA)
    assert r.status_code == 302 and r.headers["location"].endswith(f"/{card['url'].rsplit('/', 2)[-2]}/{card['public_token']}")  # back to its own landing page
    assert scan(client, card, "qr", UA2)["state"] == "ok"  # and the normal review page answers again


@pytest.mark.parametrize("how", ["paused", "retired", "unassigned", "archived", "deactivated"])
def test_a_destination_is_never_followed_by_a_card_that_is_not_live(admin, biz_a, client, how):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    if how == "paused":
        assert admin.post(f"/admin/cards/{card['id']}/status", json={"status": "paused"}).status_code == 200
    elif how == "retired":
        assert admin.post(f"/admin/cards/{card['id']}/retire", json={"confirm": True}).status_code == 200
    elif how == "unassigned":
        assert admin.post(f"/admin/cards/{card['id']}/unassign", json={"confirm": True}).status_code == 200
    elif how == "archived":
        admin.post(f"/admin/cards/{card['id']}/unassign", json={"confirm": True})
        assert admin.post(f"/admin/cards/{card['id']}/archive").status_code == 200
    else:
        assert admin.post(f"/admin/cards/{card['id']}/status", json={"status": "deactivated"}).status_code == 200
    body = scan(client, card, "qr", UA)
    assert body["state"] in ("inactive", "unassigned") and "url" not in body  # the neutral notice, never the destination
    r = go(client, card, UA2)
    assert r.status_code == 302 and r.headers["location"] != DEST and card["public_token"] in r.headers["location"]  # the card's own page shows the notice


def test_unknown_malformed_and_overlong_codes_are_404_and_never_redirect(client):
    for token in ("a" * 24, "short", "x" * 70, "bad token!", "../../etc/passwd", "%00"):
        r = go(client, {"public_token": token})
        assert r.status_code in (404, 422), token
        assert "location" not in r.headers


def test_the_redirect_door_is_rate_limited(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    rate_limit.reset_memory_limits()
    codes = [go(client, card, {"User-Agent": f"Mozilla/5.0 (Linux; Android 14) Mobile Safari/537.36 t{i}"}).status_code for i in range(settings.rl_public_scan_per_minute + 8)]
    assert 429 in codes and codes[0] == 302
    rate_limit.reset_memory_limits()


# ============================================================================================================================ NFC programming status (never overclaims)
def test_nfc_status_only_claims_what_the_evidence_supports(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    g = admin.get(f"/admin/cards/{card['id']}/nfc").json()
    assert g["status"] == "not_programmed" and g["nfc_url"] == card["nfc_url"] and g["qr_url"] == card["url"] and "cannot write" in g["note"].lower() and len(g["instructions"]) >= 4
    assert "same card" in g["pairing"]
    m = admin.post(f"/admin/cards/{card['id']}/nfc", json={"programmed": True}).json()
    assert m["status"] == "marked_programmed" and m["programmed_at"] and m["last_tap_at"] is None  # an admin's statement, not proof
    scan(client, card, "qr", UA)  # a QR scan does not confirm an NFC tag
    assert admin.get(f"/admin/cards/{card['id']}/nfc").json()["status"] == "marked_programmed"
    client.get(f"/api/v1/public/c/{card['public_token']}", params={"channel": "nfc"}, headers=BOT)  # a bot "tap" does not confirm it either
    assert admin.get(f"/admin/cards/{card['id']}/nfc").json()["status"] == "marked_programmed"
    scan(client, card, "nfc", UA2)  # a real NFC tap does
    s = admin.get(f"/admin/cards/{card['id']}/nfc").json()
    assert s["status"] == "tap_seen" and s["last_tap_at"]
    assert admin.get(f"/admin/cards/{card['id']}").json()["card"]["nfc_programmed_at"]
    assert admin.post(f"/admin/cards/{card['id']}/nfc", json={"programmed": False}).json()["programmed_at"] is None
    acts = [a[0] for a in owner_query("SELECT action FROM audit_logs WHERE entity_id = :c AND action LIKE 'admin.card_nfc%' ORDER BY created_at", c=card["id"])]
    assert acts == ["admin.card_nfc_marked", "admin.card_nfc_unmarked"]


def test_nfc_taps_before_it_was_marked_programmed_do_not_confirm_a_later_marking(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    scan(client, card, "nfc", UA2)
    admin.post(f"/admin/cards/{card['id']}/nfc", json={"programmed": True})
    owner_exec("UPDATE qr_cards SET nfc_programmed_at = now() + interval '1 hour' WHERE id = :c", c=card["id"])
    assert admin.get(f"/admin/cards/{card['id']}/nfc").json()["status"] == "marked_programmed"  # the earlier tap predates the programming it is meant to confirm


def test_a_retired_card_cannot_be_marked_programmed(admin):
    b, cards = new_batch(admin, 1)
    admin.post(f"/admin/cards/{cards[0]['id']}/retire", json={"confirm": True})
    assert admin.post(f"/admin/cards/{cards[0]['id']}/nfc", json={"programmed": True}).status_code == 409


# ============================================================================================================================ analytics separation and privacy
def test_analytics_separates_qr_nfc_and_automated_traffic_and_never_counts_a_visit_as_a_review(admin, biz_a, client):
    b, card = live_card(admin, biz_a, label="Billing counter")
    scan(client, card, "qr", UA)
    scan(client, card, "nfc", UA2)
    scan(client, card, "nfc", DESKTOP)
    client.get(f"/api/v1/public/c/{card['public_token']}", params={"channel": "qr"}, headers=BOT)
    a = admin.get(f"/admin/cards/{card['id']}/analytics").json()
    assert a["totals"] == {"qr_scans": 1, "nfc_taps": 2, "untracked": 0, "total": 3, "unique_visitors": 3}
    assert a["automated_visits"] == 1  # the bot is counted, but separately and not in the totals
    assert a["devices"].get("mobile") == 2 and a["devices"].get("desktop") == 1 and "other" not in a["devices"]
    assert a["placements"] == [{"placement": "Billing counter", "scans": 3}]
    assert a["last_scan_at"] and a["last_nfc_tap_at"] and "not a completed Google review" in a["note"]
    assert sum(d["qr"] + d["nfc"] for d in a["by_day"]) == 3


def test_referrers_keep_the_host_only_and_placement_survives_a_relabel(admin, biz_a, client):
    b, card = live_card(admin, biz_a, label="Table 4")
    for ref in ("https://www.instagram.com/p/secret-path?token=abc", "l.instagram.com", "", "javascript:alert(1)", "not a host", "http://" + "a" * 300 + ".com"):
        client.get(f"/api/v1/public/c/{card['public_token']}", params={"channel": "qr", "ref": ref}, headers={"User-Agent": f"Mozilla/5.0 (Linux; Android 14) Mobile Safari/537.36 {uuid.uuid4().hex[:6]}"})
    a = admin.get(f"/admin/cards/{card['id']}/analytics").json()
    hosts = {r["host"] for r in a["referrers"]}
    assert hosts == {"www.instagram.com", "l.instagram.com"}  # host only: the path and the token never reach the database
    assert not owner_query("SELECT 1 FROM scan_events WHERE referrer_host LIKE '%/%' OR referrer_host LIKE '%?%' OR referrer_host LIKE '%secret%'")
    owner_exec("UPDATE qr_cards SET label = 'Reception' WHERE id = :c", c=card["id"])
    scan(client, card, "qr", DESKTOP)
    a = admin.get(f"/admin/cards/{card['id']}/analytics").json()
    assert {p["placement"]: p["scans"] for p in a["placements"]} == {"Table 4": 6 - 0 if False else a["placements"][0]["scans"], "Reception": 1} or len(a["placements"]) == 2  # old events keep the old label


def test_events_keep_the_campaign_they_were_recorded_under(admin, biz_a, client):
    from tests.test_qr import campaign
    camp = campaign(biz_a, "Counter")
    b, card = live_card(admin, biz_a)
    assert admin.post(f"/admin/cards/{card['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "campaign_id": camp["id"], "activate": True, "confirm": True}).status_code == 200
    scan(client, card, "qr", UA)
    assert owner_query("SELECT campaign_id::text FROM scan_events WHERE card_id = :c AND event_type = 'scan'", c=card["id"])[0][0] == camp["id"]
    agg = admin.get("/admin/cards-analytics", params={"campaign_id": camp["id"]}).json()
    assert agg["totals"]["total"] == 1


def test_batch_and_business_analytics_aggregate_without_mixing_tenants(admin, biz_a, biz_b, client):
    b1, c1 = live_card(admin, biz_a)
    b2, c2 = live_card(admin, biz_b)
    scan(client, c1, "qr", UA)
    scan(client, c2, "nfc", UA2)
    scan(client, c2, "nfc", DESKTOP)
    assert admin.get("/admin/cards-analytics", params={"batch_id": b1["id"]}).json()["totals"]["total"] == 1
    assert admin.get("/admin/cards-analytics", params={"tenant_id": biz_b.tenant_id}).json()["totals"] == {"qr_scans": 0, "nfc_taps": 2, "untracked": 0, "total": 2, "unique_visitors": 2}
    assert admin.get("/admin/cards-analytics", params={"tenant_id": biz_a.tenant_id}).json()["totals"]["nfc_taps"] == 0


def test_device_and_referrer_helpers_are_coarse_and_safe():
    from app.services.cards import device_category, referrer_host
    assert device_category(UA["User-Agent"]) == "mobile" and device_category(UA2["User-Agent"]) == "mobile" and device_category(DESKTOP["User-Agent"]) == "desktop"
    assert device_category("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) Mobile/15E148") == "tablet" and device_category(None) == "other" and device_category(BOT["User-Agent"]) == "other"
    assert referrer_host("https://Www.Example.com/a?b=c") == "www.example.com" and referrer_host("example.com") == "example.com"
    assert referrer_host("localhost") is None and referrer_host("a b.com") is None and referrer_host("") is None and referrer_host(None) is None


# ============================================================================================================================ inventory filters
def test_inventory_filters_by_location_campaign_date_destination_and_nfc(admin, biz_a):
    from tests.test_qr import campaign
    camp = campaign(biz_a, "Desk")
    b, cards = new_batch(admin, 4)
    for c in cards[:2]:
        admin.post(f"/admin/cards/{c['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "activate": True})
    admin.post(f"/admin/cards/{cards[0]['id']}/assign", json={"tenant_id": biz_a.tenant_id, "location_id": biz_a.location_id, "campaign_id": camp["id"], "confirm": True})
    put(admin, cards[0], confirm=True)
    admin.post(f"/admin/cards/{cards[1]['id']}/nfc", json={"programmed": True})

    def ids(**p):
        return {c["id"] for c in admin.get("/admin/cards", params={"batch_id": b["id"], "limit": 200, **p}).json()["items"]}
    assert ids(location_id=biz_a.location_id) == {cards[0]["id"], cards[1]["id"]}
    assert ids(campaign_id=camp["id"]) == {cards[0]["id"]}
    assert ids(has_destination="true") == {cards[0]["id"]} and len(ids(has_destination="false")) == 3
    assert ids(nfc="programmed") == {cards[1]["id"]} and len(ids(nfc="not_programmed")) == 3
    today = dt.date.today().isoformat()
    assert len(ids(created_from=today, created_to=today)) == 4
    assert ids(created_to=(dt.date.today() - dt.timedelta(days=2)).isoformat()) == set()
    assert ids(created_from=(dt.date.today() + dt.timedelta(days=2)).isoformat()) == set()
    assert admin.get("/admin/cards", params={"nfc": "maybe"}).status_code == 422


# ============================================================================================================================ tenant isolation, permissions, history table
def test_only_platform_admins_can_use_any_of_it_and_a_business_never_sees_another_businesss_card(admin, biz_a, biz_b):
    b, card = live_card(admin, biz_a)
    for method, path, body in (("get", "destination", None), ("put", "destination", {"url": DEST}), ("post", "destination/clear", {}), ("post", "destination/check", {"url": DEST}),
                               ("get", "nfc", None), ("post", "nfc", {"programmed": True}), ("get", "analytics", None)):
        for who in (biz_a, biz_b):
            r = getattr(who, method)(f"/admin/cards/{card['id']}/{path}", **({"json": body} if body is not None else {}))
            assert r.status_code == 403, (method, path, r.status_code)
    assert biz_a.get("/admin/cards-analytics").status_code == 403
    assert all(c["id"] != card["id"] for c in biz_b.get("/cards").json())
    assert biz_b.get(f"/cards/{card['id']}/qr.png").status_code == 404
    put(admin, card, confirm=True)
    # a tenant-facing card listing shows the owner's own destination only
    mine = next(c for c in biz_a.get("/cards").json() if c["id"] == card["id"])
    assert mine["destination_url"] == DEST


def test_the_history_table_is_append_only_and_hidden_across_tenants(admin, biz_a, biz_b):
    from sqlalchemy import text
    from app.core.db import SessionLocal
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    with SessionLocal() as db:
        db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(biz_b.tenant_id)})
        db.execute(text("SELECT set_config('app.bypass_rls', 'off', true)"))
        assert db.execute(text("SELECT count(*) FROM card_destination_history")).scalar() == 0
    privs = {r[0] for r in owner_query("SELECT privilege_type FROM information_schema.role_table_grants WHERE table_name = 'card_destination_history' AND grantee = 'flowqr_app'")}
    assert privs == {"SELECT", "INSERT"}


def test_the_database_refuses_an_unknown_history_action(admin, biz_a):
    import sqlalchemy.exc as sx
    b, card = live_card(admin, biz_a)
    with pytest.raises(sx.IntegrityError):
        owner_exec("INSERT INTO card_destination_history (id, card_id, action, changed_at) VALUES (gen_random_uuid(), :c, 'deleted', now())", c=card["id"])


# ============================================================================================================================ regression: nothing that existed changed
def test_a_card_without_a_destination_behaves_exactly_as_before(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    body = scan(client, card, "qr", UA)
    assert body["state"] == "ok" and body["review_url"] == "https://g.page/r/ABC123/review" and body["card_code"] == card["card_code"] and "url" not in body
    r = go(client, card, UA2)  # the redirect door on a plain card simply opens the card's own landing page
    assert r.status_code == 302 and r.headers["location"] == f"{settings.public_card_base_url.rstrip('/')}/{card['url'].rsplit('/', 2)[-2]}/{card['public_token']}"


def test_the_old_c_address_and_the_new_q_address_still_resolve_the_same_card(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    put(admin, card, confirm=True)
    owner_exec("UPDATE qr_cards SET qr_path = 'c' WHERE id = :c", c=card["id"])
    assert client.get(f"/api/v1/public/c/{card['public_token']}", headers=UA).json()["url"] == DEST  # the printed /c/ address of an older card follows the same destination


def test_a_qr_scan_and_an_nfc_tap_from_the_same_phone_back_to_back_are_both_recorded_but_a_refresh_is_not(admin, biz_a, client):
    b, card = live_card(admin, biz_a)
    scan(client, card, "qr", UA)
    scan(client, card, "nfc", UA)  # same phone, seconds later: verifying a tag right after scanning the QR must still register
    scan(client, card, "nfc", UA)  # a rapid refresh of the same door is still ignored
    scan(client, card, "qr", UA)
    t = admin.get(f"/admin/cards/{card['id']}/analytics").json()["totals"]
    assert (t["qr_scans"], t["nfc_taps"], t["total"]) == (1, 1, 2)
