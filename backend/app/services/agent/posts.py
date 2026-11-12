"""Google Posts workflow: draft -> awaiting approval -> approved -> scheduled -> publishing -> published | failed.

Google does not schedule posts for us, so FlowQR holds approved posts and a Celery job publishes them when due. A post is marked
`published` only after Google returns it. Failures keep Google's diagnostic and are retried only when retrying can help.
"""
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rate_limit import hit
from app.models import GoogleConnection, GoogleConnectionStatus, GoogleLocation, ScheduledPost, Tenant
from app.models.base import utcnow
from app.services import google as g
from app.services.agent import knowledge as kbs
from app.services.agent.safety import check_text
from app.services.ai.base import AIUnavailable, LLMProvider
from app.services.google.tokens import get_access_token, note_not_approved

log = logging.getLogger("flowqr.posts")
MAX_ATTEMPTS = 4
SUMMARY_MIN, SUMMARY_MAX = 10, 1500

TRANSITIONS = {
    "draft": {"awaiting_approval", "canceled"},
    "awaiting_approval": {"approved", "draft", "canceled"},
    "approved": {"scheduled", "publishing", "draft", "canceled"},
    "scheduled": {"publishing", "approved", "draft", "canceled"},
    "publishing": {"published", "failed", "scheduled"},
    "failed": {"scheduled", "draft", "canceled"},
    "published": set(),
    "canceled": set(),
}
EDITABLE = {"draft", "awaiting_approval", "failed"}


class PostError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def move(post: ScheduledPost, to: str) -> None:
    if to not in TRANSITIONS.get(post.status, set()):
        raise PostError(f"A post that is {post.status.replace('_', ' ')} cannot become {to.replace('_', ' ')}.")
    post.status = to


SYSTEM = """You write short Google Business Profile posts for a local business owner.

RULES:
- 2 to 4 sentences, friendly and specific, in the requested language. No hashtags spam, at most one emoji if the brand voice allows it.
- Use ONLY the business facts you are given. Never invent services, prices, offers, discounts, results, staff, awards or opening times.
- Do not promise outcomes. Do not mention any customer or patient. No medical advice.
- Output ONLY the post text. No quotes, no title, no markdown."""

TOPICS = ["introduce one of the services", "answer one of the frequently asked questions", "remind people of the opening hours and how to get in touch",
          "share a seasonal, general wellbeing or local-community message that makes no claims", "present a verified offer, if one exists"]


def draft_post(provider: LLMProvider, tenant: Tenant, kb: dict, *, topic: str | None = None, language: str | None = None, avoid: list[str] | None = None) -> tuple[str, list[dict]]:
    """AI post text grounded in the knowledge base. Returns (text, []) or raises AIUnavailable(code="rejected") after one retry."""
    lang = language or tenant.language or "en"
    pick = topic or TOPICS[(utcnow().timetuple().tm_yday) % (len(TOPICS) - (0 if kb["offers"] else 1))]
    user = (kbs.render(kb) + f"\n\nLanguage: {'Hindi (Devanagari)' if lang == 'hi' else 'Hinglish (Hindi in Roman letters)' if lang == 'hinglish' else 'English'}\n"
            f"Write one post that will {pick}.\n" + (f"Do not repeat these recent posts:\n- " + "\n- ".join(a[:140] for a in avoid[:5]) if avoid else ""))
    out = provider.generate(SYSTEM, user, max_tokens=350, temperature=0.6).strip().strip('"').strip()
    bad = check_text(out, kb=kb, kind="post") if out else []
    if bad:
        out = provider.generate(SYSTEM, user + "\n\nYour previous draft was rejected because: " + " ".join(b.message for b in bad) + "\nWrite a new post that avoids this.",
                                max_tokens=350, temperature=0.3).strip().strip('"').strip()
        if out and check_text(out, kb=kb, kind="post"):
            raise AIUnavailable("The post draft broke a safety rule twice, so it was not shown", code="rejected")
    if not (SUMMARY_MIN <= len(out) <= SUMMARY_MAX):
        raise AIUnavailable("The draft didn't meet our quality checks")
    return out, []


def validate_content(post: ScheduledPost, kb: dict) -> list[dict]:
    """Safety findings for a post the owner is about to approve (also applies to hand-written and edited text)."""
    return [v.as_dict() for v in check_text(post.summary, kb=kb, kind="post")]


def approve(post: ScheduledPost, *, user_id: uuid.UUID, when: datetime | None) -> None:
    """Owner approval. `when=None` means publish as soon as the scheduler runs; otherwise at that time (must be in the future)."""
    if post.status != "awaiting_approval":
        raise PostError("Only a post that is awaiting approval can be approved.")
    now = utcnow()
    if when is not None and when <= now + timedelta(seconds=30):
        when = None
    move(post, "approved")
    post.approved_by, post.approved_at = user_id, now
    move(post, "scheduled")
    post.scheduled_for = when or now
    post.next_attempt_at, post.failure_reason, post.attempts = None, None, 0


def retry(post: ScheduledPost) -> None:
    if post.status != "failed":
        raise PostError("Only a failed post can be retried.")
    move(post, "scheduled")
    post.scheduled_for = post.next_attempt_at = utcnow()
    post.failure_reason, post.attempts = None, 0


def describe_failure(exc: Exception) -> tuple[str, bool]:
    """(owner-readable diagnostic, retry_may_help)."""
    if isinstance(exc, g.GoogleApiNotApproved):
        return str(exc), False
    if isinstance(exc, g.GoogleAuthRevoked):
        return "Google access was revoked or the permission is missing. Reconnect Google, then retry.", False
    if isinstance(exc, g.GoogleRateLimited):
        return "Google rate limit reached; FlowQR will try again automatically.", True
    if isinstance(exc, g.GoogleAPIError):
        if exc.transient or exc.status in (408, 429):
            return f"Google had a temporary problem (HTTP {exc.status}); FlowQR will try again automatically.", True
        if exc.status == 400:
            return f"Google rejected this post: {str(exc)[:200]}. Edit it and retry.", False
        if exc.status in (401, 403):
            return "Google denied the request: the connected account may not manage this location, or the API is not approved for FlowQR.", False
        return f"Google answered HTTP {exc.status}; nothing was published.", False
    return f"Unexpected error ({type(exc).__name__}); nothing was published.", True


def publish(db: Session, post: ScheduledPost, *, provider=None, now: datetime | None = None) -> str:
    """Try to publish one due post. Returns published | retry | failed | skipped. The caller holds the row lock and commits."""
    now = now or utcnow()
    gloc = db.get(GoogleLocation, post.google_location_id)
    conn = db.get(GoogleConnection, gloc.connection_id) if gloc else None
    if gloc is None or not gloc.selected or conn is None or conn.status != GoogleConnectionStatus.active:
        post.status, post.failure_reason = "failed", "This location is no longer connected to Google. Reconnect it, then retry."
        return "failed"
    if not hit(f"gbp-edit:{gloc.id}", 10, 60):  # Google allows 10 edits per minute per location
        post.next_attempt_at = now + timedelta(seconds=65)
        return "skipped"
    move(post, "publishing")
    post.attempts += 1
    try:
        provider = provider or g.get_google_provider()
        token = get_access_token(db, conn, provider)
        created = provider.create_post(token, gloc.google_account_name, gloc.google_location_name,
                                       {"summary": post.summary, "language": post.language, "cta_type": post.cta_type, "cta_url": post.cta_url, "photo_url": post.photo_url})
    except Exception as exc:  # noqa: BLE001 - every failure is recorded, none is swallowed
        reason, may_retry = describe_failure(exc)
        if isinstance(exc, g.GoogleApiNotApproved):
            note_not_approved(conn, exc)
        if may_retry and post.attempts < MAX_ATTEMPTS:
            post.status, post.failure_reason = "scheduled", reason
            post.next_attempt_at = now + timedelta(minutes=5 * 2 ** (post.attempts - 1))
            return "retry"
        post.status, post.failure_reason, post.next_attempt_at = "failed", reason, None
        return "failed"
    post.status, post.published_at, post.google_post_name = "published", utcnow(), (created or {}).get("name")
    post.failure_reason, post.next_attempt_at = None, None
    return "published"


def due(db: Session, limit: int = 50, now: datetime | None = None) -> list[ScheduledPost]:
    now = now or utcnow()
    q = (select(ScheduledPost).where(ScheduledPost.status == "scheduled", ScheduledPost.scheduled_for <= now,
                                     (ScheduledPost.next_attempt_at.is_(None)) | (ScheduledPost.next_attempt_at <= now))
         .order_by(ScheduledPost.scheduled_for).limit(limit).with_for_update(skip_locked=True))
    return list(db.scalars(q))
