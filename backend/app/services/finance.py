"""Revenue, cost and unit economics, computed from what the system actually recorded.

Every figure carries a STATUS so nobody mistakes a guess for a measurement:
  actual     measured from recorded events or payments
  estimated  computed from recorded data plus a stated assumption
  missing    cannot be computed because an input was never provided; the value is None and `needs` says what to provide. A missing cost is NEVER treated as zero.

Definitions (the ones people argue about):
  * MRR counts ONLY subscriptions that are active and paid through the payment provider, at the plan's list price. Trials, the free Growth month that comes with a physical
    card, and comped (manual) subscriptions are not MRR; they are counted separately so nothing is hidden.
  * Physical-card revenue is ONE-TIME revenue. It is reported on its own line and is never part of MRR or ARR.
  * Past-due subscriptions inside the grace period are reported as "at risk", not removed from MRR and not silently kept either.
  * USD costs (AI, Places) and INR revenue are only combined when USD_INR_RATE is configured.
  * A margin is computed only when EVERY variable-cost input exists. Otherwise the margin is None and the missing inputs are listed; a partial sum is shown under its own name.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    AICallLedger, ApiUsage, BillingPlan, CardOrder, Payment, PromotionalGrant, Subscription, SubscriptionEvent, Tenant,
)
from app.models.base import utcnow


def bounds(month: str | None) -> tuple[datetime, datetime, str]:
    """[start, end) of a calendar month; `month` is "YYYY-MM", default the current one."""
    if month:
        y, m = (int(x) for x in month.split("-"))
    else:
        n = utcnow()
        y, m = n.year, n.month
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=timezone.utc)
    return start, end, f"{y:04d}-{m:02d}"


def metric(value, status: str, note: str | None = None, needs: str | None = None) -> dict:
    return {"value": value, "status": status, "note": note, "needs": needs}


def _usd(x) -> float | None:
    return None if x is None else round(float(x), 4)


# ---------------------------------------------------------------------------------------------------------------------------------------------
# costs
# ---------------------------------------------------------------------------------------------------------------------------------------------
def ai_costs(db: Session, start: datetime, end: datetime) -> dict:
    ok = (AICallLedger.created_at >= start, AICallLedger.created_at < end)
    tot = db.execute(select(func.coalesce(func.sum(AICallLedger.cost_usd), 0), func.count(), func.count().filter(AICallLedger.cost_usd.is_(None)),
                            func.coalesce(func.sum(AICallLedger.input_tokens), 0), func.coalesce(func.sum(AICallLedger.output_tokens), 0)).where(*ok, AICallLedger.status == "ok")).one()
    by_status = dict(db.execute(select(AICallLedger.status, func.count()).where(*ok).group_by(AICallLedger.status)).all())
    by_feature = [{"feature": k, "calls": c, "usd": _usd(u), "unpriced_calls": un} for k, c, u, un in db.execute(
        select(AICallLedger.kind, func.count(), func.coalesce(func.sum(AICallLedger.cost_usd), 0), func.count().filter(AICallLedger.cost_usd.is_(None)))
        .where(*ok, AICallLedger.status == "ok").group_by(AICallLedger.kind).order_by(func.coalesce(func.sum(AICallLedger.cost_usd), 0).desc())).all()]
    by_tenant = db.execute(select(AICallLedger.tenant_id, func.count(), func.coalesce(func.sum(AICallLedger.cost_usd), 0), func.count().filter(AICallLedger.cost_usd.is_(None)))
                           .where(*ok, AICallLedger.status == "ok").group_by(AICallLedger.tenant_id)).all()
    return {"usd": _usd(tot[0]), "calls": tot[1], "unpriced_calls": tot[2], "input_tokens": int(tot[3]), "output_tokens": int(tot[4]), "failed_calls": by_status.get("error", 0),
            "refused_calls": by_status.get("blocked", 0), "by_feature": by_feature, "_by_tenant": {t: (c, float(u), un) for t, c, u, un in by_tenant},
            "priced": settings.ai_price_in_per_mtok > 0 or settings.ai_price_out_per_mtok > 0}


def api_costs(db: Session, start: datetime, end: datetime) -> dict:
    ok = (ApiUsage.created_at >= start, ApiUsage.created_at < end)
    rows = db.execute(select(ApiUsage.provider, ApiUsage.operation, ApiUsage.feature, ApiUsage.status, func.coalesce(func.sum(ApiUsage.units), 0), func.coalesce(func.sum(ApiUsage.est_cost_usd), 0),
                             func.coalesce(func.sum(ApiUsage.units).filter(ApiUsage.priced.is_(False)), 0)).where(*ok).group_by(ApiUsage.provider, ApiUsage.operation, ApiUsage.feature, ApiUsage.status)).all()
    by_op, usd, unpriced, units_ok, failed, refused = {}, Decimal(0), 0, 0, 0, 0
    for prov, op, feat, status, units, cost, unp in rows:
        if status == "refused":
            refused += int(units)
        else:
            units_ok += int(units) if status == "ok" else 0
            failed += int(units) if status == "error" else 0
            usd += Decimal(cost)
            unpriced += int(unp)
        d = by_op.setdefault((prov, op, feat), {"provider": prov, "operation": op, "feature": feat, "units": 0, "usd": 0.0, "failed_units": 0, "refused_units": 0, "unpriced_units": 0})
        key = {"ok": "units", "error": "failed_units", "refused": "refused_units"}[status]
        d[key] += int(units)
        if status != "refused":
            d["usd"] = round(d["usd"] + float(cost), 6)
            d["unpriced_units"] += int(unp)
    by_tenant = db.execute(select(ApiUsage.tenant_id, func.coalesce(func.sum(ApiUsage.units), 0), func.coalesce(func.sum(ApiUsage.est_cost_usd), 0)).where(*ok, ApiUsage.status != "refused")
                           .group_by(ApiUsage.tenant_id)).all()
    return {"usd": _usd(usd), "units": units_ok, "failed_units": failed, "refused_units": refused, "unpriced_units": unpriced, "by_operation": sorted(by_op.values(), key=lambda d: -d["units"]),
            "_by_tenant": {t: (int(u), float(c)) for t, u, c in by_tenant}, "priced": bool(settings.api_prices) or settings.rank_cost_per_call_usd > 0}


def costs(db: Session, month: str | None = None, top: int = 20) -> dict:
    start, end, label = bounds(month)
    ai, api = ai_costs(db, start, end), api_costs(db, start, end)
    tenants = {}
    for t, (c, u, un) in ai.pop("_by_tenant").items():
        tenants.setdefault(t, {"ai_calls": 0, "ai_usd": 0.0, "ai_unpriced_calls": 0, "api_units": 0, "api_usd": 0.0})
        tenants[t].update(ai_calls=c, ai_usd=round(u, 4), ai_unpriced_calls=un)
    for t, (u, c) in api.pop("_by_tenant").items():
        tenants.setdefault(t, {"ai_calls": 0, "ai_usd": 0.0, "ai_unpriced_calls": 0, "api_units": 0, "api_usd": 0.0})
        tenants[t].update(api_units=u, api_usd=round(c, 4))
    names = dict(db.execute(select(Tenant.id, Tenant.name).where(Tenant.id.in_([t for t in tenants if t]))).all()) if tenants else {}
    rows = sorted(({"tenant_id": str(t) if t else None, "name": names.get(t) or ("(platform)" if t is None else "(deleted business)"), **v, "total_usd": round(v["ai_usd"] + v["api_usd"], 4)}
                   for t, v in tenants.items()), key=lambda r: (-r["total_usd"], -(r["ai_calls"] + r["api_units"])))[:top]  # priced cost first, then the busiest unpriced businesses
    total = None if (ai["usd"] is None or api["usd"] is None) else round(ai["usd"] + api["usd"], 4)
    unpriced = ai["unpriced_calls"] + api["unpriced_units"]
    return {"month": label, "ai": ai, "api": api, "total_usd": total, "unpriced_calls_and_units": unpriced,
            "complete": unpriced == 0 and (ai["priced"] or ai["calls"] == 0) and (api["priced"] or api["units"] + api["failed_units"] == 0),
            "note": ("Totals cover only calls with a configured price. " + (f"{unpriced} call(s)/unit(s) had no price configured and are NOT included in the dollar totals." if unpriced else "")).strip(),
            "by_business": rows}


# ---------------------------------------------------------------------------------------------------------------------------------------------
# revenue
# ---------------------------------------------------------------------------------------------------------------------------------------------
def _prices(db: Session) -> dict[str, int]:
    return {p.code: p.price_paise for p in db.scalars(select(BillingPlan))}


def revenue(db: Session, month: str | None = None) -> dict:
    start, end, label = bounds(month)
    price = _prices(db)
    subs = db.scalars(select(Subscription)).all()
    now = utcnow()
    paid = [s for s in subs if s.status == "active" and s.source == "razorpay"]
    at_risk = [s for s in subs if s.status == "past_due" and s.source == "razorpay"]
    mrr = sum(price.get(s.plan, 0) for s in paid)
    dist: dict[str, int] = {}
    for s in paid:
        dist[s.plan] = dist.get(s.plan, 0) + 1
    unknown_price = [s.plan for s in paid if s.plan not in price]
    events = db.scalars(select(SubscriptionEvent).where(SubscriptionEvent.created_at >= start, SubscriptionEvent.created_at < end)).all()
    new_paid = len({e.tenant_id for e in events if e.kind == "activated" and e.source in ("user", "webhook")})
    up = down = 0
    for e in events:
        if e.kind == "plan_changed" and e.from_plan in price and e.to_plan in price and e.source in ("user", "webhook"):
            up += price[e.to_plan] > price[e.from_plan]
            down += price[e.to_plan] < price[e.from_plan]
    lost = sum(price.get(e.from_plan or "", 0) for e in events if e.kind in ("canceled", "expired") and e.from_status in ("active", "past_due") and e.source in ("user", "webhook", "system"))
    promo_new = db.scalar(select(func.count()).select_from(PromotionalGrant).where(PromotionalGrant.created_at >= start, PromotionalGrant.created_at < end)) or 0
    promo_active = db.scalar(select(func.count()).select_from(PromotionalGrant).where(PromotionalGrant.status == "active", PromotionalGrant.ends_at > now)) or 0
    trials_started = sum(1 for e in events if e.kind == "trial_started")
    cohort_den = trials_started + promo_new
    # one-time card revenue: captured card payments in the month, less what was refunded
    cards = db.execute(select(Payment.amount_paise, Payment.status, Payment.meta).where(Payment.kind == "card_order", Payment.paid_at >= start, Payment.paid_at < end, Payment.status.in_(("captured", "refunded")))).all()
    card_gross = sum(a for a, _, _ in cards)
    card_refunds = sum(sum(((m or {}).get("refunds") or {}).values()) for _, _, m in cards)
    sub_pay = db.execute(select(Payment.amount_paise, Payment.status, Payment.meta).where(Payment.kind == "subscription", Payment.paid_at >= start, Payment.paid_at < end, Payment.status.in_(("captured", "refunded")))).all()
    sub_gross = sum(a for a, _, _ in sub_pay)
    sub_refunds = sum(sum(((m or {}).get("refunds") or {}).values()) for _, _, m in sub_pay)
    return {
        "month": label,
        "mrr_paise": metric(mrr, "actual", "Active subscriptions paid through the payment provider, at list price. Trials, the free card month and comped subscriptions are not included."),
        "arr_paise": metric(mrr * 12, "estimated", "MRR x 12: a run-rate, not a forecast or a contract value."),
        "mrr_at_risk_paise": metric(sum(price.get(s.plan, 0) for s in at_risk), "actual", "Paid subscriptions whose last payment failed and are inside the grace period."),
        "paid_subscribers": metric(len(paid), "actual"),
        "plan_distribution": metric(dist, "actual", None if not unknown_price else f"{len(unknown_price)} paid subscription(s) are on a plan with no price row and count as 0 until corrected"),
        "new_paid_subscribers": metric(new_paid, "actual", "Businesses whose subscription became active this month."),
        "upgrades": metric(up, "actual"), "downgrades": metric(down, "actual"),
        "mrr_lost_paise": metric(lost, "actual", "List price of subscriptions that were cancelled or lapsed this month."),
        "trials_in_progress": metric(sum(1 for s in subs if s.status == "trialing" and s.source == "trial" and (s.trial_ends_at or now) > now), "actual", "Not revenue."),
        "comped_subscriptions": metric(sum(1 for s in subs if s.source == "manual" and s.status in ("manual", "active")), "actual", "Given free by an admin. Not revenue."),
        "promotional_growth_activations": metric(promo_new, "actual", "Free Growth months started by a card purchase this month. Not MRR."),
        "promotional_growth_active_now": metric(promo_active, "actual"),
        "free_to_paid_conversion": (metric(round(new_paid / cohort_den, 3), "estimated", "New paid subscribers this month divided by trials and promotional months started this month. A period ratio, not a cohort study.")
                                    if cohort_den else metric(None, "missing", "No trials or promotional months started this month.", "trial or promo activity in the period")),
        "card_revenue_paise": metric(card_gross - card_refunds, "actual", "ONE-TIME revenue from physical cards (net of refunds). Never part of MRR or ARR."),
        "card_revenue_refunded_paise": metric(card_refunds, "actual"),
        "subscription_cash_collected_paise": metric(sub_gross - sub_refunds, "actual", "Cash actually captured for subscriptions this month, net of refunds. Differs from MRR."),
    }


# ---------------------------------------------------------------------------------------------------------------------------------------------
# variable costs and unit economics
# ---------------------------------------------------------------------------------------------------------------------------------------------
def economics(db: Session, month: str | None = None) -> dict:
    start, end, label = bounds(month)
    c, r = costs(db, month), revenue(db, month)
    rate = settings.usd_inr_rate
    paid = r["paid_subscribers"]["value"]
    cash_inr = (r["subscription_cash_collected_paise"]["value"] + r["card_revenue_paise"]["value"]) / 100
    n_cards = db.scalar(select(func.coalesce(func.sum(CardOrder.quantity), 0)).where(CardOrder.status.in_(("paid", "processing", "shipped")), CardOrder.created_at >= start, CardOrder.created_at < end)) or 0
    n_orders = db.scalar(select(func.count()).select_from(CardOrder).where(CardOrder.status.in_(("paid", "processing", "shipped")), CardOrder.created_at >= start, CardOrder.created_at < end)) or 0
    captured = (r["subscription_cash_collected_paise"]["value"] + r["card_revenue_paise"]["value"]) / 100

    lines: dict[str, dict] = {}
    lines["ai_and_google_api"] = (metric(round(c["total_usd"] * rate, 2), "actual" if c["complete"] else "estimated", "AI and Google API usage in INR at the configured rate" + ("" if c["complete"] else "; some calls had no price configured and are excluded"))
                                 if (rate and c["total_usd"] is not None) else metric(None, "missing", "USD cost cannot be put next to INR revenue without a rate", "USD_INR_RATE (and AI / API prices)"))
    lines["payment_processing"] = (metric(round(captured * settings.payment_fee_pct / 100, 2), "estimated", f"{settings.payment_fee_pct}% of cash captured") if settings.payment_fee_pct is not None
                                  else metric(None, "missing", needs="PAYMENT_FEE_PCT (the provider's fee; check your Razorpay dashboard)"))
    lines["card_manufacturing"] = (metric(round(n_cards * settings.card_unit_cost_inr, 2), "estimated", f"{n_cards} cards x the PROVISIONAL unit cost of {settings.card_unit_cost_inr}; the real cost is not confirmed")
                                  if settings.card_unit_cost_inr is not None else metric(None, "missing", needs="CARD_UNIT_COST_INR (about 75 per card was an estimate: packaging, shipping and fulfilment are not confirmed)"))
    lines["card_fulfilment"] = (metric(round(n_orders * settings.card_fulfilment_per_order_inr, 2), "estimated", f"{n_orders} orders") if settings.card_fulfilment_per_order_inr is not None
                               else metric(None, "missing", needs="CARD_FULFILMENT_PER_ORDER_INR"))
    fixed = {"hosting": settings.hosting_monthly_inr, "support": settings.support_monthly_inr}
    for k, v in fixed.items():
        lines[k] = metric(v, "estimated", "A figure you configured, not a measurement") if v is not None else metric(None, "missing", needs=f"{k.upper()}_MONTHLY_INR")
    var_keys = ("ai_and_google_api", "payment_processing", "card_manufacturing", "card_fulfilment")
    missing_var = [k for k in var_keys if lines[k]["value"] is None]
    known_var = round(sum(lines[k]["value"] for k in var_keys if lines[k]["value"] is not None), 2)
    out = {"month": label, "cost_lines_inr": lines, "known_variable_costs_inr": metric(known_var, "estimated", "Only the cost lines that are known. NOT total cost" if missing_var else "All variable cost lines are known"),
           "missing_variable_inputs": missing_var}
    out["contribution_margin_inr"] = (metric(round(cash_inr - known_var, 2), "estimated", "Cash collected minus all variable costs") if not missing_var
                                      else metric(None, "missing", "A margin needs every variable-cost input; showing a partial one would overstate it", ", ".join(missing_var)))
    out["contribution_margin_pct"] = (metric(round(100 * (cash_inr - known_var) / cash_inr, 1), "estimated") if (not missing_var and cash_inr > 0) else metric(None, "missing", needs="every variable cost input, and some revenue"))

    arpa = (r["mrr_paise"]["value"] / 100 / paid) if paid else None
    out["revenue_per_paid_business_inr"] = metric(round(arpa, 2), "actual", "MRR / paid subscribers") if arpa is not None else metric(None, "missing", "No paid subscribers yet", "a paid subscriber")
    active_n = db.scalar(select(func.count()).select_from(Tenant).where(Tenant.is_active.is_(True))) or 0
    ai_api = lines["ai_and_google_api"]["value"]
    out["variable_ai_api_cost_per_business_inr"] = (metric(round(ai_api / active_n, 2), "estimated", "AI and Google API cost / all active businesses (free ones cost too)") if (ai_api is not None and active_n)
                                                    else metric(None, "missing", needs="USD_INR_RATE and prices"))
    mkt = settings.marketing_spend_monthly_inr
    new_paid = r["new_paid_subscribers"]["value"]
    out["customer_acquisition_cost_inr"] = (metric(round(mkt / new_paid, 2), "estimated", "Marketing spend you configured / new paid subscribers this month") if (mkt is not None and new_paid)
                                            else metric(None, "missing", "Needs a marketing spend and at least one new paid subscriber this month", "MARKETING_SPEND_MONTHLY_INR"))
    # lifetime value needs an observed churn rate: with none observed there is no honest lifetime, so it is MISSING rather than infinite
    lost_n = db.scalar(select(func.count()).select_from(SubscriptionEvent).where(SubscriptionEvent.created_at >= start, SubscriptionEvent.created_at < end, SubscriptionEvent.kind.in_(("canceled", "expired")),
                                                                                  SubscriptionEvent.from_status.in_(("active", "past_due")))) or 0
    churn = (lost_n / (paid + lost_n)) if (paid + lost_n) else None
    gm = out["contribution_margin_pct"]["value"]
    out["monthly_paid_churn"] = metric(round(churn, 4), "estimated", "Paid subscriptions lost this month / (paid now + lost)") if churn is not None else metric(None, "missing", needs="paid subscribers")
    if arpa is not None and churn and gm is not None:
        ltv = arpa * (gm / 100) / churn
        out["lifetime_value_inr"] = metric(round(ltv, 2), "estimated", "revenue per business x margin / monthly churn; one month of churn data is a thin basis")
        cac = out["customer_acquisition_cost_inr"]["value"]
        out["ltv_to_cac"] = metric(round(ltv / cac, 2), "estimated") if cac else metric(None, "missing", needs="CAC")
        out["cac_payback_months"] = metric(round(cac / (arpa * gm / 100), 1), "estimated") if (cac and gm > 0) else metric(None, "missing", needs="CAC and a positive margin")
    else:
        why = "No paid churn has been observed yet, so a lifetime cannot be estimated honestly" if not churn else "needs a margin and revenue per business"
        for k in ("lifetime_value_inr", "ltv_to_cac", "cac_payback_months"):
            out[k] = metric(None, "missing", why, "paid subscribers, observed churn, every variable cost input")
    fixed_total = sum(v for v in fixed.values() if v is not None) if all(v is not None for v in fixed.values()) else None
    unit = (arpa - (ai_api / active_n if (ai_api is not None and active_n) else 0)) if arpa is not None else None
    out["break_even_paid_businesses"] = (metric(int(-(-fixed_total // unit)), "estimated", "Fixed costs / (revenue per paid business minus its AI/API cost); ignores payment fees and cards")
                                         if (fixed_total is not None and unit and unit > 0) else metric(None, "missing", needs="HOSTING_MONTHLY_INR, SUPPORT_MONTHLY_INR and a paid subscriber"))
    return {"revenue": r, "costs_usd": c, "economics": out,
            "reading_guide": "actual = measured; estimated = measured plus a stated assumption or a figure you configured; missing = an input was never provided. Nothing missing is treated as zero."}
