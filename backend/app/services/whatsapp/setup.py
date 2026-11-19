"""First-run set-up: a short guided path from "nothing" to "my first helper is on", told as a checklist a shop owner can follow without knowing what a webhook is.

The six steps (each is derived from real records, never from a flag the owner ticks):
  1 plan        the WhatsApp add-on is on (recorded by FlowQR);
  2 connect     the business's own number is connected and healthy;
  3 messages    WhatsApp has approved the standard messages (FlowQR submits them for the owner in one click);
  4 customers   at least one customer has agreed to visit updates;
  5 test        a test message was sent to the owner's OWN number and WhatsApp accepted it;
  6 helper      at least one helper is switched on.

The test message goes through the same sender and gate as every other message (consent, approved template, limits, emergency stop). To send it the owner confirms the number is their own, which records a
visit-updates consent for that number written by the owner about themselves (source owner_entry, with that note). It is a real message and is counted in usage like any other; it is sent at most a few times an hour.
Nothing here sends anything unless sending is switched on.
"""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import hit
from app.models import Tenant, User
from app.models.base import utcnow
from app.models.whatsapp import WhatsAppMessage
from app.services.audit import audit
from app.services.whatsapp import WaError, addons, automations, connection, consent, sender, templates

UTILITY_KEYS = ("review_followup", "enquiry_ack", "enquiry_followup")
STEPS = ("plan", "connect", "messages", "customers", "test", "helper")
TEST_PREFIX = "test:"
OWN_NUMBER_NOTE = "The owner's own number, used to send a test message"

# What suits which kind of business, in one line each. A suggestion only: the owner chooses.
SUGGESTIONS = [
    (("clinic", "physio", "dental", "doctor", "hospital", "diagnostic", "salon", "spa", "beauty", "gym", "fitness", "yoga"), ["review_followup", "enquiry_followup"],
     "People often book by asking first, and a kind word after a visit is when they are happiest to review you."),
    (("restaurant", "cafe", "food", "bakery", "sweet", "grocery", "store", "shop", "retail", "boutique", "garment", "jewel"), ["offers", "review_followup"],
     "Customers come back for offers, and a review request after a visit brings new people in."),
    (("plumb", "electric", "repair", "cleaning", "service", "contractor", "lawyer", "advocate", "account", "consult"), ["enquiry_followup", "review_followup"],
     "Most work starts with an enquiry, so a quick reply and a follow-up matter most."),
]
DEFAULT_SUGGESTION = (["review_followup", "enquiry_followup"], "A thank-you for every enquiry and a request for honest feedback after a visit suit most businesses.")


def recommend(category: str | None) -> dict:
    c = (category or "").lower()
    for words, keys, why in SUGGESTIONS:
        if any(w in c for w in words):
            return {"helpers": keys, "why": why}
    return {"helpers": DEFAULT_SUGGESTION[0], "why": DEFAULT_SUGGESTION[1]}


def last_test(db: Session, tenant_id: uuid.UUID) -> WhatsAppMessage | None:
    return db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.tenant_id == tenant_id, WhatsAppMessage.idempotency_key.like(TEST_PREFIX + "%")).order_by(WhatsAppMessage.created_at.desc()).limit(1))


def _step(key: str, title: str, body: str, state: str, **extra) -> dict:
    return {"key": key, "title": title, "body": body, "state": state, **extra}  # state: done | todo | waiting | blocked


def status(db: Session, tenant: Tenant) -> dict:
    tid = tenant.id
    addon = addons.active_addon(db, tid)
    live = connection.live_connection(db, tid)
    conn = connection.connected_connection(db, tid)
    connected = conn is not None and conn.status == "connected"
    rows = {k: templates.standard_row(db, tid, k) for k in UTILITY_KEYS}
    counts = consent.counts(db, tid)
    test = last_test(db, tid)
    helpers_on = automations.active_count(db, tid)
    addon_ok = addon is not None or not settings.whatsapp_require_addon
    signup = connection.signup_configured()
    steps: list[dict] = []

    steps.append(_step("plan", "WhatsApp is switched on for your business", "WhatsApp automation is an add-on. FlowQR turns it on for you." if not addon_ok else
                       (f"You have {addons.tier(addon)['label']}." if addon else "Included."), "done" if addon_ok else "blocked", action="ask_flowqr"))

    if connected:
        steps.append(_step("connect", "Your WhatsApp number is connected", f"Connected: {conn.display_phone_number or 'your number'}.", "done", action="connect"))
    elif not addon_ok:
        steps.append(_step("connect", "Connect your WhatsApp number", "Switch on the add-on first.", "blocked", action="connect"))
    elif live is not None and live.status == "needs_attention":
        steps.append(_step("connect", "Fix your WhatsApp connection", live.attention_reason or "Your connection needs attention.", "todo", action="connect"))
    elif not signup:
        steps.append(_step("connect", "Connect your WhatsApp number", "Connecting is not available yet. FlowQR is still completing its set-up with Meta.", "waiting", action="connect"))
    else:
        steps.append(_step("connect", "Connect your WhatsApp number", "It takes about ten minutes. You need your number and a Facebook login.", "todo", action="connect"))

    if not connected:
        steps.append(_step("messages", "Get your messages approved", "WhatsApp approves every message before it can be sent. We send them for you once you are connected.", "blocked", action="prepare_messages"))
    else:
        approved = [k for k, r in rows.items() if r is not None and r.approval_status == "approved"]
        pending = [k for k, r in rows.items() if r is not None and r.approval_status == "pending"]
        refused = [k for k, r in rows.items() if r is not None and r.approval_status in ("rejected", "paused", "disabled")]
        missing = [k for k, r in rows.items() if r is None]
        if len(approved) == len(UTILITY_KEYS):
            steps.append(_step("messages", "Your messages are approved", "WhatsApp has approved the messages your helpers use.", "done", action="prepare_messages"))
        elif refused:
            steps.append(_step("messages", "A message was not approved", "WhatsApp did not approve one of the messages. Open Messages to see why.", "todo", action="open_messages", refused=refused))
        elif pending and not missing:
            steps.append(_step("messages", "WhatsApp is reviewing your messages", "This usually takes a short while. Press Check with WhatsApp to see if they are ready.", "waiting", action="check_messages", pending=pending))
        else:
            steps.append(_step("messages", "Get your messages approved", "One click sends the messages your helpers use to WhatsApp for approval.", "todo", action="prepare_messages", missing=missing))

    if counts["utility"] > 0:
        steps.append(_step("customers", "You have customers who agreed", f"{counts['utility']} customer{'s' if counts['utility'] != 1 else ''} agreed to updates about their visit.", "done", action="customers"))
    else:
        steps.append(_step("customers", "Add a customer who agreed to hear from you", "Only customers who agreed are ever messaged. Add yourself first to try it out.", "todo", action="customers"))

    tested = test is not None and test.delivery_status in ("sent", "delivered", "read")
    if tested:
        steps.append(_step("test", "Your test message arrived", {"sent": "WhatsApp accepted it. Check your phone.", "delivered": "It reached your phone.", "read": "You opened it."}[test.delivery_status], "done", action="test",
                           test={"status": test.delivery_status, "sent_at": test.sent_at, "delivered_at": test.delivered_at}))
    elif not connected or any(r is None or r.approval_status != "approved" for k, r in rows.items() if k == "enquiry_ack"):
        steps.append(_step("test", "Send yourself a test message", "You can test once your number is connected and your messages are approved.", "blocked", action="test"))
    elif not automations.sending_allowed():
        steps.append(_step("test", "Send yourself a test message", "Sending is not switched on yet. The test will work as soon as FlowQR switches it on.", "waiting", action="test"))
    else:
        steps.append(_step("test", "Send yourself a test message", "See exactly what a customer receives, on your own phone." + (" Your last try did not go through." if test is not None and test.delivery_status == "failed" else ""), "todo", action="test"))

    rec = recommend(tenant.category)
    if helpers_on > 0:
        steps.append(_step("helper", "A helper is on", f"{helpers_on} helper{'s are' if helpers_on != 1 else ' is'} switched on.", "done", action="helpers", recommended=rec["helpers"]))
    else:
        steps.append(_step("helper", "Switch on your first helper", rec["why"], "todo" if connected else "blocked", action="helpers", recommended=rec["helpers"]))

    done = sum(1 for s in steps if s["state"] == "done")
    nxt = next((s["key"] for s in steps if s["state"] != "done"), None)
    return {"steps": steps, "done": done, "total": len(steps), "complete": done == len(steps), "next": nxt, "sending": automations.sending_allowed(), "recommended": rec,
            "last_test": {"status": test.delivery_status, "sent_at": test.sent_at, "delivered_at": test.delivered_at} if test is not None else None}


def prepare_messages(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, ip: str | None = None, include_offer: bool = False, include_optin: bool = False) -> dict:
    """Submit the standard messages the helpers use (and, if asked, the offer message and the opt-in confirmations) that are not yet with WhatsApp. Safe to repeat."""
    keys = list(UTILITY_KEYS) + (["offer"] if include_offer else []) + (["optin_confirm", "optin_confirm_offers"] if include_optin else [])
    done, skipped = [], []
    for k in keys:
        if templates.standard_row(db, tenant_id, k) is not None:
            skipped.append(k)
            continue
        templates.install(db, tenant_id, k, user_id, ip)
        done.append(k)
    return {"submitted": done, "already_there": skipped}


def send_test(db: Session, tenant: Tenant, user: User, *, phone: str, own_number: bool, ip: str | None = None, now: datetime | None = None) -> dict:
    """A test message to the owner's own number, through the normal sender and gate."""
    now = now or utcnow()
    if not own_number:
        raise WaError(422, "own_number_required", "Please confirm this is your own number. A test goes to you, not to a customer.")
    conn = connection.connected_connection(db, tenant.id)
    if conn is None or conn.status != "connected":
        raise WaError(409, "not_connected", "Connect your WhatsApp number first.")
    row = templates.standard_row(db, tenant.id, "enquiry_ack")
    if row is None or row.approval_status != "approved":
        raise WaError(409, "template_not_approved", "WhatsApp has not approved the message yet. Prepare your messages and check again in a short while.")
    if not automations.sending_allowed():
        raise WaError(409, "sending_off", "Sending is not switched on yet. Your test will work as soon as FlowQR switches it on.")
    if not hit(f"wa-test:{tenant.id}", 5, 3600):
        raise WaError(429, "rate_limited", "That is enough tests for now. Please try again in an hour.")
    p = consent.e164(phone)
    contact, _ = consent.create_contact(db, tenant, phone=p, name=None, tags=["test"], source="owner_entry", user_id=user.id)
    consent.grant(db, tenant, contact, "utility", "owner_entry", user_id=user.id, attested=True, evidence=OWN_NUMBER_NOTE, ip=ip)
    res = sender.send_template(db, tenant, contact, row, [templates.first_name(user.full_name), tenant.name], idem_key=f"{TEST_PREFIX}{tenant.id}:{p}:{int(now.timestamp()) // 60}")
    audit(db, action="whatsapp.test_message", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_contact", entity_id=contact.id, meta={"result": res.status, "reason": res.reason}, ip=ip)
    if res.status == "sent":
        return {"sent": True, "message_id": res.message_id, "to_last4": p[-4:]}
    if res.status == "failed":
        raise WaError(502, "meta_rejected", "WhatsApp did not accept the message. Check that the number can receive WhatsApp messages and try again.")
    if res.status == "retry":
        raise WaError(503, "try_again", "WhatsApp is busy right now. Please try again in a minute.")
    raise WaError(409, res.reason, "The test could not be sent: " + {"no_utility_consent": "this number has not agreed to messages yet.", "opted_out": "this number asked to stop.", "too_soon": "a message was sent very recently.",
                                                                    "emergency_stop": "sending is paused for everyone for now.", "token_expired": "your WhatsApp connection needs renewing."}.get(res.reason, "it was not allowed right now."))
