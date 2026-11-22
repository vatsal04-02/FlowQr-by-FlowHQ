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
from app.services.ai import craft, intelligence, quality
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


SYSTEM = """You are a local-marketing strategist who specialises in Google Business Profile for small businesses in India. You write one Google Post for the owner to approve.

WHAT MAKES A GOOD POST
- The first sentence earns the read: it names a problem, question, season or situation the customer already has. It is never the business name, "Welcome to", or a greeting.
- It gives the reader ONE concrete, useful thing (a tip, an answer, what to expect, how to book). Specific beats enthusiastic.
- It sounds like a person at this business talking to a neighbour: natural words, short sentences, no brochure language.
- It ends with one natural next step that suits how customers reach this business (call, visit, message), without pressure.
- 3 to 5 sentences. At most one emoji, and only if the brand voice suits it. No hashtags.

NEVER
- State anything about the business that is not in the BUSINESS FACTS: no invented services, prices, offers, discounts, results, staff, awards, timings, dates or events.
- Promise outcomes, cures or results; mention any customer or patient; give medical advice; make comparative claims ("best", "number 1").
- Use stock phrases ("we are thrilled", "state-of-the-art", "look no further", "your satisfaction is our priority") or stuff keywords.
- Copy the topic, angle or opening of a recent post.

OUTPUT: only the post text. No quotes, no title, no markdown."""

TOPICS = ["introduce one of the services", "answer one of the frequently asked questions", "remind people of the opening hours and how to get in touch",
          "share a seasonal, general wellbeing or local-community message that makes no claims", "present a verified offer, if one exists"]  # kept for callers that pass a topic


SEO_RULE = ("If search terms are given, work in at most two that genuinely fit this post, naturally and once each. Never list keywords, never repeat the business name, "
            "never mention Google rankings or promise results.")


def build_prompt(tenant: Tenant, kb: dict, *, lang: str, post_type: str | None, topic: str | None, avoid: list[str] | None, terms: str | None, intel: dict | None) -> tuple[str, str]:
    """(user prompt, post type used). A free-text `topic` from the owner wins; otherwise the type rotates so consecutive posts differ."""
    pb = craft.playbook(kb.get("category") or tenant.category)
    recent = list(dict.fromkeys((avoid or []) + ((intel or {}).get("recent_posts") or [])))
    recent_types = (intel or {}).get("recent_post_types") or [craft.classify_post(a) for a in (avoid or [])]
    ptype = post_type if post_type in craft.POST_TYPES else craft.pick_post_type(kb, day=utcnow().timetuple().tm_yday, recent_types=recent_types)
    parts = [kbs.render(kb)]
    if intel:
        obs = intelligence.render(intel)
        if obs:
            parts.append(obs)
    parts.append(f"WHAT CUSTOMERS OF THIS KIND OF BUSINESS CARE ABOUT: {pb['care']}.\nANGLES THAT WORK (pick what fits the facts, do not use any that need facts you were not given): "
                 + "; ".join(pb["angles"][:5]) + f".\nSTAY AWAY FROM: {pb['avoid']}.")
    parts.append(f"LANGUAGE: {craft.LANGUAGE_STYLE.get(lang, craft.LANGUAGE_STYLE['en'])}")
    if topic:
        parts.append(f"The owner wants a post about: {topic.strip()[:200]}. Stay within the facts above.")
        ptype = "update"
    else:
        t = craft.POST_TYPES[ptype]
        parts.append(f"POST TYPE: {t['label']}. {t['brief']}")
        if ptype == "seasonal":
            parts.append("Occasions around now (general; pick at most one that truly suits this business): " + "; ".join(craft.occasions(utcnow().date())[:4]))
    if terms:
        parts.append(f"{terms}\n{SEO_RULE}")
    if recent:
        parts.append("Recent posts: do NOT repeat their topic, angle, phrases or opening:\n- " + "\n- ".join(a[:140] for a in recent[:6]))
    return "\n\n".join(parts), ptype


def draft_post_scored(provider: LLMProvider, tenant: Tenant, kb: dict, *, topic: str | None = None, language: str | None = None, avoid: list[str] | None = None,
                      terms: str | None = None, intel: dict | None = None, post_type: str | None = None):
    """(text, quality.Assessment, post_type). Safety problems twice in a row raise AIUnavailable(code="rejected"); quality problems get one retry and then lower the score only."""
    lang = language or tenant.language or "en"
    if lang not in craft.LANGUAGE_STYLE:
        lang = "en"
    user, ptype = build_prompt(tenant, kb, lang=lang, post_type=post_type, topic=topic, avoid=avoid, terms=terms, intel=intel)
    recent = list(dict.fromkeys((avoid or []) + ((intel or {}).get("recent_posts") or [])))
    term_list = [t.strip() for t in terms.split(":", 1)[1].split(",")] if terms and ":" in terms else []

    def judge(out: str):
        bad = check_text(out, kb=kb, kind="post") if out else []
        qa = quality.assess_post(out, lang=lang, recent=recent, terms=term_list, business=tenant.name, services=kb.get("services")) if out else None
        return bad, qa

    def clean(x: str) -> str:
        return x.strip().strip('"').strip()

    out = clean(provider.generate(SYSTEM, user, max_tokens=420, temperature=0.8))
    bad, qa = judge(out)
    if bad or (qa and qa.retry_reasons):
        first, first_qa = out, qa
        why = [b.message for b in bad] + (qa.retry_reasons if qa else [])
        out = clean(provider.generate(SYSTEM, user + "\n\nYour previous draft was rejected because: " + " ".join(why) + "\nWrite a new post that fixes all of this.", max_tokens=420, temperature=0.5))
        bad, qa = judge(out)
        if bad:
            raise AIUnavailable("The post draft broke a safety rule twice, so it was not shown", code="rejected")
        if first_qa is not None and qa is not None and first_qa.score > qa.score and not judge(first)[0]:
            out, qa = first, first_qa
    if not (SUMMARY_MIN <= len(out) <= SUMMARY_MAX):
        raise AIUnavailable("The draft didn't meet our quality checks")
    return out, qa, ptype


def draft_post(provider: LLMProvider, tenant: Tenant, kb: dict, *, topic: str | None = None, language: str | None = None, avoid: list[str] | None = None,
               terms: str | None = None, intel: dict | None = None, post_type: str | None = None) -> tuple[str, list[dict]]:
    """AI post text grounded in the knowledge base. Returns (text, []) or raises AIUnavailable(code="rejected") after one retry."""
    text, _, _ = draft_post_scored(provider, tenant, kb, topic=topic, language=language, avoid=avoid, terms=terms, intel=intel, post_type=post_type)
    return text, []


IDEAS_SYSTEM = SYSTEM.split("OUTPUT:")[0].replace("You write one Google Post for the owner to approve.", "You propose several different Google Post concepts for the owner to choose from.") + """
OUTPUT: a JSON array only, no prose. Each element: {"type": one of the allowed post types, "title": 3-6 words, "text": the full post, "image": one sentence describing a REAL photo the owner could take
at their premises (never stock imagery, never a generated picture of the premises, team or results), "why": one sentence on the business purpose of this post}.
The concepts must be genuinely different: different types, different angles, different first words. Not the same paragraph reworded."""


def post_ideas(provider: LLMProvider, tenant: Tenant, kb: dict, intel: dict | None, *, n: int = 3, language: str | None = None, terms: str | None = None) -> list[dict]:
    """Several distinct, checked post concepts in ONE model call. Concepts that break a safety rule, repeat a recent post, or duplicate each other are dropped.
    Returns at least 1 concept or raises AIUnavailable. Nothing is saved; the owner picks one and it becomes an ordinary draft."""
    from app.services.ai.structured import generate_json
    lang = language or tenant.language or "en"
    if lang not in craft.LANGUAGE_STYLE:
        lang = "en"
    n = max(2, min(5, n))
    recent_types = (intel or {}).get("recent_post_types") or []
    types: list[str] = []
    for i in range(n * 2):
        t = craft.pick_post_type(kb, day=utcnow().timetuple().tm_yday + i, recent_types=recent_types + types)
        if t not in types:
            types.append(t)
        if len(types) == n:
            break
    base, _ = build_prompt(tenant, kb, lang=lang, post_type=types[0], topic=None, avoid=None, terms=terms, intel=intel)
    base = base.split("POST TYPE:")[0]
    brief = "\n".join(f"- {t}: {craft.POST_TYPES[t]['brief']}" for t in types)
    user = base + f"\n\nPropose {len(types)} concepts, one for each of these types:\n{brief}\nUse each type once, in this order."
    data = generate_json(provider, IDEAS_SYSTEM, user, max_tokens=1500, temperature=0.8)
    items = data.get("ideas") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise AIUnavailable("AI did not return a list of ideas", code="bad_response")
    recent = list(dict.fromkeys((intel or {}).get("recent_posts") or []))
    out, kept = [], []
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("text"), str):
            continue
        text = it["text"].strip().strip('"')
        if not (SUMMARY_MIN <= len(text) <= SUMMARY_MAX) or check_text(text, kb=kb, kind="post"):
            continue
        if any(quality.similarity(text, k) >= 0.3 for k in kept):
            continue  # a variation of one already chosen
        qa = quality.assess_post(text, lang=lang, recent=recent, business=tenant.name, services=kb.get("services"))
        out.append({"type": it.get("type") if it.get("type") in craft.POST_TYPES else craft.classify_post(text), "title": str(it.get("title") or "")[:60], "text": text,
                    "image": str(it.get("image") or "")[:300] or None, "why": str(it.get("why") or "")[:240] or None, "quality": qa.score, "notes": [i.message for i in qa.issues][:3]})
        kept.append(text)
    if not out:
        raise AIUnavailable("None of the proposed ideas passed our checks", code="rejected")
    return out


VISUAL_SYSTEM = """You suggest ONE photo a small business owner could take themselves to go with a Google post.
One sentence, plain words, something real at their premises (no stock imagery, no people's faces without consent, no text-heavy graphics).
Output only the sentence."""


def visual_hint(provider: LLMProvider, post_text: str, category: str | None) -> str | None:
    """A short, practical photo idea for the post (text only; nothing is generated or uploaded). None if the AI had nothing usable."""
    try:
        out = provider.generate(VISUAL_SYSTEM, f"Business category: {category or 'local business'}\nPost:\n{post_text}", max_tokens=80, temperature=0.5).strip().strip('"')
    except AIUnavailable:
        return None
    return out[:300] if 10 <= len(out) <= 300 else None


def validate_content(post: ScheduledPost, kb: dict) -> list[dict]:
    """Safety findings for a post the owner is about to approve (also applies to hand-written and edited text)."""
    return [v.as_dict() for v in check_text(post.summary, kb=kb, kind="post")]


TOPIC_TYPES = ("STANDARD", "OFFER", "EVENT")


def topic_problems(post: ScheduledPost) -> list[str]:
    """Google's own rules for OFFER and EVENT posts, checked before a person is asked to approve (so approval is never wasted)."""
    if post.topic_type not in TOPIC_TYPES:
        return ["Unknown post type."]
    if post.topic_type == "STANDARD":
        return []
    out = []
    if not (post.event_title or "").strip():
        out.append(f"An {post.topic_type.lower()} needs a title.")
    if not post.event_start or not post.event_end:
        out.append(f"An {post.topic_type.lower()} needs a start and an end date and time.")
    elif post.event_end <= post.event_start:
        out.append("The end must be after the start.")
    if post.topic_type == "OFFER" and post.offer_url and not post.offer_url.startswith("https://"):
        out.append("The offer link must start with https://")
    return out


def approve(post: ScheduledPost, *, user_id: uuid.UUID, when: datetime | None) -> None:
    """Owner approval. `when=None` means publish as soon as the scheduler runs; otherwise at that time (must be in the future)."""
    if post.status != "awaiting_approval":
        raise PostError("Only a post that is awaiting approval can be approved.")
    if problems := topic_problems(post):
        raise PostError(" ".join(problems), status=422)
    now = utcnow()
    if when is not None and when <= now + timedelta(seconds=30):
        when = None
    move(post, "approved")
    post.approved_by, post.approved_at = user_id, now
    move(post, "scheduled")
    post.scheduled_for = when or now
    post.next_attempt_at, post.failure_reason, post.attempts = None, None, 0
    post.first_attempt_at = post.publishing_started_at = post.publish_token = None  # a fresh approval is a fresh publish lifecycle


def retry(post: ScheduledPost) -> None:
    if post.status != "failed":
        raise PostError("Only a failed post can be retried.")
    move(post, "scheduled")
    post.scheduled_for = post.next_attempt_at = utcnow()
    post.failure_reason, post.attempts = None, 0
    # first_attempt_at is KEPT on purpose: an earlier attempt may have reached Google, so the next publish looks for the post before creating one.


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


RECONCILE_SLACK = timedelta(minutes=5)  # clock drift allowed between our first attempt and the post's createTime on Google
STUCK_AFTER = timedelta(minutes=10)  # a post that has been "publishing" this long was left behind by a crash or restart


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def _parse_ts(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
    except ValueError:
        return None


def find_on_google(db: Session, post: ScheduledPost, google_posts: list[dict]) -> dict | None:
    """The post, if it is already on Google. Google's localPosts.create has no idempotency key, so this is the only duplicate guard: the same text
    (whitespace and case ignored), created no earlier than our first attempt, and not already claimed by another FlowQR post at this location.
    A Google post that is REJECTED never counts as published."""
    if post.first_attempt_at is None:
        return None
    since = post.first_attempt_at - RECONCILE_SLACK
    claimed = set(db.scalars(select(ScheduledPost.google_post_name).where(
        ScheduledPost.google_location_id == post.google_location_id, ScheduledPost.google_post_name.is_not(None), ScheduledPost.id != post.id)))
    want = _norm(post.summary)
    matches = []
    for gp in google_posts:
        created = _parse_ts(gp.get("created_at"))
        if (gp.get("name") and gp["name"] not in claimed and gp.get("state") != "REJECTED" and _norm(gp.get("summary")) == want
                and created is not None and created >= since):
            matches.append((created, gp))
    return min(matches, key=lambda m: m[0])[1] if matches else None


def _mark_published(post: ScheduledPost, name: str | None, when: datetime | None = None) -> None:
    post.status, post.published_at, post.google_post_name = "published", when or utcnow(), name
    post.failure_reason, post.next_attempt_at = None, None


def publish(db: Session, post: ScheduledPost, *, provider=None, now: datetime | None = None) -> str:
    """Try to publish one due post. Returns published | retry | failed | skipped. Crash-safe in three steps:

    1. CLAIM: the post becomes `publishing` (with the attempt count, start time and a token) and that is COMMITTED before Google is called. Another
       worker can no longer pick it up (the due query only takes `scheduled`), and a crash after this point leaves a visible `publishing` row that
       `recover_stuck` resolves by asking Google, never by blindly sending again.
    2. LOOK BEFORE CREATE: if any earlier attempt could have reached Google (`first_attempt_at` is set), the location's posts are read first; a post
       with the same text created since our first attempt is adopted instead of being created again.
    3. RECORD: `published` only after Google returned the post; every failure keeps Google's diagnostic.
    The caller commits after this returns (the claim commit above is the only one inside)."""
    now = now or utcnow()
    gloc = db.get(GoogleLocation, post.google_location_id)
    conn = db.get(GoogleConnection, gloc.connection_id) if gloc else None
    if gloc is None or not gloc.selected or conn is None or conn.status != GoogleConnectionStatus.active:
        post.status, post.failure_reason = "failed", "This location is no longer connected to Google. Reconnect it, then retry."
        return "failed"
    if not hit(f"gbp-edit:{gloc.id}", 10, 60):  # Google allows 10 edits per minute per location
        post.next_attempt_at = now + timedelta(seconds=65)
        return "skipped"
    earlier_attempt = post.first_attempt_at is not None
    move(post, "publishing")  # raises PostError unless the post is publishable, so a second publish of the same row cannot start
    post.attempts += 1
    post.publishing_started_at, post.publish_token = now, uuid.uuid4()
    post.first_attempt_at = post.first_attempt_at or now
    db.commit()  # the atomic claim: durable before any external call
    try:
        provider = provider or g.get_google_provider()
        token = get_access_token(db, conn, provider, gloc=gloc, action="publish_posts")
        if earlier_attempt:
            existing = find_on_google(db, post, provider.list_posts(token, gloc.google_account_name, gloc.google_location_name))
            if existing:
                _mark_published(post, existing["name"], _parse_ts(existing.get("created_at")))
                log.info("post %s was already on Google (%s); adopted, not created again", post.id, existing["name"])
                return "published"
        from zoneinfo import ZoneInfo
        tz = ZoneInfo((db.get(Tenant, post.tenant_id).timezone or "Asia/Kolkata"))
        local = lambda d: d.astimezone(tz).replace(tzinfo=None) if d else None  # noqa: E731 - Google's event times are local wall-clock times
        created = provider.create_post(token, gloc.google_account_name, gloc.google_location_name,
                                       {"summary": post.summary, "language": post.language, "cta_type": post.cta_type, "cta_url": post.cta_url, "photo_url": post.photo_url,
                                        "topic_type": post.topic_type or "STANDARD", "event_title": post.event_title, "event_start": local(post.event_start),
                                        "event_end": local(post.event_end), "offer_coupon": post.offer_coupon, "offer_url": post.offer_url, "offer_terms": post.offer_terms})
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
    _mark_published(post, (created or {}).get("name"))
    return "published"


def recover_stuck(db: Session, *, provider=None, now: datetime | None = None, limit: int = 20) -> dict:
    """Crash recovery: posts left in `publishing` (a worker or API process died between the claim and the result).

    For each one Google is asked what is really there. Found -> adopted as published (verified by Google, not assumed). Not found -> sent back to
    `scheduled` so it is created exactly once (or `failed` after MAX_ATTEMPTS). If Google cannot be asked right now the post is left alone and looked
    at again on the next run: it is never re-sent on a guess. One post per transaction; row-locked so overlapping runs cannot both act."""
    from app.services.audit import audit

    now = now or utcnow()
    out = {"adopted": 0, "requeued": 0, "failed": 0, "deferred": 0}
    ids = list(db.scalars(select(ScheduledPost.id).where(ScheduledPost.status == "publishing", ScheduledPost.publishing_started_at < now - STUCK_AFTER).limit(limit)))
    for pid in ids:
        post = db.scalar(select(ScheduledPost).where(ScheduledPost.id == pid, ScheduledPost.status == "publishing").with_for_update(skip_locked=True))
        if post is None:
            continue
        gloc = db.get(GoogleLocation, post.google_location_id)
        conn = db.get(GoogleConnection, gloc.connection_id) if gloc else None
        if gloc is None or conn is None or conn.status != GoogleConnectionStatus.active:
            post.status, post.failure_reason = "failed", "FlowQR lost contact while publishing and this location is no longer connected to Google. Reconnect it, then retry."
            out["failed"] += 1
            audit(db, action="post.recover_failed", tenant_id=post.tenant_id, entity_type="scheduled_post", entity_id=post.id, meta={"reason": "location disconnected"})
            db.commit()
            continue
        try:
            provider = provider or g.get_google_provider()
            token = get_access_token(db, conn, provider, gloc=gloc)
            found = find_on_google(db, post, provider.list_posts(token, gloc.google_account_name, gloc.google_location_name))
        except Exception as exc:  # noqa: BLE001 - cannot ask Google now: leave it, try again later
            log.warning("recover_stuck: could not read Google for post %s: %s", pid, exc)
            out["deferred"] += 1
            db.rollback()
            continue
        if found:
            _mark_published(post, found["name"], _parse_ts(found.get("created_at")))
            out["adopted"] += 1
            outcome = "adopted"
        elif post.attempts >= MAX_ATTEMPTS:
            post.status = "failed"
            post.failure_reason = "FlowQR lost contact with Google while publishing and the post was not found on Google after several attempts. Retry it if it is still relevant."
            out["failed"] += 1
            outcome = "failed"
        else:
            post.status, post.next_attempt_at = "scheduled", now
            post.failure_reason = "FlowQR lost contact while sending this post; Google does not have it, so it will be sent again."
            out["requeued"] += 1
            outcome = "requeued"
        audit(db, action=f"post.recover_{outcome}", tenant_id=post.tenant_id, entity_type="scheduled_post", entity_id=post.id,
              meta={"attempts": post.attempts, "google_post": post.google_post_name})
        db.commit()
    return out


def due(db: Session, limit: int = 50, now: datetime | None = None, exclude=()) -> list[ScheduledPost]:
    now = now or utcnow()
    q = (select(ScheduledPost).where(ScheduledPost.status == "scheduled", ScheduledPost.scheduled_for <= now,
                                     (ScheduledPost.next_attempt_at.is_(None)) | (ScheduledPost.next_attempt_at <= now)))
    if exclude:
        q = q.where(ScheduledPost.id.not_in(list(exclude)))
    return list(db.scalars(q.order_by(ScheduledPost.scheduled_for).limit(limit).with_for_update(skip_locked=True)))
