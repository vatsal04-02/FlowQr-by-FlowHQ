"""WhatsApp two-way conversations and the inbox (Phase 7 of the second round).

A conversation reply is the first free-form text the system sends, so these tests are about when it must NOT go out (the gate, row by row), what is and is not stored, who is told, and that one
business's conversations never reach another. Mock Meta only: no real number, account or message is involved."""
import hashlib
import io
import json
import uuid
import zipfile
from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.config import settings, whatsapp_passthrough_missing
from app.core.db import system_session
from app.models import Tenant
from app.models.base import utcnow
from app.services import mailer
from app.services.whatsapp import conversations, consent, rules, sender, templates
from tests import test_whatsapp as base
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_location_permissions import invite
from tests.test_whatsapp import OWNER, add_contact, grant_addon, payload, post_wh, process, svc_db, wa  # noqa: F401 - fixtures
from tests.test_whatsapp_messaging import ready_biz, wm  # noqa: F401 - fixtures

_n = iter(range(100_000, 999_999))


@pytest.fixture(autouse=True)
def inbox_platform(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_conversations_enabled", True)
    mailer.OUTBOX.clear()


def pid(biz) -> str:
    return owner_query("SELECT phone_number_id FROM whatsapp_connections WHERE tenant_id = :t", t=biz.tenant_id)[0][0]


def inbox_biz(admin, wm, name, tier="whatsapp_starter", fresh=False, **cfg):
    biz = ready_biz(admin, name, tier=tier, wm=wm, fresh=fresh)
    r = biz.put("/whatsapp/conversations/settings", json={"enabled": True, **cfg})
    assert r.status_code == 200, r.text
    owner_exec("UPDATE users SET email_verified_at = now() WHERE id IN (SELECT user_id FROM memberships WHERE tenant_id = :t)", t=biz.tenant_id)
    return biz


def phone_digits():
    return f"9198{next(_n):08d}"


def inbound(biz, text="hello", phone=None, wamid=None, ts=None, kind="text", extra=None):
    """A customer's message on this business's own verified number, processed the way the worker does."""
    phone = phone or phone_digits()
    m = {"from": phone, "id": wamid or f"wamid.IN{uuid.uuid4().hex[:12]}", "type": kind, "timestamp": str(int((ts or utcnow()).timestamp()))}
    if kind == "text":
        m["text"] = {"body": text}
    else:
        m[kind] = extra or {"id": "MEDIA1"}
    raw = payload(pid(biz), messages=[m])
    assert post_wh(raw).status_code == 200
    out = process(base.event_id_for(raw))
    return out, phone, raw


def conv_of(biz, phone):
    row = owner_query("SELECT cv.id FROM whatsapp_conversations cv JOIN whatsapp_contacts c ON c.id = cv.contact_id WHERE cv.tenant_id = :t AND c.phone = :p", t=biz.tenant_id, p="+" + phone)
    return str(row[0][0]) if row else None


def talk(biz, text="hello", **kw):
    out, phone, raw = inbound(biz, text, **kw)
    return conv_of(biz, phone), phone


def run(biz, minutes=10):
    db = system_session()
    try:
        out = conversations.run_due(db, utcnow() + timedelta(minutes=minutes), tenant_id=uuid.UUID(biz.tenant_id))
        db.commit()
        return out
    finally:
        db.close()


def reply(biz, cid, text="Our clinic opens at 9 am.", **kw):
    return biz.post(f"/whatsapp/conversations/{cid}/reply", json={"text": text, **kw})


def mail():
    """The handoff emails only (registration also writes to the test outbox)."""
    return [m for m in mailer.OUTBOX if "needs you" in m["subject"]]


def sent_texts(wm):
    return [m["text"]["body"] for m in wm.sent if m.get("type") == "text"]


def ledger(biz):
    return owner_query("SELECT category, kind, est_rate, template_id, delivery_status, meta_message_id FROM whatsapp_messages WHERE tenant_id = :t AND kind = 'service_reply' ORDER BY created_at", t=biz.tenant_id)


def age(cid, **delta):
    """Make the customer's last message older (window tests)."""
    owner_exec("UPDATE whatsapp_conversations SET last_customer_message_at = :t WHERE id = :i", t=utcnow() - timedelta(**delta), i=cid)


# ===================================================================== a reply is a service message sent only through the gate
def test_a_reply_inside_the_window_is_sent_as_plain_text_and_recorded_as_a_service_message(wm, admin):
    biz = inbox_biz(admin, wm, "Reply Clinic")
    cid, phone = talk(biz, "What time do you open?")
    r = reply(biz, cid, "We open at 9 am.")
    assert r.status_code == 200 and r.json()["sent"] is True, r.text
    body = wm.sent[-1]
    assert body["type"] == "text" and body["text"]["body"] == "We open at 9 am." and body["to"] == phone and "template" not in body
    row = ledger(biz)
    assert len(row) == 1 and row[0][0] == "service" and row[0][1] == "service_reply" and row[0][3] is None and row[0][4] == "sent"
    assert row[0][2] == Decimal("0.0000")  # inside the 1,000 free service messages per number per month
    thread = biz.get(f"/whatsapp/conversations/{cid}").json()
    assert [m["sender_type"] for m in thread["messages"]] == ["customer", "staff"] and thread["messages"][1]["text"] == "We open at 9 am."


def test_a_service_reply_never_gives_or_changes_consent(wm, admin):
    biz = inbox_biz(admin, wm, "No Consent Change")
    cid, phone = talk(biz, "Do you have offers?")
    assert reply(biz, cid, "We are open today until 6 pm.").status_code == 200
    reply(biz, cid, "Thank you for writing to us.")
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0  # writing to us, and being answered, creates no consent
    c = biz.get("/whatsapp/contacts").json()["items"][0]
    assert c["marketing"] is None and c["utility"] is None and c["occasion"] is None and c["opted_out"] is False


@pytest.mark.parametrize("age_kw,ok", [({"hours": 23, "minutes": 59}, True), ({"hours": 24, "minutes": 1}, False), ({"hours": 24}, False), ({"minutes": 1}, True)])
def test_the_24_hour_window_edges(wm, admin, age_kw, ok):
    biz = inbox_biz(admin, wm, "Window Clinic")
    cid, _ = talk(biz, "hi")
    age(cid, **age_kw)
    r = reply(biz, cid, "Hello again.")
    if ok:
        assert r.status_code == 200
    else:
        assert r.status_code == 409 and r.json()["detail"]["code"] == "window_closed" and wm.sent == []
        t = biz.get(f"/whatsapp/conversations/{cid}").json()
        assert t["window_open"] is False and t["window_note"] and "approved message" in t["window_note"]


def test_a_customer_who_never_wrote_cannot_be_answered_with_free_text(wm, admin):
    biz = inbox_biz(admin, wm, "Never Wrote")
    cid, _ = talk(biz, "hi")
    owner_exec("UPDATE whatsapp_conversations SET last_customer_message_at = NULL WHERE id = :i", i=cid)
    r = reply(biz, cid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_customer_message" and wm.sent == []


@pytest.mark.parametrize("switch,value,code", [("whatsapp_emergency_stop", True, "emergency_stop"), ("whatsapp_sending_enabled", False, "sending_disabled")])
def test_the_platform_switches_stop_a_reply(wm, admin, monkeypatch, switch, value, code):
    biz = inbox_biz(admin, wm, f"Switch {code}")
    cid, _ = talk(biz, "hi")
    monkeypatch.setattr(settings, switch, value)
    r = reply(biz, cid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == code and wm.sent == []


def test_the_platform_inbox_switch_and_the_business_switch_both_matter(wm, admin, monkeypatch):
    biz = inbox_biz(admin, wm, "Switches Clinic")
    cid, _ = talk(biz, "hi")
    monkeypatch.setattr(settings, "whatsapp_conversations_enabled", False)
    assert reply(biz, cid).status_code == 404 and biz.get("/whatsapp/conversations").json()["detail"]["code"] == "conversations_disabled"
    monkeypatch.setattr(settings, "whatsapp_conversations_enabled", True)
    biz.put("/whatsapp/conversations/settings", json={"enabled": False})
    assert reply(biz, cid).status_code == 404
    with svc_db(biz.tenant_id) as db:
        t = db.get(Tenant, uuid.UUID(biz.tenant_id))
        c = conversations.get(db, t.id, uuid.UUID(cid))
        res = sender.send_service_reply(db, t, c, "x", sender_type="system", idem_key="k1")
        assert (res.status, res.reason) == ("skipped", "conversations_disabled")  # the sender itself refuses, not only the route
    assert wm.sent == []


def test_the_add_on_and_a_healthy_connection_are_needed(wm, admin):
    biz = inbox_biz(admin, wm, "Addon Clinic")
    cid, _ = talk(biz, "hi")
    admin.put(f"/admin/tenants/{biz.tenant_id}/whatsapp-addon", json={"addon_key": None, "reason": "Cancelled by the owner"})
    r = reply(biz, cid)
    assert r.status_code in (402, 404) and wm.sent == []
    grant_addon(admin, biz, "whatsapp_starter")
    biz.post("/whatsapp/connection/disconnect")
    r2 = reply(biz, cid)
    assert r2.status_code in (404, 409) and wm.sent == []


def test_the_per_minute_and_per_day_limits_apply_and_a_repeat_never_sends_twice(wm, admin, monkeypatch):
    biz = inbox_biz(admin, wm, "Limits Clinic")
    cid, _ = talk(biz, "hi")
    first = reply(biz, cid, "One.", client_id="press-1")
    again = reply(biz, cid, "One.", client_id="press-1")  # the same press of Send: a double click
    assert first.status_code == 200 and again.status_code == 200 and again.json()["duplicate"] is True and len(sent_texts(wm)) == 1
    monkeypatch.setattr(settings, "whatsapp_send_per_minute", 1)
    over = reply(biz, cid, "Two.", client_id="press-2")
    assert over.status_code == 429 and over.json()["detail"]["code"] == "rate_limited" and len(sent_texts(wm)) == 1
    monkeypatch.setattr(settings, "whatsapp_send_per_minute", 1000)
    monkeypatch.setattr(settings, "whatsapp_daily_cap", 1)
    capped = reply(biz, cid, "Three.", client_id="press-3")
    assert capped.status_code == 429 and capped.json()["detail"]["code"] == "daily_cap"


def test_meta_failures_are_handled_without_a_half_sent_reply(wm, admin):
    biz = inbox_biz(admin, wm, "Meta Fail")
    cid, _ = talk(biz, "hi")
    wm.fail = {"send": 503}
    r = reply(biz, cid, "Try one.", client_id="a")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "meta_unavailable" and ledger(biz) == []  # a temporary failure leaves no trace: press Send again
    assert owner_query("SELECT count(*) FROM whatsapp_conversation_messages WHERE tenant_id = :t AND direction = 'outbound'", t=biz.tenant_id)[0][0] == 0
    wm.fail = {"send": 400}
    wm.fail_code = {"send": 131047}
    r2 = reply(biz, cid, "Try two.", client_id="b")
    assert r2.status_code == 502 and r2.json()["detail"]["code"] == "meta_rejected"
    msgs = biz.get(f"/whatsapp/conversations/{cid}").json()["messages"]
    assert msgs[-1]["status"] == "failed" and msgs[-1]["text"] == "Try two."  # the person sees that it did not go
    wm.fail = {}
    assert reply(biz, cid, "Try three.", client_id="c").status_code == 200


# ===================================================================== never an offer: a hard block for the assistant, a warning with a logged confirm for a person
def test_offer_style_text_is_found_and_ordinary_service_talk_is_not():
    for bad in ("50% off this week", "Get a discount today", "A special offer for you", "Our festive offers are live", "Flat 20 off on all sessions", "Buy 2 get 1 free", "Use coupon CODE10", "limited time deal",
                "छूट मिल रही है", "ऑफर चल रहा है", "chhoot milegi", "Free gift with every visit", "Save Rs 200 today", "Don't miss out"):
        assert rules.marketing_terms(bad), bad
    for fine in ("We offer physiotherapy and yoga.", "The session costs ₹500.", "Free parking is available.", "Our hours are 9 am to 6 pm.", "Yes, we have a slot tomorrow at 11.", "Consultation fee is Rs 300.",
                 "आपका स्वागत है", "Thank you for contacting us.", "We are offering appointments on weekdays."):
        assert rules.marketing_terms(fine) == [], fine


def test_the_assistant_and_automatic_messages_can_never_send_an_offer(wm, admin):
    biz = inbox_biz(admin, wm, "Hard Block")
    cid, _ = talk(biz, "hi")
    with svc_db(biz.tenant_id) as db:
        t = db.get(Tenant, uuid.UUID(biz.tenant_id))
        c = conversations.get(db, t.id, uuid.UUID(cid))
        for who in ("ai", "system"):
            res = sender.send_service_reply(db, t, c, "Get 50% off this week!", sender_type=who, idem_key=f"o:{who}", marketing_confirmed=True)  # a confirm flag changes nothing for them
            assert (res.status, res.reason) == ("skipped", "marketing_content"), who
        ok = sender.send_service_reply(db, t, c, "We open at 9 am.", sender_type="ai", idem_key="fine")
        db.commit()
        assert ok.ok
    assert sent_texts(wm) == ["We open at 9 am."]


def test_a_person_gets_a_warning_and_one_click_to_confirm_and_the_confirm_is_logged(wm, admin):
    biz = inbox_biz(admin, wm, "Warn Clinic")
    cid, _ = talk(biz, "hi")
    r = reply(biz, cid, "Special offer: 20% off today", client_id="m1")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "marketing_warning" and "offer" in " ".join(r.json()["detail"]["terms"]).lower() and wm.sent == []
    ok = reply(biz, cid, "Special offer: 20% off today", client_id="m1", confirm_marketing=True)
    assert ok.status_code == 200 and sent_texts(wm) == ["Special offer: 20% off today"]
    msgs = biz.get(f"/whatsapp/conversations/{cid}").json()["messages"]
    assert msgs[-1]["marketing_confirmed"] is True
    logged = owner_query("SELECT metadata FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.service_reply_marketing_confirmed'", t=biz.tenant_id)
    assert len(logged) == 1 and logged[0][0]["terms"] and "Special offer: 20% off today" not in json.dumps(logged[0][0])  # what was confirmed, not the whole message
    assert reply(biz, cid, "Our hours are 9 to 6.", client_id="m2").status_code == 200  # ordinary text needs no confirmation


# ===================================================================== what is stored, and what never is
def test_a_new_customer_becomes_a_labelled_contact_with_no_consent_excluded_from_every_audience_and_template(wm, admin):
    biz = inbox_biz(admin, wm, "No Consent Contact", tier="whatsapp_pro")
    cid, phone = talk(biz, "Hello, do you take walk-ins?")
    c = next(x for x in biz.get("/whatsapp/contacts").json()["items"] if x["phone"] == "+" + phone)
    assert c["source"] == "customer_message" and c["no_consent_contact"] is True and c["marketing"] is None and c["utility"] is None and c["occasion"] is None  # (1) labelled "contact, no consent"
    from app.services.whatsapp import campaigns
    with svc_db(biz.tenant_id) as db:
        tid = uuid.UUID(biz.tenant_id)
        audiences = [{"kind": "all"}, {"kind": "new", "days": 30}, {"kind": "existing", "days": 0 + 1}, {"kind": "all", "engaged": "replied", "engaged_days": 30}, {"kind": "all", "winback_days": 1},
                     {"kind": "all", "no_engagement_last_offers": 1}, {"kind": "all", "engaged": "read"}]
        for aud in audiences:
            assert db.scalars(campaigns.audience_query(tid, campaigns.clean_audience(aud, "advanced")).with_only_columns(campaigns.WhatsAppContact.id)).all() == [], aud  # (2) in no audience
        t = db.get(Tenant, tid)
        contact = consent.find_by_phone(db, tid, "+" + phone)
        for key, kind in (("review_followup", None), ("enquiry_ack", None), ("enquiry_followup", None), ("offer", None), ("optin_confirm", "optin_confirm"), ("optin_confirm_offers", "optin_confirm")):
            row = templates.standard_row(db, tid, key)
            if row is None:
                continue
            vars_ = ["Asha", "No Consent Contact"] + (["https://g.page/r/x/review"] if key == "review_followup" else ["10% off"] if key == "offer" else ["updates"] if key.startswith("optin") else [])
            res = sender.send_template(db, t, contact, row, vars_, idem_key=f"nc:{key}", kind=kind)
            assert res.status == "skipped" and "consent" in res.reason, (key, res.reason)  # (2) no template can be sent to them
    assert wm.sent == []


def test_such_a_contact_is_purged_with_the_conversation_retention_unless_they_consent_or_book(wm, admin):
    biz = inbox_biz(admin, wm, "Purge Contacts", retention_days=30)
    stranger, p1 = talk(biz, "hi, stranger")
    agreed, p2 = talk(biz, "hi, agreed")
    stopped, p3 = talk(biz, "hi, stopped")
    booked, p4 = talk(biz, "hi, booked")
    owner_exec("INSERT INTO whatsapp_consents (id, tenant_id, contact_id, purpose, source, wording_version, wording_text, granted_at) SELECT gen_random_uuid(), :t, id, 'utility', 'customer_message', 'v1', 'x', now() FROM whatsapp_contacts WHERE phone = :p AND tenant_id = :t",
               t=biz.tenant_id, p="+" + p2)
    owner_exec("UPDATE whatsapp_contacts SET marketing_opted_out_at = now() WHERE phone = :p AND tenant_id = :t", p="+" + p3, t=biz.tenant_id)
    old = utcnow() - timedelta(days=45)
    owner_exec("UPDATE whatsapp_conversation_messages SET created_at = :o WHERE tenant_id = :t", o=old, t=biz.tenant_id)
    owner_exec("UPDATE whatsapp_conversations SET created_at = :o, last_message_at = :o WHERE tenant_id = :t", o=old, t=biz.tenant_id)
    owner_exec("UPDATE whatsapp_contacts SET created_at = :o WHERE tenant_id = :t", o=old, t=biz.tenant_id)
    keep_id = owner_query("SELECT id FROM whatsapp_contacts WHERE tenant_id = :t AND phone = :p", t=biz.tenant_id, p="+" + p4)[0][0]
    conversations._CONTACT_KEEPERS.append(lambda col: col == keep_id)  # a booking (a later feature) is a reason to keep a contact
    try:
        db = system_session()
        try:
            out = conversations.purge(db)
            db.commit()
        finally:
            db.close()
    finally:
        conversations._CONTACT_KEEPERS.clear()
    left = {r[0] for r in owner_query("SELECT phone FROM whatsapp_contacts WHERE tenant_id = :t", t=biz.tenant_id)}
    assert left == {"+" + p2, "+" + p3, "+" + p4}  # (3) the stranger is gone; one who agreed, one who said STOP, and one who booked stay
    assert out["contacts"] >= 1 and owner_query("SELECT count(*) FROM whatsapp_conversation_messages WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0
    assert stranger and agreed and stopped and booked and p1


def test_stop_and_opt_in_messages_never_become_conversation_text(wm, admin):
    biz = inbox_biz(admin, wm, "No Text For Stop")
    biz.put("/whatsapp/optin", json={"qr_enabled": True})
    biz.post("/whatsapp/optin/keywords", json={"keyword": "joinoffers", "purpose": "marketing"})
    out, phone, raw = inbound(biz, "STOP")
    assert out["opt_outs"] == 1
    out2, phone2, raw2 = inbound(biz, "joinoffers")
    assert out2["opt_ins"] == 1
    out3, phone3, raw3 = inbound(biz, "Unsubscribe")
    for p in (phone, phone2, phone3):
        assert conv_of(biz, p) is None  # no conversation, no message
    assert owner_query("SELECT count(*) FROM whatsapp_conversation_messages WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0
    for r in (raw, raw2, raw3):
        stored = json.dumps(owner_query("SELECT payload FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=hashlib.sha256(r).hexdigest())[0][0])
        assert "STOP" not in stored and "joinoffers" not in stored and "Unsubscribe" not in stored  # the words are not kept in the event log either
    assert [c["phone"] for c in biz.get("/whatsapp/contacts").json()["items"]] == ["+" + phone2]  # only the person who joined exists as a contact


def test_conversation_text_is_not_kept_in_the_event_log_once_processed_or_after_a_day_if_not(wm, admin):
    biz = inbox_biz(admin, wm, "Event Text")
    secret = "my knee hurts when I climb the stairs at home"
    out, phone, raw = inbound(biz, secret)
    stored = json.dumps(owner_query("SELECT payload FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=hashlib.sha256(raw).hexdigest())[0][0])
    assert secret not in stored  # blanked as soon as it was processed
    cid = conv_of(biz, phone)
    assert biz.get(f"/whatsapp/conversations/{cid}").json()["messages"][0]["text"] == secret  # but it is in the conversation, where retention applies
    unprocessed = payload(pid(biz), messages=[{"from": phone_digits(), "id": "wamid.WAITING", "type": "text", "text": {"body": "still waiting to be processed"}, "timestamp": str(int(utcnow().timestamp()))}])
    assert post_wh(unprocessed).status_code == 200
    h = hashlib.sha256(unprocessed).hexdigest()
    assert "still waiting" in json.dumps(owner_query("SELECT payload FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=h)[0][0])
    owner_exec("UPDATE whatsapp_webhook_events SET received_at = now() - interval '25 hours' WHERE payload_sha256 = :h", h=h)
    db = system_session()
    try:
        from app.services.whatsapp import webhook
        assert webhook.scrub_old_texts(db) >= 1
        db.commit()
    finally:
        db.close()
    assert "still waiting" not in json.dumps(owner_query("SELECT payload FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=h)[0][0])


def test_with_the_inbox_off_nothing_is_stored_and_nobody_is_created(wm, admin, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_conversations_enabled", False)
    biz = ready_biz(admin, "Inbox Off", tier="whatsapp_starter", wm=wm)
    out, phone, raw = inbound(biz, "a message nobody keeps")
    assert out.get("conversation_messages") is None and conv_of(biz, phone) is None
    assert owner_query("SELECT count(*) FROM whatsapp_contacts WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0
    assert "nobody keeps" not in json.dumps(owner_query("SELECT payload FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=hashlib.sha256(raw).hexdigest())[0][0])


def test_a_picture_or_voice_note_is_recorded_without_text(wm, admin):
    biz = inbox_biz(admin, wm, "Media Clinic")
    out, phone, _ = inbound(biz, kind="image", extra={"id": "MEDIA9", "caption": "a photo of my knee"})
    cid = conv_of(biz, phone)
    m = biz.get(f"/whatsapp/conversations/{cid}").json()["messages"][0]
    assert m["msg_type"] == "image" and m["text"] is None
    assert biz.get("/whatsapp/conversations").json()["items"][0]["preview"] == "[image]"
    assert "knee" not in json.dumps(owner_query("SELECT row_to_json(m)::text FROM whatsapp_conversation_messages m WHERE tenant_id = :t", t=biz.tenant_id), default=str)


# ===================================================================== ingestion: duplicates, batching, the window
def test_a_repeat_delivery_stores_the_message_once(wm, admin):
    biz = inbox_biz(admin, wm, "Dup Clinic")
    phone = phone_digits()
    out, _, raw = inbound(biz, "same message", phone=phone, wamid="wamid.SAME1")
    assert post_wh(raw).status_code == 200  # Meta redelivers the very same body
    assert process(base.event_id_for(raw)) == {"skipped": "already_done"}
    out2, _, _ = inbound(biz, "same message again in a different body", phone=phone, wamid="wamid.SAME1")  # a different body that carries the same message id
    assert out2.get("conversation_messages") is None
    cid = conv_of(biz, phone)
    assert len(biz.get(f"/whatsapp/conversations/{cid}").json()["messages"]) == 1 and biz.get(f"/whatsapp/conversations/{cid}").json()["unread"] == 1


def test_rapid_messages_are_answered_once_after_a_short_wait(wm, admin):
    biz = inbox_biz(admin, wm, "Batch Clinic", debounce_seconds=4)
    phone = phone_digits()
    for i in range(3):
        out, _, _ = inbound(biz, f"part {i}", phone=phone)
        assert list(out["conversations"].values()) == [4]  # the wait the worker is told to use
    cid = conv_of(biz, phone)
    due = owner_query("SELECT reply_due_at FROM whatsapp_conversations WHERE id = :i", i=cid)[0][0]
    assert due is not None
    assert run(biz, minutes=0)["handled"] == 0  # not yet: the customer may still be typing
    first = run(biz, minutes=1)
    assert first["handled"] == 1 and first["handoff"] == 1  # one look at the whole burst, not three
    assert run(biz, minutes=2)["handled"] == 0
    assert biz.get(f"/whatsapp/conversations/{cid}").json()["unread"] == 3 and len(mail()) == 1  # one email for the burst


def test_messages_on_an_unknown_or_unconnected_number_are_ignored(wm, admin):
    biz = inbox_biz(admin, wm, "Known Number")
    raw = payload(base.uid(7), messages=[{"from": phone_digits(), "id": "wamid.X1", "type": "text", "text": {"body": "who is this"}, "timestamp": str(int(utcnow().timestamp()))}])
    assert post_wh(raw).status_code == 200
    out = process(base.event_id_for(raw))
    assert out["ignored_items"] == 1
    assert owner_query("SELECT count(*) FROM whatsapp_conversation_messages WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0


def test_a_message_is_time_stamped_by_meta_but_never_in_the_future(wm, admin):
    biz = inbox_biz(admin, wm, "Clock Clinic")
    phone = phone_digits()
    inbound(biz, "future", phone=phone, ts=utcnow() + timedelta(days=2))
    cid = conv_of(biz, phone)
    at = owner_query("SELECT last_customer_message_at FROM whatsapp_conversations WHERE id = :i", i=cid)[0][0]
    assert at <= utcnow() + timedelta(seconds=5)  # the window can never be stretched by a wrong clock
    old_phone = phone_digits()
    inbound(biz, "old", phone=old_phone, ts=utcnow() - timedelta(hours=30))  # delivered late: the window is measured from when it was sent
    assert biz.get(f"/whatsapp/conversations/{conv_of(biz, old_phone)}").json()["window_open"] is False


# ===================================================================== a person takes over; the owner is told, and why
def test_a_waiting_conversation_says_why_and_emails_the_owner_once_an_hour_without_the_message(wm, admin):
    biz = inbox_biz(admin, wm, "Notify Clinic")
    phone = phone_digits()
    inbound(biz, "my very private question", phone=phone)
    cid = conv_of(biz, phone)
    run(biz, minutes=1)
    t = biz.get(f"/whatsapp/conversations/{cid}").json()
    assert t["status"] == "needs_human" and t["handoff_reason"] == "assistant_off" and "waiting for you" in t["handoff_words"]
    assert len(mail()) == 1 and "private question" not in json.dumps(mailer.OUTBOX) and f"/whatsapp/inbox?c={cid}" in mail()[0]["body"]
    inbound(biz, "another one", phone=phone)
    run(biz, minutes=2)
    assert len(mail()) == 1  # not again inside the hour
    owner_exec("UPDATE whatsapp_conversations SET last_notified_at = now() - interval '2 hours' WHERE id = :i", i=cid)
    inbound(biz, "and a third", phone=phone)
    run(biz, minutes=3)
    assert len(mail()) == 2
    bell = biz.get("/notifications").json()["items"]
    assert any(i["kind"] == "conversation" and i["href"] == f"/whatsapp/inbox?c={cid}" and "private" not in json.dumps(i) for i in bell)


def test_email_can_be_switched_off_and_goes_only_to_owners_and_admins(wm, admin):
    biz = inbox_biz(admin, wm, "Quiet Clinic", notify_email=False)
    talk(biz, "hi")
    run(biz, minutes=1)
    assert mail() == []
    biz2 = inbox_biz(admin, wm, "Loud Clinic", fresh=True)
    staff = invite(biz2, role="staff")
    owner_exec("UPDATE users SET email_verified_at = now() WHERE id = :u", u=staff.user_id)
    talk(biz2, "hello there")
    run(biz2, minutes=1)
    assert len(mail()) == 1 and mail()[0]["to"] != staff.email  # the owner, not the staff member


def test_a_person_replying_pauses_the_assistant_for_the_chosen_time(wm, admin):
    biz = inbox_biz(admin, wm, "Takeover Clinic", takeover_minutes=30)
    phone = phone_digits()
    inbound(biz, "hi", phone=phone)
    cid = conv_of(biz, phone)
    assert reply(biz, cid, "Hello, how can I help?").status_code == 200
    paused = owner_query("SELECT ai_paused_until FROM whatsapp_conversations WHERE id = :i", i=cid)[0][0]
    assert abs((paused - (utcnow() + timedelta(minutes=30))).total_seconds()) < 60
    inbound(biz, "it hurts", phone=phone)
    out = run(biz, minutes=1)
    assert out["handled"] == 1 and out["handoff"] == 0 and mail() == []  # a person is in the conversation: no handoff, no email
    t = biz.get(f"/whatsapp/conversations/{cid}").json()
    assert t["status"] == "open" and t["ai_paused_until"] is not None and t["needs_reply"] is True
    back = biz.post(f"/whatsapp/conversations/{cid}/hand-back")
    assert back.status_code == 200 and back.json()["ai_paused_until"] is None
    take = biz.post(f"/whatsapp/conversations/{cid}/take-over").json()
    assert take["handoff_reason"] == "staff_took_over" and take["ai_paused_until"] is not None


def test_the_takeover_time_the_wait_and_the_retention_are_limited(wm, admin):
    biz = inbox_biz(admin, wm, "Limits Settings")
    assert biz.get("/whatsapp/conversations/settings").json()["settings"] == {"enabled": True, "retention_days": 90, "takeover_minutes": 60, "debounce_seconds": 4, "notify_email": True,
                                                                              "limits": {"retention_days": [30, 365], "takeover_minutes": [5, 1440], "debounce_seconds": [2, 10]}}
    for bad in ({"retention_days": 29}, {"retention_days": 366}, {"takeover_minutes": 4}, {"takeover_minutes": 1441}, {"debounce_seconds": 1}, {"debounce_seconds": 11}, {"retention_days": True}, {"retention_days": "ninety"}, {"retention_days": 90.5}):
        r = biz.put("/whatsapp/conversations/settings", json=bad)
        assert r.status_code == 422, bad
    for good in ({"retention_days": 30}, {"retention_days": 365}, {"takeover_minutes": 5}, {"takeover_minutes": 1440}, {"debounce_seconds": 2}, {"debounce_seconds": 10}):
        assert biz.put("/whatsapp/conversations/settings", json=good).status_code == 200, good
    with pytest.raises(Exception):
        owner_exec("UPDATE whatsapp_conversation_settings SET retention_days = 10 WHERE tenant_id = :t", t=biz.tenant_id)  # the database refuses it too
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.conversation_settings'", t=biz.tenant_id)[0][0] >= 7


def test_a_customer_who_said_stop_is_never_answered_automatically_but_a_person_may_reply(wm, admin):
    biz = inbox_biz(admin, wm, "Stop Then Write")
    phone = phone_digits()
    add_contact(biz, "+" + phone, name="Stopper", marketing=True, **OWNER)
    inbound(biz, "STOP", phone=phone)
    inbound(biz, "actually, what time do you open tomorrow?", phone=phone)
    cid = conv_of(biz, phone)
    t = biz.get(f"/whatsapp/conversations/{cid}").json()
    assert t["status"] == "needs_human" and t["handoff_reason"] == "customer_opted_out" and t["contact"]["opted_out"] is True
    assert run(biz, minutes=1)["handoff"] == 1 and sent_texts(wm) == []  # nothing automatic
    ok = reply(biz, cid, "We open at 9 am.")  # they wrote first, so a person may answer
    assert ok.status_code == 200 and sent_texts(wm) == ["We open at 9 am."]
    c = biz.get("/whatsapp/contacts").json()["items"][0]
    assert c["opted_out"] is True and c["marketing"] is None  # still opted out: a reply does not lift STOP


# ===================================================================== the inbox
def test_the_inbox_lists_searches_filters_and_labels_who_sent_what(wm, admin):
    biz = inbox_biz(admin, wm, "Inbox Clinic")
    a, pa = talk(biz, "I need a physio appointment")
    b, pb = talk(biz, "Where are you located?")
    reply(biz, a, "Sure, what day suits you?")
    biz.post(f"/whatsapp/conversations/{a}/read")
    lst = biz.get("/whatsapp/conversations").json()
    assert lst["total"] == 2 and lst["unread_total"] == 1
    by = {i["id"]: i for i in lst["items"]}
    assert by[a]["unread"] == 0 and by[b]["unread"] == 1 and by[a]["preview"] == "Sure, what day suits you?" and by[a]["preview_from"] == "staff" and by[b]["needs_reply"] is True
    assert [i["id"] for i in biz.get("/whatsapp/conversations", params={"filter": "unread"}).json()["items"]] == [b]
    assert [i["id"] for i in biz.get("/whatsapp/conversations", params={"q": "physio"}).json()["items"]] == [a]  # search finds words inside messages
    assert [i["id"] for i in biz.get("/whatsapp/conversations", params={"q": pb[-6:]}).json()["items"]] == [b]  # and phone numbers
    assert biz.get("/whatsapp/conversations", params={"q": "zzzz"}).json()["total"] == 0
    thread = biz.get(f"/whatsapp/conversations/{a}").json()
    labels = [m["sender_label"] for m in thread["messages"]]
    assert labels[0] == "A customer" and labels[1] not in ("A customer", None) and thread["messages"][1]["sender_type"] == "staff"
    biz.post(f"/whatsapp/conversations/{b}/close")
    assert biz.get("/whatsapp/conversations", params={"filter": "closed"}).json()["total"] == 1 and biz.get("/whatsapp/conversations").json()["total"] == 1
    biz.post(f"/whatsapp/conversations/{b}/reopen")
    inbound(biz, "second message after closing", phone=pa)
    assert biz.get(f"/whatsapp/conversations/{a}").json()["status"] in ("open", "needs_human")


def test_a_staff_member_can_answer_and_the_message_carries_their_name_but_cannot_change_settings(wm, admin):
    biz = inbox_biz(admin, wm, "Staff Clinic")
    staff = invite(biz, role="staff")
    cid, _ = talk(biz, "hello")
    r = staff.post(f"/whatsapp/conversations/{cid}/reply", json={"text": "Hello, this is the front desk."})
    assert r.status_code == 200
    thread = staff.get(f"/whatsapp/conversations/{cid}").json()
    name = owner_query("SELECT full_name FROM users WHERE id = :u", u=staff.user_id)[0][0]
    assert thread["messages"][-1]["sender_label"] == name and thread["assigned_name"] == name
    assert staff.put("/whatsapp/conversations/settings", json={"retention_days": 30}).status_code == 403
    assert staff.delete(f"/whatsapp/conversations/{cid}").status_code == 403
    assert biz.delete(f"/whatsapp/conversations/{cid}").status_code == 204
    assert owner_query("SELECT count(*) FROM whatsapp_conversation_messages WHERE conversation_id = :i", i=cid)[0][0] == 0


def test_a_location_restricted_member_does_not_get_the_business_wide_inbox(wm, admin):
    biz = inbox_biz(admin, wm, "Scoped Clinic")
    loc2 = biz.post("/locations", json={"name": "Branch", "city": "Agra", "review_url": "https://g.page/r/Z/review"}).json()["id"]
    limited = invite(biz, role="staff", location_ids=[loc2])
    talk(biz, "hi")
    r = limited.get("/whatsapp/conversations")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_for_your_role"


def test_outside_the_window_the_inbox_offers_an_approved_message_and_says_why(wm, admin):
    biz = inbox_biz(admin, wm, "Fallback Clinic")
    cid, phone = talk(biz, "hi")
    age(cid, hours=30)
    t = biz.get(f"/whatsapp/conversations/{cid}").json()
    assert t["window_open"] is False and t["fallback_templates"][0]["key"] == "enquiry_followup" and t["fallback_templates"][0]["can_send"] is False and t["fallback_templates"][0]["reason"] == "no_utility_consent"
    r = biz.post(f"/whatsapp/conversations/{cid}/send-template", json={"key": "enquiry_followup"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_utility_consent" and wm.sent == []  # the customer never agreed to updates: no template
    cid2 = conv_of(biz, phone)
    owner_exec("INSERT INTO whatsapp_consents (id, tenant_id, contact_id, purpose, source, wording_version, wording_text, granted_at) SELECT gen_random_uuid(), :t, contact_id, 'utility', 'customer_message', 'v1', 'x', now() FROM whatsapp_conversations WHERE id = :i",
               t=biz.tenant_id, i=cid2)
    t2 = biz.get(f"/whatsapp/conversations/{cid}").json()
    assert t2["fallback_templates"][0]["can_send"] is True and "following up on your enquiry" in t2["fallback_templates"][0]["text"]
    ok = biz.post(f"/whatsapp/conversations/{cid}/send-template", json={"key": "enquiry_followup"})
    assert ok.status_code == 200 and wm.sent[-1]["type"] == "template"
    assert biz.get(f"/whatsapp/conversations/{cid}").json()["messages"][-1]["template_key"] == "enquiry_followup"
    inbound(biz, "thanks", phone=phone)
    assert biz.post(f"/whatsapp/conversations/{cid}/send-template", json={"key": "enquiry_followup"}).json()["detail"]["code"] == "window_open"  # the window is open again: write a reply


def test_a_delivery_update_moves_the_reply_status_forward(wm, admin):
    biz = inbox_biz(admin, wm, "Status Clinic")
    cid, _ = talk(biz, "hi")
    reply(biz, cid, "Hello!")
    wamid = owner_query("SELECT meta_message_id FROM whatsapp_messages WHERE tenant_id = :t AND kind = 'service_reply'", t=biz.tenant_id)[0][0]
    raw = payload(pid(biz), statuses=[{"id": wamid, "status": "delivered", "timestamp": str(int(utcnow().timestamp()))}])
    post_wh(raw)
    process(base.event_id_for(raw))
    assert biz.get(f"/whatsapp/conversations/{cid}").json()["messages"][-1]["status"] == "delivered"


def test_a_message_typed_in_the_whatsapp_business_app_is_recorded_as_a_person_replying(wm, admin):
    """UNVERIFIED against real Meta traffic: this only proves how FlowQR reads the shape it expects (docs/WHATSAPP_META_CHECKLIST.md, first item)."""
    biz = inbox_biz(admin, wm, "Echo Clinic")
    phone = phone_digits()
    inbound(biz, "hi", phone=phone)
    cid = conv_of(biz, phone)
    value = {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "15550100100", "phone_number_id": pid(biz)},
             "message_echoes": [{"from": "15550100100", "to": phone, "id": "wamid.ECHO1", "timestamp": str(int(utcnow().timestamp())), "type": "text", "text": {"body": "Typed on the phone"}}]}
    raw = json.dumps({"object": "whatsapp_business_account", "entry": [{"id": base.WABA, "changes": [{"field": "smb_message_echoes", "value": value}]}]}).encode()
    assert post_wh(raw).status_code == 200
    assert process(base.event_id_for(raw))["echoes"] == 1
    t = biz.get(f"/whatsapp/conversations/{cid}").json()
    assert t["messages"][-1]["via_app"] is True and t["messages"][-1]["sender_label"] == "WhatsApp Business app" and t["messages"][-1]["text"] == "Typed on the phone" and t["needs_reply"] is False
    assert t["ai_paused_until"] is not None  # a person is in the conversation
    assert "Typed on the phone" not in json.dumps(owner_query("SELECT payload FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=hashlib.sha256(raw).hexdigest())[0][0])


# ===================================================================== retention, export, deletion
def test_old_text_is_purged_per_business_and_only_counts_are_logged(wm, admin):
    a = inbox_biz(admin, wm, "Retain 30", retention_days=30)
    b = inbox_biz(admin, wm, "Retain 365", retention_days=365, fresh=True)
    for biz in (a, b):
        cid, phone = talk(biz, "an old private sentence")
        reply(biz, cid, "An old answer.")
    old = utcnow() - timedelta(days=60)
    owner_exec("UPDATE whatsapp_conversation_messages SET created_at = :o WHERE tenant_id IN (:a, :b)", o=old, a=a.tenant_id, b=b.tenant_id)
    talk(a, "a fresh sentence")
    db = system_session()
    try:
        out = conversations.purge(db)
        db.commit()
    finally:
        db.close()
    assert out["messages"] >= 2
    assert owner_query("SELECT count(*) FROM whatsapp_conversation_messages WHERE tenant_id = :t", t=a.tenant_id)[0][0] == 1  # only the fresh one survives at 30 days
    assert owner_query("SELECT count(*) FROM whatsapp_conversation_messages WHERE tenant_id = :t", t=b.tenant_id)[0][0] == 2  # 365 days keeps both
    logged = json.dumps([r[0] for r in owner_query("SELECT metadata FROM audit_logs WHERE action = 'whatsapp.conversation_purge'")], default=str)
    assert "private sentence" not in logged and "old answer" not in logged
    db = system_session()
    try:
        again = conversations.purge(db)  # a second run finds nothing more to do for these two businesses
        assert owner_query("SELECT count(*) FROM whatsapp_conversation_messages WHERE tenant_id = :t", t=a.tenant_id)[0][0] == 1 and again["messages"] >= 0
    finally:
        db.close()


def test_export_and_deletion_cover_conversations(wm, admin):
    biz = inbox_biz(admin, wm, "Export Conversations")
    cid, phone = talk(biz, "please export me")
    reply(biz, cid, "Noted.")
    z = zipfile.ZipFile(io.BytesIO(biz.get("/account/export").content))
    assert {"whatsapp_conversation_settings.json", "whatsapp_conversations.json", "whatsapp_conversation_messages.json"} <= set(z.namelist())
    texts = [m["text"] for m in json.loads(z.read("whatsapp_conversation_messages.json"))]
    assert "please export me" in texts and "Noted." in texts
    contact = next(c for c in biz.get("/whatsapp/contacts").json()["items"] if c["phone"] == "+" + phone)
    assert biz.delete(f"/whatsapp/contacts/{contact['id']}").status_code == 204  # deleting the customer deletes the conversation and every message
    assert owner_query("SELECT count(*) FROM whatsapp_conversations WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0
    assert owner_query("SELECT count(*) FROM whatsapp_conversation_messages WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0
    cid2, _ = talk(biz, "and the business too")
    db = system_session()
    try:
        from sqlalchemy import text
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": biz.tenant_id})
        db.commit()
    finally:
        db.close()
    for t in ("whatsapp_conversation_settings", "whatsapp_conversations", "whatsapp_conversation_messages"):
        assert owner_query(f"SELECT count(*) FROM {t} WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0, t
    assert cid2


# ===================================================================== tenant isolation
def test_one_business_never_sees_or_answers_another_businesss_conversations(wm, admin):
    a = inbox_biz(admin, wm, "Iso Conv A")
    b = inbox_biz(admin, wm, "Iso Conv B", fresh=True)
    phone = phone_digits()
    ca, _ = talk(a, "a private note for business A", phone=phone)
    cb, _ = talk(b, "something for business B", phone=phone)  # the same person writes to both
    assert ca != cb
    for viewer, other_id in ((a, cb), (b, ca)):
        assert viewer.get(f"/whatsapp/conversations/{other_id}").status_code == 404
        assert viewer.post(f"/whatsapp/conversations/{other_id}/reply", json={"text": "Hello"}).status_code == 404
        assert viewer.post(f"/whatsapp/conversations/{other_id}/take-over").status_code == 404
        assert viewer.delete(f"/whatsapp/conversations/{other_id}").status_code == 404
    assert json.dumps(a.get("/whatsapp/conversations").json()).count("business B") == 0 and json.dumps(b.get("/whatsapp/conversations").json()).count("business A") == 0
    assert [m["text"] for m in a.get(f"/whatsapp/conversations/{ca}").json()["messages"]] == ["a private note for business A"]
    from sqlalchemy import text

    from app.core.db import SessionLocal, set_rls_context
    for table in ("whatsapp_conversation_settings", "whatsapp_conversations", "whatsapp_conversation_messages"):
        assert owner_query("SELECT relforcerowsecurity FROM pg_class WHERE relname = :t", t=table)[0][0] is True
        with SessionLocal() as db:
            set_rls_context(db, tenant_id=uuid.UUID(b.tenant_id))
            assert db.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": a.tenant_id}).scalar() == 0, table
    wm.sent.clear()
    reply(a, ca, "Only to A's customer.")
    assert len(wm.sent) == 1 and wm.sent[0]["to"] == phone


# ===================================================================== shape
def test_the_passthrough_check_lists_settings_that_would_be_silently_ignored():
    missing = whatsapp_passthrough_missing({"WHATSAPP_ENABLED": "true"})
    assert "WHATSAPP_ENABLED" not in missing and "WHATSAPP_CONVERSATIONS_ENABLED" in missing and "WHATSAPP_SENDING_ENABLED" in missing and "META_APP_ID" in missing and "META_APP_SECRET" in missing
    assert whatsapp_passthrough_missing({n: "x" for n in whatsapp_passthrough_missing({})}) == []
    assert all(n.startswith(("WHATSAPP_", "META_")) for n in missing)


def test_the_inbox_needs_whatsapp_and_the_manifest_lists_every_route(wm):
    biz = make_business("Inbox Off Biz")
    assert biz.get("/whatsapp/conversations/settings").status_code == 200
    assert biz.get("/whatsapp/conversations").status_code in (403, 404)
    lines = [ln.split("\t") for ln in open("tests/route_access_manifest.txt", encoding="utf-8").read().splitlines() if "/whatsapp/conversations" in ln]
    kinds = {(m, p.replace("/api/v1/whatsapp/conversations", "")): k for k, m, p in lines}
    assert kinds[("PUT", "/settings")] == "role-admin" and kinds[("DELETE", "/{conversation_id}")] == "role-admin" and kinds[("GET", "")] == "member" and kinds[("POST", "/{conversation_id}/reply")] == "member"


def test_the_migration_added_the_conversation_tables_with_the_limits(wm):
    assert owner_query("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_wa_conv_retention'")[0][0].replace(" ", "") .find("30") > 0
    cols = {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = 'whatsapp_conversation_messages'")}
    assert {"text", "sender_type", "staff_user_id", "via_app", "marketing_confirmed", "meta_message_id", "ledger_id"} <= cols
    role = settings.database_url.split("//")[1].split(":")[0]
    assert owner_query("SELECT has_table_privilege(:r, 'public.whatsapp_conversation_messages', 'DELETE')", r=role)[0][0] is True  # the purge needs it
