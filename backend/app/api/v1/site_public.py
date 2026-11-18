"""The ONE public endpoint of the website builder: the enquiry form's backend.

It is not called by a visitor's browser. A visitor's form posts to their own website's address; the hosting Worker (deploy/cloudflare/sites-worker) validates the hostname, then forwards the form here,
server to server, with a secret service token. That is why:
  * no CORS entry is needed or added for any business website (the API never accepts a browser request from a business hostname)
  * no cookie is read or set: session and CSRF cookies are irrelevant to this route and ignored
  * the token is a long random secret compared in constant time; a wrong token is refused before anything else is looked at, and the route answers 404 while websites are switched off
  * the visitor's address comes from the Worker (`client_ip`), which is trustworthy only because of the token
Unknown, unpublished, suspended and unpaid sites all get the same 404."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import public_db
from app.core.rate_limit import limit_by_ip
from app.core.security import constant_time_equals
from app.schemas.sites import EnquiryPublicIn
from app.services.sites import service as svc

router = APIRouter(tags=["sites-public"])


@router.post("/site-enquiry", status_code=201, dependencies=[Depends(limit_by_ip("site-enquiry-auth", 120, 60))])
def site_enquiry(body: EnquiryPublicIn, request: Request, x_sites_token: str | None = Header(default=None), db: Session = Depends(public_db)):
    if not settings.sites_enabled or len(settings.sites_service_token or "") < 32:
        raise HTTPException(status_code=404, detail="Not found")
    if not x_sites_token or not constant_time_equals(x_sites_token, settings.sites_service_token):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        svc.create_enquiry(db, host=body.host, payload=body.model_dump(), ip=body.client_ip)
    except svc.SiteError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    db.commit()
    return {"ok": True}
