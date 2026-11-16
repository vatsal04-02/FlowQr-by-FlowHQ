"""Inbound payment-provider webhooks. Public by necessity, so each one proves itself: no cookie, no CSRF, its own signature over the RAW body.

POST /api/v1/webhooks/cashfree
  1. 404 unless Cashfree billing is switched on (the endpoint does not exist for a deployment that does not use it)
  2. body size cap, then the signature and timestamp check on the raw bytes (a refusal is a generic 400; the real reason goes to the log only)
  3. the event is stored BEFORE it is processed, under a key built from fields that are really in the payload (Cashfree sends no event id)
  4. a repeat of an event that was processed is acknowledged and ignored; one that failed is processed again
  5. processing treats the event as a hint: the tenant comes from OUR subscription id, and the truth is re-read from Cashfree
  6. 2xx only after the event is safely stored; a processing failure answers 500 so a retry (Cashfree's, the hourly reconcile, or an administrator's) can finish the job"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db, set_rls_context
from app.core.rate_limit import limit_by_ip
from app.services import billing_cashfree as cfb
from app.services import cashfree as cf

log = logging.getLogger("flowqr.webhooks")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])
MAX_BODY = 64 * 1024


@router.post("/cashfree", dependencies=[Depends(limit_by_ip("cf-webhook", 300, 60))])
async def cashfree_webhook(request: Request, x_webhook_signature: str | None = Header(default=None), x_webhook_timestamp: str | None = Header(default=None),
                           db: Session = Depends(get_db)):
    if not settings.cashfree_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY:
        raise HTTPException(status_code=413, detail="Payload too large")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        cf.verify_webhook(raw, x_webhook_signature, x_webhook_timestamp)
        env = cf.parse_envelope(raw)
    except cf.WebhookError as exc:
        log.warning("Cashfree webhook refused: %s", exc.reason)
        raise HTTPException(status_code=400, detail="Invalid webhook")
    set_rls_context(db, bypass=True)
    row, is_new = cfb.record_event(db, env)
    if row is None:  # lost a race with an identical delivery: the other request owns it
        db.commit()
        return {"status": "duplicate"}
    if not is_new and row.status in ("processed", "ignored"):
        db.commit()
        return {"status": "duplicate"}
    try:
        client = cf.get_cashfree()
    except cf.CashfreeNotConfigured:
        db.commit()
        raise HTTPException(status_code=503, detail="Billing is not configured")
    try:
        result = cfb.process_event(db, client, row, env)
        db.commit()
    except cf.CashfreeError:
        db.commit()  # keep the stored event and its failure note so it can be processed again
        raise HTTPException(status_code=500, detail="Processing failed")
    except Exception:
        db.rollback()
        log.exception("Cashfree webhook processing failed (%s)", env.type)
        raise HTTPException(status_code=500, detail="Processing failed")
    return {"status": result}
