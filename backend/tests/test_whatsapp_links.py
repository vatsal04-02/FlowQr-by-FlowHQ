"""WhatsApp click tracking (Phase 3 of the second round, Pro only): tracked review links and "link clicked".

A tracked link is a long random token that leads to ONE fixed destination. These tests are about what it must never do: redirect anywhere else, count a bot, a preview or a double tap, store who clicked,
outlive its business, work for a plan that does not include it, or ever be described as a review left. Mock Meta only; no real number, account or message is involved."""
import json
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import links as links_api
from app.core.config import settings
from app.core.db import system_session
from app.main import app
from app.services.whatsapp import links
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_whatsapp import OWNER, add_contact, grant_addon, svc_db, wa  # noqa: F401 - fixtures
from tests.test_whatsapp_messaging import ready_biz, tick, wm  # noqa: F401 - fixtures

BROWSER = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
DEST = "https://g.page/r/ABC123/review"


def hit_link(token, ua=BROWSER, method="GET", params=None):
    with TestClient(app, base_url="http://testserver") as c:
        headers = {"User-Agent": ua} if ua is not None else {}
        return c.request(method, f"/api/v1/l/{token}", headers=headers, params=params, follow_redirects=False)


def phone(n):
    return f"98765 {n:05d}"


def tracked(admin, wm, name, tier="whatsapp_pro", track=True, fresh=False, n=1):
    """A business whose review request went out, with the link counted when `track` is on (and the plan allows it)."""
    biz = ready_biz(admin, name, tier=tier, wm=wm, fresh=fresh)
    r = biz.put("/whatsapp/automations/review_followup", json={"status": "on", "config": {"delay_minutes": 5, "track_clicks": track}})
    assert r.status_code == 200, r.text
    c = add_contact(biz, phone(70000 + n), name="Meera Shah", utility=True, **OWNER)
    assert biz.post(f"/whatsapp/contacts/{c['id']}/visit").json()["scheduled"] is True
    assert tick(biz.tenant_id, 30)["automations"]["sent"] == 1
    return biz, c


def token_of(biz):
    return owner_query("SELECT token FROM whatsapp_links WHERE tenant_id = :t ORDER BY created_at DESC", t=biz.tenant_id)[0][0]


def clicks(biz):
    return owner_query("SELECT count(*) FROM whatsapp_link_clicks WHERE tenant_id = :t", t=biz.tenant_id)[0][0]


# ===================================================================== the link itself
def test_the_review_request_carries_a_tracked_link_that_leads_to_the_same_review_page(wm, admin):
    biz, c = tracked(admin, wm, "Link Clinic")
    token = token_of(biz)
    sent = [p["text"] for p in wm.sent[-1]["template"]["components"][0]["parameters"]]
    assert sent == ["Meera", "Link Clinic", f"{settings.whatsapp_link_base_url}/{token}"] and sent[2].startswith("https://api.flowqr.site/api/v1/l/")
    r = hit_link(token)
    assert r.status_code == 302 and r.headers["location"] == DEST  # the business's own review page
    link = owner_query("SELECT destination, message_id, contact_id FROM whatsapp_links WHERE token = :t", t=token)[0]
    msg = owner_query("SELECT id FROM whatsapp_messages WHERE tenant_id = :t", t=biz.tenant_id)[0][0]
    assert link[0] == DEST and link[1] == msg and str(link[2]) == c["id"]


def test_tokens_are_long_random_and_url_safe(wm, admin):
    seen = {links.new_token() for _ in range(200)}
    assert len(seen) == 200 and all(len(t) >= 43 and re.fullmatch(r"[A-Za-z0-9_-]+", t) for t in seen)
    biz, _ = tracked(admin, wm, "Token Clinic")
    assert len(token_of(biz)) >= 43 and links.TOKEN_RE.fullmatch(token_of(biz))


def test_the_destination_is_fixed_and_the_route_takes_no_url_parameter(wm, admin):
    biz, _ = tracked(admin, wm, "Not Open")
    token = token_of(biz)
    for params in ({"url": "https://evil.example"}, {"to": "https://evil.example"}, {"redirect": "//evil.example"}, {"next": "https://evil.example"}, {"destination": "https://evil.example", "u": "x", "r": "y"}):
        r = hit_link(token, params=params)
        assert r.status_code == 302 and r.headers["location"] == DEST, params  # whatever the request says, it goes to the stored destination
    params = app.openapi()["paths"]["/api/v1/l/{token}"]["get"].get("parameters", [])
    assert [(p["name"], p["in"]) for p in params] == [("token", "path")]  # no query parameter, no body: nothing in a request can choose where it goes
    assert "requestBody" not in app.openapi()["paths"]["/api/v1/l/{token}"]["get"]
    for bad in ("short", "x" * 100, "../../etc/passwd", "a" * 43 + "%00", token[:-1] + "!", token.upper() if token.upper() != token else "Z" * 43):
        assert hit_link(bad).status_code == 404, bad
    assert hit_link(links.new_token()).status_code == 404  # a well-formed token nobody holds
    assert hit_link(token, method="POST").status_code == 405
    r = hit_link(token)
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"


def test_a_destination_that_is_not_a_plain_https_address_is_never_used():
    for bad in (None, "", "http://g.page/r/x", "javascript:alert(1)", "//evil.example", "https://exa mple.com", "https://" + "a" * 600, "ftp://x.example/y", "https://"):
        assert links.safe_destination(bad) is None, bad
    assert links.safe_destination(DEST) == DEST


def test_a_retry_of_the_same_send_reuses_its_link(wm, admin):
    biz = ready_biz(admin, "Retry Link")
    with svc_db(biz.tenant_id) as db:
        tid = uuid.UUID(biz.tenant_id)
        a = links.get_or_create(db, tid, DEST, "run:abc", None)
        b = links.get_or_create(db, tid, DEST, "run:abc", None)
        c = links.get_or_create(db, tid, DEST, "run:other", None)
        db.commit()
        assert a.token == b.token and a.id == b.id and a.token != c.token


# ===================================================================== Pro only
def test_click_counting_is_pro_only(wm, admin):
    for tier in ("whatsapp_starter", "whatsapp_growth"):
        biz = ready_biz(admin, f"No Count {tier}", tier=tier, wm=wm, fresh=True)
        r = biz.put("/whatsapp/automations/review_followup", json={"status": "on", "config": {"track_clicks": True}})
        assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_required", tier
        ok = biz.put("/whatsapp/automations/review_followup", json={"status": "on", "config": {"track_clicks": False}})
        assert ok.status_code == 200
    pro = ready_biz(admin, "Count Pro", tier="whatsapp_pro", wm=wm, fresh=True)
    assert pro.put("/whatsapp/automations/review_followup", json={"status": "on", "config": {"track_clicks": True}}).status_code == 200


def test_without_counting_the_review_request_carries_the_plain_review_link(wm, admin):
    biz, _ = tracked(admin, wm, "Plain Link", tier="whatsapp_growth", track=False)
    assert [p["text"] for p in wm.sent[-1]["template"]["components"][0]["parameters"]][2] == DEST
    assert owner_query("SELECT count(*) FROM whatsapp_links WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0
    pro_off, _ = tracked(admin, wm, "Pro Not Asked", tier="whatsapp_pro", track=False, fresh=True)
    assert [p["text"] for p in wm.sent[-1]["template"]["components"][0]["parameters"]][2] == DEST  # Pro has to turn it on: it is a choice, not a default
    assert pro_off


def test_after_a_downgrade_the_link_still_works_but_nothing_new_is_counted(wm, admin):
    biz, _ = tracked(admin, wm, "Downgraded Link")
    token = token_of(biz)
    assert hit_link(token).status_code == 302 and clicks(biz) == 1
    assert admin.put(f"/admin/tenants/{biz.tenant_id}/whatsapp-addon", json={"addon_key": "whatsapp_growth", "reason": "Plan changed to Growth by the owner"}).status_code == 200
    owner_exec("UPDATE whatsapp_link_clicks SET clicked_at = clicked_at - interval '5 minutes' WHERE tenant_id = :t", t=biz.tenant_id)
    r = hit_link(token)
    assert r.status_code == 302 and r.headers["location"] == DEST and clicks(biz) == 1  # the customer still gets to the page; no click is recorded
    assert biz.get("/whatsapp/usage").json()["links"]["enabled"] is False


def test_nothing_is_counted_while_whatsapp_is_off(wm, admin, monkeypatch):
    biz, _ = tracked(admin, wm, "Off Link")
    monkeypatch.setattr(settings, "whatsapp_enabled", False)
    assert hit_link(token_of(biz)).status_code == 302 and clicks(biz) == 0


# ===================================================================== what counts as a click
def test_bots_previews_scanners_and_head_requests_never_count(wm, admin):
    biz, _ = tracked(admin, wm, "Bot Filter")
    token = token_of(biz)
    agents = ["WhatsApp/2.23.20.0 A", "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", "curl/8.4.0",
              "python-requests/2.31.0", "Slackbot-LinkExpanding 1.0", "TelegramBot (like TwitterBot)", "Mozilla/5.0 (compatible; bingbot/2.0)", "Mozilla/5.0 HeadlessChrome/120.0.0.0 Safari/537.36",
              "Mozilla/5.0 (Windows NT 10.0) Microsoft Office Safelinks Protection", "Mozilla/5.0 (compatible; Proofpoint URL Defense)", "Mozilla/5.0 (compatible; Mimecast)", "Go-http-client/2.0",
              "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit Mobile Link Preview", "okhttp/4.9.0"]
    for ua in agents:
        r = hit_link(token, ua=ua)
        assert r.status_code == 302 and r.headers["location"] == DEST, ua  # they still reach the page
    assert clicks(biz) == 0
    for nameless in (None, "", "   "):  # a request with no browser name at all is a script, not a person
        assert links.is_bot(nameless) is True
    assert links.is_bot(BROWSER) is False and links.is_bot("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1") is False
    head = hit_link(token, method="HEAD")
    assert head.status_code == 302 and head.headers["location"] == DEST and clicks(biz) == 0  # a HEAD is never a click, even with a browser's name
    assert hit_link(token).status_code == 302 and clicks(biz) == 1  # a real browser counts


def test_repeat_opens_within_60_seconds_count_once(wm, admin):
    biz, _ = tracked(admin, wm, "Dedupe")
    token = token_of(biz)
    assert settings.whatsapp_link_dedupe_seconds == 60
    for _ in range(5):
        assert hit_link(token).status_code == 302
    assert clicks(biz) == 1
    owner_exec("UPDATE whatsapp_link_clicks SET clicked_at = clicked_at - interval '59 seconds' WHERE tenant_id = :t", t=biz.tenant_id)
    hit_link(token)
    assert clicks(biz) == 1  # 59 seconds on: still the same open
    owner_exec("UPDATE whatsapp_link_clicks SET clicked_at = clicked_at - interval '2 seconds' WHERE tenant_id = :t", t=biz.tenant_id)
    hit_link(token)
    assert clicks(biz) == 2  # past 60 seconds: a new click
    other, _ = tracked(admin, wm, "Dedupe Other", fresh=True, n=2)
    hit_link(token_of(other))
    assert clicks(other) == 1  # each link has its own window


def test_a_click_records_the_link_the_customer_the_message_and_the_time_and_nothing_else(wm, admin):
    biz, c = tracked(admin, wm, "Nothing Else")
    token = token_of(biz)
    ua = "Mozilla/5.0 (Linux; Android 14) UniqueBrowserMarker/9.9 Chrome/120.0 Mobile Safari/537.36"
    hit_link(token, ua=ua)
    cols = {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = 'whatsapp_link_clicks'")}
    assert cols == {"id", "tenant_id", "link_id", "contact_id", "message_id", "clicked_at"}  # no address, no browser, no place
    lcols = {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = 'whatsapp_links'")}
    assert lcols == {"id", "tenant_id", "token", "destination", "idem_key", "message_id", "contact_id", "created_at"}
    stored = " ".join(r[0] for r in owner_query("SELECT row_to_json(t)::text FROM whatsapp_link_clicks t")) + " ".join(r[0] for r in owner_query("SELECT row_to_json(t)::text FROM whatsapp_links t"))
    assert "UniqueBrowserMarker" not in stored and "testclient" not in stored and "127.0.0.1" not in stored and "Mozilla" not in stored
    row = owner_query("SELECT contact_id, message_id FROM whatsapp_link_clicks WHERE tenant_id = :t", t=biz.tenant_id)[0]
    assert str(row[0]) == c["id"] and row[1] is not None
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND metadata::text LIKE '%UniqueBrowserMarker%'", t=biz.tenant_id)[0][0] == 0


# ===================================================================== rate limits that never keep the address
def test_the_redirect_is_rate_limited_per_visitor_and_per_link(wm, admin, monkeypatch):
    biz, _ = tracked(admin, wm, "Rate Limit")
    token = token_of(biz)
    other, _ = tracked(admin, wm, "Rate Limit Two", fresh=True, n=3)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rl_link_per_ip_per_minute", 4)
    monkeypatch.setattr(settings, "rl_link_per_token_per_minute", 100)
    codes = [hit_link(token, ua=f"{BROWSER} v{i}").status_code for i in range(6)]
    assert codes[:4] == [302] * 4 and codes[4:] == [429, 429]  # per visitor
    r = hit_link(token)
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    monkeypatch.setattr(settings, "rl_link_per_ip_per_minute", 1000)
    monkeypatch.setattr(settings, "rl_link_per_token_per_minute", 2)
    t2 = token_of(other)
    codes = [hit_link(t2).status_code for _ in range(4)]
    assert codes == [302, 302, 429, 429]  # per link
    assert hit_link(token_of(biz)).status_code in (302, 429)  # another link has its own count (its first minute may already be spent by the section above)


def test_the_rate_limit_counters_never_hold_the_address_or_the_token(wm, admin, monkeypatch):
    biz, _ = tracked(admin, wm, "Hashed Keys")
    token = token_of(biz)
    keys = []
    monkeypatch.setattr(links_api, "hit", lambda key, limit, window: keys.append(key) or True)
    hit_link(token)
    assert len(keys) == 2 and all(k.startswith("wa-link-") for k in keys)
    assert all("testclient" not in k and "127.0.0.1" not in k and token not in k for k in keys)
    assert all(re.fullmatch(r"wa-link-(ip|token):[0-9a-f]{24}", k) for k in keys)
    assert keys[0] != keys[1]


# ===================================================================== deletion
def test_deleting_the_customer_deletes_their_clicks_but_the_link_still_leads_to_its_page(wm, admin):
    biz, c = tracked(admin, wm, "Delete Customer")
    token = token_of(biz)
    hit_link(token)
    assert clicks(biz) == 1
    assert biz.delete(f"/whatsapp/contacts/{c['id']}").status_code == 204
    assert clicks(biz) == 0  # their clicks went with them
    row = owner_query("SELECT contact_id, destination FROM whatsapp_links WHERE token = :t", t=token)[0]
    assert row[0] is None and row[1] == DEST  # the link stays, with no customer on it
    r = hit_link(token)
    assert r.status_code == 302 and r.headers["location"] == DEST  # still works for whoever holds it
    assert clicks(biz) == 0  # and counts nobody


def test_deleting_the_message_does_not_break_the_link(wm, admin):
    biz, _ = tracked(admin, wm, "Delete Message")
    token = token_of(biz)
    owner_exec("DELETE FROM whatsapp_messages WHERE tenant_id = :t", t=biz.tenant_id)
    assert owner_query("SELECT message_id FROM whatsapp_links WHERE token = :t", t=token)[0][0] is None
    r = hit_link(token)
    assert r.status_code == 302 and r.headers["location"] == DEST


def test_a_link_dies_only_with_its_business(wm, admin):
    biz, _ = tracked(admin, wm, "Delete Business")
    token = token_of(biz)
    hit_link(token)
    assert hit_link(token).status_code == 302 and clicks(biz) == 1
    db = system_session()
    try:
        from sqlalchemy import text
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": biz.tenant_id})
        db.commit()
    finally:
        db.close()
    for t in ("whatsapp_links", "whatsapp_link_clicks"):
        assert owner_query(f"SELECT count(*) FROM {t} WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0, t
    assert hit_link(token).status_code == 404


def test_the_account_export_carries_the_links_and_clicks(wm, admin):
    import io
    import zipfile
    biz, _ = tracked(admin, wm, "Export Links")
    hit_link(token_of(biz))
    z = zipfile.ZipFile(io.BytesIO(biz.get("/account/export").content))
    assert {"whatsapp_links.json", "whatsapp_link_clicks.json"} <= set(z.namelist())
    assert len(json.loads(z.read("whatsapp_link_clicks.json"))) == 1 and json.loads(z.read("whatsapp_links.json"))[0]["destination"] == DEST


def test_a_business_sees_only_its_own_links_and_clicks(wm, admin):
    a, _ = tracked(admin, wm, "Iso Links A")
    b, _ = tracked(admin, wm, "Iso Links B", fresh=True, n=4)
    hit_link(token_of(a))
    from sqlalchemy import text

    from app.core.db import SessionLocal, set_rls_context
    for table in ("whatsapp_links", "whatsapp_link_clicks"):
        assert owner_query("SELECT relforcerowsecurity FROM pg_class WHERE relname = :t", t=table)[0][0] is True
        with SessionLocal() as db:
            set_rls_context(db, tenant_id=uuid.UUID(b.tenant_id))
            assert db.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": a.tenant_id}).scalar() == 0, table
    assert b.get("/whatsapp/usage").json()["links"]["link_clicked"] == 0 and a.get("/whatsapp/usage").json()["links"]["link_clicked"] == 1


# ===================================================================== what the owner sees: "link clicked", never "review left"
def test_the_owner_sees_link_clicked_and_never_review_left(wm, admin):
    biz, _ = tracked(admin, wm, "Words Links")
    hit_link(token_of(biz))
    u = biz.get("/whatsapp/usage").json()["links"]
    assert u["enabled"] is True and u["link_clicked"] == 1 and u["messages_with_a_click"] == 1 and len(u["by_day"]) == 1 and u["by_day"][0]["clicks"] == 1
    assert "does not mean a review was left" in u["note"] and "security scanners" in u["note"]  # honest about previews and scanners
    act = biz.get("/whatsapp/messages").json()["items"]
    assert act[0]["link_clicked_at"] is not None
    blob = json.dumps({"usage": biz.get("/whatsapp/usage").json(), "messages": act}, default=str).lower()
    assert "link_clicked" in blob
    assert not re.search(r"review_left|review left|left a review|reviewed|rating|stars|converted|sale|revenue", blob.replace("does not mean a review was left", ""))


def test_the_message_export_has_a_link_clicked_column_and_only_the_last_four_digits(wm, admin):
    biz, c = tracked(admin, wm, "Export Column")
    c2 = add_contact(biz, phone(70099), name="Ravi", utility=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{c2['id']}/visit")
    tick(biz.tenant_id, 120)
    hit_link(owner_query("SELECT l.token FROM whatsapp_links l JOIN whatsapp_messages m ON m.id = l.message_id WHERE l.tenant_id = :t AND l.contact_id = :c", t=biz.tenant_id, c=c["id"])[0][0])
    r = biz.get("/whatsapp/messages/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and r.headers["cache-control"] == "no-store"
    lines = r.text.splitlines()
    assert lines[0] == "sent_at,customer,phone_last4,category,status,delivered_at,read_at,link_clicked,link_clicked_at"
    rows = {ln.split(",")[1]: ln.split(",") for ln in lines[1:]}
    assert rows["Meera Shah"][7] == "yes" and rows["Meera Shah"][8] != "" and rows["Ravi"][7] == "no" and rows["Ravi"][8] == ""
    assert "98765" not in r.text and "+9198765" not in r.text and rows["Meera Shah"][2] == "0001" and rows["Ravi"][2] == "0099"
    assert "review" not in lines[0].lower()
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.messages_export'", t=biz.tenant_id)[0][0] == 1


def test_the_message_export_is_for_owners_and_admins_only(wm, admin):
    biz, _ = tracked(admin, wm, "Export Roles")
    assert biz.get("/whatsapp/messages/export").status_code == 200
    anon = TestClient(app, base_url="http://testserver")
    assert anon.get("/api/v1/whatsapp/messages/export").status_code in (401, 403)
    off = make_business("Export Off")
    r = off.get("/whatsapp/messages/export")
    assert r.status_code == 200 and r.text.splitlines() == ["sent_at,customer,phone_last4,category,status,delivered_at,read_at,link_clicked,link_clicked_at"]  # a business with nothing sent gets only the header, never anyone else's rows


# ===================================================================== shape
def test_the_route_is_in_the_manifest_and_the_tables_exist_with_the_right_rules(wm):
    lines = {(m, p): k for k, m, p in (ln.split("\t") for ln in open("tests/route_access_manifest.txt", encoding="utf-8").read().splitlines() if "/api/v1/l/" in ln or "messages/export" in ln)}
    assert lines == {("GET", "/api/v1/l/{token}"): "public-bypass-db", ("GET", "/api/v1/whatsapp/messages/export"): "role-admin"}
    role = settings.database_url.split("//")[1].split(":")[0]
    for t in ("whatsapp_links", "whatsapp_link_clicks"):
        assert owner_query("SELECT has_table_privilege(:r, :t, 'INSERT')", r=role, t=f"public.{t}")[0][0] is True
    assert "CASCADE" in "".join(r[0] for r in owner_query("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'whatsapp_link_clicks'::regclass AND contype = 'f' AND pg_get_constraintdef(oid) LIKE '%whatsapp_contacts%'"))
    assert "SET NULL" in "".join(r[0] for r in owner_query("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'whatsapp_links'::regclass AND contype = 'f' AND pg_get_constraintdef(oid) LIKE '%whatsapp_messages%'"))


# ===================================================================== the visitor counters: short-lived, hashed, never in a table
def test_the_redis_counters_expire_within_a_minute_and_hold_only_a_hash(monkeypatch):
    from app.core import rate_limit

    class FakePipe:
        def __init__(self, store): self.store, self.ops = store, []
        def incr(self, k): self.ops.append(("incr", k)); return self
        def expire(self, k, t): self.ops.append(("expire", k, t)); return self
        def execute(self):
            for op in self.ops:
                self.store.append(op)
            return [1, True]

    class FakeRedis:
        def __init__(self): self.log = []
        def pipeline(self): return FakePipe(self.log)

    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "_redis", fake)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    with TestClient(app, base_url="http://testserver") as c:
        c.get(f"/api/v1/l/{links.new_token()}", headers={"User-Agent": BROWSER})
    expires = [op for op in fake.log if op[0] == "expire"]
    assert len(expires) == 2 and all(op[2] <= 61 for op in expires)  # gone within a minute
    assert all(re.fullmatch(r"rl:wa-link-(ip|token):[0-9a-f]{24}:\d+", op[1]) for op in fake.log if op[0] == "incr")  # a hash and a time window, never the address


def test_the_in_memory_fallback_forgets_finished_counters(monkeypatch):
    import time

    from app.core import rate_limit
    monkeypatch.setattr(rate_limit, "_get_redis", lambda: None)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    rate_limit.reset_memory_limits()
    old = time.time() - 300
    rate_limit._memory["wa-link-ip:stale"] = (3, old)
    rate_limit._windows["wa-link-ip:stale"] = 60
    rate_limit._memory["wa-link-ip:fresh"] = (1, time.time())
    rate_limit._windows["wa-link-ip:fresh"] = 60
    monkeypatch.setattr(rate_limit, "_last_sweep", 0.0)
    assert rate_limit.hit("wa-link-ip:another", 5, 60) is True
    assert "wa-link-ip:stale" not in rate_limit._memory and "wa-link-ip:stale" not in rate_limit._windows  # the finished window was swept
    assert "wa-link-ip:fresh" in rate_limit._memory and "wa-link-ip:another" in rate_limit._memory  # live ones stay
    rate_limit.reset_memory_limits()


def test_no_table_holds_a_visitor_counter_or_address():
    """The counters live only in Redis (or process memory). Nothing in the link tables, the audit log or the webhook log can hold a visitor's address."""
    tables = owner_query("SELECT table_name FROM information_schema.columns WHERE column_name IN ('ip', 'ip_address', 'client_ip', 'user_agent', 'ua', 'visitor_hash', 'remote_addr') AND table_schema = 'public' AND table_name LIKE 'whatsapp\\_%'")
    assert tables == []
