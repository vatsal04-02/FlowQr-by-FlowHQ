"""The prepaid price list (1, 3, 6, 12 months) that the pricing screen reads.

Pins what the owner decided on 2026-11-17 and the rules that keep it honest: one place for the amounts, longer terms cost less per month,
no reference ("MRP") price is stored or served, the one-time checkout flag stays off until a one-time checkout exists, and the public
catalogue exposes nothing that could start a subscription.
"""
import json

from app.services import plans

OWNER_DECISION = {
    "starter": {1: 499, 3: 1399, 6: 2699, 12: 4999},
    "growth": {1: 799, 3: 2299, 6: 4299, 12: 7999},
    "pro": {1: 1299, 3: 3699, 6: 6999, 12: 12999},
}


def test_the_price_list_is_exactly_the_owner_decision_in_paise():
    assert plans.TERM_MONTHS == (1, 3, 6, 12)
    assert {c: {m: p // 100 for m, p in t.items()} for c, t in plans.TERM_PRICES_PAISE.items()} == OWNER_DECISION
    for t in plans.TERM_PRICES_PAISE.values():
        assert all(p % 100 == 0 for p in t.values()), "whole rupees only"


def test_every_plan_has_every_term_and_no_unknown_plan_is_priced():
    assert set(plans.TERM_PRICES_PAISE) == set(plans.PLANS)
    for code, t in plans.TERM_PRICES_PAISE.items():
        assert set(t) == set(plans.TERM_MONTHS), code


def test_a_longer_term_always_costs_less_per_month_and_more_in_total():
    for code, t in plans.TERM_PRICES_PAISE.items():
        months = sorted(t)
        for a, b in zip(months, months[1:]):
            assert t[b] / b < t[a] / a, f"{code}: {b} months must be cheaper per month than {a}"
            assert t[b] > t[a], f"{code}: {b} months must cost more in total than {a}"


def test_launch_and_growth_one_month_equal_the_plan_price():
    for code in ("starter", "growth"):
        assert plans.TERM_PRICES_PAISE[code][1] == plans.PLANS[code]["price_paise"]


def test_the_scale_monthly_difference_is_known_and_pinned():
    # Owner's brief says Scale is Rs 1,299 a month; the subscription plan row says Rs 1,499. Prepaid terms use the brief; the subscription price is untouched.
    # If someone reconciles the two, this test must change on purpose, not by accident.
    assert plans.TERM_PRICES_PAISE["pro"][1] == 129900
    assert plans.PLANS["pro"]["price_paise"] == 149900


def test_one_time_checkout_is_closed_unless_switched_on_with_credentials(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "prepaid_checkout_enabled", False)
    assert plans.public_terms()["checkout_open"] is False
    monkeypatch.setattr(settings, "prepaid_checkout_enabled", True)
    monkeypatch.setattr(settings, "cashfree_client_id", "")
    assert plans.public_terms()["checkout_open"] is False  # switched on but no credentials: still closed
    monkeypatch.setattr(settings, "cashfree_client_id", "x")
    monkeypatch.setattr(settings, "cashfree_client_secret", "y")
    assert plans.public_terms()["checkout_open"] is True


def test_the_public_catalogue_serves_the_terms_and_nothing_that_looks_like_a_reference_price(client):
    r = client.get("/api/v1/billing/plans")
    assert r.status_code == 200
    body = r.json()
    terms = body["terms"]
    assert terms["months"] == [1, 3, 6, 12] and terms["checkout_open"] is False  # the test environment has the switch off
    assert {c: {int(m): p // 100 for m, p in t.items()} for c, t in terms["prices_paise"].items()} == OWNER_DECISION
    text = json.dumps(body).lower()
    for word in ("mrp", "reference_price", "list_price", "original_price", "strike", "discount"):
        assert word not in text, word
    # the three plans are still the same three, and the subscription price per plan is unchanged
    assert [(p["code"], p["price_paise"]) for p in body["plans"]] == [("starter", 49900), ("growth", 79900), ("pro", 149900)]
