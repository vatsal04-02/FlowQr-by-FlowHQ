"""WhatsApp opt-in without collecting a phone number (Phase 1 of the second round): the QR page's click-to-chat button and opt-in keywords.

The customer's own message is the consent, so every test here is about when a message does NOT count (fail closed), what a consent that does count records, and that the one confirmation reply goes through
the normal sender and gate. Mock Meta only: no real number, account or message is involved."""
import hashlib
import io
import json
import re
import uuid
import zipfile
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import system_session
from app.main import app
from app.services.whatsapp import optin, rules, webhook as wh
from tests import test_whatsapp as base
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_whatsapp import OWNER, add_contact, connect, grant_addon, payload, post_wh, process, wa  # noqa: F401 - fixtures
from tests.test_whatsapp_messaging import messages, ready_biz, send, wm  # noqa: F401 - fixtures

PHONE = "919876543210"
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}


def prepared(admin, name="Optin Clinic", tier="whatsapp_growth", **opts):
    """A connected business whose standard and opt-in confirmation messages are approved, with the QR opt-in switched on."""
    biz = ready_biz(admin, name, tier=tier, install=False)
    assert biz.post("/whatsapp/setup/prepare-messages", json={"include_optin": True, "include_offer": True}).status_code == 200
    r = biz.put("/whatsapp/optin", json={"qr_enabled": True, **opts})
    assert r.status_code == 200, r.text
    return biz


def prefill(biz) -> str:
    return biz.get("/whatsapp/optin").json()["settings"]["prefill_text"]


def inbound(text, phone=PHONE, phone_id=None, wamid=None):
    """A customer's message arriving on a business's verified number, processed the way the worker does."""
    raw = payload(phone_id, messages=[{"from": phone, "id": wamid or f"wamid.IN{uuid.uuid4().hex[:10]}", "type": "text", "text": {"body": text}}])
    assert post_wh(raw).status_code == 200
    return process(base.event_id_for(raw))


def pid(biz) -> str:
    """The Meta id of this business's own connected number (a second business in a test has its own)."""
    return owner_query("SELECT phone_number_id FROM whatsapp_connections WHERE tenant_id = :t", t=biz.tenant_id)[0][0]


def contacts(biz, **params):
    return biz.get("/whatsapp/contacts", params=params).json()["items"]


def consents(biz):
    return owner_query("SELECT purpose, source, wording_version, wording_text, granted_at, revoked_at FROM whatsapp_consents WHERE tenant_id = :t ORDER BY purpose", t=biz.tenant_id)


# ===================================================================== the wording and the code
def test_every_prefilled_text_is_the_consent_wording_and_names_the_business_the_purpose_and_a_code(wm, admin):
    code_alphabet = set(optin.CODE_ALPHABET)
    for purpose, must in (("utility", ["updates about my visits and enquiries"]), ("marketing", ["offers and updates", "STOP"]), ("both", ["visits and enquiries", "offers", "STOP"])):
        biz = ready_biz(admin, f"Wording {purpose}", install=False, wm=wm, fresh=True)
        s = biz.put("/whatsapp/optin", json={"purpose": purpose}).json()["settings"]
        assert len(s["code"]) == 6 and set(s["code"]) <= code_alphabet and not set(s["code"]) & set("01OI")
        text = s["prefill_text"]
        assert f"Wording {purpose}" in text and text.endswith(f"Code: {s['code']}") and len(text) <= 200
        assert all(m in text for m in must)
        assert text == rules.optin_text(purpose, f"Wording {purpose}", s["code"])
    assert biz.get("/whatsapp/optin").json()["purpose_words"]["both"].startswith("updates about your visits")


def test_each_business_gets_its_own_code_and_it_never_changes(wm, admin):
    a = ready_biz(admin, "Code A", install=False)
    b = ready_biz(admin, "Code B", install=False, wm=wm, fresh=True)
    ca = a.put("/whatsapp/optin", json={"qr_enabled": True}).json()["settings"]["code"]
    cb = b.put("/whatsapp/optin", json={"qr_enabled": True}).json()["settings"]["code"]
    assert ca != cb
    assert a.put("/whatsapp/optin", json={"purpose": "both"}).json()["settings"]["code"] == ca  # changing the purpose keeps the code
    assert a.get("/whatsapp/optin").json()["settings"]["code"] == ca


def test_a_new_business_has_nothing_switched_on_and_settings_changes_are_audited(wm, admin):
    biz = ready_biz(admin, "Fresh Optin", install=False)
    g = biz.get("/whatsapp/optin").json()
    assert g["settings"] is None and g["keywords"] == [] and g["link_live"] is False and g["max_keywords"] == 5 and g["connected"] is True
    assert biz.put("/whatsapp/optin", json={"purpose": "everything"}).status_code == 422
    biz.put("/whatsapp/optin", json={"qr_enabled": True, "purpose": "both", "confirm_reply": False})
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.optin_settings'", t=biz.tenant_id)[0][0] == 1


# ===================================================================== the public QR page
def landing(biz):
    c = biz.post("/review-growth/campaigns", json={"name": "Front desk", "location_id": biz.location_id}).json()
    with TestClient(app, base_url="http://testserver") as client:
        r = client.get(f"/api/v1/public/reviews/{c['public_id']}", headers=UA)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_review_page_offers_a_click_to_chat_link_only_when_everything_is_in_place(wm, admin, monkeypatch):
    biz = ready_biz(admin, "Page Clinic", install=False)
    assert landing(biz)["whatsapp_optin"] is None  # not switched on
    biz.put("/whatsapp/optin", json={"qr_enabled": True})
    page = landing(biz)["whatsapp_optin"]
    assert set(page) == {"url", "purpose_words"} and page["purpose_words"] == "updates about your visits and enquiries"
    u = urlparse(page["url"])
    assert u.scheme == "https" and u.netloc == "wa.me" and u.path == "/15550100100" and parse_qs(u.query)["text"] == [prefill(biz)]  # the mock number, and the exact wording, encoded
    assert "98765" not in json.dumps(landing(biz))  # no customer data of any kind on the page
    monkeypatch.setattr(settings, "whatsapp_enabled", False)
    assert landing(biz)["whatsapp_optin"] is None
    monkeypatch.setattr(settings, "whatsapp_enabled", True)
    admin.put(f"/admin/tenants/{biz.tenant_id}/whatsapp-addon", json={"addon_key": None, "reason": "Cancelled by the owner"})
    assert landing(biz)["whatsapp_optin"] is None  # no add-on, no button
    grant_addon(admin, biz)
    biz.post("/whatsapp/connection/disconnect")
    assert landing(biz)["whatsapp_optin"] is None  # no connected number, no button
    other = make_business("Page Other")
    assert landing(other)["whatsapp_optin"] is None


def test_the_review_page_still_works_if_the_optin_lookup_fails(wm, admin, monkeypatch):
    biz = ready_biz(admin, "Page Safe", install=False)
    biz.put("/whatsapp/optin", json={"qr_enabled": True})
    monkeypatch.setattr(optin, "public_link", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    page = landing(biz)
    assert page["whatsapp_optin"] is None and page["state"] == "ok"


# ===================================================================== a customer opts in from the QR page
def test_the_exact_prefilled_message_records_consent_with_its_wording_time_and_source_and_confirms_once(wm, admin):
    biz = prepared(admin)
    text = prefill(biz)
    out = inbound(text)
    assert out["opt_ins"] == 1
    c = contacts(biz)[0]
    assert c["phone"] == "+919876543210" and c["source"] == "qr_click_to_chat" and c["utility"]["source"] == "qr_click_to_chat" and c["marketing"] is None  # visit updates only
    row = consents(biz)
    assert [r[0] for r in row] == ["utility"] and row[0][1] == "qr_click_to_chat" and row[0][2] == "optin-1" and row[0][3] == text and row[0][4] is not None and row[0][5] is None
    sent = wm.sent[-1]["template"]
    assert sent["name"] == "flowqr_optin_confirm_en" and [p["text"] for p in sent["components"][0]["parameters"]] == ["there", "Optin Clinic", "updates about your visits and enquiries"]
    m = messages(biz.tenant_id)
    assert len(m) == 1 and m[0][0] == "utility" and m[0][1] == "sent" and m[0][5].startswith("optin:")
    assert owner_query("SELECT kind FROM whatsapp_messages WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == "optin_confirm"
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.consent_grant'", t=biz.tenant_id)[0][0] == 1


def test_the_purpose_comes_only_from_the_wording_the_customer_sent(wm, admin):
    util = prepared(admin, "Purpose Util", purpose="utility")
    inbound(prefill(util), phone="919876540001")
    assert [r[0] for r in consents(util)] == ["utility"]
    mk = ready_biz(admin, "Purpose Offers", install=False, wm=wm, fresh=True)
    mk.post("/whatsapp/setup/prepare-messages", json={"include_optin": True})
    mk.put("/whatsapp/optin", json={"qr_enabled": True, "purpose": "marketing"})
    inbound(prefill(mk), phone="919876540002", phone_id=pid(mk))
    row = consents(mk)
    assert [r[0] for r in row] == ["marketing"] and "offers and updates" in row[0][3]  # offers consent, never visit updates
    assert wm.sent[-1]["template"]["name"] == "flowqr_optin_confirm_offers_en"  # a marketing confirmation: it needs the offers consent that was just recorded
    both = ready_biz(admin, "Purpose Both", install=False, wm=wm, fresh=True)
    both.post("/whatsapp/setup/prepare-messages", json={"include_optin": True})
    both.put("/whatsapp/optin", json={"qr_enabled": True, "purpose": "both"})
    inbound(prefill(both), phone="919876540003", phone_id=pid(both))
    assert [r[0] for r in consents(both)] == ["marketing", "utility"]


@pytest.mark.parametrize("how", ["edited_sentence", "code_only", "wrong_code", "extra_words", "other_business_text", "disabled", "empty"])
def test_a_message_that_is_not_exactly_the_wording_creates_nothing(wm, admin, how):
    biz = prepared(admin, f"Closed {how}")
    other = ready_biz(admin, f"Closed other {how}", install=False, wm=wm, fresh=True)
    other.put("/whatsapp/optin", json={"qr_enabled": True})
    text = prefill(biz)
    code = biz.get("/whatsapp/optin").json()["settings"]["code"]
    msg = {"edited_sentence": text.replace("Yes, send me", "Please do not send me"), "code_only": f"Code: {code}", "wrong_code": text.replace(code, "ZZZZZZ"),
           "extra_words": "hello " + text, "other_business_text": prefill(other), "disabled": text, "empty": ""}[how]
    if how == "disabled":
        biz.put("/whatsapp/optin", json={"qr_enabled": False})
    out = inbound(msg or "hi there")
    assert out.get("opt_ins", 0) == 0 and contacts(biz) == [] and consents(biz) == [] and wm.sent == []


def test_wording_differences_that_do_not_change_the_meaning_of_the_message_itself_are_accepted(wm, admin):
    biz = prepared(admin, "Lenient Clinic")
    inbound("  " + prefill(biz).upper().replace("CODE:", "Code:") .lower() + "  ")  # case and spacing only: the sentence is the same
    assert [r[0] for r in consents(biz)] == ["utility"]


def test_the_message_must_arrive_on_the_businesses_own_verified_number(wm, admin):
    biz = prepared(admin, "Own Number")
    text = prefill(biz)
    out = inbound(text, phone_id=base.uid(7))  # a number nobody has connected
    assert out["ignored_items"] == 1 and consents(biz) == [] and wm.sent == []
    other = ready_biz(admin, "Own Number Other", install=False, wm=wm, fresh=True)
    other.put("/whatsapp/optin", json={"qr_enabled": True})
    inbound(text)  # this business's text to this business's number: fine; and it never touches the other business
    assert len(consents(biz)) == 1 and consents(other) == []


def test_a_repeat_creates_no_second_consent_and_no_second_confirmation(wm, admin):
    biz = prepared(admin, "Repeat Clinic")
    text = prefill(biz)
    inbound(text)
    inbound(text)
    inbound(text, wamid="wamid.AGAIN")
    assert len(consents(biz)) == 1 and len(wm.sent) == 1 and len(contacts(biz)) == 1
    raw = payload(messages=[{"from": PHONE, "id": "wamid.SAME", "type": "text", "text": {"body": text}}])
    post_wh(raw)
    post_wh(raw)  # Meta redelivers the same body
    eid = base.event_id_for(raw)
    process(eid)
    assert process(eid) == {"skipped": "already_done"} and len(wm.sent) == 1


def test_stop_always_wins_and_only_the_customer_can_opt_in_again(wm, admin):
    biz = prepared(admin, "Stop Optin", purpose="marketing")
    biz.post("/whatsapp/setup/prepare-messages", json={"include_optin": True})
    text = prefill(biz)
    inbound(text)
    assert len(consents(biz)) == 1
    inbound("STOP")
    c = contacts(biz)[0]
    assert c["opted_out"] is True and c["marketing"] is None
    assert biz.post(f"/whatsapp/contacts/{c['id']}/consent", json={"purpose": "marketing", **OWNER}).json()["detail"]["code"] == "opted_out"  # the owner cannot
    sent_before = len(wm.sent)
    inbound(text)  # the customer themselves, with the exact offers wording
    c2 = contacts(biz)[0]
    assert c2["opted_out"] is False and c2["marketing"]["source"] == "qr_click_to_chat"
    assert len(wm.sent) == sent_before + 1  # and they get their confirmation again
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE tenant_id = :t AND purpose = 'marketing'", t=biz.tenant_id)[0][0] == 2  # the old consent stays as history


def test_joining_for_visit_updates_never_lifts_an_opt_out_of_offers(wm, admin):
    biz = prepared(admin, "Separate Optin")  # visit updates only
    c = add_contact(biz, "98765 43210", marketing=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{c['id']}/opt-out", json={"purpose": "marketing"})
    inbound(prefill(biz))
    got = contacts(biz)[0]
    assert got["utility"]["source"] == "qr_click_to_chat" and got["opted_out"] is True and got["marketing"] is None


def test_an_inbound_message_that_is_not_an_opt_in_keeps_no_text_beyond_the_keyword_check(wm, admin):
    biz = prepared(admin, "Privacy Optin")
    long_chat = "I would like to ask about my appointment next week please " * 3
    raw = payload(messages=[{"from": PHONE, "id": "wamid.CHAT", "type": "text", "text": {"body": long_chat}}])
    post_wh(raw)
    stored = owner_query("SELECT payload::text FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=hashlib.sha256(raw).hexdigest())[0][0]
    assert "appointment" not in stored  # a normal chat message is not kept
    text = prefill(biz)
    raw2 = payload(messages=[{"from": PHONE, "id": "wamid.JOIN", "type": "text", "text": {"body": text}}])
    post_wh(raw2)
    assert text in owner_query("SELECT payload::text FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=hashlib.sha256(raw2).hexdigest())[0][0].replace("\\u2019", "'")


# ===================================================================== keywords
def test_keywords_are_validated_limited_and_stored_in_lower_case(wm, admin):
    biz = ready_biz(admin, "Keyword Clinic", install=False)
    bad = {"ab": "invalid_keyword", "hello world": "invalid_keyword", "join!": "invalid_keyword", "x" * 21: "invalid_keyword", "yes": "invalid_keyword", "OK": "invalid_keyword", "stop": "invalid_keyword", "UNSUBSCRIBE": "invalid_keyword"}
    for k, code in bad.items():
        r = biz.post("/whatsapp/optin/keywords", json={"keyword": k})
        assert r.status_code in (422,) and (r.json().get("detail") if r.status_code == 422 else None) is not None, k
    ok = biz.post("/whatsapp/optin/keywords", json={"keyword": "JoinUs", "purpose": "marketing"})
    assert ok.status_code == 201 and ok.json()["keyword"] == "joinus" and ok.json()["wording"] == rules.keyword_wording("joinus", "marketing", "Keyword Clinic")
    assert 'Texting "JOINUS" to Keyword Clinic on WhatsApp means: I agree to receive offers and updates' in ok.json()["wording"] and "STOP" in ok.json()["wording"]
    assert biz.post("/whatsapp/optin/keywords", json={"keyword": "JOINUS"}).json()["detail"]["code"] == "keyword_exists"
    for k in ("alpha1", "beta22", "gamma3", "delta4"):
        assert biz.post("/whatsapp/optin/keywords", json={"keyword": k}).status_code == 201
    r = biz.post("/whatsapp/optin/keywords", json={"keyword": "epsilon5"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "too_many_keywords"  # five at most
    assert len(biz.get("/whatsapp/optin").json()["keywords"]) == 5
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.optin_keyword_add'", t=biz.tenant_id)[0][0] == 5


def test_a_keyword_that_is_the_whole_message_opts_in_with_the_wording_it_stands_for(wm, admin):
    biz = prepared(admin, "Join Clinic")
    kid = biz.post("/whatsapp/optin/keywords", json={"keyword": "JoinOffers", "purpose": "both"}).json()["id"]
    out = inbound(" joinoffers! ")
    assert out["opt_ins"] == 1
    c = contacts(biz)[0]
    assert c["source"] == "keyword_opt_in" and c["utility"]["source"] == "keyword_opt_in" and c["marketing"]["source"] == "keyword_opt_in"
    row = consents(biz)
    assert {r[0] for r in row} == {"marketing", "utility"} and all(r[3] == rules.keyword_wording("joinoffers", "both", "Join Clinic") and r[2] == "optin-1" for r in row)
    assert wm.sent[-1]["template"]["name"] == "flowqr_optin_confirm_en" and wm.sent[-1]["template"]["components"][0]["parameters"][2]["text"] == "updates about your visits and enquiries, and offers"
    assert biz.get("/whatsapp/optin").json()["keywords"][0]["id"] == kid


@pytest.mark.parametrize("msg", ["I want to joinoffers now", "joinoffers please", "join offers", "joinoffer", "xjoinoffers", ""])
def test_a_keyword_inside_a_sentence_or_a_near_miss_opts_in_nobody(wm, admin, msg):
    biz = prepared(admin, "Near Miss")
    biz.post("/whatsapp/optin/keywords", json={"keyword": "joinoffers"})
    out = inbound(msg or "hello")
    assert out.get("opt_ins", 0) == 0 and consents(biz) == [] and contacts(biz) == []


def test_a_disabled_or_deleted_keyword_stops_working_and_one_business_cannot_use_anothers(wm, admin):
    a = prepared(admin, "Kw A")
    b = ready_biz(admin, "Kw B", install=False, wm=wm, fresh=True)
    k = a.post("/whatsapp/optin/keywords", json={"keyword": "welcome"}).json()
    assert a.patch(f"/whatsapp/optin/keywords/{k['id']}", json={"enabled": False}).json()["enabled"] is False
    assert inbound("welcome").get("opt_ins", 0) == 0
    a.patch(f"/whatsapp/optin/keywords/{k['id']}", json={"enabled": True, "purpose": "marketing"})
    assert inbound("welcome", phone="919876540010")["opt_ins"] == 1 and [r[0] for r in consents(a)] == ["marketing"]
    assert b.patch(f"/whatsapp/optin/keywords/{k['id']}", json={"enabled": False}).status_code == 404 and b.delete(f"/whatsapp/optin/keywords/{k['id']}").status_code == 404
    assert a.delete(f"/whatsapp/optin/keywords/{k['id']}").status_code == 204
    assert inbound("welcome", phone="919876540011").get("opt_ins", 0) == 0
    b.post("/whatsapp/optin/keywords", json={"keyword": "welcome"})  # the same word is fine for another business: it only ever works on its own number
    assert b.get("/whatsapp/optin").json()["keywords"][0]["keyword"] == "welcome"


# ===================================================================== the confirmation goes through the normal gate
def test_consent_is_recorded_even_when_the_confirmation_cannot_be_sent(wm, admin, monkeypatch):
    biz = prepared(admin, "Gate Optin")
    text = prefill(biz)
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", False)
    inbound(text, phone="919876540020")
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", True)
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", True)
    inbound(text, phone="919876540021")
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", False)
    owner_exec("UPDATE whatsapp_templates SET approval_status = 'pending' WHERE tenant_id = :t AND template_name = 'flowqr_optin_confirm_en'", t=biz.tenant_id)
    inbound(text, phone="919876540022")
    owner_exec("UPDATE whatsapp_templates SET approval_status = 'approved' WHERE tenant_id = :t", t=biz.tenant_id)
    biz.put("/whatsapp/optin", json={"confirm_reply": False})
    inbound(text, phone="919876540023")
    assert len(consents(biz)) == 4 and wm.sent == [] and messages(biz.tenant_id) == []  # four customers opted in, none was messaged


def test_a_confirmation_does_not_use_up_the_offer_frequency_gap(wm, admin):
    biz = ready_biz(admin, "Gap Optin", install=False)
    biz.post("/whatsapp/setup/prepare-messages", json={"include_optin": True, "include_offer": True})
    biz.put("/whatsapp/optin", json={"qr_enabled": True, "purpose": "marketing"})
    inbound(prefill(biz), phone="919876540030")
    assert wm.sent[-1]["template"]["name"] == "flowqr_optin_confirm_offers_en"  # a marketing-category confirmation was just sent
    cid = contacts(biz)[0]["id"]
    r = send(biz, cid, key="offer", variables=["there", "Gap Optin", "10% off this week"])
    assert r.ok  # not "too soon": the confirmation the customer asked for is not an offer
    again = send(biz, cid, key="offer", variables=["there", "Gap Optin", "20% off this week"])
    assert (again.status, again.reason) == ("skipped", "too_soon")  # but a second offer is


def test_a_temporary_failure_retries_the_whole_event_without_double_consent_or_double_confirmation(wm, admin):
    biz = prepared(admin, "Retry Optin")
    text = prefill(biz)
    raw = payload(messages=[{"from": PHONE, "id": "wamid.RETRY", "type": "text", "text": {"body": text}}])
    post_wh(raw)
    eid = base.event_id_for(raw)
    wm.fail = {"send": 503}
    with pytest.raises(optin.TransientOptinError):
        process(eid)
    assert consents(biz) == [] and messages(biz.tenant_id) == []  # the failed attempt left nothing behind
    wm.fail = {}
    process(eid)
    assert len(consents(biz)) == 1 and len(wm.sent) == 1 and len(messages(biz.tenant_id)) == 1


def test_the_worker_task_retries_a_temporary_confirmation_failure(wm, admin):
    from app.workers.tasks import whatsapp_process_event
    biz = prepared(admin, "Task Optin")
    raw = payload(messages=[{"from": PHONE, "id": "wamid.TASKJ", "type": "text", "text": {"body": prefill(biz)}}])
    post_wh(raw)
    wm.fail = {"send": 503}
    res = whatsapp_process_event.apply(args=[str(base.event_id_for(raw))])
    assert res.failed() is False or res.state in ("RETRY", "FAILURE", "SUCCESS")
    wm.fail = {}
    assert consents(biz) == []  # nothing committed by the failed pass


# ===================================================================== records, export, deletion, isolation
def test_the_opt_in_source_shows_on_the_customer_and_in_the_export(wm, admin):
    biz = prepared(admin, "Export Optin")
    biz.post("/whatsapp/optin/keywords", json={"keyword": "joinme", "purpose": "marketing"})
    inbound(prefill(biz), phone="919876540040")
    inbound("joinme", phone="919876540041")
    add_contact(biz, "98765 40042", utility=True, **OWNER)
    rows = {c["phone"]: c for c in contacts(biz)}
    assert rows["+919876540040"]["utility"]["source"] == "qr_click_to_chat" and rows["+919876540041"]["marketing"]["source"] == "keyword_opt_in" and rows["+919876540042"]["utility"]["source"] == "owner_entry"
    csv = biz.get("/whatsapp/contacts/export").text.splitlines()
    assert csv[0].startswith("phone,name,tags,marketing_consent_since,marketing_consent_source,utility_consent_since,utility_consent_source,opted_out_of_marketing,source,added")
    body = "\n".join(csv)
    assert "qr_click_to_chat" in body and "keyword_opt_in" in body and "owner_entry" in body


def test_the_account_export_and_deletion_cover_the_optin_data(wm, admin):
    biz = prepared(admin, "Account Optin")
    biz.post("/whatsapp/optin/keywords", json={"keyword": "joinus"})
    inbound(prefill(biz), phone="919876540050")
    z = zipfile.ZipFile(io.BytesIO(biz.get("/account/export").content))
    assert {"whatsapp_optin_settings.json", "whatsapp_optin_keywords.json", "whatsapp_consents.json"} <= set(z.namelist())
    assert json.loads(z.read("whatsapp_optin_keywords.json"))[0]["keyword"] == "joinus"
    assert any(c["source"] == "qr_click_to_chat" and c["wording_version"] == "optin-1" for c in json.loads(z.read("whatsapp_consents.json")))
    db = system_session()
    try:
        from sqlalchemy import text
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": biz.tenant_id})
        db.commit()
    finally:
        db.close()
    for t in ("whatsapp_optin_settings", "whatsapp_optin_keywords", "whatsapp_consents", "whatsapp_contacts"):
        assert owner_query(f"SELECT count(*) FROM {t} WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0, t


def test_a_business_sees_and_changes_only_its_own_optin_settings(wm, admin):
    a = prepared(admin, "Iso Optin A")
    b = ready_biz(admin, "Iso Optin B", install=False, wm=wm, fresh=True)
    a.post("/whatsapp/optin/keywords", json={"keyword": "secretword"})
    assert b.get("/whatsapp/optin").json()["settings"] is None and b.get("/whatsapp/optin").json()["keywords"] == []
    from sqlalchemy import text

    from app.core.db import SessionLocal, set_rls_context
    for table in ("whatsapp_optin_settings", "whatsapp_optin_keywords"):
        assert owner_query("SELECT relforcerowsecurity FROM pg_class WHERE relname = :t", t=table)[0][0] is True
        with SessionLocal() as db:
            set_rls_context(db, tenant_id=uuid.UUID(b.tenant_id))
            assert db.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": a.tenant_id}).scalar() == 0, table


def test_the_optin_routes_answer_disabled_while_whatsapp_is_off():
    biz = make_business("Off Optin")
    for method, url in (("GET", "/whatsapp/optin"), ("PUT", "/whatsapp/optin"), ("POST", "/whatsapp/optin/keywords")):
        r = biz.request(method, url, json={"qr_enabled": True, "keyword": "welcome"}) if method != "GET" else biz.get(url)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "whatsapp_disabled", url


def test_the_optin_routes_are_in_the_access_manifest_with_the_right_roles():
    by = {(m, p): k for k, m, p in (ln.split("\t") for ln in open("tests/route_access_manifest.txt", encoding="utf-8").read().splitlines() if "/whatsapp/optin" in ln)}
    assert by == {("GET", "/api/v1/whatsapp/optin"): "member", ("PUT", "/api/v1/whatsapp/optin"): "role-admin", ("POST", "/api/v1/whatsapp/optin/keywords"): "role-admin",
                  ("PATCH", "/api/v1/whatsapp/optin/keywords/{keyword_id}"): "role-admin", ("DELETE", "/api/v1/whatsapp/optin/keywords/{keyword_id}"): "role-admin"}
    assert re and wh and connect


def test_the_migration_added_the_new_sources_and_tables_and_downgrade_is_reversible_in_shape():
    srcs = owner_query("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_wa_consent_source'")[0][0]
    assert "qr_click_to_chat" in srcs and "keyword_opt_in" in srcs
    assert owner_query("SELECT count(*) FROM information_schema.columns WHERE table_name = 'whatsapp_messages' AND column_name = 'kind'")[0][0] == 1
    role = settings.database_url.split("//")[1].split(":")[0]
    assert owner_query("SELECT has_table_privilege(:r, 'public.whatsapp_optin_keywords', 'DELETE')", r=role)[0][0] is True
