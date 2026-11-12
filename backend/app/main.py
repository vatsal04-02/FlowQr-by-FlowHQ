import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1 import (
    admin, analytics, auth_google, billing, gbp, auth, cards, google, locations, public, qr, review_growth, review_public, reviews, tenants,
)
from app.core.config import assert_production_safe, settings
from app.core.db import engine

log = logging.getLogger("flowqr")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO if not settings.hardened else logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")
assert_production_safe(settings)

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
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
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


API = "/api/v1"
for module in (auth, auth_google, tenants, locations, cards, qr, admin, public, review_public, review_growth, google, reviews, analytics, billing, gbp):
    app.include_router(module.router, prefix=API)
