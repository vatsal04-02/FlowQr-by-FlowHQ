"""Registration gate: who may create a NEW account or a NEW business.

OWNER DECISION 2026-11-15: production must not take public sign-ups yet. Three modes (settings.effective_registration_mode):
  closed     nobody registers (platform-admin addresses excepted, so the first administrator can exist)
  allowlist  only addresses on the allowlist register: REGISTRATION_ALLOWLIST (environment), the database list an administrator manages (Admin API or `python -m app.cli registration`),
             and the platform-admin addresses. THE DEFAULT whenever APP_ENV is staging or production
  open       anyone may register. In production only if REGISTRATION_MODE=open is set deliberately. The default for development and tests

This module is the ONLY place the rule lives, and it is called from the three places an account or business can be created: password sign-up (api/v1/auth.py), Google sign-up
(api/v1/auth_google.py) and business creation (api/v1/tenants.py). Nothing here depends on what the frontend shows. Existing accounts are never affected: signing in is not registration.

Properties (each is a test in tests/test_registration_gate.py):
  * emails are normalised (Unicode NFKC, trimmed, lower case) before any comparison; look-alike characters and `+tag` aliases do NOT match
  * a refused attempt gets the SAME answer whether the mode is closed or the address is merely not listed, and the check runs BEFORE any "account already exists" answer, so the response
    never says whether an address is listed or registered. Repeated refusals from one address are rate-limited. (An address that IS permitted creates an account, which is what registration
    is; that account is unverified and cannot create a business, connect Google or touch billing until its mailbox is verified.)
  * every attempt is audited (`registration.allowed` / `registration.rejected`); a rejected address is recorded only as a short hash and its domain, never in full
  * administrator rights still need a VERIFIED address (api/v1/auth.py); being on a list grants none
  * outside `open` mode, creating a business needs a listed AND verified address (a stranger who registers an approved address first cannot spend the trial on it)"""
from __future__ import annotations

import hashlib
import logging
import unicodedata
from datetime import datetime

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import set_rls_context
from app.core.rate_limit import client_ip, hit
from app.models import RegistrationAllowlist
from app.models.base import utcnow
from app.services.audit import audit

log = logging.getLogger("flowqr.registration")
CODE = "registration_restricted"
MESSAGE = "FlowQR is open to approved businesses only at the moment. If you expected access, contact FlowQR support."
UNVERIFIED_CODE = "email_not_verified"
UNVERIFIED_MESSAGE = "Verify your email address to set up your business. We sent you a link when you registered; you can ask for another from this page."
MAX_REFUSALS = (5, 900)  # per address, per 15 minutes


def normalize_email(raw: object) -> str | None:
    """The one canonical spelling of an address, or None if it is not a plausible single address. NFKC folds full-width and compatibility characters; it does not fold look-alikes from
    other scripts (those stay different, which is the safe direction) and it does not strip `+tag`."""
    if not isinstance(raw, str):
        return None
    s = unicodedata.normalize("NFKC", raw).strip().lower()
    if not s or len(s) > 320 or s.count("@") != 1 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in s):
        return None
    local, _, domain = s.partition("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith(".") or ".." in domain:
        return None
    return s


def mode() -> str:
    return settings.effective_registration_mode


def _fingerprint(email: str | None) -> tuple[str, str]:
    n = normalize_email(email)
    return (hashlib.sha256(n.encode()).hexdigest()[:16] if n else "invalid", n.partition("@")[2] if n else "")


def is_listed(db: Session, email: str | None) -> bool:
    n = normalize_email(email)
    if not n:
        return False
    if n in settings.registration_allowlist_set or n in {normalize_email(e) for e in settings.platform_admin_email_set}:
        return True
    return db.scalar(select(RegistrationAllowlist.id).where(RegistrationAllowlist.email == n)) is not None


def permits(db: Session, email: str | None) -> bool:
    m = mode()
    n = normalize_email(email)
    if m == "open":
        return True
    if not n:
        return False
    if n in {normalize_email(e) for e in settings.platform_admin_email_set}:
        return True  # an administrator address can always exist (otherwise a closed production could never get its first administrator)
    return m == "allowlist" and is_listed(db, n)


def _refuse(db: Session, request: Request, email: str | None, via: str):
    h, domain = _fingerprint(email)
    set_rls_context(db, bypass=True)
    audit(db, action="registration.rejected", entity_type="registration", meta={"via": via, "mode": mode(), "email_sha256": h, "domain": domain}, ip=client_ip(request))
    db.commit()  # the refusal must be on record even though the request ends in an error
    if not hit(f"reg-refused:{client_ip(request)}", *MAX_REFUSALS):
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
    raise HTTPException(status_code=403, detail={"code": CODE, "message": MESSAGE})


def gate_new_account(db: Session, request: Request, email: str | None, via: str) -> str | None:
    """Call BEFORE creating a user (and before any answer that would reveal whether the address already has an account). Raises the one standard refusal; returns the normalised
    address when the attempt is permitted. `via` is "password" or "google"."""
    if not permits(db, email):
        _refuse(db, request, email, via)
    n = normalize_email(email)
    h, domain = _fingerprint(email)
    set_rls_context(db, bypass=True)
    audit(db, action="registration.allowed", entity_type="registration", meta={"via": via, "mode": mode(), "email_sha256": h, "domain": domain}, ip=client_ip(request))
    if n:
        row = db.scalar(select(RegistrationAllowlist).where(RegistrationAllowlist.email == n))
        if row is not None and row.used_at is None:
            row.used_at = utcnow()
    return n


def assert_can_create_business(db: Session, request: Request, user) -> None:
    """Call before creating a business. `open`: as before. Otherwise the signed-in user must be a platform admin, or be listed (never in `closed`) AND have a verified address."""
    if mode() == "open" or user.is_platform_admin:
        return
    if mode() == "closed" or not permits(db, user.email):
        _refuse(db, request, user.email, "business")
    if not user.email_verified_at:
        raise HTTPException(status_code=403, detail={"code": UNVERIFIED_CODE, "message": UNVERIFIED_MESSAGE})


# ---------------------------------------------------------------------------------------------------- the database list (Admin API and CLI)
def add(db: Session, email: str, *, note: str | None = None, user_id=None) -> RegistrationAllowlist:
    n = normalize_email(email)
    if not n:
        raise ValueError("That is not a valid email address.")
    row = db.scalar(select(RegistrationAllowlist).where(RegistrationAllowlist.email == n))
    if row is not None:
        return row
    row = RegistrationAllowlist(email=n, note=(note or "").strip()[:300] or None, added_by=user_id, created_at=utcnow())
    db.add(row)
    db.flush()
    return row


def remove(db: Session, email: str) -> bool:
    n = normalize_email(email)
    row = db.scalar(select(RegistrationAllowlist).where(RegistrationAllowlist.email == n)) if n else None
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def entries(db: Session) -> list[dict]:
    rows = db.scalars(select(RegistrationAllowlist).order_by(RegistrationAllowlist.created_at.desc())).all()
    return [{"id": str(r.id), "email": r.email, "note": r.note, "added_by": str(r.added_by) if r.added_by else None, "created_at": r.created_at, "used_at": r.used_at} for r in rows]


def summary(db: Session) -> dict:
    return {"mode": mode(), "explicit": bool((settings.registration_mode or "").strip()), "env_allowlist_count": len(settings.registration_allowlist_set),
            "admin_addresses_count": len(settings.platform_admin_email_set), "entries": entries(db)}
