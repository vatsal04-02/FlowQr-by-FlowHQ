"""WhatsApp engagement audiences and win-back (Phase 4 of the second round, Pro only).

The choices are: read, replied, clicked, delivered but not read, no engagement in the last N offers, and not visited or messaged in N days. They only choose WHO an ordinary marketing offer is for. The offer
itself is unchanged: offers consent, the 72-hour gap, STOP, sending hours, plan limits, the emergency stop and the approval tied to the preview count all still apply, and the single send gate re-checks
every recipient at the moment of sending. Only timestamps are kept; no message text is stored. Mock Meta only."""
import io
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.core.config import settings
from app.core.db import system_session
from app.models import Tenant
from app.models.base import utcnow
from app.services.whatsapp import automations, campaigns, consent, sender, templates
from tests import test_whatsapp as base
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_whatsapp import OWNER, add_contact, payload, post_wh, process, svc_db, wa  # noqa: F401 - fixtures
from tests.test_whatsapp_messaging import approve, draft, offer_id, ready_biz, send, tick, wm  # noqa: F401 - fixtures

IST = ZoneInfo("Asia/Kolkata")
_n = iter(range(10_000, 99_999))


def pro(admin, wm, name, fresh=False, tier="whatsapp_pro"):
    biz = ready_biz(admin, name, tier=tier, wm=wm, fresh=fresh)
    biz.camp = draft(biz)["id"]  # a real campaign for the offer messages we plant
    return biz


def person(biz, name="Cust", *, old=True, marketing=True, utility=False, days_old=200):
    c = add_contact(biz, f"98{next(_n):08d}", name=name, marketing=marketing, utility=utility, **OWNER)
    if old:
        owner_exec("UPDATE whatsapp_contacts SET created_at = :t WHERE id = :i", t=utcnow() - timedelta(days=days_old), i=c["id"])
    return c


def offer_msg(biz, cid, days_ago, *, status="delivered", read=False):
    """An offer that went out `days_ago` days ago (a real send, then moved back in time so the 72-hour gap does not get in the way)."""
    r = send(biz, cid, key="offer", variables=["Asha", "Engagement Biz", "10% off this week"], idem=f"o:{uuid.uuid4()}")
    assert r.ok, (r.status, r.reason)
    t = utcnow() - timedelta(days=days_ago)
    owner_exec("UPDATE whatsapp_messages SET created_at = :t, sent_at = :t, delivery_status = :s, delivered_at = :d, read_at = :r, campaign_id = :c WHERE id = :i",
               t=t, s=status, d=t if status in ("delivered", "read") else None, r=t if read else None, c=biz.camp, i=str(r.message_id))
    return r.message_id


def update_msg(biz, cid, days_ago, key="review_followup"):
    r = send(biz, cid, key=key, idem=f"u:{uuid.uuid4()}")
    assert r.ok, (r.status, r.reason)
    owner_exec("UPDATE whatsapp_messages SET created_at = :t WHERE id = :i", t=utcnow() - timedelta(days=days_ago), i=str(r.message_id))
    return r.message_id


def replied(cid, days_ago):
    owner_exec("UPDATE whatsapp_contacts SET last_replied_at = :t WHERE id = :i", t=utcnow() - timedelta(days=days_ago), i=cid)


def clicked(biz, cid, days_ago):
    lid = str(uuid.uuid4())
    owner_exec("INSERT INTO whatsapp_links (id, tenant_id, token, destination, contact_id) VALUES (:i, :t, :k, 'https://g.page/r/x/review', :c)", i=lid, t=biz.tenant_id, k=uuid.uuid4().hex + uuid.uuid4().hex, c=cid)
    owner_exec("INSERT INTO whatsapp_link_clicks (id, tenant_id, link_id, contact_id, clicked_at) VALUES (:i, :t, :l, :c, :a)", i=str(uuid.uuid4()), t=biz.tenant_id, l=lid, c=cid, a=utcnow() - timedelta(days=days_ago))


def prev(biz, aud):
    c = draft(biz, name=f"Aud {uuid.uuid4().hex[:6]}", audience=aud)
    return biz.get(f"/whatsapp/campaigns/{c['id']}").json(), c


def count(biz, aud):
    return prev(biz, aud)[0]["recipients"]


def names(biz, aud):
    """Who an audience picks out, by name (the exact list that sending would use)."""
    with svc_db(biz.tenant_id) as db:
        q = campaigns.audience_query(uuid.UUID(biz.tenant_id), campaigns.clean_audience(aud, "advanced")).with_only_columns(campaigns.WhatsAppContact.customer_name)
        return sorted(db.scalars(q))


# ===================================================================== Pro only, and what is accepted
def test_engagement_and_winback_choices_are_pro_only(wm, admin):
    grow = ready_biz(admin, "Growth Eng", tier="whatsapp_growth", wm=wm, fresh=True)
    for aud in ({"kind": "all", "engaged": "read"}, {"kind": "all", "no_engagement_last_offers": 3}, {"kind": "all", "winback_days": 60}, {"kind": "all", "engaged": "clicked", "engaged_days": 30}):
        r = grow.post("/whatsapp/campaigns", json={"name": "Try", "template_id": str(offer_id(grow)), "audience": aud, "variables": {"offer_text": "10% off this week"}})
        assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_required", aud
    plain = draft(grow)
    r = grow.patch(f"/whatsapp/campaigns/{plain['id']}", json={"audience": {"kind": "all", "winback_days": 60}})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_required"
    p = pro(admin, wm, "Pro Eng", fresh=True)
    for aud in ({"kind": "all", "engaged": "read"}, {"kind": "all", "no_engagement_last_offers": 3}, {"kind": "all", "winback_days": 60}):
        assert prev(p, aud)[1]["status"] == "draft"


def test_the_choices_are_checked(wm, admin):
    biz = pro(admin, wm, "Checks Eng")
    bad = [{"engaged": "ignored"}, {"engaged": "read", "engaged_days": 0}, {"engaged": "read", "engaged_days": 366}, {"engaged": "read", "engaged_days": True}, {"engaged": "read", "engaged_days": "30"},
           {"no_engagement_last_offers": 0}, {"no_engagement_last_offers": 11}, {"no_engagement_last_offers": True}, {"winback_days": 0}, {"winback_days": 366}, {"winback_days": "30"}, {"winback_days": True}]
    for extra in bad:
        r = biz.post("/whatsapp/campaigns", json={"name": "Bad", "template_id": str(offer_id(biz)), "audience": {"kind": "all", **extra}, "variables": {"offer_text": "10% off this week"}})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_audience", extra
    ok = prev(biz, {"kind": "all", "engaged": "read"})[1]
    assert biz.get(f"/whatsapp/campaigns/{ok['id']}").json()["audience"] == {"kind": "all", "engaged": "read", "engaged_days": 30}  # the days default to 30
    lone = prev(biz, {"kind": "all", "engaged_days": 10})[1]
    assert biz.get(f"/whatsapp/campaigns/{lone['id']}").json()["audience"] == {"kind": "all"}  # days with no choice are dropped


# ===================================================================== each filter
def test_read_picks_customers_who_read_a_message_in_the_period(wm, admin):
    biz = pro(admin, wm, "Read Eng")
    a, b, c, d = (person(biz, n) for n in ("Read10", "Read40", "Unread", "Quiet"))
    offer_msg(biz, a["id"], 10, read=True)
    offer_msg(biz, b["id"], 40, read=True)
    offer_msg(biz, c["id"], 10)
    assert names(biz, {"kind": "all", "engaged": "read", "engaged_days": 30}) == ["Read10"]
    assert names(biz, {"kind": "all", "engaged": "read", "engaged_days": 60}) == ["Read10", "Read40"]
    assert names(biz, {"kind": "all", "engaged": "read"}) == ["Read10"] and d


def test_replied_picks_customers_who_wrote_in_the_period(wm, admin):
    biz = pro(admin, wm, "Replied Eng")
    a, b, _ = person(biz, "Wrote5"), person(biz, "Wrote50"), person(biz, "Silent")
    replied(a["id"], 5)
    replied(b["id"], 50)
    assert names(biz, {"kind": "all", "engaged": "replied", "engaged_days": 30}) == ["Wrote5"]
    assert names(biz, {"kind": "all", "engaged": "replied", "engaged_days": 90}) == ["Wrote5", "Wrote50"]


def test_clicked_picks_customers_who_opened_a_tracked_link_in_the_period(wm, admin):
    biz = pro(admin, wm, "Clicked Eng")
    a, b, _ = person(biz, "Click3"), person(biz, "Click45"), person(biz, "NoClick")
    clicked(biz, a["id"], 3)
    clicked(biz, b["id"], 45)
    assert names(biz, {"kind": "all", "engaged": "clicked", "engaged_days": 30}) == ["Click3"]
    assert names(biz, {"kind": "all", "engaged": "clicked", "engaged_days": 60}) == ["Click3", "Click45"]
    notes = prev(biz, {"kind": "all", "engaged": "clicked"})[0]["audience_notes"]
    assert any("only have data from the time link click counting was switched on" in n["text"] for n in notes)  # the limit is shown beside the count


def test_delivered_but_not_read_is_never_called_ignored_and_says_read_receipts_may_be_off(wm, admin):
    biz = pro(admin, wm, "DNR Eng")
    a, b, c, d = (person(biz, n) for n in ("DeliveredOnly", "DeliveredThenRead", "SentOnly", "OldDelivered"))
    offer_msg(biz, a["id"], 5)
    offer_msg(biz, b["id"], 5)
    offer_msg(biz, b["id"], 20, read=True)  # read one of them in the period: not "delivered but not read"
    offer_msg(biz, c["id"], 5, status="sent")
    offer_msg(biz, d["id"], 50)
    assert names(biz, {"kind": "all", "engaged": "delivered_not_read", "engaged_days": 30}) == ["DeliveredOnly"]
    p = prev(biz, {"kind": "all", "engaged": "delivered_not_read"})[0]
    text = " ".join(n["text"] for n in p["audience_notes"])
    assert "may include people with read receipts turned off" in text
    assert "ignor" not in json.dumps(p).lower()  # never described as ignored, anywhere in what the owner is sent


def test_no_engagement_in_the_last_n_offers(wm, admin):
    biz = pro(admin, wm, "Offers Eng")
    ghost = person(biz, "Ghost")  # two offers reached the phone, nothing since
    reader = person(biz, "Reader")  # read one of the last two
    wrote = person(biz, "Wrote")  # replied after the older of the last two
    one = person(biz, "OnlyOne")  # only one offer so far: cannot be said to have missed two
    unsent = person(biz, "NotDelivered")  # the offers never reached the phone
    old_reader = person(biz, "OldReader")  # read an offer long ago, ignored the last two
    clicker = person(biz, "Clicker")  # clicked after the older of the last two
    offer_msg(biz, ghost["id"], 20)
    offer_msg(biz, ghost["id"], 8)
    offer_msg(biz, reader["id"], 20)
    offer_msg(biz, reader["id"], 8, read=True)
    offer_msg(biz, wrote["id"], 20)
    offer_msg(biz, wrote["id"], 8)
    replied(wrote["id"], 4)
    offer_msg(biz, one["id"], 8)
    offer_msg(biz, unsent["id"], 20, status="sent")
    offer_msg(biz, unsent["id"], 8, status="sent")
    offer_msg(biz, old_reader["id"], 60, read=True)
    offer_msg(biz, old_reader["id"], 20)
    offer_msg(biz, old_reader["id"], 8)
    offer_msg(biz, clicker["id"], 20)
    offer_msg(biz, clicker["id"], 8)
    clicked(biz, clicker["id"], 3)
    assert names(biz, {"kind": "all", "no_engagement_last_offers": 2}) == ["Ghost", "OldReader"]
    assert names(biz, {"kind": "all", "no_engagement_last_offers": 1}) == ["Ghost", "OldReader", "OnlyOne"]  # one offer is enough for OnlyOne; Wrote and Clicker engaged after their last offer
    assert names(biz, {"kind": "all", "no_engagement_last_offers": 3}) == []  # nobody has three unread offers (Ghost has two, OldReader read one of her last three)
    notes = prev(biz, {"kind": "all", "no_engagement_last_offers": 2})[0]["audience_notes"]
    assert any("at least 2 offers" in n["text"] for n in notes) and any("only have data" in n["text"] for n in notes)


def test_an_engagement_choice_combines_with_the_other_choices(wm, admin):
    biz = pro(admin, wm, "Combine Eng")
    a, b = person(biz, "VipReader"), person(biz, "PlainReader")
    owner_exec("UPDATE whatsapp_contacts SET tags = '[\"vip\"]'::jsonb WHERE id = :i", i=a["id"])
    offer_msg(biz, a["id"], 5, read=True)
    offer_msg(biz, b["id"], 5, read=True)
    assert names(biz, {"kind": "tag", "tag": "vip", "engaged": "read"}) == ["VipReader"]
    assert names(biz, {"kind": "all", "engaged": "read", "exclude_tags": ["vip"]}) == ["PlainReader"]


# ===================================================================== win-back: not visited or messaged in N days
def test_winback_uses_messages_only_until_visits_are_marked_and_says_so(wm, admin):
    biz = pro(admin, wm, "Winback Msgs")
    away = person(biz, "Away")
    messaged = person(biz, "Messaged")
    update_msg_target = add_contact(biz, f"98{next(_n):08d}", name="Updated", utility=True, marketing=True, **OWNER)
    owner_exec("UPDATE whatsapp_contacts SET created_at = now() - interval '200 days' WHERE id = :i", i=update_msg_target["id"])
    newbie = person(biz, "Newbie", old=False)
    offer_msg(biz, messaged["id"], 10)
    update_msg(biz, update_msg_target["id"], 12)  # a visit-update message counts as a message too
    p = prev(biz, {"kind": "all", "winback_days": 30})[0]
    assert names(biz, {"kind": "all", "winback_days": 30}) == ["Away"]  # not messaged, old enough; Newbie has had no time to be away
    assert p["audience_notes"][0]["basis"] == "messages_only" and "have not marked any visits" in p["audience_notes"][0]["text"] and "any message counts" in p["audience_notes"][0]["text"]
    assert newbie
    assert names(biz, {"kind": "all", "winback_days": 5}) == ["Away", "Messaged", "Updated"]  # the shorter the window, the fewer count as recently messaged


def test_winback_counts_greetings_and_ignores_failed_messages(wm, admin):
    biz = pro(admin, wm, "Winback Greet")
    greeted, failed_only, away = person(biz, "Greeted"), person(biz, "FailedOnly"), person(biz, "Away")
    biz.post("/whatsapp/setup/prepare-messages", json={})
    biz.post("/whatsapp/templates/sync")
    biz.post(f"/whatsapp/contacts/{greeted['id']}/consent", json={"purpose": "occasion", **OWNER})
    with svc_db(biz.tenant_id) as db:
        t = db.get(Tenant, uuid.UUID(biz.tenant_id))
        res = sender.send_template(db, t, consent.get_contact(db, t.id, uuid.UUID(greeted["id"])), templates.standard_row(db, t.id, "occasion_birthday"), ["Asha", t.name], idem_key=f"g:{uuid.uuid4()}", kind="occasion",
                                   now=datetime.now(IST).replace(hour=11, minute=0).astimezone(timezone.utc))
        db.commit()
    assert res.ok
    owner_exec("UPDATE whatsapp_messages SET created_at = :t WHERE tenant_id = :x AND kind = 'occasion'", t=utcnow() - timedelta(days=9), x=biz.tenant_id)
    mid = offer_msg(biz, failed_only["id"], 5)
    owner_exec("UPDATE whatsapp_messages SET delivery_status = 'failed' WHERE id = :i", i=str(mid))
    assert names(biz, {"kind": "all", "winback_days": 30}) == ["Away", "FailedOnly"]  # a greeting counts as a message; one that failed does not
    assert away


def test_winback_uses_visits_once_any_are_marked_and_enquiries_always(wm, admin):
    biz = pro(admin, wm, "Winback Visits")
    visited, away, enquired = person(biz, "Visited"), person(biz, "Away"), person(biz, "Enquired")
    r = biz.post(f"/whatsapp/contacts/{visited['id']}/visit")  # the helper is off: the visit is still recorded
    assert r.status_code == 200 and r.json()["visit_recorded"] is True
    owner_exec("UPDATE whatsapp_contacts SET last_visit_at = :t WHERE id = :i", t=utcnow() - timedelta(days=3), i=visited["id"])
    owner_exec("UPDATE whatsapp_contacts SET last_enquiry_at = :t WHERE id = :i", t=utcnow() - timedelta(days=4), i=enquired["id"])
    p = prev(biz, {"kind": "all", "winback_days": 30})[0]
    assert names(biz, {"kind": "all", "winback_days": 30}) == ["Away"]
    assert p["audience_notes"][0]["basis"] == "visits" and "Only visits you marked can be known" in p["audience_notes"][0]["text"]
    owner_exec("UPDATE whatsapp_contacts SET last_visit_at = :t WHERE id = :i", t=utcnow() - timedelta(days=45), i=visited["id"])
    assert names(biz, {"kind": "all", "winback_days": 30}) == ["Away", "Visited"]  # the visit was long enough ago
    assert names(biz, {"kind": "all", "winback_days": 60}) == ["Away"]  # but not 60 days ago


def test_an_enquiry_with_a_whatsapp_agreement_records_its_time(wm, admin):
    biz = pro(admin, wm, "Enquiry Time")
    enquiry = SimpleNamespace(id=uuid.uuid4(), phone="98765 43210", name="Meera Shah")
    with svc_db(biz.tenant_id) as db:
        out = automations.on_enquiry(db, uuid.UUID(biz.tenant_id), enquiry, True)
        db.commit()
    assert out["consent_recorded"] is True
    assert owner_query("SELECT last_enquiry_at IS NOT NULL FROM whatsapp_contacts WHERE tenant_id = :t", t=biz.tenant_id)[0][0] is True
    with svc_db(biz.tenant_id) as db:
        automations.on_enquiry(db, uuid.UUID(biz.tenant_id), SimpleNamespace(id=uuid.uuid4(), phone="98765 43211", name="No Tick"), False)  # no WhatsApp agreement: nothing is recorded
        db.commit()
    assert owner_query("SELECT count(*) FROM whatsapp_contacts WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 1


# ===================================================================== replies: a time, never text, never a STOP
def inbound(text, phone="919876543210", wamid=None):
    raw = payload(messages=[{"from": phone, "id": wamid or f"wamid.R{uuid.uuid4().hex[:10]}", "type": "text", "text": {"body": text}, "timestamp": str(int(utcnow().timestamp()))}])
    assert post_wh(raw).status_code == 200
    return process(base.event_id_for(raw)), raw


def test_a_reply_records_only_the_time_and_a_stop_never_counts_as_a_reply(wm, admin):
    biz = pro(admin, wm, "Reply Time")
    c = add_contact(biz, "98765 43210", name="Meera", marketing=True, **OWNER)
    stopper = add_contact(biz, "98765 43211", name="Stopper", marketing=True, **OWNER)
    out, _ = inbound("STOP", "919876543211")
    assert out["opt_outs"] == 1
    assert owner_query("SELECT last_replied_at FROM whatsapp_contacts WHERE id = :i", i=stopper["id"])[0][0] is None  # a STOP is not a reply
    for word in ("stop all", "Unsubscribe", "OPT OUT", "बंद"):
        inbound(word, "919876543211")
        assert owner_query("SELECT last_replied_at FROM whatsapp_contacts WHERE id = :i", i=stopper["id"])[0][0] is None
    before = utcnow()
    out, raw = inbound("Yes, I would like to come on Friday for my knee pain", "919876543210")
    assert out["replies"] == 1
    at = owner_query("SELECT last_replied_at FROM whatsapp_contacts WHERE id = :i", i=c["id"])[0][0]
    assert at is not None and abs((at - before).total_seconds()) < 120
    assert owner_query("SELECT last_replied_at FROM whatsapp_contacts WHERE id = :i", i=stopper["id"])[0][0] is None
    assert names(biz, {"kind": "all", "engaged": "replied", "engaged_days": 7}) == ["Meera"]  # the STOP sender is opted out, so this alone does not prove it: the filter on its own is checked next
    with svc_db(biz.tenant_id) as db:
        f = campaigns._filtered(uuid.UUID(biz.tenant_id), campaigns.clean_audience({"kind": "all", "engaged": "replied", "engaged_days": 7}, "advanced"), utcnow())
        assert [x.customer_name for x in db.scalars(f)] == ["Meera"]  # only the customer who really wrote; the STOP sender is not there


def test_no_message_text_is_stored_anywhere_after_a_reply(wm, admin):
    biz = pro(admin, wm, "No Text")
    add_contact(biz, "98765 43210", name="Meera", marketing=True, **OWNER)
    secret = "my knee hurts when I climb stairs"
    out, raw = inbound(secret)
    assert out["replies"] == 1
    import hashlib
    stored = json.dumps(owner_query("SELECT payload FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=hashlib.sha256(raw).hexdigest())[0][0])
    assert secret not in stored and '"text": null' in stored  # the words were only needed to recognise STOP and sign-ups; once handled they are gone
    cols = {r[0]: r[1] for r in owner_query("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'whatsapp_contacts' AND column_name IN ('last_replied_at', 'last_visit_at', 'last_enquiry_at')")}
    assert cols == {"last_replied_at": "timestamp with time zone", "last_visit_at": "timestamp with time zone", "last_enquiry_at": "timestamp with time zone"}  # timestamps, nothing else
    assert secret not in " ".join(r[0] for r in owner_query("SELECT row_to_json(c)::text FROM whatsapp_contacts c WHERE tenant_id = :t", t=biz.tenant_id)) and secret not in json.dumps(biz.get("/whatsapp/contacts").json(), default=str)


def test_an_unknown_number_or_a_signup_message_is_not_a_reply(wm, admin):
    biz = pro(admin, wm, "Not A Reply")
    inbound("hello there", "919000000001")
    assert owner_query("SELECT count(*) FROM whatsapp_contacts WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0  # a reply never creates a customer
    biz.put("/whatsapp/optin", json={"qr_enabled": True})
    c = add_contact(biz, "98765 43210", name="Meera", marketing=True, **OWNER)
    biz.post("/whatsapp/optin/keywords", json={"keyword": "joinoffers", "purpose": "marketing"})
    inbound("joinoffers", "919876543210")  # an opt-in keyword is a sign-up, not a reply to an offer
    assert owner_query("SELECT last_replied_at FROM whatsapp_contacts WHERE id = :i", i=c["id"])[0][0] is None


def test_a_reply_only_touches_the_business_it_was_sent_to(wm, admin):
    a = pro(admin, wm, "Reply A")
    b = pro(admin, wm, "Reply B", fresh=True)
    ca = add_contact(a, "98765 43210", name="SamePerson", marketing=True, **OWNER)
    cb = add_contact(b, "98765 43210", name="SamePerson", marketing=True, **OWNER)
    inbound("hello", "919876543210")  # arrives on A's number
    assert owner_query("SELECT last_replied_at IS NOT NULL FROM whatsapp_contacts WHERE id = :i", i=ca["id"])[0][0] is True
    assert owner_query("SELECT last_replied_at IS NULL FROM whatsapp_contacts WHERE id = :i", i=cb["id"])[0][0] is True


# ===================================================================== win-back is still an ordinary offer
def test_the_preview_shows_the_count_and_how_many_were_left_out_and_why(wm, admin):
    biz = pro(admin, wm, "Preview Eng")
    for i in range(3):
        person(biz, f"Eligible{i}")
    stopped = person(biz, "Stopped")
    biz.post(f"/whatsapp/contacts/{stopped['id']}/opt-out", json={"purpose": "marketing"})
    person(biz, "NoConsent", marketing=False, utility=True)
    person(biz, "NoConsentTwo", marketing=False)
    new = person(biz, "TooNew", old=False)
    p = prev(biz, {"kind": "all", "winback_days": 30})[0]
    assert p["recipients"] == 3 and p["matching"] == 6 and p["excluded"] == {"no_consent": 2, "opted_out": 1}  # TooNew is not part of a win-back at all
    assert p["matching"] - p["excluded"]["no_consent"] - p["excluded"]["opted_out"] == p["recipients"]
    plain = prev(biz, {"kind": "all"})[0]
    assert plain["recipients"] == 4 and plain["excluded"] == {"no_consent": 2, "opted_out": 1} and new  # the same report for every offer
    assert "Only customers who agreed to receive offers" in p["excluded_note"]


def test_a_winback_offer_is_approved_for_exactly_the_count_that_was_shown(wm, admin):
    biz = pro(admin, wm, "Approve Eng")
    for i in range(3):
        person(biz, f"Away{i}")
    p, c = prev(biz, {"kind": "all", "winback_days": 30})
    assert p["recipients"] == 3
    assert approve(biz, c["id"], 3, accept=False).json()["detail"]["code"] == "estimate_not_accepted"
    r = approve(biz, c["id"], 2)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "recipients_changed"
    person(biz, "Away3")  # someone else becomes eligible before the owner confirms
    r2 = approve(biz, c["id"], 3)
    assert r2.status_code == 409 and r2.json()["detail"]["code"] == "recipients_changed" and "3 to 4" in r2.json()["detail"]["message"]
    ok = approve(biz, c["id"], 4)
    assert ok.status_code == 200 and ok.json()["status"] == "scheduled" and ok.json()["approved_recipients"] == 4
    assert wm.sent == []  # nothing goes out on approval itself, only when sending starts


def test_the_approved_list_is_fixed_and_the_gate_rechecks_each_person_when_sending(wm, admin):
    biz = pro(admin, wm, "Recheck Eng")
    cs = [person(biz, f"Away{i}") for i in range(5)]
    p, c = prev(biz, {"kind": "all", "winback_days": 30})
    assert approve(biz, c["id"], 5).status_code == 200
    late = person(biz, "AddedAfterApproval")  # eligible, but not in the list the owner approved
    biz.post(f"/whatsapp/contacts/{cs[0]['id']}/opt-out", json={"purpose": "marketing"})  # STOP-style opt-out after approval
    owner_exec("UPDATE whatsapp_consents SET revoked_at = now(), revoked_source = 'owner' WHERE contact_id = :i AND purpose = 'marketing'", i=cs[1]["id"])  # consent withdrawn after approval, no opt-out flag
    sent_offer = send(biz, cs[2]["id"], key="offer", variables=["Asha", "Recheck Eng", "10% off this week"], idem="elsewhere")  # an offer to someone else's recipient inside the 72 hours
    assert sent_offer.ok
    out = tick(biz.tenant_id, 2)["campaigns"]
    r = biz.get(f"/whatsapp/campaigns/{c['id']}/results").json()
    assert out["sent"] == 2 and out["skipped"] == 3 and out["finished"] == 1
    assert r["approved_recipients"] == 5 and r["sent"] + 1 == len(wm.sent) and r["skipped"] == 3  # sent and skipped add up to what was approved
    assert r["skipped_reasons"] == {"opted_out": 1, "no_marketing_consent": 1, "too_soon": 1}
    sent_to = {m["to"] for m in wm.sent}
    assert sent_to.isdisjoint({cs[0]["phone"].lstrip("+"), cs[1]["phone"].lstrip("+")}) and late["phone"].lstrip("+") not in sent_to


def test_a_winback_offer_waits_for_sending_hours_and_stops_for_the_emergency_stop(wm, admin, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_send_window_start", 9)
    monkeypatch.setattr(settings, "whatsapp_send_window_end", 21)
    biz = pro(admin, wm, "Hours Eng")
    for i in range(2):
        person(biz, f"Away{i}")
    p, c = prev(biz, {"kind": "all", "winback_days": 30})
    assert approve(biz, c["id"], 2).status_code == 200
    db = system_session()
    try:
        night = datetime.now(IST).replace(hour=23, minute=30, second=0).astimezone(timezone.utc) + timedelta(days=1)
        assert campaigns.run_due(db, now=night, tenant_id=uuid.UUID(biz.tenant_id)) == {"held": True, "reason": "outside_hours"}
        monkeypatch.setattr(settings, "whatsapp_emergency_stop", True)
        noon = datetime.now(IST).replace(hour=12, minute=0, second=0).astimezone(timezone.utc) + timedelta(days=1)
        assert campaigns.run_due(db, now=noon, tenant_id=uuid.UUID(biz.tenant_id)) == {"held": True}
        monkeypatch.setattr(settings, "whatsapp_emergency_stop", False)
        out = campaigns.run_due(db, now=noon, tenant_id=uuid.UUID(biz.tenant_id))
        db.commit()
    finally:
        db.close()
    assert out["sent"] == 2 and len(wm.sent) == 2  # inside the hours and with nothing stopped, it goes


def test_a_winback_offer_is_an_ordinary_offer_to_the_gate(wm, admin):
    biz = pro(admin, wm, "Gate Eng")
    c = person(biz, "Away")
    assert approve(biz, prev(biz, {"kind": "all", "winback_days": 30})[1]["id"], 1).status_code == 200
    tick(biz.tenant_id, 2)
    row = owner_query("SELECT category, campaign_id IS NOT NULL, kind FROM whatsapp_messages WHERE tenant_id = :t AND contact_id = :c", t=biz.tenant_id, c=c["id"])
    assert row[-1] == ("marketing", True, None)  # a marketing message from a campaign, with no special kind that could skip any rule
    assert wm.sent[-1]["template"]["name"] == "flowqr_offer_en"
    assert owner_query("SELECT count(*) FROM whatsapp_messages WHERE tenant_id = :t AND kind IS NOT NULL", t=biz.tenant_id)[0][0] == 0


def test_a_winback_audience_for_a_plan_that_lost_pro_is_refused_at_approval_time_for_new_choices(wm, admin):
    biz = pro(admin, wm, "Downgrade Eng")
    person(biz, "Away")
    p, c = prev(biz, {"kind": "all", "winback_days": 30})
    assert admin.put(f"/admin/tenants/{biz.tenant_id}/whatsapp-addon", json={"addon_key": "whatsapp_growth", "reason": "Plan changed to Growth by the owner"}).status_code == 200
    r = biz.patch(f"/whatsapp/campaigns/{c['id']}", json={"audience": {"kind": "all", "winback_days": 45}})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_required"  # editing the choices needs Pro
    assert c


# ===================================================================== the new columns: shown, exported, deleted
def test_visit_reply_and_enquiry_times_are_shown_exported_and_deleted_with_the_customer(wm, admin):
    biz = pro(admin, wm, "Columns Eng")
    c = add_contact(biz, "98765 43210", name="Meera Shah", utility=True, **OWNER)
    r = biz.post(f"/whatsapp/contacts/{c['id']}/visit")
    assert r.status_code == 200 and r.json()["visit_recorded"] is True
    inbound("hello", "919876543210")
    owner_exec("UPDATE whatsapp_contacts SET last_enquiry_at = now() WHERE id = :i", i=c["id"])
    got = biz.get("/whatsapp/contacts").json()["items"][0]
    assert got["last_visit_at"] and got["last_replied_at"] and got["last_enquiry_at"]
    lines = biz.get("/whatsapp/contacts/export").text.splitlines()
    assert lines[0].endswith("last_visit_at,last_enquiry_at,last_replied_at")
    row = dict(zip(lines[0].split(","), next(ln for ln in lines if "Meera" in ln).split(",")))
    assert row["last_visit_at"] and row["last_enquiry_at"] and row["last_replied_at"] and "hello" not in " ".join(lines)
    z = zipfile.ZipFile(io.BytesIO(biz.get("/account/export").content))
    exported = json.loads(z.read("whatsapp_contacts.json"))[0]
    assert exported["last_visit_at"] and exported["last_replied_at"] and exported["last_enquiry_at"]
    assert biz.delete(f"/whatsapp/contacts/{c['id']}").status_code == 204
    assert owner_query("SELECT count(*) FROM whatsapp_contacts WHERE id = :i", i=c["id"])[0][0] == 0  # the times were columns of the customer: gone with them
    assert "Meera" not in biz.get("/whatsapp/contacts/export").text


def test_the_times_go_when_the_business_goes(wm, admin):
    biz = pro(admin, wm, "Columns Gone")
    c = add_contact(biz, "98765 43211", name="Ravi", utility=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{c['id']}/visit")
    db = system_session()
    try:
        from sqlalchemy import text
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": biz.tenant_id})
        db.commit()
    finally:
        db.close()
    assert owner_query("SELECT count(*) FROM whatsapp_contacts WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0


def test_a_visit_is_saved_whatever_the_helper_or_consent(wm, admin):
    biz = pro(admin, wm, "Visit Always")
    no_consent = add_contact(biz, "98765 43212", name="NoConsent")
    r = biz.post(f"/whatsapp/contacts/{no_consent['id']}/visit")
    assert r.status_code == 200 and r.json() == {"visit_recorded": True, "scheduled": False, "reason": "automation_off"}
    biz.put("/whatsapp/automations/review_followup", json={"status": "on"})
    r2 = biz.post(f"/whatsapp/contacts/{no_consent['id']}/visit")
    assert r2.json() == {"visit_recorded": True, "scheduled": False, "reason": "no_utility_consent"}
    assert owner_query("SELECT last_visit_at IS NOT NULL FROM whatsapp_contacts WHERE id = :i", i=no_consent["id"])[0][0] is True
    other = make_business("Visit Other")
    assert other.post(f"/whatsapp/contacts/{no_consent['id']}/visit").status_code in (404, 409)  # another business cannot mark it


def test_the_migration_added_only_timestamps_to_the_customer():
    cols = {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = 'whatsapp_contacts'")}
    assert {"last_replied_at", "last_visit_at", "last_enquiry_at"} <= cols
    assert not {"last_reply_text", "last_message", "reply_text", "last_reply"} & cols
