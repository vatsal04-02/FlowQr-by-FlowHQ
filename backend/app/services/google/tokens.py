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


def get_access_token(db: Session, conn: GoogleConnection, provider=None) -> str:
    """Return a valid access token, refreshing if needed. Marks the connection revoked on invalid_grant."""
    if conn.status in (GoogleConnectionStatus.disconnected, GoogleConnectionStatus.revoked):
        raise g.GoogleAuthRevoked("Connection is not active")
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


def mark_revoked(db: Session, conn: GoogleConnection, reason: str) -> None:
    conn.status = GoogleConnectionStatus.revoked
    conn.last_error = reason
    conn.access_token_encrypted = None
    conn.access_token_expires_at = None
    db.commit()
