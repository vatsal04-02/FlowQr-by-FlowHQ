"""WhatsApp appointment booking (Phase 9 of the second round). It ships OFF.

What must never happen: two people holding the same slot, a booking that quietly gives consent, a reminder to someone who has not agreed (or said STOP), an assistant that books outside the calendar, touches
another customer's booking or invents a free time. The model is a stub; Meta is a mock. Nothing real is involved."""
import io
import json
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.config import Settings, settings, whatsapp_passthrough_missing
from app.core.db import system_session
from app.models import Tenant
from app.models.base import utcnow
from app.services import mailer
from app.services.whatsapp import ai_text, bookings, conversations, rules, templates
from tests.conftest import owner_exec, owner_query
from tests.test_location_permissions import invite
from tests.test_whatsapp import OWNER, add_contact, wa  # noqa: F401 - fixtures
from tests.test_whatsapp_ai import KNOW, Stub, ai, ai_biz, chat, conv, sent_texts  # noqa: F401 - fixtures and helpers
from tests.test_whatsapp_conversations import conv_of, inbound, inbox_biz, inbox_platform, phone_digits, run  # noqa: F401
from tests.test_whatsapp_messaging import wm  # noqa: F401 - fixtures

IST = bookings.IST
TODAY = datetime.now(IST).date()
ALL_DAYS = [{"weekday": d, "opens": "09:00", "closes": "18:00"} for d in range(7)]
SVC = {"name": "Back pain assessment", "duration_minutes": 45, "buffer_minutes": 15, "price_inr": 600}


@pytest.fixture(autouse=True)
def bk_platform(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_booking_enabled", True)
    mailer.OUTBOX.clear()


def day(n: int) -> str:
    return (TODAY + timedelta(days=n)).isoformat()


def utc_of(d: str, hhmm: str) -> datetime:
    return bookings.parse_start(d, hhmm)


def setup_bookings(biz, *, capacity=1, hours=True, service=True, enable=True, **extra):
    r = biz.put("/whatsapp/bookings/settings", json={"capacity": capacity, "enabled": enable, **extra})
    assert r.status_code == 200, r.text
    if hours:
        assert biz.put("/whatsapp/bookings/hours", json={"days": ALL_DAYS}).status_code == 200
    svc = None
    if service:
        r = biz.post("/whatsapp/bookings/services", json=SVC)
        assert r.status_code == 201, r.text
        svc = r.json()
    return svc


def bk_biz(admin, wm, name, tier="whatsapp_growth", fresh=False, **kw):
    biz = inbox_biz(admin, wm, name, tier=tier, fresh=fresh)
    return biz, setup_bookings(biz, **kw)


def make(biz, svc, d, t, **kw):
    return biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": d, "time": t, "phone": kw.pop("phone", "98765 43210"), "name": kw.pop("name", "Asha"), **kw})


def booking_rows(biz, where="TRUE"):
    return owner_query(f"SELECT code, status, source, service_name, starts_at FROM whatsapp_bookings WHERE tenant_id = :t AND {where} ORDER BY starts_at", t=biz.tenant_id)


# ===================================================================== off by default, plan, roles
def test_the_defaults_are_off_and_the_overlay_passes_the_switch_through():
    assert Settings.model_fields["whatsapp_booking_enabled"].default is False
    import os
    path = next(p for p in ("../deploy/vps/docker-compose.vps.yml", "../../deploy/vps/docker-compose.vps.yml", "/deploy/vps/docker-compose.vps.yml") if os.path.exists(p))
    overlay = open(path, encoding="utf-8").read()
    assert "WHATSAPP_BOOKING_ENABLED: ${WHATSAPP_BOOKING_ENABLED:-false}" in overlay and "WHATSAPP_BOOKING_ENABLED" in whatsapp_passthrough_missing({})


def test_the_platform_switch_the_tier_and_the_business_switch_all_have_to_be_on(wm, admin, monkeypatch):
    biz = inbox_biz(admin, wm, "Switch Clinic", tier="whatsapp_growth")
    monkeypatch.setattr(settings, "whatsapp_booking_enabled", False)
    assert biz.get("/whatsapp/bookings").status_code == 404 and biz.put("/whatsapp/bookings/settings", json={"enabled": True}).json()["detail"]["code"] == "bookings_disabled"
    monkeypatch.setattr(settings, "whatsapp_booking_enabled", True)
    starter = inbox_biz(admin, wm, "Starter No Booking", tier="whatsapp_starter", fresh=True)
    r = starter.put("/whatsapp/bookings/settings", json={"enabled": True})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "plan_required"  # bookings are a Growth and Pro feature
    assert starter.get("/whatsapp/bookings/overview").json()["plan_ok"] is False
    ov = biz.get("/whatsapp/bookings/overview").json()
    assert ov["active"] is False and ov["setup_needed"] == ["Add at least one service", "Set your opening hours"]
    svc = setup_bookings(biz, enable=False)
    assert make(biz, svc, day(3), "10:00").json()["detail"]["code"] == "not_bookable"  # set up but not switched on: nobody can book
    assert biz.put("/whatsapp/bookings/settings", json={"enabled": True}).json()["active"] is True


def test_only_owners_and_admins_set_up_bookings_and_a_limited_member_has_no_calendar(wm, admin):
    biz, svc = bk_biz(admin, wm, "Roles Clinic")
    member = invite(biz, role="staff")
    assert member.get("/whatsapp/bookings").status_code == 200 and member.get("/whatsapp/bookings/overview").status_code == 200
    assert member.put("/whatsapp/bookings/settings", json={"capacity": 5}).status_code == 403
    assert member.post("/whatsapp/bookings/services", json=SVC).status_code == 403
    assert make(member, svc, day(3), "10:00").status_code == 201  # any team member may book a customer in
    limited = invite(biz, role="staff", location_ids=[biz.location_id])
    assert limited.get("/whatsapp/bookings").status_code == 403


def test_settings_services_hours_and_closed_days_are_validated(wm, admin):
    biz, svc = bk_biz(admin, wm, "Validation Clinic")
    for bad in ({"capacity": 0}, {"capacity": 51}, {"slot_step_minutes": 3}, {"max_days_ahead": 0}, {"reminder_day_hour": 8}, {"reminder_soon_hours": 7}):
        assert biz.put("/whatsapp/bookings/settings", json=bad).status_code == 422, bad
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.booking_settings'", t=biz.tenant_id)[0][0] >= 1
    assert biz.post("/whatsapp/bookings/services", json={**SVC, "duration_minutes": 3}).status_code == 422
    assert biz.post("/whatsapp/bookings/services", json={**SVC, "buffer_minutes": 500}).status_code == 422
    assert biz.post("/whatsapp/bookings/services", json={**SVC, "name": "x"}).status_code == 422
    assert biz.post("/whatsapp/bookings/services", json={**SVC, "price_inr": "cheap"}).status_code == 422
    assert biz.put("/whatsapp/bookings/hours", json={"days": [{"weekday": 0, "opens": "18:00", "closes": "09:00"}]}).status_code == 422
    assert biz.put("/whatsapp/bookings/hours", json={"days": [{"weekday": 0, "opens": "09:00", "closes": "10:00"}, {"weekday": 0, "opens": "11:00", "closes": "12:00"}]}).status_code == 422
    assert biz.put("/whatsapp/bookings/hours", json={"days": [{"weekday": 9, "opens": "09:00", "closes": "10:00"}]}).status_code == 422
    assert biz.put("/whatsapp/bookings/hours", json={"days": [{"weekday": 0, "opens": "9am", "closes": "10:00"}]}).status_code == 422
    assert biz.post("/whatsapp/bookings/closed-days", json={"day": day(5), "reason": "Diwali"}).status_code == 201
    ov = biz.get("/whatsapp/bookings/overview").json()
    assert [c["reason"] for c in ov["closed"]] == ["Diwali"] and len(ov["hours"]) == 7


# ===================================================================== availability, capacity, buffers
def free(biz, svc, d):
    return [s["time"] for s in biz.get(f"/whatsapp/bookings/slots?service_id={svc['id']}&day={d}").json()["slots"]]


def test_slots_follow_the_hours_closed_days_the_length_and_the_buffer(wm, admin):
    biz, svc = bk_biz(admin, wm, "Slots Clinic")
    d = day(4)
    times = free(biz, svc, d)
    assert times[0] == "09:00" and times[-1] == "17:00" and "17:30" not in times  # a 45 minute visit must finish by the 18:00 close
    assert make(biz, svc, d, "10:00").status_code == 201  # 10:00 to 10:45, kept busy until 11:00 by the 15 minute buffer
    after = free(biz, svc, d)
    assert "09:30" not in after  # 9:30 would run to 10:15 into the booking
    assert "10:00" not in after and "10:30" not in after and "11:00" in after and "09:00" in after
    biz.post("/whatsapp/bookings/closed-days", json={"day": day(6), "reason": "Holiday"})
    assert free(biz, svc, day(6)) == []
    assert make(biz, svc, day(6), "10:00").json()["detail"]["code"] == "closed_day"


def test_the_server_refuses_outside_hours_the_past_too_soon_too_far_and_a_taken_time(wm, admin):
    biz, svc = bk_biz(admin, wm, "Refusals Clinic", min_notice_minutes=120, max_days_ahead=10)
    d = day(3)
    for t, code in (("08:00", "outside_hours"), ("17:30", "outside_hours"), ("18:30", "outside_hours")):
        r = make(biz, svc, d, t)
        assert r.status_code == 409 and r.json()["detail"]["code"] == code, (t, r.text)
    assert make(biz, svc, day(-1), "10:00").json()["detail"]["code"] == "in_the_past"
    assert make(biz, svc, day(40), "10:00").json()["detail"]["code"] == "too_far"
    assert make(biz, svc, d, "10:00").status_code == 201
    taken = make(biz, svc, d, "10:30", phone="98765 40002")
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "slot_taken"
    assert make(biz, svc, d, "banana").status_code == 422 and make(biz, svc, "2026-13-45", "10:00").status_code == 422
    assert len(booking_rows(biz)) == 1


def test_capacity_lets_that_many_overlap_and_no_more_checked_at_every_instant(wm, admin):
    biz, svc = bk_biz(admin, wm, "Capacity Clinic", capacity=2)
    d = day(4)
    assert make(biz, svc, d, "10:00").status_code == 201 and make(biz, svc, d, "10:00", phone="98765 40002").status_code == 201
    assert make(biz, svc, d, "10:00", phone="98765 40003").json()["detail"]["code"] == "slot_taken"
    assert make(biz, svc, d, "10:30", phone="98765 40004").json()["detail"]["code"] == "slot_taken"  # both are still there at 10:30
    # two back-to-back bookings never overlap each other, so a third may sit across the join while capacity is 2
    assert make(biz, svc, d, "13:00", phone="98765 40005").status_code == 201 and make(biz, svc, d, "14:00", phone="98765 40006").status_code == 201
    long = biz.post("/whatsapp/bookings/services", json={"name": "Long session", "duration_minutes": 90, "buffer_minutes": 0}).json()
    assert make(biz, long, d, "13:30", phone="98765 40007").status_code == 201  # only one other person is there at any moment
    assert make(biz, long, d, "13:30", phone="98765 40008").json()["detail"]["code"] == "slot_taken"


def test_two_people_racing_for_the_last_slot_cannot_both_get_it(wm, admin):
    """The check and the write happen under a lock on the business's booking settings, so the server, not luck, decides."""
    biz, svc = bk_biz(admin, wm, "Race Clinic")
    d = day(5)
    barrier = threading.Barrier(8)

    def go(i):
        barrier.wait()
        return make(biz, svc, d, "11:00", phone=f"98765 5{i:04d}").status_code
    with ThreadPoolExecutor(max_workers=8) as ex:
        codes = list(ex.map(go, range(8)))
    assert sorted(codes) == [201] + [409] * 7, codes
    assert len(booking_rows(biz)) == 1


def test_a_repeated_request_with_the_same_key_books_once(wm, admin):
    biz, svc = bk_biz(admin, wm, "Idempotent Clinic")
    a = make(biz, svc, day(3), "10:00", client_id="same-click")
    b = make(biz, svc, day(3), "10:00", client_id="same-click")
    assert a.status_code == 201 and b.status_code == 201 and a.json()["id"] == b.json()["id"] and len(booking_rows(biz)) == 1


# ===================================================================== change, cancel, done, no-show
def test_reschedule_cancel_and_the_calendar(wm, admin):
    biz, svc = bk_biz(admin, wm, "Change Clinic")
    d = day(4)
    a = make(biz, svc, d, "10:00").json()
    b = make(biz, svc, d, "12:00", phone="98765 40002").json()
    assert biz.post(f"/whatsapp/bookings/{a['id']}/reschedule", json={"date": d, "time": "12:00"}).json()["detail"]["code"] == "slot_taken"
    assert biz.post(f"/whatsapp/bookings/{a['id']}/reschedule", json={"date": d, "time": "10:30"}).status_code == 200  # it does not collide with itself
    moved = biz.get(f"/whatsapp/bookings?start={d}&end={d}").json()["items"]
    assert [m["when"].split(" at ")[1] for m in moved] == ["10:30 am", "12:00 pm"]
    assert biz.post(f"/whatsapp/bookings/{b['id']}/cancel", json={"reason": "Customer called"}).json()["status"] == "cancelled"
    assert make(biz, svc, d, "12:00", phone="98765 40003").status_code == 201  # a cancelled booking frees its place
    assert biz.post(f"/whatsapp/bookings/{b['id']}/cancel", json={}).json()["detail"]["code"] == "not_booked"
    assert biz.post(f"/whatsapp/bookings/{b['id']}/reschedule", json={"date": d, "time": "15:00"}).json()["detail"]["code"] == "not_booked"
    assert [x["status"] for x in biz.get(f"/whatsapp/bookings?start={d}&end={d}&status=cancelled").json()["items"]] == ["cancelled"]


def test_done_and_no_show_only_after_the_start_and_done_feeds_the_review_request(wm, admin):
    biz, svc = bk_biz(admin, wm, "Visit Clinic")
    c = add_contact(biz, "98765 41111", name="Ravi", utility=True, **OWNER)
    r = biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3), "time": "10:00", "contact_id": c["id"]})
    assert r.status_code == 201
    bid = r.json()["id"]
    assert biz.post(f"/whatsapp/bookings/{bid}/done").json()["detail"]["code"] == "too_early"  # the visit has not happened yet
    owner_exec("UPDATE whatsapp_bookings SET starts_at = now() - interval '3 hours', ends_at = now() - interval '2 hours', blocks_until = now() - interval '2 hours' WHERE id = :i", i=bid)
    done = biz.post(f"/whatsapp/bookings/{bid}/done").json()
    assert done["status"] == "done" and done["review"] == {"scheduled": False, "reason": "automation_off"}  # the visit is recorded even with the review helper off
    assert owner_query("SELECT last_visit_at IS NOT NULL FROM whatsapp_contacts WHERE id = :i", i=c["id"])[0][0] is True
    assert biz.post(f"/whatsapp/bookings/{bid}/no-show").json()["detail"]["code"] == "not_booked"
    # with the review helper on (template approved, customer agreed to updates) the same click schedules the one neutral request
    assert biz.post("/whatsapp/templates/install", json={"key": "review_followup"}).status_code == 200
    assert biz.put("/whatsapp/automations/review_followup", json={"status": "on"}).status_code == 200
    r2 = biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(4), "time": "10:00", "contact_id": c["id"]})
    b2 = r2.json()["id"]
    owner_exec("UPDATE whatsapp_bookings SET starts_at = now() - interval '4 hours', ends_at = now() - interval '3 hours', blocks_until = now() - interval '3 hours' WHERE id = :i", i=b2)
    assert biz.post(f"/whatsapp/bookings/{b2}/done").json()["review"]["scheduled"] is True
    r3 = biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(5), "time": "10:00", "phone": "98765 42222", "name": "Meena"})
    b3 = r3.json()["id"]
    owner_exec("UPDATE whatsapp_bookings SET starts_at = now() - interval '4 hours', ends_at = now() - interval '3 hours', blocks_until = now() - interval '3 hours' WHERE id = :i", i=b3)
    assert biz.post(f"/whatsapp/bookings/{b3}/no-show").json()["status"] == "no_show"
    assert owner_query("SELECT last_visit_at IS NULL FROM whatsapp_contacts WHERE tenant_id = :t AND phone = '+919876542222'", t=biz.tenant_id)[0][0] is True  # a no-show is not a visit


# ===================================================================== a booking never gives consent
def test_a_booking_made_by_a_person_creates_no_consent_unless_they_attest_it_the_usual_way(wm, admin):
    biz, svc = bk_biz(admin, wm, "No Consent Booking")
    assert make(biz, svc, day(3), "10:00").status_code == 201
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0  # a booking is not consent
    c = biz.get("/whatsapp/contacts").json()["items"][0]
    assert c["marketing"] is None and c["utility"] is None and c["occasion"] is None
    no_note = make(biz, svc, day(3), "12:00", phone="98765 40002", agreed_to_updates=True)
    assert no_note.status_code == 422 and len(booking_rows(biz)) == 1  # "they agreed" without a note of how is refused, and nothing is booked
    ok = make(biz, svc, day(3), "13:00", phone="98765 40003", agreed_to_updates=True, agreed_evidence="Asked at the counter and wrote it in the register")
    assert ok.status_code == 201
    rows = owner_query("SELECT purpose, source FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)
    assert rows == [("utility", "owner_entry")]  # visit updates only: never offers, never greetings


# ===================================================================== the assistant books, server-validated
def ai_book_biz(admin, wm, name, **kw):
    biz = ai_biz(admin, wm, name, **kw)
    svc = setup_bookings(biz)
    return biz, svc


def book_script(d, t="10:00"):
    return [{"action": "check_slots", "service": "Back pain assessment", "date": d}, {"action": "book", "service": "Back pain assessment", "date": d, "time": t}]


def test_the_assistant_books_through_the_server_and_asks_the_customer_for_updates_consent_with_a_fixed_question(wm, admin, ai):
    biz, svc = ai_book_biz(admin, wm, "AI Booking")
    d = day(4)
    ai.use(*book_script(d))
    cid, phone, out = chat(biz, "I want to book a back pain assessment for tomorrow morning")
    assert out["replied"] == 1 and len(ai.stub.calls) == 2
    assert "CALENDAR" in ai.stub.calls[1][1] and "Free times" in ai.stub.calls[1][1] and "Services that can be booked" in ai.stub.calls[1][1]
    text = sent_texts(wm)[0]
    assert text.startswith("Hi! I'm the automated assistant for AI Booking.") and "Your appointment is booked: Back pain assessment," in text
    assert text.endswith("Reply YES if you would.")  # the booking confirmation and the question are fixed server text, not the model's
    (row,) = booking_rows(biz)
    assert row[1:4] == ("booked", "ai", "Back pain assessment") and row[4] == utc_of(d, "10:00")
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0  # asked, not assumed
    assert owner_query("SELECT booking_consent_ask_id IS NOT NULL FROM whatsapp_conversations WHERE id = :i", i=cid)[0][0] is True
    assert owner_query("SELECT counted FROM whatsapp_ai_runs WHERE tenant_id = :t", t=biz.tenant_id)[0][0] is True


@pytest.mark.parametrize("answer,gets_consent", [("yes", True), ("YES!", True), ("Haan", True), ("हाँ", True), ("ok", True), ("no", False), ("nahi", False), ("yes but not on Sundays", False), ("maybe later", False), ("", False)])
def test_only_a_short_explicit_yes_in_the_chat_records_consent_and_only_for_visit_updates(wm, admin, ai, answer, gets_consent):
    biz, svc = ai_book_biz(admin, wm, f"Consent {abs(hash(answer)) % 9999}")
    ai.use(*book_script(day(4)))
    cid, phone, _ = chat(biz, "please book me a back pain assessment")
    calls = len(ai.stub.calls)
    if answer:
        ai.use({"action": "reply", "kind": "greet", "text": "", "sources": []})  # only used if the message is NOT an answer to the question
        inbound(biz, answer, phone=phone)
        run(biz)
    rows = owner_query("SELECT purpose, source, wording_version, left(evidence, 12) FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)
    if gets_consent:
        assert [r[:3] for r in rows] == [("utility", "whatsapp_booking", "booking-1")] and rows[0][3].startswith("Replied")
        assert len(ai.stub.calls) == 0 and sent_texts(wm)[-1] in ai_text.UPDATES_YES.values()  # answered by fixed text, no model involved
    else:
        assert rows == []  # silence, "no", and anything that is not a plain yes are not consent
    assert not any(r[0] in ("marketing", "occasion") for r in rows)
    if answer:
        assert owner_query("SELECT booking_consent_ask_id IS NULL FROM whatsapp_conversations WHERE id = :i", i=cid)[0][0] is True  # the question is not asked twice


def test_a_yes_that_comes_a_day_late_is_not_consent(wm, admin, ai):
    biz, svc = ai_book_biz(admin, wm, "Late Yes")
    ai.use(*book_script(day(4)))
    cid, phone, _ = chat(biz, "book me a back pain assessment")
    owner_exec("UPDATE whatsapp_conversations SET booking_consent_asked_at = now() - interval '30 hours' WHERE id = :i", i=cid)
    inbound(biz, "yes", phone=phone)
    ai.use({"action": "reply", "kind": "greet", "text": "", "sources": []})
    run(biz)
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0


def test_the_model_cannot_grant_consent_or_name_another_customer(wm, admin, ai):
    biz, svc = ai_book_biz(admin, wm, "Schema Booking")
    ai.use({"action": "book", "service": "Back pain assessment", "date": day(4), "time": "10:00", "consent": True, "phone": "+919999999999"})
    cid, _, out = chat(biz, "book me in")
    assert out["handoff"] == 1 and booking_rows(biz) == []  # unknown fields are rejected, so there is no field that could carry consent or someone else's number
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0


def test_the_assistant_cannot_double_book_the_server_refuses_and_the_customer_is_offered_other_times(wm, admin, ai):
    biz, svc = ai_book_biz(admin, wm, "AI Double")
    d = day(4)
    assert make(biz, svc, d, "10:00").status_code == 201
    ai.use({"action": "book", "service": "Back pain assessment", "date": d, "time": "10:00"},
           {"action": "reply", "kind": "answer", "text": "That time is taken. 11:00 am is free.", "sources": ["S1"]})
    cid, _, out = chat(biz, "book me at 10 please")
    assert len(booking_rows(biz)) == 1 and "That could not be booked: That time is already taken." in ai.stub.calls[1][1]
    assert out["replied"] == 1 and "11:00 am is free" in sent_texts(wm)[0]


def test_a_time_the_calendar_never_listed_is_never_offered(wm, admin, ai):
    biz, svc = ai_book_biz(admin, wm, "AI Invented Time")
    ai.use({"action": "check_slots", "service": "Back pain assessment", "date": day(4)}, {"action": "reply", "kind": "answer", "text": "We have 4:45 pm free.", "sources": ["S1"]})
    cid, _, out = chat(biz, "any time free?")
    assert out["handoff"] == 1 and "4:45" not in " ".join(sent_texts(wm)) and conv(biz, cid)["handoff_reason"] == "reply_blocked"


def test_the_assistant_touches_only_the_customers_own_bookings(wm, admin, ai):
    biz, svc = ai_book_biz(admin, wm, "AI Own Only")
    d = day(4)
    ai.use(*book_script(d, "10:00"))
    cid1, phone1, _ = chat(biz, "book me a back pain assessment")
    mine = owner_query("SELECT code FROM whatsapp_bookings WHERE tenant_id = :t", t=biz.tenant_id)[0][0]
    ai.use({"action": "cancel", "code": mine}, {"action": "handoff", "reason": "low_confidence"})  # someone else tries to cancel that booking by its code
    cid2, phone2, _ = chat(biz, "cancel booking " + mine)
    assert "No upcoming booking with that code for this customer" in ai.stub.calls[0][1] + (ai.stub.calls[1][1] if len(ai.stub.calls) > 1 else "")
    assert booking_rows(biz)[0][1] == "booked"
    # the owner of the booking can move and cancel it
    ai.use({"action": "reschedule", "date": d, "time": "12:00"})
    inbound(biz, "move it to 12", phone=phone1)
    assert run(biz)["replied"] == 1 and booking_rows(biz)[0][4] == utc_of(d, "12:00") and "moved" in sent_texts(wm)[-1]
    ai.use({"action": "cancel"})
    inbound(biz, "cancel it", phone=phone1)
    assert run(biz)["replied"] == 1 and booking_rows(biz)[0][1] == "cancelled" and "cancelled" in sent_texts(wm)[-1]


def test_booking_through_the_assistant_needs_bookings_on_and_set_up(wm, admin, ai):
    biz = ai_biz(admin, wm, "AI Not Set Up")
    setup_bookings(biz, service=False)  # on, but nothing to book yet
    ai.use({"action": "book", "service": "Back pain assessment", "date": day(4), "time": "10:00"})
    cid, _, out = chat(biz, "book me in")
    assert out["handoff"] == 1 and booking_rows(biz) == [] and "booking tools" not in ai.stub.calls[0][0]
    biz2 = ai_biz(admin, wm, "AI Booking Off", fresh=True)  # not switched on at all: the assistant is told to hand booking requests over
    ai.use({"action": "book", "service": "Back pain assessment", "date": day(4), "time": "10:00"})
    cid2, _, out2 = chat(biz2, "book me in")
    assert out2["handoff"] == 1 and "handoff" in ai.stub.calls[0][0] and conv(biz2, cid2)["handoff_reason"] == "not_in_knowledge"


def test_test_it_chat_shows_real_availability_but_never_books(wm, admin, ai):
    biz, svc = ai_book_biz(admin, wm, "Dry Run")
    ai.use({"action": "book", "service": "Back pain assessment", "date": day(4), "time": "10:00"})
    r = biz.post("/whatsapp/ai/test-chat", json={"message": "book me a back pain assessment"})
    assert r.status_code == 200 and "Test only" in r.json()["reply"] and booking_rows(biz) == [] and wm.sent == []
    ai.use({"action": "book", "service": "Back pain assessment", "date": day(4), "time": "23:00"}, {"action": "handoff", "reason": "low_confidence"})
    biz.post("/whatsapp/ai/test-chat", json={"message": "book me at 11 pm"})
    assert "That could not be booked: That time is outside the opening hours." in ai.stub.calls[1][1]  # the test uses the real rules


# ===================================================================== reminders: fixed templates, the gate fails closed
def reminders_biz(admin, wm, name, *, category=("utility", True), consent_updates=True, consent_marketing=False, hour=10, **kw):
    biz, svc = bk_biz(admin, wm, name, **kw)
    biz.put("/whatsapp/bookings/settings", json={"reminders_enabled": True, "reminder_day_hour": 10, "reminder_soon_hours": 2})
    for k in ("booking_reminder_day", "booking_reminder_soon"):
        assert biz.post("/whatsapp/templates/install", json={"key": k}).status_code == 200
    set_category(biz, *category)
    c = add_contact(biz, "98765 44444", name="Asha", **({"utility": True, **OWNER} if consent_updates else {}), **({"marketing": True} if consent_marketing else {}))
    return biz, svc, c


def set_category(biz, category, confirmed, status="approved"):
    owner_exec("UPDATE whatsapp_templates SET category = :c, category_confirmed = :k, approval_status = :s WHERE tenant_id = :t AND template_name LIKE 'flowqr_booking_reminder%'", c=category, k=confirmed, s=status, t=biz.tenant_id)


def pass_at(biz, when: datetime):
    db = system_session()
    try:
        out = bookings.run_reminders(db, when, tenant_id=uuid.UUID(biz.tenant_id))
        db.commit()
        return out
    finally:
        db.close()


def day_before_hour(d: str) -> datetime:
    return bookings.to_utc(date.fromisoformat(d) - timedelta(days=1), datetime.min.time().replace(hour=10, minute=5))


def book_for(biz, svc, c, d, t="14:00"):
    r = biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": d, "time": t, "contact_id": c["id"]})
    assert r.status_code == 201, r.text
    return r.json()


def template_sends(wm):
    return [m for m in wm.sent if m.get("type") == "template"]


def test_the_reminder_templates_are_fixed_utility_wording_with_no_offers_and_only_for_their_own_kind():
    for key in ("booking_reminder_day", "booking_reminder_soon"):
        t = templates.STANDARD[key]
        assert t["category"] == "utility" and not rules.marketing_terms(t["body"]) and len(t["variables"]) == 4
    from app.services.whatsapp import sender
    assert sender.KIND_TEMPLATES["booking_reminder"] == ("booking_reminder_day", "booking_reminder_soon") and "booking_reminder" in sender.GAP_EXEMPT
    assert rules.wording_for("utility", "Acme Clinic", "booking-1").startswith("I agree to receive confirmations and reminders about my appointment with Acme Clinic")


def test_a_reminder_is_sent_when_updates_consent_exists_and_whatsapp_has_confirmed_the_category_is_utility(wm, admin):
    biz, svc, c = reminders_biz(admin, wm, "Remind Clinic")
    d = day(3)
    book_for(biz, svc, c, d)
    assert pass_at(biz, day_before_hour(d) - timedelta(minutes=30)) == {"sent": 0, "skipped": 0} and template_sends(wm) == []  # not yet the chosen hour
    assert pass_at(biz, day_before_hour(d)) == {"sent": 1, "skipped": 0}
    (m,) = template_sends(wm)
    assert m["template"]["name"] == "flowqr_booking_reminder_day_en" and m["to"] == "919876544444"
    assert [p["text"] for p in m["template"]["components"][0]["parameters"]][1:3] == ["Remind Clinic", "Back pain assessment"]
    led = owner_query("SELECT category, kind, delivery_status FROM whatsapp_messages WHERE tenant_id = :t", t=biz.tenant_id)
    assert led == [("utility", "booking_reminder", "sent")]
    assert pass_at(biz, day_before_hour(d) + timedelta(minutes=10)) == {"sent": 0, "skipped": 0} and len(template_sends(wm)) == 1  # never twice
    assert pass_at(biz, utc_of(d, "14:00") - timedelta(hours=2)) == {"sent": 1, "skipped": 0} and len(template_sends(wm)) == 2  # and the second reminder, a few hours before
    assert owner_query("SELECT reminder_day_result, reminder_soon_result FROM whatsapp_bookings WHERE tenant_id = :t", t=biz.tenant_id)[0] == ("sent", "sent")


@pytest.mark.parametrize("category,agreed_offers,expected", [
    (("utility", False), False, "no_marketing_consent"),  # category not yet reported by WhatsApp: fail closed, offers consent is needed too
    (("marketing", True), False, "no_marketing_consent"),  # WhatsApp says marketing: offers consent is needed too
    (("utility", False), True, "sent"), (("marketing", True), True, "sent"),
    (("utility", True), False, "sent"),  # confirmed utility: updates consent is enough
])
def test_the_gate_fails_closed_until_the_category_is_confirmed_utility(wm, admin, category, agreed_offers, expected):
    biz, svc, c = reminders_biz(admin, wm, f"Closed {category}{agreed_offers}", category=category, consent_marketing=agreed_offers)
    d = day(3)
    book_for(biz, svc, c, d)
    pass_at(biz, day_before_hour(d))
    assert owner_query("SELECT reminder_day_result FROM whatsapp_bookings WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == expected
    assert len(template_sends(wm)) == (1 if expected == "sent" else 0)


def test_no_reminder_without_updates_consent_after_stop_or_when_the_booking_is_not_active(wm, admin):
    biz, svc, c = reminders_biz(admin, wm, "No Reminder Cases", consent_updates=False)
    d = day(3)
    b = book_for(biz, svc, c, d)
    pass_at(biz, day_before_hour(d))
    assert owner_query("SELECT reminder_day_result FROM whatsapp_bookings WHERE id = :i", i=b["id"])[0][0] == "no_utility_consent" and template_sends(wm) == []  # a booking is not consent
    owner = add_contact(biz, "98765 45555", name="Stopper", utility=True, marketing=True, **OWNER)
    b2 = book_for(biz, svc, owner, d, "16:00")
    owner_exec("UPDATE whatsapp_contacts SET marketing_opted_out_at = now() WHERE id = :i", i=owner["id"])  # they replied STOP
    pass_at(biz, day_before_hour(d))
    assert owner_query("SELECT reminder_day_result FROM whatsapp_bookings WHERE id = :i", i=b2["id"])[0][0] == "opted_out" and template_sends(wm) == []
    ok = add_contact(biz, "98765 46666", name="Fine", utility=True, **OWNER)
    b3 = book_for(biz, svc, ok, d, "11:00")
    biz.post(f"/whatsapp/bookings/{b3['id']}/cancel", json={})
    pass_at(biz, day_before_hour(d))
    assert owner_query("SELECT reminder_day_result FROM whatsapp_bookings WHERE id = :i", i=b3["id"])[0][0] is None and template_sends(wm) == []  # cancelled: nothing


def test_reminders_wait_for_approval_respect_the_night_the_plan_and_the_switches(wm, admin, monkeypatch):
    biz, svc, c = reminders_biz(admin, wm, "Reminder Limits")
    d = day(3)
    b = book_for(biz, svc, c, d, "09:30")
    set_category(biz, "utility", True, status="pending")
    pass_at(biz, day_before_hour(d))
    assert owner_query("SELECT reminder_day_result FROM whatsapp_bookings WHERE id = :i", i=b["id"])[0][0] is None  # not approved yet: tried again later, not given up on
    set_category(biz, "utility", True)
    assert pass_at(biz, utc_of(d, "09:30") - timedelta(hours=2)) == {"sent": 0, "skipped": 1}  # the second reminder would land at 7:30 in the morning: skipped, never sent at night
    assert owner_query("SELECT reminder_soon_result FROM whatsapp_bookings WHERE id = :i", i=b["id"])[0][0] == "outside_hours"
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", False)
    assert pass_at(biz, day_before_hour(d)) == {"held": True}
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", True)
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", True)
    assert pass_at(biz, day_before_hour(d)) == {"held": True} and template_sends(wm) == []
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", False)
    biz.put("/whatsapp/bookings/settings", json={"reminders_enabled": False})
    assert pass_at(biz, day_before_hour(d)) == {"sent": 0, "skipped": 0} and template_sends(wm) == []


def test_a_rescheduled_booking_gets_fresh_reminders_for_its_new_time(wm, admin):
    biz, svc, c = reminders_biz(admin, wm, "Reschedule Reminders")
    d = day(3)
    b = book_for(biz, svc, c, d, "14:00")
    pass_at(biz, day_before_hour(d))
    assert len(template_sends(wm)) == 1
    d2 = day(5)
    assert biz.post(f"/whatsapp/bookings/{b['id']}/reschedule", json={"date": d2, "time": "15:00"}).status_code == 200
    assert owner_query("SELECT reminder_day_result FROM whatsapp_bookings WHERE id = :i", i=b["id"])[0][0] is None
    pass_at(biz, day_before_hour(d2))
    assert len(template_sends(wm)) == 2


def test_the_gate_refuses_a_reminder_under_any_other_template_or_kind(wm, admin):
    biz, svc, c = reminders_biz(admin, wm, "Kind Guard", consent_marketing=True)
    from app.services.whatsapp import sender
    db = system_session()
    try:
        t = db.get(Tenant, uuid.UUID(biz.tenant_id))
        from app.models.whatsapp import WhatsAppContact
        contact = db.get(WhatsAppContact, uuid.UUID(c["id"]))
        offer = templates.standard_row(db, t.id, "offer")  # installed with the standard set
        assert offer is not None
        res = sender.send_template(db, t, contact, offer, ["Asha", "Kind Guard", "10% off"], idem_key="k1", kind="booking_reminder")
        assert res.reason == "kind_mismatch" and res.status == "skipped"  # an offer can never be sent under the reminder kind
    finally:
        db.rollback()
        db.close()
    assert template_sends(wm) == []


def test_a_business_that_drops_to_starter_gets_no_bookings_or_reminders(wm, admin):
    from tests.test_whatsapp import grant_addon
    biz, svc, c = reminders_biz(admin, wm, "Starter Reminders")
    book_for(biz, svc, c, day(3))
    grant_addon(admin, biz, "whatsapp_starter")  # the add-on is changed by hand: the bookings and reminders part of it goes
    assert biz.get("/whatsapp/bookings").status_code == 403 and make(biz, svc, day(4), "10:00").status_code == 403
    assert pass_at(biz, day_before_hour(day(3))) == {"sent": 0, "skipped": 0} and template_sends(wm) == []
    assert len(booking_rows(biz)) == 1  # nothing is deleted: the customer's booking is still there


# ===================================================================== isolation, retention, export
def test_one_business_cannot_see_or_change_anothers_bookings_services_or_settings(wm, admin):
    a, sa = bk_biz(admin, wm, "Iso Book A")
    b, sb = bk_biz(admin, wm, "Iso Book B", fresh=True)
    mine = make(a, sa, day(3), "10:00").json()
    assert b.get("/whatsapp/bookings").json()["items"] == [] and b.get("/whatsapp/bookings/overview").json()["services"] != a.get("/whatsapp/bookings/overview").json()["services"]
    for path, body in (("reschedule", {"date": day(3), "time": "12:00"}), ("cancel", {}), ("done", None), ("no-show", None)):
        assert b.post(f"/whatsapp/bookings/{mine['id']}/{path}", json=body or {}).status_code == 404
    assert b.patch(f"/whatsapp/bookings/services/{sa['id']}", json={**SVC, "name": "Hijacked"}).status_code == 404
    assert b.delete(f"/whatsapp/bookings/services/{sa['id']}").status_code == 404
    assert make(b, sa, day(3), "10:00").status_code == 404  # another business's service cannot be booked
    assert booking_rows(a)[0][1] == "booked" and make(b, sb, day(3), "10:00").status_code == 201  # the same time is free for B: capacity is per business
    for table in ("whatsapp_booking_settings", "whatsapp_booking_services", "whatsapp_booking_hours", "whatsapp_booking_closed", "whatsapp_bookings"):
        assert owner_query("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :n", n=table)[0] == (True, True), table


def test_a_customer_with_a_booking_is_kept_by_the_retention_purge_a_stranger_is_not(wm, admin):
    biz, svc = bk_biz(admin, wm, "Purge Bookings")
    _, phone1, _ = inbound(biz, "hello")
    inbound(biz, "hello", phone=phone_digits())
    contact = owner_query("SELECT id FROM whatsapp_contacts WHERE tenant_id = :t AND phone = :p", t=biz.tenant_id, p="+" + phone1)[0][0]
    assert biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3), "time": "10:00", "contact_id": str(contact)}).status_code == 201
    owner_exec("UPDATE whatsapp_contacts SET created_at = now() - interval '200 days' WHERE tenant_id = :t", t=biz.tenant_id)
    owner_exec("UPDATE whatsapp_conversations SET created_at = now() - interval '200 days' WHERE tenant_id = :t", t=biz.tenant_id)
    owner_exec("UPDATE whatsapp_conversation_messages SET created_at = now() - interval '200 days' WHERE tenant_id = :t", t=biz.tenant_id)
    db = system_session()
    try:
        conversations.purge(db)
        db.commit()
    finally:
        db.close()
    left = {r[0] for r in owner_query("SELECT phone FROM whatsapp_contacts WHERE tenant_id = :t", t=biz.tenant_id)}
    assert left == {"+" + phone1}  # the stranger who only wrote once is gone; the customer with a booking stays


def test_export_and_deletion_cover_bookings_and_everything_is_deleted_with_the_business(wm, admin):
    biz, svc = bk_biz(admin, wm, "Export Bookings")
    r = make(biz, svc, day(3), "10:00")
    assert r.status_code == 201
    biz.post("/whatsapp/bookings/closed-days", json={"day": day(6), "reason": "x"})
    z = zipfile.ZipFile(io.BytesIO(biz.get("/account/export").content))
    assert {"whatsapp_booking_settings.json", "whatsapp_booking_services.json", "whatsapp_booking_hours.json", "whatsapp_booking_closed.json", "whatsapp_bookings.json"} <= set(z.namelist())
    assert "Back pain assessment" in z.read("whatsapp_bookings.json").decode()
    contact = biz.get("/whatsapp/contacts").json()["items"][0]
    assert biz.delete(f"/whatsapp/contacts/{contact['id']}").status_code == 204  # deleting the customer deletes their bookings
    assert booking_rows(biz) == []
    fks = owner_query("SELECT c.relname, con.confdeltype FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY (con.conkey) "
                      "WHERE con.contype = 'f' AND a.attname = 'tenant_id' AND c.relname LIKE 'whatsapp_booking%'")
    assert len(fks) == 5 and all(d == "c" for _, d in fks)  # and with the business


def test_migration_0058_shape():
    from tests.conftest import make_business
    biz = make_business("Migration 58")
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] >= "0058"
    with pytest.raises(Exception):
        owner_exec("INSERT INTO whatsapp_booking_settings (id, tenant_id, capacity) VALUES (gen_random_uuid(), :t, 0)", t=biz.tenant_id)
    with pytest.raises(Exception):
        owner_exec("INSERT INTO whatsapp_booking_hours (id, tenant_id, weekday, opens, closes) VALUES (gen_random_uuid(), :t, 1, '10:00', '09:00')", t=biz.tenant_id)
    with pytest.raises(Exception):
        owner_exec("INSERT INTO whatsapp_booking_services (id, tenant_id, name, duration_minutes) VALUES (gen_random_uuid(), :t, 'x', 2)", t=biz.tenant_id)
    assert "whatsapp_booking" in owner_query("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_wa_consent_source'")[0][0]


# ===================================================================== small pure pieces
@pytest.mark.parametrize("text,expected", [("yes", "yes"), ("Yes!", "yes"), ("  haan ", "yes"), ("ji haan", "yes"), ("हां", "yes"), ("ठीक है", "yes"), ("no", "no"), ("No thanks", "no"), ("nahi", "no"), ("नहीं", "no"),
                                           ("yes, and send me offers", None), ("what time?", None), ("y" * 30, None), ("", None), ("yesss", None), ("not now", None)])
def test_consent_answers_are_short_and_explicit(text, expected):
    assert bookings.consent_answer(text) == expected


def test_times_are_shown_in_india_time_in_plain_words():
    assert bookings.when_text(datetime(2026, 11, 21, 5, 0, tzinfo=timezone.utc)) == "Sat 21 Nov at 10:30 am"
    assert bookings.when_text(datetime(2026, 11, 21, 12, 30, tzinfo=timezone.utc)) == "Sat 21 Nov at 6:00 pm"
    assert bookings.clock_text(datetime(2026, 11, 21, 6, 30, tzinfo=timezone.utc)) == "12:00 pm"
    assert ai_text.say(ai_text.BOOKED, "en", "X", service="S", when="W") == "Your appointment is booked: S, W."
    assert not any(rules.marketing_terms(ai_text.say(t, lang, "Acme Clinic", service="Facial", when="Sat 21 Nov at 10:30 am")) for t in (ai_text.BOOKED, ai_text.ASK_UPDATES, ai_text.UPDATES_YES, ai_text.UPDATES_NO,
                                                                                                                                   ai_text.RESCHEDULED, ai_text.CANCELLED) for lang in ("en", "hi", "hinglish"))
