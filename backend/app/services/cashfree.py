"""Cashfree Subscriptions: the HTTP client, the webhook signature check and the parsing of Cashfree's answers. Nothing here knows about FlowQR's database.

What is DOCUMENTED (https://www.cashfree.com/docs/api-reference/payments/latest/subscription/overview) and used here:
  * base URLs https://sandbox.cashfree.com/pg and https://api.cashfree.com/pg; headers x-client-id, x-client-secret, x-api-version, optional x-idempotency-key (a UUID)
  * POST /plans, GET /plans/{id}; POST /subscriptions, GET /subscriptions/{id}; POST /subscriptions/{id}/manage (CANCEL | PAUSE | ACTIVATE | CHANGE_PLAN);
    GET /subscriptions/{id}/payments; POST /subscriptions/{id}/payments/{payment_id}/manage (CANCEL | RETRY, RETRY needs action_details.next_scheduled_time)
  * subscription_first_charge_time (ISO 8601, IST) for PERIODIC plans; authorization_details {authorization_amount, authorization_amount_refund, payment_methods}
  * webhooks: headers x-webhook-signature and x-webhook-timestamp; signature = Base64(HMAC-SHA256(secret, timestamp + rawBody)); a 5-minute window is recommended
What is NOT documented, and therefore NOT assumed (each is checked in the sandbox before it is relied on): a webhook EVENT ID (there is none: see `dedupe_key`), webhook retry timing,
ordering guarantees, duplicate plan or subscription id errors, the format of x-webhook-timestamp (several are accepted below, anything else is refused), and which secret signs webhooks
(CASHFREE_WEBHOOK_SECRET, defaulting to the client secret).

Secrets: the client id and secret are read from settings and sent only as headers. They are never logged, never put in an exception message and never returned to a caller. Error text kept
from Cashfree is only its short `message` field, trimmed. A customer's phone, email or bank detail is never logged by this module."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.core.config import settings

log = logging.getLogger("flowqr.cashfree")
IST = timezone(timedelta(hours=5, minutes=30))


class CashfreeNotConfigured(Exception):
    pass


class CashfreeError(Exception):
    """A failed call to Cashfree. `message` is Cashfree's own short message (or a fixed phrase); never a request body, a header or a secret."""

    def __init__(self, status: int, code: str = "", message: str = ""):
        super().__init__(f"Cashfree {status} {code}: {message}"[:300])
        self.status, self.code, self.message = status, code, (message or "")[:200]


class WebhookError(Exception):
    """A webhook that must be refused. `reason` is a short fixed code (missing_headers, bad_signature, stale_timestamp, bad_timestamp, bad_payload, not_configured)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ------------------------------------------------------------------------------------------------------------------------------ money and time
def to_rupees(paise: int) -> float:
    return float(Decimal(int(paise)) / Decimal(100))


def to_paise(rupees: Any) -> int:
    return int((Decimal(str(rupees)) * 100).to_integral_value())


def ist_iso(dt: datetime) -> str:
    """Cashfree stores and expects IST; send an unambiguous ISO 8601 string with the offset."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).isoformat(timespec="seconds")


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)  # Cashfree timestamps without an offset are IST


def norm_status(s: Any) -> str:
    """Cashfree's own FAQ writes 'ON HOLD' while its webhook page writes ON_HOLD: accept both."""
    return str(s or "").strip().upper().replace(" ", "_")


# ------------------------------------------------------------------------------------------------------------------------------ typed results
@dataclass(frozen=True)
class Customer:
    name: str
    email: str
    phone: str


@dataclass(frozen=True)
class PlanResult:
    plan_id: str
    status: str
    amount_paise: int | None
    max_amount_paise: int | None


@dataclass(frozen=True)
class SubscriptionResult:
    subscription_id: str
    cf_id: str | None
    status: str  # normalised: INITIALIZED, BANK_APPROVAL_PENDING, ACTIVE, ON_HOLD, ...
    session_id: str | None = None
    plan_id: str | None = None
    first_charge_at: datetime | None = None
    next_charge_at: datetime | None = None
    authorization_status: str | None = None


@dataclass(frozen=True)
class PaymentResult:
    payment_id: str
    cf_payment_id: str | None
    payment_type: str  # AUTH | CHARGE
    status: str  # normalised: SUCCESS, FAILED, PENDING, INITIALIZED, CANCELLED, USER_DROPPED
    amount_paise: int
    scheduled_for: datetime | None = None
    initiated_at: datetime | None = None
    failure_reason: str | None = None
    method: str | None = None
    retry_attempts: int = 0


@dataclass(frozen=True)
class OrderResult:
    """A Cashfree Payment Gateway ORDER (one-time payment). `status` is normalised: ACTIVE (payable), PAID, EXPIRED, TERMINATED."""
    order_id: str
    cf_order_id: str | None
    status: str
    amount_paise: int | None = None
    currency: str | None = None
    session_id: str | None = None  # payment_session_id: returned when the order is created and handed to the browser once; it is never stored or logged


@dataclass(frozen=True)
class OrderPayment:
    """One attempt to pay an order. `status` is normalised: SUCCESS, FAILED, PENDING, NOT_ATTEMPTED, USER_DROPPED, CANCELLED, VOID."""
    cf_payment_id: str
    status: str
    amount_paise: int
    currency: str | None = None
    method: str | None = None  # only the kind: upi, card, netbanking, app, ...
    failure_reason: str | None = None
    paid_at: datetime | None = None


@dataclass(frozen=True)
class WebhookEnvelope:
    type: str
    event_time: datetime | None
    data: dict = field(default_factory=dict)
    subscription_id: str | None = None
    payment_id: str | None = None
    status: str | None = None
    dedupe_key: str = ""
    payload_hash: str = ""


# ------------------------------------------------------------------------------------------------------------------------------ the client contract
class CashfreeClient(Protocol):
    def ensure_plan(self, *, plan_id: str, name: str, amount_paise: int, max_amount_paise: int) -> PlanResult: ...
    def create_subscription(self, *, subscription_id: str, plan_id: str, customer: Customer, first_charge_at: datetime, authorization_paise: int,
                            refund_authorization: bool, methods: list[str], return_url: str, idempotency_key: str) -> SubscriptionResult: ...
    def fetch_subscription(self, subscription_id: str) -> SubscriptionResult: ...
    def list_payments(self, subscription_id: str) -> list[PaymentResult]: ...
    def cancel_subscription(self, subscription_id: str) -> None: ...
    def change_plan(self, subscription_id: str, plan_id: str) -> None: ...
    def retry_payment(self, subscription_id: str, payment_id: str, next_attempt_on: date) -> None: ...
    # --- one-time Payment Gateway orders (prepaid plans)
    def create_order(self, *, order_id: str, amount_paise: int, customer_id: str, customer: Customer, return_url: str, notify_url: str | None, expires_at: datetime,
                     note: str, idempotency_key: str) -> OrderResult: ...
    def fetch_order(self, order_id: str) -> OrderResult: ...
    def list_order_payments(self, order_id: str) -> list[OrderPayment]: ...


# ------------------------------------------------------------------------------------------------------------------------------ parsing
def _sub_from(d: dict) -> SubscriptionResult:
    auth = d.get("authorisation_details") or d.get("authorization_details") or {}
    plan = d.get("plan_details") or {}
    return SubscriptionResult(
        subscription_id=str(d.get("subscription_id") or ""), cf_id=(str(d["cf_subscription_id"]) if d.get("cf_subscription_id") is not None else None),
        status=norm_status(d.get("subscription_status")), session_id=d.get("subscription_session_id"), plan_id=plan.get("plan_id"),
        first_charge_at=parse_time(d.get("subscription_first_charge_time")), next_charge_at=parse_time(d.get("next_schedule_date")),
        authorization_status=norm_status(auth.get("authorization_status")) or None)


def _method_name(pm: Any) -> str | None:
    if isinstance(pm, dict) and pm:
        return next(iter(pm.keys()))  # e.g. {"upi": {...}} or {"card": {...}}
    return None


def _pay_from(d: dict) -> PaymentResult:
    fail = d.get("failure_details") or {}
    auth = d.get("authorization_details") or {}
    return PaymentResult(
        payment_id=str(d.get("payment_id") or ""), cf_payment_id=(str(d["cf_payment_id"]) if d.get("cf_payment_id") is not None else None),
        payment_type=norm_status(d.get("payment_type")) or "CHARGE", status=norm_status(d.get("payment_status")),
        amount_paise=to_paise(d.get("payment_amount") or 0), scheduled_for=parse_time(d.get("payment_schedule_date")),
        initiated_at=parse_time(d.get("payment_initiated_date")), failure_reason=(fail.get("failure_reason") if isinstance(fail, dict) else None),
        method=_method_name(auth.get("payment_method")) if isinstance(auth, dict) else None, retry_attempts=int(d.get("retry_attempts") or 0))


def _order_from(d: dict) -> OrderResult:
    amt = d.get("order_amount")
    return OrderResult(order_id=str(d.get("order_id") or ""), cf_order_id=(str(d["cf_order_id"]) if d.get("cf_order_id") is not None else None), status=norm_status(d.get("order_status")),
                       amount_paise=to_paise(amt) if amt is not None else None, currency=(str(d["order_currency"]).upper() if d.get("order_currency") else None),
                       session_id=d.get("payment_session_id"))


def _order_payment_from(d: dict) -> OrderPayment:
    err = d.get("error_details") or {}
    return OrderPayment(cf_payment_id=str(d.get("cf_payment_id") or ""), status=norm_status(d.get("payment_status")), amount_paise=to_paise(d.get("payment_amount") or 0),
                        currency=(str(d["payment_currency"]).upper() if d.get("payment_currency") else None), method=_method_name(d.get("payment_method")),
                        failure_reason=((err.get("error_description") or err.get("error_reason")) if isinstance(err, dict) else None) or None, paid_at=parse_time(d.get("payment_time")))


# ------------------------------------------------------------------------------------------------------------------------------ webhooks
def _ts_from_header(value: str) -> datetime:
    v = value.strip()
    if v.isdigit():
        n = int(v)
        return datetime.fromtimestamp(n / 1000 if n > 10_000_000_000 else n, tz=timezone.utc)  # milliseconds or seconds
    dt = parse_time(v)
    if dt is None:
        raise WebhookError("bad_timestamp")
    return dt


def verify_webhook(raw_body: bytes, signature: str | None, timestamp: str | None, *, secret: str | None = None, now: datetime | None = None,
                   tolerance_seconds: int | None = None) -> datetime:
    """Raises WebhookError unless the request is authentic and fresh; returns the signed timestamp. Runs on the RAW bytes: never parse or re-serialise before this."""
    secret = settings.cashfree_webhook_key if secret is None else secret
    if not secret:
        raise WebhookError("not_configured")
    if not signature or not timestamp:
        raise WebhookError("missing_headers")
    expected = base64.b64encode(hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + raw_body, hashlib.sha256).digest()).decode("ascii")
    if not hmac.compare_digest(expected, signature.strip()):
        raise WebhookError("bad_signature")
    sent = _ts_from_header(timestamp)  # only reached for an authentic request, so a bad value here is a provider format change, not an attack
    now = now or datetime.now(timezone.utc)
    tol = settings.cashfree_webhook_tolerance_seconds if tolerance_seconds is None else tolerance_seconds
    if abs((now - sent).total_seconds()) > tol:
        raise WebhookError("stale_timestamp")
    return sent


def sign_webhook(raw_body: bytes, timestamp: str, secret: str) -> str:
    """The same algorithm, for tests and for the local sandbox harness. Never used on the receiving path."""
    return base64.b64encode(hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + raw_body, hashlib.sha256).digest()).decode("ascii")


def dedupe_key(etype: str, subscription_id: str | None, payment_id: str | None, status: str | None, event_time: str | None) -> str:
    """Cashfree sends NO event id (verified against its Events page). The key is built only from fields that are really in the payload: the event type, our subscription id, the payment id,
    the status and Cashfree's own event_time. Two different events cannot share it (they differ in status or time); a repeated delivery is identical in all five."""
    return hashlib.sha256("|".join([etype, subscription_id or "", payment_id or "", status or "", event_time or ""]).encode("utf-8")).hexdigest()


def parse_envelope(raw_body: bytes) -> WebhookEnvelope:
    try:
        doc = json.loads(raw_body)
    except ValueError as exc:
        raise WebhookError("bad_payload") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("type"), str) or not isinstance(doc.get("data", {}), dict):
        raise WebhookError("bad_payload")
    data = doc.get("data") or {}
    nested = data.get("subscription_details") or (data.get("subscription_status_webhook") or {}).get("subscription_details") or {}
    sid = data.get("subscription_id") or nested.get("subscription_id")
    pid = data.get("payment_id")
    status = data.get("payment_status") or nested.get("subscription_status") or (data.get("authorization_details") or {}).get("authorization_status")
    etime = doc.get("event_time") if isinstance(doc.get("event_time"), str) else None
    return WebhookEnvelope(
        type=doc["type"], event_time=parse_time(etime), data=data, subscription_id=str(sid) if sid else None, payment_id=str(pid) if pid else None,
        status=norm_status(status) or None, dedupe_key=dedupe_key(doc["type"], str(sid) if sid else None, str(pid) if pid else None, norm_status(status) or None, etime),
        payload_hash=hashlib.sha256(raw_body).hexdigest())


@dataclass(frozen=True)
class PgWebhook:
    """A Payment Gateway webhook (PAYMENT_SUCCESS_WEBHOOK, PAYMENT_FAILED_WEBHOOK, PAYMENT_USER_DROPPED_WEBHOOK, ...). Only used as a HINT that an order changed: the order id is read from it,
    and the truth is then fetched from Cashfree. Nothing in the payload grants access."""
    type: str
    order_id: str | None
    cf_payment_id: str | None
    payment_status: str | None
    event_time: str | None
    dedupe_key: str
    payload_hash: str


def parse_pg_webhook(raw_body: bytes) -> PgWebhook:
    try:
        doc = json.loads(raw_body)
    except ValueError as exc:
        raise WebhookError("bad_payload") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("type"), str):
        raise WebhookError("bad_payload")
    data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
    order = data.get("order") if isinstance(data.get("order"), dict) else {}
    pay = data.get("payment") if isinstance(data.get("payment"), dict) else {}
    oid = order.get("order_id")
    cfp = pay.get("cf_payment_id")
    status = norm_status(pay.get("payment_status")) or None
    etime = doc.get("event_time") if isinstance(doc.get("event_time"), str) else None
    key = hashlib.sha256("|".join(["pg", doc["type"], str(oid or ""), str(cfp or ""), status or "", etime or ""]).encode("utf-8")).hexdigest()
    return PgWebhook(type=doc["type"], order_id=str(oid) if oid else None, cf_payment_id=str(cfp) if cfp else None, payment_status=status, event_time=etime, dedupe_key=key,
                     payload_hash=hashlib.sha256(raw_body).hexdigest())


# ------------------------------------------------------------------------------------------------------------------------------ the real client
class HttpCashfreeClient:
    def __init__(self) -> None:
        if not (settings.cashfree_configured or settings.prepaid_configured):
            raise CashfreeNotConfigured("Cashfree is not configured")
        self._http = httpx.Client(base_url=settings.cashfree_base_url, timeout=20, headers={
            "x-client-id": settings.cashfree_client_id, "x-client-secret": settings.cashfree_client_secret,
            "x-api-version": settings.cashfree_api_version, "accept": "application/json", "content-type": "application/json"})

    def _call(self, method: str, path: str, body: dict | None = None, *, idempotency_key: str | None = None, retries: int = 0, api_version: str | None = None) -> Any:
        headers = {"x-idempotency-key": idempotency_key} if idempotency_key else {}
        if api_version:
            headers["x-api-version"] = api_version
        headers = headers or None
        last: Exception | None = None
        for _ in range(retries + 1):
            try:
                r = self._http.request(method, path, json=body, headers=headers)
                break
            except httpx.HTTPError as exc:  # network trouble: never include the request in the message
                last = exc
        else:
            raise CashfreeError(503, "network_error", "Could not reach Cashfree") from last
        if r.status_code >= 400:
            code = msg = ""
            try:
                j = r.json()
                code, msg = str(j.get("code") or j.get("type") or ""), str(j.get("message") or "")
            except ValueError:
                pass
            log.warning("Cashfree %s %s -> %s %s", method, path.split("?")[0], r.status_code, code)  # path and code only: no body, no headers
            raise CashfreeError(r.status_code, code, msg)
        if not r.content:
            return {}
        return r.json()

    def ensure_plan(self, *, plan_id: str, name: str, amount_paise: int, max_amount_paise: int) -> PlanResult:
        """Idempotent: fetch first; create only when Cashfree says the plan does not exist. An existing plan with a DIFFERENT amount is an error, never silently reused (a plan's amount cannot be edited)."""
        def parse(d: dict) -> PlanResult:
            return PlanResult(plan_id=d.get("plan_id", plan_id), status=norm_status(d.get("plan_status")),
                              amount_paise=to_paise(d["plan_recurring_amount"]) if d.get("plan_recurring_amount") is not None else None,
                              max_amount_paise=to_paise(d["plan_max_amount"]) if d.get("plan_max_amount") is not None else None)
        try:
            found = parse(self._call("GET", f"/plans/{plan_id}", retries=2))
        except CashfreeError as exc:
            # Observed in the Cashfree Sandbox (2026-11-16): a missing plan is answered with HTTP 400 and code `plan_not_found`, NOT 404. Both mean "does not exist"; any other error is real.
            if exc.status != 404 and exc.code != "plan_not_found":
                raise
            found = None
        if found is not None:
            if found.amount_paise != amount_paise:
                raise CashfreeError(409, "plan_amount_mismatch", "A Cashfree plan with this id exists with a different amount")
            return found
        body = {"plan_id": plan_id, "plan_name": name[:40], "plan_type": "PERIODIC", "plan_currency": "INR", "plan_recurring_amount": to_rupees(amount_paise),
                "plan_max_amount": to_rupees(max_amount_paise), "plan_interval_type": "MONTH", "plan_intervals": 1,
                "plan_note": "FlowQR monthly subscription"}
        return parse(self._call("POST", "/plans", body, idempotency_key=str(uuid.uuid5(uuid.NAMESPACE_URL, f"flowqr-plan:{plan_id}:{amount_paise}"))))

    def create_subscription(self, *, subscription_id, plan_id, customer, first_charge_at, authorization_paise, refund_authorization, methods, return_url, idempotency_key) -> SubscriptionResult:
        body = {
            "subscription_id": subscription_id,
            "customer_details": {"customer_name": customer.name[:100], "customer_email": customer.email, "customer_phone": customer.phone},
            "plan_details": {"plan_id": plan_id},
            "authorization_details": {"authorization_amount": to_rupees(authorization_paise), "authorization_amount_refund": bool(refund_authorization), "payment_methods": methods},
            "subscription_first_charge_time": ist_iso(first_charge_at),
            "subscription_meta": {"return_url": return_url, "notification_channel": ["EMAIL", "SMS"]},
        }
        return _sub_from(self._call("POST", "/subscriptions", body, idempotency_key=idempotency_key))

    def fetch_subscription(self, subscription_id: str) -> SubscriptionResult:
        return _sub_from(self._call("GET", f"/subscriptions/{subscription_id}", retries=2))

    def list_payments(self, subscription_id: str) -> list[PaymentResult]:
        j = self._call("GET", f"/subscriptions/{subscription_id}/payments", retries=2)
        rows = j.get("data", []) if isinstance(j, dict) else j
        return [_pay_from(x) for x in (rows or []) if isinstance(x, dict)]

    def cancel_subscription(self, subscription_id: str) -> None:
        self._call("POST", f"/subscriptions/{subscription_id}/manage", {"subscription_id": subscription_id, "action": "CANCEL"})

    def change_plan(self, subscription_id: str, plan_id: str) -> None:
        self._call("POST", f"/subscriptions/{subscription_id}/manage", {"subscription_id": subscription_id, "action": "CHANGE_PLAN", "action_details": {"plan_id": plan_id}})

    def retry_payment(self, subscription_id: str, payment_id: str, next_attempt_on: date) -> None:
        when = datetime(next_attempt_on.year, next_attempt_on.month, next_attempt_on.day, 10, 0, tzinfo=IST)
        self._call("POST", f"/subscriptions/{subscription_id}/payments/{payment_id}/manage",
                   {"subscription_id": subscription_id, "payment_id": payment_id, "action": "RETRY", "action_details": {"next_scheduled_time": ist_iso(when)}})


    # ------------------------------------------------------------------------------------------------------------------------ one-time orders (Payment Gateway, not Subscriptions)
    def create_order(self, *, order_id, amount_paise, customer_id, customer, return_url, notify_url, expires_at, note, idempotency_key) -> OrderResult:
        meta = {"return_url": return_url}
        if notify_url:
            meta["notify_url"] = notify_url
        body = {"order_id": order_id, "order_amount": to_rupees(amount_paise), "order_currency": "INR",
                "customer_details": {"customer_id": customer_id, "customer_name": customer.name[:100], "customer_email": customer.email, "customer_phone": customer.phone},
                "order_meta": meta, "order_expiry_time": expires_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "order_note": note[:200]}
        return _order_from(self._call("POST", "/orders", body, idempotency_key=idempotency_key, api_version=settings.cashfree_pg_api_version))

    def fetch_order(self, order_id: str) -> OrderResult:
        return _order_from(self._call("GET", f"/orders/{order_id}", retries=2, api_version=settings.cashfree_pg_api_version))

    def list_order_payments(self, order_id: str) -> list[OrderPayment]:
        j = self._call("GET", f"/orders/{order_id}/payments", retries=2, api_version=settings.cashfree_pg_api_version)
        rows = j if isinstance(j, list) else (j.get("data", []) if isinstance(j, dict) else [])
        return [_order_payment_from(x) for x in (rows or []) if isinstance(x, dict)]


def get_cashfree() -> CashfreeClient:
    return HttpCashfreeClient()
