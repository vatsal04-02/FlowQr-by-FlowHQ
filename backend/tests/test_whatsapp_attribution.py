"""Click-to-WhatsApp attribution and the free entry-point window (Phase 11 of the second round). It ships OFF and is Pro only.

Meta's referral shape is written from documentation and not seen from real traffic, so these tests prove OUR handling: what is kept, that it is trimmed, that it never creates consent or changes who may be
messaged, and that no message is estimated as free unless the window length has been checked by an administrator."""
import io
import json
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.config import Settings, settings, whatsapp_passthrough_missing
from app.core.db import system_session
from app.models.base import utcnow
from app.services.whatsapp import attribution, conversations
from tests import test_whatsapp as base
from tests.conftest import owner_exec, owner_query
from tests.test_location_permissions import invite
from tests.test_whatsapp import grant_addon, payload, post_wh, process, wa  # noqa: F401 - fixtures
from tests.test_whatsapp_bookings import day, setup_bookings
from tests.test_whatsapp_conversations import conv_of, inbound, inbox_biz, inbox_platform, pid, phone_digits, reply, sent_texts, talk  # noqa: F401
from tests.test_whatsapp_messaging import wm  # noqa: F401 - fixtures

AD = {"source_type": "ad", "source_id": "120330000000001", "source_url": "https://fb.me/abc123", "headline": "Back pain relief in Lucknow", "body": "Book a visit", "media_type": "image", "ctwa_clid": "AR-click-1"}


@pytest.fixture(autouse=True)
def platform(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_attribution_enabled", True)
    monkeypatch.setattr(settings, "whatsapp_booking_enabled", True)


def pro(admin, wm, name, fresh=False, tier="whatsapp_pro"):
    return inbox_biz(admin, wm, name, tier=tier, fresh=fresh)


def referral_message(biz, referral=AD, text="Hi, I saw your ad", phone=None, ts=None):
    """A customer's first message arriving from an ad: the way Meta delivers it, processed the way the worker does."""
    phone = phone or phone_digits()
    m = {"from": phone, "id": f"wamid.AD{uuid.uuid4().hex[:12]}", "type": "text", "timestamp": str(int((ts or utcnow()).timestamp())), "text": {"body": text}}
    if referral is not None:
        m["referral"] = referral
    raw = payload(pid(biz), messages=[m])
    assert post_wh(raw).status_code == 200
    process(base.event_id_for(raw))
    return conv_of(biz, phone), phone


def row(biz, cid):
    return owner_query("SELECT source, referral_type, referral_id, referral_headline, referral_url, referral_clid, entry_point_at FROM whatsapp_conversations WHERE id = :i", i=cid)[0]


def verify_window(admin, hours_row_date="2026-09-21", ok=True):
    wid = next(w["id"] for w in admin.get("/admin/whatsapp/entry-windows").json()["items"] if w["effective_from"] == hours_row_date)
    assert admin.post(f"/admin/whatsapp/entry-windows/{wid}/check", json={"verified": ok, "note": "Matches Meta's pricing documentation, page dated 1 Dec 2026"}).status_code == 201
    return wid


@pytest.fixture()
def clean_windows():
    yield
    owner_exec("DELETE FROM whatsapp_entry_window_checks")
    owner_exec("DELETE FROM whatsapp_entry_windows WHERE source LIKE 'TEST %'")


# ===================================================================== off by default, plan, parsing
def test_defaults_are_off_and_passed_through_the_overlay():
    assert Settings.model_fields["whatsapp_attribution_enabled"].default is False
    import os
    path = next(p for p in ("../deploy/vps/docker-compose.vps.yml", "../../deploy/vps/docker-compose.vps.yml", "/deploy/vps/docker-compose.vps.yml") if os.path.exists(p))
    assert "WHATSAPP_ATTRIBUTION_ENABLED: ${WHATSAPP_ATTRIBUTION_ENABLED:-false}" in open(path, encoding="utf-8").read() and "WHATSAPP_ATTRIBUTION_ENABLED" in whatsapp_passthrough_missing({})


def test_an_ad_click_tags_the_conversation_with_where_it_came_from(wm, admin):
    biz = pro(admin, wm, "Ad Biz")
    cid, phone = referral_message(biz)
    assert row(biz, cid)[:6] == ("ad", "ad", "120330000000001", "Back pain relief in Lucknow", "https://fb.me/abc123", "AR-click-1") and row(biz, cid)[6] is not None
    t = biz.get(f"/whatsapp/conversations/{cid}").json()
    assert t["source"] == "ad" and t["referral"]["id"] == "120330000000001" and t["referral"]["headline"] == "Back pain relief in Lucknow" and t["entry_window"]["counts_as_free"] is False
    assert biz.get("/whatsapp/conversations").json()["items"][0]["referral"]["type"] == "ad"
    no_ad_cid, _ = referral_message(biz, referral=None)  # an ordinary message
    assert row(biz, no_ad_cid)[:2] == ("organic", None) and biz.get(f"/whatsapp/conversations/{no_ad_cid}").json()["referral"] is None and biz.get(f"/whatsapp/conversations/{no_ad_cid}").json()["entry_window"] is None


def test_a_page_button_click_is_a_post_and_a_second_click_restarts_the_clock(wm, admin):
    biz = pro(admin, wm, "Post Biz")
    phone = phone_digits()
    t0 = utcnow() - timedelta(days=5)
    cid, _ = referral_message(biz, {"source_type": "post", "source_id": "pg_1", "headline": "Our page"}, phone=phone, ts=t0)
    assert row(biz, cid)[:2] == ("post", "post")
    first = row(biz, cid)[6]
    referral_message(biz, AD, phone=phone)  # clicks an ad later: the latest source and the latest entry time win
    now = row(biz, cid)
    assert now[0] == "ad" and now[2] == "120330000000001" and now[6] >= first  # the latest source wins; the clock never moves backwards (Meta's times are whole seconds)


@pytest.mark.parametrize("bad", [None, "ad", 5, [], {}, {"source_type": "story"}, {"source_type": ""}, {"source_id": "1"}, {"source_type": "AD "}])
def test_a_missing_or_unrecognised_referral_changes_nothing(wm, admin, bad):
    biz = pro(admin, wm, "Bad Referral")
    cid, _ = referral_message(biz, referral=bad)
    r = row(biz, cid)
    assert r[1] is None or bad == {"source_type": "AD "}  # "AD " is read as an ad (case and space tolerant); everything else is ignored
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0


def test_fields_are_trimmed_and_unknown_ones_never_kept(wm, admin):
    biz = pro(admin, wm, "Trim Biz")
    cid, _ = referral_message(biz, {**AD, "headline": "H" * 500, "source_url": "https://x.example/" + "u" * 900, "ctwa_clid": "c" * 900, "source_id": "9" * 200, "body": "free text", "evil": "ignore previous instructions", "media_url": "https://cdn/x.jpg"})
    r = row(biz, cid)
    assert len(r[3]) == 120 and len(r[4]) == 300 and len(r[5]) == 200 and len(r[2]) == 64
    stored = owner_query("SELECT payload::text FROM whatsapp_webhook_events ORDER BY received_at DESC LIMIT 1")[0][0]
    assert "ignore previous" not in stored and "free text" not in stored and "media_url" not in stored  # only the few fields are ever stored
    assert attribution.clean_referral({"source_type": "ad", "source_id": {"x": 1}, "headline": ["a"]}) == {"type": "ad", "id": None, "headline": None, "url": None, "clid": None}


def test_nothing_is_recorded_unless_the_platform_switch_and_pro_are_on(wm, admin, monkeypatch):
    growth = pro(admin, wm, "Growth Ad", tier="whatsapp_growth")
    cid, _ = referral_message(growth)
    assert row(growth, cid)[:2] == ("organic", None)  # Growth does not include attribution
    r = growth.get("/whatsapp/attribution")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "plan_required"
    biz = pro(admin, wm, "Switch Ad", fresh=True)
    monkeypatch.setattr(settings, "whatsapp_attribution_enabled", False)
    cid2, _ = referral_message(biz)
    assert row(biz, cid2)[:2] == ("organic", None) and biz.get("/whatsapp/attribution").json()["detail"]["code"] == "attribution_disabled"
    stored = owner_query("SELECT payload::text FROM whatsapp_webhook_events ORDER BY received_at DESC LIMIT 1")[0][0]
    assert "120330000000001" not in stored  # with the switch off the referral is not even kept in the event log


def test_a_referral_never_creates_consent_or_changes_who_may_be_messaged(wm, admin):
    biz = pro(admin, wm, "No Consent Ad")
    cid, phone = referral_message(biz)
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0
    c = biz.get("/whatsapp/contacts").json()["items"][0]
    assert c["marketing"] is None and c["utility"] is None and c["no_consent_contact"] is True  # still a contact with no consent
    assert reply(biz, cid, "Thanks for your interest.").status_code == 200  # they wrote first, so a person may answer
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0


def test_stop_is_still_handled_first_and_never_stored_with_a_referral(wm, admin):
    biz = pro(admin, wm, "Stop Ad")
    phone = phone_digits()
    referral_message(biz, AD, text="STOP", phone=phone)
    assert owner_query("SELECT count(*) FROM whatsapp_conversations WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0  # STOP is handled before conversations: nothing stored, nothing tagged
    assert owner_query("SELECT count(*) FROM whatsapp_suppressions WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 1


# ===================================================================== the free entry-point window
def test_both_candidate_lengths_are_seeded_dated_and_unverified(wm, admin):
    items = admin.get("/admin/whatsapp/entry-windows").json()
    rows = {w["effective_from"]: w for w in items["items"]}
    assert rows["2026-01-01"]["hours"] == 72 and rows["2026-09-21"]["hours"] == 168
    assert all(w["verified"] is False and "NOT checked" in w["source"] for w in rows.values() if w["effective_from"] in ("2026-01-01", "2026-09-21"))
    assert items["warning"] and "normal rate" in items["warning"]
    assert owner_query("SELECT count(*) FROM whatsapp_entry_window_checks")[0][0] == 0


def test_a_message_inside_the_window_is_NOT_free_while_the_length_is_unverified(wm, admin):
    biz = pro(admin, wm, "Unverified Window")
    cid, _ = referral_message(biz)
    assert reply(biz, cid, "Thanks for your interest.").status_code == 200
    # Meta's first 1,000 service messages a month are free anyway; the point is that the entry window is not what made it free
    st = biz.get(f"/whatsapp/conversations/{cid}").json()["entry_window"]
    assert st["open"] is True and st["verified"] is False and st["counts_as_free"] is False and "normal rate" in st["warning"] and st["hours"] == 168
    assert attribution.free_now(system_session(), uuid.UUID(biz.tenant_id), uuid.UUID(biz.get("/whatsapp/contacts").json()["items"][0]["id"])) is False


def test_once_an_administrator_has_checked_the_length_messages_inside_the_window_are_estimated_as_free(wm, admin, clean_windows):
    biz = pro(admin, wm, "Verified Window")
    # make plain service messages cost something so "free because of the entry window" is visible: no free allowance, a real rate
    owner_exec("UPDATE whatsapp_rates SET free_per_number_month = 0 WHERE category = 'service'")
    try:
        cid, phone = referral_message(biz)
        organic_cid, _ = referral_message(biz, referral=None)
        assert reply(biz, cid, "First answer.").status_code == 200
        before = owner_query("SELECT est_rate FROM whatsapp_messages WHERE tenant_id = :t AND kind = 'service_reply' ORDER BY created_at", t=biz.tenant_id)
        assert before[0][0] > 0  # not free: the length is unverified
        verify_window(admin)
        assert reply(biz, cid, "Second answer.").status_code == 200
        assert reply(biz, organic_cid, "Organic answer.").status_code == 200
        rates = [r[0] for r in owner_query("SELECT est_rate FROM whatsapp_messages WHERE tenant_id = :t AND kind = 'service_reply' ORDER BY created_at", t=biz.tenant_id)]
        assert rates[1] == Decimal("0.0000") and rates[2] > 0  # free inside the verified window; an ordinary conversation is not
        assert biz.get(f"/whatsapp/conversations/{cid}").json()["entry_window"]["counts_as_free"] is True
        # a later check that says "no" takes it back
        verify_window(admin, ok=False)
        assert biz.get(f"/whatsapp/conversations/{cid}").json()["entry_window"]["counts_as_free"] is False
    finally:
        owner_exec("UPDATE whatsapp_rates SET free_per_number_month = 1000 WHERE category = 'service' AND free_per_number_month = 0")


def test_the_window_closes_and_is_measured_with_the_length_in_force_on_the_day_of_the_click(wm, admin, clean_windows):
    biz = pro(admin, wm, "Window Edges")
    verify_window(admin, "2026-01-01")
    verify_window(admin, "2026-09-21")
    cid, _ = referral_message(biz)
    db = system_session()
    try:
        conv = db.get(__import__("app.models.whatsapp", fromlist=["WhatsAppConversation"]).WhatsAppConversation, uuid.UUID(cid))
        e = conv.entry_point_at
        assert attribution.state(db, conv, e + timedelta(hours=167))["counts_as_free"] is True
        assert attribution.state(db, conv, e + timedelta(hours=168))["counts_as_free"] is False  # 7 days (the row in force today)
        conv.entry_point_at = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)  # a click before 21 Sep uses the 72 hour row
        assert attribution.state(db, conv, conv.entry_point_at + timedelta(hours=71))["counts_as_free"] is True
        assert attribution.state(db, conv, conv.entry_point_at + timedelta(hours=73))["counts_as_free"] is False
        conv.entry_point_at = datetime(2025, 6, 1, tzinfo=timezone.utc)  # before any row exists: no claim
        assert attribution.state(db, conv, datetime(2025, 6, 2, tzinfo=timezone.utc))["counts_as_free"] is False
    finally:
        db.rollback()
        db.close()


def test_a_window_change_is_a_new_dated_row_never_an_edit(wm, admin, clean_windows):
    ok = admin.post("/admin/whatsapp/entry-windows", json={"hours": 72, "effective_from": "2027-03-01", "source": "TEST Meta pricing page dated 1 Mar 2027"})
    assert ok.status_code == 201 and ok.json()["verified"] is False  # a new row always starts unverified
    assert admin.post("/admin/whatsapp/entry-windows", json={"hours": 48, "effective_from": "2027-03-01", "source": "TEST same day again"}).json()["detail"]["code"] == "date_taken"
    for bad in ({"hours": 0}, {"hours": 721}, {"hours": 72, "source": "short"}):
        body = {"hours": 72, "effective_from": "2027-04-01", "source": "TEST long enough source", **bad}
        assert admin.post("/admin/whatsapp/entry-windows", json=body).status_code == 422
    wid = ok.json()["id"]
    assert admin.post(f"/admin/whatsapp/entry-windows/{wid}/check", json={"verified": True, "note": "too short"}).status_code == 422
    assert admin.put(f"/admin/whatsapp/entry-windows/{wid}", json={"hours": 1}).status_code in (404, 405)
    assert owner_query("SELECT hours FROM whatsapp_entry_windows WHERE id = :i", i=wid)[0][0] == 72
    assert owner_query("SELECT count(*) FROM audit_logs WHERE action = 'admin.whatsapp_entry_window'")[0][0] >= 1


def test_only_platform_administrators_touch_the_window(wm, admin):
    biz = pro(admin, wm, "Not Admin")
    assert biz.get("/admin/whatsapp/entry-windows").status_code in (401, 403, 404) and biz.post("/admin/whatsapp/entry-windows", json={"hours": 72, "effective_from": "2027-05-01", "source": "TEST not allowed here"}).status_code in (401, 403, 404)


# ===================================================================== what the owner sees
def test_the_summary_counts_conversations_and_customers_who_booked_per_ad(wm, admin):
    biz = pro(admin, wm, "Summary Biz")
    svc = setup_bookings(biz)
    ad2 = {**AD, "source_id": "999", "headline": "Second ad"}
    c1, p1 = referral_message(biz)
    referral_message(biz)
    referral_message(biz, ad2)
    referral_message(biz, referral=None)
    contact = next(c for c in biz.get("/whatsapp/contacts").json()["items"] if c["phone"] == "+" + p1)
    assert biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3), "time": "10:00", "contact_id": contact["id"]}).status_code == 201
    s = biz.get("/whatsapp/attribution").json()
    by = {x["id"]: x for x in s["sources"]}
    assert by["120330000000001"]["conversations"] == 2 and by["120330000000001"]["customers_who_booked"] == 1 and by["999"]["conversations"] == 1 and by["999"]["customers_who_booked"] == 0
    assert s["from_ads_or_posts"] == 3 and s["conversations_in_period"] == 4 and s["window_note"]
    assert "phone" not in json.dumps(s) and "+91" not in json.dumps(s)  # no customer is named


def test_the_summary_is_for_owners_of_every_location_and_isolated_per_business(wm, admin):
    a = pro(admin, wm, "Iso Ad A")
    b = pro(admin, wm, "Iso Ad B", fresh=True)
    referral_message(a)
    assert b.get("/whatsapp/attribution").json()["sources"] == []
    limited = invite(a, role="staff", location_ids=[a.location_id])
    assert limited.get("/whatsapp/attribution").status_code == 403
    assert a.get("/whatsapp/attribution").json()["sources"][0]["conversations"] == 1


def test_the_new_conversation_event_says_where_the_customer_came_from_and_carries_no_text(wm, admin, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_integrations_enabled", True)
    biz = pro(admin, wm, "Event Ad")
    assert biz.post("/whatsapp/integrations/endpoints", json={"url": "https://hooks.example.com/x", "events": ["conversation.created"]}).status_code in (201, 422)
    from app.services.whatsapp import integrations
    monkeypatch.setattr(integrations, "_resolve", lambda host, port, type=None: [(2, 1, 6, "", ("93.184.216.34", port))])
    r = biz.post("/whatsapp/integrations/endpoints", json={"url": "https://hooks.example.com/x", "events": ["conversation.created"]})
    assert r.status_code == 201, r.text
    referral_message(biz, text="a private health question")
    d = owner_query("SELECT payload::text FROM whatsapp_webhook_deliveries WHERE tenant_id = :t AND event_type = 'conversation.created'", t=biz.tenant_id)[0][0]
    assert "\"referral_type\": \"ad\"" in d and "120330000000001" in d and "private health" not in d


# ===================================================================== export, retention, migration
def test_the_export_includes_the_referral_and_the_retention_purge_removes_it_with_the_conversation(wm, admin):
    biz = pro(admin, wm, "Export Ad")
    cid, phone = referral_message(biz)
    z = zipfile.ZipFile(io.BytesIO(biz.get("/account/export").content))
    conv = json.loads(z.read("whatsapp_conversations.json"))[0]
    assert conv["referral_type"] == "ad" and conv["referral_id"] == "120330000000001" and conv["source"] == "ad" and conv["entry_point_at"]
    owner_exec("UPDATE whatsapp_conversations SET created_at = now() - interval '200 days' WHERE id = :i", i=cid)
    owner_exec("UPDATE whatsapp_contacts SET created_at = now() - interval '200 days' WHERE tenant_id = :t", t=biz.tenant_id)
    owner_exec("UPDATE whatsapp_conversation_messages SET created_at = now() - interval '200 days' WHERE tenant_id = :t", t=biz.tenant_id)
    db = system_session()
    try:
        conversations.purge(db)
        db.commit()
    finally:
        db.close()
    assert owner_query("SELECT count(*) FROM whatsapp_conversations WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0  # the ad tag goes with the conversation and its retention
    contact = next(iter(owner_query("SELECT 1 FROM whatsapp_contacts WHERE tenant_id = :t", t=biz.tenant_id)), None)
    assert contact is None


def test_migration_0060_shape():
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] >= "0060"
    cols = {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = 'whatsapp_conversations'")}
    assert {"referral_type", "referral_id", "referral_headline", "referral_url", "referral_clid", "entry_point_at"} <= cols
    with pytest.raises(Exception):
        owner_exec("INSERT INTO whatsapp_entry_windows (id, hours, effective_from, source) VALUES (gen_random_uuid(), 0, '2031-01-01', 'x')")
    with pytest.raises(Exception):
        owner_exec("INSERT INTO whatsapp_entry_windows (id, hours, effective_from, source) VALUES (gen_random_uuid(), 72, '2026-01-01', 'duplicate date')")
