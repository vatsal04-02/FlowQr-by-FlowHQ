"""Migration 0037 (Cashfree billing columns, plan display names Launch / Growth / Scale): one clean path from production's revision 0036, additive, reversible, safe for existing rows (production's four trial subscriptions hold NULL in the dropped card_status). Runs real alembic against the PostgreSQL test database."""
import os
import subprocess
import sys

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.conftest import make_business, owner_exec, owner_query

BACKEND = os.path.dirname(os.path.dirname(__file__))
NEW = {
    "billing_plans": {"cashfree_plan_id"},
    "subscriptions": {"provider", "cashfree_subscription_id", "cashfree_cf_subscription_id", "authorization_status", "trial_entitlement", "trial_started_at", "first_charge_at", "next_charge_at", "last_provider_sync_at"},
    "payments": {"provider", "cashfree_payment_id", "cashfree_cf_payment_id", "payment_type", "period_start", "period_end", "failure_reason"},
    "webhook_events": {"subscription_ref", "payment_ref", "payload_hash", "attempts", "last_error", "provider_event_time"},
}


def alembic(*a):
    subprocess.run([sys.executable, "-m", "alembic", *a], check=True, env={**os.environ}, cwd=BACKEND)


def cols(table):
    return {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = :t", t=table)}


def present():
    return all(c in cols(t) for t, cs in NEW.items() for c in cs)


def absent():
    return not any(c in cols(t) for t, cs in NEW.items() for c in cs)


def plans():
    return {r[0]: (r[1], r[2]) for r in owner_query("SELECT code, name, price_paise FROM billing_plans WHERE code IN ('starter', 'growth', 'pro')")}


def test_the_history_is_one_straight_line_from_production_head_0036():
    sd = ScriptDirectory.from_config(Config(os.path.join(BACKEND, "alembic.ini")))
    assert sd.get_heads() == ["0053"]  # one head (0040-0043 sit on 0037; 0044 = consent grants; 0045 = privacy and account lifecycle; 0046 = admin-managed businesses; 0047 = website builder; 0048 = WhatsApp foundation; 0049 = WhatsApp messaging; 0050 = WhatsApp campaign manager)
    assert sd.get_revision("0053").down_revision == "0052" and sd.get_revision("0052").down_revision == "0051" and sd.get_revision("0051").down_revision == "0050" and sd.get_revision("0050").down_revision == "0049" and sd.get_revision("0049").down_revision == "0048" and sd.get_revision("0048").down_revision == "0047" and sd.get_revision("0047").down_revision == "0046" and sd.get_revision("0046").down_revision == "0045" and sd.get_revision("0045").down_revision == "0044" and sd.get_revision("0044").down_revision == "0043"
    assert sd.get_revision("0037").down_revision == "0036"  # production is stamped 0036: this is the next revision after it
    chain = [r.revision for r in sd.walk_revisions()]
    assert chain[:18] == ["0053", "0052", "0051", "0050", "0049", "0048", "0047", "0046", "0045", "0044", "0043", "0042", "0041", "0040", "0037", "0036", "0035", "0033"]  # newest first
    assert not [f for f in os.listdir(os.path.join(BACKEND, "alembic", "versions")) if f.startswith("0034")]  # no stray second file with the old id


def test_at_head_everything_is_present_and_the_plans_have_their_final_names_and_unchanged_prices_and_codes():
    assert present()
    assert plans() == {"starter": ("Launch", 49900), "growth": ("Growth", 79900), "pro": ("Scale", 149900)}
    assert owner_query("SELECT count(*) FROM billing_plans WHERE code IN ('starter','growth','pro')")[0][0] == 3  # no duplicate plan was created
    assert "card_status" in cols("subscriptions")  # kept on purpose: the running release still reads it, so an application rollback needs no database change
    for table in ("subscriptions", "payments"):  # row-level security still forced on the tenant tables that gained columns
        assert owner_query("SELECT relforcerowsecurity FROM pg_class WHERE relname = :t", t=table)[0][0] is True
    assert owner_query("SELECT 1 FROM pg_constraint WHERE conname = 'uq_subscriptions_cashfree_subscription_id'") and owner_query("SELECT 1 FROM pg_constraint WHERE conname = 'uq_payments_cashfree_payment_id'")


def test_downgrade_to_0036_removes_only_the_new_columns_restores_the_old_names_and_card_status_then_upgrade_restores_it_all():
    biz = make_business()  # a real subscription row that must survive both directions
    before_rows = owner_query("SELECT count(*) FROM subscriptions")[0][0]
    before_pay = owner_query("SELECT count(*) FROM payments")[0][0]
    before_plan = owner_query("SELECT plan, status FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0]
    alembic("downgrade", "0036")
    try:
        assert absent() and "card_status" in cols("subscriptions")  # exactly 0036's shape
        assert plans() == {"starter": ("Starter", 49900), "growth": ("Growth", 79900), "pro": ("Pro", 149900)}
        assert owner_query("SELECT count(*) FROM subscriptions")[0][0] == before_rows and owner_query("SELECT count(*) FROM payments")[0][0] == before_pay
        assert owner_query("SELECT plan, status FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0] == before_plan
        for t in ("razorpay_subscription_id", "razorpay_plan_id"):  # historical Razorpay columns untouched
            assert any(t in cols(tbl) for tbl in ("subscriptions", "billing_plans"))
        assert owner_query("SELECT version_num FROM alembic_version")[0][0] == "0036"
    finally:
        alembic("upgrade", "head")
    assert present() and plans() == {"starter": ("Launch", 49900), "growth": ("Growth", 79900), "pro": ("Scale", 149900)}
    assert owner_query("SELECT plan, status FROM subscriptions WHERE tenant_id = :t", t=biz.tenant_id)[0] == before_plan
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] == "0053"  # the head now


def test_a_name_an_administrator_changed_is_never_overwritten_by_the_rename():
    alembic("downgrade", "0036")
    try:
        owner_exec("UPDATE billing_plans SET name = 'Custom Scale' WHERE code = 'pro'")
    finally:
        alembic("upgrade", "head")
    try:
        assert plans()["pro"] == ("Custom Scale", 149900) and plans()["starter"][0] == "Launch"
    finally:
        owner_exec("UPDATE billing_plans SET name = 'Scale' WHERE code = 'pro'")
    assert plans()["pro"][0] == "Scale"


def test_production_shape_0036_upgrades_without_touching_card_status_or_any_row():
    alembic("downgrade", "0036")
    try:
        assert owner_query("SELECT count(*) FROM subscriptions WHERE card_status IS NOT NULL")[0][0] == 0
        rows = owner_query("SELECT count(*) FROM subscriptions")[0][0]
    finally:
        alembic("upgrade", "head")
    assert "card_status" in cols("subscriptions") and present() and owner_query("SELECT count(*) FROM subscriptions")[0][0] == rows


def test_physical_qr_card_functionality_is_untouched():
    for t in ("qr_cards", "card_batches", "card_assignments", "scan_events", "card_orders"):
        assert cols(t), t
    assert owner_query("SELECT 1 FROM pg_type WHERE typname = 'card_status'")  # the QR card lifecycle enum is a different thing from the withdrawn subscriptions.card_status column
    assert "status" in cols("qr_cards")


def test_the_unique_constraints_refuse_a_second_row_with_the_same_provider_id():
    from sqlalchemy.exc import IntegrityError
    biz = make_business()
    owner_exec("UPDATE subscriptions SET cashfree_subscription_id = 'fqs_uniq_test' WHERE tenant_id = :t", t=biz.tenant_id)
    other = make_business()
    with pytest.raises(IntegrityError):
        owner_exec("UPDATE subscriptions SET cashfree_subscription_id = 'fqs_uniq_test' WHERE tenant_id = :t", t=other.tenant_id)
    owner_exec("UPDATE subscriptions SET cashfree_subscription_id = NULL WHERE cashfree_subscription_id = 'fqs_uniq_test'")
