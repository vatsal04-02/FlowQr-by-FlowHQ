"""Notifications (PRD §6.5 bell, §9 email preferences).

Nothing new is recorded to feed these: every item is read from data FlowQR already keeps (synced reviews, reply drafts, Google sync
state, scheduled posts, the subscription). The bell polls; the email job runs hourly with a per-person watermark so nothing is sent twice.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GoogleLocation, Membership, MembershipLocation, ReplyDraft, ReplyStatus, Review, ScheduledPost, Subscription, Tenant, User
from app.models.base import utcnow
from app.models.notifications import DEFAULTS, NotificationPref
from app.services.ai.safety import assess_review

RECENT = timedelta(days=7)


@dataclass
class Item:
    id: str
    kind: str  # new_review | flagged_review | failed_reply | sync_failed | failed_post | trial_ending
    tone: str  # info | warn | bad
    title: str
    body: str
    href: str
    at: datetime


def prefs_for(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, *, create: bool = False) -> NotificationPref:
    p = db.scalar(select(NotificationPref).where(NotificationPref.tenant_id == tenant_id, NotificationPref.user_id == user_id))
    if p is None:
        p = NotificationPref(tenant_id=tenant_id, user_id=user_id, **DEFAULTS)
        if create:
            db.add(p)
    return p


def _in_scope(col, location_ids: frozenset[uuid.UUID] | None):
    from sqlalchemy import true
    return true() if location_ids is None else col.in_(list(location_ids))


def collect(db: Session, tenant: Tenant, *, location_ids: frozenset[uuid.UUID] | None, since: datetime | None = None, now: datetime | None = None) -> list[Item]:
    """Everything worth a person's attention, newest first. `location_ids` = what this member may see (None = all)."""
    now = now or utcnow()
    since = since or (now - RECENT)
    out: list[Item] = []
    sensitive_ids: set[uuid.UUID] = set()

    # new reviews (first seen by FlowQR, not the date the customer wrote them: a review synced late is still "new" to the owner)
    for r in db.scalars(select(Review).where(Review.tenant_id == tenant.id, Review.first_seen_at > since, _in_scope(Review.location_id, location_ids))
                        .order_by(Review.first_seen_at.desc()).limit(20)):
        reasons = assess_review(r.text, r.rating, tenant.category) if r.google_reply_text is None else []
        who = r.reviewer_name or "A customer"
        if reasons:
            sensitive_ids.add(r.id)
            out.append(Item(f"flagged-{r.id}", "flagged_review", "warn", f"{who} left a review that needs you personally",
                            "It mentions something sensitive, so the AI won't reply without your acknowledgement.", f"/gbp/reviews/{r.id}", r.first_seen_at))
        else:
            out.append(Item(f"review-{r.id}", "new_review", "info", f"New {r.rating}-star review from {who}",
                            (r.text or "Rating only, no comment")[:140], f"/gbp/reviews/{r.id}", r.first_seen_at))

    # replies Google didn't accept
    for d, r in db.execute(select(ReplyDraft, Review).join(Review, Review.id == ReplyDraft.review_id).where(
            ReplyDraft.tenant_id == tenant.id, ReplyDraft.status == ReplyStatus.failed, ReplyDraft.updated_at > since,
            _in_scope(Review.location_id, location_ids)).order_by(ReplyDraft.updated_at.desc()).limit(10)):
        out.append(Item(f"failed-reply-{d.id}", "failed_reply", "bad", "A reply didn't reach Google",
                        d.failure_reason or "Google didn't accept it. Open the review to try again.", f"/gbp/reviews/{r.id}", d.updated_at))

    # Google sync problems (only for locations this member can see)
    for g in db.scalars(select(GoogleLocation).where(GoogleLocation.tenant_id == tenant.id, GoogleLocation.selected.is_(True),
                                                     GoogleLocation.last_sync_status.in_(["error", "rate_limited"]), _in_scope(GoogleLocation.location_id, location_ids))):
        at = g.last_synced_at or g.updated_at
        out.append(Item(f"sync-{g.id}-{int(at.timestamp())}", "sync_failed", "bad", f"Reviews from {g.title or 'a location'} aren't updating",
                        g.last_sync_error or "Google didn't let FlowQR read this location.", "/gbp/locations", at))

    # Google posts that failed (business-wide, so only for people who see every location)
    if location_ids is None:
        for p in db.scalars(select(ScheduledPost).where(ScheduledPost.tenant_id == tenant.id, ScheduledPost.status == "failed", ScheduledPost.updated_at > since).limit(10)):
            out.append(Item(f"post-{p.id}", "failed_post", "bad", "A Google post didn't publish", p.failure_reason or p.summary[:140], "/gbp/posts", p.updated_at))

    # trial ending (once it is within 5 days)
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant.id))
    if location_ids is None and sub and sub.status == "trialing" and sub.trial_ends_at and now <= sub.trial_ends_at <= now + timedelta(days=5):
        days = max(0, (sub.trial_ends_at - now).days)
        out.append(Item(f"trial-{sub.trial_ends_at.date()}", "trial_ending", "warn",
                        "Your free trial ends today" if days == 0 else f"{days} {'day' if days == 1 else 'days'} left in your free trial",
                        "Choose a plan to keep AI replies and Google sync running. Your cards keep working either way.", "/settings/billing", sub.trial_ends_at - timedelta(days=5)))
    out.sort(key=lambda i: i.at, reverse=True)
    return out


def member_location_ids(db: Session, m: Membership) -> frozenset[uuid.UUID] | None:
    if m.all_locations or m.role.value in ("owner", "admin"):
        return None
    return frozenset(db.scalars(select(MembershipLocation.location_id).where(MembershipLocation.membership_id == m.id)))


def as_json(items: list[Item], seen_at: datetime | None) -> dict:
    rows = [{**asdict(i), "at": i.at.isoformat(), "unread": seen_at is None or i.at > seen_at} for i in items]
    return {"items": rows, "unread": sum(1 for r in rows if r["unread"])}


PREF_FOR_KIND = {"new_review": "email_new_review", "flagged_review": "email_flagged_review", "sync_failed": "email_sync_failed", "trial_ending": "email_trial_ending"}


def digest_for(db: Session, tenant: Tenant, m: Membership, prefs: NotificationPref, now: datetime) -> list[Item]:
    """What this member should be emailed now: events since their watermark, filtered by their choices. Trial notices are sent once,
    when the trial first enters its last 5 days."""
    since = prefs.last_emailed_at
    items = collect(db, tenant, location_ids=member_location_ids(db, m), since=since, now=now)
    # Sync problems are current state, not events, so they are also checked against the watermark here; for a trial notice `at` is the
    # moment its 5-day window opened, so it goes out exactly once.
    return [i for i in items if (key := PREF_FOR_KIND.get(i.kind)) and getattr(prefs, key) and i.at > since]


def email_text(tenant: Tenant, user: User, items: list[Item], frontend_url: str) -> tuple[str, str]:
    n = len(items)
    subject = f"FlowQR: {items[0].title}" if n == 1 else f"FlowQR: {n} updates for {tenant.name}"
    lines = [f"Hi {user.full_name.split()[0] if user.full_name else ''},".strip(), "", f"Here's what happened at {tenant.name}:", ""]
    for i in items[:15]:
        lines += [f"- {i.title}", f"  {i.body}", f"  {frontend_url.rstrip('/')}{i.href}", ""]
    if n > 15:
        lines.append(f"…and {n - 15} more on your FlowQR dashboard.")
    lines += ["", "Nothing is posted to Google until you approve it.", f"Change which emails you get: {frontend_url.rstrip('/')}/settings/notifications"]
    return subject, "\n".join(lines)
