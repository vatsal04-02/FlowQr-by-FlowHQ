import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AICallLedger, AIGenerationLog, Subscription, Tenant
from app.models.base import utcnow
from app.services.ai.base import AIUnavailable

log = logging.getLogger("flowqr.ai_usage")


def month_start() -> datetime:
    n = utcnow()
    return datetime(n.year, n.month, 1, tzinfo=timezone.utc)


def usage_this_month(db: Session, tenant_id: uuid.UUID, field: str | None = None) -> int:
    """Generations that count against a plan allowance this calendar month. `field` = "review_generations" or "review_replies" for ONE allowance; None = both added
    together (the display total). Only SUCCESSFUL generations count: a call that failed gave the customer nothing and does not use their allowance (its cost is still
    in the ledger and bounded by the USD budgets)."""
    from app.services import plans

    kinds = plans.kinds_for(field) if field else plans.REVIEW_GENERATION_KINDS | plans.REPLY_KINDS
    return db.scalar(
        select(func.count()).select_from(AIGenerationLog).where(
            AIGenerationLog.tenant_id == tenant_id, AIGenerationLog.created_at >= month_start(), AIGenerationLog.kind.in_(kinds), AIGenerationLog.status == "ok")
    ) or 0


def quota_exceeded(db: Session, tenant_id: uuid.UUID, kind: str | None = None) -> bool:
    """True when this AI task must not run: the subscription is not active, or the allowance THIS TASK DRAWS ON is used up.
    Review generation and replies are separate allowances (a plan with 400 and 400 has 800 operations, not 400 shared). A task with no per-plan count in the commercial
    terms (posts, descriptions, the growth agent) is only held back by an inactive subscription, its plan feature and the USD budgets."""
    from app.services import entitlements as ent
    from app.services import plans

    e = ent.for_tenant(db, tenant_id)
    if not e.active:
        return True
    field = plans.quota_field_for(kind)
    return field is not None and usage_this_month(db, tenant_id, field) >= getattr(e, field)


def log_generation(db: Session, *, tenant_id, kind, provider, model, language, input_chars, output_chars, status,
                   started: float, location_id=None, card_id=None, error: str | None = None, usage: dict | None = None,
                   stats: dict | None = None) -> None:
    """`usage` is the provider's running total ({"prompt_tokens", "completion_tokens", "calls", "cost", "model"}), if it reports one.
    `stats` is generate_review's {"attempts", "rejects_rules", "rejects_factcheck"}. Failed and rejected attempts that still consumed
    tokens are logged with them. Never pass customer text here."""
    used = usage if usage and usage.get("calls") else None
    stats = stats or {}
    cost = (used or {}).get("cost")
    if not cost and used:  # the provider reports no price (Gemini): estimate from the configured per-token prices, NULL when none is configured
        cost = estimate_cost(used["prompt_tokens"], used["completion_tokens"])
    db.add(AIGenerationLog(
        tenant_id=tenant_id, location_id=location_id, card_id=card_id, kind=kind, provider=provider, model=(used or {}).get("model") or model,
        language=language, input_chars=input_chars, output_chars=output_chars, status=status,
        prompt_tokens=used["prompt_tokens"] if used else None, completion_tokens=used["completion_tokens"] if used else None,
        model_calls=used["calls"] if used else None, attempts=stats.get("attempts"), rejects_rules=stats.get("rejects_rules"),
        rejects_factcheck=stats.get("rejects_factcheck"), cost_usd=round(cost, 6) if cost else None,
        error=(error or None) and error[:500], latency_ms=int((time.monotonic() - started) * 1000), created_at=utcnow(),
    ))


# =============================================================================================================================================
# Per-call metering and budgets
#
# `metered(provider, db, tenant_id, kind)` wraps any LLMProvider. Every generate() call:
#   1. is checked against the business's and the platform's monthly budgets BEFORE the model is called. The wrapper sits at the provider, so a
#      rewrite, a second attempt or a fact-check pass is checked again; nothing a caller does can reuse an earlier approval ("no silent bypass");
#   2. is written to ai_call_ledger afterwards (task, tenant, model, input/output tokens, estimated USD, ok/error), in its OWN transaction so the
#      cost is kept even if the request later rolls back.
# Spend is read from the ledger as committed. Concurrent in-flight calls can overshoot a limit by at most their own worst case (the pre-check
# already adds the call's own worst case: estimated input + max_tokens), so a single call never crosses a limit by itself.
# =============================================================================================================================================

# Customer-facing review writing and the review-risk safety check keep working until the platform HARD limit; everything else is nonessential.
ESSENTIAL_KINDS = frozenset({"review_generate", "review_assist", "review_risk", "site_draft"})  # site_draft: building a website is free and is not held by the per-business dollar budget

# A FREE TRIAL (owner decision 2026-11-25) may write reviews, get a few SEO tips and build a website, nothing else. Everything below is enforced here, in the one place every model call passes.
TRIAL_KINDS = frozenset({"review_generate", "review_assist", "review_risk", "review_test", "agent_draft", "site_draft"})
TRIAL_SEO_KINDS = frozenset({"agent_draft"})  # SEO and growth tips: the profile and SEO engines, the growth agent, the operator's prepared changes


def trial_gate(tenant_id: uuid.UUID | None, kind: str) -> None:
    """Raise BudgetExceeded('trial') when a business that is on its FREE TRIAL asks for something the trial does not include or has used its few SEO tips.
    Paid, prepaid, managed and expired businesses are not affected here (their own allowances and the active check apply)."""
    if tenant_id is None:
        return
    db = _own_session()
    try:
        sub = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
        if sub is None or sub.status != "trialing" or sub.plan != "trial":
            return
        if kind.startswith("whatsapp"):
            return  # the WhatsApp add-on has its own entitlement and quotas (services/whatsapp); the trial rules here are about the plan's AI
        if kind == "reply_draft" and settings.trial_review_replies > 0:
            return  # counted against the trial's reply allowance by the plan quota
        if kind not in TRIAL_KINDS:
            raise BudgetExceeded("trial", "This is part of the paid plans. Your free trial includes review writing, a few SEO tips and your website. Choose a plan to use everything.")
        if kind in TRIAL_SEO_KINDS:
            used = db.scalar(select(func.count()).select_from(AICallLedger).where(
                AICallLedger.tenant_id == tenant_id, AICallLedger.created_at >= month_start(), AICallLedger.status == "ok", AICallLedger.kind.in_(TRIAL_SEO_KINDS))) or 0
            if used >= settings.trial_seo_tips:
                raise BudgetExceeded("trial", f"Your free trial includes {settings.trial_seo_tips} SEO tips and they are used. Choose a plan to get more.")
    finally:
        db.close()


class BudgetExceeded(AIUnavailable):
    """A budget stopped this call. It IS an AIUnavailable (callers already degrade gracefully on that), with a distinct code:
    budget_tenant | budget_platform | budget_unpriced. It never pauses AI for everyone (ai/health only pauses on provider codes)."""

    def __init__(self, scope: str, message: str):
        super().__init__(message, code=f"budget_{scope}")
        self.scope = scope


def price_known() -> bool:
    return bool(settings.ai_price_in_per_mtok or settings.ai_price_out_per_mtok)


def estimate_cost(input_tokens: int | None, output_tokens: int | None, reported: float | None = None) -> Decimal | None:
    """USD for one call: the provider's own figure when it gives one, else tokens x the configured prices. None when neither exists (never a guess)."""
    if reported:
        return Decimal(str(round(float(reported), 6)))
    if not price_known() or input_tokens is None or output_tokens is None:
        return None
    usd = (input_tokens * settings.ai_price_in_per_mtok + output_tokens * settings.ai_price_out_per_mtok) / 1_000_000
    return Decimal(str(round(usd, 6)))


def _own_session():
    from app.core.db import SessionLocal, set_rls_context

    db = SessionLocal()
    set_rls_context(db, bypass=True)
    return db


def spend_this_month(tenant_id: uuid.UUID | None = None) -> dict:
    """{usd, tokens, unpriced_calls, calls} from the ledger (committed rows only; blocked attempts cost nothing). tenant_id=None = the whole platform."""
    db = _own_session()
    try:
        q = select(func.coalesce(func.sum(AICallLedger.cost_usd), 0), func.coalesce(func.sum(AICallLedger.input_tokens + AICallLedger.output_tokens), 0),
                   func.count().filter(AICallLedger.cost_usd.is_(None)), func.count()).where(AICallLedger.created_at >= month_start(), AICallLedger.status == "ok")
        if tenant_id is not None:
            q = q.where(AICallLedger.tenant_id == tenant_id)
        usd, tokens, unpriced, calls = db.execute(q).one()
        return {"usd": Decimal(usd), "tokens": int(tokens or 0), "unpriced_calls": int(unpriced), "calls": int(calls)}
    finally:
        db.close()


def record_call(*, tenant_id, kind: str, provider: str, model: str | None, input_tokens: int | None, output_tokens: int | None,
                cost_usd: Decimal | None, status: str, error_code: str | None = None, latency_ms: int | None = None, location_id=None, actor_user_id=None,
                request_id: str | None = None, retry_count: int | None = None, cached_tokens: int | None = None) -> None:
    """Append one ledger row in its own transaction. Never raises: a failed write is logged loudly, it must not turn a successful model call into an error."""
    db = _own_session()
    try:
        db.add(AICallLedger(tenant_id=tenant_id, kind=kind[:32], provider=provider[:32], model=(model[:80] if model else None), input_tokens=input_tokens,
                            output_tokens=output_tokens, cost_usd=cost_usd, status=status, error_code=(error_code[:32] if error_code else None),
                            latency_ms=latency_ms, created_at=utcnow(), google_location_id=location_id, actor_user_id=actor_user_id, request_id=request_id, retry_count=retry_count,
                            cached_tokens=cached_tokens, feature=kind[:32]))
        db.commit()
    except Exception:  # noqa: BLE001
        log.exception("could not write the AI cost ledger row (kind=%s tenant=%s): this call's cost is NOT recorded", kind, tenant_id)
        db.rollback()
    finally:
        db.close()


def _usd(n) -> str:
    return f"${float(n):.2f}"


def check_budget(*, tenant_id: uuid.UUID | None, kind: str, est_input_tokens: int, max_output_tokens: int, tenant_budget_usd: Decimal | float | None = None) -> None:
    """Raise BudgetExceeded when this call may not be made. See the module comment for the rules. Called before every model call."""
    trial_gate(tenant_id, kind)
    hard_usd, hard_tok = settings.ai_platform_hard_limit_usd, settings.ai_platform_monthly_token_limit
    t_usd = float(tenant_budget_usd) if tenant_budget_usd is not None else settings.ai_tenant_monthly_budget_usd
    t_tok = settings.ai_tenant_monthly_token_budget
    if not (hard_usd > 0 or hard_tok > 0 or t_usd > 0 or t_tok > 0):
        return  # nothing configured: the call is still recorded afterwards
    essential = kind in ESSENTIAL_KINDS
    worst_tok = est_input_tokens + max_output_tokens
    worst_usd = estimate_cost(est_input_tokens, max_output_tokens)
    if (hard_usd > 0 or (t_usd > 0 and not essential)) and worst_usd is None:  # a USD limit that applies to THIS call needs a price to be checkable
        raise BudgetExceeded("unpriced", "A spending limit is set but no AI price is configured (AI_PRICE_IN_PER_MTOK / AI_PRICE_OUT_PER_MTOK), so spending cannot be "
                                          "checked. Generation is stopped until a price is set.")
    pct = max(1, min(100, settings.ai_platform_soft_pct)) / 100
    if hard_usd > 0 or hard_tok > 0:
        platform = spend_this_month()
        for limit, used, add, fmt in ((hard_usd, float(platform["usd"]), float(worst_usd or 0), _usd), (hard_tok, platform["tokens"], worst_tok, str)):
            if limit <= 0:
                continue
            if used + add > limit:
                raise BudgetExceeded("platform", f"FlowQR's AI spending limit for this month has been reached ({fmt(used)} of {fmt(limit)}). AI resumes next month or when the limit is raised.")
            if not essential and used + add > limit * pct:
                raise BudgetExceeded("platform", f"FlowQR's AI usage is at {int(pct * 100)}% of the monthly limit, so only customer review writing is running. Drafts resume next month or when the limit is raised.")
    if tenant_id is not None and not essential and (t_usd > 0 or t_tok > 0):
        mine = spend_this_month(tenant_id)
        if t_usd > 0 and float(mine["usd"]) + float(worst_usd or 0) > t_usd:
            raise BudgetExceeded("tenant", f"This business's monthly AI budget is used ({_usd(mine['usd'])} of {_usd(t_usd)}). Drafting resumes next month or when the budget is raised.")
        if t_tok > 0 and mine["tokens"] + worst_tok > t_tok:
            raise BudgetExceeded("tenant", f"This business's monthly AI usage limit is reached ({mine['tokens']:,} of {t_tok:,} tokens). Drafting resumes next month or when the limit is raised.")


class MeteredProvider:
    """An LLMProvider that enforces budgets before, and records the ledger after, every generate() call. Everything else proxies to the wrapped provider."""

    def __init__(self, inner, *, tenant_id: uuid.UUID | None, kind: str, tenant_budget_usd=None, location_id=None, actor_user_id=None):
        import inspect

        self._inner, self._tenant_id, self._kind, self._budget = inner, tenant_id, kind, tenant_budget_usd
        self._location_id, self._actor, self._calls = location_id, actor_user_id, 0
        self.name, self.model = inner.name, inner.model
        try:
            self._inner_json = "json_mode" in inspect.signature(inner.generate).parameters
        except (TypeError, ValueError):
            self._inner_json = False

    def with_kind(self, kind: str) -> "MeteredProvider":
        """The same provider and tenant, accounted (and budget-checked) under another task name."""
        return MeteredProvider(self._inner, tenant_id=self._tenant_id, kind=kind, tenant_budget_usd=self._budget, location_id=self._location_id, actor_user_id=self._actor)

    @property
    def usage(self):
        return getattr(self._inner, "usage", None)

    def __getattr__(self, item):  # anything else (thinking level, timeouts...) comes from the wrapped provider
        return getattr(self._inner, item)

    def _snap(self) -> tuple[int, int, float]:
        u = getattr(self._inner, "usage", None) or {}
        return int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0), float(u.get("cost") or 0)

    def generate(self, system: str, user: str, *, max_tokens: int = 600, temperature: float = 0.4, json_mode: bool = False) -> str:
        est_in = max(1, (len(system) + len(user)) // 3)  # a conservative chars-per-token guess, used only for the pre-call worst case
        try:
            check_budget(tenant_id=self._tenant_id, kind=self._kind, est_input_tokens=est_in, max_output_tokens=max_tokens, tenant_budget_usd=self._budget)
        except BudgetExceeded as exc:
            record_call(tenant_id=self._tenant_id, kind=self._kind, provider=self.name, model=self.model, input_tokens=0, output_tokens=0, cost_usd=None,
                        status="blocked", error_code=exc.code)
            raise
        before, started = self._snap(), time.monotonic()
        request_id, retry = uuid.uuid4().hex, self._calls  # 0 for the first call of this task, 1+ for a rewrite or a second attempt
        self._calls += 1
        kw = {"max_tokens": max_tokens, "temperature": temperature}
        if json_mode and self._inner_json:
            kw["json_mode"] = True
        status, code = "ok", None
        try:
            return self._inner.generate(system, user, **kw)
        except AIUnavailable as exc:
            status, code = "error", exc.code
            raise
        except Exception:
            status, code = "error", "exception"
            raise
        finally:
            after = self._snap()
            reports = getattr(self._inner, "usage", None) is not None
            d_in, d_out, d_cost = after[0] - before[0], after[1] - before[1], after[2] - before[2]
            record_call(tenant_id=self._tenant_id, kind=self._kind, provider=self.name, model=(getattr(self._inner, "usage", None) or {}).get("model") or self.model,
                        input_tokens=d_in if reports else None, output_tokens=d_out if reports else None,
                        cost_usd=estimate_cost(d_in if reports else None, d_out if reports else None, d_cost or None), status=status, error_code=code,
                        latency_ms=int((time.monotonic() - started) * 1000), location_id=self._location_id, actor_user_id=self._actor, request_id=request_id, retry_count=retry,
                        cached_tokens=(getattr(self._inner, "usage", None) or {}).get("cached_tokens"))


def metered(provider, db: Session | None, tenant_id: uuid.UUID | None, kind: str, *, location_id=None, actor_user_id=None):
    """Wrap a provider for budget enforcement and per-call accounting. `db` (the caller's session) is only used to read the business's own budget."""
    if isinstance(provider, MeteredProvider):
        return provider
    budget = db.scalar(select(Tenant.ai_monthly_budget_usd).where(Tenant.id == tenant_id)) if (db is not None and tenant_id is not None) else None
    return MeteredProvider(provider, tenant_id=tenant_id, kind=kind, tenant_budget_usd=budget, location_id=location_id, actor_user_id=actor_user_id)
