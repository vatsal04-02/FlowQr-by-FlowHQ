"""WhatsApp campaign manager (Phase 4): scheduling, sending hours, audience by plan, choosing an approved message and filling its blanks, results (timeline, comparison, a results file) and duplicating.

Runs against the mock of Meta used by the Phase 2 and 3 tests: no real number, account or message is involved."""
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import config_problems, settings
from app.core.db import system_session
from app.models.base import utcnow
from app.services.whatsapp import automations, campaigns, templates
from tests import test_whatsapp as base
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_config_guard import good
from tests.test_whatsapp import OWNER, add_contact, payload, post_wh, process, svc_db, wa  # noqa: F401 - fixtures
from tests.test_whatsapp_messaging import approve, audience, draft, messages, offer_id, ready_biz, send, tick, tpl, wm  # noqa: F401 - fixtures

IST = campaigns.IST


def ist(day_offset: int, hour: int, minute: int = 0) -> datetime:
    """A UTC instant that is `hour:minute` India time, `day_offset` days from today."""
    t = (utcnow().astimezone(IST) + timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return t.astimezone(timezone.utc)


def naive_ist(day_offset: int, hour: int) -> str:
    return (utcnow().astimezone(IST) + timedelta(days=day_offset)).replace(hour=hour, minute=0, second=0, microsecond=0, tzinfo=None).isoformat()


def own_template(wm, biz, *, status="APPROVED", category="MARKETING", header=False, body="Hello {{1}}, {{2}} has {{3}} for you. Reply STOP to stop receiving offers."):
    comps = [{"type": "BODY", "text": body}] + ([{"type": "HEADER", "format": "IMAGE"}] if header else [])
    name = f"promo_{uuid.uuid4().hex[:6]}_en"
    wm.templates[name] = {"id": f"x{uuid.uuid4().hex[:5]}", "name": name, "language": "en", "category": category, "status": status, "components": comps}
    assert biz.post("/whatsapp/templates/sync").status_code == 200
    return next(t for t in biz.get("/whatsapp/templates").json()["items"] if t["name"] == name)


MAP = {"mapping": [{"source": "customer_name"}, {"source": "business_name"}, {"source": "text", "value": "a free check-up"}]}


# ===================================================================== sending hours
def test_offers_go_out_only_during_sending_hours_india_time(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_send_window_start", 9)
    monkeypatch.setattr(settings, "whatsapp_send_window_end", 21)
    for h, m, expect in ((8, 59, False), (9, 0, True), (14, 30, True), (20, 59, True), (21, 0, False), (23, 30, False), (0, 15, False)):
        assert campaigns.in_window(ist(1, h, m)) is expect, (h, m)
    late = ist(1, 22, 30)
    assert campaigns.next_open(late) == ist(2, 9, 0)  # after hours: the next morning
    early = ist(1, 6, 0)
    assert campaigns.next_open(early) == ist(1, 9, 0)  # before hours: this morning
    assert campaigns.next_open(ist(1, 12, 0)) == ist(1, 12, 0)  # during hours: now
    monkeypatch.setattr(settings, "whatsapp_send_window_start", 0)
    monkeypatch.setattr(settings, "whatsapp_send_window_end", 24)
    assert campaigns.in_window(ist(1, 3, 0)) is True and campaigns.window_info()["always"] is True


def test_a_campaign_waits_outside_hours_and_sends_inside_them_but_helpers_are_not_held(wm, admin, monkeypatch):
    biz = ready_biz(admin, "Hours Clinic")
    audience(biz, 2)
    c = draft(biz)
    approve(biz, c["id"], 2)
    monkeypatch.setattr(settings, "whatsapp_send_window_start", 9)
    monkeypatch.setattr(settings, "whatsapp_send_window_end", 21)
    db = system_session()
    try:
        night = ist(0, 23, 0) if ist(0, 23, 0) > utcnow() else ist(1, 23, 0)
        assert campaigns.run_due(db, now=night + timedelta(days=1), tenant_id=uuid.UUID(biz.tenant_id)) == {"held": True, "reason": "outside_hours"}
        db.commit()
    finally:
        db.close()
    assert wm.sent == [] and owner_query("SELECT status FROM whatsapp_campaigns WHERE id = :c", c=c["id"])[0][0] == "scheduled"  # waiting, nothing lost
    day = ist(3, 11, 0)
    db = system_session()
    try:
        out = campaigns.run_due(db, now=day, tenant_id=uuid.UUID(biz.tenant_id))
        db.commit()
    finally:
        db.close()
    assert out["started"] == 1 and out["sent"] == 2 and len(wm.sent) == 2
    # a helper's reply (a thank-you for an enquiry) is not an offer: it is not held by sending hours
    biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    ct = add_contact(biz, "98765 80001", utility=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{ct['id']}/visit")
    db = system_session()
    try:
        out = automations.run_due(db, now=ist(4, 23, 30) + timedelta(hours=0), tenant_id=uuid.UUID(biz.tenant_id))
        db.commit()
    finally:
        db.close()
    assert out.get("sent") == 1


def test_the_preview_says_when_it_will_really_start(wm, admin, monkeypatch):
    biz = ready_biz(admin, "Starts Clinic")
    audience(biz, 3)
    monkeypatch.setattr(settings, "whatsapp_send_window_start", 9)
    monkeypatch.setattr(settings, "whatsapp_send_window_end", 21)
    c = draft(biz, scheduled_at=naive_ist(2, 23))  # 11 pm, two days ahead: outside hours
    p = biz.get(f"/whatsapp/campaigns/{c['id']}").json()
    assert p["window"] == {"start": 9, "end": 21, "timezone": "Asia/Kolkata", "open_now": p["window"]["open_now"], "always": False}
    assert p["waits_for_hours"] is True
    start = datetime.fromisoformat(p["starts_at"]).astimezone(IST)
    assert (start.hour, start.minute) == (9, 0) and start.date() == (utcnow().astimezone(IST) + timedelta(days=3)).date()  # the next morning, 9:00
    ok = draft(biz, name="Daytime", scheduled_at=naive_ist(2, 11))
    assert biz.get(f"/whatsapp/campaigns/{ok['id']}").json()["waits_for_hours"] is False
    assert p["estimated_minutes"] == 1


# ===================================================================== scheduling
def test_a_start_time_must_be_in_the_future_and_within_ninety_days(wm, admin):
    biz = ready_biz(admin, "Sched Clinic")
    body = lambda when: {"name": "Offer", "template_id": str(offer_id(biz)), "variables": {"offer_text": "10% off this week"}, "scheduled_at": when}  # noqa: E731
    assert biz.post("/whatsapp/campaigns", json=body(naive_ist(-1, 10))).json()["detail"]["code"] == "invalid_schedule"
    assert biz.post("/whatsapp/campaigns", json=body(naive_ist(120, 10))).json()["detail"]["code"] == "invalid_schedule"
    r = biz.post("/whatsapp/campaigns", json=body(naive_ist(2, 10)))
    assert r.status_code == 201
    stored = owner_query("SELECT scheduled_at FROM whatsapp_campaigns WHERE id = :c", c=r.json()["id"])[0][0].astimezone(IST)
    assert stored.hour == 10 and stored.tzinfo is not None  # a time without a zone is read as India time
    z = biz.post("/whatsapp/campaigns", json=body((utcnow() + timedelta(days=2)).isoformat()))  # an explicit UTC time is respected
    assert z.status_code == 201


def test_an_approved_campaign_waits_for_its_start_time_and_can_be_moved_until_it_starts(wm, admin):
    biz = ready_biz(admin, "Move Clinic")
    audience(biz, 2)
    c = draft(biz, scheduled_at=naive_ist(2, 11))
    assert approve(biz, c["id"], 2).json()["status"] == "scheduled"
    assert tick(biz.tenant_id, 60)["campaigns"].get("started", 0) == 0 and wm.sent == []  # not yet: its time is two days away
    moved = biz.post(f"/whatsapp/campaigns/{c['id']}/reschedule", json={"scheduled_at": naive_ist(3, 12)})
    assert moved.status_code == 200
    assert owner_query("SELECT metadata FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.campaign_reschedule'", t=biz.tenant_id)[0][0]["to"]
    assert tick(biz.tenant_id, 2 * 24 * 60 + 120)["campaigns"].get("started", 0) == 0  # the old time passed, the new one has not
    out = tick(biz.tenant_id, 3 * 24 * 60 + 12 * 60)["campaigns"]
    assert out["started"] == 1 and out["sent"] == 2
    again = biz.post(f"/whatsapp/campaigns/{c['id']}/reschedule", json={"scheduled_at": naive_ist(5, 12)})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "not_reschedulable"
    assert biz.post(f"/whatsapp/campaigns/{c['id']}/reschedule", json={"scheduled_at": naive_ist(-2, 12)}).status_code in (409, 422)


def test_only_the_owners_own_campaign_can_be_moved(wm, admin):
    a = ready_biz(admin, "Own Move A")
    b = make_business("Own Move B")
    audience(a, 1)
    c = draft(a)
    assert b.post(f"/whatsapp/campaigns/{c['id']}/reschedule", json={"scheduled_at": naive_ist(2, 12)}).status_code == 404
    assert b.post(f"/whatsapp/campaigns/{c['id']}/duplicate").status_code == 404
    assert b.get(f"/whatsapp/campaigns/{c['id']}/results.csv").status_code == 404


# ===================================================================== audience by plan
def test_growth_has_the_basics_and_pro_adds_location_groups_and_how_recently_someone_got_an_offer(wm, admin):
    growth = ready_biz(admin, "Seg Growth")
    advanced = [{"kind": "all", "tags_any": ["vip"]}, {"kind": "all", "tags_all": ["vip", "regular"]}, {"kind": "all", "exclude_tags": ["staff"]}, {"kind": "all", "location_id": str(uuid.uuid4())},
                {"kind": "all", "not_messaged_days": 30}, {"kind": "all", "never_messaged": True}]
    for aud in advanced:
        r = growth.post("/whatsapp/campaigns", json={"name": "Offer", "template_id": str(offer_id(growth)), "audience": aud, "variables": {"offer_text": "10% off this week"}})
        assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_required", aud
    for aud in ({"kind": "all"}, {"kind": "tag", "tag": "vip"}, {"kind": "new", "days": 30}, {"kind": "existing", "days": 30}):
        assert growth.post("/whatsapp/campaigns", json={"name": "Offer", "template_id": str(offer_id(growth)), "audience": aud, "variables": {"offer_text": "10% off this week"}}).status_code == 201, aud
    assert growth.get(f"/whatsapp/campaigns/{draft(growth)['id']}").json()["segmentation"] == "basic"
    pro = ready_biz(admin, "Seg Pro", tier="whatsapp_pro", wm=wm, fresh=True)
    assert pro.get(f"/whatsapp/campaigns/{draft(pro)['id']}").json()["segmentation"] == "advanced"
    assert pro.patch(f"/whatsapp/campaigns/{draft(pro)['id']}", json={"audience": {"kind": "all", "tags_any": ["vip"]}}).status_code == 200


def test_advanced_groups_pick_exactly_the_right_people(wm, admin):
    biz = ready_biz(admin, "Adv Clinic", tier="whatsapp_pro")
    loc2 = biz.post("/locations", json={"name": "Second branch", "city": "Delhi", "review_url": "https://g.page/r/XYZ/review"}).json()["id"]
    a = add_contact(biz, "98765 81001", name="A", tags=["vip", "regular"], marketing=True, location_id=loc2, **OWNER)
    b = add_contact(biz, "98765 81002", name="B", tags=["vip"], marketing=True, **OWNER)
    c = add_contact(biz, "98765 81003", name="C", tags=["staff", "vip"], marketing=True, location_id=loc2, **OWNER)
    d = add_contact(biz, "98765 81004", name="D", marketing=True, **OWNER)
    count = lambda **aud: biz.get(f"/whatsapp/campaigns/{draft(biz, audience={'kind': 'all', **aud})['id']}").json()["recipients"]  # noqa: E731
    assert count() == 4 and count(tags_any=["regular", "staff"]) == 2 and count(tags_all=["vip", "regular"]) == 1 and count(exclude_tags=["staff"]) == 3
    assert count(location_id=loc2) == 2 and count(location_id=loc2, exclude_tags=["staff"]) == 1 and count(tags_any=["vip"], exclude_tags=["staff"], location_id=loc2) == 1
    assert a and b and c and d
    # "not sent an offer lately" and "never sent an offer" follow the real send history
    assert send(biz, b["id"], key="offer", variables=["B", "Adv Clinic", "an earlier offer"]).ok
    assert count(never_messaged=True) == 3 and count(not_messaged_days=30) == 3 and count(never_messaged=True, tags_any=["vip"]) == 2
    owner_exec("UPDATE whatsapp_messages SET created_at = now() - interval '60 days' WHERE tenant_id = :t", t=biz.tenant_id)
    assert count(not_messaged_days=30) == 4 and count(never_messaged=True) == 3 and count(not_messaged_days=90) == 3


def test_advanced_audience_values_are_validated(wm, admin):
    biz = ready_biz(admin, "Adv Valid", tier="whatsapp_pro")
    body = lambda aud: {"name": "Offer", "template_id": str(offer_id(biz)), "audience": aud, "variables": {"offer_text": "10% off this week"}}  # noqa: E731
    for bad in ({"kind": "all", "tags_any": ["t"] * 11}, {"kind": "all", "tags_any": "vip"}, {"kind": "all", "location_id": "not-a-uuid"}, {"kind": "all", "not_messaged_days": 0}, {"kind": "all", "not_messaged_days": 999},
                {"kind": "all", "not_messaged_days": True}):
        r = biz.post("/whatsapp/campaigns", json=body(bad))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_audience", bad
    ok = biz.post("/whatsapp/campaigns", json=body({"kind": "all", "tags_any": ["  vip  ", "VIP", ""], "never_messaged": True}))
    assert ok.status_code == 201 and ok.json()["audience"] == {"kind": "all", "tags_any": ["vip", "VIP"], "never_messaged": True}


def test_a_customer_can_be_placed_at_one_of_the_businesses_own_locations_only(wm, admin):
    a = ready_biz(admin, "Loc A")
    b = make_business("Loc B")
    foreign = b.get("/locations").json()[0]["id"]
    mine = a.get("/locations").json()[0]["id"]
    assert a.post("/whatsapp/contacts", json={"phone": "98765 82001", "location_id": foreign}).json()["detail"]["code"] == "invalid_location"
    c = a.post("/whatsapp/contacts", json={"phone": "98765 82002", "name": "Placed", "location_id": mine}).json()
    assert c["location_id"] == mine
    assert a.patch(f"/whatsapp/contacts/{c['id']}", json={"location_id": foreign}).status_code == 422
    assert a.patch(f"/whatsapp/contacts/{c['id']}", json={"location_id": None}).json()["location_id"] is None
    a.patch(f"/whatsapp/contacts/{c['id']}", json={"location_id": mine})
    assert a.get("/whatsapp/contacts", params={"location_id": mine}).json()["total"] == 1 and a.get("/whatsapp/contacts", params={"location_id": foreign}).json()["total"] == 0
    owner_exec("UPDATE whatsapp_contacts SET location_id = :l WHERE id = :c", l=mine, c=c["id"])
    owner_exec("DELETE FROM locations WHERE id = :l", l=mine)
    assert owner_query("SELECT location_id FROM whatsapp_contacts WHERE id = :c", c=c["id"])[0][0] is None  # deleting a branch never deletes a customer


# ===================================================================== choosing an approved message
def test_an_approved_text_only_marketing_message_can_be_used_and_its_blanks_are_filled_from_the_mapping(wm, admin):
    biz = ready_biz(admin, "Own Msg")
    t = own_template(wm, biz)
    assert t["simple"] is True and t["category"] == "marketing" and t["variables"] == ["variable_1", "variable_2", "variable_3"]
    cs = audience(biz, 2)
    c = biz.post("/whatsapp/campaigns", json={"name": "Check-up", "template_id": t["id"], "variables": MAP}).json()
    assert c["variables"] == MAP
    p = biz.get(f"/whatsapp/campaigns/{c['id']}").json()
    assert p["message_preview"] == "Hello Cust, Own Msg has a free check-up for you. Reply STOP to stop receiving offers."
    approve(biz, c["id"], 2)
    out = tick(biz.tenant_id, 1)["campaigns"]
    assert out["sent"] == 2
    sent = [m["template"] for m in wm.sent]
    assert {s["name"] for s in sent} == {t["name"]} and all([x["text"] for x in s["components"][0]["parameters"]][1:] == ["Own Msg", "a free check-up"] for s in sent)
    assert sorted(s["components"][0]["parameters"][0]["text"] for s in sent) == ["Cust", "Cust"] and cs


def test_a_message_with_a_picture_or_button_or_the_wrong_kind_is_refused_clearly(wm, admin):
    biz = ready_biz(admin, "Bad Msg")
    fancy = own_template(wm, biz, header=True)
    util = own_template(wm, biz, category="UTILITY")
    assert fancy["simple"] is False and util["category"] == "utility"
    for t, code in ((fancy, "template_not_simple"), (util, "template_not_marketing")):
        r = biz.post("/whatsapp/campaigns", json={"name": "Offer", "template_id": t["id"], "variables": MAP})
        assert r.status_code == 422 and r.json()["detail"]["code"] == code
    assert biz.post("/whatsapp/campaigns", json={"name": "Offer", "template_id": str(uuid.uuid4()), "variables": MAP}).status_code == 404
    other = make_business("Bad Msg Other")
    grant = ready_biz(admin, "Other Msg", wm=wm, fresh=True)
    assert grant.post("/whatsapp/campaigns", json={"name": "Offer", "template_id": own_template(wm, biz)["id"], "variables": MAP}).status_code == 404  # another business's message
    assert other.get("/whatsapp/templates").json()["items"] == []


def test_the_blanks_must_be_filled_with_allowed_things(wm, admin):
    biz = ready_biz(admin, "Blank Clinic")
    t = own_template(wm, biz)
    bad = [{"mapping": [{"source": "customer_name"}]}, {"mapping": MAP["mapping"][:2] + [{"source": "text"}]}, {"mapping": MAP["mapping"][:2] + [{"source": "text", "value": "x" * 201}]},
           {"mapping": MAP["mapping"][:2] + [{"source": "phone"}]}, {"mapping": "customer_name"}, {}, {"offer_text": "not for this message"}]
    for v in bad:
        r = biz.post("/whatsapp/campaigns", json={"name": "Offer", "template_id": t["id"], "variables": v})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_variables", v
    ok = biz.post("/whatsapp/campaigns", json={"name": "Offer", "template_id": t["id"], "variables": {"mapping": MAP["mapping"][:2] + [{"source": "text", "value": "a\n\tfree   visit"}]}})
    assert ok.status_code == 201 and ok.json()["variables"]["mapping"][2]["value"] == "a free visit"  # cleaned to single line


def test_a_message_waiting_for_approval_cannot_be_approved_for_sending(wm, admin):
    biz = ready_biz(admin, "Wait Msg")
    t = own_template(wm, biz, status="PENDING")
    audience(biz, 1)
    c = biz.post("/whatsapp/campaigns", json={"name": "Offer", "template_id": t["id"], "variables": MAP}).json()
    assert approve(biz, c["id"], 1).json()["detail"]["code"] == "template_not_approved" and wm.sent == []


def test_templates_with_only_a_text_body_are_recognised_as_simple():
    assert templates.is_simple(None) and templates.is_simple([{"type": "BODY", "text": "Hi {{1}}"}]) and templates.is_simple([{"type": "BODY", "text": "x"}, {"type": "FOOTER", "text": "Reply STOP"}])
    for comps in ([{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "x"}], [{"type": "BODY", "text": "x"}, {"type": "BUTTONS", "buttons": []}], [{"type": "BODY", "text": "x"}, {"type": "FOOTER", "text": "Hi {{1}}"}],
                  [{"type": "CAROUSEL"}]):
        assert templates.is_simple(comps) is False


# ===================================================================== results, comparison, file, duplicate
def run_and_deliver(biz, wm, n=4, deliver=3, read=1):
    audience(biz, n)
    c = draft(biz)
    approve(biz, c["id"], n)
    tick(biz.tenant_id, 0)
    ids = [r[3] for r in messages(biz.tenant_id)]
    for i, wamid in enumerate(ids[:deliver]):
        raw = payload(statuses=[{"id": wamid, "status": "read" if i < read else "delivered", "timestamp": "1700000009"}])
        post_wh(raw)
        process(base.event_id_for(raw))
    return c


def test_results_carry_a_daily_timeline_and_rates_and_never_a_sales_claim(wm, admin):
    biz = ready_biz(admin, "Timeline Clinic")
    c = run_and_deliver(biz, wm)
    r = biz.get(f"/whatsapp/campaigns/{c['id']}/results").json()
    assert (r["sent"], r["delivered"], r["read"]) == (4, 3, 1) and r["delivery_rate"] == 75 and r["read_rate"] == 33
    assert len(r["timeline"]) == 1 and r["timeline"][0]["sent"] == 4 and r["timeline"][0]["delivered"] == 3 and r["timeline"][0]["read"] == 1 and r["timeline"][0]["date"] == utcnow().astimezone(IST).date().isoformat()
    assert "cannot tell you how many sales" in r["note"] and not any(w in json.dumps(r).lower() for w in ("conversion", "revenue", "roi"))
    empty = draft(biz, name="Not sent")
    e = biz.get(f"/whatsapp/campaigns/{empty['id']}/results").json()
    assert e["timeline"] == [] and e["delivery_rate"] is None and e["read_rate"] is None


def test_the_comparison_lists_started_campaigns_with_what_whatsapp_reported(wm, admin):
    biz = ready_biz(admin, "Compare Clinic")
    one = run_and_deliver(biz, wm, n=3, deliver=2, read=0)
    draft(biz, name="Still a draft")
    rows = biz.get("/whatsapp/campaigns/compare").json()["items"]
    assert [r["id"] for r in rows] == [one["id"]]  # a draft that never started is not compared
    assert rows[0]["sent"] == 3 and rows[0]["delivered"] == 2 and rows[0]["delivery_rate"] == 67 and rows[0]["read_rate"] == 0 and rows[0]["approved_recipients"] == 3
    assert set(rows[0]) == {"id", "name", "status", "approved_recipients", "sent", "delivered", "read", "failed", "delivery_rate", "read_rate", "opted_out_after", "estimated_meta_cost", "approved_estimate", "started_at"}
    other = make_business("Compare Other")
    assert other.get("/whatsapp/campaigns/compare").json()["items"] == []


def test_the_results_file_lists_each_customer_and_neutralises_formulas_and_is_audited(wm, admin):
    biz = ready_biz(admin, "Csv Camp")
    add_contact(biz, "98765 83001", name="=HYPERLINK(\"http://evil\")", marketing=True, **OWNER)
    add_contact(biz, "98765 83002", name="Ravi", marketing=True, **OWNER)
    c = draft(biz)
    approve(biz, c["id"], 2)
    tick(biz.tenant_id, 0)
    ids = [r[3] for r in messages(biz.tenant_id)]
    raw = payload(statuses=[{"id": ids[0], "status": "delivered", "timestamp": "1700000010"}])
    post_wh(raw)
    process(base.event_id_for(raw))
    r = biz.get(f"/whatsapp/campaigns/{c['id']}/results.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "no-store" in r.headers["cache-control"]
    lines = r.text.splitlines()
    assert lines[0] == "name,phone,result,reason,delivered_at,read_at" and len(lines) == 3
    body = r.text
    assert "'=HYPERLINK" in body and ",=HYPERLINK" not in body and "delivered" in body and "sent" in body
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.campaign_export'", t=biz.tenant_id)[0][0] == 1


def test_duplicating_makes_a_fresh_draft_without_approval_schedule_or_results(wm, admin):
    biz = ready_biz(admin, "Dup Camp", tier="whatsapp_pro")
    audience(biz, 2)
    c = draft(biz, audience={"kind": "all", "tags_any": ["x"]}, scheduled_at=naive_ist(2, 11))
    biz.patch(f"/whatsapp/campaigns/{c['id']}", json={"audience": {"kind": "all"}})
    approve(biz, c["id"], 2)
    tick(biz.tenant_id, 3 * 24 * 60)
    d = biz.post(f"/whatsapp/campaigns/{c['id']}/duplicate")
    assert d.status_code == 201
    j = d.json()
    assert j["id"] != c["id"] and j["name"] == "Diwali offer (copy)" and j["status"] == "draft" and j["scheduled_at"] is None and j["approved_at"] is None and j["variables"] == c["variables"]
    assert owner_query("SELECT status, approved_at IS NULL FROM whatsapp_campaigns WHERE id = :c", c=j["id"])[0] == ("draft", True)
    assert owner_query("SELECT count(*) FROM whatsapp_campaign_recipients WHERE campaign_id = :c", c=j["id"])[0][0] == 0
    assert wm.sent and len(wm.sent) == 2  # the copy sent nothing
    starter = ready_biz(admin, "Dup Starter", tier="whatsapp_starter", wm=wm, fresh=True)
    assert starter.post(f"/whatsapp/campaigns/{c['id']}/duplicate").status_code == 404


# ===================================================================== config, manifest
def test_sending_hours_are_checked_in_the_production_config():
    assert not [p for p in config_problems(good()) if "WINDOW" in p]
    for s, e in ((21, 9), (9, 9), (-1, 20), (9, 25)):
        assert any("WINDOW" in p for p in config_problems(good(whatsapp_enabled=True, whatsapp_send_window_start=s, whatsapp_send_window_end=e))), (s, e)
    assert not [p for p in config_problems(good(whatsapp_enabled=True, whatsapp_send_window_start=0, whatsapp_send_window_end=24)) if "WINDOW" in p]


def test_the_new_routes_are_in_the_access_manifest_with_the_right_roles():
    by = {(m, p): k for k, m, p in (ln.split("\t") for ln in open("tests/route_access_manifest.txt", encoding="utf-8").read().splitlines() if "/whatsapp" in ln)}
    assert by[("GET", "/api/v1/whatsapp/campaigns/compare")] == "member" and by[("POST", "/api/v1/whatsapp/campaigns/{campaign_id}/reschedule")] == "role-admin"
    assert by[("POST", "/api/v1/whatsapp/campaigns/{campaign_id}/duplicate")] == "role-admin" and by[("GET", "/api/v1/whatsapp/campaigns/{campaign_id}/results.csv")] == "role-admin"
    assert io and pytest
