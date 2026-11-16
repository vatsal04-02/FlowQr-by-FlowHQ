"""One ledger for external API usage that costs money or is rate-limited: Google Places searches and Google Business Profile calls.

AI model calls have their own ledger (`ai_call_ledger`, services/ai_usage.py) and this module reads both for the cost views; it does not duplicate that tracking.

Rules that matter:
  * PRICES ARE CONFIGURED, NEVER ASSUMED. `settings.api_prices` maps "<provider>.<operation>" to USD per unit. A call whose price is not configured is recorded with
    est_cost_usd = NULL and priced = False. It is never recorded as free, and every total says how many units were unpriced.
  * What is counted is what was actually requested: one row per Places search (a map point is one search, a scan of 9 points is 9 rows), one per position lookup, one per
    Business Profile write. A scan is not "one request".
  * Retries cannot double count: a row can carry an idempotency key, and a second row with the same key for the same business is not written.
  * A refused call (over a cap, plan, budget) is recorded too, with the reason, in its own transaction, so it survives the rollback that usually follows a refusal.
  * Rows are append-only for the application (SELECT and INSERT only) and have no foreign key to tenants, so spend history outlives a deleted business."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ApiUsage, Tenant
from app.models.base import utcnow

log = logging.getLogger("flowqr.usage")
PLACES, GBP = "places", "google_business"


def price_for(provider: str, operation: str) -> Decimal | None:
    """USD per unit, or None when no price is configured. `api_prices` wins; for Places the older single `rank_cost_per_call_usd` is the fallback."""
    p = (settings.api_prices or {}).get(f"{provider}.{operation}")
    if p is None and provider == PLACES and settings.rank_cost_per_call_usd > 0:
        p = settings.rank_cost_per_call_usd
    return Decimal(str(p)) if p is not None else None


def month_start(now: datetime | None = None) -> datetime:
    n = now or utcnow()
    return datetime(n.year, n.month, 1, tzinfo=n.tzinfo)


def _row(*, tenant_id, provider, operation, feature, units, status, location_id, user_id, request_id, idempotency_key, reason, meta) -> dict:
    price = price_for(provider, operation)
    return dict(id=uuid.uuid4(), tenant_id=tenant_id, google_location_id=location_id, user_id=user_id, created_at=utcnow(), provider=provider, operation=operation[:48], feature=feature[:32],
                units=units, status=status, reason=(reason or None) and reason[:200], request_id=request_id, idempotency_key=idempotency_key,
                est_cost_usd=(price * units) if (price is not None and status != "refused") else None, priced=price is not None and status != "refused", meta=meta or {})


def record(db: Session, *, tenant_id: uuid.UUID | None, provider: str, operation: str, feature: str, units: int = 1, status: str = "ok", location_id=None, user_id=None,
           request_id: str | None = None, idempotency_key: str | None = None, reason: str | None = None, meta: dict | None = None) -> bool:
    """Add one usage row to the CALLER'S transaction. Returns False when the idempotency key was already recorded (nothing was written)."""
    values = _row(tenant_id=tenant_id, provider=provider, operation=operation, feature=feature, units=units, status=status, location_id=location_id, user_id=user_id,
                  request_id=request_id, idempotency_key=idempotency_key, reason=reason, meta=meta)
    stmt = pg_insert(ApiUsage.__table__).values(**{("metadata" if k == "meta" else k): v for k, v in values.items()})
    if idempotency_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"], index_where=ApiUsage.__table__.c.idempotency_key.is_not(None))
    # RETURNING, not rowcount: the driver reports -1 for this statement, which would make every call look like it wrote a row
    return db.execute(stmt.returning(ApiUsage.__table__.c.id)).first() is not None


def record_isolated(**kw) -> None:
    """The same, in its own transaction: for refusals and failures that are followed by a rollback. Never raises (a bookkeeping failure must not hide the real error)."""
    from app.core.db import SessionLocal, set_rls_context

    db = SessionLocal()
    try:
        set_rls_context(db, bypass=True)
        record(db, **kw)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("could not record an API usage row")
    finally:
        db.close()


def units_this_month(db: Session, tenant_id: uuid.UUID | None, provider: str = PLACES, now: datetime | None = None) -> int:
    """Units actually requested this calendar month (successful and failed requests both cost; refused ones did not happen)."""
    q = select(func.coalesce(func.sum(ApiUsage.units), 0)).where(ApiUsage.provider == provider, ApiUsage.created_at >= month_start(now), ApiUsage.status.in_(("ok", "error")))
    if tenant_id is not None:
        q = q.where(ApiUsage.tenant_id == tenant_id)
    return int(db.scalar(q) or 0)


def tenant_places_cap(db: Session, tenant_id: uuid.UUID) -> int | None:
    return db.scalar(select(Tenant.places_monthly_cap).where(Tenant.id == tenant_id))


def places_budget_problem(db: Session, tenant_id: uuid.UUID, need: int, *, feature: str, location_id=None) -> str | None:
    """Why `need` more Places searches may not be made for this business right now, or None. A refusal is recorded. Covers the per-business ceiling an admin can set;
    the plan allowance and the platform-wide cap are enforced where they are defined (rank.py, rank_grid.py) and recorded here too when they refuse."""
    cap = tenant_places_cap(db, tenant_id)
    if cap is None:
        return None
    used = units_this_month(db, tenant_id)
    if used + need > cap:
        msg = f"This business's monthly limit of {cap} Google searches is reached ({used} used). It resets on the 1st."
        record_isolated(tenant_id=tenant_id, provider=PLACES, operation="searchText", feature=feature, units=need, status="refused", location_id=location_id, reason="business monthly cap")
        return msg
    return None


def refused(tenant_id, feature: str, reason: str, *, units: int = 1, location_id=None, operation: str = "searchText", provider: str = PLACES) -> None:
    record_isolated(tenant_id=tenant_id, provider=provider, operation=operation, feature=feature, units=units, status="refused", location_id=location_id, reason=reason)
