"""The tracked-link door: GET /api/v1/l/{token} answers a real HTTP 302 to the link's FIXED destination.

  * The destination is read from the database. The route takes no URL, no redirect target and no other parameter, so nothing in a request can change where it goes: it is not an open redirect.
  * Unknown or malformed tokens answer 404 and record nothing.
  * Rate limited per visitor and per token. The visitor's address is hashed with the server secret for the counter and is never stored anywhere else.
  * HEAD requests, known bot and preview agents, and repeat opens inside the dedupe window are not counted (they still redirect). A click records the link, the customer, the message and the time: no address
    and no browser.
  * A link whose message or customer was deleted still redirects, for as long as the business exists. Counting happens only on the Pro add-on.
  * Never cached, never sends a referrer."""
import hashlib
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import public_db
from app.core.rate_limit import client_ip, hit
from app.services.whatsapp import links

router = APIRouter(prefix="/l", tags=["public"])
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow"}


def _keyed(scope: str, value: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"{scope}:{value}".encode(), hashlib.sha256).hexdigest()[:24]


def _lookup(token: str, request: Request, db: Session):
    if not hit(f"wa-link-ip:{_keyed('ip', client_ip(request))}", settings.rl_link_per_ip_per_minute, 60) or not hit(f"wa-link-token:{_keyed('token', token)}", settings.rl_link_per_token_per_minute, 60):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.", headers={"Retry-After": "60"})
    link = links.resolve(db, token)
    if link is None:
        raise HTTPException(status_code=404, detail="Not found")
    return link


@router.get("/{token}")
def follow(token: str, request: Request, db: Session = Depends(public_db)):
    link = _lookup(token, request, db)
    try:
        links.maybe_record(db, link, request.headers.get("user-agent"))
        db.commit()
    except Exception:  # noqa: BLE001 - counting must never stop the customer reaching the page
        db.rollback()
    return RedirectResponse(link.destination, status_code=302, headers=NO_STORE)


@router.head("/{token}", include_in_schema=False)
def follow_head(token: str, request: Request, db: Session = Depends(public_db)):
    """A HEAD is never a click: it only answers where the link goes."""
    link = _lookup(token, request, db)
    return RedirectResponse(link.destination, status_code=302, headers=NO_STORE)
