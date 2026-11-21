"""Photo library and scheduler (PRD: Photo Manager & Scheduler).

awaiting_approval -> scheduled -> publishing -> published | failed (retried when retrying can help) ; canceled.

* Upload validates against Google's published rules: JPG or PNG, 10 KB to 5 MB, at least 250 px on each side (720 px recommended).
  COVER and PROFILE are exempt from Google's minimum-size rule but still need to be real images.
* Nothing goes to Google without an owner or admin approving the photo and its category.
* A Celery job sends due photos with Google's documented byte upload (media:startUpload -> upload -> media.create with dataRef),
  so FlowQR never needs to make the file public.
* `published` = Google returned a MediaItem. Google may still be processing it, or hold it until the profile is verified; the job keeps
  checking for Google's own `googleUrl`, and the UI says "Google is processing" until then. An upload into FlowQR alone is never shown as
  published.
"""
from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import hit
from app.models import GoogleConnection, GoogleConnectionStatus, GoogleLocation, ScheduledMedia
from app.models.base import utcnow
from app.services import google as g
from app.services.agent.posts import describe_failure
from app.services.google.tokens import get_access_token, note_not_approved

MIN_BYTES, MAX_BYTES = 10 * 1024, 5 * 1024 * 1024
MIN_EDGE, RECOMMENDED_EDGE = 250, 720
MAX_PIXELS = 50_000_000  # 50 megapixels: far above any phone photo, far below a decompression bomb
MAX_ATTEMPTS = 4
FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png"}

# Google MediaItem categories (v4 reference). LOGO is a deprecated alias of PROFILE and is not offered.
CATEGORIES = {
    "COVER": "Cover photo", "PROFILE": "Logo / profile photo", "EXTERIOR": "Exterior", "INTERIOR": "Interior", "PRODUCT": "Products",
    "AT_WORK": "At work / services", "TEAMS": "Team", "FOOD_AND_DRINK": "Food & drink", "MENU": "Menu", "COMMON_AREA": "Common area",
    "ROOMS": "Rooms", "ADDITIONAL": "Additional",
}
# What most local businesses should have; food and lodging categories are only suggested where they apply.
CORE = ["COVER", "PROFILE", "EXTERIOR", "INTERIOR", "TEAMS", "AT_WORK", "PRODUCT"]
FOOD = ("restaurant", "cafe", "café", "bakery", "food", "bar", "dhaba", "sweet")
LODGING = ("hotel", "guest house", "lodge", "hostel", "resort", "homestay")

TRANSITIONS = {
    "awaiting_approval": {"scheduled", "canceled"},
    "scheduled": {"publishing", "awaiting_approval", "canceled"},
    "publishing": {"published", "failed", "scheduled"},
    "failed": {"scheduled", "canceled"},
    "published": set(),
    "canceled": set(),
}


class MediaError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def move(m: ScheduledMedia, to: str) -> None:
    if to not in TRANSITIONS.get(m.status, set()):
        raise MediaError(f"A photo that is {m.status.replace('_', ' ')} cannot become {to.replace('_', ' ')}.")
    m.status = to


def inspect(data: bytes, category: str) -> dict:
    """Validate a photo the way Google will. Returns {content_type, width, height, warnings[]} or raises MediaError(422)."""
    from PIL import Image, UnidentifiedImageError

    if category not in CATEGORIES:
        raise MediaError("Choose a photo category.", 422)
    if len(data) < MIN_BYTES:
        raise MediaError("This file is smaller than 10 KB. Google needs a real photo between 10 KB and 5 MB.", 422)
    if len(data) > MAX_BYTES:
        raise MediaError(f"This file is {len(data) / 1048576:.1f} MB. Google accepts photos up to 5 MB; export a smaller JPG.", 422)
    try:
        img = Image.open(io.BytesIO(data))  # reads the header only
        fmt, (w, h) = img.format, img.size
        if w * h > MAX_PIXELS:  # checked BEFORE any pixel is decoded: a tiny file can declare a gigantic canvas
            raise MediaError(f"This image is {w}×{h} px, which is too many pixels. Export a normal-sized JPG (under 50 megapixels).", 422)
        img.verify()  # structural check (truncated or fake files fail here)
        img = Image.open(io.BytesIO(data))
    except MediaError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):  # Pillow itself refuses absurd canvases at open()
        raise MediaError("This image has too many pixels (over 50 megapixels). Export a normal-sized JPG.", 422)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise MediaError("This isn't a readable image. Google accepts JPG or PNG photos.", 422)
    if fmt not in FORMATS:
        raise MediaError(f"{fmt or 'This'} files aren't accepted. Google accepts JPG or PNG.", 422)
    if getattr(img, "is_animated", False):
        raise MediaError("Animated images aren't accepted. Use a still JPG or PNG.", 422)
    warnings = []
    if category not in ("COVER", "PROFILE") and min(w, h) < MIN_EDGE:
        raise MediaError(f"This photo is {w}×{h} px. Google needs at least 250 px on each side.", 422)
    if min(w, h) < RECOMMENDED_EDGE:
        warnings.append(f"{w}×{h} px is below Google's recommended 720×720 px; it may look blurry.")
    if category == "PROFILE" and abs(w - h) > max(w, h) * 0.2:
        warnings.append("Logos look best square; Google crops profile photos to a circle.")
    if category == "COVER" and w < h:
        warnings.append("Cover photos are shown wide; a landscape photo works best.")
    return {"content_type": FORMATS[fmt], "width": w, "height": h, "warnings": warnings}


def create(db: Session, *, tenant_id: uuid.UUID, gloc: GoogleLocation, data: bytes, category: str, description: str | None,
           file_name: str | None, user_id: uuid.UUID) -> tuple[ScheduledMedia, list[str]]:
    info = inspect(data, category)
    digest = hashlib.sha256(data).hexdigest()
    dup = db.scalar(select(ScheduledMedia.id).where(ScheduledMedia.tenant_id == tenant_id, ScheduledMedia.google_location_id == gloc.id,
                                                    ScheduledMedia.sha256 == digest, ScheduledMedia.status != "canceled"))
    if dup:
        raise MediaError("This exact photo is already in the library for this location.", 409)
    m = ScheduledMedia(tenant_id=tenant_id, google_location_id=gloc.id, category=category, description=(description or "").strip()[:300] or None,
                       file_name=(file_name or "")[:200] or None, content_type=info["content_type"], size_bytes=len(data), width=info["width"],
                       height=info["height"], sha256=digest, data=data, status="awaiting_approval", created_by=user_id)
    db.add(m)
    db.flush()
    return m, info["warnings"]


def approve(m: ScheduledMedia, *, user_id: uuid.UUID, when: datetime | None) -> None:
    if m.status != "awaiting_approval":
        raise MediaError("Only a photo that is waiting for approval can be approved.")
    now = utcnow()
    if when is not None and when <= now + timedelta(seconds=30):
        when = None
    move(m, "scheduled")
    m.approved_by, m.approved_at = user_id, now
    m.scheduled_for = when or now
    m.next_attempt_at, m.failure_reason, m.attempts = None, None, 0


def retry(m: ScheduledMedia) -> None:
    if m.status != "failed":
        raise MediaError("Only a failed photo can be retried.")
    move(m, "scheduled")
    m.scheduled_for = m.next_attempt_at = utcnow()
    m.failure_reason, m.attempts = None, 0


def suggestions(category: str | None, on_google: list[str], in_flowqr: list[str]) -> list[dict]:
    """Photo categories this business should add, in order, with whether one is already on its way."""
    want = list(CORE)
    c = (category or "").lower()
    if any(k in c for k in FOOD):
        want += ["FOOD_AND_DRINK", "MENU"]
    if any(k in c for k in LODGING):
        want += ["ROOMS", "COMMON_AREA"]
    have = set(on_google)
    pending = set(in_flowqr)
    return [{"category": k, "label": CATEGORIES[k], "on_google": k in have, "pending": k in pending and k not in have} for k in want]


def publish(db: Session, m: ScheduledMedia, *, provider=None, now: datetime | None = None) -> str:
    """Send one due photo to Google. published | retry | failed | skipped. The caller holds the row lock and commits."""
    now = now or utcnow()
    gloc = db.get(GoogleLocation, m.google_location_id)
    conn = db.get(GoogleConnection, gloc.connection_id) if gloc else None
    if gloc is None or not gloc.selected or conn is None or conn.status != GoogleConnectionStatus.active:
        m.status, m.failure_reason = "failed", "This location is no longer connected to Google. Reconnect it, then retry."
        return "failed"
    if not hit(f"gbp-edit:{gloc.id}", 10, 60):  # Google allows 10 edits per minute per location
        m.next_attempt_at = now + timedelta(seconds=65)
        return "skipped"
    move(m, "publishing")
    m.attempts += 1
    try:
        provider = provider or g.get_google_provider()
        token = get_access_token(db, conn, provider, gloc=gloc)
        created = provider.upload_media_bytes(token, gloc.google_account_name, gloc.google_location_name, m.data, m.content_type, m.category, m.description)
    except Exception as exc:  # noqa: BLE001 - every failure is recorded
        reason, may_retry = describe_failure(exc)
        reason = reason.replace("this post", "this photo").replace("nothing was published", "nothing was uploaded to Google")
        if isinstance(exc, g.GoogleApiNotApproved):
            note_not_approved(conn, exc)
        if may_retry and m.attempts < MAX_ATTEMPTS:
            m.status, m.failure_reason = "scheduled", reason
            m.next_attempt_at = now + timedelta(minutes=5 * 2 ** (m.attempts - 1))
            return "retry"
        m.status, m.failure_reason, m.next_attempt_at = "failed", reason, None
        return "failed"
    name = (created or {}).get("name")
    if not name:  # a 2xx without a MediaItem name is not something we can call published
        m.status, m.failure_reason = "failed", "Google answered without creating the photo. Nothing is shown as published; retry."
        return "failed"
    m.status, m.published_at, m.google_media_name = "published", utcnow(), name
    m.google_url, m.google_checked_at = created.get("google_url"), utcnow()
    m.failure_reason, m.next_attempt_at = None, None
    return "published"


def due(db: Session, limit: int = 5, now: datetime | None = None) -> list[ScheduledMedia]:
    now = now or utcnow()
    q = (select(ScheduledMedia).where(ScheduledMedia.status == "scheduled", ScheduledMedia.scheduled_for <= now,
                                      (ScheduledMedia.next_attempt_at.is_(None)) | (ScheduledMedia.next_attempt_at <= now))
         .order_by(ScheduledMedia.scheduled_for).limit(limit).with_for_update(skip_locked=True))
    return list(db.scalars(q))


def check_processing(db: Session, m: ScheduledMedia, *, provider=None) -> bool:
    """For a published photo Google hasn't served yet: ask Google for the MediaItem again. True once Google returns its own URL."""
    gloc = db.get(GoogleLocation, m.google_location_id)
    conn = db.get(GoogleConnection, gloc.connection_id) if gloc else None
    if not m.google_media_name or conn is None or conn.status != GoogleConnectionStatus.active:
        return False
    provider = provider or g.get_google_provider()
    item = provider.get_media(get_access_token(db, conn, provider, gloc=gloc), m.google_media_name)
    m.google_checked_at = utcnow()
    if item.get("google_url"):
        m.google_url = item["google_url"]
        return True
    return False


def out(m: ScheduledMedia) -> dict:
    stage = {"awaiting_approval": "Waiting for approval", "scheduled": "Scheduled", "publishing": "Sending to Google", "failed": "Didn't reach Google",
             "canceled": "Cancelled"}.get(m.status)
    if m.status == "published":
        stage = "Live on Google" if m.google_url else "Google is processing it"
    return {"id": str(m.id), "google_location_id": str(m.google_location_id), "category": m.category, "category_label": CATEGORIES.get(m.category, m.category),
            "description": m.description, "file_name": m.file_name, "content_type": m.content_type, "size_bytes": m.size_bytes, "width": m.width, "height": m.height,
            "status": m.status, "stage": stage, "scheduled_for": m.scheduled_for, "next_attempt_at": m.next_attempt_at, "attempts": m.attempts,
            "failure_reason": m.failure_reason, "google_media_name": m.google_media_name, "google_url": m.google_url, "google_checked_at": m.google_checked_at,
            "published_at": m.published_at, "approved_at": m.approved_at, "created_at": m.created_at}
