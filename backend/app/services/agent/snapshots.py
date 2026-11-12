"""What Google last told us about each location. Health and the daily plan are computed from this, never from guesses."""
import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GbpSnapshot, GoogleConnection, GoogleConnectionStatus, GoogleLocation
from app.models.base import utcnow
from app.services import google as g
from app.services.google.provider import PERFORMANCE_METRICS
from app.services.google.tokens import get_access_token, note_not_approved

log = logging.getLogger("flowqr.snapshots")
ACTION_METRICS = ["CALL_CLICKS", "WEBSITE_CLICKS", "BUSINESS_DIRECTION_REQUESTS", "BUSINESS_BOOKINGS", "MESSAGING_CLICKS"]
DESCRIPTION_MIN = 100  # characters; Google recommends a full description, short ones add little


def profile_completeness(info: dict | None) -> dict:
    """{percent, missing[], fields[]} for one location's profile as Google reports it."""
    info = info or {}
    checks = [
        ("description", "Description", 30, len((info.get("description") or "").strip()) >= DESCRIPTION_MIN, f"at least {DESCRIPTION_MIN} characters"),
        ("hours", "Opening hours", 25, bool(info.get("hours")), "weekly hours"),
        ("phone", "Phone number", 15, bool((info.get("phone") or "").strip()), "a phone number"),
        ("website", "Website", 15, bool((info.get("website") or "").strip()), "a website link"),
        ("category", "Main category", 15, bool(info.get("primary_category")), "a main category"),
    ]
    got = sum(w for _, _, w, ok, _ in checks if ok)
    return {"percent": got, "missing": [{"key": k, "label": label, "needs": need} for k, label, _, ok, need in checks if not ok],
            "fields": [{"key": k, "label": label, "weight": w, "ok": ok} for k, label, w, ok, _ in checks]}


def _sum_window(series: dict, start: date, end: date) -> int:
    total = 0
    for metric in ACTION_METRICS:
        for pt in series.get(metric, []):
            if start.isoformat() <= pt["date"] <= end.isoformat():
                total += int(pt["value"])
    return total


def refresh(db: Session, gloc: GoogleLocation, *, provider=None, today: date | None = None) -> GbpSnapshot:
    """Fetch profile, posts, photos and 56 days of performance. Each part is independent: a failure in one is recorded and the rest
    are still stored. Nothing is invented when Google refuses."""
    snap = db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gloc.id))
    if snap is None:
        snap = GbpSnapshot(tenant_id=gloc.tenant_id, google_location_id=gloc.id)
        db.add(snap)
    conn = db.get(GoogleConnection, gloc.connection_id)
    errors: list[str] = []
    if conn is None or conn.status != GoogleConnectionStatus.active:
        snap.error = "Google is not connected for this location."
        return snap
    try:
        provider = provider or g.get_google_provider()
        token = get_access_token(db, conn, provider)
    except g.GoogleError as exc:
        snap.error = f"Could not authorise with Google: {exc}"[:400]
        return snap
    today = today or utcnow().date()
    end = today - timedelta(days=3)  # Google's data lags a few days
    cur_start, prev_end, prev_start = end - timedelta(days=27), end - timedelta(days=28), end - timedelta(days=55)

    def attempt(label, fn):
        try:
            return fn()
        except g.GoogleApiNotApproved as exc:
            note_not_approved(conn, exc)
            errors.append(f"{label}: {exc}")
        except g.GoogleError as exc:
            errors.append(f"{label}: {exc}")
        return None

    info = attempt("profile", lambda: provider.get_location_details(token, gloc.google_location_name))
    posts = attempt("posts", lambda: provider.list_posts(token, gloc.google_account_name, gloc.google_location_name))
    media = attempt("photos", lambda: provider.list_media(token, gloc.google_account_name, gloc.google_location_name))
    perf = attempt("performance", lambda: provider.fetch_performance(token, gloc.google_location_name, prev_start.isoformat(), end.isoformat(), PERFORMANCE_METRICS))
    if info is not None:
        snap.info = info
    if posts is not None:
        snap.posts = [{"name": p.get("name"), "summary": (p.get("summary") or "")[:200], "state": p.get("state"), "created_at": p.get("created_at")} for p in posts]
    if media is not None:
        snap.media = [{"name": m.get("name"), "category": m.get("category"), "created_at": m.get("created_at")} for m in media]
    if perf is not None:
        snap.performance = {"current": _sum_window(perf, cur_start, end), "previous": _sum_window(perf, prev_start, prev_end),
                            "window_days": 28, "from": cur_start.isoformat(), "to": end.isoformat(), "metrics": ACTION_METRICS}
    snap.error = "; ".join(errors)[:600] or None
    if len(errors) < 4:
        snap.fetched_at = utcnow()
    return snap
