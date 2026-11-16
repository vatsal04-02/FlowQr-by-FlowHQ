"""The Cashfree provider layer on its own: webhook signature and replay window, the deduplication key (Cashfree sends no event id), parsing, the exact shape of every request, secrets never
leaking into logs or errors, and the production guard. No database and no network: the HTTP client runs against httpx.MockTransport."""
import json
import logging
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app.core.config import config_problems
from app.services import cashfree as cf
from tests.test_config_guard import good

SECRET = "cf_test_webhook_secret_value"
NOW = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
RAW = json.dumps({"type": "SUBSCRIPTION_PAYMENT_SUCCESS", "event_time": "2026-11-20T17:30:00+05:30",
                  "data": {"payment_id": "pay-1", "cf_payment_id": "555", "subscription_id": "fqs_abc", "payment_status": "SUCCESS", "payment_amount": 799.0, "payment_type": "CHARGE"}}).encode()


def stamp(dt=NOW, ms=True):
    return str(int(dt.timestamp() * (1000 if ms else 1)))


# ------------------------------------------------------------------------------------------------------------------------------ signature and replay
def test_a_correctly_signed_fresh_webhook_is_accepted_in_milliseconds_or_seconds():
    for ms in (True, False):
        ts = stamp(ms=ms)
        assert cf.verify_webhook(RAW, cf.sign_webhook(RAW, ts, SECRET), ts, secret=SECRET, now=NOW) == NOW


def test_the_signature_is_exactly_base64_hmac_sha256_of_timestamp_plus_raw_body():
    import base64, hashlib, hmac  # noqa: E401
    ts = stamp()
    expected = base64.b64encode(hmac.new(SECRET.encode(), ts.encode() + RAW, hashlib.sha256).digest()).decode()
    assert cf.sign_webhook(RAW, ts, SECRET) == expected


@pytest.mark.parametrize("case", ["tampered_body", "wrong_secret", "wrong_timestamp_signed", "empty_signature", "missing_signature", "missing_timestamp"])
def test_anything_not_authentic_is_refused(case):
    ts = stamp()
    sig = cf.sign_webhook(RAW, ts, SECRET)
    raw, secret, header_ts = RAW, SECRET, ts
    if case == "tampered_body":
        raw = RAW.replace(b"SUCCESS", b"FAILED_")
    elif case == "wrong_secret":
        secret = "another-secret"
    elif case == "wrong_timestamp_signed":
        header_ts = stamp(NOW + timedelta(seconds=1))
    elif case == "empty_signature":
        sig = ""
    elif case == "missing_signature":
        sig = None
    elif case == "missing_timestamp":
        header_ts = None
    with pytest.raises(cf.WebhookError):
        cf.verify_webhook(raw, sig, header_ts, secret=secret, now=NOW)


def test_a_replayed_webhook_outside_the_five_minute_window_is_refused_even_if_the_signature_is_valid():
    old = NOW - timedelta(minutes=6)
    ts = stamp(old)
    with pytest.raises(cf.WebhookError) as e:
        cf.verify_webhook(RAW, cf.sign_webhook(RAW, ts, SECRET), ts, secret=SECRET, now=NOW)
    assert e.value.reason == "stale_timestamp"
    future = stamp(NOW + timedelta(minutes=6))
    with pytest.raises(cf.WebhookError):
        cf.verify_webhook(RAW, cf.sign_webhook(RAW, future, SECRET), future, secret=SECRET, now=NOW)
    fresh = stamp(NOW - timedelta(minutes=4))
    cf.verify_webhook(RAW, cf.sign_webhook(RAW, fresh, SECRET), fresh, secret=SECRET, now=NOW)


def test_an_unconfigured_secret_refuses_everything_and_a_garbage_timestamp_fails_closed():
    ts = stamp()
    with pytest.raises(cf.WebhookError) as e:
        cf.verify_webhook(RAW, cf.sign_webhook(RAW, ts, ""), ts, secret="", now=NOW)
    assert e.value.reason == "not_configured"
    with pytest.raises(cf.WebhookError) as e2:
        cf.verify_webhook(RAW, cf.sign_webhook(RAW, "not-a-time", SECRET), "not-a-time", secret=SECRET, now=NOW)
    assert e2.value.reason == "bad_timestamp"


def test_the_signature_is_checked_on_the_raw_bytes_so_reformatting_the_json_breaks_it():
    ts = stamp()
    sig = cf.sign_webhook(RAW, ts, SECRET)
    reformatted = json.dumps(json.loads(RAW), indent=2).encode()
    with pytest.raises(cf.WebhookError):
        cf.verify_webhook(reformatted, sig, ts, secret=SECRET, now=NOW)


# ------------------------------------------------------------------------------------------------------------------------------ deduplication without an event id
def test_the_dedupe_key_comes_only_from_real_payload_fields_and_separates_distinct_events():
    env = cf.parse_envelope(RAW)
    assert env.type == "SUBSCRIPTION_PAYMENT_SUCCESS" and env.subscription_id == "fqs_abc" and env.payment_id == "pay-1" and env.status == "SUCCESS"
    assert cf.parse_envelope(RAW).dedupe_key == env.dedupe_key  # a repeated delivery is identical
    assert len(env.dedupe_key) == 64 and "fqs_abc" not in env.dedupe_key  # a hash: nothing readable, nothing to leak
    other_status = cf.parse_envelope(RAW.replace(b'"payment_status": "SUCCESS"', b'"payment_status": "FAILED"'))
    other_time = cf.parse_envelope(RAW.replace(b"17:30:00", b"17:30:01"))
    other_payment = cf.parse_envelope(RAW.replace(b'"pay-1"', b'"pay-2"'))
    assert len({env.dedupe_key, other_status.dedupe_key, other_time.dedupe_key, other_payment.dedupe_key}) == 4
    assert env.payload_hash != other_time.payload_hash and len(env.payload_hash) == 64


def test_envelope_parsing_covers_status_card_expiry_and_garbage():
    status_event = json.dumps({"type": "SUBSCRIPTION_STATUS_CHANGED", "event_time": "2026-11-20T10:00:00+05:30", "data": {"subscription_details": {"subscription_id": "fqs_x", "subscription_status": "ON HOLD"}}}).encode()
    e = cf.parse_envelope(status_event)
    assert (e.subscription_id, e.status) == ("fqs_x", "ON_HOLD")
    card = json.dumps({"type": "SUBSCRIPTION_CARD_EXPIRY_REMINDER", "event_time": "2026-11-20T10:00:00+05:30",
                       "data": {"subscription_status_webhook": {"subscription_details": {"subscription_id": "fqs_y", "subscription_status": "ACTIVE"}}, "card_expiry_date": "2027-01-31"}}).encode()
    assert cf.parse_envelope(card).subscription_id == "fqs_y"
    for bad in (b"not json", b"[]", b'{"data": {}}', b'{"type": 5}', b'{"type": "X", "data": "no"}'):
        with pytest.raises(cf.WebhookError):
            cf.parse_envelope(bad)


def test_money_time_and_status_helpers():
    assert cf.to_rupees(79900) == 799.0 and cf.to_rupees(100) == 1.0
    assert cf.to_paise(799.0) == 79900 and cf.to_paise("1.00") == 100 and cf.to_paise(1499) == 149900 and cf.to_paise(0.1 + 0.2) == 30
    assert cf.norm_status("on hold") == "ON_HOLD" and cf.norm_status(" Link Expired ") == "LINK_EXPIRED" and cf.norm_status(None) == ""
    assert cf.ist_iso(datetime(2026, 11, 20, 4, 30, tzinfo=timezone.utc)) == "2026-11-20T10:00:00+05:30"
    assert cf.parse_time("2026-11-20T10:00:00").utcoffset() == timedelta(hours=5, minutes=30)  # no offset means IST


# ------------------------------------------------------------------------------------------------------------------------------ the real client, against a mock transport
class Recorder:
    def __init__(self, routes):
        self.routes, self.seen = routes, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        handler = self.routes.get((request.method, request.url.path))
        if handler is None:
            return httpx.Response(404, json={"message": "no route", "code": "x"})
        return handler(request)


def make_client(monkeypatch, routes, **cfg):
    from app.core.config import settings
    for k, v in {"billing_provider": "cashfree", "cashfree_env": "sandbox", "cashfree_client_id": "CLIENT_ID_VALUE", "cashfree_client_secret": "CLIENT_SECRET_VALUE", **cfg}.items():
        monkeypatch.setattr(settings, k, v)
    c = cf.HttpCashfreeClient()
    rec = Recorder(routes)
    c._http = httpx.Client(base_url=settings.cashfree_base_url, headers=dict(c._http.headers), transport=httpx.MockTransport(rec))
    return c, rec


def test_the_client_uses_the_sandbox_host_and_documented_headers_and_never_a_secret_in_the_path(monkeypatch):
    sub = {"cf_subscription_id": 777, "subscription_id": "fqs_1", "subscription_status": "INITIALIZED", "subscription_session_id": "sess_123", "plan_details": {"plan_id": "p"}}
    c, rec = make_client(monkeypatch, {("POST", "/pg/subscriptions"): lambda r: httpx.Response(200, json=sub)})
    out = c.create_subscription(subscription_id="fqs_1", plan_id="flowqr-growth-79900", customer=cf.Customer("Asha", "asha@example.com", "9876543210"),
                                first_charge_at=datetime(2026, 11, 27, 4, 30, tzinfo=timezone.utc), authorization_paise=100, refund_authorization=True, methods=["upi", "card"],
                                return_url="https://www.flowqr.site/settings/billing/return?s=fqs_1", idempotency_key="11111111-1111-5111-8111-111111111111")
    req = rec.seen[0]
    assert str(req.url).startswith("https://sandbox.cashfree.com/pg/subscriptions")
    assert req.headers["x-client-id"] == "CLIENT_ID_VALUE" and req.headers["x-client-secret"] == "CLIENT_SECRET_VALUE" and req.headers["x-api-version"] == "2026-01-01"
    assert req.headers["x-idempotency-key"] == "11111111-1111-5111-8111-111111111111"
    assert "CLIENT_SECRET_VALUE" not in str(req.url)
    body = json.loads(req.content)
    assert body["subscription_id"] == "fqs_1" and body["plan_details"] == {"plan_id": "flowqr-growth-79900"}
    assert body["authorization_details"] == {"authorization_amount": 1.0, "authorization_amount_refund": True, "payment_methods": ["upi", "card"]}
    assert body["subscription_first_charge_time"] == "2026-11-27T10:00:00+05:30"
    assert body["customer_details"] == {"customer_name": "Asha", "customer_email": "asha@example.com", "customer_phone": "9876543210"}
    assert "enach" not in json.dumps(body).lower()
    assert (out.subscription_id, out.cf_id, out.status, out.session_id) == ("fqs_1", "777", "INITIALIZED", "sess_123")


def test_production_uses_the_production_host(monkeypatch):
    c, rec = make_client(monkeypatch, {("GET", "/pg/subscriptions/s1"): lambda r: httpx.Response(200, json={"subscription_id": "s1", "subscription_status": "ACTIVE"})}, cashfree_env="production")
    c.fetch_subscription("s1")
    assert str(rec.seen[0].url).startswith("https://api.cashfree.com/pg/subscriptions/s1")


def test_ensure_plan_fetches_first_creates_only_on_404_and_never_reuses_a_different_amount(monkeypatch):
    plan = {"plan_id": "flowqr-growth-79900", "plan_status": "ACTIVE", "plan_recurring_amount": 799.0, "plan_max_amount": 1499.0}
    created = []
    routes = {("GET", "/pg/plans/flowqr-growth-79900"): lambda r: httpx.Response(404, json={"message": "nf", "code": "x"}),
              ("POST", "/pg/plans"): lambda r: (created.append(json.loads(r.content)), httpx.Response(200, json=plan))[1]}
    c, _ = make_client(monkeypatch, routes)
    res = c.ensure_plan(plan_id="flowqr-growth-79900", name="FlowQR Growth", amount_paise=79900, max_amount_paise=149900)
    assert res.amount_paise == 79900 and created[0]["plan_type"] == "PERIODIC" and created[0]["plan_interval_type"] == "MONTH" and created[0]["plan_intervals"] == 1
    assert created[0]["plan_recurring_amount"] == 799.0 and created[0]["plan_max_amount"] == 1499.0 and created[0]["plan_currency"] == "INR"
    # an existing plan is reused without a second create
    c2, rec2 = make_client(monkeypatch, {("GET", "/pg/plans/flowqr-growth-79900"): lambda r: httpx.Response(200, json=plan)})
    assert c2.ensure_plan(plan_id="flowqr-growth-79900", name="x", amount_paise=79900, max_amount_paise=149900).plan_id == "flowqr-growth-79900"
    assert [r.method for r in rec2.seen] == ["GET"]
    # same id, different amount: refused, not silently reused
    c3, _ = make_client(monkeypatch, {("GET", "/pg/plans/flowqr-growth-79900"): lambda r: httpx.Response(200, json={**plan, "plan_recurring_amount": 500.0})})
    with pytest.raises(cf.CashfreeError) as e:
        c3.ensure_plan(plan_id="flowqr-growth-79900", name="x", amount_paise=79900, max_amount_paise=149900)
    assert e.value.code == "plan_amount_mismatch"


def test_manage_calls_use_the_documented_actions(monkeypatch):
    ok = lambda r: httpx.Response(200, json={})  # noqa: E731
    c, rec = make_client(monkeypatch, {("POST", "/pg/subscriptions/s1/manage"): ok, ("POST", "/pg/subscriptions/s1/payments/p1/manage"): ok})
    c.cancel_subscription("s1")
    c.change_plan("s1", "flowqr-pro-149900")
    c.retry_payment("s1", "p1", date(2026, 12, 3))
    bodies = [json.loads(r.content) for r in rec.seen]
    assert bodies[0] == {"subscription_id": "s1", "action": "CANCEL"}
    assert bodies[1] == {"subscription_id": "s1", "action": "CHANGE_PLAN", "action_details": {"plan_id": "flowqr-pro-149900"}}
    assert bodies[2]["action"] == "RETRY" and bodies[2]["action_details"]["next_scheduled_time"] == "2026-12-03T10:00:00+05:30"


def test_payments_are_parsed_including_the_authorisation_and_failure_reason(monkeypatch):
    rows = {"data": [
        {"payment_id": "a1", "cf_payment_id": 1, "payment_type": "AUTH", "payment_status": "SUCCESS", "payment_amount": 1, "payment_initiated_date": "2026-11-20T10:00:00+05:30"},
        {"payment_id": "c1", "cf_payment_id": 2, "payment_type": "CHARGE", "payment_status": "FAILED", "payment_amount": 799, "retry_attempts": 1,
         "failure_details": {"failure_reason": "DEBIT FAILED | Insufficient Funds"}, "authorization_details": {"payment_method": {"card": {}}}}]}
    c, _ = make_client(monkeypatch, {("GET", "/pg/subscriptions/s1/payments"): lambda r: httpx.Response(200, json=rows)})
    auth, charge = c.list_payments("s1")
    assert (auth.payment_type, auth.status, auth.amount_paise) == ("AUTH", "SUCCESS", 100)
    assert (charge.status, charge.amount_paise, charge.retry_attempts, charge.method, charge.failure_reason) == ("FAILED", 79900, 1, "card", "DEBIT FAILED | Insufficient Funds")


def test_errors_carry_only_cashfrees_short_message_and_secrets_never_reach_logs_or_exceptions(monkeypatch, caplog):
    body = {"message": "Invalid request", "code": "request_invalid", "type": "invalid_request_error"}
    c, _ = make_client(monkeypatch, {("GET", "/pg/subscriptions/s1"): lambda r: httpx.Response(400, json=body)})
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(cf.CashfreeError) as e:
            c.fetch_subscription("s1")
    text = str(e.value) + " ".join(r.getMessage() for r in caplog.records)
    assert "CLIENT_SECRET_VALUE" not in text and "CLIENT_ID_VALUE" not in text
    assert e.value.status == 400 and e.value.code == "request_invalid"

    def boom(request):
        raise httpx.ConnectError("secret CLIENT_SECRET_VALUE in the message")
    c2, _ = make_client(monkeypatch, {("GET", "/pg/subscriptions/s1"): boom})
    with pytest.raises(cf.CashfreeError) as e2:
        c2.fetch_subscription("s1")
    assert e2.value.status == 503 and "CLIENT_SECRET_VALUE" not in str(e2.value)


def test_an_unconfigured_client_refuses_to_start(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "billing_provider", "cashfree")
    monkeypatch.setattr(settings, "cashfree_client_id", "")
    monkeypatch.setattr(settings, "cashfree_client_secret", "")
    with pytest.raises(cf.CashfreeNotConfigured):
        cf.HttpCashfreeClient()
    monkeypatch.setattr(settings, "billing_provider", "")
    monkeypatch.setattr(settings, "cashfree_client_id", "a")
    monkeypatch.setattr(settings, "cashfree_client_secret", "b")
    with pytest.raises(cf.CashfreeNotConfigured):  # credentials without BILLING_PROVIDER=cashfree switch nothing on
        cf.HttpCashfreeClient()


# ------------------------------------------------------------------------------------------------------------------------------ production guard
CF = dict(billing_provider="cashfree", cashfree_env="production", cashfree_client_id="id", cashfree_client_secret="secret", razorpay_key_id="", razorpay_key_secret="", razorpay_webhook_secret="")


def test_a_correct_cashfree_production_configuration_has_no_problems():
    assert config_problems(good(**CF)) == []


@pytest.mark.parametrize("over,needle", [
    (dict(cashfree_env="sandbox"), "CASHFREE_SANDBOX_ACK"),
    (dict(cashfree_client_secret=""), "must both be set"),
    (dict(cashfree_client_id=""), "must both be set"),
    (dict(cashfree_env="staging"), "not one of sandbox, production"),
    (dict(cashfree_methods="upi,enach"), "eNACH is not enabled"),
    (dict(cashfree_methods="netbanking"), "may only contain upi and card"),
    (dict(billing_provider="stripe"), "BILLING_PROVIDER"),
    (dict(cashfree_authorization_paise=50), "CASHFREE_AUTHORIZATION_PAISE"),
    (dict(razorpay_key_id="rzp_live_abcdefghij", razorpay_key_secret="x" * 20, razorpay_webhook_secret="w" * 20), "one payment provider only"),
])
def test_the_production_guard_refuses_unsafe_cashfree_settings(over, needle):
    assert any(needle in p for p in config_problems(good(**{**CF, **over}))), over


def test_sandbox_credentials_run_in_production_only_with_the_explicit_acknowledgement_and_production_keys_never_in_staging():
    assert config_problems(good(**{**CF, "cashfree_env": "sandbox", "cashfree_sandbox_ack": True})) == []
    assert any("only allowed with APP_ENV=production" in p for p in config_problems(good(**{**CF, "app_env": "staging"})))


def test_default_settings_switch_nothing_on():
    from app.core.config import Settings
    s = Settings(_env_file=None)
    assert s.billing_provider == "" and not s.cashfree_enabled and not s.cashfree_configured
