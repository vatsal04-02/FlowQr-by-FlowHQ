"""WhatsApp birthday and festival greetings (Phase 2 of the second round).

A greeting is the most sensitive thing the add-on sends, so these tests are about when it must NOT go out (fail closed), and that it can only ever go out through the one sender and gate.
Mock Meta only: no real number, account or message is involved.

The rule under test: occasion consent is always required. While the approved category of a greeting is marketing, or WhatsApp has not yet reported it, offers consent is required too, and anyone
who asked to stop offers is never greeted. STOP stops greetings but never visit or enquiry updates."""
import io
import json
import re
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.config import settings
from app.core.db import system_session
from app.models import Tenant
from app.services.whatsapp import automations, consent, occasions, rules, sender, templates
from tests import test_whatsapp as base
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_whatsapp import OWNER, add_contact, grant_addon, payload, post_wh, process, svc_db, wa  # noqa: F401 - fixtures
from tests.test_whatsapp_messaging import messages, ready_biz, send, wm  # noqa: F401 - fixtures

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(autouse=True)
def tidy_festivals():
    yield
    owner_exec("DELETE FROM whatsapp_festivals")  # the shared list starts empty and every test leaves it that way


def at(d: date, hour: int, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=IST).astimezone(timezone.utc)


TODAY = occasions.ist_today()


def prep(admin, wm, name, tier="whatsapp_growth", sync=True, fresh=False, include_offer=True):
    """A connected business with the standard messages and the two greetings submitted (the mock approves them). `sync` reads WhatsApp's status listing, which is what confirms each category."""
    biz = ready_biz(admin, name, tier=tier, install=False, wm=wm, fresh=fresh)
    r = biz.post("/whatsapp/setup/prepare-messages", json={"include_offer": include_offer})
    assert r.status_code == 200, r.text
    if sync:
        assert biz.post("/whatsapp/templates/sync").status_code == 200
    return biz


def person(biz, phone, *, occasion=True, marketing=False, utility=False, birth=None, name="Asha"):
    body = {"occasion": occasion, "marketing": marketing, "utility": utility, **OWNER}
    if birth:
        body["birth_day"], body["birth_month"] = birth
    return add_contact(biz, phone, name=name, **body)


def greet(biz, cid, key="occasion_birthday", now=None, idem=None):
    """One greeting straight through the single sender, the way a helper's run does it."""
    with svc_db(biz.tenant_id) as db:
        t = db.get(Tenant, uuid.UUID(biz.tenant_id))
        c = consent.get_contact(db, t.id, uuid.UUID(cid))
        row = templates.standard_row(db, t.id, key)
        vars_ = ["Asha", t.name] + (["Diwali"] if key == "occasion_festival" else [])
        res = sender.send_template(db, t, c, row, vars_, idem_key=idem or f"g:{uuid.uuid4()}", kind="occasion", now=now or at(TODAY, 11))
        db.commit()
        return res


def run(biz, now):
    """What the worker does at `now`: schedule today's greetings, then send what is due."""
    db = system_session()
    try:
        out = (occasions.schedule_due(db, now, uuid.UUID(biz.tenant_id)), automations.run_due(db, now=now, tenant_id=uuid.UUID(biz.tenant_id)))
        db.commit()
        return out
    finally:
        db.close()


def switch_on(biz, key="birthday", hour=10):
    r = biz.put(f"/whatsapp/automations/{key}", json={"status": "on", "config": {"send_hour": hour}})
    assert r.status_code == 200, r.text
    return r.json()


def runs(biz, key="birthday"):
    return biz.get(f"/whatsapp/automations/{key}/runs").json()


def sent_greetings(biz):
    return owner_query("SELECT count(*) FROM whatsapp_messages WHERE tenant_id = :t AND kind = 'occasion'", t=biz.tenant_id)[0][0]


def set_category(biz, category, confirmed):
    owner_exec("UPDATE whatsapp_templates SET category = :c, category_confirmed = :k WHERE tenant_id = :t AND template_name LIKE 'flowqr_occasion%'", c=category, k=confirmed, t=biz.tenant_id)


def stop(phone="919876540000"):
    raw = payload(messages=[{"from": phone, "id": f"wamid.S{uuid.uuid4().hex[:10]}", "type": "text", "text": {"body": "STOP"}}])
    assert post_wh(raw).status_code == 200
    process(base.event_id_for(raw))


def festival(admin, name="Testival Alpha", day=None, region="All India"):
    r = admin.post("/admin/whatsapp/festivals", json={"name": name, "festival_date": (day or TODAY).isoformat(), "region": region})
    assert r.status_code == 201, r.text
    return r.json()


# ===================================================================== the fail-closed consent rule
def test_a_greeting_always_needs_occasion_consent(wm, admin):
    biz = prep(admin, wm, "Needs Occasion")
    set_category(biz, "utility", True)  # even once WhatsApp confirms a greeting is utility, agreeing to offers or visit updates is not agreeing to greetings
    only_other = person(biz, "98765 40001", occasion=False, marketing=True, utility=True, birth=(TODAY.day, TODAY.month))
    r = greet(biz, only_other["id"])
    assert (r.status, r.reason) == ("skipped", "no_occasion_consent") and sent_greetings(biz) == 0 and wm.sent == []
    none = person(biz, "98765 40002", occasion=False)
    assert greet(biz, none["id"]).reason == "no_occasion_consent"


def test_while_the_category_is_marketing_or_not_yet_known_offers_consent_is_needed_too(wm, admin):
    biz = prep(admin, wm, "Marketing Rule", sync=False)  # submitted, approved, but WhatsApp's status listing has not reported the category
    occ_only = person(biz, "98765 40010")
    both = person(biz, "98765 40011", marketing=True)
    row = owner_query("SELECT category, category_confirmed FROM whatsapp_templates WHERE tenant_id = :t AND template_name = 'flowqr_occasion_birthday_en'", t=biz.tenant_id)[0]
    assert row == ("marketing", False)  # asked for as marketing, not yet confirmed: "not yet known"
    r = greet(biz, occ_only["id"])
    assert (r.status, r.reason) == ("skipped", "no_marketing_consent")  # unknown category: treated as marketing
    assert greet(biz, both["id"]).ok
    assert biz.post("/whatsapp/templates/sync").status_code == 200  # now WhatsApp reports it: marketing
    assert owner_query("SELECT category, category_confirmed FROM whatsapp_templates WHERE tenant_id = :t AND template_name = 'flowqr_occasion_birthday_en'", t=biz.tenant_id)[0] == ("marketing", True)
    assert greet(biz, occ_only["id"], now=at(TODAY, 12)).reason == "no_marketing_consent"  # confirmed marketing: still needs offers consent
    assert sent_greetings(biz) == 1


def test_an_offers_opt_out_blocks_a_greeting_whatever_its_category(wm, admin):
    biz = prep(admin, wm, "Opted Out Rule")
    c = person(biz, "98765 40020", marketing=True, utility=True)
    assert biz.post(f"/whatsapp/contacts/{c['id']}/opt-out", json={"purpose": "marketing"}).status_code == 200
    for category, confirmed in (("marketing", True), ("marketing", False), ("utility", True)):
        set_category(biz, category, confirmed)
        r = greet(biz, c["id"], idem=f"o:{category}:{confirmed}")
        assert (r.status, r.reason) == ("skipped", "opted_out"), (category, confirmed)
    assert sent_greetings(biz) == 0 and wm.sent == []


def test_once_whatsapp_confirms_a_greeting_is_utility_occasion_consent_alone_is_enough(wm, admin):
    """The relaxed rule exists in the gate but applies only after WhatsApp's own listing says so."""
    biz = prep(admin, wm, "Relaxed Rule")
    c = person(biz, "98765 40030")
    assert greet(biz, c["id"]).reason == "no_marketing_consent"  # today: marketing, fail closed
    set_category(biz, "utility", True)
    assert greet(biz, c["id"], now=at(TODAY, 12)).ok
    assert wm.sent[-1]["template"]["name"] == "flowqr_occasion_birthday_en"


def test_the_preview_shows_the_category_a_warning_and_who_would_really_get_it(wm, admin):
    biz = prep(admin, wm, "Preview Greeting", sync=False)
    person(biz, "98765 40040", marketing=True)
    person(biz, "98765 40041")
    p = biz.get("/whatsapp/occasions").json()
    b = p["birthday"]
    assert b["submitted"] is True and b["category"] is None and b["category_known"] is False and b["needs_offers_consent"] is True and "not yet confirmed" in b["warning"]
    assert b["audience"] == {"agreed": 2, "would_receive": 1, "with_birthday": 0, "left_out": 1}  # one agreed to greetings but not to offers: left out
    assert p["hours"] == {"start": 9, "end": 21, "timezone": "Asia/Kolkata"} and p["gap_days"] == 14 and p["allowed"] is True
    biz.post("/whatsapp/templates/sync")
    b2 = biz.get("/whatsapp/occasions").json()["birthday"]
    assert b2["category"] == "marketing" and b2["category_known"] is True and b2["needs_offers_consent"] is True and "AND to offers" in b2["warning"]
    set_category(biz, "utility", True)
    b3 = biz.get("/whatsapp/occasions").json()["birthday"]
    assert b3["category"] == "utility" and b3["needs_offers_consent"] is False and b3["warning"] is None and b3["audience"]["would_receive"] == 2


def test_a_greeting_template_that_was_never_submitted_is_shown_as_unknown_and_fail_closed(wm, admin):
    biz = ready_biz(admin, "Not Submitted", install=False)
    b = biz.get("/whatsapp/occasions").json()["birthday"]
    assert b["submitted"] is False and b["category_known"] is False and b["needs_offers_consent"] is True and b["warning"]


# ===================================================================== STOP
def test_stop_blocks_greetings_but_never_visit_or_enquiry_updates(wm, admin):
    biz = prep(admin, wm, "Stop Rule")
    c = person(biz, "98765 40000", marketing=True, utility=True, birth=(TODAY.day, TODAY.month))
    assert greet(biz, c["id"]).ok  # agreed to everything: the greeting goes
    stop("919876540000")
    got = biz.get("/whatsapp/contacts").json()["items"][0]
    assert got["opted_out"] is True and got["marketing"] is None and got["occasion"] is None and got["utility"] is not None  # greetings and offers stopped, visit updates kept
    r = greet(biz, c["id"], now=at(TODAY + timedelta(days=20), 11))
    assert (r.status, r.reason) == ("skipped", "opted_out")
    review = send(biz, c["id"], key="review_followup", variables=["Asha", "Stop Rule", "https://g.page/r/x/review"])
    ack = send(biz, c["id"], key="enquiry_ack", variables=["Asha", "Stop Rule"])
    assert review.ok and ack.ok  # visit and enquiry updates are not affected by STOP
    assert owner_query("SELECT revoked_source FROM whatsapp_consents WHERE contact_id = :c AND purpose = 'occasion'", c=c["id"])[0][0] == "customer_stop"


def test_after_stop_the_owner_cannot_give_a_greeting_consent_back(wm, admin):
    biz = prep(admin, wm, "No Owner Lift")
    c = person(biz, "98765 40000", marketing=True)
    stop("919876540000")
    r = biz.post(f"/whatsapp/contacts/{c['id']}/consent", json={"purpose": "occasion", **OWNER})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "opted_out"
    assert greet(biz, c["id"]).reason == "opted_out"


# ===================================================================== birthdays: once a year, 29 February
def test_a_birthday_greeting_is_scheduled_once_per_person_per_year(wm, admin):
    biz = prep(admin, wm, "Once A Year")
    switch_on(biz, "birthday", 10)
    c = person(biz, "98765 41001", marketing=True, birth=(TODAY.day, TODAY.month))
    person(biz, "98765 41002", marketing=True, birth=((TODAY + timedelta(days=3)).day, (TODAY + timedelta(days=3)).month))  # not today
    s, r = run(biz, at(TODAY, 10, 5))
    assert s["birthdays"] == 1 and r["sent"] == 1 and sent_greetings(biz) == 1
    for minute in (20, 40):  # the worker ticks again and again: still one
        s, r = run(biz, at(TODAY, 10, minute))
        assert s["birthdays"] == 0 and r.get("sent", 0) == 0
    assert sent_greetings(biz) == 1 and len([x for x in runs(biz) if x["status"] == "sent"]) == 1
    nxt = TODAY.replace(year=TODAY.year + 1) if not (TODAY.month == 2 and TODAY.day == 29) else date(TODAY.year + 1, 2, 28)
    s, r = run(biz, at(nxt, 10, 5))  # a year later: one more
    assert s["birthdays"] == 1 and r["sent"] == 1 and sent_greetings(biz) == 2
    assert c and wm.sent[-1]["template"]["name"] == "flowqr_occasion_birthday_en"


def test_a_29_february_birthday_is_greeted_on_28_february_in_years_without_a_29th(wm, admin):
    biz = prep(admin, wm, "Leap Day")
    switch_on(biz, "birthday", 10)
    person(biz, "98765 41010", marketing=True, birth=(29, 2))
    s, r = run(biz, at(date(2027, 2, 27), 10, 5))
    assert s["birthdays"] == 0  # not the day before
    s, r = run(biz, at(date(2027, 2, 28), 10, 5))
    assert s["birthdays"] == 1 and r["sent"] == 1  # 2027 has no 29 February: greeted on the 28th
    s, r = run(biz, at(date(2027, 3, 1), 10, 5))
    assert s["birthdays"] == 0 and sent_greetings(biz) == 1
    s, r = run(biz, at(date(2028, 2, 28), 10, 5))
    assert s["birthdays"] == 0  # 2028 is a leap year: not on the 28th
    s, r = run(biz, at(date(2028, 2, 29), 10, 5))
    assert s["birthdays"] == 1 and r["sent"] == 1 and sent_greetings(biz) == 2  # on the 29th itself


def test_a_28_february_birthday_is_not_greeted_twice_in_a_year(wm, admin):
    biz = prep(admin, wm, "Feb 28")
    switch_on(biz, "birthday", 10)
    person(biz, "98765 41011", marketing=True, birth=(28, 2))
    run(biz, at(date(2027, 2, 28), 10, 5))
    run(biz, at(date(2027, 2, 28), 11, 5))
    assert sent_greetings(biz) == 1


def test_only_customers_who_agreed_to_greetings_are_ever_scheduled(wm, admin):
    biz = prep(admin, wm, "Agreed Only")
    switch_on(biz, "birthday", 10)
    person(biz, "98765 41020", occasion=False, marketing=True, utility=True, birth=(TODAY.day, TODAY.month))  # gave a birthday, did not agree to greetings
    s, r = run(biz, at(TODAY, 10, 5))
    assert s["birthdays"] == 0 and sent_greetings(biz) == 0 and runs(biz) == []


# ===================================================================== the two caps
def test_greetings_have_their_own_14_day_cap(wm, admin):
    biz = prep(admin, wm, "Own Cap")
    c = person(biz, "98765 42001", marketing=True)
    assert greet(biz, c["id"], "occasion_birthday", at(TODAY, 11)).ok
    r = greet(biz, c["id"], "occasion_festival", at(TODAY, 12))
    assert (r.status, r.reason) == ("skipped", "greeting_too_soon")  # a second greeting inside 14 days
    assert greet(biz, c["id"], "occasion_festival", at(TODAY + timedelta(days=13), 12)).reason == "greeting_too_soon"
    assert greet(biz, c["id"], "occasion_festival", at(TODAY + timedelta(days=15), 12)).ok  # 15 days later
    assert settings.whatsapp_occasion_gap_days == 14 and sent_greetings(biz) == 2


def test_the_cap_is_per_person(wm, admin):
    biz = prep(admin, wm, "Cap Per Person")
    a, b = person(biz, "98765 42010", marketing=True), person(biz, "98765 42011", marketing=True)
    assert greet(biz, a["id"]).ok and greet(biz, b["id"]).ok


def test_greetings_are_excluded_from_the_72_hour_offer_gap_in_both_directions(wm, admin):
    biz = prep(admin, wm, "Gap Exempt")
    c = person(biz, "98765 42020", marketing=True, utility=True)
    assert greet(biz, c["id"]).ok
    offer = send(biz, c["id"], key="offer", variables=["Asha", "Gap Exempt", "10% off this week"])
    assert offer.ok  # an offer straight after a greeting is not "too soon"
    c2 = person(biz, "98765 42021", marketing=True, utility=True)
    assert send(biz, c2["id"], key="offer", variables=["Asha", "Gap Exempt", "10% off this week"]).ok
    assert greet(biz, c2["id"], now=at(TODAY, 12)).ok  # and a greeting straight after an offer is not blocked by the offer gap
    assert send(biz, c["id"], key="offer", variables=["Asha", "Gap Exempt", "20% off this week"]).reason == "too_soon"  # but a second offer still is


def test_a_greeting_is_never_used_to_dodge_the_offer_rules(wm, admin):
    """The 'occasion' kind skips the offer gap, so it may only be used with the two greeting messages."""
    biz = prep(admin, wm, "No Bypass")
    c = person(biz, "98765 42030", marketing=True, utility=True)
    for key, kind in (("offer", "occasion"), ("review_followup", "occasion"), ("occasion_birthday", "optin_confirm"), ("offer", "optin_confirm"), ("offer", "anything")):
        with svc_db(biz.tenant_id) as db:
            t = db.get(Tenant, uuid.UUID(biz.tenant_id))
            row = templates.standard_row(db, t.id, key)
            vars_ = ["Asha", "No Bypass", "x"] if key in ("offer", "review_followup") else ["Asha", "No Bypass"]
            res = sender.send_template(db, t, consent.get_contact(db, t.id, uuid.UUID(c["id"])), row, vars_, idem_key=f"b:{uuid.uuid4()}", kind=kind, now=at(TODAY, 11))
        assert (res.status, res.reason) == ("skipped", "kind_mismatch"), (key, kind)
    assert wm.sent == []


# ===================================================================== hours
def test_a_greeting_is_never_sent_outside_9_am_to_9_pm_india_time(wm, admin):
    biz = prep(admin, wm, "Hours Rule")
    cs = [person(biz, f"98765 4300{i}", marketing=True) for i in range(1, 6)]
    cases = [((8, 59), "outside_hours"), ((9, 0), None), ((20, 59), None), ((21, 0), "outside_hours"), ((23, 30), "outside_hours"), ((0, 15), "outside_hours")]
    for i, ((h, m), want) in enumerate(cases):
        c = cs[i % len(cs)] if want else person(biz, f"98765 4301{i}", marketing=True)
        r = greet(biz, c["id"], now=at(TODAY, h, m))
        assert (r.reason if want else "ok") == (want or "ok"), (h, m, r)
    assert rules.OCCASION_START == 9 and rules.OCCASION_END == 21


def test_a_greeting_goes_out_at_the_chosen_hour_and_not_before(wm, admin):
    biz = prep(admin, wm, "Chosen Hour")
    switch_on(biz, "birthday", 15)
    person(biz, "98765 43020", marketing=True, birth=(TODAY.day, TODAY.month))
    s, r = run(biz, at(TODAY, 8, 0))
    assert s["birthdays"] == 1 and r.get("sent", 0) == 0 and sent_greetings(biz) == 0  # scheduled for 3 pm India time, nothing yet
    run(biz, at(TODAY, 14, 59))
    assert sent_greetings(biz) == 0
    run(biz, at(TODAY, 15, 1))
    assert sent_greetings(biz) == 1


def test_the_chosen_hour_can_only_be_between_9_am_and_8_pm(wm, admin):
    biz = prep(admin, wm, "Hour Choices")
    for bad in (0, 8, 21, 22, 24, -1, True, "10"):
        r = biz.put("/whatsapp/automations/birthday", json={"status": "on", "config": {"send_hour": bad}})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_config", bad
    for good in (9, 20):
        assert biz.put("/whatsapp/automations/birthday", json={"status": "on", "config": {"send_hour": good}}).status_code == 200


def test_a_greeting_that_missed_its_hours_or_its_day_is_skipped_never_sent_late(wm, admin):
    biz = prep(admin, wm, "Missed Day")
    switch_on(biz, "birthday", 10)
    person(biz, "98765 44001", marketing=True, birth=(TODAY.day, TODAY.month))
    s, _ = run(biz, at(TODAY, 9, 30))
    assert s["birthdays"] == 1
    _, r = run(biz, at(TODAY, 21, 10))  # the worker was down all day and wakes after the hours close
    assert r["skipped"] == 1 and runs(biz)[0]["reason"] == "outside_hours" and sent_greetings(biz) == 0
    biz2 = prep(admin, wm, "Missed Day Two", fresh=True)
    switch_on(biz2, "birthday", 10)
    person(biz2, "98765 44002", marketing=True, birth=(TODAY.day, TODAY.month))
    run(biz2, at(TODAY, 9, 30))
    _, r = run(biz2, at(TODAY + timedelta(days=1), 10, 30))  # found the next morning
    assert runs(biz2)[0]["reason"] == "day_passed" and sent_greetings(biz2) == 0
    biz3 = prep(admin, wm, "Late Switch On", fresh=True)
    switch_on(biz3, "birthday", 10)
    person(biz3, "98765 44003", marketing=True, birth=(TODAY.day, TODAY.month))
    s, _ = run(biz3, at(TODAY, 21, 30))  # nothing is even scheduled once the hours are closed
    assert s["birthdays"] == 0 and runs(biz3) == []


# ===================================================================== the words of a greeting
def test_greeting_texts_contain_no_offer_or_discount():
    for key in ("occasion_birthday", "occasion_festival"):
        body = templates.STANDARD[key]["body"]
        words = set(re.findall(r"[a-z]+", body.lower()))
        assert not words & rules.OFFER_WORDS, (key, words & rules.OFFER_WORDS)
        assert not re.search(r"[0-9%₹$]", re.sub(r"\{\{\d+\}\}", "", body)) and templates.valid_body(body) and "STOP" in body
        assert templates.STANDARD[key]["category"] == "marketing"  # asked for honestly; WhatsApp decides


def test_a_festival_name_cannot_smuggle_in_an_offer(wm, admin):
    for bad in ("Diwali Sale", "Diwali 50% off", "Free Diwali", "Flat discount Holi", "Diwali!", "D", "Diwali" + "x" * 60, "Holi @ 20", "Eid gift", "Buy Eid"):
        r = admin.post("/admin/whatsapp/festivals", json={"name": bad, "festival_date": TODAY.isoformat()})
        assert r.status_code in (422,), bad
    assert admin.get("/admin/whatsapp/festivals").json()["items"] == []
    assert festival(admin, "Diwali")["name"] == "Diwali" and festival(admin, "Eid ul Fitr", TODAY + timedelta(days=1))["name"] == "Eid ul Fitr"
    assert rules.greeting_name_problem("Makar Sankranti") is None and rules.greeting_name_problem("Raksha Bandhan") is None


def test_the_greeting_that_reaches_the_customer_is_the_fixed_text_with_only_names_filled_in(wm, admin):
    biz = prep(admin, wm, "Words Check")
    c = person(biz, "98765 45001", marketing=True, name="Meera Shah")
    assert greet(biz, c["id"]).ok
    sent = wm.sent[-1]
    assert sent["type"] == "template" and "text" not in sent and "body" not in sent  # never free text
    assert [p["text"] for p in sent["template"]["components"][0]["parameters"]] == ["Asha", "Words Check"]
    assert wm.templates["flowqr_occasion_birthday_en"]["components"][0]["text"] == templates.STANDARD["occasion_birthday"]["body"]


# ===================================================================== plan, helper count, emergency stop
def test_greetings_are_for_growth_and_pro_only(wm, admin):
    starter = prep(admin, wm, "Starter Greets", tier="whatsapp_starter")
    prep_msgs = starter.post("/whatsapp/setup/prepare-messages", json={}).json()
    assert "occasion_birthday" not in prep_msgs["submitted"] + prep_msgs["already_there"]  # not submitted for a plan that cannot use them
    r = starter.put("/whatsapp/automations/birthday", json={"status": "on"})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_required"
    assert starter.put("/whatsapp/automations/festival", json={"status": "on"}).json()["detail"]["code"] == "plan_required"
    assert starter.get("/whatsapp/occasions").json()["allowed"] is False
    for tier in ("whatsapp_growth", "whatsapp_pro"):
        biz = prep(admin, wm, f"Greets {tier}", tier=tier, fresh=True)
        assert switch_on(biz, "birthday")["status"] == "on" and biz.get("/whatsapp/occasions").json()["allowed"] is True


def test_a_plan_downgrade_stops_greetings_at_the_gate(wm, admin):
    biz = prep(admin, wm, "Downgraded")
    switch_on(biz, "birthday", 10)
    c = person(biz, "98765 46001", marketing=True, birth=(TODAY.day, TODAY.month))
    r = admin.put(f"/admin/tenants/{biz.tenant_id}/whatsapp-addon", json={"addon_key": "whatsapp_starter", "reason": "Plan changed to Starter by the owner"})
    assert r.status_code == 200
    s, r = run(biz, at(TODAY, 10, 5))
    assert s["birthdays"] == 0 and sent_greetings(biz) == 0
    assert greet(biz, c["id"]).reason == "plan_required"


def test_each_greeting_helper_counts_against_the_plans_helper_limit(wm, admin, monkeypatch):
    monkeypatch.setitem(rules.ADDON_TIERS["whatsapp_growth"], "automation_limit", 2)
    biz = prep(admin, wm, "Helper Count")
    assert biz.put("/whatsapp/automations/review_followup", json={"status": "on"}).status_code == 200
    assert switch_on(biz, "birthday")["status"] == "on"
    r = biz.put("/whatsapp/automations/festival", json={"status": "on"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "automation_limit"
    assert biz.put("/whatsapp/automations/birthday", json={"status": "off"}).status_code == 200
    assert biz.put("/whatsapp/automations/festival", json={"status": "on"}).status_code == 200


def test_the_emergency_stop_and_the_sending_switch_stop_greetings(wm, admin, monkeypatch):
    biz = prep(admin, wm, "Switches")
    switch_on(biz, "birthday", 10)
    c = person(biz, "98765 47001", marketing=True, birth=(TODAY.day, TODAY.month))
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", True)
    s, r = run(biz, at(TODAY, 10, 5))
    assert s.get("held") is True and r.get("held") is True and sent_greetings(biz) == 0 and runs(biz) == []
    assert greet(biz, c["id"]).reason == "emergency_stop"
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", False)
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", False)
    assert greet(biz, c["id"]).reason == "sending_disabled" and run(biz, at(TODAY, 10, 6))[0].get("held") is True
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", True)
    monkeypatch.setattr(settings, "whatsapp_enabled", False)
    assert greet(biz, c["id"]).reason == "whatsapp_disabled"
    monkeypatch.setattr(settings, "whatsapp_enabled", True)
    s, r = run(biz, at(TODAY, 10, 7))
    assert s["birthdays"] == 1 and r["sent"] == 1  # back on: it goes out


def test_the_greeting_needs_its_own_approved_message(wm, admin):
    biz = prep(admin, wm, "Approval")
    c = person(biz, "98765 48001", marketing=True)
    owner_exec("UPDATE whatsapp_templates SET approval_status = 'pending' WHERE tenant_id = :t AND template_name = 'flowqr_occasion_birthday_en'", t=biz.tenant_id)
    assert greet(biz, c["id"]).reason == "template_not_approved"
    owner_exec("UPDATE whatsapp_templates SET approval_status = 'approved' WHERE tenant_id = :t", t=biz.tenant_id)
    assert greet(biz, c["id"], now=at(TODAY, 12)).ok


def test_the_set_up_checklist_still_counts_only_the_three_core_messages(wm, admin):
    biz = prep(admin, wm, "Checklist Three")
    assert automations.NEEDS["review_followup"] == ("review_followup",) and len(__import__("app.services.whatsapp.setup", fromlist=["x"]).UTILITY_KEYS) == 3
    owner_exec("UPDATE whatsapp_templates SET approval_status = 'pending' WHERE tenant_id = :t AND template_name LIKE 'flowqr_occasion%'", t=biz.tenant_id)
    step = next(s for s in biz.get("/whatsapp/setup").json()["steps"] if s["key"] == "messages")
    assert step["state"] == "done"  # pending greetings do not hold up the checklist


# ===================================================================== birth day and month: manual add, upload, export, delete
def test_a_birthday_typed_in_by_hand_needs_the_they_agreed_confirmation(wm, admin):
    biz = prep(admin, wm, "By Hand")
    r = biz.post("/whatsapp/contacts", json={"phone": "98765 49001", "name": "Asha", "birth_day": 14, "birth_month": 3})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "attestation_required"
    assert biz.post("/whatsapp/contacts", json={"phone": "98765 49001", "birth_day": 14, "birth_month": 3, "attested": True}).json()["detail"]["code"] == "evidence_required"
    ok = biz.post("/whatsapp/contacts", json={"phone": "98765 49001", "name": "Asha", "birth_day": 14, "birth_month": 3, **OWNER})
    assert ok.status_code == 201 and (ok.json()["birth_day"], ok.json()["birth_month"]) == (14, 3) and ok.json()["occasion"] is None  # a birthday is not consent to greetings
    again = biz.patch(f"/whatsapp/contacts/{ok.json()['id']}", json={"birth_day": 15, "birth_month": 3})
    assert again.status_code == 422 and again.json()["detail"]["code"] == "attestation_required"
    assert biz.patch(f"/whatsapp/contacts/{ok.json()['id']}", json={"birth_day": 15, "birth_month": 3, **OWNER}).json()["birth_day"] == 15
    cleared = biz.patch(f"/whatsapp/contacts/{ok.json()['id']}", json={"birth_day": None, "birth_month": None}).json()
    assert cleared["birth_day"] is None and cleared["birth_month"] is None  # taking a birthday away needs no confirmation


def test_an_impossible_or_half_a_birthday_is_refused(wm, admin):
    biz = prep(admin, wm, "Bad Dates")
    for d, m in ((31, 4), (30, 2), (31, 6), (31, 11), (32, 1), (0, 5), (5, 13)):
        r = biz.post("/whatsapp/contacts", json={"phone": f"98765 4902{d % 10}", "birth_day": d, "birth_month": m, **OWNER})
        assert r.status_code == 422, (d, m)
    half = biz.post("/whatsapp/contacts", json={"phone": "98765 49030", "birth_day": 5, **OWNER})
    assert half.status_code == 422 and half.json()["detail"]["code"] == "invalid_birthday"
    leap = biz.post("/whatsapp/contacts", json={"phone": "98765 49031", "birth_day": 29, "birth_month": 2, **OWNER})
    assert leap.status_code == 201  # 29 February is a real birthday
    for d, m in ((30, 2), (31, 4)):  # and the database refuses what the API would
        with pytest.raises(Exception):
            owner_exec("UPDATE whatsapp_contacts SET birth_day = :d, birth_month = :m WHERE id = :i", d=d, m=m, i=leap.json()["id"])
    with pytest.raises(Exception):
        owner_exec("UPDATE whatsapp_contacts SET birth_day = 5, birth_month = NULL WHERE id = :i", i=leap.json()["id"])


def test_occasion_consent_is_its_own_agreement_recorded_with_its_wording(wm, admin):
    biz = prep(admin, wm, "Own Consent")
    c = person(biz, "98765 49040")
    row = owner_query("SELECT purpose, source, wording_text, wording_version FROM whatsapp_consents WHERE contact_id = :c", c=c["id"])
    assert len(row) == 1 and row[0][0] == "occasion" and row[0][1] == "owner_entry" and "birthday and festival greetings" in row[0][2] and "Own Consent" in row[0][2] and "STOP" in row[0][2]
    unattested = biz.post("/whatsapp/contacts", json={"phone": "98765 49041", "occasion": True})
    assert unattested.status_code == 422 and unattested.json()["detail"]["code"] == "attestation_required"


def test_a_csv_upload_can_carry_birth_day_and_month_and_never_a_year(wm, admin):
    biz = prep(admin, wm, "Upload Birthdays")
    text = ("phone,name,birth_day,birth_month\n98765 50001,Asha,14,3\n98765 50002,Ravi,29,2\n98765 50003,Meena,31,4\n98765 50004,Kiran,,\n")
    r = biz.post("/whatsapp/contacts/import", json={"csv": text, "purposes": ["occasion", "marketing"], **OWNER})
    assert r.status_code == 200 and r.json()["added"] == 4 and r.json()["birthdays_set"] == 2 and r.json()["consents_recorded"] == 8
    by = {c["customer_name"]: c for c in biz.get("/whatsapp/contacts").json()["items"]}
    assert (by["Asha"]["birth_day"], by["Asha"]["birth_month"]) == (14, 3) and (by["Ravi"]["birth_day"], by["Ravi"]["birth_month"]) == (29, 2)
    assert by["Meena"]["birth_day"] is None and by["Kiran"]["birth_day"] is None and by["Asha"]["occasion"]["source"] == "csv_import"
    assert any("14-03" in e["reason"] or "birthday" in e["reason"] for e in r.json()["errors"])  # 31 April was refused with a reason
    combined = "phone,name,birthday\n98765 50011,One,14-03\n98765 50012,Two,05/11\n98765 50013,Three,14-03-1990\n98765 50014,Four,March 14\n"
    r2 = biz.post("/whatsapp/contacts/import", json={"csv": combined, "purposes": ["occasion"], **OWNER})
    assert r2.json()["birthdays_set"] == 2 and r2.json()["added"] == 4  # a value with a year is refused, not trimmed
    got = {c["customer_name"]: c for c in biz.get("/whatsapp/contacts").json()["items"]}
    assert (got["Two"]["birth_day"], got["Two"]["birth_month"]) == (5, 11) and got["Three"]["birth_day"] is None and got["Four"]["birth_day"] is None


def test_an_upload_still_needs_the_they_agreed_confirmation_even_for_birthdays(wm, admin):
    biz = prep(admin, wm, "Upload Attest")
    text = "phone,birth_day,birth_month\n98765 50021,14,3\n"
    r = biz.post("/whatsapp/contacts/import", json={"csv": text, "purposes": ["occasion"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "attestation_required"
    assert biz.get("/whatsapp/contacts").json()["total"] == 0


def test_the_export_carries_birth_day_month_and_the_greeting_consent_and_deletion_removes_them(wm, admin):
    biz = prep(admin, wm, "Export Birthdays")
    a = person(biz, "98765 51001", marketing=True, birth=(14, 3), name="Asha")
    person(biz, "98765 51002", occasion=False, utility=True, name="Ravi")
    lines = biz.get("/whatsapp/contacts/export").text.splitlines()
    assert lines[0].startswith("phone,name,tags,marketing_consent_since,marketing_consent_source,utility_consent_since,utility_consent_source,opted_out_of_marketing,source,added")
    assert "occasion_consent_since,occasion_consent_source,birth_day,birth_month" in lines[0]
    hdr = lines[0].split(",")
    asha = dict(zip(hdr, next(ln for ln in lines if "Asha" in ln).split(",")))
    assert asha["occasion_consent_since"] != "" and asha["occasion_consent_source"] == "owner_entry" and (asha["birth_day"], asha["birth_month"]) == ("14", "3")
    ravi = dict(zip(hdr, next(ln for ln in lines if "Ravi" in ln).split(",")))
    assert [ravi[k] for k in ("occasion_consent_since", "occasion_consent_source", "birth_day", "birth_month")] == ["", "", "", ""]
    assert biz.delete(f"/whatsapp/contacts/{a['id']}").status_code == 204
    assert owner_query("SELECT count(*) FROM whatsapp_contacts WHERE id = :i", i=a["id"])[0][0] == 0
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE contact_id = :i", i=a["id"])[0][0] == 0
    assert "Asha" not in biz.get("/whatsapp/contacts/export").text


def test_the_birthday_itself_is_never_written_to_the_audit_log(wm, admin):
    biz = prep(admin, wm, "Audit Birthdays")
    person(biz, "98765 51010", birth=(14, 3))
    rows = owner_query("SELECT action, metadata FROM audit_logs WHERE tenant_id = :t AND action LIKE 'whatsapp.birthday%'", t=biz.tenant_id)
    assert [r[0] for r in rows] == ["whatsapp.birthday_set"]  # recorded that it happened, with no date
    assert not rows[0][1] and "14" not in json.dumps(rows[0][1], default=str)
    everything = json.dumps([r[0] for r in owner_query("SELECT metadata FROM audit_logs WHERE tenant_id = :t", t=biz.tenant_id)], default=str)
    assert "birth_day" not in everything and "birth_month" not in everything


def test_account_export_and_deletion_cover_greeting_data(wm, admin):
    biz = prep(admin, wm, "Account Greetings")
    person(biz, "98765 51020", marketing=True, birth=(14, 3))
    f = festival(admin, "Testival Beta")
    assert biz.put(f"/whatsapp/occasions/festivals/{f['id']}", json={"enabled": True}).status_code == 200
    z = zipfile.ZipFile(io.BytesIO(biz.get("/account/export").content))
    assert "whatsapp_festival_optins.json" in z.namelist() and any(c["purpose"] == "occasion" for c in json.loads(z.read("whatsapp_consents.json")))
    assert any(c.get("birth_day") == 14 for c in json.loads(z.read("whatsapp_contacts.json")))
    db = system_session()
    try:
        from sqlalchemy import text
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": biz.tenant_id})
        db.commit()
    finally:
        db.close()
    for t in ("whatsapp_festival_optins", "whatsapp_consents", "whatsapp_contacts"):
        assert owner_query(f"SELECT count(*) FROM {t} WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0, t
    assert owner_query("SELECT count(*) FROM whatsapp_festivals WHERE id = :i", i=f["id"])[0][0] == 1  # the shared list is not the business's data


# ===================================================================== festivals
def test_only_a_platform_administrator_keeps_the_festival_list(wm, admin):
    biz = make_business("Festival Peeker")
    f = festival(admin, "Testival Gamma")
    assert biz.get("/admin/whatsapp/festivals").status_code == 403
    assert biz.post("/admin/whatsapp/festivals", json={"name": "Holi", "festival_date": TODAY.isoformat()}).status_code == 403
    assert biz.patch(f"/admin/whatsapp/festivals/{f['id']}", json={"active": False}).status_code == 403
    dup = admin.post("/admin/whatsapp/festivals", json={"name": "Testival Gamma", "festival_date": TODAY.isoformat(), "region": "All India"})
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "festival_exists"
    assert admin.post("/admin/whatsapp/festivals", json={"name": "Holi", "festival_date": TODAY.isoformat(), "region": "Gujarat 5"}).status_code == 422
    assert admin.patch(f"/admin/whatsapp/festivals/{f['id']}", json={"active": False}).json()["active"] is False
    assert admin.get("/admin/whatsapp/festivals").json()["items"][0]["active"] is False  # switched off, never deleted


def test_a_festival_greeting_needs_the_business_to_opt_in_and_goes_only_to_agreed_customers(wm, admin):
    biz = prep(admin, wm, "Festival Optin")
    switch_on(biz, "festival", 11)
    agreed = person(biz, "98765 52001", marketing=True, name="Asha")
    person(biz, "98765 52002", occasion=False, marketing=True, utility=True, name="Ravi")
    f = festival(admin, "Testival Delta", TODAY)
    s, r = run(biz, at(TODAY, 11, 5))
    assert s["festivals"] == 0 and sent_greetings(biz) == 0  # the business has not chosen this festival
    assert biz.put(f"/whatsapp/occasions/festivals/{f['id']}", json={"enabled": True}).status_code == 200
    s, r = run(biz, at(TODAY, 11, 10))
    assert s["festivals"] == 1 and r["sent"] == 1 and sent_greetings(biz) == 1  # only the customer who agreed
    sent = wm.sent[-1]["template"]
    assert sent["name"] == "flowqr_occasion_festival_en" and [p["text"] for p in sent["components"][0]["parameters"]] == ["Asha", "Festival Optin", "Testival Delta"]
    s, r = run(biz, at(TODAY, 11, 20))
    assert s["festivals"] == 0 and sent_greetings(biz) == 1  # not twice
    assert agreed


def test_a_festival_on_another_day_or_switched_off_or_unchosen_sends_nothing(wm, admin):
    biz = prep(admin, wm, "Festival Days")
    switch_on(biz, "festival", 11)
    person(biz, "98765 52010", marketing=True)
    later = festival(admin, "Testival Epsilon", TODAY + timedelta(days=1))
    off = festival(admin, "Testival Zeta", TODAY)
    for f in (later, off):
        assert biz.put(f"/whatsapp/occasions/festivals/{f['id']}", json={"enabled": True}).status_code == 200
    admin.patch(f"/admin/whatsapp/festivals/{off['id']}", json={"active": False})
    s, _ = run(biz, at(TODAY, 11, 5))
    assert s["festivals"] == 0 and sent_greetings(biz) == 0
    s, _ = run(biz, at(TODAY + timedelta(days=1), 11, 5))
    assert s["festivals"] == 1  # the day it is


def test_the_business_sees_upcoming_festivals_and_its_own_choices_only(wm, admin):
    a = prep(admin, wm, "Festival View A")
    b = prep(admin, wm, "Festival View B", fresh=True)
    f = festival(admin, "Testival Eta", TODAY + timedelta(days=5))
    festival(admin, "Testival Theta", TODAY - timedelta(days=5))  # already past: not listed
    a.put(f"/whatsapp/occasions/festivals/{f['id']}", json={"enabled": True})
    la, lb = a.get("/whatsapp/occasions").json()["festivals"], b.get("/whatsapp/occasions").json()["festivals"]
    assert [x["name"] for x in la] == ["Testival Eta"] and la[0]["enabled"] is True and lb[0]["enabled"] is False and la[0]["region"] == "All India"
    assert b.put(f"/whatsapp/occasions/festivals/{uuid.uuid4()}", json={"enabled": True}).status_code == 404
    from sqlalchemy import text

    from app.core.db import SessionLocal, set_rls_context
    assert owner_query("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'whatsapp_festival_optins'")[0][0] is True
    with SessionLocal() as db:
        set_rls_context(db, tenant_id=uuid.UUID(b.tenant_id))
        assert db.execute(text("SELECT count(*) FROM whatsapp_festival_optins WHERE tenant_id = :t"), {"t": a.tenant_id}).scalar() == 0


def test_birthday_and_festival_on_the_same_day_send_one_greeting_because_of_the_cap(wm, admin):
    biz = prep(admin, wm, "Same Day")
    switch_on(biz, "birthday", 10)
    switch_on(biz, "festival", 10)
    person(biz, "98765 52020", marketing=True, birth=(TODAY.day, TODAY.month))
    f = festival(admin, "Testival Iota", TODAY)
    biz.put(f"/whatsapp/occasions/festivals/{f['id']}", json={"enabled": True})
    s, r = run(biz, at(TODAY, 10, 5))
    assert s["birthdays"] == 1 and s["festivals"] == 1 and sent_greetings(biz) == 1  # the second hits the 14-day cap
    reasons = [x["reason"] for k in ("birthday", "festival") for x in runs(biz, k) if x["status"] == "skipped"]
    assert reasons == ["greeting_too_soon"]


# ===================================================================== catalogue, access, shape
def test_the_helpers_appear_in_the_catalogue_with_plain_words(wm, admin):
    biz = prep(admin, wm, "Catalogue Greets")
    items = {i["key"]: i for i in biz.get("/whatsapp/automations").json()["items"]}
    assert items["birthday"]["available"] is True and items["festival"]["available"] is True and items["birthday"]["purpose"] == "occasion"
    assert items["birthday"]["state"]["config"] == {"send_hour": 10} and items["birthday"]["ready"]["customers"] is False
    person(biz, "98765 53001")
    assert {i["key"]: i for i in biz.get("/whatsapp/automations").json()["items"]}["birthday"]["ready"]["customers"] is True
    blob = json.dumps(items["birthday"]).lower() + json.dumps(items["festival"]).lower()
    assert "never contains an offer" in blob and "9 am and 9 pm" in blob


def test_greeting_routes_are_off_while_whatsapp_is_off_and_in_the_manifest():
    biz = make_business("Greetings Off")
    assert biz.get("/whatsapp/occasions").status_code == 404 and biz.get("/whatsapp/occasions").json()["detail"]["code"] == "whatsapp_disabled"
    lines = {(m, p): k for k, m, p in (ln.split("\t") for ln in open("tests/route_access_manifest.txt", encoding="utf-8").read().splitlines() if "occasions" in ln or "whatsapp/festivals" in ln)}
    assert lines == {("GET", "/api/v1/whatsapp/occasions"): "member", ("PUT", "/api/v1/whatsapp/occasions/festivals/{festival_id}"): "role-admin", ("GET", "/api/v1/admin/whatsapp/festivals"): "platform-admin",
                     ("POST", "/api/v1/admin/whatsapp/festivals"): "platform-admin", ("PATCH", "/api/v1/admin/whatsapp/festivals/{festival_id}"): "platform-admin"}


def test_the_migration_added_the_occasion_pieces(wm):
    assert "occasion" in owner_query("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_wa_consent_purpose'")[0][0]
    assert "birthday" in owner_query("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_wa_auto_key'")[0][0]
    cols = {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = 'whatsapp_contacts'")}
    assert {"birth_day", "birth_month"} <= cols
    assert not {"birth_year", "birthday", "birth_date"} & cols  # never a year
    role = settings.database_url.split("//")[1].split(":")[0]
    assert owner_query("SELECT has_table_privilege(:r, 'public.whatsapp_festivals', 'DELETE')", r=role)[0][0] is False  # a festival is switched off, never deleted
    assert owner_query("SELECT has_table_privilege(:r, 'public.whatsapp_festivals', 'INSERT')", r=role)[0][0] is True


# ===================================================================== the owner sees the likely cost before switching a greeting helper on
def test_the_owner_sees_the_estimated_cost_labelled_and_unverified_before_switching_a_greeting_on(wm, admin):
    biz = prep(admin, wm, "Greeting Cost", sync=False)
    person(biz, "98765 54001", marketing=True)
    person(biz, "98765 54002", marketing=True)
    for key in ("birthday", "festival"):
        e = biz.get("/whatsapp/occasions").json()[key]["estimate"]
        assert e["category_used"] == "marketing"  # not yet known: the marketing price
        one, everyone = e["per_greeting"], e["for_everyone_who_would_get_it"]
        assert one["rate"] == "1.0900" and one["amount"] == "1.09" and one["verified"] is False and one["effective_from"] == "2026-10-01" and one["warning"]
        assert "not a bill" in one["note"].lower() and "estimate" in one["note"].lower() and "FlowQR's fee is separate" in one["note"]
        assert everyone["count"] == 2 and everyone["amount"] == "2.18"
    set_category(biz, "utility", True)  # only once WhatsApp says it is a utility message does the utility price apply
    assert biz.get("/whatsapp/occasions").json()["birthday"]["estimate"]["per_greeting"]["rate"] == "0.1450"
    set_category(biz, "marketing", True)
    admin.post("/admin/whatsapp/rates/" + next(i for i in admin.get("/admin/whatsapp/rates").json()["items"] if i["category"] == "marketing" and i["in_force"])["id"] + "/verification",
               json={"verified": True, "note": "Matches Meta's India marketing rate, checked today"})
    try:
        e = biz.get("/whatsapp/occasions").json()["birthday"]["estimate"]["per_greeting"]
        assert e["verified"] is True and e["warning"] is None  # the warning goes away once the price in use is checked
    finally:
        owner_exec("DELETE FROM whatsapp_rate_verifications")
