"""Published websites hosted by FlowQR (SITES_PROVIDER=app): GET renders the PUBLISHED snapshot (never the draft) with the business's current Google reviews; POST receives the enquiry form.

The pages are served under the app's own site, so every answer is sandboxed into its own opaque origin (hosting.APP_CSP) and ships no JavaScript. No cookie is read or set here. Anything that is
not a published, paid-or-complimentary, active site answers the same 404."""
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import public_db
from app.core.rate_limit import client_ip, limit_by_ip
from app.models import Site, Tenant
from app.services.sites import content as CT
from app.services.sites import hosting, render
from app.services.sites import service as svc

router = APIRouter(prefix="/public-site", tags=["sites-public"])

HEADERS = {"Content-Security-Policy": hosting.APP_CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "strict-origin-when-cross-origin", "X-Frame-Options": "DENY"}
NOT_FOUND = "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Not found</title><h1>This website is not available</h1>"
MAX_FORM = 8192


def _missing() -> HTMLResponse:
    return HTMLResponse(NOT_FOUND, status_code=404, headers={**HEADERS, "Cache-Control": "no-store"})


def _live(db: Session, slug: str) -> Site | None:
    if not (settings.sites_enabled and settings.sites_provider == "app"):
        return None
    site = db.scalar(select(Site).where(Site.site_slug == slug))
    if site is None or site.status != "published" or not site.published_content or site.commercial_status not in ("complimentary", "paid_offline"):
        return None
    tenant = db.get(Tenant, site.tenant_id)
    return site if tenant is not None and tenant.is_active and not tenant.suspended_at else None


def _files(db: Session, site: Site) -> dict[str, bytes]:
    c = site.published_content
    assets = svc._assets(db, site, CT.referenced_assets({"business": c["business"], "seo": c["seo"], "sections": [s for s in c["sections"] if s["enabled"]]}), True)
    return render.build_site(c, site.template_key, host=svc.host_of(site), assets=assets, retention_days=settings.sites_enquiry_retention_days,
                             base=svc.public_base(site), origin=settings.frontend_url, reviews=svc.live_reviews(db, site.tenant_id))


def _serve(slug: str, path: str, db: Session) -> Response:
    site = _live(db, slug)
    if site is None:
        return _missing()
    files = _files(db, site)
    path = path.strip("/")
    key = path if path in files else f"{path}/index.html".lstrip("/")
    if path.startswith("_") or key not in files or key.startswith("_"):
        return _missing()
    cache = "public, max-age=31536000, immutable" if key.endswith((".css", ".webp")) else "public, max-age=60"
    return Response(files[key], media_type=hosting.content_type_for(key), headers={**HEADERS, "Cache-Control": cache})


@router.get("/{slug}", dependencies=[Depends(limit_by_ip("public-site", 600, 60))])
def home(slug: str, db: Session = Depends(public_db)):
    return _serve(slug, "", db)


@router.get("/{slug}/{path:path}", dependencies=[Depends(limit_by_ip("public-site", 600, 60))])
def page(slug: str, path: str, db: Session = Depends(public_db)):
    return _serve(slug, path, db)


@router.post("/{slug}/_enquiry", dependencies=[Depends(limit_by_ip("public-site-enquiry", 60, 60))])
async def enquiry(slug: str, request: Request, db: Session = Depends(public_db)):
    """The form on a hosted site. A plain form post (no JavaScript), answered with a redirect to the thank-you or problem page."""
    site = _live(db, slug)
    if site is None:
        return _missing()
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_FORM:
            raise HTTPException(status_code=413, detail="Too large")
    form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True).items()}
    payload = {k: form.get(k, "") for k in ("name", "phone", "email", "message", "website")}
    payload["consent"] = form.get("consent") == "yes"
    payload["whatsapp_ok"] = form.get("whatsapp_ok") == "yes"
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or client_ip(request)  # behind the app's rewrite; used only for rate limits, stored only as a one-way code
    base = svc.public_base(site)
    try:
        svc.create_enquiry(db, host=svc.host_of(site), payload=payload, ip=ip)
    except svc.SiteError:
        db.rollback()
        return RedirectResponse(f"{base}/problem", status_code=303, headers=HEADERS)
    db.commit()
    return RedirectResponse(f"{base}/thanks", status_code=303, headers=HEADERS)
