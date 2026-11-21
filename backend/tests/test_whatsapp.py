"""WhatsApp automation, Phase 1: the connection, the webhook, consent and the add-on. Everything runs against a mock of Meta's Graph API; no real number, account or message is involved.

Covers: switched off by default; admin and tenant authorisation; add-on gating; Embedded Signup (state single use and expiry, code exchange, ownership check, encrypted token that never leaves the
server, number-in-use, webhook subscription, health check, disconnect); webhook verification and signatures; sanitised, de-duplicated, asynchronous processing; tenant resolution only through the
verified phone_number_id; delivery status ordering; opt-out; consent (attestation, wording, suppression, customer-only lifting); CSV import; the send gate; export, deletion, row-level security."""
import hashlib
import hmac
import io
import json
import uuid
import zipfile
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import config_problems, settings
from app.core.db import SessionLocal, set_rls_context, system_session
from app.core.security import get_cipher
from app.main import app
from app.models import Tenant
from app.models.base import utcnow
from app.services import account as account_svc
from app.services.whatsapp import WaError, addons, connection, consent, gate, rules
from app.services.whatsapp import webhook as wh
from app.services.whatsapp.meta import MetaClient, MetaError, redact, set_meta_client
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_config_guard import good

APP_SECRET = "s3cr3t-app-secret-for-tests-0123456789"
VERIFY = "verify-token-for-tests-0123456789"
TOKEN = "EAAGtestTOKEN1234567890abcdefXYZ"
WABA = PHONE = ""  # fresh, unique Meta ids for every test (a number belongs to one business at a time and the test database persists): set by the `wa` fixture


def uid(prefix: int = 1) -> str:
    return f"{prefix}{uuid.uuid4().int % 10**14:014d}"
REASON = "Paid 299 by UPI on 12 Nov"


class MockMeta:
    """Stands in for graph.facebook.com. `fail` names the calls that should fail: exchange, debug, phone, subscribe, unsubscribe (value = HTTP status)."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.fail: dict[str, int] = {}
        self.valid, self.expires, self.granted = True, 0, [WABA]
        self.waba = self.phone_id = None
        self.phone = {"display_phone_number": "+1 555 010 0100", "verified_name": "Asha Clinic", "quality_rating": "GREEN"}

    def handler(self, req: httpx.Request) -> httpx.Response:
        path, m = req.url.path, req.method
        op = ("exchange" if path.endswith("oauth/access_token") else "debug" if path.endswith("debug_token") else "subscribe" if m == "POST" and path.endswith("subscribed_apps")
              else "unsubscribe" if m == "DELETE" and path.endswith("subscribed_apps") else "phone")
        self.calls.append((op, path))
        if op in self.fail:
            return httpx.Response(self.fail[op], json={"error": {"message": f"boom {TOKEN}", "code": 190}})
        if op == "exchange":
            return httpx.Response(200, json={"access_token": TOKEN})
        if op == "debug":
            return httpx.Response(200, json={"data": {"is_valid": self.valid, "expires_at": self.expires, "granular_scopes": [{"scope": "whatsapp_business_management", "target_ids": self.granted}]}})
        if op in ("subscribe", "unsubscribe"):
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json=self.phone)

    def n(self, op: str) -> int:
        return sum(1 for o, _ in self.calls if o == op)


@pytest.fixture()
def wa(monkeypatch):
    for k, v in dict(whatsapp_enabled=True, whatsapp_signup_enabled=True, whatsapp_webhook_enabled=True, whatsapp_require_addon=True, meta_app_id="123456789012345", meta_app_secret=APP_SECRET,
                     whatsapp_embedded_signup_config_id="cfg-777", whatsapp_webhook_verify_token=VERIFY, whatsapp_sending_enabled=False, whatsapp_emergency_stop=False).items():
        monkeypatch.setattr(settings, k, v)
    global WABA, PHONE
    WABA, PHONE = uid(1), uid(2)
    m = MockMeta()
    m.waba, m.phone_id = WABA, PHONE
    set_meta_client(MetaClient(httpx.Client(transport=httpx.MockTransport(m.handler))))
    queued: list[uuid.UUID] = []
    monkeypatch.setattr(wh, "enqueue", lambda eid: queued.append(eid))
    m.queued = queued
    yield m
    set_meta_client(None)


REAL_ENQUEUE = wh.enqueue


def grant_addon(admin, biz, key="whatsapp_starter"):
    r = admin.put(f"/admin/tenants/{biz.tenant_id}/whatsapp-addon", json={"addon_key": key, "reason": REASON})
    assert r.status_code == 200, r.text
    return r.json()


def connect(biz, admin, *, addon=True, code="code-123", waba=None, phone=None):
    if addon:
        grant_addon(admin, biz)
    st = biz.post("/whatsapp/connect/start")
    assert st.status_code == 200, st.text
    st = st.json()
    return biz.post("/whatsapp/connect/complete", json={"state": st["state"], "code": code, "waba_id": waba or WABA, "phone_number_id": phone or PHONE}), st


def connected(admin, name="Asha Clinic"):
    biz = make_business(name)
    r, _ = connect(biz, admin)
    assert r.status_code == 200, r.text
    return biz


def sign(raw: bytes, secret=APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def payload(phone_id=None, *, statuses=(), messages=(), field="messages", waba=None, event=None, extra=None):
    phone_id, waba = phone_id or PHONE, waba or WABA
    value = {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "15550100100", "phone_number_id": phone_id}}
    if statuses:
        value["statuses"] = list(statuses)
    if messages:
        value["messages"] = list(messages)
        value["contacts"] = [{"profile": {"name": "Secret Customer Name"}, "wa_id": "919876543210"}]
    if event:
        value["event"] = event
    body = {"object": "whatsapp_business_account", "entry": [{"id": waba, "changes": [{"field": field, "value": value}]}]}
    body.update(extra or {})
    return json.dumps(body).encode()


def post_wh(raw: bytes, sig="auto", content_type="application/json"):
    h = {"Content-Type": content_type}
    if sig == "auto":
        h["X-Hub-Signature-256"] = sign(raw)
    elif sig:
        h["X-Hub-Signature-256"] = sig
    with TestClient(app, base_url="http://testserver") as c:
        return c.post("/api/v1/webhooks/whatsapp", content=raw, headers=h)


def process(event_id):
    db = system_session()
    try:
        out = wh.process_event(db, event_id)
        db.commit()
        return out
    finally:
        db.close()


def event_id_for(raw: bytes):
    return owner_query("SELECT id FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=hashlib.sha256(raw).hexdigest())[0][0]


def add_message(tenant_id, wamid, status="sent", phone_id=None):
    phone_id = phone_id or PHONE
    owner_exec("INSERT INTO whatsapp_messages (id, tenant_id, phone_number_id, meta_message_id, direction, delivery_status, created_at, updated_at) "
               "VALUES (gen_random_uuid(), :t, :p, :w, 'outbound', :s, now(), now())", t=tenant_id, p=phone_id, w=wamid, s=status)


def msg_status(wamid):
    return owner_query("SELECT delivery_status, error_code, delivered_at IS NOT NULL, read_at IS NOT NULL FROM whatsapp_messages WHERE meta_message_id = :w", w=wamid)[0]


def svc_db(tenant_id):
    db = SessionLocal()
    set_rls_context(db, tenant_id=uuid.UUID(str(tenant_id)))
    return db


def add_contact(biz, phone="98765 43210", **kw):
    body = {"phone": phone, "name": "Asha", **kw}
    r = biz.post("/whatsapp/contacts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


OWNER = {"attested": True, "evidence": "Asked at the counter on 12 Nov and wrote it in the register"}


# ===================================================================== off by default, authorisation, add-on
def test_everything_is_off_by_default_and_the_rest_of_the_app_is_unaffected():
    assert settings.whatsapp_enabled is False and settings.whatsapp_sending_enabled is False and settings.whatsapp_emergency_stop is False
    biz = make_business("Off Clinic")
    for method, url in (("GET", "/whatsapp/status"), ("GET", "/whatsapp/contacts"), ("POST", "/whatsapp/connect/start"), ("GET", "/whatsapp/automations"), ("GET", "/whatsapp/templates")):
        r = biz.request(method, url)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "whatsapp_disabled", url
    with TestClient(app, base_url="http://testserver") as c:
        assert c.get("/api/v1/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "x"}).status_code == 404
        assert c.post("/api/v1/webhooks/whatsapp", content=b"{}").status_code == 404
    assert biz.get("/auth/me").json()["integrations"]["whatsapp_enabled"] is False
    assert biz.get("/tenant").status_code == 200


def test_the_housekeeping_job_does_nothing_while_switched_off():
    from app.workers.tasks import whatsapp_housekeeping, whatsapp_process_event
    assert whatsapp_housekeeping.run() == {"enabled": False}
    assert whatsapp_process_event.run(str(uuid.uuid4())) == {"enabled": False}


def test_a_business_cannot_connect_without_the_add_on_and_status_says_why(wa, admin):
    biz = make_business("No Addon")
    s = biz.get("/whatsapp/status").json()
    assert s["addon"] is None and s["can_connect"] is False and s["addon_required"] is True and s["messaging"]["enabled"] is False
    r = biz.post("/whatsapp/connect/start")
    assert r.status_code == 402 and r.json()["detail"]["code"] == "addon_required"
    grant_addon(admin, biz)
    s = biz.get("/whatsapp/status").json()
    assert s["can_connect"] is True and s["addon"]["automation_limit"] == 3 and s["addon"]["key"] == "whatsapp_starter"


def test_signup_reports_not_configured_when_meta_credentials_are_missing(wa, admin, monkeypatch):
    biz = make_business("Unconfigured")
    grant_addon(admin, biz)
    monkeypatch.setattr(settings, "meta_app_id", "")
    r = biz.post("/whatsapp/connect/start")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "not_configured"
    assert biz.get("/whatsapp/status").json()["signup_available"] is False


def test_the_addon_is_recorded_by_an_administrator_with_a_reason_and_audited(wa, admin):
    biz = make_business("Addon Clinic")
    assert biz.put(f"/admin/tenants/{biz.tenant_id}/whatsapp-addon", json={"addon_key": "whatsapp_growth", "reason": REASON}).status_code == 403  # an owner cannot grant themselves one
    assert admin.put(f"/admin/tenants/{biz.tenant_id}/whatsapp-addon", json={"addon_key": "whatsapp_growth", "reason": "x"}).status_code == 422
    assert admin.put(f"/admin/tenants/{biz.tenant_id}/whatsapp-addon", json={"addon_key": "whatsapp_gold", "reason": REASON}).status_code == 422
    grant_addon(admin, biz, "whatsapp_growth")
    grant_addon(admin, biz, "whatsapp_pro")  # moving up ends the previous tier: never two active
    rows = owner_query("SELECT addon_key, status FROM tenant_addons WHERE tenant_id = :t ORDER BY created_at", t=biz.tenant_id)
    assert rows == [("whatsapp_growth", "ended"), ("whatsapp_pro", "active")]
    assert biz.get("/whatsapp/status").json()["addon"]["automation_limit"] == 15
    admin.put(f"/admin/tenants/{biz.tenant_id}/whatsapp-addon", json={"addon_key": None, "reason": "Cancelled by the owner"})
    assert biz.get("/whatsapp/status").json()["addon"] is None
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'admin.whatsapp_addon'", t=biz.tenant_id)[0][0] == 3
    assert {k: v["automation_limit"] for k, v in rules.ADDON_TIERS.items()} == {"whatsapp_starter": 3, "whatsapp_growth": 8, "whatsapp_pro": 15}
    assert {k: v["price_inr_month"] for k, v in rules.ADDON_TIERS.items()} == {"whatsapp_starter": 299, "whatsapp_growth": 499, "whatsapp_pro": 799}


def test_the_addon_summary_for_staff(wa, admin):
    biz = make_business("Summary Clinic")
    s = admin.get(f"/admin/tenants/{biz.tenant_id}/whatsapp").json()
    assert s["enabled"] is True and s["addon"] is None and s["connection"] is None and len(s["tiers"]) == 3
    assert biz.get(f"/admin/tenants/{biz.tenant_id}/whatsapp").status_code == 403


# ===================================================================== Embedded Signup
def test_signup_stores_the_token_encrypted_and_never_returns_it(wa, admin):
    biz = make_business("Signup Clinic")
    r, st = connect(biz, admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "connected" and body["display_phone_number"] == "+1 555 010 0100" and body["webhook_status"] == "subscribed" and body["is_test_number"] is True
    for forbidden in (TOKEN, st["state"], "access_token", "state_hash"):
        assert forbidden not in r.text and forbidden not in json.dumps(biz.get("/whatsapp/status").json())
    stored = owner_query("SELECT access_token_enc, state_hash, waba_id, phone_number_id FROM whatsapp_connections WHERE tenant_id = :t", t=biz.tenant_id)[0]
    assert stored[0] and TOKEN not in stored[0] and get_cipher().decrypt(stored[0]) == TOKEN
    assert stored[1] is None and stored[2] == WABA and stored[3] == PHONE
    assert wa.n("subscribe") == 1
    audit = " ".join(str(x) for x in owner_query("SELECT metadata FROM audit_logs WHERE tenant_id = :t AND action LIKE 'whatsapp.%'", t=biz.tenant_id))
    assert TOKEN not in audit and st["state"] not in audit
    start = owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.connect'", t=biz.tenant_id)[0][0]
    assert start == 1


def test_the_start_response_has_only_public_values(wa, admin):
    biz = make_business("Public Values")
    grant_addon(admin, biz)
    st = biz.post("/whatsapp/connect/start").json()
    assert set(st) == {"app_id", "config_id", "graph_version", "state", "expires_at"}
    assert st["app_id"] == "123456789012345" and st["config_id"] == "cfg-777" and APP_SECRET not in json.dumps(st)
    assert len(st["state"]) >= 32
    stored = owner_query("SELECT state_hash FROM whatsapp_connections WHERE tenant_id = :t", t=biz.tenant_id)[0][0]
    assert stored == hashlib.sha256(st["state"].encode()).hexdigest() and st["state"] not in stored  # only the hash is stored


def test_a_state_is_single_use_and_a_new_start_replaces_the_old_one(wa, admin):
    biz = make_business("State Clinic")
    grant_addon(admin, biz)
    old = biz.post("/whatsapp/connect/start").json()["state"]
    new = biz.post("/whatsapp/connect/start").json()["state"]
    assert old != new
    body = lambda s: {"state": s, "code": "code-123", "waba_id": WABA, "phone_number_id": PHONE}  # noqa: E731
    assert biz.post("/whatsapp/connect/complete", json=body(old)).status_code == 400  # replaced
    assert biz.post("/whatsapp/connect/complete", json=body(new)).status_code == 200
    again = biz.post("/whatsapp/connect/complete", json=body(new))
    assert again.status_code == 400 and again.json()["detail"]["code"] == "invalid_state"  # replay
    assert wa.n("exchange") == 1


def test_a_state_expires(wa, admin):
    biz = make_business("Expiry Clinic")
    grant_addon(admin, biz)
    st = biz.post("/whatsapp/connect/start").json()
    owner_exec("UPDATE whatsapp_connections SET state_expires_at = now() - interval '1 minute' WHERE tenant_id = :t", t=biz.tenant_id)
    r = biz.post("/whatsapp/connect/complete", json={"state": st["state"], "code": "c" * 10, "waba_id": WABA, "phone_number_id": PHONE})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_state" and wa.n("exchange") == 0


def test_another_business_cannot_use_a_state_it_was_not_given(wa, admin):
    a, b = make_business("State A"), make_business("State B")
    grant_addon(admin, a)
    grant_addon(admin, b)
    sa = a.post("/whatsapp/connect/start").json()["state"]
    r = b.post("/whatsapp/connect/complete", json={"state": sa, "code": "c" * 10, "waba_id": WABA, "phone_number_id": PHONE})
    assert r.status_code == 400 and wa.n("exchange") == 0
    assert connection.live_connection  # a's attempt is untouched
    assert owner_query("SELECT status FROM whatsapp_connections WHERE tenant_id = :t", t=a.tenant_id)[0][0] == "pending"


def test_the_ids_from_the_browser_are_not_trusted_meta_must_confirm_them(wa, admin):
    biz = make_business("Spoof Clinic")
    wa.granted = [uid(9)]  # the token was granted a DIFFERENT account than the browser claims
    r, _ = connect(biz, admin)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "account_mismatch"
    assert owner_query("SELECT status, access_token_enc IS NULL FROM whatsapp_connections WHERE tenant_id = :t", t=biz.tenant_id)[0] == ("pending", True)
    assert wa.n("subscribe") == 0


def test_meta_failures_are_reported_plainly_and_store_nothing(wa, admin):
    for op, status, expect in (("exchange", 400, 400), ("debug", 400, 400), ("phone", 400, 400), ("exchange", 503, 502)):
        wa.fail = {op: status}
        biz = make_business(f"Fail {op} {status}")
        r, _ = connect(biz, admin)
        assert r.status_code == expect and r.json()["detail"]["code"] == "meta_error", (op, status, r.text)
        assert TOKEN not in r.text
        assert owner_query("SELECT status, access_token_enc IS NULL FROM whatsapp_connections WHERE tenant_id = :t", t=biz.tenant_id)[0] == ("pending", True)
    wa.fail = {}
    wa.valid = False
    biz = make_business("Invalid token")
    r, _ = connect(biz, admin)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "token_invalid"


def test_a_failed_webhook_subscription_connects_but_asks_the_owner_to_act(wa, admin):
    wa.fail = {"subscribe": 400}
    biz = make_business("No Hooks")
    r, _ = connect(biz, admin)
    assert r.status_code == 200 and r.json()["status"] == "needs_attention" and r.json()["webhook_status"] == "failed" and "delivery updates" in r.json()["attention_reason"]
    wa.fail = {}
    c = biz.post("/whatsapp/connection/check")
    assert c.status_code == 200 and c.json()["status"] == "connected" and c.json()["webhook_status"] == "subscribed" and c.json()["attention_reason"] is None


def test_a_number_can_belong_to_only_one_business(wa, admin):
    a = connected(admin, "Number A")
    b = make_business("Number B")
    r, _ = connect(b, admin)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "number_in_use"
    assert owner_query("SELECT count(*) FROM whatsapp_connections WHERE phone_number_id = :p AND status <> 'disconnected'", p=PHONE)[0][0] == 1
    assert a.get("/whatsapp/status").json()["connection"]["status"] == "connected"


def test_one_live_connection_per_business(wa, admin):
    biz = connected(admin, "One Only")
    r = biz.post("/whatsapp/connect/start")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_connected"


def test_the_health_check_notices_a_revoked_expired_or_expiring_token(wa, admin):
    biz = connected(admin, "Health Clinic")
    wa.valid = False
    assert biz.post("/whatsapp/connection/check").json()["status"] == "needs_attention"
    wa.valid = True
    assert biz.post("/whatsapp/connection/check").json()["status"] == "connected"
    wa.expires = int((utcnow() + timedelta(days=3)).timestamp())
    r = biz.post("/whatsapp/connection/check").json()
    assert r["status"] == "connected" and r["token_state"] == "expiring" and "expires soon" in r["attention_reason"]
    wa.expires = int((utcnow() - timedelta(days=1)).timestamp())
    r = biz.post("/whatsapp/connection/check").json()
    assert r["status"] == "needs_attention" and r["token_state"] == "expired"
    wa.fail = {"debug": 503}
    assert biz.post("/whatsapp/connection/check").status_code == 502  # Meta unreachable: report it, do not guess


def test_the_daily_check_rechecks_old_connections(wa, admin):
    biz = connected(admin, "Daily Clinic")
    owner_exec("UPDATE whatsapp_connections SET token_checked_at = now() - interval '2 days' WHERE tenant_id = :t", t=biz.tenant_id)
    wa.valid = False
    db = system_session()
    try:
        out = connection.check_all(db)
        db.commit()
    finally:
        db.close()
    assert out["checked"] >= 1 and out["needs_attention"] >= 1
    assert owner_query("SELECT status FROM whatsapp_connections WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == "needs_attention"


def test_disconnect_wipes_the_token_unsubscribes_and_keeps_the_customers(wa, admin):
    biz = connected(admin, "Leave Clinic")
    add_contact(biz, marketing=True, **OWNER)
    r = biz.post("/whatsapp/connection/disconnect")
    assert r.status_code == 200 and r.json()["status"] == "disconnected"
    assert wa.n("unsubscribe") == 1
    row = owner_query("SELECT access_token_enc, status, disconnected_at IS NOT NULL FROM whatsapp_connections WHERE tenant_id = :t", t=biz.tenant_id)[0]
    assert row == (None, "disconnected", True)
    assert biz.get("/whatsapp/contacts").json()["total"] == 1  # their people and consents are theirs and stay
    r2, _ = connect(biz, admin, addon=False)  # and they can connect again (a number freed by a disconnect is available)
    assert r2.status_code == 200
    assert biz.post("/whatsapp/connection/disconnect").status_code == 200 and biz.post("/whatsapp/connection/disconnect").status_code == 404


def test_a_failed_unsubscribe_never_keeps_a_business_connected(wa, admin):
    biz = connected(admin, "Stuck Clinic")
    wa.fail = {"unsubscribe": 500}
    assert biz.post("/whatsapp/connection/disconnect").status_code == 200
    assert owner_query("SELECT status FROM whatsapp_connections WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == "disconnected"


def test_secrets_are_redacted_from_meta_errors(wa):
    assert TOKEN not in redact(f"Invalid OAuth access token {TOKEN}") and APP_SECRET not in redact(f"secret {APP_SECRET}")
    e = MetaError(f"bad {TOKEN}")
    assert TOKEN not in str(e) and "[token]" in e.message


def test_the_meta_client_redacts_a_token_echoed_in_an_error(wa, admin):
    biz = make_business("Echo Clinic")
    wa.fail = {"exchange": 400}  # the mock's error text contains the token
    r, _ = connect(biz, admin)
    assert TOKEN not in r.text


# ===================================================================== tenant isolation
def test_a_business_sees_only_its_own_whatsapp_data(wa, admin):
    a = connected(admin, "Iso A")
    b = make_business("Iso B")
    add_contact(a, marketing=True, **OWNER)
    assert b.get("/whatsapp/contacts").json()["total"] == 0 and b.get("/whatsapp/status").json()["connection"] is None
    cid = a.get("/whatsapp/contacts").json()["items"][0]["id"]
    for method, url, body in (("PATCH", f"/whatsapp/contacts/{cid}", {"name": "x"}), ("POST", f"/whatsapp/contacts/{cid}/opt-out", {"purpose": "marketing"}),
                              ("POST", f"/whatsapp/contacts/{cid}/consent", {"purpose": "utility", **OWNER}), ("DELETE", f"/whatsapp/contacts/{cid}", None)):
        r = b.request(method, url, json=body) if body is not None else b.request(method, url)
        assert r.status_code == 404, (method, url)
    assert a.get("/whatsapp/contacts").json()["total"] == 1
    assert b.post("/whatsapp/connection/check").status_code == 404 and b.post("/whatsapp/connection/disconnect").status_code == 404


def test_row_level_security_hides_every_whatsapp_table_from_other_businesses(wa, admin):
    a = connected(admin, "Rls A")
    b = make_business("Rls B")
    add_contact(a, marketing=True, **OWNER)
    add_message(a.tenant_id, "wamid.RLS")
    grant_addon(admin, b, "whatsapp_growth")
    for table in ("whatsapp_connections", "whatsapp_contacts", "whatsapp_consents", "whatsapp_suppressions", "whatsapp_templates", "whatsapp_messages", "whatsapp_webhook_events", "tenant_addons"):
        assert owner_query("SELECT relforcerowsecurity FROM pg_class WHERE relname = :t", t=table)[0][0] is True, table
        with svc_db(b.tenant_id) as db:
            assert db.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": a.tenant_id}).scalar() == 0, table
    with svc_db(a.tenant_id) as db:
        assert db.execute(text("SELECT count(*) FROM whatsapp_contacts")).scalar() == 1
        assert db.execute(text("SELECT count(*) FROM whatsapp_messages")).scalar() == 1
    with SessionLocal() as db:  # no tenant at all: nothing
        set_rls_context(db)
        assert db.execute(text("SELECT count(*) FROM whatsapp_contacts")).scalar() == 0


BOOKING_MEMBER_ACTIONS = ("bookings", "reschedule", "cancel", "done", "no-show")
INBOX_ACTIONS = ("read", "reply", "send-template", "take-over", "hand-back", "close", "reopen", "ai-pause", "feedback")


def test_every_owner_route_needs_a_role_and_the_manifest_knows_them():
    lines = open("tests/route_access_manifest.txt", encoding="utf-8").read().splitlines()
    wa_lines = [ln for ln in lines if "/whatsapp" in ln]
    assert wa_lines, "WhatsApp routes missing from the access manifest"
    for ln in wa_lines:
        kind, method, path = ln.split("\t")
        if path.startswith("/api/v1/webhooks/whatsapp"):
            assert kind.startswith("public"), ln
        elif path.startswith("/api/v1/admin/"):
            assert kind == "platform-admin", ln
        elif method == "GET" and path.startswith("/api/v1/whatsapp/integrations"):
            assert kind == "role-admin", ln  # keys and webhook endpoints are for owners and admins only, even to read
        elif path.startswith("/api/v1/integrations/v1/"):
            assert kind == "public" and "key" not in ln, ln  # the inbound API is authenticated by an API key, not a login (reviewed in test_phase2_security_audit)
        elif method == "GET" and "export" not in path and not path.endswith(".csv"):  # a file download of customers or results is an owner/admin action
            assert kind == "member", ln
        elif method == "POST" and path.startswith("/api/v1/whatsapp/conversations/{conversation_id}/") and path.rsplit("/", 1)[1] in INBOX_ACTIONS:
            assert kind == "member", ln  # the one deliberate exception: any team member answers customers in the inbox (replies carry their name). Settings and deleting stay owner/admin.
        elif method == "POST" and path.startswith("/api/v1/whatsapp/bookings") and path.rsplit("/", 1)[1] in BOOKING_MEMBER_ACTIONS:
            assert kind == "member", ln  # any team member books a customer in, moves, cancels and marks visits; setup (settings, services, hours, closed days) stays owner/admin
        else:
            assert kind == "role-admin", ln
    seen = {ln.split("	")[2].rsplit("/", 1)[1] for ln in wa_lines if ln.split("	")[1] == "POST" and "/conversations/{conversation_id}/" in ln}
    assert seen == set(INBOX_ACTIONS)


# ===================================================================== webhook
def test_the_verification_challenge_needs_the_exact_token(wa):
    with TestClient(app, base_url="http://testserver") as c:
        ok = c.get("/api/v1/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1158201444"})
        assert ok.status_code == 200 and ok.text == "1158201444" and ok.headers["content-type"].startswith("text/plain")
        for params in ({"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"}, {"hub.mode": "subscribe", "hub.challenge": "1"},
                       {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY, "hub.challenge": "1"}, {"hub.mode": "subscribe", "hub.verify_token": VERIFY}):
            assert c.get("/api/v1/webhooks/whatsapp", params=params).status_code == 403, params


def test_the_webhook_needs_the_sub_flag_as_well(wa, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_webhook_enabled", False)
    with TestClient(app, base_url="http://testserver") as c:
        assert c.get("/api/v1/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1"}).status_code == 404
    assert post_wh(payload()).status_code == 404


def test_a_delivery_needs_a_valid_signature_over_the_raw_body(wa, admin):
    biz = connected(admin, "Sig Clinic")
    raw = payload(statuses=[{"id": "wamid.SIG", "status": "delivered", "timestamp": "1700000000"}])
    before = owner_query("SELECT count(*) FROM whatsapp_webhook_events")[0][0]
    assert post_wh(raw, sig=None).status_code == 403
    assert post_wh(raw, sig="sha256=" + "0" * 64).status_code == 403
    assert post_wh(raw, sig="md5=abc").status_code == 403
    assert post_wh(raw, sig=sign(raw, "another-secret-entirely-0123456789")).status_code == 403
    assert post_wh(raw, sig=sign(raw + b" ")).status_code == 403  # signed a different body
    assert post_wh(raw.replace(b"delivered", b"read"), sig=sign(raw)).status_code == 403  # tampered after signing
    assert owner_query("SELECT count(*) FROM whatsapp_webhook_events")[0][0] == before  # nothing was stored for any refusal
    assert post_wh(raw).status_code == 200
    assert owner_query("SELECT count(*) FROM whatsapp_webhook_events")[0][0] == before + 1
    assert biz.tenant_id  # keep the fixture used


def test_a_delivery_is_refused_when_the_app_secret_is_not_configured(wa, monkeypatch):
    monkeypatch.setattr(settings, "meta_app_secret", "")
    raw = payload()
    assert post_wh(raw, sig=sign(raw, "")).status_code == 403


def test_invalid_payloads_are_rejected_after_the_signature_and_store_nothing(wa):
    before = owner_query("SELECT count(*) FROM whatsapp_webhook_events")[0][0]
    for raw in (b"not json", b'["a"]', b'{"object": "page", "entry": []}', b'{"object": "whatsapp_business_account"}', b""):
        assert post_wh(raw).status_code == 400, raw
    assert post_wh(b"x" * 1_100_000).status_code == 413
    assert owner_query("SELECT count(*) FROM whatsapp_webhook_events")[0][0] == before


def test_a_stored_event_is_sanitised_deduplicated_and_queued_once(wa, admin):
    connected(admin, "Sanitise Clinic")
    raw = payload(messages=[{"from": "919876543210", "id": "wamid.IN1", "type": "text", "text": {"body": "STOP"}}, {"from": "919876543211", "id": "wamid.IN2", "type": "text", "text": {"body": "x" * 5000}}],
                  statuses=[{"id": "wamid.S1", "status": "sent", "timestamp": "1700000000", "recipient_id": "919876543210", "conversation": {"id": "c1"}, "pricing": {"billable": True}}])
    assert post_wh(raw).status_code == 200 and post_wh(raw).status_code == 200 and post_wh(raw).status_code == 200  # Meta redelivers
    rows = owner_query("SELECT payload::text, status FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=hashlib.sha256(raw).hexdigest())
    assert len(rows) == 1 and rows[0][1] == "received"
    stored = rows[0][0]
    assert "Secret Customer Name" not in stored and "x" * 100 not in stored and "conversation" not in stored and "pricing" not in stored and "recipient_id" not in stored
    assert len(wa.queued) == 1  # the duplicates were recognised and not queued again


def test_a_failed_queue_still_answers_200_and_housekeeping_requeues(wa, monkeypatch, admin):
    connected(admin, "Queue Clinic")
    monkeypatch.setattr(wh, "enqueue", REAL_ENQUEUE)  # the real one, with a broker that refuses
    import app.workers.tasks as tasks

    def refuse(*a, **k):
        raise RuntimeError("broker down")
    monkeypatch.setattr(tasks.whatsapp_process_event, "delay", refuse)
    raw = payload(statuses=[{"id": "wamid.Q1", "status": "sent", "timestamp": "1700000000"}])
    assert post_wh(raw).status_code == 200
    eid = event_id_for(raw)
    owner_exec("UPDATE whatsapp_webhook_events SET received_at = now() - interval '10 minutes' WHERE id = :i", i=eid)
    db = system_session()
    try:
        assert eid in wh.stale_event_ids(db)
    finally:
        db.close()


def test_delivery_status_only_moves_forward_and_a_repeat_changes_nothing(wa, admin):
    biz = connected(admin, "Status Clinic")
    add_message(biz.tenant_id, "wamid.FWD", "queued")
    def deliver(status, ts, errors=None):
        s = {"id": "wamid.FWD", "status": status, "timestamp": ts}
        if errors:
            s["errors"] = errors
        raw = payload(statuses=[s])
        assert post_wh(raw).status_code == 200
        return process(event_id_for(raw))
    assert deliver("sent", "1700000001")["statuses"] == 1 and msg_status("wamid.FWD")[0] == "sent"
    assert deliver("read", "1700000009")["statuses"] == 1 and msg_status("wamid.FWD") == ("read", None, False, True)  # read does not invent a delivered time
    assert deliver("delivered", "1700000005")["statuses"] == 0 and msg_status("wamid.FWD")[0] == "read"  # older news arrives late: ignored
    assert deliver("failed", "1700000010", [{"code": 131026}])["statuses"] == 0 and msg_status("wamid.FWD")[0] == "read"  # cannot fail after being read


def test_a_failed_delivery_records_the_error_code(wa, admin):
    biz = connected(admin, "Failed Clinic")
    add_message(biz.tenant_id, "wamid.BAD", "sent")
    raw = payload(statuses=[{"id": "wamid.BAD", "status": "failed", "timestamp": "1700000002", "errors": [{"code": 131047, "title": "Re-engagement message"}]}])
    post_wh(raw)
    assert process(event_id_for(raw))["statuses"] == 1
    assert msg_status("wamid.BAD")[:2] == ("failed", "131047")


def test_processing_the_same_event_twice_is_harmless(wa, admin):
    biz = connected(admin, "Twice Clinic")
    add_message(biz.tenant_id, "wamid.TWICE", "sent")
    raw = payload(statuses=[{"id": "wamid.TWICE", "status": "delivered", "timestamp": "1700000003"}])
    post_wh(raw)
    eid = event_id_for(raw)
    assert process(eid)["statuses"] == 1
    assert process(eid) == {"skipped": "already_done"}
    assert owner_query("SELECT status, attempts FROM whatsapp_webhook_events WHERE id = :i", i=eid)[0] == ("processed", 1)


def test_the_business_comes_only_from_the_verified_phone_number_never_from_the_payload(wa, admin):
    biz = connected(admin, "Mapped Clinic")
    other = make_business("Victim Clinic")
    add_message(other.tenant_id, "wamid.VICTIM", "sent", phone_id=uid(3))
    add_message(biz.tenant_id, "wamid.MINE", "sent")
    # a hostile body: names another business's tenant and message id, arrives on THIS business's verified number
    raw = payload(statuses=[{"id": "wamid.VICTIM", "status": "read", "timestamp": "1700000004", "tenant_id": other.tenant_id}, {"id": "wamid.MINE", "status": "read", "timestamp": "1700000004"}],
                  extra={"tenant_id": other.tenant_id})
    post_wh(raw)
    out = process(event_id_for(raw))
    assert out["statuses"] == 1
    assert msg_status("wamid.VICTIM")[0] == "sent" and msg_status("wamid.MINE")[0] == "read"
    ev = owner_query("SELECT tenant_id FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=hashlib.sha256(raw).hexdigest())[0][0]
    assert str(ev) == biz.tenant_id


def test_an_unknown_or_disconnected_number_is_ignored_and_attributed_to_nobody(wa, admin):
    biz = connected(admin, "Gone Clinic")
    add_message(biz.tenant_id, "wamid.GONE", "sent")
    unknown = payload(uid(7), statuses=[{"id": "wamid.GONE", "status": "read", "timestamp": "1700000005"}])
    post_wh(unknown)
    assert process(event_id_for(unknown))["ignored_items"] == 1 and msg_status("wamid.GONE")[0] == "sent"
    assert owner_query("SELECT status, tenant_id FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=hashlib.sha256(unknown).hexdigest())[0] == ("ignored", None)
    biz.post("/whatsapp/connection/disconnect")
    after = payload(statuses=[{"id": "wamid.GONE", "status": "delivered", "timestamp": "1700000006"}])
    post_wh(after)
    assert process(event_id_for(after))["ignored_items"] == 1 and msg_status("wamid.GONE")[0] == "sent"


def test_two_businesses_in_one_delivery_are_each_handled_under_their_own_number(wa, admin):
    a = connected(admin, "Batch A")
    b = make_business("Batch B")
    wa.phone = {"display_phone_number": "+1 555 010 0200", "verified_name": "B", "quality_rating": "GREEN"}
    waba2, phone2 = uid(4), uid(5)
    wa.granted = [waba2]
    rb, _ = connect(b, admin, waba=waba2, phone=phone2)
    assert rb.status_code == 200, rb.text
    add_message(a.tenant_id, "wamid.SAME", "sent", phone_id=PHONE)
    add_message(b.tenant_id, "wamid.SAME", "sent", phone_id=phone2)  # the same message id on two different numbers
    body = json.loads(payload(statuses=[{"id": "wamid.SAME", "status": "delivered", "timestamp": "1700000007"}]))
    second = json.loads(payload(phone2, statuses=[{"id": "wamid.SAME", "status": "read", "timestamp": "1700000008"}], waba=waba2))
    body["entry"].extend(second["entry"])
    raw = json.dumps(body).encode()
    post_wh(raw)
    assert process(event_id_for(raw))["statuses"] == 2
    rows = dict(owner_query("SELECT phone_number_id, delivery_status FROM whatsapp_messages WHERE meta_message_id = 'wamid.SAME'"))
    assert rows == {PHONE: "delivered", phone2: "read"}
    assert owner_query("SELECT tenant_id FROM whatsapp_webhook_events WHERE payload_sha256 = :h", h=hashlib.sha256(raw).hexdigest())[0][0] is None  # spans two businesses: unattributed


def test_a_customer_reply_of_stop_opts_them_out_of_marketing_only_for_that_business(wa, admin):
    a = connected(admin, "Stop Clinic")
    other = make_business("Other Shop")
    ca = add_contact(a, marketing=True, utility=True, **OWNER)
    co = add_contact(other, marketing=True, **OWNER)
    raw = payload(messages=[{"from": "919876543210", "id": "wamid.STOP1", "type": "text", "text": {"body": " Stop. "}}])
    post_wh(raw)
    assert process(event_id_for(raw))["opt_outs"] == 1
    got = a.get("/whatsapp/contacts").json()["items"][0]
    assert got["opted_out"] is True and got["marketing"] is None and got["utility"] is not None and got["id"] == ca["id"]  # utility consent is a separate record
    assert other.get("/whatsapp/contacts").json()["items"][0]["opted_out"] is False and co["id"]
    assert owner_query("SELECT count(*) FROM whatsapp_suppressions WHERE tenant_id = :t", t=a.tenant_id)[0][0] == 1
    again = payload(messages=[{"from": "919876543210", "id": "wamid.STOP2", "type": "text", "text": {"body": "STOP"}}])
    post_wh(again)
    process(event_id_for(again))
    assert owner_query("SELECT count(*) FROM whatsapp_suppressions WHERE tenant_id = :t", t=a.tenant_id)[0][0] == 1  # idempotent


def test_only_a_message_that_is_just_the_stop_word_opts_out(wa, admin):
    a = connected(admin, "Word Clinic")
    add_contact(a, marketing=True, **OWNER)
    for text_ in ("please do not stop the reminders", "stop calling me at night", "I want to stop by tomorrow", "unsubscribed?", ""):
        raw = payload(messages=[{"from": "919876543210", "id": f"wamid.{abs(hash(text_))}", "type": "text", "text": {"body": text_}}])
        post_wh(raw)
        process(event_id_for(raw))
    assert a.get("/whatsapp/contacts").json()["items"][0]["opted_out"] is False
    assert all(rules.is_opt_out(w) for w in ("STOP", "unsubscribe", "Stop all", "बंद", "opt out")) and not rules.is_opt_out("stop by")


def test_stop_from_a_number_that_is_not_a_contact_still_suppresses_it(wa, admin):
    a = connected(admin, "Unknown Stop")
    raw = payload(messages=[{"from": "919123456780", "id": "wamid.UNK", "type": "text", "text": {"body": "STOP"}}])
    post_wh(raw)
    process(event_id_for(raw))
    r = a.post("/whatsapp/contacts", json={"phone": "91234 56780", "marketing": True, **OWNER})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "opted_out"  # an owner cannot add them back for offers


def test_a_meta_account_problem_asks_the_owner_to_act(wa, admin):
    a = connected(admin, "Alert Clinic")
    raw = payload(field="account_update", event="DISABLED_UPDATE")
    post_wh(raw)
    assert process(event_id_for(raw))["attention"] == 1
    s = a.get("/whatsapp/status").json()["connection"]
    assert s["status"] == "needs_attention" and "WhatsApp Manager" in s["attention_reason"]


def test_the_worker_task_processes_and_old_events_are_purged(wa, admin, monkeypatch):
    from app.workers.tasks import whatsapp_housekeeping, whatsapp_process_event
    biz = connected(admin, "Task Clinic")
    add_message(biz.tenant_id, "wamid.TASK", "sent")
    raw = payload(statuses=[{"id": "wamid.TASK", "status": "delivered", "timestamp": "1700000011"}])
    post_wh(raw)
    eid = event_id_for(raw)
    assert whatsapp_process_event.apply(args=[str(eid)]).get()["statuses"] == 1
    assert msg_status("wamid.TASK")[0] == "delivered"
    owner_exec("UPDATE whatsapp_webhook_events SET received_at = now() - interval '40 days' WHERE id = :i", i=eid)
    out = whatsapp_housekeeping.run()
    assert out["purged"] >= 1 and owner_query("SELECT count(*) FROM whatsapp_webhook_events WHERE id = :i", i=eid)[0][0] == 0


# ===================================================================== consent
def test_a_contact_is_not_consent_and_owner_consent_needs_an_attestation_and_a_note(wa, admin):
    biz = connected(admin, "Consent Clinic")
    c = add_contact(biz)  # just a person
    assert c["marketing"] is None and c["utility"] is None and c["phone"] == "+919876543210"
    for body, code in (({"phone": "90000 00001", "marketing": True}, "attestation_required"), ({"phone": "90000 00002", "marketing": True, "attested": True}, "evidence_required"),
                       ({"phone": "90000 00003", "marketing": True, "attested": True, "evidence": "yes"}, "evidence_required")):
        r = biz.post("/whatsapp/contacts", json=body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, body
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0
    ok = add_contact(biz, "90000 00004", marketing=True, utility=True, **OWNER)
    assert ok["marketing"]["source"] == "owner_entry" and ok["utility"]["wording_version"] == rules.WORDING_VERSION


def test_the_wording_and_version_are_stored_exactly_and_never_change(wa, admin):
    biz = connected(admin, "Wording Clinic")
    add_contact(biz, marketing=True, utility=True, **OWNER)
    rows = {r[0]: r for r in owner_query("SELECT purpose, wording_version, wording_text, evidence, granted_by IS NOT NULL FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)}
    assert rows["marketing"][1] == rules.WORDING_VERSION and "offers and updates from Wording Clinic on WhatsApp" in rows["marketing"][2] and "STOP" in rows["marketing"][2]
    assert "visit, booking or enquiry" in rows["utility"][2] and rows["marketing"][3].startswith("Asked at the counter") and rows["marketing"][4] is True
    with SessionLocal() as db:  # the application role cannot edit what was agreed
        set_rls_context(db, bypass=True)
        for sql in ("UPDATE whatsapp_consents SET wording_text = 'edited'", "UPDATE whatsapp_consents SET granted_at = now()", "UPDATE whatsapp_consents SET source = 'qr_page'"):
            with pytest.raises(DBAPIError):
                db.execute(text(sql))
            db.rollback()
        db.execute(text("UPDATE whatsapp_consents SET revoked_at = now(), revoked_source = 'owner' WHERE purpose = 'utility' AND tenant_id = :t"), {"t": biz.tenant_id})  # revocation columns are allowed
        db.rollback()


def test_asking_again_for_a_consent_that_exists_adds_nothing(wa, admin):
    biz = connected(admin, "Idem Clinic")
    c = add_contact(biz, marketing=True, **OWNER)
    r = biz.post(f"/whatsapp/contacts/{c['id']}/consent", json={"purpose": "marketing", **OWNER})
    assert r.status_code == 200
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE contact_id = :c", c=c["id"])[0][0] == 1
    assert biz.post("/whatsapp/contacts", json={"phone": "98765 43210", "name": "Asha"}).json()["id"] == c["id"]  # the same number is the same contact


def test_a_customer_can_give_consent_themselves_without_an_attestation(wa, admin):
    biz = connected(admin, "Self Clinic")
    c = add_contact(biz)
    with svc_db(biz.tenant_id) as db:
        t = db.get(Tenant, uuid.UUID(biz.tenant_id))
        contact = consent.get_contact(db, t.id, uuid.UUID(c["id"]))
        for purpose, src in (("marketing", "qr_page"), ("utility", "website_form")):
            row, made = consent.grant(db, t, contact, purpose, src)
            assert made and row.source == src and row.evidence is None
        second = consent.create_contact(db, t, phone="98765 43211", name=None, tags=[], source="customer_message", user_id=None)[0]
        assert consent.grant(db, t, second, "utility", "customer_message")[1] is True
        db.commit()
    got = biz.get("/whatsapp/contacts", params={"search": "43210"}).json()["items"][0]
    assert got["marketing"]["source"] == "qr_page" and got["utility"]["source"] == "website_form"


def test_withdrawing_marketing_flags_the_person_suppresses_the_number_and_keeps_utility(wa, admin):
    biz = connected(admin, "Withdraw Clinic")
    c = add_contact(biz, marketing=True, utility=True, **OWNER)
    r = biz.post(f"/whatsapp/contacts/{c['id']}/opt-out", json={"purpose": "marketing"}).json()
    assert r["opted_out"] is True and r["marketing"] is None and r["utility"] is not None
    row = owner_query("SELECT revoked_at IS NOT NULL, revoked_source FROM whatsapp_consents WHERE contact_id = :c AND purpose = 'marketing'", c=c["id"])[0]
    assert row == (True, "owner")
    sup = owner_query("SELECT phone_hash, reason FROM whatsapp_suppressions WHERE tenant_id = :t", t=biz.tenant_id)
    assert len(sup) == 1 and "9876543210" not in sup[0][0] and sup[0][0] == rules.phone_hash(uuid.UUID(biz.tenant_id), "+919876543210")
    assert biz.post(f"/whatsapp/contacts/{c['id']}/opt-out", json={"purpose": "marketing"}).status_code == 200  # idempotent
    assert owner_query("SELECT count(*) FROM whatsapp_suppressions WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 1


def test_after_an_opt_out_only_the_customer_can_consent_again(wa, admin):
    biz = connected(admin, "Back Clinic")
    c = add_contact(biz, marketing=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{c['id']}/opt-out", json={"purpose": "marketing"})
    r = biz.post(f"/whatsapp/contacts/{c['id']}/consent", json={"purpose": "marketing", **OWNER})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "opted_out"
    assert biz.post(f"/whatsapp/contacts/{c['id']}/consent", json={"purpose": "utility", **OWNER}).status_code == 200  # utility is a different purpose
    with svc_db(biz.tenant_id) as db:  # an administrator cannot lift it either
        t = db.get(Tenant, uuid.UUID(biz.tenant_id))
        contact = consent.get_contact(db, t.id, uuid.UUID(c["id"]))
        with pytest.raises(WaError) as e:
            consent.grant(db, t, contact, "marketing", "admin_entry", attested=True, evidence="phoned them and they said yes")
        assert e.value.code == "opted_out"
        row, made = consent.grant(db, t, contact, "marketing", "qr_page")  # the customer agrees again themselves
        db.commit()
        assert made
    got = biz.get("/whatsapp/contacts").json()["items"][0]
    assert got["opted_out"] is False and got["marketing"]["source"] == "qr_page"
    assert owner_query("SELECT count(*) FROM whatsapp_suppressions WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE contact_id = :c AND purpose = 'marketing'", c=c["id"])[0][0] == 2  # the old consent row stays as history


def test_erasing_a_person_removes_them_but_keeps_an_opt_out_as_a_hash(wa, admin):
    biz = connected(admin, "Erase Clinic")
    a = add_contact(biz, "98765 00001", marketing=True, **OWNER)
    b = add_contact(biz, "98765 00002", marketing=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{b['id']}/opt-out", json={"purpose": "marketing"})
    assert biz.delete(f"/whatsapp/contacts/{a['id']}").status_code == 204 and biz.delete(f"/whatsapp/contacts/{b['id']}").status_code == 204
    assert biz.get("/whatsapp/contacts").json()["total"] == 0
    assert owner_query("SELECT count(*) FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0
    assert owner_query("SELECT count(*) FROM whatsapp_suppressions WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 1  # only the one who opted out
    r = biz.post("/whatsapp/contacts", json={"phone": "98765 00002", "marketing": True, **OWNER})
    assert r.status_code == 409  # erased, but still cannot be added for offers
    assert biz.post("/whatsapp/contacts", json={"phone": "98765 00001", "marketing": True, **OWNER}).status_code == 201  # the one who never opted out can be added again


def test_phone_numbers_and_names_are_validated_and_cleaned(wa, admin):
    biz = connected(admin, "Valid Clinic")
    for bad in ("abc", "12345", "", "98765"):
        assert biz.post("/whatsapp/contacts", json={"phone": bad}).status_code in (422, 400), bad
    r = biz.post("/whatsapp/contacts", json={"phone": "+91 98765-43210", "name": "  Asha‮​ Verma  ", "tags": ["vip", "VIP", "  regular  ", "x" * 99]})
    assert r.status_code == 201 and r.json()["phone"] == "+919876543210" and r.json()["customer_name"] == "Asha Verma" and r.json()["tags"] == ["vip", "regular", "x" * 30]
    assert biz.post("/whatsapp/contacts", json={"phone": "98765 43210", "name": "Other", "tags": ["new"]}).json()["customer_name"] == "Asha Verma"  # an existing name is not overwritten
    p = biz.patch(f"/whatsapp/contacts/{r.json()['id']}", json={"name": "Asha V", "tags": ["a"]}).json()
    assert p["customer_name"] == "Asha V" and p["tags"] == ["a"]


def test_listing_filters_and_search(wa, admin):
    biz = connected(admin, "List Clinic")
    add_contact(biz, "98765 00011", name="Meera", marketing=True, **OWNER)
    add_contact(biz, "98765 00012", name="Ravi", utility=True, **OWNER)
    add_contact(biz, "98765 00013", name="Sita")
    o = add_contact(biz, "98765 00014", name="Omar", marketing=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{o['id']}/opt-out", json={"purpose": "marketing"})
    f = lambda **p: sorted(i["customer_name"] for i in biz.get("/whatsapp/contacts", params=p).json()["items"])  # noqa: E731
    assert f() == ["Meera", "Omar", "Ravi", "Sita"] and f(consent_filter="marketing") == ["Meera"] and f(consent_filter="utility") == ["Ravi"]
    assert f(consent_filter="opted_out") == ["Omar"] and f(consent_filter="none") == ["Omar", "Sita"] and f(search="rav") == ["Ravi"] and f(search="00013") == ["Sita"]
    assert biz.get("/whatsapp/contacts").json()["counts"] == {"contacts": 4, "marketing": 1, "utility": 1, "occasion": 0, "opted_out": 1}


# ===================================================================== CSV
CSV_OK = "phone,name,tags\n98765 10001,Anil,vip;regular\n98765 10002,Bina,\n98765 10003,Chetan,new\n"


def test_a_csv_import_needs_an_attestation_a_note_and_a_purpose(wa, admin):
    biz = connected(admin, "Csv Clinic")
    base = {"csv": CSV_OK, "purposes": ["marketing"], **OWNER}
    for patch, code in (({"attested": False}, "attestation_required"), ({"evidence": "ok"}, "evidence_required"), ({"evidence": None}, "evidence_required")):
        r = biz.post("/whatsapp/contacts/import", json={**base, **patch})
        assert r.status_code == 422 and r.json()["detail"]["code"] == code
    assert biz.post("/whatsapp/contacts/import", json={**base, "purposes": []}).status_code == 422
    assert biz.get("/whatsapp/contacts").json()["total"] == 0
    r = biz.post("/whatsapp/contacts/import", json=base).json()
    assert (r["rows"], r["added"], r["consents_recorded"], r["skipped"]) == (3, 3, 3, 0)
    rows = owner_query("SELECT source, evidence FROM whatsapp_consents WHERE tenant_id = :t", t=biz.tenant_id)
    assert {s for s, _ in rows} == {"csv_import"} and all(e.startswith("Asked at the counter") for _, e in rows)
    assert biz.get("/whatsapp/contacts", params={"search": "Anil"}).json()["items"][0]["tags"] == ["vip", "regular"]


def test_a_csv_cannot_smuggle_consent_for_people_who_opted_out_and_reports_bad_rows(wa, admin):
    biz = connected(admin, "Csv Two")
    o = add_contact(biz, "98765 10001", marketing=True, **OWNER)
    biz.post(f"/whatsapp/contacts/{o['id']}/opt-out", json={"purpose": "marketing"})
    text_csv = "mobile,name\n98765 10001,Anil\nnot-a-number,Bad\n98765 10002,Bina\n98765 10002,Bina again\n,\n"
    r = biz.post("/whatsapp/contacts/import", json={"csv": text_csv, "purposes": ["marketing"], **OWNER}).json()
    assert r["added"] == 1 and r["skipped"] == 4 and r["consents_recorded"] == 1
    reasons = " ".join(e["reason"] for e in r["errors"])
    assert "asked to stop" in reasons and "Not a valid mobile number" in reasons and "twice" in reasons
    assert biz.get("/whatsapp/contacts", params={"consent_filter": "marketing"}).json()["total"] == 1  # only Bina


def test_csv_import_limits_and_shape(wa, admin):
    biz = connected(admin, "Csv Three")
    ok = {"purposes": ["utility"], **OWNER}
    assert biz.post("/whatsapp/contacts/import", json={**ok, "csv": "name,city\nA,B\n"}).json()["detail"]["code"] == "no_phone_column"
    big = "phone\n" + "\n".join(f"9{n:09d}" for n in range(1, 2002))
    assert biz.post("/whatsapp/contacts/import", json={**ok, "csv": big}).json()["detail"]["code"] == "too_many_rows"
    assert biz.post("/whatsapp/contacts/import", json={**ok, "csv": "x" * 400_001}).status_code == 422
    assert biz.get("/whatsapp/contacts").json()["total"] == 0


def test_the_export_is_a_safe_csv_and_audited(wa, admin):
    biz = connected(admin, "Export Clinic")
    add_contact(biz, "98765 20001", name="=HYPERLINK(\"http://evil\")", tags=["+cmd"], marketing=True, **OWNER)
    r = biz.get("/whatsapp/contacts/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "no-store" in r.headers["cache-control"]
    lines = r.text.splitlines()
    assert lines[0].startswith("phone,name,tags,marketing_consent_since") and "'=HYPERLINK" in lines[1] and "'+cmd" in lines[1] and ",=HYPERLINK" not in lines[1]
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'whatsapp.contact_export'", t=biz.tenant_id)[0][0] == 1


# ===================================================================== the send gate (Phase 2 will call it; Phase 1 proves it)
def gate_for(biz, contact_id, purpose):
    with svc_db(biz.tenant_id) as db:
        t = uuid.UUID(biz.tenant_id)
        return gate.preflight(db, t, consent.get_contact(db, t, uuid.UUID(contact_id)), purpose)


def test_nothing_may_send_in_phase_one(wa, admin):
    biz = connected(admin, "Gate Off")
    c = add_contact(biz, marketing=True, utility=True, **OWNER)
    assert gate_for(biz, c["id"], "marketing") == (False, "sending_disabled") and gate_for(biz, c["id"], "utility") == (False, "sending_disabled")


def test_the_gate_requires_consent_for_the_purpose_a_live_connection_and_no_emergency_stop(wa, admin, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", True)
    biz = connected(admin, "Gate Clinic")
    nobody = add_contact(biz, "98765 30001")
    util = add_contact(biz, "98765 30002", utility=True, **OWNER)
    mkt = add_contact(biz, "98765 30003", marketing=True, **OWNER)
    assert gate_for(biz, nobody["id"], "marketing") == (False, "no_marketing_consent") and gate_for(biz, nobody["id"], "utility") == (False, "no_utility_consent")
    assert gate_for(biz, util["id"], "marketing") == (False, "no_marketing_consent")  # utility consent never allows marketing
    assert gate_for(biz, util["id"], "utility") == (True, "ok") and gate_for(biz, mkt["id"], "marketing") == (True, "ok")
    assert gate_for(biz, mkt["id"], "utility") == (False, "no_utility_consent")  # and marketing consent never allows utility
    biz.post(f"/whatsapp/contacts/{mkt['id']}/opt-out", json={"purpose": "marketing"})
    assert gate_for(biz, mkt["id"], "marketing") == (False, "opted_out")
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", True)
    assert gate_for(biz, util["id"], "utility") == (False, "emergency_stop")
    monkeypatch.setattr(settings, "whatsapp_emergency_stop", False)
    monkeypatch.setattr(settings, "whatsapp_enabled", False)
    assert gate_for(biz, util["id"], "utility") == (False, "whatsapp_disabled")


def test_the_gate_refuses_without_an_addon_a_connection_or_a_valid_token(wa, admin, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", True)
    biz = connected(admin, "Gate Two")
    c = add_contact(biz, utility=True, **OWNER)
    wa.valid = False
    biz.post("/whatsapp/connection/check")
    assert gate_for(biz, c["id"], "utility") == (False, "not_connected")  # needs_attention
    wa.valid = True
    biz.post("/whatsapp/connection/check")
    assert gate_for(biz, c["id"], "utility") == (True, "ok")
    owner_exec("UPDATE whatsapp_connections SET token_expires_at = now() - interval '1 hour' WHERE tenant_id = :t", t=biz.tenant_id)
    assert gate_for(biz, c["id"], "utility") == (False, "token_expired")
    owner_exec("UPDATE whatsapp_connections SET token_expires_at = NULL WHERE tenant_id = :t", t=biz.tenant_id)
    admin.put(f"/admin/tenants/{biz.tenant_id}/whatsapp-addon", json={"addon_key": None, "reason": "Cancelled by the owner"})
    assert gate_for(biz, c["id"], "utility") == (False, "no_addon")
    biz.post("/whatsapp/connection/disconnect")
    admin.put(f"/admin/tenants/{biz.tenant_id}/whatsapp-addon", json={"addon_key": "whatsapp_starter", "reason": REASON})
    assert gate_for(biz, c["id"], "utility") == (False, "not_connected")


def test_a_contact_of_another_business_can_never_pass_the_gate(wa, admin, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_sending_enabled", True)
    a = connected(admin, "Gate A")
    b = make_business("Gate B")
    ca = add_contact(a, utility=True, **OWNER)
    with svc_db(a.tenant_id) as db:
        contact = consent.get_contact(db, uuid.UUID(a.tenant_id), uuid.UUID(ca["id"]))
        assert consent.has_consent(db, uuid.UUID(b.tenant_id), contact, "utility") == (False, "wrong_business")
        with pytest.raises(WaError):
            consent.get_contact(db, uuid.UUID(b.tenant_id), uuid.UUID(ca["id"]))


# ===================================================================== catalogue, export, deletion, config
def test_the_catalogue_is_plain_language_and_only_the_built_helpers_are_available(wa, admin):
    biz = make_business("Cat Clinic")
    r = biz.get("/whatsapp/automations").json()
    titles = [i["title"] for i in r["items"]]
    assert "Get more customer reviews" in titles and "Follow up with enquiries" in titles and "Send offers to customers" in titles
    live = {i["key"] for i in r["items"] if i["available"]}
    assert live == {"review_followup", "enquiry_followup", "offers", "birthday", "festival"} and all(i["coming_soon"] is (not i["available"]) for i in r["items"]) and r["limit"] is None
    blob = json.dumps(r).lower()
    for jargon in ("webhook", "api", "waba", "token", "phone_number_id", "cloud api"):
        assert jargon not in blob, jargon
    grant_addon(admin, biz, "whatsapp_growth")
    again = biz.get("/whatsapp/automations").json()
    assert again["limit"] == 8 and all(i["ready"]["addon"] for i in again["items"]) and not any(i["ready"]["connection"] for i in again["items"])


def test_the_account_export_includes_whatsapp_data_but_never_a_secret(wa, admin):
    biz = connected(admin, "Export Co")
    add_contact(biz, marketing=True, **OWNER)
    z = zipfile.ZipFile(io.BytesIO(biz.get("/account/export").content))
    names = set(z.namelist())
    assert {"whatsapp_connections.json", "whatsapp_contacts.json", "whatsapp_consents.json", "tenant_addons.json", "whatsapp_suppressions.json", "whatsapp_messages.json", "whatsapp_templates.json"} <= names
    blob = b"".join(z.read(n) for n in names if n.endswith(".json")).decode()
    ciphertext = owner_query("SELECT access_token_enc FROM whatsapp_connections WHERE tenant_id = :t", t=biz.tenant_id)[0][0]
    for secret in (TOKEN, ciphertext, "access_token_enc", "state_hash", APP_SECRET):
        assert secret not in blob, secret
    assert json.loads(z.read("whatsapp_contacts.json"))[0]["phone"] == "+919876543210"
    assert json.loads(z.read("whatsapp_consents.json"))[0]["wording_version"] == rules.WORDING_VERSION


def test_every_whatsapp_tenant_table_is_in_the_account_export():
    exported = {m.__tablename__ for m in account_svc.TABLES}
    assert {"whatsapp_connections", "whatsapp_contacts", "whatsapp_consents", "whatsapp_suppressions", "whatsapp_templates", "whatsapp_messages", "whatsapp_webhook_events", "tenant_addons"} <= exported
    assert {"access_token_enc", "state_hash"} <= account_svc.SECRET_COLUMNS


def test_deleting_a_business_unsubscribes_it_from_meta_and_removes_every_row(wa, admin):
    biz = connected(admin, "Delete Co")
    add_contact(biz, marketing=True, **OWNER)
    add_message(biz.tenant_id, "wamid.DEL")
    db = system_session()
    try:
        t = db.get(Tenant, uuid.UUID(biz.tenant_id))
        connection.on_tenant_delete(db, t.id)
        db.commit()
        assert wa.n("unsubscribe") == 1
        db.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": biz.tenant_id})
        db.commit()
    finally:
        db.close()
    for table in ("whatsapp_connections", "whatsapp_contacts", "whatsapp_consents", "whatsapp_messages", "tenant_addons"):
        assert owner_query(f"SELECT count(*) FROM {table} WHERE tenant_id = :t", t=biz.tenant_id)[0][0] == 0, table


def test_a_meta_outage_during_deletion_never_blocks_it(wa, admin):
    biz = connected(admin, "Outage Co")
    wa.fail = {"unsubscribe": 500}
    db = system_session()
    try:
        connection.on_tenant_delete(db, uuid.UUID(biz.tenant_id))  # must not raise
    finally:
        db.close()


def test_production_config_checks():
    assert not [p for p in config_problems(good()) if "WHATSAPP" in p or "META" in p]  # off by default: nothing to configure
    assert any("TOKEN_ENCRYPTION_KEY" in p and "WHATSAPP" in p for p in config_problems(good(whatsapp_enabled=True, token_encryption_key="")))
    problems = " ".join(config_problems(good(whatsapp_enabled=True, whatsapp_webhook_enabled=True, whatsapp_signup_enabled=True, whatsapp_webhook_verify_token="short", meta_app_secret="", meta_app_id="")))
    assert "WHATSAPP_WEBHOOK_VERIFY_TOKEN" in problems and "META_APP_ID" in problems and "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID" in problems
    assert any("https" in p for p in config_problems(good(whatsapp_enabled=True, whatsapp_graph_base_url="http://graph.example")))
    ok = good(whatsapp_enabled=True, whatsapp_webhook_enabled=True, whatsapp_signup_enabled=True, whatsapp_webhook_verify_token="v" * 30, meta_app_secret="s" * 32, meta_app_id="123456789", whatsapp_embedded_signup_config_id="cfg")
    assert not [p for p in config_problems(ok) if "WHATSAPP" in p or "META" in p]


# ===================================================================== what the database itself enforces (not just the application)
def test_the_database_allows_one_live_connection_per_business_and_one_active_tier(wa, admin):
    from sqlalchemy.exc import IntegrityError
    biz = connected(admin, "Db Rules")  # connected() recorded a starter tier
    with pytest.raises(IntegrityError):
        owner_exec("INSERT INTO whatsapp_connections (id, tenant_id, status, created_at, updated_at) VALUES (gen_random_uuid(), :t, 'pending', now(), now())", t=biz.tenant_id)
    with pytest.raises(IntegrityError):
        owner_exec("INSERT INTO tenant_addons (id, tenant_id, addon_key, status, reason, started_at, created_at, updated_at) VALUES (gen_random_uuid(), :t, 'whatsapp_pro', 'active', 'second active tier', now(), now(), now())", t=biz.tenant_id)
    add_contact(biz, "98765 43210")
    with pytest.raises(IntegrityError):
        owner_exec("INSERT INTO whatsapp_contacts (id, tenant_id, phone, source, created_at, updated_at) VALUES (gen_random_uuid(), :t, '+919876543210', 'owner_entry', now(), now())", t=biz.tenant_id)
    for bad in ("status = 'zombie'",):
        with pytest.raises(IntegrityError):
            owner_exec(f"UPDATE whatsapp_connections SET {bad} WHERE tenant_id = :t", t=biz.tenant_id)


def test_the_application_role_has_only_the_database_privileges_it_needs(wa):
    role = settings.database_url.split("//")[1].split(":")[0]
    has = lambda table, priv: owner_query("SELECT has_table_privilege(:r, :t, :p)", r=role, t=f"public.{table}", p=priv)[0][0]  # noqa: E731
    col = lambda column, priv: owner_query("SELECT has_column_privilege(:r, 'public.whatsapp_consents', :c, :p)", r=role, c=column, p=priv)[0][0]  # noqa: E731
    assert not has("whatsapp_consents", "UPDATE") and has("whatsapp_consents", "INSERT") and has("whatsapp_consents", "SELECT")  # a consent can be added, never rewritten
    assert col("revoked_at", "UPDATE") and col("revoked_source", "UPDATE") and col("revoked_by", "UPDATE")
    assert not col("wording_text", "UPDATE") and not col("granted_at", "UPDATE") and not col("source", "UPDATE") and not col("purpose", "UPDATE") and not col("evidence", "UPDATE")
    assert not has("whatsapp_suppressions", "UPDATE") and not has("whatsapp_connections", "TRUNCATE") and not has("tenant_addons", "DELETE")


def test_the_migrations_are_two_steps_on_top_of_the_website_builder():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["0063"] and script.get_revision("0048").down_revision == "0047" and script.get_revision("0049").down_revision == "0048" and script.get_revision("0063").down_revision == "0062" and script.get_revision("0062").down_revision == "0061" and script.get_revision("0061").down_revision == "0060" and script.get_revision("0060").down_revision == "0059" and script.get_revision("0059").down_revision == "0058" and script.get_revision("0058").down_revision == "0057" and script.get_revision("0057").down_revision == "0056" and script.get_revision("0056").down_revision == "0055" and script.get_revision("0055").down_revision == "0054" and script.get_revision("0054").down_revision == "0053" and script.get_revision("0053").down_revision == "0052" and script.get_revision("0052").down_revision == "0051" and script.get_revision("0051").down_revision == "0050" and script.get_revision("0050").down_revision == "0049"
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] == "0063"
    tables = {r[0] for r in owner_query("SELECT tablename FROM pg_tables WHERE tablename LIKE 'whatsapp_%' OR tablename = 'tenant_addons'")}
    assert tables == {"whatsapp_connections", "whatsapp_contacts", "whatsapp_consents", "whatsapp_suppressions", "whatsapp_templates", "whatsapp_messages", "whatsapp_webhook_events", "tenant_addons",
                      "whatsapp_rates", "whatsapp_automations", "whatsapp_automation_runs", "whatsapp_campaigns", "whatsapp_campaign_recipients", "whatsapp_optin_settings", "whatsapp_optin_keywords", "whatsapp_rate_verifications", "whatsapp_festivals", "whatsapp_festival_optins", "whatsapp_links", "whatsapp_link_clicks", "whatsapp_conversation_settings", "whatsapp_conversations", "whatsapp_conversation_messages",
                      "whatsapp_ai_quotas", "whatsapp_ai_settings", "whatsapp_knowledge_items", "whatsapp_ai_runs", "whatsapp_unanswered_questions",
                      "whatsapp_booking_settings", "whatsapp_booking_services", "whatsapp_booking_hours", "whatsapp_booking_closed", "whatsapp_bookings",
                      "whatsapp_api_keys", "whatsapp_api_requests", "whatsapp_webhook_endpoints", "whatsapp_webhook_deliveries",
                      "whatsapp_entry_windows", "whatsapp_entry_window_checks"}
