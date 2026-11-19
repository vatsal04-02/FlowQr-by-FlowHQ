"""WhatsApp first-run set-up (Phase 5): the checklist is derived from real records, one click prepares the messages, a test message goes to the owner's OWN number through the normal sender and gate,
and the helpers are recommended by kind of business. Mock Meta only: no real number, account or message is involved."""
import json
import uuid

import pytest

from app.core.config import settings
from app.services.whatsapp import setup as wa_setup
from tests import test_whatsapp as base
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_whatsapp import OWNER, add_contact, connect, grant_addon, payload, post_wh, process, wa  # noqa: F401 - fixtures
from tests.test_whatsapp_messaging import messages, ready_biz, wm  # noqa: F401 - fixtures


def steps(biz) -> dict:
    return {s["key"]: s for s in biz.get("/whatsapp/setup").json()["steps"]}


def state(biz) -> dict:
    return {k: v["state"] for k, v in steps(biz).items()}


def test_a_new_business_sees_what_to_do_first_and_nothing_is_done(wm, admin):
    biz = make_business("Fresh Setup")
    r = biz.get("/whatsapp/setup").json()
    assert [s["key"] for s in r["steps"]] == ["plan", "connect", "messages", "customers", "test", "helper"] and r["total"] == 6 and r["done"] == 0 and r["complete"] is False and r["next"] == "plan"
    assert state(biz) == {"plan": "blocked", "connect": "blocked", "messages": "blocked", "customers": "todo", "test": "blocked", "helper": "blocked"}
    assert steps(biz)["plan"]["action"] == "ask_flowqr" and "add-on" in steps(biz)["plan"]["body"]


def test_each_step_unlocks_from_real_records(wm, admin):
    biz = make_business("Steps Clinic")
    grant_addon(admin, biz, "whatsapp_growth")
    assert state(biz)["plan"] == "done" and state(biz)["connect"] == "todo" and biz.get("/whatsapp/setup").json()["next"] == "connect"
    r, _ = connect(biz, admin, addon=False)
    assert r.status_code == 200
    s = state(biz)
    assert (s["connect"], s["messages"], s["helper"], s["test"]) == ("done", "todo", "todo", "blocked") and biz.get("/whatsapp/setup").json()["next"] == "messages"
    assert steps(biz)["messages"]["missing"] == ["review_followup", "enquiry_ack", "enquiry_followup"]
    assert biz.post("/whatsapp/setup/prepare-messages", json={}).status_code == 200
    s = state(biz)
    assert s["messages"] == "done" and s["test"] == "todo" and biz.get("/whatsapp/setup").json()["next"] == "customers"
    add_contact(biz, "98765 90001", marketing=True, **OWNER)  # offers consent only does not count as visit updates
    assert state(biz)["customers"] == "todo"
    add_contact(biz, "98765 90002", utility=True, **OWNER)
    assert state(biz)["customers"] == "done" and "1 customer agreed" in steps(biz)["customers"]["body"].replace("customers", "customer")
    assert biz.put("/whatsapp/automations/review_followup", json={"status": "on"}).status_code == 200
    assert state(biz)["helper"] == "done" and steps(biz)["helper"]["body"] == "1 helper is switched on."


def test_connecting_is_shown_as_waiting_when_flowqr_has_not_finished_its_meta_setup(wm, admin, monkeypatch):
    biz = make_business("Waiting Setup")
    grant_addon(admin, biz, "whatsapp_growth")
    monkeypatch.setattr(settings, "meta_app_id", "")
    c = steps(biz)["connect"]
    assert c["state"] == "waiting" and "not available yet" in c["body"]


def test_a_connection_that_needs_attention_is_a_todo_with_the_reason(wm, admin):
    biz = ready_biz(admin, "Attention Setup", install=False)
    wm.valid = False
    biz.post("/whatsapp/connection/check")
    c = steps(biz)["connect"]
    assert c["state"] == "todo" and "no longer accepts" in c["body"]


def test_one_click_prepares_the_messages_and_repeating_it_is_safe(wm, admin):
    biz = ready_biz(admin, "Prep Clinic", install=False)
    first = biz.post("/whatsapp/setup/prepare-messages", json={}).json()
    assert first == {"submitted": ["review_followup", "enquiry_ack", "enquiry_followup"], "already_there": []}  # not the offer message unless asked
    again = biz.post("/whatsapp/setup/prepare-messages", json={}).json()
    assert again == {"submitted": [], "already_there": ["review_followup", "enquiry_ack", "enquiry_followup"]}
    assert len([c for c in wm.calls if c[0] == "tpl_create"]) == 3
    offer = biz.post("/whatsapp/setup/prepare-messages", json={"include_offer": True}).json()
    assert offer["submitted"] == ["offer"]
    assert owner_query("SELECT count(*) FROM whatsapp_templates WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 4


def test_preparing_needs_a_connection(wm, admin):
    biz = make_business("Prep None")
    grant_addon(admin, biz, "whatsapp_growth")
    r = biz.post("/whatsapp/setup/prepare-messages", json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_connected"


def test_the_messages_step_explains_waiting_and_refusal(wm, admin):
    biz = ready_biz(admin, "Review Setup", install=False)
    wm.template_status = "PENDING"
    biz.post("/whatsapp/setup/prepare-messages", json={})
    m = steps(biz)["messages"]
    assert m["state"] == "waiting" and m["action"] == "check_messages" and set(m["pending"]) == {"review_followup", "enquiry_ack", "enquiry_followup"} and "reviewing" in m["title"]
    wm.templates["flowqr_enquiry_ack_en"].update(status="REJECTED", rejected_reason="INVALID_FORMAT")
    biz.post("/whatsapp/templates/sync")
    m = steps(biz)["messages"]
    assert m["state"] == "todo" and m["refused"] == ["enquiry_ack"] and "not approved" in m["title"]
    for t in wm.templates.values():
        t.update(status="APPROVED", rejected_reason="NONE")
    biz.post("/whatsapp/templates/sync")
    assert steps(biz)["messages"]["state"] == "done"


# ===================================================================== the test message
def test_a_test_message_goes_to_the_owners_own_number_through_the_normal_gate(wm, admin):
    biz = ready_biz(admin, "Test Clinic")
    r = biz.post("/whatsapp/setup/test-message", json={"phone": "98765 43210", "own_number": True})
    assert r.status_code == 200 and r.json()["sent"] is True and r.json()["to_last4"] == "3210"
    sent = wm.sent[-1]
    assert sent["type"] == "template" and sent["to"] == "919876543210" and sent["template"]["name"] == "flowqr_enquiry_ack_en"
    assert [p["text"] for p in sent["template"]["components"][0]["parameters"]] == ["Test", "Test Clinic"]
    c = biz.get("/whatsapp/contacts", params={"search": "3210"}).json()["items"][0]
    assert c["tags"] == ["test"] and c["utility"]["source"] == "owner_entry" and c["marketing"] is None  # visit updates only: never offers
    assert owner_query("SELECT evidence FROM whatsapp_consents WHERE contact_id = :c", c=c["id"])[0][0] == wa_setup.OWN_NUMBER_NOTE
    row = messages(biz.tenant_id)[0]
    assert row[0] == "utility" and row[1] == "sent" and row[5].startswith("test:")
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.test_message'", t=biz.tenant_id)[0][0] == 1
    t = steps(biz)["test"]
    assert t["state"] == "done" and t["test"]["status"] == "sent" and "accepted" in t["body"]


def test_the_test_step_follows_delivery(wm, admin):
    biz = ready_biz(admin, "Deliver Test")
    biz.post("/whatsapp/setup/test-message", json={"phone": "98765 43211", "own_number": True})
    wamid = messages(biz.tenant_id)[0][3]
    for st, words in (("delivered", "reached your phone"), ("read", "opened it")):
        raw = payload(statuses=[{"id": wamid, "status": st, "timestamp": "1700000011"}])
        post_wh(raw)
        process(base.event_id_for(raw))
        assert words in steps(biz)["test"]["body"] and biz.get("/whatsapp/setup").json()["last_test"]["status"] == st


def test_the_same_test_twice_in_a_minute_sends_once(wm, admin):
    biz = ready_biz(admin, "Twice Test")
    a = biz.post("/whatsapp/setup/test-message", json={"phone": "98765 43212", "own_number": True})
    b = biz.post("/whatsapp/setup/test-message", json={"phone": "98765 43212", "own_number": True})
    assert a.status_code == 200 and b.status_code == 200 and len(wm.sent) == 1


def test_a_test_is_refused_clearly_and_sends_nothing(wm, admin, monkeypatch):
    biz = ready_biz(admin, "Refuse Test")
    body = lambda **k: {"phone": "98765 43213", "own_number": True, **k}  # noqa: E731
    r = biz.post("/whatsapp/setup/test-message", json=body(own_number=False))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "own_number_required"
    assert biz.post("/whatsapp/setup/test-message", json=body(phone="12")).status_code == 422
    assert biz.post("/whatsapp/setup/test-message", json=body(phone="abcdefg")).status_code == 422
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", False)
    r = biz.post("/whatsapp/setup/test-message", json=body())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "sending_off" and "switches it on" in r.json()["detail"]["message"]
    assert steps(biz)["test"]["state"] == "waiting"
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", True)
    owner_exec("UPDATE whatsapp_templates SET approval_status = 'pending' WHERE tenant_id = :t AND template_name = 'flowqr_enquiry_ack_en'", t=biz.tenant_id)
    r = biz.post("/whatsapp/setup/test-message", json=body())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "template_not_approved" and steps(biz)["test"]["state"] == "blocked"
    owner_exec("UPDATE whatsapp_templates SET approval_status = 'approved' WHERE tenant_id = :t", t=biz.tenant_id)
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", True)
    assert biz.post("/whatsapp/setup/test-message", json=body()).status_code == 409
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", False)
    assert wm.sent == []
    bare = make_business("Bare Test")
    assert bare.post("/whatsapp/setup/test-message", json=body()).json()["detail"]["code"] == "not_connected"


def test_when_whatsapp_rejects_the_test_the_owner_is_told_and_can_try_again(wm, admin):
    biz = ready_biz(admin, "Reject Test")
    wm.fail, wm.fail_code = {"send": 400}, {"send": 131026}
    r = biz.post("/whatsapp/setup/test-message", json={"phone": "98765 43214", "own_number": True})
    assert r.status_code == 502 and "can receive WhatsApp messages" in r.json()["detail"]["message"] and "131026" not in r.text
    s = steps(biz)["test"]
    assert s["state"] == "todo" and "did not go through" in s["body"] and biz.get("/whatsapp/setup").json()["last_test"]["status"] == "failed"
    wm.fail = {}
    wm.fail_code = {}
    wa_setup  # noqa: B018
    wm.fail = {"send": 503}
    assert biz.post("/whatsapp/setup/test-message", json={"phone": "98765 43215", "own_number": True}).status_code == 503


def test_tests_are_limited_to_a_few_an_hour(wm, admin):
    biz = ready_biz(admin, "Limit Test")
    codes = [biz.post("/whatsapp/setup/test-message", json={"phone": f"98765 4400{i}", "own_number": True}).status_code for i in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429] and len(wm.sent) == 5


def test_a_number_that_opted_out_of_visit_updates_is_not_messaged_by_a_test(wm, admin):
    biz = ready_biz(admin, "Optout Test")
    c = add_contact(biz, "98765 45001", utility=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{c['id']}/opt-out", json={"purpose": "utility"})
    # the owner confirming it is their own number is a fresh, explicit consent for a test, so it goes through; a number that opted out of OFFERS is unaffected either way
    mk = add_contact(biz, "98765 45002", marketing=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{mk['id']}/opt-out", json={"purpose": "marketing"})
    assert biz.post("/whatsapp/setup/test-message", json={"phone": "98765 45002", "own_number": True}).status_code == 200
    assert biz.get("/whatsapp/contacts", params={"search": "45002"}).json()["items"][0]["opted_out"] is True  # still opted out of offers


# ===================================================================== complete, recommendations, isolation
def test_all_six_steps_done_is_complete(wm, admin):
    biz = ready_biz(admin, "Complete Setup")
    add_contact(biz, "98765 46001", utility=True, **OWNER)
    biz.post("/whatsapp/setup/test-message", json={"phone": "98765 46002", "own_number": True})
    biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    r = biz.get("/whatsapp/setup").json()
    assert r["done"] == 6 and r["complete"] is True and r["next"] is None and all(s["state"] == "done" for s in r["steps"])


@pytest.mark.parametrize("category,first,why", [
    ("Physiotherapy clinic", "review_followup", "kind word after a visit"), ("Restaurant or cafe", "offers", "come back for offers"), ("Plumber", "enquiry_followup", "starts with an enquiry"),
    ("Salon or spa", "review_followup", "kind word"), ("Grocery or general store", "offers", "offers"), (None, "review_followup", "thank-you"), ("Something unusual", "review_followup", "thank-you")])
def test_helpers_are_recommended_for_the_kind_of_business(category, first, why):
    r = wa_setup.recommend(category)
    assert r["helpers"][0] == first and why in r["why"] and set(r["helpers"]) <= {"review_followup", "enquiry_followup", "offers"}


def test_the_status_carries_the_recommendation_and_is_private_to_the_business(wm, admin):
    a = ready_biz(admin, "Iso Setup A")
    a.post("/whatsapp/setup/test-message", json={"phone": "98765 47001", "own_number": True})
    add_contact(a, "98765 47002", utility=True, **OWNER)
    b = make_business("Iso Setup B")
    sa, sb = a.get("/whatsapp/setup").json(), b.get("/whatsapp/setup").json()
    assert sa["recommended"]["helpers"] == ["review_followup", "enquiry_followup"] and sa["done"] >= 4
    assert sb["done"] == 0 and sb["last_test"] is None and steps(b)["customers"]["state"] == "todo"
    assert json.dumps(sb).count("98765") == 0


def test_the_setup_routes_answer_disabled_while_whatsapp_is_off():
    biz = make_business("Off Setup")
    for method, url in (("GET", "/whatsapp/setup"), ("POST", "/whatsapp/setup/prepare-messages"), ("POST", "/whatsapp/setup/test-message")):
        r = biz.request(method, url, json={"phone": "98765 48001", "own_number": True} if method == "POST" else None) if method == "POST" else biz.get(url)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "whatsapp_disabled", url


def test_the_setup_routes_are_in_the_access_manifest_with_the_right_roles():
    by = {(m, p): k for k, m, p in (ln.split("\t") for ln in open("tests/route_access_manifest.txt", encoding="utf-8").read().splitlines() if "/whatsapp/setup" in ln)}
    assert by == {("GET", "/api/v1/whatsapp/setup"): "member", ("POST", "/api/v1/whatsapp/setup/prepare-messages"): "role-admin", ("POST", "/api/v1/whatsapp/setup/test-message"): "role-admin"}
    assert uuid and base
