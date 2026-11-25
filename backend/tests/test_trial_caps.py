"""The free trial (owner decision 2026-11-25): review writing (15 a month), a few SEO tips (5), website building free, nothing else. Real database, real subscription rows."""
import uuid
from decimal import Decimal

import pytest

from app.core.config import settings
from app.services import ai_usage as au
from tests.conftest import make_business, owner_exec


def call(tenant_id, kind):
    au.check_budget(tenant_id=uuid.UUID(str(tenant_id)), kind=kind, est_input_tokens=100, max_output_tokens=100)


def used(tenant_id, kind, n=1):
    for _ in range(n):
        au.record_call(tenant_id=uuid.UUID(str(tenant_id)), kind=kind, provider="test", model="m", input_tokens=10, output_tokens=10, cost_usd=Decimal("0.0001"), status="ok")


def test_a_trial_may_write_reviews_and_build_a_website_but_not_reply_post_or_run_campaigns():
    biz = make_business("Trial Scope Cafe")
    for kind in ("review_generate", "review_assist", "review_risk", "site_draft", "agent_draft"):
        call(biz.tenant_id, kind)
    for kind in ("reply_draft", "post_draft", "post_ideas", "campaign", "whatsapp_assistant"):
        with pytest.raises(au.BudgetExceeded) as e:
            call(biz.tenant_id, kind)
        assert e.value.scope == "trial", kind


def test_a_trial_gets_a_few_seo_tips_and_then_is_asked_to_choose_a_plan(monkeypatch):
    monkeypatch.setattr(settings, "trial_seo_tips", 3)
    biz = make_business("Trial Tips Cafe")
    used(biz.tenant_id, "agent_draft", 3)
    with pytest.raises(au.BudgetExceeded) as e:
        call(biz.tenant_id, "agent_draft")
    assert e.value.scope == "trial" and "3 SEO tips" in str(e.value)
    call(biz.tenant_id, "site_draft")  # website building is never counted
    used(biz.tenant_id, "site_draft", 6)
    call(biz.tenant_id, "site_draft")
    call(biz.tenant_id, "review_generate")


def test_the_website_builder_is_free_even_when_the_business_dollar_budget_is_used(monkeypatch):
    monkeypatch.setattr(settings, "ai_tenant_monthly_budget_usd", 0.0001)
    biz = make_business("Trial Free Site Cafe")
    used(biz.tenant_id, "agent_draft", 5)
    call(biz.tenant_id, "site_draft")  # essential: not held by the per-business budget
    with pytest.raises(au.BudgetExceeded):
        call(biz.tenant_id, "agent_draft")


def test_a_paid_business_is_not_held_to_the_trial_rules():
    biz = make_business("Paid Scope Cafe")
    owner_exec("UPDATE subscriptions SET status = 'active', plan = 'growth' WHERE tenant_id = :t", t=uuid.UUID(biz.tenant_id))
    used(biz.tenant_id, "agent_draft", 9)
    for kind in ("reply_draft", "post_draft", "agent_draft", "campaign"):
        call(biz.tenant_id, kind)


def test_the_trial_allowance_on_the_subscription_row_follows_the_settings():
    biz = make_business("Trial Row Cafe")
    lim = biz.get("/billing/subscription").json()["limits"]
    assert (lim["review_generations"], lim["review_replies"]) == (15, 0)
