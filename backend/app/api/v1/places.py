"""Set-up helpers: find a business or an address on Google while typing, and look up a PIN code. Any signed-in person may use them (the business does not exist yet at
the first step). They return only what the forms need; the Google key stays on the server. See services/places_suggest.py for the cost limits."""
import re

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import AuthContext, get_auth_context
from app.core.rate_limit import hit
from app.services import places_suggest as svc

router = APIRouter(prefix="/places", tags=["places"])
_SESSION = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_PLACE_ID = re.compile(r"^[A-Za-z0-9_-]{10,200}$")


def _throttle(ctx: AuthContext) -> None:
    if not hit(f"places-suggest:{ctx.user.id}", 90, 60):
        raise HTTPException(status_code=429, detail="Too many suggestions at once. Slow down a little.")


def _fail(e: svc.SuggestError):
    return HTTPException(status_code=e.status, detail=str(e))


@router.get("/autocomplete")
def autocomplete(q: str = Query(min_length=3, max_length=80), kind: str = Query("business", pattern="^(business|address)$"),
                 session: str = Query(min_length=8, max_length=64), ctx: AuthContext = Depends(get_auth_context)):
    """Suggestions for a business name (kind=business) or a street address (kind=address). `enabled: false` means the server has no Google key: the form stays manual."""
    client = svc.get_client()
    if client is None:
        return {"enabled": False, "suggestions": []}
    if not _SESSION.match(session):
        raise HTTPException(status_code=422, detail="Bad session")
    _throttle(ctx)
    if (why := svc.budget_problem(ctx.user.id)):
        svc._record(ctx.user.id, "autocomplete", "refused", why[:190])
        return {"enabled": False, "suggestions": [], "note": why}
    try:
        items = client.autocomplete(q.strip(), kind, session)
    except svc.SuggestError as e:
        svc._record(ctx.user.id, "autocomplete", "error", str(e)[:190])
        if e.status == 429:
            raise _fail(e)
        return {"enabled": True, "suggestions": [], "note": str(e)}
    svc._record(ctx.user.id, "autocomplete")
    return {"enabled": True, "suggestions": items}


@router.get("/details")
def details(place_id: str = Query(min_length=10, max_length=200), session: str = Query(min_length=8, max_length=64), ctx: AuthContext = Depends(get_auth_context)):
    """The chosen place, shaped for the forms: name, street, city, state, PIN, a mobile number if Google lists one, website, our category and Google's review link."""
    client = svc.get_client()
    if client is None:
        raise HTTPException(status_code=404, detail="Suggestions are not switched on")
    if not _PLACE_ID.match(place_id) or not _SESSION.match(session):
        raise HTTPException(status_code=422, detail="Bad place")
    _throttle(ctx)
    if (why := svc.budget_problem(ctx.user.id)):
        svc._record(ctx.user.id, "getPlace", "refused", why[:190])
        raise HTTPException(status_code=429, detail=why)
    try:
        g = client.details(place_id, session)
    except svc.SuggestError as e:
        svc._record(ctx.user.id, "getPlace", "error", str(e)[:190])
        raise _fail(e)
    svc._record(ctx.user.id, "getPlace")
    return svc.shape_details(g)


@router.get("/pincode/{pin}")
def pincode(pin: str, ctx: AuthContext = Depends(get_auth_context)):
    """City and state for an Indian PIN code (India Post's public directory). Works without a Google key."""
    _throttle(ctx)
    try:
        found = svc.lookup_pincode(pin)
    except svc.SuggestError as e:
        raise _fail(e)
    if not found:
        raise HTTPException(status_code=404, detail="We could not find that PIN code")
    return found
