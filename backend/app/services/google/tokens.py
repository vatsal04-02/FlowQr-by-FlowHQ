"""Token lifecycle. Refresh tokens are encrypted at rest and never leave the backend."""
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.security import get_cipher
from app.models import GoogleConnection, GoogleConnectionStatus
from app.models.base import utcnow
from app.services import google as g


def store_tokens(conn: GoogleConnection, *, refresh_token: str | None, access_token: str, expires_in: int) -> None:
    cipher = get_cipher()
    if refresh_token:
        conn.refresh_token_encrypted = cipher.encrypt(refresh_token)
    conn.access_token_encrypted = cipher.encrypt(access_token)
    conn.access_token_expires_at = utcnow() + timedelta(seconds=expires_in)


def get_access_token(db: Session, conn: GoogleConnection, provider=None, gloc=None, action: str | None = None) -> str:
    """Return a valid access token, refreshing if needed. Marks the connection revoked on invalid_grant.

    `gloc` is the Google location about to be used. An agency-managed connection requires the explicit tenant-to-location mapping for it (agency.resolve_agency_access); pass it wherever the call is for one location.
    `action` names the kind of change about to be made (agency.ACTION_CATEGORIES: reply_to_reviews, publish_posts, edit_profile); an agency connection refuses one the business did not agree to. Reads need none."""
    if conn.status in (GoogleConnectionStatus.disconnected, GoogleConnectionStatus.revoked):
        raise g.GoogleAuthRevoked("Connection is not active")
    if conn.auth_mode == "agency_account":  # the client invited a FlowQR agency account as manager (services/google/agency.py); the client's own token is not used
        from app.services.google import agency

        return agency.token_for_connection(db, conn, provider, gloc, action)
    cipher = get_cipher()
    if conn.access_token_encrypted and conn.access_token_expires_at and conn.access_token_expires_at > utcnow() + timedelta(seconds=60):
        return cipher.decrypt(conn.access_token_encrypted)
    if not conn.refresh_token_encrypted:
        mark_revoked(db, conn, "No refresh token stored")
        raise g.GoogleAuthRevoked("No refresh token")
    provider = provider or g.get_google_provider()
    try:
        ts = provider.refresh_access_token(cipher.decrypt(conn.refresh_token_encrypted))
    except g.GoogleAuthRevoked:
        mark_revoked(db, conn, "Google access was revoked. Please reconnect.")
        raise
    store_tokens(conn, refresh_token=ts.refresh_token, access_token=ts.access_token, expires_in=ts.expires_in)
    db.flush()
    return ts.access_token


AWAITING_APPROVAL = ("Google has not yet approved FlowQR for Business Profile API access (quota 0). Your Google login worked, but reviews, "
                     "posts and insights stay unavailable until approval.")
PROBABLY_AWAITING = ("Google refused the very first Business Profile request with a quota error. That is what an unapproved project "
                     "(quota 0) looks like, so this is most likely awaiting Google's approval. Your Google login itself worked.")
API_DISABLED = ("A required Google Business Profile API is not enabled on FlowQR's Google Cloud project{service}. Your Google login "
                "worked, but nothing can be read or changed until FlowQR support enables it.")


def note_api_access(conn: GoogleConnection, state: str) -> None:
    """Record what the last real Google response told us about project access (caller commits).
    States: unknown | approved | awaiting_approval | api_disabled."""
    if conn.api_access != state:
        conn.api_access = state
    conn.api_access_checked_at = utcnow()


def note_not_approved(conn: GoogleConnection, exc) -> str:
    """Record a GoogleApiNotApproved (or a first-contact quota error) and return the message to show. Caller commits."""
    why = getattr(exc, "why", None)
    if why == "service_disabled":
        note_api_access(conn, "api_disabled")
        svc = getattr(exc, "service", None)
        return API_DISABLED.format(service=f" ({svc})" if svc else "")
    note_api_access(conn, "awaiting_approval")
    return AWAITING_APPROVAL if why == "quota_zero" else PROBABLY_AWAITING


def mark_revoked(db: Session, conn: GoogleConnection, reason: str) -> None:
    conn.status = GoogleConnectionStatus.revoked
    conn.last_error = reason
    conn.access_token_encrypted = None
    conn.access_token_expires_at = None
    db.commit()
