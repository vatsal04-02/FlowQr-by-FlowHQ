"""The Meta WhatsApp webhook. Public by necessity, so it proves itself: the one-time verification needs the verify token; every delivery needs a valid X-Hub-Signature-256 over the RAW body.
No cookie, no CSRF, no CORS. It never trusts the payload to name a business (see services/whatsapp/webhook.py). Answers 404 until WHATSAPP_ENABLED and WHATSAPP_WEBHOOK_ENABLED are both true."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import public_db
from app.core.rate_limit import limit_by_ip
from app.services.whatsapp import webhook as wh

log = logging.getLogger("flowqr.whatsapp.webhook")
router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp-webhook"])


def _live() -> None:
    if not (settings.whatsapp_enabled and settings.whatsapp_webhook_enabled):
        raise HTTPException(status_code=404, detail="Not found")


@router.get("", dependencies=[Depends(limit_by_ip("wa-webhook-verify", 60, 60))])
def verify(request: Request):
    _live()
    q = request.query_params
    challenge = wh.verify_challenge(q.get("hub.mode"), q.get("hub.verify_token"), q.get("hub.challenge"))
    if challenge is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    return PlainTextResponse(challenge)


@router.post("", dependencies=[Depends(limit_by_ip("wa-webhook", 600, 60))])
async def receive(request: Request, db: Session = Depends(public_db)):
    _live()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > wh.MAX_BODY:
        raise HTTPException(status_code=413, detail="Too large")
    raw = await request.body()
    if len(raw) > wh.MAX_BODY:
        raise HTTPException(status_code=413, detail="Too large")
    if not wh.signature_ok(raw, request.headers.get("x-hub-signature-256")):  # before anything is parsed or stored
        log.warning("WhatsApp webhook refused: bad signature")
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        event_id, is_new = wh.receive(db, raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad request")
    db.commit()
    if is_new and event_id:
        wh.enqueue(event_id)
    return {"ok": True}
