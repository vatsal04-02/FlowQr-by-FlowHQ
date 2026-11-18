"""Consent for automation: express, specific, per location, per action type, revocable, and recorded (Local SEO Milestone 2, decision D2).

Google's Business Profile API policy: "you must not automate or trigger review replies, Q&As, listing creations, listing edits, or other actions without the user's prior
specific and express consent." Support policy adds that "verbal consent isn't sufficient" for responding to reviews on a merchant's behalf.

What this module guarantees (each is a test in tests/test_consent.py):
  * default is NO consent. A new business, a new location and a new action type have none; an existing business inherits none;
  * a grant covers ONE location and ONE action type. A grant at branch A never authorises branch B, and a grant for hours never authorises descriptions;
  * only an OWNER can grant, and only for a scope this module lists: Level 1 and 2 profile changes that FlowQr can actually write, and the template reply rule.
    Level 3 changes, and public content (posts, photos, AI-drafted replies), are not grantable here: a person approves each one, every time;
  * the grant stores the exact wording that was shown and its version; a grant made against old wording is refused, so nobody agrees to text they did not see;
  * revoking takes effect at once: every queued autonomous action of that location and type returns to "waiting for a person", and the executor re-checks consent at the
    moment it would write, so a revoked grant can never be used by a job that was already queued;
  * the record is append-only in the database (see migration 0038): a grant can be revoked, never edited or deleted, and a later grant is a new row.
This module does not decide what an action is allowed to change: that is autonomy_policy. Consent is necessary, never sufficient."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConsentGrant, GoogleLocation
from app.models.base import utcnow
from app.services.agent import autonomy_policy as pol
from app.services.audit import audit

WORDING_VERSION = "2026-11-17.1"
REPLY_SCOPE = "reply_template"


class ConsentError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def scopes() -> dict[str, dict]:
    """Every scope an owner can consent to, with the plain-language wording. Derived from the policy table, so a new action type cannot become grantable by accident:
    it must be Level 1 or 2, writable by the integration, and not public content."""
    out: dict[str, dict] = {}
    for s in pol.SPECS.values():
        if s.internal or s.person_only or s.level >= 3 or not s.writable:
            continue
        out[s.key] = {"scope": s.key, "label": s.label, "level": s.level, "kind": "profile_change",
                      "wording": (f"Let FlowQR make this kind of change to this Google Business Profile by itself, without asking you each time: {s.label.lower()}. "
                                  "FlowQR only uses facts you have verified in your Business Brain or business record, reads your profile back from Google to check the result, "
                                  "and records every change in your Activity history. It never changes anything else, and it never changes your business name, address, "
                                  "primary category, service area or primary contact details. You can withdraw this at any time and it stops straight away.")}
    out[REPLY_SCOPE] = {"scope": REPLY_SCOPE, "label": "Automatic thank-you replies to new 4 and 5 star reviews", "level": 2, "kind": "review_reply",
                        "wording": ("Let FlowQR reply by itself to NEW reviews of 4 or 5 stars at this location, using only the reply templates you approved (no AI writes them). "
                                    "It never replies to older reviews, to reviews that mention a problem or anything sensitive, or to a review someone has already replied to. "
                                    "Every reply is checked on Google afterwards and listed in your Activity history. You can withdraw this at any time and it stops straight away.")}
    return out


def wording_for(scope: str, location_title: str | None) -> str:
    sc = scopes().get(scope)
    if sc is None:
        raise ConsentError("That is not something FlowQR can ask your consent for. Changes to your name, address, primary category, service area or primary contact, "
                           "and publishing posts or photos, always need your approval one by one.", 422)
    return f"{sc['wording']} Location: {location_title or 'this location'}."


def active(db: Session, tenant_id: uuid.UUID, google_location_id: uuid.UUID, scope: str) -> ConsentGrant | None:
    return db.scalar(select(ConsentGrant).where(ConsentGrant.tenant_id == tenant_id, ConsentGrant.google_location_id == google_location_id,
                                                ConsentGrant.scope == scope, ConsentGrant.revoked_at.is_(None)).limit(1))


def has_active(db: Session, tenant_id: uuid.UUID, google_location_id: uuid.UUID, scope: str) -> bool:
    return active(db, tenant_id, google_location_id, scope) is not None


def grant(db: Session, *, tenant_id: uuid.UUID, gloc: GoogleLocation, scope: str, user_id: uuid.UUID, wording_version: str, source: str = "owner_ui",
          ip: str | None = None, now: datetime | None = None) -> tuple[ConsentGrant, bool]:
    """Record the owner's consent. Idempotent: an active grant for the same location and scope is returned unchanged ("created" False). Caller commits."""
    now = now or utcnow()
    if gloc.tenant_id != tenant_id:
        raise ConsentError("That location does not belong to this business.", 404)
    if wording_version != WORDING_VERSION:
        raise ConsentError("The wording changed while you were reading it. Reload the page and read it again before agreeing.", 409)
    text = wording_for(scope, gloc.title)  # also refuses an unknown or ungrantable scope
    existing = active(db, tenant_id, gloc.id, scope)
    if existing is not None:
        return existing, False
    row = ConsentGrant(tenant_id=tenant_id, google_location_id=gloc.id, scope=scope, wording_version=WORDING_VERSION, wording_text=text, granted_by=user_id,
                       granted_at=now, source=source[:16])
    db.add(row)
    db.flush()
    audit(db, action="consent.granted", tenant_id=tenant_id, user_id=user_id, entity_type="consent_grant", entity_id=row.id, ip=ip,
          meta={"scope": scope, "google_location_id": str(gloc.id), "wording_version": WORDING_VERSION})
    return row, True


def revoke(db: Session, row: ConsentGrant, *, user_id: uuid.UUID | None, reason: str | None = None, ip: str | None = None, now: datetime | None = None) -> dict:
    """Withdraw one grant, and immediately return everything queued under it to "waiting for a person". Idempotent. Caller commits."""
    from app.services.agent import executor

    now = now or utcnow()
    if row.revoked_at is not None:
        return {"revoked": False, "withdrawn": 0}
    row.revoked_at, row.revoked_by, row.revoked_reason = now, user_id, (reason or "").strip()[:300] or None
    db.flush()
    n = 0
    if row.scope != REPLY_SCOPE:
        n = executor.withdraw_autonomous(db, row.tenant_id, reason="the owner withdrew consent for this location and action type", user_id=user_id, now=now,
                                         google_location_id=row.google_location_id, effective_type=row.scope)
    audit(db, action="consent.revoked", tenant_id=row.tenant_id, user_id=user_id, entity_type="consent_grant", entity_id=row.id, ip=ip,
          meta={"scope": row.scope, "google_location_id": str(row.google_location_id), "withdrawn_actions": n, "reason": row.revoked_reason})
    return {"revoked": True, "withdrawn": n}


def revoke_all(db: Session, tenant_id: uuid.UUID, *, user_id: uuid.UUID | None, google_location_id: uuid.UUID | None = None, reason: str | None = None,
               ip: str | None = None, now: datetime | None = None) -> dict:
    q = select(ConsentGrant).where(ConsentGrant.tenant_id == tenant_id, ConsentGrant.revoked_at.is_(None))
    if google_location_id is not None:
        q = q.where(ConsentGrant.google_location_id == google_location_id)
    revoked = withdrawn = 0
    for row in list(db.scalars(q)):
        r = revoke(db, row, user_id=user_id, reason=reason, ip=ip, now=now)
        revoked += r["revoked"]
        withdrawn += r["withdrawn"]
    return {"revoked": revoked, "withdrawn": withdrawn}


def out(row: ConsentGrant) -> dict:
    return {"id": str(row.id), "google_location_id": str(row.google_location_id), "scope": row.scope, "wording_version": row.wording_version, "wording_text": row.wording_text,
            "granted_by": str(row.granted_by) if row.granted_by else None, "granted_at": row.granted_at.isoformat(), "source": row.source,
            "active": row.revoked_at is None, "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            "revoked_by": str(row.revoked_by) if row.revoked_by else None, "revoked_reason": row.revoked_reason}
