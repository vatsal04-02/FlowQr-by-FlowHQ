"""Razorpay client behind a Protocol. Real HTTP implementation + signature helpers.

Never simulates payment success: with no keys, `get_razorpay()` raises RazorpayNotConfigured and the API
reports "billing configuration pending".
"""
import hashlib
import hmac
from typing import Protocol

import httpx

from app.core.config import settings

BASE = "https://api.razorpay.com/v1"


class RazorpayNotConfigured(Exception):
    pass


class RazorpayError(Exception):
    def __init__(self, status: int, message: str = ""):
        super().__init__(f"Razorpay error {status}: {message}"[:300])
        self.status = status


class RazorpayClient(Protocol):
    def create_plan(self, *, name: str, amount_paise: int, currency: str, interval: str) -> dict: ...
    def create_subscription(self, *, plan_id: str, total_count: int, start_at: int | None, notes: dict) -> dict: ...
    def fetch_subscription(self, subscription_id: str) -> dict: ...
    def cancel_subscription(self, subscription_id: str, at_cycle_end: bool) -> dict: ...
    def update_subscription(self, subscription_id: str, *, plan_id: str, at_cycle_end: bool) -> dict: ...
    def create_order(self, *, amount_paise: int, receipt: str, notes: dict) -> dict: ...
    def fetch_order(self, order_id: str) -> dict: ...


class HttpRazorpayClient:
    def __init__(self) -> None:
        if not settings.razorpay_configured:
            raise RazorpayNotConfigured("Razorpay keys are not configured")
        self._http = httpx.Client(base_url=BASE, auth=(settings.razorpay_key_id, settings.razorpay_key_secret), timeout=20)

    def _call(self, method: str, path: str, json: dict | None = None) -> dict:
        try:
            r = self._http.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise RazorpayError(503, "network error") from exc
        if r.status_code >= 400:
            msg = ""
            try:
                msg = r.json().get("error", {}).get("description", "")
            except ValueError:
                pass
            raise RazorpayError(r.status_code, msg)
        return r.json()

    def create_plan(self, *, name, amount_paise, currency, interval):
        return self._call("POST", "/plans", {"period": "monthly" if interval == "monthly" else "yearly", "interval": 1,
                                             "item": {"name": name, "amount": amount_paise, "currency": currency}})

    def create_subscription(self, *, plan_id, total_count, start_at, notes):
        body = {"plan_id": plan_id, "total_count": total_count, "customer_notify": 1, "notes": notes}
        if start_at:
            body["start_at"] = start_at
        return self._call("POST", "/subscriptions", body)

    def fetch_subscription(self, subscription_id):
        return self._call("GET", f"/subscriptions/{subscription_id}")

    def cancel_subscription(self, subscription_id, at_cycle_end):
        return self._call("POST", f"/subscriptions/{subscription_id}/cancel", {"cancel_at_cycle_end": 1 if at_cycle_end else 0})

    def update_subscription(self, subscription_id, *, plan_id, at_cycle_end):
        return self._call("PATCH", f"/subscriptions/{subscription_id}",
                          {"plan_id": plan_id, "schedule_change_at": "cycle_end" if at_cycle_end else "now"})

    def create_order(self, *, amount_paise, receipt, notes):
        return self._call("POST", "/orders", {"amount": amount_paise, "currency": "INR", "receipt": receipt[:40], "notes": notes})

    def fetch_order(self, order_id):
        return self._call("GET", f"/orders/{order_id}")


def get_razorpay() -> RazorpayClient:
    """Factory; tests replace this with a labelled fake."""
    return HttpRazorpayClient()


def _hmac(secret: str, message: str | bytes) -> str:
    msg = message.encode() if isinstance(message, str) else message
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def verify_subscription_signature(payment_id: str, subscription_id: str, signature: str) -> bool:
    """Checkout callback: HMAC_SHA256(payment_id|subscription_id, key_secret)."""
    if not settings.razorpay_key_secret or not signature:
        return False
    return hmac.compare_digest(_hmac(settings.razorpay_key_secret, f"{payment_id}|{subscription_id}"), signature)


def verify_order_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Checkout callback for Orders: HMAC_SHA256(order_id|payment_id, key_secret)."""
    if not settings.razorpay_key_secret or not signature:
        return False
    return hmac.compare_digest(_hmac(settings.razorpay_key_secret, f"{order_id}|{payment_id}"), signature)


def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
    if not settings.razorpay_webhook_secret or not signature:
        return False
    return hmac.compare_digest(_hmac(settings.razorpay_webhook_secret, raw_body), signature)
