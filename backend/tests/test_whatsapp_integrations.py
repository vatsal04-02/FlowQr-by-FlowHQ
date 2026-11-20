"""WhatsApp integrations (Phase 10 of the second round): API keys, the idempotent inbound API, signed outbound webhooks. It ships OFF and is Pro only.

What must never happen: a key that works after it is revoked or on a business that left Pro, one business's key touching another's data, an API call that quietly records consent, a request done twice, a webhook sent
to a private address or without a signature, message text in an event. No real network is used: DNS and the outbound HTTP call are replaced.
"""
import hashlib
import hmac
import io
import json
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings, whatsapp_passthrough_missing
from app.core.db import system_session
from app.core.security import get_cipher
from app.main import app
from app.models.base import utcnow
from app.services import mailer
from app.services.whatsapp import integrations
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_location_permissions import invite
from tests.test_whatsapp import OWNER, add_contact, grant_addon, payload, post_wh, process, wa  # noqa: F401 - fixtures
from tests import test_whatsapp as base
from tests.test_whatsapp_bookings import ALL_DAYS, SVC, day, setup_bookings
from tests.test_whatsapp_conversations import conv_of, inbound, inbox_biz, inbox_platform, phone_digits, run  # noqa: F401
from tests.test_whatsapp_messaging import messages, send, wm  # noqa: F401 - fixtures

API = "/api/v1/integrations/v1"
HOOK_URL = "https://hooks.example.com/flowqr"
DNS = {"hooks.example.com": "93.184.216.34", "other.example.com": "93.184.216.35"}
ALL_SCOPES = ["customers:write", "visits:write", "enquiries:write", "bookings:write"]


@pytest.fixture(autouse=True)
def platform(monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_integrations_enabled", True)
    monkeypatch.setattr(settings, "whatsapp_booking_enabled", True)
    mailer.OUTBOX.clear()


class Net:
    """Stands in for DNS and for the outbound HTTP call. `answers` are the receiver's replies, in order (the last repeats)."""

    def __init__(self):
        self.dns, self.calls, self.answers = dict(DNS), [], [200]

    def resolve(self, host, port, type=None):
        if host not in self.dns:
            raise OSError("not found")
        addr = self.dns[host]
        return [(10 if ":" in addr else 2, 1, 6, "", (addr, port))]

    def post(self, url, content=None, headers=None, timeout=None, follow_redirects=None, extensions=None):
        self.calls.append({"url": url, "body": content, "headers": headers, "follow_redirects": follow_redirects, "extensions": extensions})
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        return httpx.Response(a)


@pytest.fixture()
def net(monkeypatch):
    n = Net()
    monkeypatch.setattr(integrations, "_resolve", n.resolve)
    monkeypatch.setattr(integrations, "_post", n.post)
    return n


def pro_biz(admin, wm, name, tier="whatsapp_pro", fresh=False):
    return inbox_biz(admin, wm, name, tier=tier, fresh=fresh)


def new_key(biz, scopes=None, **kw):
    r = biz.post("/whatsapp/integrations/keys", json={"name": "Shop system", "scopes": scopes or ALL_SCOPES, **kw})
    assert r.status_code == 201, r.text
    return r.json()["key"], r.json()


def call(key, method, path, body=None, idem="auto", **headers):
    h = {"Authorization": f"Bearer {key}", **headers}
    if method == "POST" and idem == "auto":
        idem = uuid.uuid4().hex
    if method == "POST" and idem:
        h["Idempotency-Key"] = idem
    with TestClient(app, base_url="http://testserver") as c:
        return c.request(method, API + path, json=body, headers=h)


def new_hook(biz, events=None, url=HOOK_URL):
    r = biz.post("/whatsapp/integrations/endpoints", json={"url": url, "events": events or ["booking.created", "booking.updated", "message.status", "contact.opted_out", "conversation.created"]})
    assert r.status_code == 201, r.text
    return r.json()["secret"], r.json()


def deliveries(biz, where="TRUE"):
    return owner_query(f"SELECT event_type, status, attempts, last_status_code, last_error FROM whatsapp_webhook_deliveries WHERE tenant_id = :t AND {where} ORDER BY created_at", t=biz.tenant_id)


def drain(biz, when=None):
    db = system_session()
    try:
        out = integrations.run_deliveries(db, when, tenant_id=uuid.UUID(biz.tenant_id))
        db.commit()
        return out
    finally:
        db.close()


def consents(biz):
    return owner_query("SELECT purpose, source FROM whatsapp_consents WHERE tenant_id = :t ORDER BY purpose", t=biz.tenant_id)


# ===================================================================== off by default, plan, roles
def test_the_defaults_are_off_and_the_switch_is_passed_through_and_needs_the_encryption_key():
    assert Settings.model_fields["whatsapp_integrations_enabled"].default is False
    import os
    path = next(p for p in ("../deploy/vps/docker-compose.vps.yml", "../../deploy/vps/docker-compose.vps.yml", "/deploy/vps/docker-compose.vps.yml") if os.path.exists(p))
    assert "WHATSAPP_INTEGRATIONS_ENABLED: ${WHATSAPP_INTEGRATIONS_ENABLED:-false}" in open(path, encoding="utf-8").read() and "WHATSAPP_INTEGRATIONS_ENABLED" in whatsapp_passthrough_missing({})


def test_only_pro_owners_and_admins_can_use_it_and_the_platform_switch_gates_everything(wm, admin, monkeypatch):
    biz = pro_biz(admin, wm, "Pro Biz")
    growth = pro_biz(admin, wm, "Growth Biz", tier="whatsapp_growth", fresh=True)
    r = growth.post("/whatsapp/integrations/keys", json={"name": "x system", "scopes": ["customers:write"]})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "plan_required"  # Growth does not include integrations
    assert growth.get("/whatsapp/integrations").json()["plan_ok"] is False
    member = invite(biz, role="staff")
    assert member.get("/whatsapp/integrations").status_code == 403 and member.post("/whatsapp/integrations/keys", json={"name": "nope", "scopes": ["customers:write"]}).status_code == 403
    monkeypatch.setattr(settings, "whatsapp_integrations_enabled", False)
    assert biz.get("/whatsapp/integrations").status_code == 404 and biz.post("/whatsapp/integrations/keys", json={"name": "nope", "scopes": ["customers:write"]}).json()["detail"]["code"] == "integrations_disabled"
    monkeypatch.setattr(settings, "whatsapp_integrations_enabled", True)
    key, _ = new_key(biz)
    monkeypatch.setattr(settings, "whatsapp_integrations_enabled", False)
    assert call(key, "GET", "/me").status_code == 403  # a valid key does nothing while the platform switch is off


# ===================================================================== keys
def test_a_key_is_shown_once_stored_only_as_a_hash_and_listed_without_it(wm, admin):
    biz = pro_biz(admin, wm, "Key Biz")
    key, row = new_key(biz)
    assert key.startswith("fqk_") and len(key) > 40 and row["prefix"] == key[:12] and "key" in row and "key_hash" not in row
    stored = owner_query("SELECT key_hash, prefix FROM whatsapp_api_keys WHERE tenant_id = :t", t=biz.tenant_id)[0]
    assert stored[0] == hashlib.sha256(key.encode()).hexdigest() and key not in stored  # only the hash is kept
    listed = biz.get("/whatsapp/integrations").json()["keys"][0]
    assert "key" not in listed and "key_hash" not in listed and listed["prefix"] == key[:12] and listed["active"] is True
    assert key not in json.dumps(biz.get("/whatsapp/integrations").json())
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.api_key_create'", t=biz.tenant_id)[0][0] == 1
    assert key not in str(owner_query("SELECT row_to_json(a)::text FROM audit_logs a WHERE tenant_id = :t", t=biz.tenant_id))  # never in the audit log either
    me = call(key, "GET", "/me").json()
    assert me["business"] == "Key Biz" and me["key"]["scopes"] == ALL_SCOPES and owner_query("SELECT last_used_at IS NOT NULL FROM whatsapp_api_keys WHERE tenant_id = :t", t=biz.tenant_id)[0][0] is True


def test_a_revoked_expired_wrong_or_missing_key_is_refused_the_same_way(wm, admin):
    biz = pro_biz(admin, wm, "Revoke Biz")
    key, row = new_key(biz)
    other, _ = new_key(biz)
    expiring, _ = new_key(biz, expires_in_days=1)
    assert call(key, "GET", "/me").status_code == 200
    assert biz.post(f"/whatsapp/integrations/keys/{row['id']}/revoke").json()["active"] is False
    bodies = set()
    for k in (key, "fqk_" + "x" * 43, "not-a-key", ""):
        r = call(k, "GET", "/me")
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        bodies.add(r.text)
    assert len(bodies) == 1  # revoked, unknown and malformed look identical
    with TestClient(app, base_url="http://testserver") as c:
        assert c.get(API + "/me").status_code == 401
    assert call(other, "GET", "/me").status_code == 200  # the others are untouched
    owner_exec("UPDATE whatsapp_api_keys SET expires_at = now() - interval '1 minute' WHERE key_hash = :h", h=hashlib.sha256(expiring.encode()).hexdigest())
    assert call(expiring, "GET", "/me").status_code == 401


def test_key_creation_is_validated_and_limited(wm, admin):
    biz = pro_biz(admin, wm, "Key Rules")
    for bad in ({"name": "x", "scopes": ["customers:write"]}, {"name": "System", "scopes": []}, {"name": "System", "scopes": ["everything"]}, {"name": "System", "scopes": ["customers:write"], "rate_limit_per_min": 5},
                {"name": "System", "scopes": ["customers:write"], "rate_limit_per_min": 5000}, {"name": "System", "scopes": ["customers:write"], "expires_in_days": 0}):
        assert biz.post("/whatsapp/integrations/keys", json=bad).status_code == 422, bad
    for i in range(10):
        new_key(biz, scopes=["customers:write"])
    assert biz.post("/whatsapp/integrations/keys", json={"name": "eleventh", "scopes": ["customers:write"]}).json()["detail"]["code"] == "too_many"


def test_each_call_needs_its_own_scope_and_a_rate_limit_applies_per_key(wm, admin, monkeypatch):
    biz = pro_biz(admin, wm, "Scope Biz")
    only_customers, _ = new_key(biz, scopes=["customers:write"])
    assert call(only_customers, "POST", "/customers", {"phone": "98765 43210"}).status_code == 200
    for path, body in (("/visits", {"phone": "98765 43210"}), ("/enquiries", {"phone": "98765 43210"}), ("/bookings", {"phone": "98765 43210", "service": "x", "date": day(3), "time": "10:00"})):
        r = call(only_customers, "POST", path, body)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "insufficient_scope", path
    seen = []
    monkeypatch.setattr(integrations, "hit", lambda k, n, s: (seen.append((k, n, s)), len(seen) < 3)[1])
    key, row = new_key(biz, rate_limit_per_min=30)
    assert call(key, "GET", "/me").status_code == 200 and call(key, "GET", "/me").status_code == 200
    r = call(key, "GET", "/me")
    assert r.status_code == 429 and r.headers["retry-after"] == "60" and seen[0] == (f"wa-api:{row['id']}", 30, 60)


def test_a_business_that_drops_below_pro_loses_the_api_at_once(wm, admin):
    biz = pro_biz(admin, wm, "Downgrade Biz")
    key, _ = new_key(biz)
    assert call(key, "GET", "/me").status_code == 200
    grant_addon(admin, biz, "whatsapp_growth")
    r = call(key, "GET", "/me")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "integrations_off"
    assert len(biz.get("/whatsapp/integrations").json()["keys"]) == 1  # nothing is deleted: moving back to Pro brings it back


# ===================================================================== idempotency
def test_a_retry_with_the_same_key_returns_the_first_answer_and_does_nothing_twice(wm, admin):
    biz = pro_biz(admin, wm, "Idem Biz")
    key, _ = new_key(biz)
    assert call(key, "POST", "/customers", {"phone": "98765 43210"}, idem=None).json()["detail"]["code"] == "idempotency_key_required"
    assert call(key, "POST", "/customers", {"phone": "98765 43210"}, idem="short").status_code == 422
    body = {"phone": "98765 43210", "name": "Asha", "consent": {"purposes": ["utility"], "agreed": True, "evidence": "Ticked the WhatsApp box at checkout on 12 Nov"}}
    a = call(key, "POST", "/customers", body, idem="order-1001")
    b = call(key, "POST", "/customers", body, idem="order-1001")
    assert a.status_code == b.status_code == 200 and a.json() == b.json() and "idempotent-replay" not in a.headers and b.headers["idempotent-replay"] == "true"
    assert owner_query("SELECT count(*) FROM whatsapp_contacts WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 1 and consents(biz) == [("utility", "api_integration")]
    clash = call(key, "POST", "/customers", {**body, "name": "Someone else"}, idem="order-1001")
    assert clash.status_code == 422 and clash.json()["detail"]["code"] == "idempotency_conflict"
    assert call(key, "POST", "/customers", {"phone": "98765 43211"}, idem="order-1002").status_code == 200  # a new key is a new request
    # a failed request is not remembered: fix the cause and retry with the same key
    bad = call(key, "POST", "/visits", {"phone": "98765 49999"}, idem="visit-5001")
    assert bad.status_code == 404 and bad.json()["detail"]["code"] == "customer_not_found"
    call(key, "POST", "/customers", {"phone": "98765 49999"}, idem="cust-5001")
    assert call(key, "POST", "/visits", {"phone": "98765 49999"}, idem="visit-5001").status_code == 200
    # the same Idempotency-Key from another key (or business) is a different request altogether
    key2, _ = new_key(biz)
    assert call(key2, "POST", "/customers", body, idem="order-1001").headers.get("idempotent-replay") is None


# ===================================================================== "they agreed": nothing here creates consent by itself
def test_the_api_records_consent_only_with_an_explicit_agreement_and_a_note_of_how(wm, admin):
    biz = pro_biz(admin, wm, "Agree Biz")
    key, _ = new_key(biz)
    assert call(key, "POST", "/customers", {"phone": "98765 40001", "name": "No Consent"}).status_code == 200
    assert consents(biz) == []  # a customer arriving through the API has no consent
    ok_shape = {"purposes": ["utility"], "agreed": True, "evidence": "Ticked the WhatsApp box at checkout on 12 Nov"}
    for bad in ({**ok_shape, "agreed": False}, {k: v for k, v in ok_shape.items() if k != "evidence"}, {**ok_shape, "evidence": "yes"}, {**ok_shape, "evidence": "          "}, {**ok_shape, "purposes": []},
                {**ok_shape, "purposes": ["everything"]}, {**ok_shape, "purposes": ["utility", "marketing", "occasion", "x"]}, {**ok_shape, "extra": 1}):
        r = call(key, "POST", "/customers", {"phone": "98765 40002", "consent": bad})
        assert r.status_code == 422, (bad, r.text)
    assert consents(biz) == [] and owner_query("SELECT count(*) FROM whatsapp_contacts WHERE tenant_id = :t AND phone = '+919876540002'", t=biz.tenant_id)[0][0] == 0  # refused means nothing was done
    assert call(key, "POST", "/customers", {"phone": "98765 40003", "unknown_field": 1}).status_code == 422
    r = call(key, "POST", "/customers", {"phone": "98765 40004", "consent": {**ok_shape, "purposes": ["utility", "marketing"]}}).json()
    assert r["consent_recorded"] == {"utility": "recorded", "marketing": "recorded"} and r["consent"]["utility"] is True
    row = owner_query("SELECT purpose, source, evidence FROM whatsapp_consents WHERE tenant_id = :t AND purpose = 'marketing'", t=biz.tenant_id)[0]
    assert row[1] == "api_integration" and "checkout" in row[2]  # the same attested evidence rule as an owner typing a customer in
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.consent_grant'", t=biz.tenant_id)[0][0] == 2


def test_a_customer_who_said_stop_cannot_be_added_back_through_the_api(wm, admin):
    biz = pro_biz(admin, wm, "Stop Biz")
    key, _ = new_key(biz)
    phone = phone_digits()
    add_contact(biz, "+" + phone, name="Stopper", marketing=True, **OWNER)
    inbound(biz, "STOP", phone=phone)
    r = call(key, "POST", "/customers", {"phone": "+" + phone, "consent": {"purposes": ["marketing"], "agreed": True, "evidence": "Ticked the box on our checkout page"}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "opted_out"
    assert biz.get("/whatsapp/contacts").json()["items"][0]["opted_out"] is True


def test_visits_enquiries_and_bookings_through_the_api_never_create_consent(wm, admin):
    biz = pro_biz(admin, wm, "No Consent Api")
    key, _ = new_key(biz)
    svc = setup_bookings(biz)
    assert call(key, "POST", "/enquiries", {"phone": "98765 41111", "name": "Enq"}).json()["enquiry_recorded"] is True
    assert call(key, "POST", "/bookings", {"phone": "98765 42222", "name": "Booker", "service": "Back pain assessment", "date": day(3), "time": "10:00"}).status_code == 201
    call(key, "POST", "/customers", {"phone": "98765 43333"})
    assert call(key, "POST", "/visits", {"phone": "98765 43333"}).json()["visit_recorded"] is True
    assert consents(biz) == []


# ===================================================================== the operations
def test_customers_are_upserted_and_visits_and_enquiries_are_recorded(wm, admin):
    biz = pro_biz(admin, wm, "Ops Biz")
    key, _ = new_key(biz)
    a = call(key, "POST", "/customers", {"phone": "98765 40010", "name": "Asha", "tags": ["vip"]}).json()
    b = call(key, "POST", "/customers", {"phone": "+91 98765 40010", "name": "Different"}).json()  # the same number, written another way
    assert a["created"] is True and b["created"] is False and a["id"] == b["id"] and b["name"] == "Asha"
    assert call(key, "POST", "/customers", {"phone": "12"}).status_code == 422 and call(key, "POST", "/customers", {"phone": "not a number!!"}).status_code in (422,)
    v = call(key, "POST", "/visits", {"phone": "98765 40010", "visited_at": (utcnow() - timedelta(days=2)).isoformat()}).json()
    assert v["visit_recorded"] is True and v["review_request"] == {"scheduled": False, "reason": "automation_off"}
    for bad in ((utcnow() + timedelta(days=2)).isoformat(), (utcnow() - timedelta(days=90)).isoformat(), "yesterday"):
        assert call(key, "POST", "/visits", {"phone": "98765 40010", "visited_at": bad}).status_code == 422, bad
    assert owner_query("SELECT last_visit_at IS NOT NULL FROM whatsapp_contacts WHERE id = :i", i=a["id"])[0][0] is True
    e = call(key, "POST", "/enquiries", {"phone": "98765 40011", "name": "Meena"}).json()
    assert e["created"] is True and owner_query("SELECT last_enquiry_at IS NOT NULL FROM whatsapp_contacts WHERE id = :i", i=e["id"])[0][0] is True
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.api_customer'", t=biz.tenant_id)[0][0] >= 2


def test_a_visit_through_the_api_feeds_the_review_request_helper(wm, admin):
    biz = pro_biz(admin, wm, "Review Api")
    key, _ = new_key(biz)
    assert biz.put("/whatsapp/automations/review_followup", json={"status": "on"}).status_code == 200
    call(key, "POST", "/customers", {"phone": "98765 40020", "consent": {"purposes": ["utility"], "agreed": True, "evidence": "Asked at the counter and wrote it in the register"}})
    assert call(key, "POST", "/visits", {"phone": "98765 40020"}).json()["review_request"]["scheduled"] is True


def test_bookings_through_the_api_use_the_same_server_rules(wm, admin):
    biz = pro_biz(admin, wm, "Api Booking")
    key, _ = new_key(biz)
    body = {"phone": "98765 40030", "name": "Ravi", "service": "Back pain assessment", "date": day(4), "time": "10:00"}
    assert call(key, "POST", "/bookings", body).json()["detail"]["code"] == "not_bookable"  # bookings are not set up yet
    svc = setup_bookings(biz)
    ok = call(key, "POST", "/bookings", body, idem="book-0001")
    assert ok.status_code == 201 and ok.json()["source"] == "api" and ok.json()["service"] == "Back pain assessment"
    assert call(key, "POST", "/bookings", body, idem="book-0001").json()["id"] == ok.json()["id"]  # replay: the same booking
    assert call(key, "POST", "/bookings", {**body, "phone": "98765 40031"}).json()["detail"]["code"] == "slot_taken"
    assert call(key, "POST", "/bookings", {**body, "service": svc["id"], "time": "13:00", "phone": "98765 40032"}).status_code == 201  # a service can be named by id
    assert call(key, "POST", "/bookings", {**body, "service": "Nonexistent", "time": "15:00"}).json()["detail"]["code"] == "service_not_found"
    assert call(key, "POST", "/bookings", {**body, "time": "03:00"}).json()["detail"]["code"] == "outside_hours"
    assert owner_query("SELECT count(*) FROM whatsapp_bookings WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 2


def test_one_business_key_never_reaches_another_business(wm, admin):
    a = pro_biz(admin, wm, "Iso Api A")
    b = pro_biz(admin, wm, "Iso Api B", fresh=True)
    ka, rowa = new_key(a)
    kb, _ = new_key(b)
    sa, sb = setup_bookings(a), setup_bookings(b)
    call(ka, "POST", "/customers", {"phone": "98765 40040", "name": "In A"})
    assert call(kb, "POST", "/visits", {"phone": "98765 40040"}).status_code == 404  # B has no such customer: A's customer is not visible to B's key
    assert call(kb, "POST", "/customers", {"phone": "98765 40040", "name": "In B"}).json()["created"] is True  # a separate customer in B
    assert call(kb, "POST", "/bookings", {"phone": "98765 40041", "service": sa["id"], "date": day(3), "time": "10:00"}).json()["detail"]["code"] == "service_not_found"  # A's service id
    assert b.post(f"/whatsapp/integrations/keys/{rowa['id']}/revoke").status_code == 404  # B cannot revoke A's key
    assert call(ka, "GET", "/me").status_code == 200
    for table in ("whatsapp_api_keys", "whatsapp_api_requests", "whatsapp_webhook_endpoints", "whatsapp_webhook_deliveries"):
        assert owner_query("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :n", n=table)[0] == (True, True), table
    assert owner_query("SELECT count(*) FROM whatsapp_contacts WHERE tenant_id = :t", t=b.tenant_id)[0][0] == 1


# ===================================================================== outbound webhooks: endpoints and the address rules
def test_an_endpoint_secret_is_shown_once_and_stored_encrypted(wm, admin, net):
    biz = pro_biz(admin, wm, "Secret Biz")
    secret, row = new_hook(biz)
    assert secret.startswith("whsec_") and row["secret_hint"] == secret[-4:] and "secret_enc" not in row
    enc = owner_query("SELECT secret_enc FROM whatsapp_webhook_endpoints WHERE tenant_id = :t", t=biz.tenant_id)[0][0]
    assert enc != secret and get_cipher().decrypt(enc) == secret
    assert secret not in json.dumps(biz.get("/whatsapp/integrations").json())
    rotated = biz.patch(f"/whatsapp/integrations/endpoints/{row['id']}", json={"rotate_secret": True}).json()
    assert rotated["secret"] != secret and get_cipher().decrypt(owner_query("SELECT secret_enc FROM whatsapp_webhook_endpoints WHERE tenant_id = :t", t=biz.tenant_id)[0][0]) == rotated["secret"]
    assert biz.delete(f"/whatsapp/integrations/endpoints/{row['id']}").status_code == 204


@pytest.mark.parametrize("url", ["http://hooks.example.com/x", "ftp://hooks.example.com/x", "https://user:pass@hooks.example.com/x", "https://hooks.example.com:22/x", "https://hooks.example.com:99999/x", "https://localhost/x",
                                 "https://127.0.0.1/x", "https://10.0.0.5/x", "https://192.168.1.1/x", "https://169.254.169.254/latest/meta-data", "https://[::1]/x", "https://[::ffff:10.0.0.1]/x",
                                 "https://100.64.0.1/x", "https://service.internal/x", "https://printer.local/x", "https://nope.example.com/x", "https:///x", "not a url", "https://hooks.example.com/" + "a" * 600])
def test_an_endpoint_that_could_reach_something_private_is_refused(wm, admin, net, url):
    biz = pro_biz(admin, wm, "Ssrf Biz")
    net.dns.update({"service.internal": "10.1.1.1", "printer.local": "10.1.1.2"})
    r = biz.post("/whatsapp/integrations/endpoints", json={"url": url, "events": ["booking.created"]})
    assert r.status_code == 422, (url, r.text)
    assert owner_query("SELECT count(*) FROM whatsapp_webhook_endpoints WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0


def test_a_name_that_resolves_to_any_private_address_is_refused_even_if_others_are_public(wm, admin, net):
    biz = pro_biz(admin, wm, "Dns Biz")
    net.dns["sneaky.example.com"] = "10.9.9.9"
    assert biz.post("/whatsapp/integrations/endpoints", json={"url": "https://sneaky.example.com/x", "events": ["booking.created"]}).json()["detail"]["code"] == "address_not_allowed"
    orig = net.resolve
    net.resolve = lambda host, port, type=None: orig("hooks.example.com", port) + [(2, 1, 6, "", ("10.0.0.1", port))]  # one public answer, one private
    import app.services.whatsapp.integrations as mod
    mod._resolve = net.resolve
    assert biz.post("/whatsapp/integrations/endpoints", json={"url": "https://mixed.example.com/x", "events": ["booking.created"]}).json()["detail"]["code"] == "address_not_allowed"


def test_endpoint_events_are_validated_limited_and_isolated(wm, admin, net):
    biz = pro_biz(admin, wm, "Endpoint Rules")
    other = pro_biz(admin, wm, "Endpoint Other", fresh=True)
    for bad in ([], ["everything"], ["booking.created", "nope"]):
        assert biz.post("/whatsapp/integrations/endpoints", json={"url": HOOK_URL, "events": bad}).status_code == 422
    ids = [new_hook(biz, ["booking.created"])[1]["id"] for _ in range(5)]
    assert biz.post("/whatsapp/integrations/endpoints", json={"url": HOOK_URL, "events": ["booking.created"]}).json()["detail"]["code"] == "too_many"
    assert other.patch(f"/whatsapp/integrations/endpoints/{ids[0]}", json={"active": False}).status_code == 404
    assert other.delete(f"/whatsapp/integrations/endpoints/{ids[0]}").status_code == 404 and other.post(f"/whatsapp/integrations/endpoints/{ids[0]}/test").status_code == 404
    assert biz.patch(f"/whatsapp/integrations/endpoints/{ids[0]}", json={"url": "http://hooks.example.com/x"}).status_code == 422


# ===================================================================== outbound webhooks: events, signing, delivery
def verify(call_, secret):
    sig = call_["headers"]["X-FlowQR-Signature"]
    t, v1 = (p.split("=", 1)[1] for p in sig.split(","))
    return hmac.compare_digest(v1, hmac.new(secret.encode(), f"{t}.".encode() + call_["body"], hashlib.sha256).hexdigest())


def test_a_booking_event_is_queued_signed_and_delivered_without_any_message_text(wm, admin, net):
    biz = pro_biz(admin, wm, "Event Biz")
    secret, ep = new_hook(biz)
    svc = setup_bookings(biz)
    r = biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3), "time": "10:00", "phone": "98765 40050", "name": "Asha"})
    assert r.status_code == 201
    assert deliveries(biz) == [("booking.created", "pending", 0, None, None)]
    assert drain(biz) == {"delivered": 1, "retry": 0, "dead": 0}
    (c,) = net.calls
    assert c["url"] == "https://93.184.216.34/flowqr" and c["headers"]["Host"] == "hooks.example.com" and c["extensions"] == {"sni_hostname": "hooks.example.com"}  # the connection goes to the address that was just checked, under the real name
    assert c["follow_redirects"] is False and verify(c, secret)
    h = c["headers"]
    assert h["X-FlowQR-Event"] == "booking.created" and h["Content-Type"] == "application/json" and h["X-FlowQR-Delivery"] and h["User-Agent"].startswith("FlowQR")
    ev = json.loads(c["body"])
    assert set(ev) == {"id", "type", "api_version", "created_at", "business_id", "data"} and ev["type"] == "booking.created" and ev["business_id"] == biz.tenant_id and ev["api_version"] == integrations.API_VERSION
    assert ev["data"]["change"] == "created" and ev["data"]["booking"]["service"] == "Back pain assessment" and ev["data"]["customer_phone"] == "+919876540050"
    assert "text" not in json.dumps(ev).lower().replace("context", "")  # never message text
    assert deliveries(biz) == [("booking.created", "delivered", 1, 200, None)]
    bid = r.json()["id"]
    biz.post(f"/whatsapp/bookings/{bid}/reschedule", json={"date": day(3), "time": "12:00"})
    biz.post(f"/whatsapp/bookings/{bid}/cancel", json={})
    drain(biz)
    assert [json.loads(x["body"])["data"]["change"] for x in net.calls[1:]] == ["rescheduled", "cancelled"] and {x["headers"]["X-FlowQR-Event"] for x in net.calls[1:]} == {"booking.updated"}


def test_status_stop_and_new_conversation_events(wm, admin, net):
    biz = pro_biz(admin, wm, "Event Types")
    secret, _ = new_hook(biz)
    phone = phone_digits()
    inbound(biz, "hello there", phone=phone)  # a customer writes for the first time
    stopper = phone_digits()
    add_contact(biz, "+" + stopper, name="Stopper", marketing=True, **OWNER)
    inbound(biz, "STOP", phone=stopper)
    c = add_contact(biz, "98765 60081", utility=True, **OWNER)
    assert send(biz, c["id"]).ok
    wamid = messages(biz.tenant_id)[0][3]
    raw = payload(statuses=[{"id": wamid, "status": "delivered", "timestamp": "1700000001"}])
    post_wh(raw)
    process(base.event_id_for(raw))
    types = [d[0] for d in deliveries(biz)]
    assert "conversation.created" in types and "contact.opted_out" in types and "message.status" in types
    drain(biz)
    by = {json.loads(x["body"])["type"]: json.loads(x["body"]) for x in net.calls}
    assert by["message.status"]["data"]["status"] == "delivered" and by["message.status"]["data"]["kind"] == "template" and "customer_phone" in by["message.status"]["data"]
    assert by["conversation.created"]["data"]["customer_phone"] == "+" + phone and by["contact.opted_out"]["data"]["customer_phone"] == "+" + stopper
    assert all(verify(x, secret) for x in net.calls)
    assert "hello there" not in " ".join(x["body"].decode() for x in net.calls)  # the customer's words are never in an event


def test_only_subscribed_active_pro_endpoints_get_events(wm, admin, net, monkeypatch):
    biz = pro_biz(admin, wm, "Subscribe Biz")
    _, wants = new_hook(biz, ["booking.created"])
    _, doesnt = new_hook(biz, ["contact.opted_out"])
    _, paused = new_hook(biz, ["booking.created"])
    biz.patch(f"/whatsapp/integrations/endpoints/{paused['id']}", json={"active": False})
    svc = setup_bookings(biz)
    biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3), "time": "10:00", "phone": "98765 40060"})
    assert owner_query("SELECT endpoint_id::text FROM whatsapp_webhook_deliveries WHERE tenant_id = :t", t=biz.tenant_id) == [(wants["id"],)]
    monkeypatch.setattr(settings, "whatsapp_integrations_enabled", False)
    biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3), "time": "13:00", "phone": "98765 40061"})
    assert len(deliveries(biz)) == 1  # platform off: nothing is queued
    monkeypatch.setattr(settings, "whatsapp_integrations_enabled", True)
    grant_addon(admin, biz, "whatsapp_growth")
    biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3), "time": "15:00", "phone": "98765 40062"})
    assert len(deliveries(biz)) == 1  # off Pro: nothing is queued


def test_a_failing_receiver_is_retried_with_backoff_then_given_up_on_and_the_endpoint_is_switched_off(wm, admin, net):
    biz = pro_biz(admin, wm, "Retry Biz")
    _, ep = new_hook(biz, ["booking.created"])
    svc = setup_bookings(biz)
    biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3), "time": "10:00", "phone": "98765 40070"})
    net.answers = [500]
    now = utcnow()
    expected = integrations.BACKOFF
    for i, wait in enumerate(expected):
        assert drain(biz, now) == {"delivered": 0, "retry": 1, "dead": 0}, i
        d = owner_query("SELECT attempts, status, last_status_code, last_error, next_attempt_at FROM whatsapp_webhook_deliveries WHERE tenant_id = :t", t=biz.tenant_id)[0]
        assert d[0] == i + 1 and d[1] == "pending" and d[2] == 500 and d[3] == "receiver answered 500" and abs((d[4] - now).total_seconds() - wait) < 5
        assert drain(biz, now + timedelta(seconds=wait - 10)) == {"delivered": 0, "retry": 0, "dead": 0}  # not due yet
        now = now + timedelta(seconds=wait + 1)
    assert drain(biz, now) == {"delivered": 0, "retry": 0, "dead": 1}  # the sixth failure gives up
    assert deliveries(biz)[0][1] == "dead" and len(net.calls) == 6
    assert owner_query("SELECT failure_streak FROM whatsapp_webhook_endpoints WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 1
    # a person can ask for another try; a success resets the failure count
    did = biz.get("/whatsapp/integrations/deliveries").json()["items"][0]["id"]
    assert biz.post(f"/whatsapp/integrations/deliveries/{did}/retry").json()["status"] == "pending"
    net.answers = [200]
    assert drain(biz, now) == {"delivered": 1, "retry": 0, "dead": 0}
    assert biz.post(f"/whatsapp/integrations/deliveries/{did}/retry").json()["detail"]["code"] == "not_dead"
    assert owner_query("SELECT failure_streak FROM whatsapp_webhook_endpoints WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0


def test_network_errors_redirects_and_gone_are_handled(wm, admin, net):
    biz = pro_biz(admin, wm, "Failure Kinds")
    _, ep = new_hook(biz, ["booking.created"])
    svc = setup_bookings(biz)
    book = lambda t, p: biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3), "time": t, "phone": p})
    book("10:00", "98765 40080")
    net.answers = [httpx.ConnectTimeout("slow")]
    assert drain(biz) == {"delivered": 0, "retry": 1, "dead": 0} and deliveries(biz)[0][4] == "network error: ConnectTimeout"
    owner_exec("DELETE FROM whatsapp_webhook_deliveries WHERE tenant_id = :t", t=biz.tenant_id)
    book("12:00", "98765 40081")
    net.answers = [302]  # a redirect is not followed and counts as a failure
    drain(biz)
    assert net.calls[-1]["follow_redirects"] is False and deliveries(biz)[0][2:4] == (1, 302)
    owner_exec("DELETE FROM whatsapp_webhook_deliveries WHERE tenant_id = :t", t=biz.tenant_id)
    book("14:00", "98765 40082")
    net.answers = [410]
    assert drain(biz) == {"delivered": 0, "retry": 0, "dead": 1}
    e = owner_query("SELECT active, disabled_reason FROM whatsapp_webhook_endpoints WHERE tenant_id = :t", t=biz.tenant_id)[0]
    assert e[0] is False and "410" in e[1]


def test_ten_dead_deliveries_in_a_row_switch_the_endpoint_off(wm, admin, net):
    biz = pro_biz(admin, wm, "Streak Biz")
    _, ep = new_hook(biz, ["booking.created"])
    svc = setup_bookings(biz)
    net.answers = [500]
    for i in range(integrations.ENDPOINT_DISABLE_AFTER):
        biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3 + i // 6), "time": f"{9 + i % 6 * 1}:00", "phone": f"98765 4100{i}"})
        owner_exec("UPDATE whatsapp_webhook_deliveries SET attempts = :a WHERE tenant_id = :t AND status = 'pending'", a=integrations.MAX_ATTEMPTS - 1, t=biz.tenant_id)
        drain(biz)
    e = owner_query("SELECT active, failure_streak, disabled_reason FROM whatsapp_webhook_endpoints WHERE tenant_id = :t", t=biz.tenant_id)[0]
    assert e[0] is False and e[1] == integrations.ENDPOINT_DISABLE_AFTER and "too many" in e[2]


def test_the_address_is_checked_again_right_before_every_send(wm, admin, net):
    biz = pro_biz(admin, wm, "Rebind Biz")
    _, ep = new_hook(biz, ["booking.created"], url="https://other.example.com/hook")
    svc = setup_bookings(biz)
    biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3), "time": "10:00", "phone": "98765 40090"})
    net.dns["other.example.com"] = "10.0.0.7"  # the name now points somewhere private
    assert drain(biz) == {"delivered": 0, "retry": 1, "dead": 0} and net.calls == []
    assert deliveries(biz)[0][4] == "blocked: address_not_allowed"


def test_the_test_ping_goes_through_the_same_signed_path(wm, admin, net):
    biz = pro_biz(admin, wm, "Ping Biz")
    secret, ep = new_hook(biz, ["booking.created"])
    r = biz.post(f"/whatsapp/integrations/endpoints/{ep['id']}/test")
    assert r.status_code == 200 and r.json()["event_type"] == "ping" and r.json()["status"] == "delivered"
    (c,) = net.calls
    assert verify(c, secret) and json.loads(c["body"])["type"] == "ping" and c["headers"]["X-FlowQR-Event"] == "ping"
    net.answers = [503]
    assert biz.post(f"/whatsapp/integrations/endpoints/{ep['id']}/test").json()["status"] == "pending"


def test_the_signature_is_hmac_sha256_over_the_timestamp_and_the_exact_body():
    body = b'{"a":1}'
    assert integrations.sign("whsec_abc", 1700000000, body) == hmac.new(b"whsec_abc", b"1700000000." + body, hashlib.sha256).hexdigest()
    assert integrations.sign("whsec_abc", 1700000001, body) != integrations.sign("whsec_abc", 1700000000, body) and integrations.sign("whsec_abd", 1700000000, body) != integrations.sign("whsec_abc", 1700000000, body)


# ===================================================================== retention, export, deletion
def test_old_requests_and_finished_deliveries_are_purged_but_pending_ones_stay(wm, admin, net):
    biz = pro_biz(admin, wm, "Purge Integrations")
    key, _ = new_key(biz)
    new_hook(biz, ["booking.created"])
    call(key, "POST", "/customers", {"phone": "98765 40095"})
    svc = setup_bookings(biz)
    biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3), "time": "10:00", "phone": "98765 40096"})
    biz.post("/whatsapp/bookings", json={"service_id": svc["id"], "date": day(3), "time": "13:00", "phone": "98765 40097"})
    drain(biz)
    owner_exec("UPDATE whatsapp_webhook_deliveries SET created_at = now() - interval '20 days' WHERE tenant_id = :t", t=biz.tenant_id)
    owner_exec("UPDATE whatsapp_webhook_deliveries SET status = 'pending', next_attempt_at = now() + interval '1 day' WHERE id = (SELECT id FROM whatsapp_webhook_deliveries WHERE tenant_id = :t LIMIT 1)", t=biz.tenant_id)
    owner_exec("UPDATE whatsapp_api_requests SET created_at = now() - interval '3 days' WHERE tenant_id = :t", t=biz.tenant_id)
    db = system_session()
    try:
        out = integrations.purge(db)
        db.commit()
    finally:
        db.close()
    assert out["api_requests"] >= 1 and out["deliveries"] == 1 and len(deliveries(biz)) == 1 and deliveries(biz)[0][1] == "pending"


def test_export_covers_integrations_without_secrets_and_everything_goes_with_the_business(wm, admin, net):
    biz = pro_biz(admin, wm, "Export Integrations")
    key, _ = new_key(biz)
    secret, _ = new_hook(biz)
    call(key, "POST", "/customers", {"phone": "98765 40099"})
    z = zipfile.ZipFile(io.BytesIO(biz.get("/account/export").content))
    assert {"whatsapp_api_keys.json", "whatsapp_api_requests.json", "whatsapp_webhook_endpoints.json", "whatsapp_webhook_deliveries.json"} <= set(z.namelist())
    blob = b"".join(z.read(n) for n in z.namelist()).decode()
    assert hashlib.sha256(key.encode()).hexdigest() not in blob and key not in blob and secret not in blob and "key_hash" not in blob and "secret_enc" not in blob
    fks = owner_query("SELECT c.relname, con.confdeltype FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY (con.conkey) "
                      "WHERE con.contype = 'f' AND a.attname = 'tenant_id' AND c.relname IN ('whatsapp_api_keys', 'whatsapp_api_requests', 'whatsapp_webhook_endpoints', 'whatsapp_webhook_deliveries')")
    assert len(fks) == 4 and all(d == "c" for _, d in fks)


def test_migration_0059_shape():
    biz = make_business("Migration 59")
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] >= "0059"
    with pytest.raises(Exception):
        owner_exec("INSERT INTO whatsapp_api_keys (id, tenant_id, name, prefix, key_hash, rate_limit_per_min) VALUES (gen_random_uuid(), :t, 'x', 'fqk_', 'h', 5)", t=biz.tenant_id)
    for _ in range(2):  # the hash is unique
        try:
            owner_exec("INSERT INTO whatsapp_api_keys (id, tenant_id, name, prefix, key_hash) VALUES (gen_random_uuid(), :t, 'x', 'fqk_', 'same-hash')", t=biz.tenant_id)
        except Exception:
            break
    else:
        raise AssertionError("a duplicate key hash was accepted")
    with pytest.raises(Exception):
        owner_exec("INSERT INTO whatsapp_webhook_deliveries (id, tenant_id, endpoint_id, event_id, event_type, payload, status) VALUES (gen_random_uuid(), :t, gen_random_uuid(), gen_random_uuid(), 'x', '{}', 'weird')", t=biz.tenant_id)
    assert "api_integration" in owner_query("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_wa_consent_source'")[0][0]
