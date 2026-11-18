"""The three account-lifecycle emails: a data export was downloaded, deleting an account was requested, an account was deleted.

Rules these functions keep (docs/PRIVACY_COMPLIANCE_AUDIT.md, C):
  * the existing mailer and plain-text style are reused; nothing here talks to an email provider itself;
  * an email NEVER contains exported data, a password, a token other than the one confirmation link that is meant to be clicked, or anything about another person;
  * what is recorded is the outcome only: an audit entry `email.sent` / `email.failed` with the kind of email, never its text, its link or its recipient's address;
  * duplicates caused by retries are prevented per email: the export notice is limited to one per person and business per ten minutes; the deletion request email is sent only when a
    new confirmation link is created (a repeated request while a link is still fresh creates and sends nothing); the completion email is sent once, after the deletion has committed.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import hit
from app.services.audit import audit
from app.services.mailer import send_email

log = logging.getLogger("flowqr.account_mail")


def _first(name: str | None) -> str:
    return (name or "").split()[0] if (name or "").strip() else "there"


def _contact() -> str:
    return f" If you need help, write to {settings.support_email}." if settings.support_email else ""


def _send(db: Session, kind: str, to: str, subject: str, body: str, *, tenant_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None) -> bool:
    ok = False
    try:
        ok = send_email(to, subject, body)
    except Exception as exc:  # noqa: BLE001 - an email problem must never undo a deletion or break an export
        log.warning("account email %s failed: %s", kind, type(exc).__name__)
    audit(db, action="email.sent" if ok else "email.failed", tenant_id=tenant_id, user_id=user_id, entity_type="email", meta={"kind": kind})
    return ok


def export_downloaded(db: Session, *, to: str, name: str | None, business: str, when: datetime, tenant_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """"A copy of your business data was downloaded." Limited to one per person and business per ten minutes, so a retried request does not send twice."""
    if not hit(f"mail:export:{tenant_id}:{user_id}", 1, 600):
        return False
    body = (f"Hi {_first(name)},\n\n"
            f"A copy of the data FlowQR holds for {business} was downloaded from your account on {when:%d %b %Y at %H:%M} UTC.\n\n"
            "For your security this email does not contain any of that data.\n\n"
            "If this was you, no action is needed. If it was not, change your password now (Settings, Account) and contact us." + _contact())
    return _send(db, "export_downloaded", to, "Your FlowQR data export was downloaded", body, tenant_id=tenant_id, user_id=user_id)


def deletion_requested(db: Session, *, to: str, name: str | None, link: str, user_id: uuid.UUID) -> bool:
    """"We received a request to delete your account": the only email that carries a link, which works once and expires."""
    body = (f"Hi {_first(name)},\n\n"
            "We received a request to delete your FlowQR account.\n\n"
            f"To confirm it, open this link within {settings.user_deletion_confirm_hours} hours. It works once:\n{link}\n\n"
            f"Nothing is deleted until you confirm. After you confirm, your account is deleted in {settings.account_deletion_grace_days} days, and you can still cancel in that time "
            "by signing in and choosing Settings, Account.\n\n"
            "What deleting your account does: it removes your sign-in, your name, email and phone number, and your access to every business you belong to. It does not delete any business. "
            "Google connections that you made for a business are disconnected.\n\n"
            "If you did not ask for this, ignore this email, and change your password." + _contact())
    return _send(db, "deletion_requested", to, "Confirm deleting your FlowQR account", body, user_id=user_id)


def deletion_completed(db: Session, *, to: str, name: str | None, user_id: uuid.UUID) -> bool:
    body = (f"Hi {_first(name)},\n\n"
            "Your FlowQR account has been deleted. Your sign-in, name, email address and phone number have been removed, and you no longer have access to any business on FlowQR.\n\n"
            "Business records that you took part in, such as approvals and the history of changes, stay with that business and no longer carry your name, email address or phone number.\n\n"
            "You are welcome to register again at any time." + _contact())
    return _send(db, "deletion_completed", to, "Your FlowQR account has been deleted", body, user_id=user_id)


def deletion_blocked(db: Session, *, to: str, name: str | None, user_id: uuid.UUID) -> bool:
    body = (f"Hi {_first(name)},\n\n"
            "We could not delete your FlowQR account as planned, because you have become the only owner of a business, and a business must always have an owner. "
            "Nothing was deleted and the request was cancelled.\n\n"
            "To go ahead, make someone else an owner of that business (Settings, Team) or delete the business, then request account deletion again." + _contact())
    return _send(db, "deletion_blocked", to, "Your FlowQR account was not deleted", body, user_id=user_id)


def business_deletion_requested(db: Session, *, to: str, name: str | None, business: str, scheduled_for: datetime, tenant_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """"We received your request to delete the business." Sent once, when the deletion is first scheduled (a repeat request returns before it gets here). No link: the owner already typed the
    business name and their password, and can cancel from Settings."""
    body = (f"Hi {_first(name)},\n\n"
            f"We received a request to delete {business} and all of its data from FlowQR. It is scheduled for {scheduled_for:%d %b %Y} UTC. Until then nothing is deleted, and an owner can cancel in "
            "Settings, Your data.\n\n"
            "If you did not ask for this, cancel it now and change your password." + _contact())
    return _send(db, "business_deletion_requested", to, "We received your request to delete your FlowQR business", body, tenant_id=tenant_id, user_id=user_id)


def business_deletion_completed(db: Session, *, to: str, name: str | None, business: str, user_id: uuid.UUID | None = None) -> bool:
    body = (f"Hi {_first(name)},\n\n"
            f"{business} and its data have been deleted from FlowQR, and our access to its Google connections has been revoked.\n\n"
            "Backups made before today age out on their normal schedule." + _contact())
    return _send(db, "business_deletion_completed", to, "Your FlowQR business has been deleted", body, user_id=user_id)
