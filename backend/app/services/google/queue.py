import logging
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import _get_redis
from app.models import GoogleLocation
from app.services.google.sync import sync_google_location

log = logging.getLogger("flowqr.queue")


def enqueue_sync(db: Session, gloc_ids: list[uuid.UUID]) -> str:
    """Queue background syncs via Celery; if no broker is reachable (e.g. tests, bare dev) run inline."""
    if settings.redis_url and _get_redis() is not None:
        try:
            from app.workers.tasks import sync_location

            for gid in gloc_ids:
                sync_location.delay(str(gid))
            return "queued"
        except Exception:  # broker hiccup -> fall back
            log.warning("Celery enqueue failed; running sync inline")
    for gid in gloc_ids:
        gloc = db.get(GoogleLocation, gid)
        if gloc:
            sync_google_location(db, gloc)
    return "ran_inline"
