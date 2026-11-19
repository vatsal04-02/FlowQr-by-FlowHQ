"""What was sent, whether it arrived, and what it probably cost. Read from the message ledger (whatsapp_messages); nothing is estimated that was not measured, and every money figure is labelled an estimate.

Counts keep Meta's words apart: `sent` is accepted by WhatsApp, `delivered` reached the phone, `read` was opened (only when the customer's read receipts are on). Delivered is never called read."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.whatsapp import WhatsAppContact, WhatsAppMessage
from app.services.whatsapp import WaError, links, pricing

RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}


def month_bounds(month: str | None) -> tuple[datetime, datetime, str]:
    now = utcnow()
    if month:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise WaError(422, "invalid_month", "Choose a month like 2026-11.")
        y, m = int(month[:4]), int(month[5:])
    else:
        y, m = now.year, now.month
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=timezone.utc)
    return start, end, f"{y:04d}-{m:02d}"


def counts(db: Session, tenant_id: uuid.UUID, start: datetime, end: datetime, *, campaign_id: uuid.UUID | None = None, run_automation: bool = False) -> dict:
    q = select(WhatsAppMessage.category, WhatsAppMessage.delivery_status, func.count(), func.coalesce(func.sum(WhatsAppMessage.est_rate), 0)).where(
        WhatsAppMessage.tenant_id == tenant_id, WhatsAppMessage.direction == "outbound", WhatsAppMessage.created_at >= start, WhatsAppMessage.created_at < end)
    if campaign_id:
        q = q.where(WhatsAppMessage.campaign_id == campaign_id)
    out: dict = {}
    for cat, status, n, rate_sum in db.execute(q.group_by(WhatsAppMessage.category, WhatsAppMessage.delivery_status)):
        c = out.setdefault(cat or "other", {"attempted": 0, "sent": 0, "delivered": 0, "read": 0, "failed": 0, "estimated_cost": Decimal(0)})
        c["attempted"] += n
        if status == "failed":
            c["failed"] += n
        else:
            r = RANK.get(status, 0)
            c["sent"] += n if r >= 1 else 0  # accepted by WhatsApp (sent, delivered or read)
            c["delivered"] += n if r >= 2 else 0
            c["read"] += n if r >= 3 else 0
            if r >= 2:
                c["estimated_cost"] += Decimal(rate_sum)  # WhatsApp charges for delivered template messages
    return out


def summary(db: Session, tenant_id: uuid.UUID, month: str | None = None) -> dict:
    start, end, label = month_bounds(month)
    by = counts(db, tenant_id, start, end)
    total = {k: sum(v[k] for v in by.values()) for k in ("attempted", "sent", "delivered", "read", "failed")}
    cost = sum((v["estimated_cost"] for v in by.values()), Decimal(0))
    return {"month": label, "by_category": {k: {**{kk: vv for kk, vv in v.items() if kk != "estimated_cost"}, "estimated_cost": str(v["estimated_cost"].quantize(Decimal("0.01")))} for k, v in by.items()}, "totals": total,
            "estimated_meta_cost": str(cost.quantize(Decimal("0.01"))), "currency": "INR", "note": pricing.NOTE, "links": links.summary(db, tenant_id, start, end),
            "delivery_rate": round(total["delivered"] * 100 / total["sent"]) if total["sent"] else None}


def activity(db: Session, tenant_id: uuid.UUID, *, limit: int = 50, offset: int = 0, status: str | None = None, campaign_id: uuid.UUID | None = None) -> tuple[int, list[dict]]:
    q = select(WhatsAppMessage, WhatsAppContact).join(WhatsAppContact, WhatsAppContact.id == WhatsAppMessage.contact_id, isouter=True).where(WhatsAppMessage.tenant_id == tenant_id, WhatsAppMessage.direction == "outbound")
    if status:
        q = q.where(WhatsAppMessage.delivery_status == status)
    if campaign_id:
        q = q.where(WhatsAppMessage.campaign_id == campaign_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.execute(q.order_by(WhatsAppMessage.created_at.desc()).limit(limit).offset(offset)).all()
    clicks = links.clicked_at_for(db, tenant_id, [m.id for m, _ in rows])
    return total, [{"id": m.id, "to": (c.customer_name if c and c.customer_name else None), "phone_last4": c.phone[-4:] if c else None, "category": m.category, "status": m.delivery_status,
                    "error_code": m.error_code, "sent_at": m.sent_at, "delivered_at": m.delivered_at, "read_at": m.read_at, "created_at": m.created_at, "campaign_id": m.campaign_id,
                    "link_clicked_at": clicks.get(m.id)} for m, c in rows]


def export_csv(db: Session, tenant_id: uuid.UUID, limit: int = 5000) -> str:
    """The business's own message log for its records: when, to whom (last four digits only), what kind, what happened, and whether the link in it was clicked. "link_clicked" never means a review was left."""
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["sent_at", "customer", "phone_last4", "category", "status", "delivered_at", "read_at", "link_clicked", "link_clicked_at"])
    _, rows = activity(db, tenant_id, limit=limit, offset=0)
    for r in rows:
        w.writerow([r["sent_at"].isoformat() if r["sent_at"] else "", ("'" + r["to"]) if r["to"] and r["to"][:1] in ("=", "+", "-", "@") else (r["to"] or ""), r["phone_last4"] or "", r["category"] or "", r["status"],
                    r["delivered_at"].isoformat() if r["delivered_at"] else "", r["read_at"].isoformat() if r["read_at"] else "", "yes" if r["link_clicked_at"] else "no",
                    r["link_clicked_at"].isoformat() if r["link_clicked_at"] else ""])
    return out.getvalue()
