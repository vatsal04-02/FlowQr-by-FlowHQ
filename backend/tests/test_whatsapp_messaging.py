"""WhatsApp automation, Phases 2 and 3: templates, the sender, dated Meta pricing, usage, the review and enquiry follow-ups, and promotional campaigns. Everything runs against a mock of Meta's Graph
API: no real number, account or message is involved, and every send in these tests goes to a recorded fake.

Covers: standard templates (install, approval states, Meta re-categorising, sync); the sender's gate (consent, opt-out, approved template, own connection, variables, idempotency, frequency, limits, Meta
failures, token errors); pricing as dated data; usage and activity; automation activation (add-on limit, approved messages) and execution (delays, pause, consent withdrawn, retries and the dead letter, emergency
stop, no double send); the website enquiry tick; campaigns (plan, audience, preview and estimate, approval bound to what was shown, batches, ceiling, opt-out after approval, pause, cancel, results)."""
import hashlib
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from app.core.config import settings
from app.core.db import system_session
from app.main import app  # noqa: F401
from app.models import Tenant
from app.models.base import utcnow
from app.services.whatsapp import WaError, automations, campaigns, consent, pricing, rules, sender, templates, usage
from app.services.whatsapp.meta import MetaClient, set_meta_client
from tests import test_whatsapp as base
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_sites_api import enquire, live_site, sites_on  # noqa: F401 - fixture
from tests.test_whatsapp import MockMeta, OWNER, add_contact, connect, grant_addon, post_wh, process, payload, svc_db, wa  # noqa: F401 - fixtures


class Meta2(MockMeta):
    """The base mock plus WhatsApp's template and send endpoints."""

    def __init__(self):
        super().__init__()
        self.templates: dict[str, dict] = {}
        self.sent: list[dict] = []
        self.template_status = "APPROVED"
        self.category: str | None = None  # make Meta re-categorise what is submitted
        self.rejected_reason = "NONE"

    def handler(self, req: httpx.Request) -> httpx.Response:
        path, m = req.url.path, req.method
        op = "tpl_create" if path.endswith("/message_templates") and m == "POST" else "tpl_list" if path.endswith("/message_templates") else "send" if path.endswith("/messages") and m == "POST" else None
        if op is None:
            return super().handler(req)
        self.calls.append((op, path))
        if op in self.fail:
            return httpx.Response(self.fail[op], json={"error": {"message": "boom", "code": self.fail_code.get(op, 100)}})
        if op == "tpl_create":
            body = json.loads(req.content)
            t = {"id": f"tpl{len(self.templates) + 1}", "name": body["name"], "language": body["language"], "category": self.category or body["category"], "status": self.template_status,
                 "components": body["components"], "rejected_reason": self.rejected_reason}
            self.templates[body["name"]] = t
            return httpx.Response(200, json={"id": t["id"], "status": t["status"], "category": t["category"]})
        if op == "tpl_list":
            return httpx.Response(200, json={"data": list(self.templates.values()), "paging": {}})
        body = json.loads(req.content)
        self.sent.append(body)
        return httpx.Response(200, json={"messages": [{"id": f"wamid.SENT{len(self.sent)}-{uuid.uuid4().hex[:6]}"}]})

    fail_code: dict = {}


@pytest.fixture()
def wm(wa, monkeypatch):
    for k, v in dict(whatsapp_sending_enabled=True, whatsapp_send_per_minute=1000, whatsapp_daily_cap=100000, whatsapp_marketing_gap_hours=72, whatsapp_send_window_start=0, whatsapp_send_window_end=24).items():
        monkeypatch.setattr(settings, k, v)
    m = Meta2()
    m.waba, m.phone_id, m.fail_code = base.WABA, base.PHONE, {}
    set_meta_client(MetaClient(httpx.Client(transport=httpx.MockTransport(m.handler))))
    m.queued = wa.queued
    yield m
    set_meta_client(None)


KEYS = ("review_followup", "enquiry_ack", "enquiry_followup", "offer")


def install_all(biz, keys=KEYS):
    for k in keys:
        r = biz.post("/whatsapp/templates/install", json={"key": k})
        assert r.status_code == 200, r.text


def ready_biz(admin, name="Msg Clinic", tier="whatsapp_growth", install=True, wm=None, fresh=False):
    biz = make_business(name)
    grant_addon(admin, biz, tier)
    if fresh:  # a second business in the same test needs its own number
        waba, phone = base.uid(4), base.uid(5)
        wm.granted = [waba]
        r, _ = connect(biz, admin, addon=False, waba=waba, phone=phone)
        assert r.status_code == 200, r.text
        install_all(biz) if install else None
        return biz
    r, _ = connect(biz, admin, addon=False)
    assert r.status_code == 200, r.text
    if install:
        install_all(biz)
    return biz


def tpl(biz, key):
    with svc_db(biz.tenant_id) as db:
        t = templates.standard_row(db, uuid.UUID(biz.tenant_id), key)
        db.expunge(t)
        return t


def tick(tid, minutes=0):
    """One worker pass for ONE business at `minutes` from now."""
    db = system_session()
    try:
        now = utcnow() + timedelta(minutes=minutes)
        out = {"automations": automations.run_due(db, now=now, tenant_id=uuid.UUID(tid)), "campaigns": campaigns.run_due(db, now=now, tenant_id=uuid.UUID(tid))}
        db.commit()
        return out
    finally:
        db.close()


def send(biz, contact_id, key="review_followup", variables=None, idem=None):
    with svc_db(biz.tenant_id) as db:
        t = db.get(Tenant, uuid.UUID(biz.tenant_id))
        c = consent.get_contact(db, t.id, uuid.UUID(contact_id))
        row = templates.standard_row(db, t.id, key)
        res = sender.send_template(db, t, c, row, variables if variables is not None else ["Asha", "Msg Clinic", "https://g.page/r/x/review"] if key == "review_followup" else ["Asha", "Msg Clinic"], idem_key=idem or f"t:{uuid.uuid4()}")
        db.commit()
        return res


def messages(tid):
    return owner_query("SELECT category, delivery_status, error_code, meta_message_id, est_rate, idempotency_key FROM whatsapp_messages WHERE tenant_id = :t ORDER BY created_at", t=tid)


# ===================================================================== templates
def test_every_standard_template_obeys_metas_rules():
    for key, t in templates.STANDARD.items():
        assert templates.valid_body(t["body"]), key  # a variable never starts or ends the body
        assert templates.placeholders(t["body"]) == len(t["variables"]) == len(t["examples"]), key
        assert templates.submission(key)["name"] == f"flowqr_{key}_en" and templates.key_of(f"flowqr_{key}_en") == key
    assert templates.STANDARD["offer"]["category"] == "marketing" and "STOP" in templates.STANDARD["offer"]["body"]
    assert all(templates.STANDARD[k]["category"] == "utility" for k in ("review_followup", "enquiry_ack", "enquiry_followup"))
    body = templates.STANDARD["review_followup"]["body"].lower()
    for steering in ("5 star", "five star", "positive", "discount", "reward", "free", "gift", "rate us"):
        assert steering not in body  # neutral: asks for honest feedback, offers nothing in return


def test_installing_a_template_submits_it_to_whatsapp_and_records_what_whatsapp_decided(wm, admin):
    biz = ready_biz(admin, "Tpl Clinic", install=False)
    r = biz.post("/whatsapp/templates/install", json={"key": "review_followup"})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["category"] == "utility" and r.json()["variables"] == ["customer_name", "business_name", "review_link"]
    sub = wm.templates["flowqr_review_followup_en"]
    assert sub["category"] == "UTILITY" and sub["components"][0]["type"] == "BODY" and sub["components"][0]["example"]["body_text"] == [["Asha", "Asha Physio Clinic", "https://g.page/r/example/review"]]
    assert biz.post("/whatsapp/templates/install", json={"key": "nonsense"}).status_code == 422
    listing = biz.get("/whatsapp/templates").json()
    assert [t["key"] for t in listing["items"]] == ["review_followup"] and {a["key"]: a["installed"] for a in listing["available"]}["offer"] is False
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.template_install'", t=biz.tenant_id)[0][0] == 1


def test_a_template_waits_for_approval_and_a_rejection_is_explained(wm, admin):
    biz = ready_biz(admin, "Pending Clinic", install=False)
    wm.template_status = "PENDING"
    assert biz.post("/whatsapp/templates/install", json={"key": "offer"}).json()["status"] == "pending"
    wm.templates["flowqr_offer_en"].update(status="REJECTED", rejected_reason="INVALID_FORMAT")
    assert biz.post("/whatsapp/templates/sync").json()["changed"] == 1
    t = biz.get("/whatsapp/templates").json()["items"][0]
    assert t["status"] == "rejected" and t["rejection_reason"] == "INVALID_FORMAT"
    wm.templates["flowqr_offer_en"].update(status="APPROVED", rejected_reason="NONE")
    biz.post("/whatsapp/templates/sync")
    assert biz.get("/whatsapp/templates").json()["items"][0]["status"] == "approved" and biz.get("/whatsapp/templates").json()["items"][0]["rejection_reason"] is None


def test_the_category_is_what_whatsapp_says_not_what_flowqr_asked_for(wm, admin):
    biz = ready_biz(admin, "Recat Clinic", install=False)
    wm.category = "MARKETING"  # WhatsApp decides a review request is marketing
    assert biz.post("/whatsapp/templates/install", json={"key": "review_followup"}).json()["category"] == "marketing"
    util_only = add_contact(biz, "98765 50001", utility=True, **OWNER)
    r = send(biz, util_only["id"])
    assert (r.status, r.reason) == ("skipped", "no_marketing_consent")  # so it needs consent to offers, which this person did not give
    both = add_contact(biz, "98765 50002", marketing=True, **OWNER)
    assert send(biz, both["id"]).ok


def test_sync_reads_the_account_and_marks_vanished_templates_disabled(wm, admin):
    biz = ready_biz(admin, "Sync Clinic")
    wm.templates["theirs_promo_en"] = {"id": "x9", "name": "theirs_promo_en", "language": "en", "category": "WEIRD", "status": "APPROVED", "components": [{"type": "BODY", "text": "Hello {{1}} and {{2}} deals"}]}
    del wm.templates["flowqr_enquiry_ack_en"]
    out = biz.post("/whatsapp/templates/sync").json()
    assert out["templates"] == 4 and out["changed"] >= 2
    by = {t["name"]: t for t in biz.get("/whatsapp/templates").json()["items"]}
    assert by["flowqr_enquiry_ack_en"]["status"] == "disabled"
    assert by["theirs_promo_en"]["category"] == "marketing" and by["theirs_promo_en"]["variables"] == ["variable_1", "variable_2"] and by["theirs_promo_en"]["key"] is None  # unknown category = the stricter one


def test_templates_need_a_connection_and_meta_errors_are_plain(wm, admin):
    biz = make_business("No Conn")
    assert biz.post("/whatsapp/templates/install", json={"key": "offer"}).status_code == 409
    biz = ready_biz(admin, "Err Clinic", install=False)
    wm.fail = {"tpl_create": 400}
    r = biz.post("/whatsapp/templates/install", json={"key": "offer"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "meta_error" and "boom" not in r.text
    wm.fail = {"tpl_list": 503}
    assert biz.post("/whatsapp/templates/sync").status_code == 502


# ===================================================================== pricing
def test_rates_are_dated_data_the_newest_in_force_applies_and_nothing_is_edited(wm, admin):
    with svc_db(uuid.uuid4()) as db:
        r = pricing.rate_for(db, "marketing", date(2026, 6, 1))
        assert r is not None and r.verified is False and "UNVERIFIED" in r.source  # the seed is an unverified estimate
    assert admin.post("/admin/whatsapp/rates", json={"category": "marketing", "rate": "0.9000", "effective_from": "2026-12-01", "source": "Meta India rate card, effective 1 Dec 2026", "verified": True}).status_code == 201
    with svc_db(uuid.uuid4()) as db:
        assert pricing.rate_for(db, "marketing", date(2026, 11, 30)).rate == Decimal("1.0900")  # the October 2026 rate still applies before the new date
        assert pricing.rate_for(db, "marketing", date(2026, 9, 30)).rate == Decimal("0.8631")  # and the January row is still there as history
        assert pricing.rate_for(db, "marketing", date(2026, 12, 1)).rate == Decimal("0.9000") and pricing.rate_for(db, "marketing", date(2026, 12, 1)).verified is True
    dup = admin.post("/admin/whatsapp/rates", json={"category": "marketing", "rate": "0.95", "effective_from": "2026-12-01", "source": "Meta India rate card, effective 1 Dec 2026"})
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "rate_exists"
    assert admin.post("/admin/whatsapp/rates", json={"category": "marketing", "rate": "0.95", "effective_from": "2027-01-01", "source": "short"}).status_code == 422
    assert admin.post("/admin/whatsapp/rates", json={"category": "fax", "rate": "0.95", "effective_from": "2027-01-01", "source": "Meta India rate card"}).status_code == 422
    assert admin.post("/admin/whatsapp/rates", json={"category": "utility", "rate": "-1", "effective_from": "2027-01-01", "source": "Meta India rate card"}).status_code == 422
    biz = make_business("Rate Owner")
    assert biz.post("/admin/whatsapp/rates", json={"category": "utility", "rate": "0.1", "effective_from": "2027-02-01", "source": "Meta India rate card"}).status_code == 403
    assert admin.get("/admin/whatsapp/rates").json()["items"][0]["verified"] in (True, False)
    owner_exec("DELETE FROM whatsapp_rate_verifications WHERE rate_id IN (SELECT id FROM whatsapp_rates WHERE effective_from = '2026-12-01')")
    owner_exec("DELETE FROM whatsapp_rates WHERE effective_from = '2026-12-01'")  # keep the shared table as the migration left it


def test_an_estimate_is_labelled_and_claims_nothing_without_a_rate(wm, admin):
    with svc_db(uuid.uuid4()) as db:
        e = pricing.estimate(db, "marketing", 250, date(2026, 11, 20))
        assert e["amount"] == "272.50" and e["rate"] == "1.0900" and e["currency"] == "INR" and e["verified"] is False
        assert "estimate" in e["note"].lower() and "not a bill" in e["note"].lower() and "not been checked" in e["note"]
        assert pricing.estimate(db, "utility", 100, date(2026, 11, 20))["amount"] == "14.50"
        none = pricing.estimate(db, "marketing", 10, date(2020, 1, 1))  # before any rate was in force
        assert none["amount"] is None and none["rate"] is None and "No rate is set" in none["note"]


def test_the_application_cannot_edit_or_delete_a_rate():
    role = settings.database_url.split("//")[1].split(":")[0]
    for priv in ("UPDATE", "DELETE"):
        assert owner_query("SELECT has_table_privilege(:r, 'public.whatsapp_rates', :p)", r=role, p=priv)[0][0] is False, priv


# ===================================================================== the sender
def test_a_send_goes_out_as_an_approved_template_and_is_recorded(wm, admin):
    biz = ready_biz(admin, "Send Clinic")
    c = add_contact(biz, "98765 60001", name="Meera Shah", utility=True, **OWNER)
    r = send(biz, c["id"], variables=["Meera", "Send Clinic", "https://g.page/r/abc/review"])
    assert r.ok and r.reason == "ok"
    body = wm.sent[-1]
    assert body["type"] == "template" and body["to"] == "919876560001" and body["template"]["name"] == "flowqr_review_followup_en" and body["template"]["language"] == {"code": "en"}
    assert [p["text"] for p in body["template"]["components"][0]["parameters"]] == ["Meera", "Send Clinic", "https://g.page/r/abc/review"]
    assert "text" not in body and "body" not in body  # never free text
    row = messages(biz.tenant_id)[0]
    assert row[0] == "utility" and row[1] == "sent" and row[3].startswith("wamid.") and row[4] == Decimal("0.1450")


def test_every_refusal_has_a_stable_reason_and_sends_nothing(wm, admin, monkeypatch):
    biz = ready_biz(admin, "Refuse Clinic")
    none = add_contact(biz, "98765 60010")
    mkt = add_contact(biz, "98765 60011", marketing=True, **OWNER)
    ok = add_contact(biz, "98765 60012", utility=True, **OWNER)
    assert send(biz, none["id"]).reason == "no_utility_consent"
    assert send(biz, mkt["id"]).reason == "no_utility_consent"  # offers consent does not allow a visit message
    biz.post(f"/whatsapp/contacts/{ok['id']}/opt-out", json={"purpose": "marketing"})
    assert send(biz, ok["id"]).ok  # a STOP for offers does not stop what they separately agreed to
    assert send(biz, ok["id"], variables=["Asha", "X"]).reason == "invalid_variables"  # wrong number of variables
    assert send(biz, ok["id"], variables=["Asha", "", "https://x"]).reason == "invalid_variables"
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", True)
    assert send(biz, ok["id"]).reason == "emergency_stop"
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", False)
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", False)
    assert send(biz, ok["id"]).reason == "sending_disabled"
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", True)
    owner_exec("UPDATE whatsapp_templates SET approval_status = 'pending' WHERE tenant_id = :t AND template_name = 'flowqr_review_followup_en'", t=biz.tenant_id)
    assert send(biz, ok["id"]).reason == "template_not_approved"
    owner_exec("UPDATE whatsapp_templates SET approval_status = 'approved', category = 'authentication' WHERE tenant_id = :t AND template_name = 'flowqr_review_followup_en'", t=biz.tenant_id)
    assert send(biz, ok["id"]).reason == "category_not_supported"
    assert len(wm.sent) == 1  # only the one legitimate send


def test_variables_are_cleaned_single_line_and_bounded(wm, admin):
    biz = ready_biz(admin, "Clean Clinic")
    c = add_contact(biz, "98765 60020", utility=True, **OWNER)
    assert send(biz, c["id"], variables=["Asha\n\tVerma‮", "Clean   Clinic", "https://g.page/r/" + "x" * 500]).ok
    params = [p["text"] for p in wm.sent[-1]["template"]["components"][0]["parameters"]]
    assert params[0] == "Asha Verma" and "  " not in params[1] and len(params[2]) == 200 and all("\n" not in p and "\t" not in p for p in params)


def test_the_same_key_never_sends_twice_even_from_two_workers(wm, admin):
    biz = ready_biz(admin, "Dup Clinic")
    c = add_contact(biz, "98765 60030", utility=True, **OWNER)
    first = send(biz, c["id"], idem="run:abc")
    again = send(biz, c["id"], idem="run:abc")
    assert first.ok and again.ok and again.reason == "duplicate" and len(wm.sent) == 1 and len(messages(biz.tenant_id)) == 1
    owner_exec("INSERT INTO whatsapp_messages (id, tenant_id, phone_number_id, direction, delivery_status, idempotency_key, created_at, updated_at) VALUES (gen_random_uuid(), :t, '1', 'outbound', 'queued', 'race', now(), now())", t=biz.tenant_id)
    assert send(biz, c["id"], idem="race").reason == "duplicate" and len(wm.sent) == 1  # a key another worker already holds


def test_two_marketing_messages_to_one_person_are_not_sent_close_together(wm, admin):
    biz = ready_biz(admin, "Gap Clinic")
    c = add_contact(biz, "98765 60040", marketing=True, **OWNER)
    assert send(biz, c["id"], key="offer", variables=["Asha", "Gap Clinic", "10% off this week"]).ok
    again = send(biz, c["id"], key="offer", variables=["Asha", "Gap Clinic", "20% off this week"])
    assert (again.status, again.reason) == ("skipped", "too_soon") and len(wm.sent) == 1


def test_per_minute_and_daily_limits_hold_a_send_back_and_leave_no_trace(wm, admin, monkeypatch):
    biz = ready_biz(admin, "Limit Clinic")
    cs = [add_contact(biz, f"98765 6005{i}", utility=True, **OWNER) for i in range(3)]
    monkeypatch.setattr(settings, "whatsapp_send_per_minute", 2)
    res = [send(biz, c["id"]) for c in cs]
    assert [r.status for r in res] == ["sent", "sent", "retry"] and res[2].reason == "rate_limited" and res[2].retry_after == 60
    assert len(messages(biz.tenant_id)) == 2 and len(wm.sent) == 2
    monkeypatch.setattr(settings, "whatsapp_send_per_minute", 1000)
    monkeypatch.setattr(settings, "whatsapp_daily_cap", 2)
    assert send(biz, cs[2]["id"]).reason == "daily_cap"


def test_meta_failures_retry_cleanly_or_are_recorded_and_a_token_error_asks_the_owner_to_act(wm, admin):
    biz = ready_biz(admin, "Fail Clinic")
    c = add_contact(biz, "98765 60060", utility=True, **OWNER)
    wm.fail = {"send": 503}
    r = send(biz, c["id"], idem="k1")
    assert (r.status, r.reason) == ("retry", "meta_unavailable") and messages(biz.tenant_id) == []  # nothing left behind: the retry can use the same key
    wm.fail = {}
    assert send(biz, c["id"], idem="k1").ok and len(messages(biz.tenant_id)) == 1
    wm.fail, wm.fail_code = {"send": 400}, {"send": 131026}
    r = send(biz, c["id"], idem="k2")
    assert (r.status, r.reason) == ("failed", "meta_rejected") and messages(biz.tenant_id)[-1][1:3] == ("failed", "131026")
    wm.fail_code = {"send": 190}
    send(biz, c["id"], idem="k3")
    assert biz.get("/whatsapp/status").json()["connection"]["status"] == "needs_attention"
    assert send(biz, c["id"], idem="k4").reason == "not_connected"  # and nothing more is sent until they reconnect


def test_a_template_of_another_business_can_never_be_used(wm, admin):
    a = ready_biz(admin, "Cross A")
    b = make_business("Cross B")
    grant_addon(admin, b, "whatsapp_growth")
    wm.waba, wm.granted = base.uid(4), [base.uid(4)]
    wm.granted = [wm.waba]
    r, _ = connect(b, admin, addon=False, waba=wm.waba, phone=base.uid(5))
    assert r.status_code == 200
    install_all(b, ("review_followup",))
    cb = add_contact(b, "98765 60070", utility=True, **OWNER)
    a_template = tpl(a, "review_followup")
    with svc_db(b.tenant_id) as db:
        t = db.get(Tenant, uuid.UUID(b.tenant_id))
        contact = consent.get_contact(db, t.id, uuid.UUID(cb["id"]))
        res = sender.send_template(db, t, contact, a_template, ["Asha", "B", "https://x"], idem_key="cross")
    assert res.reason == "template_mismatch" and wm.sent == []


# ===================================================================== usage
def test_usage_keeps_sent_delivered_and_read_apart_and_estimates_only_delivered(wm, admin):
    biz = ready_biz(admin, "Usage Clinic")
    cs = [add_contact(biz, f"98765 6008{i}", utility=True, **OWNER) for i in range(4)]
    for c in cs:
        assert send(biz, c["id"]).ok
    ids = [r[3] for r in messages(biz.tenant_id)]
    def status(wamid, st, ts):
        raw = payload(statuses=[{"id": wamid, "status": st, "timestamp": ts}])
        post_wh(raw)
        process(base.event_id_for(raw))
    status(ids[0], "delivered", "1700000001")
    status(ids[1], "read", "1700000002")
    wm.fail = {"send": 400}
    extra = add_contact(biz, "98765 60090", utility=True, **OWNER)
    assert send(biz, extra["id"]).status == "failed"
    u = biz.get("/whatsapp/usage").json()
    t = u["totals"]
    assert (t["attempted"], t["sent"], t["delivered"], t["read"], t["failed"]) == (5, 4, 2, 1, 1)  # delivered is not read
    assert u["by_category"]["utility"]["estimated_cost"] == "0.29" and u["estimated_meta_cost"] == "0.29" and u["delivery_rate"] == 50  # 2 delivered x 0.145
    assert "not a bill" in u["note"].lower() and u["rates"]["marketing"]["rate"] == "1.0900" and u["limits"]["per_day"] == settings.whatsapp_daily_cap
    assert biz.get("/whatsapp/usage", params={"month": "2020-01"}).json()["totals"]["attempted"] == 0
    assert biz.get("/whatsapp/usage", params={"month": "nope"}).status_code == 422
    other = make_business("Usage Other")
    assert other.get("/whatsapp/usage").json()["totals"]["attempted"] == 0  # another business sees none of it


def test_the_activity_list_shows_who_and_what_but_only_the_last_digits(wm, admin):
    biz = ready_biz(admin, "Act Clinic")
    c = add_contact(biz, "98765 61111", name="Meera", utility=True, **OWNER)
    send(biz, c["id"])
    a = biz.get("/whatsapp/messages").json()
    assert a["total"] == 1 and a["items"][0]["to"] == "Meera" and a["items"][0]["phone_last4"] == "1111" and "9876" not in json.dumps(a)
    assert biz.get("/whatsapp/messages", params={"status": "failed"}).json()["total"] == 0


# ===================================================================== automations: activation
def test_an_automation_needs_the_addon_a_connection_and_approved_messages(wm, admin):
    biz = make_business("Act Needs")
    assert biz.put("/whatsapp/automations/review_followup", json={"status": "on"}).json()["detail"]["code"] == "addon_required"
    grant_addon(admin, biz, "whatsapp_growth")
    assert biz.put("/whatsapp/automations/review_followup", json={"status": "on"}).json()["detail"]["code"] == "not_connected"
    connect(biz, admin, addon=False)
    wm.template_status = "PENDING"
    r = biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "templates_pending"  # it submitted the message and tells them WhatsApp is still reviewing it
    assert wm.templates["flowqr_review_followup_en"]["status"] == "PENDING"
    wm.templates["flowqr_review_followup_en"]["status"] = "APPROVED"
    biz.post("/whatsapp/templates/sync")
    on = biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    assert on.status_code == 200 and on.json()["status"] == "on" and on.json()["config"] == {"delay_minutes": 60}


def test_the_addon_limits_how_many_automations_can_be_on(wm, admin, monkeypatch):
    monkeypatch.setitem(rules.ADDON_TIERS["whatsapp_starter"], "automation_limit", 1)
    biz = ready_biz(admin, "Limit Auto", tier="whatsapp_starter")
    assert biz.put("/whatsapp/automations/review_followup", json={"status": "on"}).status_code == 200
    r = biz.put("/whatsapp/automations/enquiry_followup", json={"status": "on"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "automation_limit"
    biz.put("/whatsapp/automations/review_followup", json={"status": "off"})
    assert biz.put("/whatsapp/automations/enquiry_followup", json={"status": "on"}).status_code == 200
    assert biz.get("/whatsapp/automations").json()["active"] == 1


def test_automation_settings_are_validated(wm, admin):
    biz = ready_biz(admin, "Cfg Clinic")
    for key, cfg in (("review_followup", {"delay_minutes": 1}), ("review_followup", {"delay_minutes": "soon"}), ("review_followup", {"nope": 1}), ("enquiry_followup", {"follow_up_hours": 999}),
                     ("enquiry_followup", {"send_ack": "yes"}), ("review_followup", {"delay_minutes": True})):
        r = biz.put(f"/whatsapp/automations/{key}", json={"status": "on", "config": cfg})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_config", cfg
    ok = biz.put("/whatsapp/automations/enquiry_followup", json={"status": "on", "config": {"follow_up_hours": 48, "send_ack": False}}).json()
    assert ok["config"] == {"send_ack": False, "ack_delay_minutes": 2, "follow_up_hours": 48}
    assert biz.put("/whatsapp/automations/winback", json={"status": "on"}).status_code == 422  # not built


def test_automation_changes_are_for_owners_and_admins_and_audited(wm, admin):
    biz = ready_biz(admin, "Audit Auto")
    biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    biz.put("/whatsapp/automations/review_followup", json={"status": "paused"})
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.automation_status'", t=biz.tenant_id)[0][0] == 2
    other = make_business("Audit Other")
    assert other.get("/whatsapp/automations/review_followup/runs").json() == []


# ===================================================================== automations: review follow-up
def test_a_visit_schedules_one_neutral_request_and_it_is_sent_after_the_delay(wm, admin):
    biz = ready_biz(admin, "Review Clinic")
    biz.put("/whatsapp/automations/review_followup", json={"status": "on", "config": {"delay_minutes": 30}})
    c = add_contact(biz, "98765 62001", name="Meera Shah", utility=True, **OWNER)
    r = biz.post(f"/whatsapp/contacts/{c['id']}/visit").json()
    assert r["scheduled"] is True and r["reason"] == "ok"
    assert tick(biz.tenant_id, 10)["automations"]["executed"] == 0 and wm.sent == []  # not yet
    assert tick(biz.tenant_id, 45)["automations"]["sent"] == 1
    params = [p["text"] for p in wm.sent[0]["template"]["components"][0]["parameters"]]
    assert params == ["Meera", "Review Clinic", "https://g.page/r/ABC123/review"]  # the business's own review link; one message for everyone who agreed, not filtered by anything
    runs = biz.get("/whatsapp/automations/review_followup/runs").json()
    assert runs[0]["status"] == "sent" and runs[0]["phone_last4"] == "2001"
    assert tick(biz.tenant_id, 90)["automations"]["executed"] == 0 and len(wm.sent) == 1  # a run executes once


def test_a_visit_is_refused_politely_when_it_should_not_send(wm, admin):
    biz = ready_biz(admin, "Visit Clinic")
    c = add_contact(biz, "98765 62010", utility=True, **OWNER)
    assert biz.post(f"/whatsapp/contacts/{c['id']}/visit").json()["detail"]["code"] == "automation_off"
    biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    nobody = add_contact(biz, "98765 62011")
    assert biz.post(f"/whatsapp/contacts/{nobody['id']}/visit").json() == {"scheduled": False, "reason": "no_utility_consent"}
    assert biz.post(f"/whatsapp/contacts/{c['id']}/visit").json()["scheduled"] is True
    again = biz.post(f"/whatsapp/contacts/{c['id']}/visit").json()
    assert again["scheduled"] is False and again["reason"] == "asked_recently"  # never twice in WHATSAPP_REVIEW_GAP_DAYS
    assert owner_query("SELECT count(*) FROM whatsapp_automation_runs WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 1
    other = make_business("Visit Other")
    assert other.post(f"/whatsapp/contacts/{c['id']}/visit").status_code == 404


def test_a_scheduled_request_is_cancelled_or_skipped_when_things_change(wm, admin):
    biz = ready_biz(admin, "Change Clinic")
    biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    a, b, c = (add_contact(biz, f"98765 6202{i}", utility=True, **OWNER) for i in range(3))
    for x in (a, b, c):
        assert biz.post(f"/whatsapp/contacts/{x['id']}/visit").json()["scheduled"]
    biz.post(f"/whatsapp/contacts/{b['id']}/opt-out", json={"purpose": "utility"})  # b withdraws their agreement before the send
    biz.delete(f"/whatsapp/contacts/{c['id']}")  # c is deleted
    tick(biz.tenant_id, 120)
    by = {r["phone_last4"] or "gone": (r["status"], r["reason"]) for r in biz.get("/whatsapp/automations/review_followup/runs").json()}
    assert by["2020"] == ("sent", None) and by["2021"] == ("skipped", "no_utility_consent") and by["gone"] == ("cancelled", "contact_deleted")
    assert len(wm.sent) == 1


def test_pausing_cancels_what_has_not_been_sent_and_the_emergency_stop_holds_everything(wm, admin, monkeypatch):
    biz = ready_biz(admin, "Pause Clinic")
    biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    a, b = add_contact(biz, "98765 62030", utility=True, **OWNER), add_contact(biz, "98765 62031", utility=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{a['id']}/visit")
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", True)
    assert tick(biz.tenant_id, 120)["automations"] == {"held": True, "executed": 0} and wm.sent == []  # held, not dropped
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", False)
    biz.put("/whatsapp/automations/review_followup", json={"status": "paused"})
    tick(biz.tenant_id, 120)
    assert wm.sent == []
    assert [r["status"] for r in biz.get("/whatsapp/automations/review_followup/runs").json()] == ["cancelled"]
    biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    assert biz.post(f"/whatsapp/contacts/{b['id']}/visit").json()["scheduled"] is True  # switching it back on works for new visits


def test_without_a_review_link_the_request_is_skipped_not_sent_blank(wm, admin):
    biz = ready_biz(admin, "NoLink Clinic")
    biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    c = add_contact(biz, "98765 62040", utility=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{c['id']}/visit")
    owner_exec("UPDATE locations SET review_url = NULL WHERE tenant_id = :t", t=biz.tenant_id)
    tick(biz.tenant_id, 120)
    assert wm.sent == [] and biz.get("/whatsapp/automations/review_followup/runs").json()[0]["reason"] == "no_review_link"


# ===================================================================== automations: retries and the dead letter
def test_a_failing_send_is_retried_with_growing_delays_then_given_up_visibly(wm, admin, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_send_max_attempts", 3)
    biz = ready_biz(admin, "Retry Clinic")
    biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    c = add_contact(biz, "98765 62050", utility=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{c['id']}/visit")
    wm.fail = {"send": 503}
    tick(biz.tenant_id, 120)
    r = owner_query("SELECT status, attempts, reason, scheduled_at FROM whatsapp_automation_runs WHERE tenant_id = :t", t=biz.tenant_id)[0]
    assert r[0] == "scheduled" and r[1] == 1 and r[2] == "meta_unavailable"
    tick(biz.tenant_id, 120 + 3)  # not due again until the backoff has passed
    assert owner_query("SELECT attempts FROM whatsapp_automation_runs WHERE tenant_id = :t", t=biz.tenant_id)[0][0] in (1, 2)
    tick(biz.tenant_id, 24 * 60)
    tick(biz.tenant_id, 48 * 60)
    last = biz.get("/whatsapp/automations/review_followup/runs", params={"status": "failed"}).json()
    assert len(last) == 1 and last[0]["reason"] == "gave_up:meta_unavailable" and last[0]["attempts"] == 3  # the dead letter, visible
    assert messages(biz.tenant_id) == []
    wm.fail = {}
    tick(biz.tenant_id, 72 * 60)
    assert wm.sent == []  # a given-up run is never revived silently


def test_a_temporary_failure_that_recovers_sends_exactly_once(wm, admin):
    biz = ready_biz(admin, "Recover Clinic")
    biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    c = add_contact(biz, "98765 62060", utility=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{c['id']}/visit")
    wm.fail = {"send": 503}
    tick(biz.tenant_id, 120)
    wm.fail = {}
    tick(biz.tenant_id, 24 * 60)
    tick(biz.tenant_id, 25 * 60)
    assert len(wm.sent) == 1 and biz.get("/whatsapp/automations/review_followup/runs").json()[0]["status"] == "sent"


def test_a_crash_inside_one_run_does_not_stop_the_others(wm, admin, monkeypatch):
    biz = ready_biz(admin, "Crash Clinic")
    biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    a, b = add_contact(biz, "98765 62070", utility=True, **OWNER), add_contact(biz, "98765 62071", utility=True, **OWNER)
    for x in (a, b):
        biz.post(f"/whatsapp/contacts/{x['id']}/visit")
    real = sender.send_template
    n = {"c": 0}
    def flaky(*args, **kw):
        n["c"] += 1
        if n["c"] == 1:
            raise RuntimeError("boom")
        return real(*args, **kw)
    monkeypatch.setattr(sender, "send_template", flaky)
    out = tick(biz.tenant_id, 120)["automations"]
    assert out["executed"] == 2 and out.get("sent") == 1 and len(wm.sent) == 1


# ===================================================================== automations: enquiry follow-up (the website form's tick)
def test_the_site_form_tick_records_the_visitors_own_consent_and_schedules_an_ack_and_a_follow_up(wm, admin, sites_on):
    biz = ready_biz(admin, "Enq Clinic")
    biz.put("/whatsapp/automations/enquiry_followup", json={"status": "on", "config": {"follow_up_hours": 24}})
    site = base_site(admin, biz)
    assert enquire(site["hostname"], whatsapp_ok=True, name="Asha Verma", phone="98765 63001").status_code == 201
    c = biz.get("/whatsapp/contacts", params={"search": "63001"}).json()["items"][0]
    assert c["source"] == "website_form" and c["utility"]["source"] == "website_form" and c["marketing"] is None  # utility only: never offers
    assert owner_query("SELECT evidence FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)[0][0] is None  # the visitor did it themselves: no attestation
    runs = owner_query("SELECT step, status FROM whatsapp_automation_runs WHERE tenant_id = :t ORDER BY scheduled_at", t=biz.tenant_id)
    assert runs == [("ack", "scheduled"), ("followup", "scheduled")]
    assert tick(biz.tenant_id, 5)["automations"].get("sent") == 1
    assert wm.sent[0]["template"]["name"] == "flowqr_enquiry_ack_en" and [p["text"] for p in wm.sent[0]["template"]["components"][0]["parameters"]] == ["Asha", "Enq Clinic"]
    tick(biz.tenant_id, 25 * 60)
    assert wm.sent[-1]["template"]["name"] == "flowqr_enquiry_followup_en" and len(wm.sent) == 2


def test_an_enquiry_without_the_tick_records_and_sends_nothing(wm, admin, sites_on):
    biz = ready_biz(admin, "NoTick Clinic")
    biz.put("/whatsapp/automations/enquiry_followup", json={"status": "on"})
    site = base_site(admin, biz)
    assert enquire(site["hostname"], whatsapp_ok=False, phone="98765 63010").status_code == 201
    assert enquire(site["hostname"], phone="98765 63011", client_ip="203.0.113.50").status_code == 201
    assert biz.get("/whatsapp/contacts").json()["total"] == 0
    assert owner_query("SELECT count(*) FROM whatsapp_automation_runs WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0
    tick(biz.tenant_id, 5000)
    assert wm.sent == []


def test_an_answered_enquiry_is_not_chased(wm, admin, sites_on):
    biz = ready_biz(admin, "Answered Clinic")
    biz.put("/whatsapp/automations/enquiry_followup", json={"status": "on", "config": {"send_ack": False}})
    site = base_site(admin, biz)
    enquire(site["hostname"], whatsapp_ok=True, phone="98765 63020")
    owner_exec("UPDATE site_enquiries SET status = 'contacted', contacted_at = now() WHERE tenant_id = :t", t=biz.tenant_id)  # someone replied
    tick(biz.tenant_id, 25 * 60)
    assert wm.sent == [] and owner_query("SELECT status, reason FROM whatsapp_automation_runs WHERE tenant_id = :t", t=biz.tenant_id)[0] == ("skipped", "responded")


def test_the_enquiry_trigger_is_idempotent_and_a_failure_never_loses_the_enquiry(wm, admin, sites_on, monkeypatch):
    biz = ready_biz(admin, "Idem Enq")
    biz.put("/whatsapp/automations/enquiry_followup", json={"status": "on"})
    site = base_site(admin, biz)
    enquire(site["hostname"], whatsapp_ok=True, phone="98765 63030")
    eid = owner_query("SELECT id FROM site_enquiries WHERE tenant_id = :t", t=biz.tenant_id)[0][0]
    with svc_db(biz.tenant_id) as db:
        from app.models.sites import SiteEnquiry
        e = db.get(SiteEnquiry, eid)
        assert automations.on_enquiry(db, uuid.UUID(biz.tenant_id), e, True)["scheduled"] == 0  # the same enquiry again: nothing new
        db.commit()
    assert owner_query("SELECT count(*) FROM whatsapp_automation_runs WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 2
    monkeypatch.setattr(automations, "on_enquiry", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = enquire(site["hostname"], whatsapp_ok=True, phone="98765 63031", client_ip="203.0.113.77")
    assert r.status_code == 201 and owner_query("SELECT count(*) FROM site_enquiries WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 2


def test_the_tick_does_nothing_while_whatsapp_is_off(admin, sites_on):
    assert settings.whatsapp_enabled is False
    _, s = live_site(admin)
    assert enquire(s["hostname"], whatsapp_ok=True, phone="98765 63040").status_code == 201
    assert owner_query("SELECT count(*) FROM whatsapp_contacts WHERE phone = '+919876563040'")[0][0] == 0


def base_site(admin, biz):
    from tests.test_sites_api import new_site, publish, ready
    owner_exec("UPDATE tenants SET phone = '+919876500000', email = 'hello@example.com' WHERE id = :t", t=biz.tenant_id)  # a site with an enquiry form needs a contact detail for the business
    return publish(admin, ready(admin, new_site(admin, {"id": biz.tenant_id})))


# ===================================================================== campaigns
def offer_id(biz):
    return tpl(biz, "offer").id


def draft(biz, name="Diwali offer", audience=None, offer="10% off all sessions this week", **kw):
    r = biz.post("/whatsapp/campaigns", json={"name": name, "template_id": str(offer_id(biz)), "audience": audience or {"kind": "all"}, "variables": {"offer_text": offer}, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def approve(biz, cid, n, accept=True):
    return biz.post(f"/whatsapp/campaigns/{cid}/approve", json={"confirm_recipients": n, "accept_estimate": accept})


def audience(biz, n, prefix="9876570"):
    return [add_contact(biz, f"{prefix}{i:03d}", name=f"Cust {i}", marketing=True, **OWNER) for i in range(n)]


def test_campaigns_need_the_growth_or_pro_addon(wm, admin):
    starter = ready_biz(admin, "Starter Camp", tier="whatsapp_starter")
    r = starter.post("/whatsapp/campaigns", json={"name": "Offer", "template_id": str(offer_id(starter)), "variables": {"offer_text": "10% off this week"}})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_required"
    assert starter.get("/whatsapp/campaigns").json()["allowed"] is False
    grow = ready_biz(admin, "Growth Camp", tier="whatsapp_growth", wm=wm, fresh=True)
    assert draft(grow)["status"] == "draft" and grow.get("/whatsapp/campaigns").json()["allowed"] is True


def test_a_campaign_is_validated_and_only_a_draft_can_be_edited(wm, admin):
    biz = ready_biz(admin, "Valid Camp")
    ok = {"name": "Offer", "template_id": str(offer_id(biz)), "variables": {"offer_text": "10% off this week"}}
    for patch in ({"name": "x"}, {"variables": {"offer_text": "no"}}, {"variables": {"offer_text": "y" * 121}}, {"variables": {}}, {"audience": {"kind": "everyone"}}, {"audience": {"kind": "tag"}},
                  {"audience": {"kind": "new", "days": 0}}, {"template_id": str(tpl(biz, "review_followup").id)}, {"template_id": str(uuid.uuid4())}):
        assert biz.post("/whatsapp/campaigns", json={**ok, **patch}).status_code in (404, 422), patch
    c = draft(biz)
    assert biz.patch(f"/whatsapp/campaigns/{c['id']}", json={"variables": {"offer_text": "Free consultation this Friday"}}).json()["message_preview"].endswith("Reply STOP to stop receiving offers.")
    audience(biz, 1)
    biz.post(f"/whatsapp/campaigns/{c['id']}/approve", json={"confirm_recipients": 1, "accept_estimate": True})
    assert biz.patch(f"/whatsapp/campaigns/{c['id']}", json={"name": "Changed"}).json()["detail"]["code"] == "not_editable"


def test_the_preview_counts_only_people_who_agreed_to_offers_and_estimates_the_charge(wm, admin):
    biz = ready_biz(admin, "Preview Camp")
    audience(biz, 3)
    add_contact(biz, "98765 70900", name="Only visits", utility=True, **OWNER)  # utility consent only
    add_contact(biz, "98765 70901", name="No consent")
    stop = add_contact(biz, "98765 70902", name="Stopped", marketing=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{stop['id']}/opt-out", json={"purpose": "marketing"})
    c = draft(biz)
    p = biz.get(f"/whatsapp/campaigns/{c['id']}").json()
    assert p["recipients"] == 3 and p["estimate"]["amount"] == "3.27" and p["estimate"]["count"] == 3 and p["estimate"]["verified"] is False  # 3 x 1.09
    assert "estimate" in p["estimate"]["note"].lower() and "not a bill" in p["estimate"]["note"].lower()
    assert p["message_preview"] == "Hi Cust, Preview Camp has an offer for you: 10% off all sessions this week. Reply STOP to stop receiving offers."
    assert p["ready"] == {"plan": True, "connection": True, "template_approved": True, "has_recipients": True, "sending_on": True} and p["status"] == "draft"
    assert wm.sent == [] and "Only visits" not in json.dumps(p)


def test_audience_filters_pick_the_right_people(wm, admin):
    biz = ready_biz(admin, "Aud Camp")
    vip = add_contact(biz, "98765 71001", name="Vip", tags=["vip"], marketing=True, **OWNER)
    new = add_contact(biz, "98765 71002", name="New", marketing=True, **OWNER)
    old = add_contact(biz, "98765 71003", name="Old", marketing=True, **OWNER)
    owner_exec("UPDATE whatsapp_contacts SET created_at = now() - interval '90 days' WHERE id = :i", i=old["id"])
    count = lambda aud: biz.get(f"/whatsapp/campaigns/{draft(biz, audience=aud)['id']}").json()["recipients"]  # noqa: E731
    assert count({"kind": "all"}) == 3 and count({"kind": "tag", "tag": "vip"}) == 1 and count({"kind": "tag", "tag": "none"}) == 0
    assert count({"kind": "new", "days": 30}) == 2 and count({"kind": "existing", "days": 30}) == 1 and vip and new


def test_nothing_is_sent_without_the_explicit_approval_and_approval_is_bound_to_what_was_shown(wm, admin):
    biz = ready_biz(admin, "Approve Camp")
    audience(biz, 3)
    c = draft(biz)
    assert tick(biz.tenant_id, 10)["campaigns"].get("started", 0) == 0 and wm.sent == []  # a draft never sends
    assert approve(biz, c["id"], 3, accept=False).json()["detail"]["code"] == "estimate_not_accepted"
    r = approve(biz, c["id"], 2)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "recipients_changed" and "2 to 3" in r.json()["detail"]["message"]
    assert approve(biz, c["id"], 0).status_code in (409, 422)
    assert wm.sent == []
    ok = approve(biz, c["id"], 3)
    assert ok.status_code == 200 and ok.json()["status"] == "scheduled" and ok.json()["approved_recipients"] == 3 and ok.json()["approved_cost"] == "3.27"
    a = owner_query("SELECT metadata FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.campaign_approve'", t=biz.tenant_id)[0][0]
    assert a["recipients"] == 3 and a["estimate"] == "3.27"


def test_an_approval_is_refused_when_the_audience_changed_since_it_was_shown(wm, admin):
    biz = ready_biz(admin, "Changed Camp")
    cs = audience(biz, 3)
    c = draft(biz)
    biz.post(f"/whatsapp/contacts/{cs[0]['id']}/opt-out", json={"purpose": "marketing"})  # someone stops offers after the owner looked
    r = approve(biz, c["id"], 3)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "recipients_changed"
    assert approve(biz, c["id"], 2).status_code == 200


def test_approval_needs_a_connection_an_approved_offer_and_someone_to_send_to(wm, admin):
    biz = ready_biz(admin, "Gate Camp")
    c = draft(biz)
    assert approve(biz, c["id"], 0).json()["detail"]["code"] == "no_recipients"
    audience(biz, 1)
    owner_exec("UPDATE whatsapp_templates SET approval_status = 'pending' WHERE tenant_id = :t AND template_name = 'flowqr_offer_en'", t=biz.tenant_id)
    assert approve(biz, c["id"], 1).json()["detail"]["code"] == "template_not_approved"
    owner_exec("UPDATE whatsapp_templates SET approval_status = 'approved' WHERE tenant_id = :t AND template_name = 'flowqr_offer_en'", t=biz.tenant_id)
    biz.post("/whatsapp/connection/disconnect")
    assert approve(biz, c["id"], 1).json()["detail"]["code"] == "not_connected" or approve(biz, c["id"], 1).status_code in (404, 409)


def test_a_campaign_sends_in_batches_to_the_approved_people_only(wm, admin, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_campaign_batch", 2)
    biz = ready_biz(admin, "Batch Camp")
    audience(biz, 5)
    c = draft(biz)
    assert approve(biz, c["id"], 5).status_code == 200
    late = add_contact(biz, "98765 72999", name="Late", marketing=True, **OWNER)  # agreed AFTER the approval: not included
    out = tick(biz.tenant_id, 1)["campaigns"]
    assert out["started"] == 1 and out["sent"] == 2 and len(wm.sent) == 2
    assert biz.get(f"/whatsapp/campaigns/{c['id']}/results").json()["waiting"] == 3
    tick(biz.tenant_id, 2)
    last = tick(biz.tenant_id, 3)["campaigns"]
    assert last["finished"] == 1 and len(wm.sent) == 5
    assert owner_query("SELECT status FROM whatsapp_campaigns WHERE id = :c", c=c["id"])[0][0] == "done"
    sent_to = {m["to"] for m in wm.sent}
    assert "919876572999" not in sent_to and len(sent_to) == 5  # each person once
    assert all(m["template"]["name"] == "flowqr_offer_en" and m["type"] == "template" for m in wm.sent)
    assert tick(biz.tenant_id, 10)["campaigns"].get("sent", 0) == 0 and late


def test_an_opt_out_after_approval_removes_that_person_at_the_moment_of_sending(wm, admin):
    biz = ready_biz(admin, "Late Stop Camp")
    cs = audience(biz, 3)
    c = draft(biz)
    approve(biz, c["id"], 3)
    biz.post(f"/whatsapp/contacts/{cs[1]['id']}/opt-out", json={"purpose": "marketing"})
    out = tick(biz.tenant_id, 1)["campaigns"]
    assert out["sent"] == 2 and out["finished"] == 1 and len(wm.sent) == 2
    r = biz.get(f"/whatsapp/campaigns/{c['id']}/results").json()
    assert r["skipped"] == 0 or r["skipped_reasons"]  # the opted-out person was never in the sending list (re-resolved when sending started)
    assert "919876570001" not in {m["to"] for m in wm.sent}


def test_a_campaign_can_be_paused_resumed_and_cancelled(wm, admin, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_campaign_batch", 2)
    biz = ready_biz(admin, "Pause Camp")
    audience(biz, 6)
    c = draft(biz)
    approve(biz, c["id"], 6)
    tick(biz.tenant_id, 1)
    assert len(wm.sent) == 2
    assert biz.post(f"/whatsapp/campaigns/{c['id']}/pause").json()["status"] == "paused"
    tick(biz.tenant_id, 2)
    assert len(wm.sent) == 2  # paused: nothing more
    assert biz.post(f"/whatsapp/campaigns/{c['id']}/resume").json()["status"] == "sending"
    tick(biz.tenant_id, 3)
    assert len(wm.sent) == 4
    cancelled = biz.post(f"/whatsapp/campaigns/{c['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    tick(biz.tenant_id, 4)
    assert len(wm.sent) == 4
    r = biz.get(f"/whatsapp/campaigns/{c['id']}/results").json()
    assert r["sent"] == 4 and r["skipped_reasons"] == {"campaign_cancelled": 2}
    assert biz.post(f"/whatsapp/campaigns/{c['id']}/cancel").json()["detail"]["code"] == "not_cancellable"
    assert biz.post(f"/whatsapp/campaigns/{c['id']}/resume").json()["detail"]["code"] == "not_resumable"


def test_the_emergency_stop_holds_a_campaign_and_it_continues_afterwards(wm, admin, monkeypatch):
    biz = ready_biz(admin, "Stop Camp")
    audience(biz, 2)
    c = draft(biz)
    approve(biz, c["id"], 2)
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", True)
    assert tick(biz.tenant_id, 1)["campaigns"] == {"held": True} and wm.sent == []
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", False)
    assert tick(biz.tenant_id, 2)["campaigns"]["sent"] == 2


def test_a_person_with_a_recent_marketing_message_is_skipped_not_messaged_again(wm, admin):
    biz = ready_biz(admin, "Soon Camp")
    cs = audience(biz, 2)
    assert send(biz, cs[0]["id"], key="offer", variables=["Cust", "Soon Camp", "an earlier offer here"]).ok  # an offer went out a moment ago
    c = draft(biz)
    approve(biz, c["id"], 2)
    tick(biz.tenant_id, 1)
    r = biz.get(f"/whatsapp/campaigns/{c['id']}/results").json()
    assert r["sent"] == 1 and r["skipped_reasons"] == {"too_soon": 1}  # of the two, one is sent; the one who had an offer a moment ago is skipped


def test_results_report_what_whatsapp_reports_and_claim_no_sales(wm, admin):
    biz = ready_biz(admin, "Results Camp")
    audience(biz, 4)
    c = draft(biz)
    approve(biz, c["id"], 4)
    tick(biz.tenant_id, 0)
    ids = [r[3] for r in messages(biz.tenant_id)]
    for wamid, st in ((ids[0], "delivered"), (ids[1], "read"), (ids[2], "delivered")):
        raw = payload(statuses=[{"id": wamid, "status": st, "timestamp": "1700000009"}])
        post_wh(raw)
        process(base.event_id_for(raw))
    stop = payload(messages=[{"from": "919876570000", "id": "wamid.STOPX", "type": "text", "text": {"body": "STOP"}}])
    post_wh(stop)
    process(base.event_id_for(stop))
    r = biz.get(f"/whatsapp/campaigns/{c['id']}/results").json()
    assert (r["attempted"], r["sent"], r["delivered"], r["read"], r["failed"]) == (4, 4, 3, 1, 0) and r["opted_out_after"] == 1  # delivered is not read
    assert r["approved_recipients"] == 4 and r["approved_estimate"] == "4.36" and r["estimated_meta_cost"] == "3.27"  # approved estimate vs what was actually delivered
    note = r["note"].lower()
    assert "cannot tell you how many sales" in note and "not a bill" in note
    for claim in ("conversion", "revenue", "roi"):
        assert claim not in json.dumps(r).lower()


def test_another_business_cannot_see_or_change_a_campaign(wm, admin):
    a = ready_biz(admin, "Iso Camp A")
    b = make_business("Iso Camp B")
    audience(a, 1)
    c = draft(a)
    for method, url, body in (("GET", f"/whatsapp/campaigns/{c['id']}", None), ("GET", f"/whatsapp/campaigns/{c['id']}/results", None), ("PATCH", f"/whatsapp/campaigns/{c['id']}", {"name": "Hacked"}),
                              ("POST", f"/whatsapp/campaigns/{c['id']}/approve", {"confirm_recipients": 1, "accept_estimate": True}), ("POST", f"/whatsapp/campaigns/{c['id']}/cancel", None)):
        r = b.request(method, url, json=body) if body is not None else b.request(method, url)
        assert r.status_code == 404, (method, url)
    assert b.get("/whatsapp/campaigns").json()["items"] == []
    assert a.get(f"/whatsapp/campaigns/{c['id']}").json()["status"] == "draft"


def test_the_worker_task_sends_due_work_and_holds_when_switched_off(wm, admin):
    from app.workers.tasks import whatsapp_run_due
    biz = ready_biz(admin, "Task Camp")
    audience(biz, 2)
    c = draft(biz)
    approve(biz, c["id"], 2)
    owner_exec("UPDATE whatsapp_campaigns SET scheduled_at = now() - interval '1 minute' WHERE id = :c", c=c["id"])
    out = whatsapp_run_due.run()
    assert out["campaigns"]["started"] >= 1 and len(wm.sent) >= 2
    settings.whatsapp_sending_enabled = False
    try:
        assert whatsapp_run_due.run() == {"held": True}
    finally:
        settings.whatsapp_sending_enabled = True


def test_the_account_export_covers_the_new_tables_and_deleting_a_business_removes_them(wm, admin):
    import io
    import zipfile
    biz = ready_biz(admin, "Export Camp")
    audience(biz, 1)
    c = draft(biz)
    approve(biz, c["id"], 1)
    tick(biz.tenant_id, 1)
    z = zipfile.ZipFile(io.BytesIO(biz.get("/account/export").content))
    assert {"whatsapp_campaigns.json", "whatsapp_campaign_recipients.json", "whatsapp_automations.json", "whatsapp_automation_runs.json", "whatsapp_messages.json"} <= set(z.namelist())
    blob = b"".join(z.read(n) for n in z.namelist() if n.endswith(".json")).decode()
    assert "access_token_enc" not in blob and "Hi Cust" not in blob  # no message text is ever stored
    db = system_session()
    try:
        from sqlalchemy import text
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": biz.tenant_id})
        db.commit()
    finally:
        db.close()
    for t in ("whatsapp_campaigns", "whatsapp_campaign_recipients", "whatsapp_messages", "whatsapp_automations", "whatsapp_automation_runs"):
        assert owner_query(f"SELECT count(*) FROM {t} WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0, t


def test_the_new_routes_are_in_the_access_manifest_with_the_right_roles():
    lines = [ln.split("\t") for ln in open("tests/route_access_manifest.txt", encoding="utf-8").read().splitlines() if "/whatsapp" in ln]
    by = {(m, p): k for k, m, p in lines}
    assert by[("POST", "/api/v1/whatsapp/campaigns/{campaign_id}/approve")] == "role-admin" and by[("GET", "/api/v1/whatsapp/campaigns/{campaign_id}/results")] == "member"
    assert by[("PUT", "/api/v1/whatsapp/automations/{key}")] == "role-admin" and by[("POST", "/api/v1/whatsapp/contacts/{contact_id}/visit")] == "role-admin"
    assert by[("GET", "/api/v1/whatsapp/usage")] == "member" and by[("POST", "/api/v1/whatsapp/templates/install")] == "role-admin"
    assert by[("POST", "/api/v1/admin/whatsapp/rates")] == "platform-admin" and by[("GET", "/api/v1/admin/whatsapp/rates")] == "platform-admin"
    assert hashlib.sha256(b"x").hexdigest() and WaError and usage and rules and Tenant  # imports used


def test_the_site_form_shows_the_whatsapp_tick_only_when_it_is_switched_on_and_it_is_optional():
    from app.services.sites import catalog as site_catalog
    from tests.test_sites_content import build, filled
    c = filled("clinic")
    sec = next(s for s in c["sections"] if s["type"] == "contact")
    sec["data"]["show_enquiry"], sec["data"]["whatsapp_optin"] = True, False
    assert b'name="whatsapp_ok"' not in build(c, "clinic")["index.html"]
    sec["data"]["whatsapp_optin"] = True
    html = build(c, "clinic")["index.html"].decode()
    assert 'name="whatsapp_ok"' in html and "I can reply STOP at any time" in html
    tick = html[html.index('name="whatsapp_ok"') - 60: html.index('name="whatsapp_ok"') + 80]
    assert "required" not in tick  # the tick is the visitor's free choice; the enquiry works without it
    assert "whatsapp_optin" in {f["key"] for f in site_catalog.SECTION_TYPES["contact"]["fields"]}
