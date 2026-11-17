"""The temporary per-business price override (the Rs 1 Growth test offer).

It must be impossible for it to leak: only the business it was created for sees or pays it, only once, only until it expires, only ever lower than the list, decided by the SERVER, and the
permanent price list and the public price answer must never change because of it."""
import json
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient

from app import prepaid_cli
from app.core.db import SessionLocal, set_rls_context
from app.main import app
from app.models.base import utcnow
from app.services import plans as plans_svc
from app.services import prepaid
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_prepaid_checkout import (  # noqa: F401  (fixtures and helpers shared with the main prepaid tests)
    PHONE, checkout, deliver_pg, entitlements_of, events_of, n_orders, order_row, payments_of, pg, sub_of, verify,
)

LIST = 79900


def override(biz, *, plan="growth", months=1, amount=100, hours=48, reason="owner payment test (temporary)"):
    assert prepaid_cli.create(str(biz.tenant_id), plan, months, amount, hours, reason) == 0


def rows(biz):
    return owner_query("SELECT plan_code, months, amount_paise, list_price_paise, revoked_at IS NOT NULL, used_order_id IS NOT NULL, expires_at FROM prepaid_price_overrides WHERE tenant_id = :t ORDER BY created_at", t=biz.tenant_id)


def test_the_override_prices_the_order_at_one_rupee_on_the_server_and_records_the_list_price_separately(pg):
    biz = make_business()
    override(biz)
    r = checkout(biz, "growth", 1, amount_paise=79900, price=79900)  # whatever the browser claims is ignored
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["amount_paise"] == 100 and d["list_price_paise"] == LIST and d["override"] is True
    assert pg.orders[d["order_id"]]["amount"] == 100  # Cashfree is asked for exactly Rs 1
    row = owner_query("SELECT amount_paise, list_price_paise, override_id IS NOT NULL FROM prepaid_orders WHERE order_id = :o", o=d["order_id"])[0]
    assert row == (100, LIST, True)


def test_other_businesses_and_other_terms_and_plans_pay_the_normal_price(pg):
    biz, other = make_business("Test Owner"), make_business("Some Customer")
    override(biz)
    assert checkout(other, "growth", 1).json()["amount_paise"] == LIST  # another business never sees or gets it
    assert checkout(biz, "growth", 3).json()["amount_paise"] == plans_svc.TERM_PRICES_PAISE["growth"][3] == 229900  # same business, other term: unchanged
    assert checkout(biz, "growth", 6).json()["amount_paise"] == 429900
    assert checkout(biz, "growth", 12).json()["amount_paise"] == 799900
    assert checkout(biz, "starter", 1).json()["amount_paise"] == 49900 and checkout(biz, "pro", 1).json()["amount_paise"] == 129900


def test_the_public_price_list_and_the_permanent_prices_never_show_or_change_because_of_an_override(pg):
    biz = make_business()
    override(biz)
    body = TestClient(app, base_url="http://testserver").get("/api/v1/billing/plans").json()
    assert body["terms"]["prices_paise"]["growth"]["1"] == LIST and "100" not in json.dumps(body["terms"]["prices_paise"])
    assert plans_svc.TERM_PRICES_PAISE["growth"][1] == LIST
    assert [(p["code"], p["price_paise"]) for p in body["plans"]] == [("starter", 49900), ("growth", 79900), ("pro", 149900)]


def test_only_the_owning_business_sees_the_offer_in_its_own_pricing_screen(pg):
    biz, other = make_business("Test Owner"), make_business("Some Customer")
    override(biz)
    mine = biz.get("/billing/prepaid/offers").json()["offers"]
    assert len(mine) == 1 and mine[0]["plan"] == "growth" and mine[0]["months"] == 1 and mine[0]["amount_paise"] == 100 and mine[0]["list_price_paise"] == LIST and mine[0]["label"] == "Test price"
    assert other.get("/billing/prepaid/offers").json()["offers"] == []
    assert TestClient(app, base_url="http://testserver").get("/api/v1/billing/prepaid/offers").status_code in (401, 403)


def test_a_real_one_rupee_payment_grants_growth_for_exactly_one_month_and_consumes_the_offer(pg):
    biz = make_business()
    override(biz)
    d = checkout(biz, "growth", 1).json()
    pg.pay(d["order_id"])
    r = verify(biz, d["order_id"]).json()
    assert r["state"] == "paid" and r["amount_paise"] == 100
    s = sub_of(biz)
    assert (s["status"], s["plan"], s["provider"]) == ("active", "growth", "prepaid")
    assert s["current_period_end"] == prepaid.add_months(s["current_period_start"], 1)  # one calendar month from the activation instant
    assert payments_of(biz) == [("subscription", "captured", 100, "PREPAID", "cashfree")]
    e = entitlements_of(biz)
    assert e.active and e.plan == "growth" and "keyword_tracking" in e.features
    used = rows(biz)[0]
    assert used[5] is True  # consumed by the first paid order
    assert order_row(d["order_id"])["amount_paise"] == 100
    assert owner_query("SELECT list_price_paise FROM prepaid_orders WHERE order_id = :o", o=d["order_id"])[0][0] == LIST
    assert verify(biz, d["order_id"]).json()["state"] == "paid" and deliver_pg(d["order_id"]).status_code == 200  # replays add nothing
    assert len(payments_of(biz)) == 1 and events_of(biz).count("activated") == 1


def test_after_it_is_used_the_next_purchase_is_at_the_list_price_even_once_the_term_has_ended(pg):
    biz = make_business()
    override(biz)
    d = checkout(biz, "growth", 1).json()
    pg.pay(d["order_id"])
    verify(biz, d["order_id"])
    assert checkout(biz, "growth", 1).status_code == 409  # a running term blocks a second purchase
    owner_exec("UPDATE subscriptions SET current_period_end = now() - interval '1 day' WHERE tenant_id = :t", t=biz.tenant_id)
    again = checkout(biz, "growth", 1).json()
    assert again["amount_paise"] == LIST and again["override"] is False
    assert biz.get("/billing/prepaid/offers").json()["offers"] == []


def test_two_orders_under_one_offer_cannot_both_be_granted(pg):
    biz = make_business()
    override(biz)
    a, b = checkout(biz, "growth", 1).json(), checkout(biz, "growth", 1).json()  # two tabs
    pg.pay(a["order_id"])
    pg.pay(b["order_id"])
    assert verify(biz, a["order_id"]).json()["state"] == "paid"
    end = sub_of(biz)["current_period_end"]
    assert verify(biz, b["order_id"]).json()["state"] == "mismatch"  # paid, but the single-use offer was already consumed: for a person to refund, no extra time
    assert sub_of(biz)["current_period_end"] == end and len(payments_of(biz)) == 1
    assert owner_query("SELECT count(*) FROM audit_logs WHERE tenant_id = :t AND action = 'billing.prepaid_override_reused'", t=biz.tenant_id)[0][0] == 1


def test_an_expired_or_revoked_offer_is_ignored(pg):
    biz = make_business()
    override(biz)
    owner_exec("UPDATE prepaid_price_overrides SET expires_at = now() - interval '1 minute' WHERE tenant_id = :t", t=biz.tenant_id)
    assert checkout(biz, "growth", 1).json()["amount_paise"] == LIST and biz.get("/billing/prepaid/offers").json()["offers"] == []
    override(biz)
    owner_exec("UPDATE prepaid_price_overrides SET revoked_at = now() WHERE tenant_id = :t AND expires_at > now()", t=biz.tenant_id)
    assert checkout(biz, "growth", 1).json()["amount_paise"] == LIST


def test_an_unpaid_failed_or_pending_offer_order_grants_nothing_and_leaves_the_offer_available(pg):
    biz = make_business()
    override(biz)
    before = sub_of(biz)
    d = checkout(biz, "growth", 1).json()
    assert verify(biz, d["order_id"]).json()["state"] == "open"
    pg.pay(d["order_id"], "FAILED", reason="declined")
    assert verify(biz, d["order_id"]).json()["state"] == "failed"
    assert sub_of(biz) == before and payments_of(biz) == []
    assert rows(biz)[0][5] is False  # not consumed: the owner can try again
    assert checkout(biz, "growth", 1).json()["amount_paise"] == 100


def test_the_cli_refuses_anything_that_could_overcharge_or_never_expire(capsys):
    biz = make_business()
    t = str(biz.tenant_id)
    assert prepaid_cli.create(t, "growth", 1, LIST, 48, "must be cheaper than the list") == 2  # equal to the list: not a discount
    assert prepaid_cli.create(t, "growth", 1, 100000, 48, "higher than the list price") == 2
    assert prepaid_cli.create(t, "growth", 1, 50, 48, "below Rs 1 is not allowed") == 2
    assert prepaid_cli.create(t, "growth", 1, 100, 0, "must expire in the future") == 2
    assert prepaid_cli.create(t, "growth", 1, 100, 24 * 30, "may not run for a month") == 2
    assert prepaid_cli.create(t, "growth", 1, 100, 48, "short") == 2  # a reason is mandatory
    assert prepaid_cli.create(t, "growth", 2, 100, 48, "not a listed term at all") == 2
    assert prepaid_cli.create(str(uuid.uuid4()), "growth", 1, 100, 48, "no such business exists") == 2
    assert rows(biz) == []


def test_creating_a_second_offer_revokes_the_first_so_only_one_is_live(pg):
    biz = make_business()
    override(biz, amount=100)
    override(biz, amount=200)
    r = rows(biz)
    assert len(r) == 2 and r[0][4] is True and r[1][4] is False
    assert checkout(biz, "growth", 1).json()["amount_paise"] == 200


def test_row_level_security_hides_one_businesss_offers_from_another(pg):
    from sqlalchemy import text
    a, b = make_business("Alpha Test"), make_business("Beta Test")
    override(a)
    with SessionLocal() as db:
        db.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(b.tenant_id)})
        db.execute(text("SELECT set_config('app.bypass_rls', 'off', true)"))
        assert db.execute(text("SELECT count(*) FROM prepaid_price_overrides")).scalar() == 0


def test_the_database_itself_refuses_a_price_that_is_not_cheaper(pg):
    biz = make_business()
    import pytest
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        owner_exec("INSERT INTO prepaid_price_overrides (id, tenant_id, plan_code, months, amount_paise, list_price_paise, reason, expires_at) VALUES (gen_random_uuid(), :t, 'growth', 1, 79900, 79900, 'x', now() + interval '1 day')", t=biz.tenant_id)
