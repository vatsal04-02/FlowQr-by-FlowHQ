import logging
import uuid

from app.core.db import system_session
from app.models import GoogleLocation
from app.services import google as g
from app.services.google.sync import due_locations, sync_google_location
from app.workers.celery_app import celery_app

log = logging.getLogger("flowqr.tasks")


@celery_app.task(name="flowqr.sync_location", bind=True, max_retries=3)
def sync_location(self, google_location_id: str):
    db = system_session()
    try:
        gloc = db.get(GoogleLocation, uuid.UUID(google_location_id))
        if not gloc:
            return {"status": "missing"}
        return sync_google_location(db, gloc)
    except g.GoogleNotConfigured:
        return {"status": "not_configured"}
    finally:
        db.close()


@celery_app.task(name="flowqr.sync_due_locations")
def sync_due_locations():
    db = system_session()
    try:
        ids = [str(x.id) for x in due_locations(db)]
    finally:
        db.close()
    for gid in ids:
        sync_location.delay(gid)
    return {"queued": len(ids)}
