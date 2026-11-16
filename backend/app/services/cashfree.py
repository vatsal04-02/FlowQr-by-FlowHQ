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


# ------------------------------------------------------------------------------------------------------------------------------ the real client
class HttpCashfreeClient:
    def __init__(self) -> None:
        if not settings.cashfree_configured:
            raise CashfreeNotConfigured("Cashfree is not configured")
        self._http = httpx.Client(base_url=settings.cashfree_base_url, timeout=20, headers={
            "x-client-id": settings.cashfree_client_id, "x-client-secret": settings.cashfree_client_secret,
            "x-api-version": settings.cashfree_api_version, "accept": "application/json", "content-type": "application/json"})

    def _call(self, method: str, path: str, body: dict | None = None, *, idempotency_key: str | None = None, retries: int = 0) -> Any:
        headers = {"x-idempotency-key": idempotency_key} if idempotency_key else None
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


def get_cashfree() -> CashfreeClient:
    return HttpCashfreeClient()
