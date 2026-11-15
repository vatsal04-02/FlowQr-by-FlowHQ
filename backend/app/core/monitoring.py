"""Error reporting. Sentry (or a compatible service) when SENTRY_DSN is set; otherwise a no-op. One init for API, worker and beat.

Privacy: send_default_pii is off, request bodies, cookies and headers are dropped before sending, and local variables are not
attached. Customer review text and tokens live in request bodies and local variables: neither is sent."""
from __future__ import annotations

import logging

from app.core.config import settings

log = logging.getLogger("flowqr.monitoring")
_on = False


def enabled() -> bool:
    return _on


def scrub(event: dict, hint: dict | None = None) -> dict | None:
    req = event.get("request") or {}
    for k in ("data", "cookies", "headers", "query_string"):
        req.pop(k, None)
    if req:
        event["request"] = req
    event.pop("user", None)
    for ex in (event.get("exception") or {}).get("values", []):
        for fr in (ex.get("stacktrace") or {}).get("frames", []):
            fr.pop("vars", None)  # local variables can hold review text or tokens
    return event


def init(component: str) -> bool:
    """component: api | worker | beat. Returns True when reporting is active."""
    global _on
    if _on or not settings.sentry_dsn:
        return _on
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.sentry_environment or settings.app_env, send_default_pii=False, include_local_variables=False,
                        traces_sample_rate=settings.sentry_traces_sample_rate, before_send=scrub, max_breadcrumbs=20)
        sentry_sdk.set_tag("component", component)
        _on = True
    except Exception as exc:  # a broken monitoring setup must never stop the app
        log.warning("Error reporting could not start (%s)", type(exc).__name__)
    return _on


def capture_message(msg: str, level: str = "error", **tags) -> None:
    if not _on:
        return
    import sentry_sdk

    with sentry_sdk.new_scope() as scope:
        for k, v in tags.items():
            scope.set_tag(k, str(v)[:60])
        sentry_sdk.capture_message(msg[:300], level=level)
