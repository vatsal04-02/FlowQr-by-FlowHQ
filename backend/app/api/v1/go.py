"""The redirect door: GET /api/v1/go/{token} answers a real HTTP 302.

  * a live card WITH an admin-set destination  -> 302 to that destination (stored in the database; nothing in the request can change it)
  * every other known card (no destination, paused, unassigned, retired...)  -> 302 to the card's normal landing page, which shows the review page or the neutral "not active" notice
  * an unknown token -> 404, not recorded (probes would grow the table)
A scan is recorded exactly as on the landing page (channel qr or nfc, bots flagged, 20-second refresh dedupe). Rate limited per IP. Never cached: a destination change applies at once."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.v1 import public as pub
from app.core.config import settings
from app.core.deps import public_db
from app.core.rate_limit import limit_by_ip
from app.services.qr import card_url

router = APIRouter(prefix="/go", tags=["public"])
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


@router.get("/{token}", dependencies=[Depends(limit_by_ip("go", settings.rl_public_scan_per_minute, 60))])
def go(token: str, request: Request, channel: str | None = None, ref: str | None = None, db: Session = Depends(public_db)):
    out = pub.resolve_card(token, request, channel, ref, db)  # same rules, same recording, same 404 for unknown tokens
    if out.get("state") == "redirect":
        return RedirectResponse(out["url"], status_code=302, headers=NO_STORE)
    card = pub._find_card(db, token)
    return RedirectResponse(card_url(token, card.qr_path or "c") if card else settings.frontend_url, status_code=302, headers=NO_STORE)
