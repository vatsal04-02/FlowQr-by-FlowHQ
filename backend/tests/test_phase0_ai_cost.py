"""Phase 0: AI cost accounting and budget enforcement.

MOCKED: the model is a TEST DOUBLE (UsageStub) that reports token usage the way GeminiProvider does ({"prompt_tokens", "completion_tokens", "calls", "model"}).
The ledger, the budgets and the database are real. Nothing here calls Gemini; what these tests prove is FlowQR's own accounting and enforcement, not a
provider's real prices (those are configured with AI_PRICE_IN_PER_MTOK / AI_PRICE_OUT_PER_MTOK)."""
import pathlib
import re
import uuid
from decimal import Decimal

import pytest

import app
from app.core.config import settings
from app.core.db import SessionLocal, set_rls_context
from app.services import ai_usage
from app.services.ai import health
from app.services.ai.base import AIUnavailable
from app.services.ai_usage import BudgetExceeded, MeteredProvider, check_budget, estimate_cost, log_generation, metered, record_call, spend_this_month
from tests.conftest import make_business, owner_exec, owner_query
from tests.test_google_and_reviews import connected, fake, greview, sync_select  # noqa: F401


class UsageStub:
    """TEST DOUBLE LLM that keeps a running usage total like GeminiProvider and can fail."""

    name, model = "gemini", "gemini-test"

    def __init__(self, tokens=(100, 20), text="Thank you for the kind words. We look forward to seeing you again."):
        self.tokens, self.text, self.calls, self.fail = tokens, text, 0, None
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "model": self.model}

    def generate(self, system, user, *, max_tokens=600, temperature=0.4, json_mode=False):
        self.calls += 1
        if self.fail:
            raise self.fail
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += self.tokens[0]
        self.usage["completion_tokens"] += self.tokens[1]
        return self.text


@pytest.fixture(autouse=True)
def clean_ledger(monkeypatch):
    owner_exec("DELETE FROM ai_call_ledger")
    for k, v in (("ai_price_in_per_mtok", 0.0), ("ai_price_out_per_mtok", 0.0), ("ai_tenant_monthly_budget_usd", 0.0), ("ai_tenant_monthly_token_budget", 0),
                 ("ai_platform_hard_limit_usd", 0.0), ("ai_platform_monthly_token_limit", 0), ("ai_platform_soft_pct", 90)):
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(settings, "gemini_data_terms_verified", True)  # these tests exercise budgets and the ledger, not the data-terms gate (that gate is tested in tests/test_privacy_lifecycle.py)
    health.reset()
    yield


def priced(monkeypatch, inp=1.0, out=4.0):
    monkeypatch.setattr(settings, "ai_price_in_per_mtok", inp)
    monkeypatch.setattr(settings, "ai_price_out_per_mtok", out)


def tenant():
    t = uuid.UUID(make_business(f"Cost Biz {uuid.uuid4().hex[:6]}").tenant_id)
    owner_exec("UPDATE subscriptions SET status = 'active', plan = 'growth', review_generations = 300, review_replies = 300 WHERE tenant_id = :t", t=t)  # these tests are about budgets, not the free-trial rules (tests/test_trial_caps.py)
    return t


def rows(tid=None, status=None):
    sql = "SELECT kind, provider, model, input_tokens, output_tokens, cost_usd, status, error_code, tenant_id FROM ai_call_ledger WHERE true"
    params = {}
    if tid:
        sql, params["t"] = sql + " AND tenant_id = :t", tid
    if status:
        sql, params["s"] = sql + " AND status = :s", status
    return owner_query(sql + " ORDER BY created_at", **params)


def seed(tid, usd=0.0, tokens=0, status="ok", kind="reply_draft"):
    owner_exec("INSERT INTO ai_call_ledger (id, tenant_id, kind, provider, model, input_tokens, output_tokens, cost_usd, status, created_at) "
               "VALUES (gen_random_uuid(), :t, :k, 'gemini', 'gemini-test', :i, 0, :c, :s, now())", t=tid, k=kind, i=tokens, c=usd, s=status)


# ============================================================================ 1. every call is recorded

def test_every_call_writes_a_ledger_row_with_tokens_model_task_tenant_cost_and_status(monkeypatch):
    priced(monkeypatch)
    tid, stub = tenant(), UsageStub(tokens=(1000, 200))
    p = metered(stub, None, tid, "reply_draft")
    p.generate("s", "u", max_tokens=300)
    p.generate("s", "u", max_tokens=300)
    r = rows(tid)
    assert len(r) == 2
    kind, provider, model, tin, tout, cost, status, code, who = r[0]
    assert (kind, provider, model, tin, tout, status, code, who) == ("reply_draft", "gemini", "gemini-test", 1000, 200, "ok", None, tid)
    assert cost == Decimal("0.001800")  # 1000 x $1/M + 200 x $4/M
    assert spend_this_month(tid)["usd"] == Decimal("0.003600") and spend_this_month(tid)["tokens"] == 2400


def test_a_failed_call_is_recorded_with_its_error_code_and_still_raises(monkeypatch):
    tid, stub = tenant(), UsageStub()
    stub.fail = AIUnavailable("rate limited", code="rate_limited")
    with pytest.raises(AIUnavailable):
        metered(stub, None, tid, "post_draft").generate("s", "u")
    (r,) = rows(tid)
    assert r[0] == "post_draft" and r[6] == "error" and r[7] == "rate_limited" and (r[3], r[4]) == (0, 0)


def test_the_ledger_row_survives_a_rolled_back_request(monkeypatch):
    priced(monkeypatch)
    tid = tenant()
    db = SessionLocal(); set_rls_context(db, bypass=True)
    prov = metered(UsageStub(), db, tid, "reply_draft")
    prov.generate("s", "u")
    db.rollback(); db.close()  # the request that made the call fails and is rolled back
    assert len(rows(tid)) == 1  # the spend was still recorded


def test_cost_is_an_estimate_from_configured_prices_and_unknown_when_no_price_is_set(monkeypatch):
    assert estimate_cost(1000, 1000) is None  # no price configured: never a guess
    priced(monkeypatch, 0.5, 2.0)
    assert estimate_cost(2_000_000, 500_000) == Decimal("2.000000")
    assert estimate_cost(10, 10, reported=0.25) == Decimal("0.250000")  # a provider's own figure wins
    tid = tenant()
    monkeypatch.setattr(settings, "ai_price_in_per_mtok", 0.0); monkeypatch.setattr(settings, "ai_price_out_per_mtok", 0.0)
    metered(UsageStub(), None, tid, "reply_draft").generate("s", "u")
    assert rows(tid)[0][5] is None and spend_this_month(tid)["unpriced_calls"] == 1


def test_a_provider_that_reports_no_usage_is_recorded_with_unknown_tokens_not_zero():
    class Bare:
        name, model = "test-stub", "stub-1"
        def generate(self, system, user, *, max_tokens=600, temperature=0.4):
            return "ok"
    tid = tenant()
    metered(Bare(), None, tid, "reply_draft").generate("s", "u")
    r = rows(tid)[0]
    assert (r[3], r[4], r[6]) == (None, None, "ok")


def test_generation_log_rows_now_carry_tokens_and_an_estimated_cost(monkeypatch):
    priced(monkeypatch)
    tid, stub = tenant(), UsageStub(tokens=(1000, 200))
    db = SessionLocal(); set_rls_context(db, bypass=True)
    p = metered(stub, db, tid, "reply_draft")
    p.generate("s", "u")
    import time
    log_generation(db, tenant_id=tid, kind="reply_draft", provider=p.name, model=p.model, language="en", input_chars=10, output_chars=10, status="ok",
                   started=time.monotonic(), usage=getattr(p, "usage", None))
    db.commit(); db.close()
    t_in, t_out, cost = owner_query("SELECT prompt_tokens, completion_tokens, cost_usd FROM ai_generation_logs WHERE tenant_id = :t", t=tid)[0]
    assert (t_in, t_out, cost) == (1000, 200, Decimal("0.001800"))


def test_the_ledger_is_tenant_isolated():
    a, b = tenant(), tenant()
    seed(a, 1.0); seed(a, 1.0); seed(b, 5.0)
    db = SessionLocal(); set_rls_context(db, tenant_id=a)
    from sqlalchemy import func, select
    from app.models import AICallLedger
    assert db.scalar(select(func.count()).select_from(AICallLedger)) == 2  # a sees only its own rows
    db.close()


# ============================================================================ 2. per-business budgets

def test_a_business_over_its_monthly_budget_stops_nonessential_generation_before_the_model_is_called(monkeypatch):
    priced(monkeypatch)
    tid, stub = tenant(), UsageStub()
    owner_exec("UPDATE tenants SET ai_monthly_budget_usd = 0.01 WHERE id = :t", t=tid)
    seed(tid, usd=0.0095)  # already spent: only $0.0005 left, less than this call's worst case
    db = SessionLocal(); set_rls_context(db, bypass=True)
    p = metered(stub, db, tid, "post_draft")
    with pytest.raises(BudgetExceeded) as exc:
        p.generate("s", "u", max_tokens=600)
    db.close()
    assert exc.value.code == "budget_tenant" and "monthly AI budget" in str(exc.value) and isinstance(exc.value, AIUnavailable)
    assert stub.calls == 0  # the model was never called
    blocked = rows(tid, "blocked")
    assert len(blocked) == 1 and blocked[0][7] == "budget_tenant" and (blocked[0][3], blocked[0][4]) == (0, 0)


def test_the_default_business_budget_applies_when_the_business_has_none(monkeypatch):
    priced(monkeypatch)
    monkeypatch.setattr(settings, "ai_tenant_monthly_budget_usd", 0.01)
    tid, stub = tenant(), UsageStub()
    seed(tid, usd=0.0099)
    with pytest.raises(BudgetExceeded):
        metered(stub, None, tid, "agent_draft").generate("s", "u", max_tokens=600)
    assert stub.calls == 0
    other = tenant()  # an untouched business is fine
    metered(UsageStub(), None, other, "agent_draft").generate("s", "u", max_tokens=600)


def test_customer_facing_review_writing_continues_when_the_business_budget_is_used(monkeypatch):
    priced(monkeypatch)
    tid = tenant()
    owner_exec("UPDATE tenants SET ai_monthly_budget_usd = 0.01 WHERE id = :t", t=tid)
    seed(tid, usd=0.02)  # well over the business's budget
    db = SessionLocal(); set_rls_context(db, bypass=True)
    for kind in ("review_generate", "review_assist", "review_risk"):
        assert metered(UsageStub(), db, tid, kind).generate("s", "u") == UsageStub().text  # essential: only the platform hard limit stops these
    with pytest.raises(BudgetExceeded):
        metered(UsageStub(), db, tid, "reply_draft").generate("s", "u")
    db.close()


def test_token_budgets_need_no_price(monkeypatch):
    monkeypatch.setattr(settings, "ai_tenant_monthly_token_budget", 1000)
    tid, stub = tenant(), UsageStub()
    seed(tid, tokens=900)
    with pytest.raises(BudgetExceeded) as exc:
        metered(stub, None, tid, "post_draft").generate("s", "u", max_tokens=600)
    assert "tokens" in str(exc.value) and stub.calls == 0


# ============================================================================ 3. no silent bypass, including retries

def test_a_retry_loop_is_checked_on_every_call_so_it_cannot_run_past_the_budget(monkeypatch):
    priced(monkeypatch)
    monkeypatch.setattr(settings, "ai_tenant_monthly_budget_usd", 0.009)
    tid, stub = tenant(), UsageStub(tokens=(1000, 1000))  # each call really costs $0.005
    p = metered(stub, None, tid, "reply_draft")
    made = 0
    with pytest.raises(BudgetExceeded):
        for _ in range(10):  # e.g. write -> rewrite -> rewrite: every attempt is a separate model call
            p.generate("s", "u", max_tokens=600)
            made += 1
    assert made == 2 and stub.calls == 2  # the third attempt was refused before the model was called
    assert spend_this_month(tid)["usd"] == Decimal("0.010000")


def test_the_reply_drafting_retry_inside_one_request_is_budget_checked_again(monkeypatch):
    """draft_reply_scored makes a second model call when the first draft breaks a rule. That second call goes through the same wrapper."""
    from types import SimpleNamespace
    from app.services.ai.replies import draft_reply_scored
    priced(monkeypatch)
    monkeypatch.setattr(settings, "ai_tenant_monthly_budget_usd", 0.005)  # room for the first call's worst case, not for a second after it really spent $0.0036
    tid = tenant()
    bad = "We cured your condition, guaranteed 100% recovery!"  # breaks the reply safety rules -> triggers a rewrite
    stub = UsageStub(tokens=(2000, 400), text=bad)
    review = SimpleNamespace(text="The staff were kind and the clinic was clean.", rating=5, reviewer_name="Asha")
    t = SimpleNamespace(name="Alpha Physio", category="Physiotherapy clinic", language="en", brand_tone=None, ai_instructions=None)
    kb = {"business": "Alpha Physio", "category": "Physiotherapy clinic", "language": "en", "description": "", "services": [], "offers": [], "hours": "", "faqs": [],
          "brand_voice": "", "approved_claims": [], "prohibited_claims": [], "safety_profile": "health", "instructions": "", "audience": ""}
    with pytest.raises(BudgetExceeded):
        draft_reply_scored(metered(stub, None, tid, "reply_draft"), review, t, None, kb=kb)
    assert stub.calls == 1  # the rewrite was refused before the model was called
    assert len(rows(tid, "ok")) == 1 and len(rows(tid, "blocked")) == 1  # one real call recorded, one refused call recorded


def test_budget_blocks_never_pause_ai_for_everyone(monkeypatch):
    priced(monkeypatch)
    monkeypatch.setattr(settings, "ai_tenant_monthly_budget_usd", 0.0001)
    tid = tenant()
    with pytest.raises(BudgetExceeded) as exc:
        metered(UsageStub(), None, tid, "reply_draft").generate("s", "u", max_tokens=600)
    health.mark_down(exc.value.code, exc.value.retry_after)  # what the public flows do with an AIUnavailable
    assert health.current() is None


def test_a_usd_limit_with_no_price_configured_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "ai_tenant_monthly_budget_usd", 5.0)  # a limit, but no AI_PRICE_*: spending cannot be measured
    stub = UsageStub()
    with pytest.raises(BudgetExceeded) as exc:
        metered(stub, None, tenant(), "reply_draft").generate("s", "u")
    assert exc.value.code == "budget_unpriced" and "no AI price" in str(exc.value) and stub.calls == 0
    metered(UsageStub(), None, tenant(), "review_generate").generate("s", "u")  # essential work is not held hostage by a limit that does not apply to it


# ============================================================================ 4. the platform hard limit

def test_platform_soft_then_hard_limit(monkeypatch):
    priced(monkeypatch)
    monkeypatch.setattr(settings, "ai_platform_hard_limit_usd", 1.0)
    a, b = tenant(), tenant()
    seed(a, usd=0.5)
    seed(b, usd=0.5)  # 100% of the limit is spent across two businesses (platform-wide, not per business)
    for kind in ("reply_draft", "review_generate"):
        with pytest.raises(BudgetExceeded) as exc:
            metered(UsageStub(), None, a, kind).generate("s", "u", max_tokens=50)
        assert exc.value.code == "budget_platform" and "spending limit" in str(exc.value)  # hard stop for ALL generation, essential included
    owner_exec("DELETE FROM ai_call_ledger")
    seed(a, usd=0.95)  # 95%: past the 90% soft line, short of the hard limit
    with pytest.raises(BudgetExceeded) as exc:
        metered(UsageStub(), None, b, "post_draft").generate("s", "u", max_tokens=50)
    assert "only customer review writing is running" in str(exc.value)
    assert metered(UsageStub(), None, b, "review_generate").generate("s", "u", max_tokens=50)  # essential still runs below 100%


def test_platform_token_limit(monkeypatch):
    monkeypatch.setattr(settings, "ai_platform_monthly_token_limit", 10_000)
    tid = tenant()
    seed(tid, tokens=9_900)
    stub = UsageStub()
    with pytest.raises(BudgetExceeded):
        metered(stub, None, tid, "review_generate").generate("s", "u", max_tokens=300)
    assert stub.calls == 0


def test_blocked_attempts_cost_nothing_and_do_not_count_as_spend(monkeypatch):
    priced(monkeypatch)
    monkeypatch.setattr(settings, "ai_platform_hard_limit_usd", 0.001)
    tid = tenant()
    for _ in range(3):
        with pytest.raises(BudgetExceeded):
            metered(UsageStub(), None, tid, "reply_draft").generate("s", "u", max_tokens=600)
    assert spend_this_month()["usd"] == 0 and len(rows(tid, "blocked")) == 3


def test_no_limits_configured_means_calls_are_only_recorded(monkeypatch):
    tid = tenant()
    check_budget(tenant_id=tid, kind="reply_draft", est_input_tokens=10**9, max_output_tokens=10**9)  # nothing configured: never raises
    metered(UsageStub(), None, tid, "reply_draft").generate("s", "u")
    assert len(rows(tid)) == 1


# ============================================================================ 5. real endpoints

def test_the_reply_draft_endpoint_records_tokens_and_says_so_when_the_budget_stops_it(connected, fake, monkeypatch):  # noqa: F811
    priced(monkeypatch)
    owner_exec("UPDATE subscriptions SET status = 'active', plan = 'growth', review_generations = 300, review_replies = 300 WHERE tenant_id = :t", t=connected.tenant_id)  # a paid business (a free trial has no AI replies)
    stub = UsageStub(tokens=(1000, 200))
    monkeypatch.setattr("app.api.v1.reviews.get_provider", lambda: stub)
    fake.reviews = [greview(1, 5, "The staff were kind and the clinic was clean.")]
    sync_select(connected, fake)
    rid = connected.get("/reviews").json()["items"][0]["id"]
    ok = connected.post(f"/reviews/{rid}/drafts/generate")
    assert ok.status_code == 201, ok.text
    mine = rows(uuid.UUID(connected.tenant_id))
    assert [(m[0], m[3], m[4], m[6]) for m in mine] == [("reply_draft", 1000, 200, "ok")]
    log = owner_query("SELECT prompt_tokens, completion_tokens, cost_usd FROM ai_generation_logs WHERE tenant_id = :t AND kind = 'reply_draft'", t=connected.tenant_id)[0]
    assert log[0] == 1000 and log[1] == 200 and log[2] == Decimal("0.001800")  # the dashboard log now has what used to be NULL

    owner_exec("UPDATE tenants SET ai_monthly_budget_usd = 0.0001 WHERE id = :t", t=connected.tenant_id)
    before = stub.calls
    blocked = connected.post(f"/reviews/{rid}/drafts/generate")
    assert blocked.status_code == 402 and "monthly AI budget" in blocked.json()["detail"]
    assert stub.calls == before  # not even tried


# ============================================================================ 6. coverage: no model call can skip the meter

def test_every_model_call_site_goes_through_the_meter():
    root = pathlib.Path(app.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        if path.name in ("base.py", "ai_usage.py") and path.parent.name in ("ai", "services"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bget_provider\(\)", line) and "def get_provider" not in line and "metered(" not in line:
                offenders.append(f"{path.relative_to(root)}:{n}: {line.strip()}")
    assert offenders == [], "model providers must be wrapped with services.ai_usage.metered():\n" + "\n".join(offenders)
