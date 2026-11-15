"""Governed publishing: Google Posts, photos and review replies go through the SAME action record, policy, emergency stop, claim, read-back verification and
tamper-evident history as profile edits (executor.py). The existing publishers (agent/posts.publish, media.publish, reviews.publish_draft) are NOT replaced and
nothing here talks to Google except through them: this module decides whether they may run (`gate`), makes sure they run at most once at a time (`claim`), and then
checks with a separate read that Google really holds what was published (`verify`). That is why there is no second publishing mechanism that could bypass policy.

Policy for this kind of change (autonomy_policy.py): Posts, photos and replies are Level 2 and `person_only`: a named person approves each one, they cannot be
pre-authorised or run by policy, and autonomy being switched on changes nothing about them. The person's approval already exists on the row (approved_by,
approved_at); this module records it as the approval of the action and refuses to run anything without it.

What "executed" means: the publisher reported success AND a separate read of Google shows the item. If the read does not show it the ACTION is `failed`
(`read_back_mismatch`) and surfaces for a person to check; the owner-facing row keeps what Google itself answered (it may simply not be visible yet). A publisher result
of retry/failed/skipped keeps its existing meaning and schedule. Failures here do NOT count toward the automatic suspension of autonomy, because nothing in this
module is autonomous."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AgentAction, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Role, ScheduledMedia, ScheduledPost, ReplyDraft, ReplyStatus, Review, Tenant
from app.models.autonomy import LIVE_STATUSES
from app.models.base import utcnow
from app.services import entitlements as ent
from app.services import google as g
from app.services import usage as api_usage
from app.services.agent import autonomy_policy as pol
from app.services.agent import controls, history
from app.services.agent.executor import _add_approval  # one approval format for every kind of action
from app.services.google.tokens import get_access_token

log = logging.getLogger("flowqr.content_exec")
CONTENT_OUTCOME = "The item is shown on your Google Business Profile. FlowQR reads it back from Google to confirm; Google may take a little while to show it publicly."
READ_BACK_PAGES = 3


@dataclass
class Subject:
    """One thing to publish, described just enough for the engine to govern it. `send` is the EXISTING publisher; `verify` is a separate read."""
    kind: str  # post | photo | reply | direct_post | direct_post_edit | direct_post_delete | direct_photo | direct_photo_delete
    action_type: str  # a key of autonomy_policy.SPECS
    tenant_id: uuid.UUID
    google_location_id: uuid.UUID
    subject_id: uuid.UUID | None  # the scheduled row, or None for a direct action
    feature: str  # the plan feature it needs
    content: dict  # canonical content (hashed, shown in the history). Never secrets.
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    label: str
    send: Callable[[], tuple[str, dict]]  # -> ("done" | "retry" | "failed" | "skipped", payload)
    verify: Callable[[Any, str, dict], dict]  # (provider, token, payload) -> {"matched": bool, "detail": str, ...}; raises if Google cannot be read
    role: Role | None = None
    next_attempt_hint: Callable[[], datetime | None] | None = None
    extra: dict = field(default_factory=dict)


def _key(sub: Subject) -> str:
    return pol.fingerprint({"t": str(sub.tenant_id), "k": sub.kind, "s": str(sub.subject_id) if sub.subject_id else None, "c": pol.fingerprint(sub.content),
                            "a": sub.approved_at.isoformat() if sub.approved_at else None, "u": str(sub.approved_by) if sub.approved_by else None})


def _field_key(sub: Subject) -> str:
    return f"{sub.kind[:6]}:{sub.subject_id.hex if sub.subject_id else pol.fingerprint(sub.content)[:24]}"  # at most 39 characters


def _get_or_create(db: Session, sub: Subject, now: datetime) -> AgentAction:
    key = _key(sub)
    a = db.scalar(select(AgentAction).where(AgentAction.tenant_id == sub.tenant_id, AgentAction.idempotency_key == key, AgentAction.status.in_(LIVE_STATUSES)).limit(1))
    if a is not None:
        return a
    decision = pol.classify(sub.action_type)
    chash = pol.fingerprint(sub.content)
    a = AgentAction(
        tenant_id=sub.tenant_id, google_location_id=sub.google_location_id, subject_type=sub.kind[:16], subject_id=sub.subject_id, action_type=sub.action_type,
        field_key=_field_key(sub), trigger="person_approved" if sub.subject_id else "owner_action", problem=f"A person approved this {sub.label} to be sent to Google.",
        reason="A named person approved this exact content; FlowQR only sends what a person approved.", expected_outcome=CONTENT_OUTCOME, evidence={"approved_at": sub.approved_at.isoformat() if sub.approved_at else None},
        source={"kind": "person_approval", "refs": [sub.kind]}, current_value={"value": None}, proposed_value={"value": sub.content, "canonical": sub.content},
        base_fingerprint=pol.fingerprint(None), value_hash=chash, facts_fingerprint=chash, idempotency_key=key, policy_level=decision.level, effective_type=decision.effective_type,
        risk_level=decision.risk, policy_reasons=decision.reasons, authorization="owner", status="approved", proposed_by="user", proposed_by_user=sub.approved_by,
    )
    try:
        with db.begin_nested():
            db.add(a)
            db.flush()
    except IntegrityError:
        racing = db.scalar(select(AgentAction).where(AgentAction.tenant_id == sub.tenant_id, AgentAction.idempotency_key == key, AgentAction.status.in_(LIVE_STATUSES)).limit(1))
        if racing is None:
            raise
        return racing
    history.record(db, a, "proposed", actor="user", user_id=sub.approved_by, now=now, data={"action_type": sub.action_type, "subject": sub.kind, "subject_id": str(sub.subject_id) if sub.subject_id else None,
                                                                                         "content": sub.content, "expected_outcome": CONTENT_OUTCOME})
    history.record(db, a, "policy_classified", actor="system", now=now, data={"level": decision.level, "label": pol.LABELS[decision.level], "effective_type": decision.effective_type, "risk": decision.risk,
                                                                              "reasons": decision.reasons, "authorization": "owner", "person_only": True})
    role_basis = {Role.owner: "owner", Role.admin: "admin"}.get(sub.role, "person")  # the scheduled job does not know the role; the approval still names the person
    ap = _add_approval(db, a, "approved", role_basis, sub.approved_by, "Approved by a person before it was sent.", sub.approved_at or now, None)
    history.record(db, a, "approved", actor="user", user_id=sub.approved_by, now=now, data={"basis": role_basis, "scope_hash": ap.scope_hash, "approved_at": sub.approved_at.isoformat() if sub.approved_at else None,
                                                                                       "content": sub.content})
    return a


def _end(db: Session, a: AgentAction, status: str, event: str, now: datetime, data: dict, *, error: str | None = None, next_at: datetime | None = None) -> None:
    a.status = status
    if error is not None:
        a.last_error = error[:1000]
    a.next_attempt_at = next_at
    history.record(db, a, event, actor="system", now=now, data=data)
    db.commit()


def govern(db: Session, sub: Subject, *, provider=None, now: datetime | None = None) -> dict:
    """Run one publish under the policy. Returns {"outcome": done | retry | failed | skipped | held, "action_id", "verified", "detail", "payload"}.
    `held` = nothing was sent and the item is untouched (platform stop, no plan feature, no person's approval, not connected)."""
    now = now or utcnow()
    spec = pol.SPECS[sub.action_type]
    if not spec.person_only:
        raise pol.PolicyError(f"'{sub.action_type}' is not governed publishing.")
    stop = controls.emergency_stop(db)
    if stop:
        return {"outcome": "held", "reason": "emergency_stop", "detail": stop["reason"]}
    if sub.approved_by is None:
        return {"outcome": "held", "reason": "no_person_approval", "detail": "A person must approve this before it is sent to Google."}
    gloc = db.get(GoogleLocation, sub.google_location_id)
    conn = db.get(GoogleConnection, gloc.connection_id) if gloc else None
    tenant = db.get(Tenant, sub.tenant_id)
    if gloc is None or conn is None or tenant is None or gloc.tenant_id != sub.tenant_id or conn.tenant_id != sub.tenant_id:
        return {"outcome": "held", "reason": "tenant_mismatch", "detail": "The item, location and Google connection do not all belong to the same business."}
    if not tenant.is_active or tenant.suspended_at or tenant.deletion_scheduled_for:  # a business that asked to be deleted, or is suspended, sends nothing more to Google
        return {"outcome": "held", "reason": "business_unavailable", "detail": "This business is suspended or has asked to be deleted, so nothing is sent to Google."}
    if not ent.for_tenant(db, sub.tenant_id).has(sub.feature):
        return {"outcome": "held", "reason": "plan", "detail": "The plan does not include this or is inactive."}
    a = _get_or_create(db, sub, now)
    if a.status == "executed":
        return {"outcome": "done", "action_id": str(a.id), "verified": a.verified_at is not None, "reason": "already_executed", "payload": a.google_result or {}}
    if a.status != "approved":
        return {"outcome": "skipped", "action_id": str(a.id), "reason": "not_approved", "detail": f"The action is {a.status}."}
    if a.next_attempt_at is not None and a.next_attempt_at > now and sub.subject_id is None:
        return {"outcome": "skipped", "action_id": str(a.id), "reason": "not_due"}
    # ---- claim: durable BEFORE the publisher runs; the in-flight unique index admits one publish of one item at a time
    a.status, a.attempts, a.claimed_at, a.last_error = "executing", (a.attempts or 0) + 1, now, None
    try:
        history.record(db, a, "executing", actor="system", now=now, data={"attempt": a.attempts, "publisher": sub.kind})
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"outcome": "skipped", "reason": "busy", "detail": "This item is already being sent."}
    # ---- the existing publisher
    try:
        result, payload = sub.send()
    except Exception as exc:  # noqa: BLE001 - recorded on the action, then re-raised: the caller maps it to its own HTTP error
        a = db.get(AgentAction, a.id)
        detail = getattr(exc, "detail", None) or str(exc)
        a.status, a.last_error = "failed", str(detail)[:1000]
        history.record(db, a, "failed", actor="google", now=now, data={"stage": "write", "reason": str(detail)[:500]})
        db.commit()
        raise
    a = db.get(AgentAction, a.id)  # the publisher may have committed or rolled back the session
    api_usage.record(db, tenant_id=a.tenant_id, provider=api_usage.GBP, operation=f"{sub.kind}.publish", feature="publish", status="ok" if result == "done" else "error",
                     location_id=a.google_location_id, idempotency_key=f"gbpc:{a.id}:{a.attempts}")
    if result in ("retry", "skipped"):
        nxt = sub.next_attempt_hint() if sub.next_attempt_hint else None
        _end(db, a, "approved", "retry_scheduled", now, {"result": result, "reason": (payload or {}).get("reason"), "next_attempt_at": nxt.isoformat() if nxt else None},
             error=(payload or {}).get("reason"), next_at=nxt)
        return {"outcome": result, "action_id": str(a.id), "detail": (payload or {}).get("reason"), "payload": payload}
    if result != "done":
        _end(db, a, "failed", "failed", now, {"stage": "write", "reason": (payload or {}).get("reason")}, error=(payload or {}).get("reason") or "Google did not accept it.")
        return {"outcome": "failed", "action_id": str(a.id), "detail": (payload or {}).get("reason"), "payload": payload}
    history.record(db, a, "google_write", actor="google", now=now, data={"result": "accepted", **{k: v for k, v in (payload or {}).items() if k in ("name", "state", "google_url")}})
    # ---- read back from Google, separately, and compare
    try:
        provider = provider or g.get_google_provider()
        token = get_access_token(db, conn, provider)
        ver = sub.verify(provider, token, payload or {})
    except Exception as exc:  # noqa: BLE001 - cannot read Google now: NOT verified, never "assumed fine"
        ver = {"matched": False, "detail": f"Google could not be read to confirm it ({type(exc).__name__}).", "unreadable": True}
    ver = {**ver, "read_at": utcnow().isoformat()}
    history.record(db, a, "read_back", actor="google", now=now, data=ver)
    a.google_result, a.verification = {k: v for k, v in (payload or {}).items() if not k.startswith('_')}, ver
    if ver.get("matched"):
        a.status, a.executed_at, a.verified_at, a.last_error = "executed", now, now, None
        history.record(db, a, "verified", actor="system", now=now, data={"subject": sub.kind, "matched": True})
        db.commit()
        return {"outcome": "done", "action_id": str(a.id), "verified": True, "payload": payload, "detail": ver.get("detail")}
    why = ver.get("detail") or "A read of Google does not show it yet."
    a.status, a.last_error = "failed", f"Sent, but not confirmed: {why}"
    history.record(db, a, "failed", actor="system", now=now, data={"stage": "verification", "reason": a.last_error})
    db.commit()
    return {"outcome": "done", "action_id": str(a.id), "verified": False, "payload": payload, "detail": a.last_error}


# =============================================================================================================================================
# the three scheduled kinds: the existing publishers, governed
# =============================================================================================================================================
def _post_content(p: ScheduledPost) -> dict:
    return {"summary": p.summary, "language": p.language, "cta_type": p.cta_type, "cta_url": p.cta_url, "topic_type": p.topic_type or "STANDARD", "photo": bool(p.photo_url),
            "event_title": p.event_title, "offer_coupon": p.offer_coupon}


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def _verify_post(summary: str):
    def check(provider, token, payload) -> dict:
        name = (payload or {}).get("name")
        gloc = (payload or {}).get("_gloc")
        found = None
        for gp in provider.list_posts(token, gloc[0], gloc[1]):
            if (name and gp.get("name") == name) or (not name and _norm(gp.get("summary")) == _norm(summary)):
                found = gp
                break
        if found is None:
            return {"matched": False, "detail": "Google's list of posts does not show it yet."}
        if found.get("state") == "REJECTED":
            return {"matched": False, "detail": "Google shows the post but REJECTED it."}
        if _norm(found.get("summary")) != _norm(summary):
            return {"matched": False, "detail": "The post Google holds has different text from what was approved."}
        return {"matched": True, "detail": f"Google lists the post (state {found.get('state') or 'LIVE'}).", "name": found.get("name"), "state": found.get("state")}
    return check


def post_subject(db: Session, post: ScheduledPost, *, provider=None, now: datetime | None = None, role: Role | None = None) -> Subject:
    from app.services.agent import posts as posts_svc

    gloc = db.get(GoogleLocation, post.google_location_id)

    def send():
        res = posts_svc.publish(db, post, provider=provider, now=now)
        names = {"published": "done"}
        return names.get(res, res), {"name": post.google_post_name, "reason": post.failure_reason, "_gloc": (gloc.google_account_name, gloc.google_location_name)}

    return Subject(kind="post", action_type="publish_content", tenant_id=post.tenant_id, google_location_id=post.google_location_id, subject_id=post.id, feature="gbp_posts",
                   content=_post_content(post), approved_by=post.approved_by, approved_at=post.approved_at, label="Google Post", send=send, verify=_verify_post(post.summary),
                   role=role, next_attempt_hint=lambda: post.next_attempt_at)


def photo_subject(db: Session, m: ScheduledMedia, *, provider=None, now: datetime | None = None, role: Role | None = None) -> Subject:
    from app.services import media as media_svc

    def send():
        res = media_svc.publish(db, m, provider=provider, now=now)
        return {"published": "done"}.get(res, res), {"name": m.google_media_name, "google_url": m.google_url, "reason": m.failure_reason}

    def verify(provider_, token, payload) -> dict:
        item = provider_.get_media(token, payload.get("name") or m.google_media_name)
        if not item or (item.get("name") and item["name"] != (payload.get("name") or m.google_media_name)):
            return {"matched": False, "detail": "Google does not return this photo."}
        return {"matched": True, "detail": "Google holds the photo" + ("" if item.get("google_url") else " and is still processing it (it appears publicly when processing finishes)") + ".",
                "name": item.get("name"), "processing": not item.get("google_url")}

    content = {"category": m.category, "sha256": m.sha256, "description": m.description, "bytes": m.size_bytes}
    return Subject(kind="photo", action_type="upload_photo", tenant_id=m.tenant_id, google_location_id=m.google_location_id, subject_id=m.id, feature="gbp_media", content=content,
                   approved_by=m.approved_by, approved_at=m.approved_at, label="photo", send=send, verify=verify, role=role, next_attempt_hint=lambda: m.next_attempt_at)


def reply_subject(db: Session, d: ReplyDraft, *, by_user, provider=None, role: Role | None = None) -> Subject:
    from app.services import reviews as review_svc

    review = db.get(Review, d.review_id)
    gloc = db.get(GoogleLocation, review.google_location_id)

    def send():
        out = review_svc.publish_draft(db, d, by_user=by_user, provider=provider)
        if out.status == ReplyStatus.published:
            return "done", {"state": review.google_reply_state}
        return "failed", {"reason": out.failure_reason}

    def verify(provider_, token, payload) -> dict:
        page_token, want = None, " ".join(d.body.split())
        for _ in range(READ_BACK_PAGES):
            page = provider_.list_reviews(token, gloc.google_account_name, gloc.google_location_name, page_token)
            hit_ = next((rv for rv in page.reviews if rv.external_id == review.external_id), None)
            if hit_ is not None:
                if getattr(hit_, "reply_state", None) == "REJECTED":
                    return {"matched": False, "detail": "Google shows the reply but REJECTED it."}
                if " ".join((hit_.reply_text or "").split()) == want:
                    return {"matched": True, "detail": f"Google shows the reply (state {hit_.reply_state or 'LIVE'})."}
                return {"matched": False, "detail": "Google shows no reply, or a different reply, on this review yet."}
            page_token = page.next_page_token
            if not page_token:
                break
        return {"matched": False, "detail": "The review was not found when reading Google back."}

    return Subject(kind="reply", action_type="reply_publish", tenant_id=d.tenant_id, google_location_id=review.google_location_id, subject_id=d.id, feature="ai_replies",
                   content={"review": review.external_id, "body": d.body, "risk": d.risk_level}, approved_by=d.approved_by, approved_at=d.approved_at, label="review reply", send=send,
                   verify=verify, role=role)


def run(db: Session, kind: str, row, *, provider=None, by_user=None, now: datetime | None = None, role: Role | None = None) -> dict:
    """The one way a scheduled post, a scheduled photo or an approved reply reaches Google. Same call shape for all three."""
    sub = {"post": lambda: post_subject(db, row, provider=provider, now=now, role=role), "photo": lambda: photo_subject(db, row, provider=provider, now=now, role=role),
           "reply": lambda: reply_subject(db, row, by_user=by_user, provider=provider, role=role)}[kind]()
    return govern(db, sub, provider=provider, now=now)


# =============================================================================================================================================
# a person acting directly in the dashboard (the owner-facing Posts and Photos tools): same governance, the acting user is the approver
# =============================================================================================================================================
def direct(db: Session, *, kind: str, action_type: str, tenant_id: uuid.UUID, gloc: GoogleLocation, user_id: uuid.UUID, role: Role, feature: str, content: dict, label: str,
           send: Callable[[], tuple[str, dict]], verify: Callable[[Any, str, dict], dict], provider=None, now: datetime | None = None) -> dict:
    at = (now or utcnow()).replace(second=0, microsecond=0)  # the same content by the same person within one minute is the same action: a double click sends once
    sub = Subject(kind=kind, action_type=action_type, tenant_id=tenant_id, google_location_id=gloc.id, subject_id=None, feature=feature, content=content, approved_by=user_id,
                  approved_at=at, label=label, send=send, verify=verify, role=role)
    return govern(db, sub, provider=provider, now=now)


# =============================================================================================================================================
# crash recovery for governed publishing
# =============================================================================================================================================
def _load_subject(db: Session, a: AgentAction):
    model = {"post": ScheduledPost, "photo": ScheduledMedia, "reply": ReplyDraft}.get(a.subject_type or "")
    return db.get(model, a.subject_id) if model is not None and a.subject_id else None


def recover_stuck(db: Session, *, provider=None, now: datetime | None = None, limit: int = 20) -> dict:
    """A governed action left `executing` by a crash is resolved by LOOKING, never by sending again on a guess:
      * the item is published  -> read Google back and verify it (executed) or fail it as unconfirmed;
      * a post/reply is still scheduled/failed -> the item's own recovery (posts.recover_stuck, the reply retry job) already decided; the action follows it;
      * a PHOTO is not published -> it may or may not have reached Google and Google has no way to say, so it is marked failed for a person to check: a photo is never re-sent blind;
      * a direct action (no row behind it) -> failed, with the note to check Google.
    """
    now = now or utcnow()
    out = {"verified": 0, "requeued": 0, "failed": 0, "deferred": 0}
    cutoff = now - timedelta(minutes=settings.autonomy_stuck_minutes)
    ids = list(db.scalars(select(AgentAction.id).where(AgentAction.status == "executing", AgentAction.subject_type.is_not(None), AgentAction.claimed_at < cutoff).limit(limit)))
    for aid in ids:
        a = db.scalar(select(AgentAction).where(AgentAction.id == aid, AgentAction.status == "executing").with_for_update(skip_locked=True))
        if a is None:
            continue
        row = _load_subject(db, a)
        status = (getattr(row, "status", None).value if hasattr(getattr(row, "status", None), "value") else getattr(row, "status", None)) if row is not None else None
        if row is None:
            _end(db, a, "failed", "failed", now, {"stage": "recovery", "reason": "interrupted; nothing is recorded for this item"}, error="Interrupted while sending. Check your Google Business Profile before sending it again.")
            out["failed"] += 1
        elif status == "published":
            try:
                provider = provider or g.get_google_provider()
                s = {"post": lambda: post_subject(db, row), "photo": lambda: photo_subject(db, row), "reply": lambda: reply_subject(db, row, by_user=row.approved_by)}[a.subject_type]()
                gloc = db.get(GoogleLocation, a.google_location_id)
                conn = db.get(GoogleConnection, gloc.connection_id)
                ver = s.verify(provider, get_access_token(db, conn, provider), {"name": getattr(row, "google_post_name", None) or getattr(row, "google_media_name", None),
                                                                                  "_gloc": (gloc.google_account_name, gloc.google_location_name)})
            except Exception as exc:  # noqa: BLE001
                log.warning("content recovery could not read Google for %s: %s", aid, exc)
                out["deferred"] += 1
                db.rollback()
                continue
            ver = {**ver, "read_at": now.isoformat(), "note": "found published when recovering from an interruption"}
            history.record(db, a, "read_back", actor="google", now=now, data=ver)
            if ver.get("matched"):
                a.status, a.executed_at, a.verified_at, a.verification = "executed", now, now, ver
                history.record(db, a, "verified", actor="system", now=now, data={"subject": a.subject_type, "matched": True, "recovered": True})
                db.commit()
                out["verified"] += 1
            else:
                _end(db, a, "failed", "failed", now, {"stage": "recovery", "reason": ver.get("detail")}, error=f"Sent, but not confirmed: {ver.get('detail')}")
                out["failed"] += 1
        elif status == "publishing":
            out["deferred"] += 1  # the item's own recovery job owns this state
            db.rollback()
        elif a.subject_type == "photo":
            if row is not None:
                row.status, row.failure_reason = "failed", "FlowQR lost contact while uploading this photo and cannot tell whether Google received it. Check your Google photos, then retry only if it is missing."
            _end(db, a, "failed", "failed", now, {"stage": "recovery", "reason": "a photo is never re-sent without a person checking"}, error="Interrupted while uploading; a person must check Google before retrying.")
            out["failed"] += 1
        elif status in ("scheduled", "approved", "draft") or status is None:
            _end(db, a, "approved", "recovered_requeued", now, {"reason": "interrupted before Google answered; the item will be checked again before anything is sent"}, next_at=now)
            out["requeued"] += 1
        else:
            _end(db, a, "failed", "failed", now, {"stage": "recovery", "reason": f"the item is {status}"}, error=f"Interrupted; the item is now {status}.")
            out["failed"] += 1
    return out
