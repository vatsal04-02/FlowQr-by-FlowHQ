import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1 import (
    leads, webhooks,
    account, admin, agent, autonomy_actions, analytics, auth_google, billing, gbp, posts, reports, workspace, auth, cards, google, locations, public, qr, review_growth, review_public, reviews, tenants, notifications, photos, request_templates, admin_users, rank, rank_grid, ops
)
from app.core.config import assert_production_safe, settings
from app.core.db import engine

log = logging.getLogger("flowqr")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO if not settings.hardened else logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")
assert_production_safe(settings)
from app.core import monitoring  # noqa: E402

monitoring.init("api")
monitoring.redact_access_logs()

app = FastAPI(
    title="FlowQR by FlowHQ API",
    version="0.1.0",
    docs_url=None if settings.hardened else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.hardened else "/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Tenant-Id"],
    # The site and the API are different hosts in production (flowqr.site, api.flowqr.site), so the browser hides every response header that is not listed here. These are the
    # ones the frontend reads (download file names, the "not for print" and "scannable" QR checks, export counts): without this list those warnings would silently vanish.
    expose_headers=["Content-Disposition", "X-FlowQR-Codes", "X-FlowQR-Not-For-Print", "X-FlowQR-Scannable", "X-FlowQR-Style", "X-FlowQR-Style-Fallbacks", "X-FlowQR-Total", "X-FlowQR-Verified"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")  # the API only serves JSON and images
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # Never leak internals / tokens in error responses.
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})


@app.get("/api/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/ready")
def ready():
    """Readiness for a load balancer or a deploy script: can this instance serve traffic? Database reachable, Redis reachable, and the database is at the revision this code expects
    (a deploy that skipped the migration is NOT ready). Only statuses are returned: no hostnames, revisions or error text. The worker heartbeat is deliberately not part of this
    (a stopped worker must not take the website down); it is on Admin > Operations."""
    from app.core.db import SessionLocal
    from app.services import ops

    db = SessionLocal()
    try:
        checks = [ops.check_database(db), ops.check_redis(), ops.check_migrations(db)]
    finally:
        db.close()
    ok = all(c["status"] == "ok" for c in checks)
    return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, "checks": {c["id"]: c["status"] for c in checks}})


API = "/api/v1"
for module in (ops, leads, notifications, photos, rank, rank_grid, request_templates, admin_users, account, agent, autonomy_actions, posts, reports, workspace, auth, auth_google, tenants, locations, cards, qr, admin, public, review_public, review_growth, google, reviews, analytics, billing, gbp, webhooks):
    app.include_router(module.router, prefix=API)
