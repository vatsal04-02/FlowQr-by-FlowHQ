"""Operator CLI for TEMPORARY prepaid price overrides.

    python -m app.prepaid_cli override-create --tenant <uuid> --plan growth --months 1 --amount-paise 100 --hours 48 --reason "owner payment test"
    python -m app.prepaid_cli override-list [--tenant <uuid>]
    python -m app.prepaid_cli override-revoke --id <uuid>

An override is for ONE business, ONE plan and term, used ONCE, and expires (`--hours`, at most 168). It can only lower a price (never below Rs 1). The permanent price list is not touched; the list
price is stored on the override and on every order. Nothing here is reachable from the web: no API route creates or revokes an override.
"""
import argparse
import sys
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.core.db import system_session
from app.models import PrepaidPriceOverride, Tenant
from app.models.base import utcnow
from app.services import plans as plans_svc
from app.services.audit import audit


def create(tenant: str, plan: str, months: int, amount_paise: int, hours: int, reason: str, label: str = "Test price") -> int:
    if not (1 <= hours <= 168):
        print("FAIL --hours must be between 1 and 168 (an override always expires)")
        return 2
    if len(reason.strip()) < 10:
        print("FAIL --reason must say why (at least 10 characters)")
        return 2
    list_price = (plans_svc.TERM_PRICES_PAISE.get(plan) or {}).get(months)
    if not list_price:
        print(f"FAIL {plan} for {months} month(s) is not in the price list")
        return 2
    if not (100 <= amount_paise < list_price):
        print(f"FAIL the amount must be at least 100 paise and LOWER than the list price ({list_price} paise)")
        return 2
    db = system_session()
    try:
        t = db.get(Tenant, uuid.UUID(tenant))
        if t is None:
            print("FAIL no such business")
            return 2
        now = utcnow()
        for old in db.scalars(select(PrepaidPriceOverride).where(PrepaidPriceOverride.tenant_id == t.id, PrepaidPriceOverride.plan_code == plan, PrepaidPriceOverride.months == months,
                                                                 PrepaidPriceOverride.revoked_at.is_(None), PrepaidPriceOverride.used_order_id.is_(None))):
            old.revoked_at = now  # one live override per business, plan and term
        ov = PrepaidPriceOverride(tenant_id=t.id, plan_code=plan, months=months, amount_paise=amount_paise, list_price_paise=list_price, label=label[:60], reason=reason.strip()[:300],
                                  expires_at=now + timedelta(hours=hours))
        db.add(ov)
        db.flush()
        audit(db, action="billing.prepaid_override_created", tenant_id=t.id, entity_type="prepaid_override", entity_id=ov.id,
              meta={"plan": plan, "months": months, "amount_paise": amount_paise, "list_price_paise": list_price, "expires_at": ov.expires_at.isoformat()})
        db.commit()
        print(f"OK override {ov.id}: business '{t.name}' may pay {amount_paise} paise (list {list_price}) for {plan} x {months} month(s), once, until {ov.expires_at:%Y-%m-%d %H:%M} UTC")
        return 0
    finally:
        db.close()


def listing(tenant: str | None) -> int:
    db = system_session()
    try:
        q = select(PrepaidPriceOverride).order_by(PrepaidPriceOverride.created_at.desc())
        if tenant:
            q = q.where(PrepaidPriceOverride.tenant_id == uuid.UUID(tenant))
        now = utcnow()
        for o in db.scalars(q.limit(50)):
            state = "used" if o.used_order_id else "revoked" if o.revoked_at else "expired" if o.expires_at <= now else "ACTIVE"
            print(f"{o.id} tenant={o.tenant_id} {o.plan_code} x{o.months} {o.amount_paise}p (list {o.list_price_paise}p) {state} expires={o.expires_at:%Y-%m-%d %H:%M} reason={o.reason!r}")
        return 0
    finally:
        db.close()


def revoke(oid: str) -> int:
    db = system_session()
    try:
        o = db.get(PrepaidPriceOverride, uuid.UUID(oid))
        if o is None:
            print("FAIL no such override")
            return 2
        o.revoked_at = o.revoked_at or utcnow()
        audit(db, action="billing.prepaid_override_revoked", tenant_id=o.tenant_id, entity_type="prepaid_override", entity_id=o.id, meta={})
        db.commit()
        print("OK revoked")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="prepaid_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("override-create")
    c.add_argument("--tenant", required=True)
    c.add_argument("--plan", required=True)
    c.add_argument("--months", type=int, required=True)
    c.add_argument("--amount-paise", type=int, required=True)
    c.add_argument("--hours", type=int, required=True)
    c.add_argument("--reason", required=True)
    c.add_argument("--label", default="Test price")
    sub.add_parser("override-list").add_argument("--tenant")
    sub.add_parser("override-revoke").add_argument("--id", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "override-create":
        return create(a.tenant, a.plan, a.months, a.amount_paise, a.hours, a.reason, a.label)
    if a.cmd == "override-list":
        return listing(a.tenant)
    return revoke(a.id)


if __name__ == "__main__":
    sys.exit(main())
